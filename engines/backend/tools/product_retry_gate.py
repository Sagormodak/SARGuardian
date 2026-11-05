#!/usr/bin/env python3
"""Receipt-backed retry planning and pre-reassembly verification for SARGuardian."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.resume_streamed_run import (  # noqa: E402
    _valid_cleanup,
    _valid_granule,
    read_json,
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED path={path}")
    return value


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    products = manifest.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("MANIFEST_PRODUCTS_MISSING")
    ids = [str(row.get("id", "")) for row in products if isinstance(row, dict)]
    if len(ids) != len(products) or any(not item for item in ids):
        raise ValueError("MANIFEST_PRODUCT_ID_MISSING")
    if len(ids) != len(set(ids)):
        raise ValueError("MANIFEST_PRODUCT_IDS_NOT_UNIQUE")
    if manifest.get("run_profile") == "full-source-baseline":
        counts = {
            family: sum(1 for row in products if row.get("product_type") == family)
            for family in ("GUNW", "GOFF")
        }
        if len(products) != 33 or counts != {"GUNW": 15, "GOFF": 18}:
            raise ValueError(
                f"FULL_BASELINE_PRODUCT_COUNTS_INVALID total={len(products)} counts={counts}"
            )
    return products


def _product_pair_status(
    product: dict[str, Any],
    manifest: dict[str, Any],
    granule_root: Path,
    cleanup_root: Path,
) -> tuple[bool, str]:
    product_id = str(product["id"])
    granule_dir = granule_root / f"sarguardian-granule-{product_id}"
    cleanup_dir = cleanup_root / f"sarguardian-cleanup-{product_id}"

    good, reason = _valid_granule(granule_dir, product, manifest)
    if not good:
        return False, f"granule:{reason}"

    metadata = read_json(granule_dir / "product-processing.json") or {}
    remote_folder = str(metadata.get("drive_remote_folder_id") or "")
    if not remote_folder:
        return False, "granule:remote_folder_id_missing"

    metadata_upload = read_json(granule_dir / "drive-metadata-upload-receipt.json")
    if not metadata_upload:
        return False, "granule:metadata_upload_receipt_missing_or_invalid"
    if metadata_upload.get("remote_verification") != "PASS":
        return False, "granule:metadata_upload_receipt_not_verified"
    if metadata_upload.get("remote_folder_id") != remote_folder:
        return False, "granule:metadata_upload_folder_mismatch"
    metadata_files = {
        str(item.get("name", ""))
        for item in metadata_upload.get("files", [])
        if isinstance(item, dict)
    }
    if not {"product-processing.json", "drive-retention-receipt.json"}.issubset(metadata_files):
        return False, "granule:required_metadata_files_not_remotely_verified"

    good, reason = _valid_cleanup(cleanup_dir, product, manifest, remote_folder)
    if not good:
        return False, f"cleanup:{reason}"
    return True, "all_product_and_cleanup_receipts_verified"


def build_retry_plan(
    manifest: dict[str, Any],
    requested_products: list[dict[str, Any]],
    granule_root: Path,
    cleanup_root: Path,
) -> dict[str, Any]:
    manifest_products = _validate_manifest(manifest)
    by_id = {str(row["id"]): row for row in manifest_products}
    requested_ids = [str(row.get("id", "")) for row in requested_products]
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("RETRY_MATRIX_PRODUCT_IDS_NOT_UNIQUE")
    if any(not product_id or product_id not in by_id for product_id in requested_ids):
        raise ValueError("RETRY_MATRIX_CONTAINS_UNKNOWN_PRODUCT")
    retry_products: list[dict[str, Any]] = []
    decisions: list[dict[str, str]] = []

    for requested in requested_products:
        product_id = str(requested["id"])
        product = by_id[product_id]
        for key in ("granule_name", "product_type", "maturity"):
            if str(requested.get(key, "")).upper() != str(product.get(key, "")).upper():
                raise ValueError(f"RETRY_MATRIX_PRODUCT_MISMATCH id={product_id} field={key}")
        good, reason = _product_pair_status(product, manifest, granule_root, cleanup_root)
        if good:
            decisions.append({"product_id": product_id, "decision": "keep", "reason": reason})
        else:
            # Preserve the exact matrix row from the original manifest output.
            retry_products.append(dict(requested))
            decisions.append({"product_id": product_id, "decision": "retry", "reason": reason})

    return {
        "schema_version": "sarguardian-preassembly-retry-plan/1.0",
        "run_id": manifest.get("run_id"),
        "run_profile": manifest.get("run_profile"),
        "products_checked": len(requested_products),
        "products_verified": len(requested_products) - len(retry_products),
        "products_to_retry": len(retry_products),
        "retry_product_ids": [str(row["id"]) for row in retry_products],
        "retry_products": retry_products,
        "decisions": decisions,
    }


def verify_manifest_checkpoints(
    manifest: dict[str, Any],
    current_granules: Path,
    current_cleanups: Path,
    previous_granules: Path,
    previous_cleanups: Path,
) -> dict[str, Any]:
    products = _validate_manifest(manifest)
    results: list[dict[str, str]] = []
    current_verified = 0
    resume_verified = 0

    for product in products:
        product_id = str(product["id"])
        chosen_source = ""
        reason = "no_complete_receipt_pair_found"
        # A granule and its cleanup receipt must come from the same attempt source.
        for source, granules, cleanups in (
            ("current-run", current_granules, current_cleanups),
            ("resume-source", previous_granules, previous_cleanups),
        ):
            good, candidate_reason = _product_pair_status(product, manifest, granules, cleanups)
            if good:
                chosen_source = source
                reason = candidate_reason
                if source == "current-run":
                    current_verified += 1
                else:
                    resume_verified += 1
                break
            reason = f"{source}:{candidate_reason}"

        results.append({
            "product_id": product_id,
            "status": "PASS" if chosen_source else "FAIL",
            "checkpoint_source": chosen_source or "missing_or_invalid",
            "reason": reason,
        })

    missing = [row["product_id"] for row in results if row["status"] != "PASS"]
    return {
        "schema_version": "sarguardian-preassembly-verification/1.0",
        "run_id": manifest.get("run_id"),
        "run_profile": manifest.get("run_profile"),
        "expected_products": len(products),
        "verified_products": len(products) - len(missing),
        "current_run_checkpoints": current_verified,
        "resume_source_checkpoints": resume_verified,
        "missing_or_invalid_product_ids": missing,
        "status": "PASS" if not missing and len(results) == len(products) else "FAIL",
        "products": results,
    }


def _write_github_output(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan-retries")
    plan.add_argument("--manifest", required=True, type=Path)
    plan.add_argument("--expected-products-json", required=True, type=Path)
    plan.add_argument("--granule-root", required=True, type=Path)
    plan.add_argument("--cleanup-root", required=True, type=Path)
    plan.add_argument("--out", required=True, type=Path)

    verify = sub.add_parser("verify")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--current-granule-root", required=True, type=Path)
    verify.add_argument("--current-cleanup-root", required=True, type=Path)
    verify.add_argument("--previous-granule-root", required=True, type=Path)
    verify.add_argument("--previous-cleanup-root", required=True, type=Path)
    verify.add_argument("--out", required=True, type=Path)

    args = parser.parse_args()
    try:
        manifest = _load_json(args.manifest)
        if args.command == "plan-retries":
            expected = json.loads(args.expected_products_json.read_text(encoding="utf-8"))
            if not isinstance(expected, list) or any(not isinstance(row, dict) for row in expected):
                raise ValueError("EXPECTED_PRODUCTS_MATRIX_INVALID")
            report = build_retry_plan(
                manifest, expected, args.granule_root, args.cleanup_root
            )
            compact_matrix = json.dumps(report["retry_products"], separators=(",", ":"))
            _write_github_output({
                "retry_matrix": compact_matrix,
                "retry_count": str(report["products_to_retry"]),
                "retry_ids": ",".join(report["retry_product_ids"]),
            })
            print(f"PRODUCT_PRE_REASSEMBLY_CHECK={'PASS' if not report['products_to_retry'] else 'RETRY_REQUIRED'}")
            print(f"PRODUCTS_CHECKED_BEFORE_REASSEMBLY={report['products_checked']}")
            print(f"PRODUCTS_VERIFIED_BEFORE_REASSEMBLY={report['products_verified']}")
            print(f"PRODUCTS_SELECTED_FOR_RETRY={report['products_to_retry']}")
            print(f"PRODUCT_RETRY_IDS={','.join(report['retry_product_ids']) or 'none'}")
            exit_code = 0
        else:
            report = verify_manifest_checkpoints(
                manifest, args.current_granule_root, args.current_cleanup_root,
                args.previous_granule_root, args.previous_cleanup_root,
            )
            _write_github_output({
                "status": report["status"],
                "expected_count": str(report["expected_products"]),
                "verified_count": str(report["verified_products"]),
            })
            print(f"PREASSEMBLY_VERIFICATION_STATUS={report['status']}")
            print(f"PREASSEMBLY_PRODUCTS_EXPECTED={report['expected_products']}")
            print(f"PREASSEMBLY_PRODUCTS_VERIFIED={report['verified_products']}")
            print(f"PREASSEMBLY_CURRENT_RUN_CHECKPOINTS={report['current_run_checkpoints']}")
            print(f"PREASSEMBLY_RESUME_SOURCE_CHECKPOINTS={report['resume_source_checkpoints']}")
            print(
                "PREASSEMBLY_INCOMPLETE_PRODUCT_IDS="
                + (",".join(report["missing_or_invalid_product_ids"]) or "none")
            )
            exit_code = 0 if report["status"] == "PASS" else 1

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return exit_code
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR=PRODUCT_RETRY_GATE_FAILED type={type(exc).__name__} detail={str(exc)[:300]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
