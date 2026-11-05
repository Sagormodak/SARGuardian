#!/usr/bin/env python3
"""Validate and merge resumable per-product checkpoints for SARGuardian batches."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

GRANULE_REQUIRED = ("product-processing.json", "derived-output-validation.json", "drive-retention-receipt.json")
CLEANUP_REQUIRED = ("local-cleanup-receipt.json", "drive-cleanup-upload-receipt.json")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _safe_child(root: Path, relative: str) -> Path | None:
    try:
        candidate = (root / relative).resolve()
        return candidate if candidate.is_relative_to(root.resolve()) else None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _identity(product: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(product.get("id", "")), str(product.get("granule_name", "")),
            str(product.get("product_type", "")), str(product.get("maturity", "")).upper())


def validate_resume_compatibility(current: dict[str, Any], previous: dict[str, Any]) -> None:
    """Reject reuse across AOIs, science revisions, retention modes or product baselines."""
    if current.get("run_profile") != "full-source-baseline":
        raise ValueError("RESUME_REQUIRES_FULL_SOURCE_BASELINE")
    if previous.get("run_profile") != "full-source-baseline":
        raise ValueError("RESUME_SOURCE_RUN_IS_NOT_FULL_BASELINE")
    for key in ("aoi", "science_commit", "retention_profile", "time_window"):
        if current.get(key) != previous.get(key):
            raise ValueError(f"RESUME_MANIFEST_MISMATCH field={key}")
    now, old = current.get("products"), previous.get("products")
    if not isinstance(now, list) or not isinstance(old, list):
        raise ValueError("RESUME_MANIFEST_PRODUCTS_INVALID")
    if [_identity(p) for p in now] != [_identity(p) for p in old]:
        raise ValueError("RESUME_BASELINE_PRODUCT_IDENTITIES_CHANGED")
    if not now:
        raise ValueError("RESUME_BASELINE_PRODUCT_SET_EMPTY")


def _valid_granule(path: Path, product: dict[str, Any], manifest: dict[str, Any]) -> tuple[bool, str]:
    meta = read_json(path / "product-processing.json")
    validation = read_json(path / "derived-output-validation.json")
    receipt = read_json(path / "drive-retention-receipt.json")
    if not meta or not validation or not receipt:
        return False, "required_product_receipt_missing_or_invalid"
    expected = {
        "id": product.get("id"), "granule_name": product.get("granule_name"),
        "product_type": product.get("product_type"), "maturity": str(product.get("maturity", "")).upper(),
        "aoi": manifest.get("aoi"), "science_commit": manifest.get("science_commit"),
        "retention_profile": manifest.get("retention_profile"),
        "derived_output_validation_status": "PASS", "drive_remote_verification": "PASS",
    }
    for key, want in expected.items():
        actual = meta.get(key)
        if key == "maturity" and actual is not None:
            actual = str(actual).upper()
        if actual != want:
            return False, f"product_metadata_mismatch:{key}"
    if validation.get("status") != "PASS":
        return False, "derived_validation_not_pass"
    if receipt.get("remote_verification") != "PASS":
        return False, "remote_retention_not_verified"
    folder = receipt.get("remote_folder_id")
    if not folder or folder != meta.get("drive_remote_folder_id"):
        return False, "remote_retention_folder_mismatch"
    source_sha = str(meta.get("source_file_sha256", ""))
    if len(source_sha) != 64 or any(c not in "0123456789abcdef" for c in source_sha.lower()):
        return False, "source_sha256_missing_or_invalid"
    try:
        if int(meta.get("source_file_bytes", 0)) <= 0:
            return False, "source_size_missing_or_invalid"
    except (TypeError, ValueError, OverflowError):
        return False, "source_size_missing_or_invalid"

    stats = _safe_child(path, str(meta.get("stats_csv") or ""))
    if stats is None or not stats.is_file() or stats.stat().st_size == 0:
        return False, "stats_csv_missing"
    required_remote = {
        "source-inventory.json", "preflight-report.json", "derived-output-validation.json",
        "download-manifest.json", stats.name,
    }
    exports = meta.get("export_files")
    if not isinstance(exports, list) or not exports:
        return False, "exports_missing_from_metadata"
    for rel in exports:
        export_path = _safe_child(path, str(rel))
        if export_path is None or not export_path.is_file() or export_path.stat().st_size == 0:
            return False, "export_missing"
        required_remote.add(export_path.name)
    for name in ("source-inventory.json", "preflight-report.json", "download-manifest.json"):
        if not (path / name).is_file():
            return False, f"local_{name}_missing"
    uploaded = {str(row.get("name", "")) for row in receipt.get("files", []) if isinstance(row, dict)}
    if not required_remote.issubset(uploaded):
        return False, "required_remote_derived_outputs_missing"
    if manifest.get("retention_profile") == "full-lossless":
        eq = read_json(path / "reader-equivalence.json")
        if not eq or eq.get("status") not in {"PASS", "PASS_NO_VALID_AOI_PIXELS"}:
            return False, "full_lossless_reader_equivalence_missing"
        if len([name for name in uploaded if name.endswith(".science.h5")]) != 1:
            return False, "full_lossless_archive_receipt_missing"
    elif meta.get("retained_archive") is not None:
        return False, "unexpected_archive_in_derived_only_checkpoint"
    return True, "reusable"


def _valid_cleanup(path: Path, product: dict[str, Any], manifest: dict[str, Any], folder: str) -> tuple[bool, str]:
    receipt = read_json(path / "local-cleanup-receipt.json")
    upload = read_json(path / "drive-cleanup-upload-receipt.json")
    if not receipt or not upload:
        return False, "required_cleanup_receipt_missing_or_invalid"
    expected = {
        "product_id": product.get("id"), "granule_name": product.get("granule_name"),
        "aoi": manifest.get("aoi"), "science_commit": manifest.get("science_commit"),
        "retention_profile": manifest.get("retention_profile"),
        "remote_retention_verification": "PASS", "remote_retention_folder_id": folder,
        "runner_raw_hdf5_deleted": True,
    }
    for key, want in expected.items():
        if receipt.get(key) != want:
            return False, f"cleanup_receipt_mismatch:{key}"
    if upload.get("remote_verification") != "PASS":
        return False, "cleanup_receipt_upload_not_verified"
    names = {str(row.get("name", "")) for row in upload.get("files", []) if isinstance(row, dict)}
    if "local-cleanup-receipt.json" not in names:
        return False, "cleanup_receipt_not_present_in_remote_upload_receipt"
    return True, "reusable"


def plan_resume(current: dict[str, Any], previous: dict[str, Any],
                previous_granules: Path, previous_cleanups: Path) -> dict[str, Any]:
    validate_resume_compatibility(current, previous)
    reused: list[str] = []
    to_process: list[dict[str, Any]] = []
    decisions: list[dict[str, str]] = []
    for product in current["products"]:
        pid = str(product["id"])
        gdir = previous_granules / f"sarguardian-granule-{pid}"
        cdir = previous_cleanups / f"sarguardian-cleanup-{pid}"
        good, reason = _valid_granule(gdir, product, current)
        if good:
            meta = read_json(gdir / "product-processing.json") or {}
            good, reason = _valid_cleanup(cdir, product, current, str(meta.get("drive_remote_folder_id", "")))
        if good:
            reused.append(pid)
            decisions.append({"product_id": pid, "decision": "reuse", "reason": "all_gates_verified"})
        else:
            to_process.append(product)
            decisions.append({"product_id": pid, "decision": "process", "reason": reason})
    return {"reused_product_ids": reused, "products_to_process": to_process,
            "products_reused": len(reused), "products_to_process_count": len(to_process),
            "decisions": decisions}


def _complete(path: Path, kind: str) -> bool:
    """Return true only for a receipt-backed checkpoint, not just files with matching names."""
    required = GRANULE_REQUIRED if kind == "granule" else CLEANUP_REQUIRED
    if not path.is_dir() or not all((path / name).is_file() for name in required):
        return False
    if kind == "granule":
        meta = read_json(path / "product-processing.json")
        validation = read_json(path / "derived-output-validation.json")
        retention = read_json(path / "drive-retention-receipt.json")
        if not meta or not validation or not retention:
            return False
        source_sha = str(meta.get("source_file_sha256", ""))
        try:
            source_bytes = int(meta.get("source_file_bytes", 0))
        except (TypeError, ValueError, OverflowError):
            return False
        return (
            validation.get("status") == "PASS"
            and meta.get("derived_output_validation_status") == "PASS"
            and meta.get("drive_remote_verification") == "PASS"
            and retention.get("remote_verification") == "PASS"
            and bool(retention.get("remote_folder_id"))
            and retention.get("remote_folder_id") == meta.get("drive_remote_folder_id")
            and len(source_sha) == 64
            and source_bytes > 0
        )
    cleanup = read_json(path / "local-cleanup-receipt.json")
    upload = read_json(path / "drive-cleanup-upload-receipt.json")
    if not cleanup or not upload:
        return False
    uploaded_names = {
        str(item.get("name", ""))
        for item in upload.get("files", [])
        if isinstance(item, dict)
    }
    return (
        cleanup.get("runner_raw_hdf5_deleted") is True
        and cleanup.get("remote_retention_verification") == "PASS"
        and bool(cleanup.get("remote_retention_folder_id"))
        and upload.get("remote_verification") == "PASS"
        and "local-cleanup-receipt.json" in uploaded_names
    )


def merge_artifact_roots(previous: Path, current: Path, output: Path, kind: str) -> dict[str, int]:
    """Prefer complete current artifacts; do not replace complete checkpoints with failed diagnostics."""
    if kind not in {"granule", "cleanup"}:
        raise ValueError("ARTIFACT_KIND_MUST_BE_GRANULE_OR_CLEANUP")
    prefix = "sarguardian-granule-" if kind == "granule" else "sarguardian-cleanup-"
    output.mkdir(parents=True, exist_ok=True)
    copied = kept = incomplete = 0
    for root in (previous, current):
        if not root.is_dir():
            continue
        for source in sorted(root.iterdir()):
            if not source.is_dir() or not source.name.startswith(prefix):
                continue
            target = output / source.name
            source_complete, target_complete = _complete(source, kind), _complete(target, kind)
            if target_complete and not source_complete:
                kept += 1
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            copied += 1
            incomplete += int(not source_complete)
    return {"copied": copied, "complete_kept_over_incomplete": kept, "incomplete": incomplete}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--kind", required=True, choices=("granule", "cleanup"))
    merge.add_argument("--previous-root", required=True, type=Path)
    merge.add_argument("--current-root", required=True, type=Path)
    merge.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    result = merge_artifact_roots(args.previous_root, args.current_root, args.output_root, args.kind)
    print(f"RESUME_ARTIFACT_MERGE kind={args.kind} copied={result['copied']} "
          f"complete_preserved={result['complete_kept_over_incomplete']} incomplete={result['incomplete']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
