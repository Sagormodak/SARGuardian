#!/usr/bin/env python3
"""Aggregate single-granule SARGuardian reader outputs and audit batch equivalence.

The workflow creates one artifact per raw product. This tool reassembles only
the small derived outputs, checks them against the pinned repository's committed
batch baselines, then runs the downstream AOI-source analysis from those outputs.
It never needs the original raw HDF5 files in the aggregation job.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

# This script is also invoked directly by the workflow. Ensure imports from the
# repository's tools namespace work when cwd and sys.path[0] are tools/ or an
# unrelated directory, not the repository root.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.run_pinned_science_suite import run_suite

NUMERIC_REL_TOL = 1e-5
NUMERIC_ABS_TOL = 1e-3
IGNORE_STAT_FIELDS = {"export_mb"}  # file sizes can vary slightly across GDAL builds
BASELINE_DOWNSTREAM = [
    "ts_goff_source.csv",
    "ts_goff_cand4_common.csv",
    "troposphere_gunw_source.csv",
    "troposphere_goff_source.csv",
    "local_floor_candidates.csv",
    "local_floor_phase_candidates.csv",
    "local_floor_cand4.csv",
    "local_floor_cand4_as_floors.csv",
    "common_ref_summer.csv",
    "bound_source.csv",
    # Deterministic model outputs and the optical candidate classification are
    # recalculated from the unchanged pinned source scripts and compared.
    "detectability.csv",
    "detectability_fixed_gate.csv",
    "scar_candidates_source.csv",
]

AUXILIARY_JSON_REFERENCES = [
    "dam_sites_source.geojson",
    "dam_sites_langtang.geojson",
    "dam_sites_lhende.geojson",
    "dam_sites_blatten.geojson",
]


def read_product_diagnostic_context(artifact_dir: Path) -> dict[str, Any]:
    """Expose the relevant sanitized per-product diagnostics when primary metadata is absent."""
    path = artifact_dir / "product-run-diagnostics.json"
    if not path.is_file():
        return {"diagnostics_artifact_present": False}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "diagnostics_artifact_present": True,
            "diagnostics_parse_error": f"{type(exc).__name__}: {str(exc)[:180]}",
        }
    if not isinstance(record, dict):
        return {
            "diagnostics_artifact_present": True,
            "diagnostics_parse_error": "diagnostics JSON root is not an object",
        }
    outcomes = record.get("step_outcomes")
    lines = record.get("download_diagnostics")
    return {
        "diagnostics_artifact_present": True,
        "diagnostic_step_outcomes": outcomes if isinstance(outcomes, dict) else {},
        "download_error_code": record.get("download_error_code"),
        "download_diagnostics": lines[:16] if isinstance(lines, list) else [],
        "download_manifest_created": record.get("download_manifest_created"),
        "drive_receipt_created": record.get("drive_receipt_created"),
        "raw_hdf5_present_at_diagnostic_time": record.get("raw_hdf5_present_at_diagnostic_time"),
    }


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {path}")
        return list(reader.fieldnames), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, str], fields: list[str]) -> tuple[str, ...]:
    # Each scientific table has a different natural key. Prefer the most
    # specific one so candidate-level rows never collide on their input file.
    candidates = (
        # Determinability sweeps identify an experiment by its input parameters,
        # not by floating-point result columns whose last decimal can vary
        # across supported numerical-library builds.
        ("precursor_days", "revisit_days", "noise_mm", "creep_mm", "gate", "gate_mm_day"),
        ("file", "layer"),
        ("target_id", "file", "window_px", "reading"),
        ("target_id", "file", "window_px"),
        ("target_id", "pair", "window_px"),
        ("geometry", "component", "epoch"),
        ("id",),
        ("file",),
    )
    chosen = next((group for group in candidates if all(k in fields for k in group)), tuple(fields))
    return tuple((row.get(k) or "").strip() for k in chosen)


def value_equal(expected: str, actual: str, field: str) -> bool:
    e, a = (expected or "").strip(), (actual or "").strip()
    if e == a:
        return True
    if field in IGNORE_STAT_FIELDS:
        try:
            return math.isclose(float(e), float(a), rel_tol=0.02, abs_tol=0.05)
        except (ValueError, TypeError):
            return False
    if e.lower() in {"nan", "inf", "-inf"} or a.lower() in {"nan", "inf", "-inf"}:
        return e.lower() == a.lower()
    try:
        ef, af = float(e), float(a)
    except (ValueError, TypeError):
        return False
    return math.isclose(ef, af, rel_tol=NUMERIC_REL_TOL, abs_tol=NUMERIC_ABS_TOL)


def compare_rows(
    expected_rows: list[dict[str, str]],
    actual_rows: list[dict[str, str]],
    fields: list[str],
    *,
    label: str,
    errors: list[dict[str, Any]],
    limit: int = 100,
) -> dict[str, Any]:
    expected_map: dict[tuple[str, ...], dict[str, str]] = {}
    actual_map: dict[tuple[str, ...], dict[str, str]] = {}
    for side, rows, target in (
        ("baseline", expected_rows, expected_map),
        ("streamed", actual_rows, actual_map),
    ):
        for row in rows:
            key = row_key(row, fields)
            if key in target:
                if len(errors) < limit:
                    errors.append({"table": label, "problem": f"duplicate_{side}_key", "key": key})
            target[key] = row
    missing = sorted(set(expected_map) - set(actual_map))
    extra = sorted(set(actual_map) - set(expected_map))
    if missing and len(errors) < limit:
        errors.append({"table": label, "problem": "missing_rows", "keys": missing[:20]})
    if extra and len(errors) < limit:
        errors.append({"table": label, "problem": "unexpected_rows", "keys": extra[:20]})
    field_mismatches = 0
    for key in sorted(set(expected_map) & set(actual_map)):
        er, ar = expected_map[key], actual_map[key]
        for field in fields:
            if field not in er or field not in ar:
                if len(errors) < limit:
                    errors.append({"table": label, "problem": "missing_column_value", "key": key, "field": field})
                field_mismatches += 1
                continue
            if not value_equal(er[field], ar[field], field):
                field_mismatches += 1
                if len(errors) < limit:
                    errors.append({
                        "table": label, "problem": "value_mismatch", "key": key,
                        "field": field, "baseline": er[field], "streamed": ar[field],
                    })
    return {
        "table": label,
        "baseline_rows": len(expected_rows),
        "streamed_rows": len(actual_rows),
        "row_keys_missing": len(missing),
        "row_keys_extra": len(extra),
        "field_mismatches": field_mismatches,
        "status": "PASS" if not missing and not extra and not field_mismatches else "FAIL",
    }


def safe_relative(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes artifact root: {relative}") from exc
    return candidate


def locate_product_artifact(artifact_root: Path, product_id: str) -> Path:
    expected = artifact_root / f"sarguardian-granule-{product_id}"
    if expected.is_dir():
        return expected
    # Keep the lookup strict: never silently choose a similarly named product.
    raise FileNotFoundError(f"Product artifact missing: sarguardian-granule-{product_id}")


def validate_cleanup_evidence(
    manifest: dict[str, Any],
    artifact_root: Path,
    cleanup_artifact_root: Path,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Require policy-aware proof that derived outputs were retained before raw cleanup."""
    expected = len(manifest.get("products", []))
    profile = str(manifest.get("retention_profile", manifest.get("archive_profile", "full-lossless")))
    verified = 0
    for product in manifest.get("products", []):
        pid = str(product.get("id", ""))
        cleanup_dir = cleanup_artifact_root / f"sarguardian-cleanup-{pid}"
        cleanup_path = cleanup_dir / "local-cleanup-receipt.json"
        drive_receipt_path = cleanup_dir / "drive-cleanup-upload-receipt.json"
        processing_path = artifact_root / f"sarguardian-granule-{pid}" / "product-processing.json"
        try:
            receipt = json.loads(cleanup_path.read_text(encoding="utf-8"))
            drive_receipt = json.loads(drive_receipt_path.read_text(encoding="utf-8"))
            meta = json.loads(processing_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({
                "problem": "cleanup_evidence_missing_or_unreadable",
                "id": pid,
                "type": type(exc).__name__,
                "detail": str(exc)[:240],
            })
            continue

        schema = receipt.get("schema_version")
        checks = {
            "schema_version": (schema in {"sarguardian-local-cleanup-receipt/1.0",
                                          "sarguardian-local-cleanup-receipt/1.1"}, True),
            "product_id": (receipt.get("product_id"), pid),
            "product_type": (receipt.get("product_type"), product.get("product_type")),
            "maturity": (receipt.get("maturity"), product.get("maturity")),
            "granule_name": (receipt.get("granule_name"), product.get("granule_name")),
            "aoi": (receipt.get("aoi"), "source"),
            "science_commit": (receipt.get("science_commit"), manifest.get("science_commit")),
            "remote_retention_verification": (receipt.get("remote_retention_verification"), "PASS"),
            "remote_retention_folder_id": (receipt.get("remote_retention_folder_id"), meta.get("drive_remote_folder_id")),
            "source_file_sha256": (receipt.get("source_file_sha256"), meta.get("source_file_sha256")),
            "runner_raw_hdf5_deleted": (receipt.get("runner_raw_hdf5_deleted"), True),
            "runner_archive_deleted": (receipt.get("runner_archive_deleted"), True),
            "retention_profile": (receipt.get("retention_profile", "full-lossless" if schema == "sarguardian-local-cleanup-receipt/1.0" else None), profile),
        }
        mismatches = [
            {"field": field, "expected": want, "actual": actual}
            for field, (actual, want) in checks.items()
            if actual != want
        ]
        retained_name = receipt.get("retained_archive_name")
        retained_sha = receipt.get("retained_archive_sha256")
        meta_archive = Path(str(meta.get("retained_archive") or "")).name if meta.get("retained_archive") else None
        if profile == "full-lossless":
            if not meta_archive or retained_name != meta_archive:
                mismatches.append({"field": "retained_archive_name", "expected": meta_archive, "actual": retained_name})
            if not meta.get("retained_archive_sha256") or retained_sha != meta.get("retained_archive_sha256"):
                mismatches.append({"field": "retained_archive_sha256", "expected": meta.get("retained_archive_sha256"), "actual": retained_sha})
        else:
            if retained_name is not None or retained_sha is not None or meta.get("retained_archive") is not None:
                mismatches.append({"field": "derived_only_must_not_retain_archive",
                                   "expected": None, "actual": {"name": retained_name, "sha256": retained_sha,
                                                                "metadata_path": meta.get("retained_archive")}})

        uploaded_receipts = drive_receipt.get("files", []) if isinstance(drive_receipt, dict) else []
        if drive_receipt.get("remote_verification") != "PASS":
            mismatches.append({
                "field": "cleanup_receipt_remote_verification",
                "expected": "PASS",
                "actual": drive_receipt.get("remote_verification"),
            })
        if not any(row.get("name") == "local-cleanup-receipt.json" for row in uploaded_receipts if isinstance(row, dict)):
            mismatches.append({
                "field": "cleanup_receipt_uploaded_to_drive",
                "expected": True,
                "actual": False,
            })
        if mismatches:
            errors.append({"problem": "cleanup_evidence_mismatch", "id": pid, "mismatches": mismatches})
            continue
        verified += 1

    status = "PASS" if verified == expected and expected > 0 else "FAIL"
    return {"status": status, "expected": expected, "verified": verified}


def summarize_retained_storage(
    manifest: dict[str, Any],
    artifact_root: Path,
    cleanup_artifact_root: Path,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sum unique remote files using post-processing Drive upload receipts.

    Counts files actually accepted/verified by Drive, not raw-download estimates.
    Product archive bytes and ancillary output bytes are reported separately.
    Run-level ZIP/report files are uploaded later and are not part of this total.
    """
    by_product: list[dict[str, Any]] = []
    unique_files: dict[str, dict[str, Any]] = {}
    new_file_ids: set[str] = set()
    accounted = 0
    products = manifest.get("products", [])
    resume_record = manifest.get("resume")
    reused_checkpoint_ids = {
        str(item) for item in (
            resume_record.get("reused_product_ids", [])
            if isinstance(resume_record, dict) and isinstance(resume_record.get("reused_product_ids", []), list)
            else []
        )
    }
    retention_profile = str(manifest.get("retention_profile", manifest.get("archive_profile", "full-lossless")))
    expected_archive_count = 1 if retention_profile == "full-lossless" else 0

    for product in products:
        pid = str(product.get("id", ""))
        product_dir = artifact_root / f"sarguardian-granule-{pid}"
        cleanup_dir = cleanup_artifact_root / f"sarguardian-cleanup-{pid}"
        receipt_paths = [
            product_dir / "drive-retention-receipt.json",
            product_dir / "drive-metadata-upload-receipt.json",
            cleanup_dir / "drive-cleanup-upload-receipt.json",
        ]
        product_files: dict[str, dict[str, Any]] = {}
        folder_ids: set[str] = set()
        product_error = False

        for receipt_path in receipt_paths:
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append({
                    "problem": "retention_storage_receipt_missing_or_unreadable",
                    "id": pid,
                    "receipt": receipt_path.name,
                    "type": type(exc).__name__,
                    "detail": str(exc)[:240],
                })
                product_error = True
                continue
            if receipt.get("remote_verification") != "PASS":
                errors.append({
                    "problem": "retention_storage_receipt_not_verified",
                    "id": pid,
                    "receipt": receipt_path.name,
                    "status": receipt.get("remote_verification"),
                })
                product_error = True
                continue
            folder_id = receipt.get("remote_folder_id")
            if not isinstance(folder_id, str) or not folder_id:
                errors.append({
                    "problem": "retention_storage_folder_id_missing",
                    "id": pid,
                    "receipt": receipt_path.name,
                })
                product_error = True
                continue
            folder_ids.add(folder_id)
            files = receipt.get("files")
            if not isinstance(files, list):
                errors.append({
                    "problem": "retention_storage_file_list_invalid",
                    "id": pid,
                    "receipt": receipt_path.name,
                })
                product_error = True
                continue

            for item in files:
                if not isinstance(item, dict):
                    product_error = True
                    errors.append({
                        "problem": "retention_storage_file_record_invalid",
                        "id": pid,
                        "receipt": receipt_path.name,
                    })
                    continue
                file_id = item.get("id")
                name = item.get("name")
                size = item.get("bytes")
                reused = item.get("reused")
                if (
                    not isinstance(file_id, str) or not file_id
                    or not isinstance(name, str) or not name
                    or isinstance(size, bool) or not isinstance(size, int) or size < 0
                    or not isinstance(reused, bool)
                ):
                    product_error = True
                    errors.append({
                        "problem": "retention_storage_file_record_invalid",
                        "id": pid,
                        "receipt": receipt_path.name,
                        "name": name if isinstance(name, str) else None,
                    })
                    continue
                record = {"id": file_id, "name": name, "bytes": size, "reused": reused}
                previous = product_files.get(file_id)
                if previous and (previous["name"] != name or previous["bytes"] != size):
                    product_error = True
                    errors.append({
                        "problem": "retention_storage_duplicate_id_mismatch",
                        "id": pid,
                        "file_id": file_id,
                    })
                    continue
                product_files[file_id] = record

        if len(folder_ids) > 1:
            product_error = True
            errors.append({
                "problem": "retention_storage_folder_mismatch",
                "id": pid,
                "folder_ids": sorted(folder_ids),
            })
        if product_error or len(receipt_paths) != 3:
            continue

        archive_rows = [x for x in product_files.values() if x["name"].endswith(".science.h5")]
        if len(archive_rows) != expected_archive_count:
            errors.append({
                "problem": "retention_storage_archive_count_invalid",
                "id": pid,
                "retention_profile": retention_profile,
                "expected": expected_archive_count,
                "count": len(archive_rows),
            })
            continue

        for file_id, row in product_files.items():
            previous = unique_files.get(file_id)
            if previous and (previous["name"] != row["name"] or previous["bytes"] != row["bytes"]):
                errors.append({
                    "problem": "retention_storage_global_duplicate_id_mismatch",
                    "id": pid,
                    "file_id": file_id,
                })
                continue
            unique_files[file_id] = row
            # The receipt's "reused" flag describes the upload attempt that
            # originally created this checkpoint. On a later workflow run, a
            # reused product's historical receipt must not inflate this run's
            # net-new byte count.
            if pid not in reused_checkpoint_ids and not row["reused"]:
                new_file_ids.add(file_id)

        product_bytes = sum(row["bytes"] for row in product_files.values())
        archive_bytes = archive_rows[0]["bytes"] if archive_rows else 0
        ancillary_bytes = product_bytes - archive_bytes
        by_product.append({
            "product_id": pid,
            "granule_name": product.get("granule_name"),
            "retention_profile": retention_profile,
            "retained_archive": bool(archive_rows),
            "remote_retained_file_count": len(product_files),
            "retained_archive_bytes": archive_bytes,
            "ancillary_retained_bytes": ancillary_bytes,
            "actual_remote_retained_bytes": product_bytes,
        })
        accounted += 1

    total_bytes = sum(item["bytes"] for item in unique_files.values())
    new_bytes = sum(unique_files[file_id]["bytes"] for file_id in new_file_ids)
    expected = len(products)
    return {
        "status": "PASS" if accounted == expected and expected > 0 else "FAIL",
        "retention_profile": retention_profile,
        "accounting_basis": "verified Google Drive upload receipt file sizes after processing; not raw source-size estimates",
        "products_expected": expected,
        "products_accounted": accounted,
        "products_reused_from_checkpoint": sum(
            str(product.get("id", "")) in reused_checkpoint_ids for product in products
        ),
        "new_bytes_excludes_reused_checkpoints": True,
        "unique_remote_file_count": len(unique_files),
        "actual_remote_retained_bytes": total_bytes,
        "actual_remote_retained_gib": round(total_bytes / (1024 ** 3), 6),
        "net_new_remote_bytes_in_run": new_bytes,
        "net_new_remote_gib_in_run": round(new_bytes / (1024 ** 3), 6),
        "run_level_bundle_included": False,
        "by_product": by_product,
    }


def aggregate_stats(
    manifest: dict[str, Any],
    artifact_root: Path,
    science_root: Path,
    out_root: Path,
    report: dict[str, Any],
) -> None:
    outputs = science_root / "outputs"
    errors: list[dict[str, Any]] = report["errors"]
    product_meta: dict[str, tuple[dict[str, Any], Path]] = {}
    rows_by_type: dict[str, list[dict[str, str]]] = {"GUNW": [], "GOFF": []}
    baseline_fields: dict[str, list[str]] = {}
    baseline_rows: dict[str, list[dict[str, str]]] = {}
    for family in ("GUNW", "GOFF"):
        stats_name = f"{family.lower()}_stats_source.csv"
        baseline_fields[family], baseline_rows[family] = read_csv(outputs / stats_name)

    retention_profile = str(manifest.get("retention_profile", manifest.get("archive_profile", "full-lossless")))
    if retention_profile not in {"derived-only", "full-lossless"}:
        errors.append({"problem": "invalid_retention_profile", "actual": retention_profile})
    seen_ids: set[str] = set()
    for product in manifest["products"]:
        pid = str(product["id"])
        if pid in seen_ids:
            errors.append({"problem": "duplicate_manifest_id", "id": pid})
            continue
        seen_ids.add(pid)
        try:
            artifact_dir = locate_product_artifact(artifact_root, pid)
            meta_path = artifact_dir / "product-processing.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key, want in (
                ("id", pid),
                ("granule_name", product["granule_name"]),
                ("product_type", product["product_type"]),
                ("maturity", product["maturity"]),
                ("aoi", "source"),
                ("science_commit", manifest["science_commit"]),
                ("retention_profile", retention_profile),
            ):
                if meta.get(key) != want:
                    errors.append({"problem": "product_metadata_mismatch", "id": pid,
                                   "field": key, "expected": want, "actual": meta.get(key)})
            eq = meta.get("reader_equivalence_status")
            if retention_profile == "full-lossless":
                if eq not in {"PASS", "PASS_NO_VALID_AOI_PIXELS"}:
                    errors.append({"problem": "reader_equivalence_not_pass", "id": pid, "actual": eq})
                if not meta.get("retained_archive"):
                    errors.append({"problem": "full_lossless_archive_path_missing", "id": pid})
            else:
                if meta.get("derived_output_validation_status") != "PASS":
                    errors.append({"problem": "derived_output_validation_not_pass", "id": pid,
                                   "actual": meta.get("derived_output_validation_status")})
                validation_path = artifact_dir / "derived-output-validation.json"
                try:
                    validation_report = json.loads(validation_path.read_text(encoding="utf-8"))
                    if validation_report.get("status") != "PASS":
                        errors.append({"problem": "derived_output_validation_report_not_pass", "id": pid,
                                       "actual": validation_report.get("status")})
                except Exception as exc:
                    errors.append({"problem": "derived_output_validation_report_missing", "id": pid,
                                   "detail": str(exc)[:240]})
                if meta.get("retained_archive") is not None:
                    errors.append({"problem": "unexpected_archive_path_in_derived_only", "id": pid})
            if meta.get("drive_remote_verification") != "PASS":
                errors.append({"problem": "remote_outputs_not_verified", "id": pid})
            stats_rel = str(meta["stats_csv"])
            stats_path = safe_relative(artifact_dir, stats_rel)
            _, rows = read_csv(stats_path)
            if not rows:
                errors.append({"problem": "empty_reader_csv", "id": pid, "path": stats_rel})
            if not any((r.get("file") or "").strip() == product["granule_name"] for r in rows):
                errors.append({"problem": "reader_csv_wrong_granule", "id": pid,
                               "expected_file": product["granule_name"],
                               "actual_files": [r.get("file") for r in rows]})
            if meta["product_type"] == "GUNW" and len(rows) != 1:
                errors.append({"problem": "unexpected_gunw_row_count", "id": pid, "count": len(rows)})
            if meta["product_type"] == "GOFF" and (len(rows) != 1 or "layer" not in rows[0] or "layer2" not in rows[0]["layer"]):
                errors.append({"problem": "goff_not_single_layer2_row", "id": pid, "rows": len(rows),
                               "layers": [r.get("layer") for r in rows]})
            rows_by_type[meta["product_type"]].extend(rows)
            product_meta[pid] = (meta, artifact_dir)
        except Exception as exc:
            errors.append({
                "problem": "product_artifact_read_failed",
                "id": pid,
                "type": type(exc).__name__,
                "detail": str(exc)[:240],
                **read_product_diagnostic_context(artifact_dir),
            })

    # Write canonical aggregate CSVs in the original batch baseline order.
    # Full profile must reproduce every row; pilot profile compares its subset only.
    for family in ("GUNW", "GOFF"):
        fields = baseline_fields[family]
        streamed = rows_by_type[family]
        available = {row_key(r, fields): r for r in streamed}
        expected_rows_all = baseline_rows[family]
        expected_products = {p["granule_name"] for p in manifest["products"] if p["product_type"] == family}
        expected_rows = [r for r in expected_rows_all if r.get("file") in expected_products]
        if manifest["run_profile"] == "full-source-baseline" and len(expected_products) != len({
            r.get("file") for r in expected_rows_all
        }):
            errors.append({"problem": "manifest_product_count_does_not_cover_baseline",
                           "family": family, "manifest_products": len(expected_products),
                           "baseline_products": len({r.get("file") for r in expected_rows_all})})
        canonical_rows = [available[row_key(r, fields)] for r in expected_rows if row_key(r, fields) in available]
        out_path = outputs / f"{family.lower()}_stats_source.csv"
        write_csv(out_path, fields, canonical_rows)
        result = compare_rows(expected_rows, streamed, fields,
                              label=f"outputs/{family.lower()}_stats_source.csv", errors=errors)
        report["comparisons"].append(result)

    # Reassemble the small, AOI-clipped geotiffs into the paths used by the
    # original downstream scripts. Only metadata-listed, root-contained files
    # from successfully validated per-granule artifacts are accepted.
    copied_exports = {"GUNW": [], "GOFF": []}
    for product in manifest["products"]:
        item = product_meta.get(str(product["id"]))
        if not item:
            continue
        meta, artifact_dir = item
        family = str(meta["product_type"])
        export_rel_dir = str(meta.get("export_dir", ""))
        if family == "GUNW":
            destination = outputs / "export_src"
        else:
            destination = outputs / "export_goff_src"
        for rel in meta.get("export_files", []):
            try:
                src = safe_relative(artifact_dir, str(rel))
                if not src.is_file() or src.suffix.lower() not in {".tif", ".tiff"}:
                    raise ValueError(f"Listed export missing or not a TIFF: {rel}")
                target = destination / src.name
                if target.exists():
                    errors.append({"problem": "duplicate_export_filename", "file": src.name})
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                copied_exports[family].append(target.name)
            except Exception as exc:
                errors.append({"problem": "export_copy_failed", "id": product["id"],
                               "path": str(rel), "detail": str(exc)[:200]})
    report["derived_exports"] = {k: len(v) for k, v in copied_exports.items()}


def compare_output_file(path: Path, baseline_path: Path, report: dict[str, Any]) -> None:
    if not baseline_path.is_file():
        report["errors"].append({
            "problem": "required_committed_baseline_missing",
            "file": path.name,
            "baseline_path": str(baseline_path),
        })
        report["comparisons"].append({"table": str(path.name), "status": "FAIL_REQUIRED_BASELINE_MISSING"})
        return
    try:
        fields, actual = read_csv(path)
        baseline_fields, baseline = read_csv(baseline_path)
        if fields != baseline_fields:
            # DictWriter order can differ, but schema equality is required, not order.
            if set(fields) != set(baseline_fields):
                report["errors"].append({"problem": "downstream_schema_mismatch", "file": path.name,
                                         "baseline_fields": baseline_fields, "actual_fields": fields})
                report["comparisons"].append({"table": path.name, "status": "FAIL_SCHEMA"})
                return
            fields = baseline_fields
        report["comparisons"].append(compare_rows(
            baseline, actual, fields, label=f"outputs/{path.name}", errors=report["errors"]
        ))
    except Exception as exc:
        report["errors"].append({"problem": "downstream_compare_failed", "file": path.name,
                                 "type": type(exc).__name__, "detail": str(exc)[:240]})
        report["comparisons"].append({"table": path.name, "status": "FAIL_COMPARE"})



def select_candidate4_common_reference_rows(
    stats: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Select the exact pinned candidate-4 source stack, preserving PR/UR duplicate edges."""
    selected = [
        row for row in stats
        if "layer2" in (row.get("layer") or "")
        and ("_PR_GOFF_" in (row.get("file") or "")
             or "_UR_GOFF_" in (row.get("file") or ""))
    ]
    pr_count = sum("_PR_GOFF_" in (row.get("file") or "") for row in selected)
    ur_count = sum("_UR_GOFF_" in (row.get("file") or "") for row in selected)
    identities = [Path(row.get("file") or "").name for row in selected]
    if len(selected) != 18 or pr_count != 16 or ur_count != 2:
        raise ValueError(
            "Expected all 18 candidate-4 GOFF layer2 source products "
            f"(16 PR + 2 UR); found total={len(selected)} PR={pr_count} UR={ur_count}"
        )
    if len(set(identities)) != 18 or any(not name for name in identities):
        raise ValueError("Candidate-4 GOFF layer2 source product identities are missing or duplicated")
    return selected


def run_common_reference_target_series(
    science_root: Path,
    report: dict[str, Any],
    *,
    target_lat: float = 28.27799,
    target_lon: float = 85.52983,
    target_label: str = "Candidate-4",
) -> None:
    """Recreate the candidate-4 common-datum series from all 18 GOFF layer2 exports.

    The committed candidate-4 baseline was built with every GOFF layer2 source
    product, including both PR and UR representations of the two late duplicate
    acquisition pairs. Those duplicate-date edges must not be deduplicated:
    their rasters participate in the cross-pair common mask and provide the
    residual degrees of freedom used by the reported uncertainty. Excluding UR
    rows changes the datum mask for every pair, not just the late time-series
    epochs, and silently changes cumulative displacement and error estimates.

    Read the small, validated AOI GeoTIFFs rather than retaining/re-downloading
    the raw HDF5 stack.
    """
    import re
    from datetime import datetime
    import numpy as np
    import rasterio
    from pyproj import Transformer

    sys.path.insert(0, str((science_root / "src").resolve()))
    import common_ref
    import timeseries

    outputs = science_root / "outputs"
    _, stats = read_csv(outputs / "goff_stats_source.csv")
    selected = select_candidate4_common_reference_rows(stats)

    target_radius_px, buffer_km = 6, 2.0
    pairs_by_key: dict[tuple[str, int], list[tuple[Any, np.ndarray, Any, Any, float]]] = {}
    all_pairs = []
    for row in selected:
        name = Path(row["file"]).name
        tif_name = Path(row.get("export_file") or "").name
        if not tif_name:
            raise ValueError(f"GOFF baseline row has no export_file: {name}")
        tif = outputs / "export_goff_src" / tif_name
        if not tif.is_file():
            raise FileNotFoundError(f"GOFF export missing for common-datum replay: {tif}")
        stamps = re.findall(r"_(\d{8})T\d{6}", name)
        match = re.search(r"_GOFF_\d+_(\d+)_([AD])_", name)
        if len(stamps) < 4 or not match:
            raise ValueError(f"Cannot parse GOFF pair identity from {name}")
        pair = timeseries.Pair(
            path=int(match.group(1)), direction=match.group(2),
            ref=datetime.strptime(stamps[0], "%Y%m%d").date(),
            sec=datetime.strptime(stamps[2], "%Y%m%d").date(),
            value=None, source=name,
        )
        with rasterio.open(tif) as ds:
            if ds.count < 1 or ds.crs is None:
                raise ValueError(f"GOFF export has no band 1 or CRS: {tif.name}")
            array = ds.read(1).astype(np.float32)
            if ds.nodata is not None and np.isfinite(ds.nodata):
                array[array == ds.nodata] = np.nan
            if not np.isfinite(array).any():
                raise ValueError(f"GOFF common-datum export has no finite range offsets: {tif.name}")
            transform, crs, pixel_size = ds.transform, ds.crs, abs(float(ds.res[0]))
        all_pairs.append(pair)
        pairs_by_key.setdefault((pair.direction, pair.path), []).append(
            (pair, array, transform, crs, pixel_size)
        )

    for (direction, path), items in sorted(pairs_by_key.items()):
        first_array, first_transform, first_crs, px = items[0][1], items[0][2], items[0][3], items[0][4]
        for pair, array, transform, crs, _ in items[1:]:
            if array.shape != first_array.shape or transform != first_transform or crs != first_crs:
                raise ValueError(f"GOFF exports do not share one lattice for {direction} path {path}")
        transformer = Transformer.from_crs("EPSG:4326", first_crs, always_xy=True)
        tx, ty = transformer.transform(target_lon, target_lat)
        # This matches rasterio.transform.rowcol used by timeseries.apply_common_datum.
        from rasterio.transform import rowcol
        centre = rowcol(first_transform, tx, ty)
        stack = [item[1] for item in items]
        common = common_ref.common_mask(stack)
        stable = common & ~common_ref.buffer_mask(
            common.shape, [centre], int(round(buffer_km * 1000 / px))
        )
        fixed, _constants = common_ref.rereference(stack, stable)
        for (pair, _array, _transform, _crs, _px), values in zip(items, fixed):
            measured, npx = common_ref.window_median(values, centre, target_radius_px)
            pair.value = float(measured) if np.isfinite(measured) else None
            pair.n_px = npx

    all_rows: list[dict[str, Any]] = []
    by_geometry: dict[tuple[str, int], list[Any]] = {}
    for pair in all_pairs:
        by_geometry.setdefault((pair.direction, pair.path), []).append(pair)
    for (direction, path), group in sorted(by_geometry.items()):
        label = f"{'ASC' if direction == 'A' else 'DESC'} path {path}"
        for index, component in enumerate(timeseries.connected_components(group), 1):
            inside = [p for p in group if p.ref in component and p.sec in component]
            all_rows.extend(timeseries.report_series(label, index, timeseries.invert_component(inside, component)))
    if not all_rows:
        raise ValueError("Common-reference target inversion produced no time-series rows")
    write_csv(outputs / "ts_goff_cand4_common.csv",
              ["geometry", "component", "epoch", "days_from_start", "cumulative_mm", "error_mm"],
              all_rows)
    report["commands"].append({
        "name": f"{target_label} common-reference series from per-product GeoTIFF exports",
        "exit_code": 0,
        "product_count": len(selected),
        "product_families": {"PR": 16, "UR": 2},
        "source": "all 18 validated GOFF layer2 reader exports, including PR and UR duplicate-date edges; not raw HDF5",
        "target": {"lat": target_lat, "lon": target_lon, "radius_px": target_radius_px, "buffer_km": buffer_km},
        "output": "outputs/ts_goff_cand4_common.csv",
    })




def run_time_series_from_exports(
    science_root: Path, family: str, out_root: Path, report: dict[str, Any]
) -> None:
    """Reproduce the raw-directory inversion from per-product AOI TIFFs.

    Do not call timeseries.pairs_from_stats here: that helper intentionally
    resolves PR/UR duplicate acquisitions, while the pinned --dir baseline
    treats each source granule as an edge. Each TIFF preserves the per-pixel
    displacement that the original reader measured; its finite-pixel median
    provides the per-pair input without loading any raw HDF5 file.
    """
    import re
    import numpy as np
    import rasterio
    from datetime import datetime

    src_dir = (science_root / "src").resolve()
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    import timeseries

    outputs = science_root / "outputs"
    csv_path = outputs / f"{family.lower()}_stats_source.csv"
    _, records = read_csv(csv_path)
    pairs = []
    export_root = outputs / ("export_src" if family == "GUNW" else "export_goff_src")
    for row in records:
        raw_name = Path((row.get("file") or "").strip()).name
        if not raw_name:
            raise ValueError(f"{family} stats row has no source filename")
        if family == "GOFF" and "layer2" not in (row.get("layer") or ""):
            continue
        export_name = Path((row.get("export_file") or "").strip()).name
        if not export_name:
            raise ValueError(f"{family} stats row has no export_file: {raw_name}")
        raster_path = export_root / export_name
        if not raster_path.is_file():
            raise FileNotFoundError(f"Missing required derived raster for time-series: {raster_path}")
        with rasterio.open(raster_path) as ds:
            if ds.count < 1:
                raise ValueError(f"Time-series raster has no displacement band: {raster_path}")
            disp = ds.read(1).astype(np.float64)
            if ds.nodata is not None:
                if isinstance(ds.nodata, float) and np.isnan(ds.nodata):
                    disp[~np.isfinite(disp)] = np.nan
                else:
                    disp[disp == ds.nodata] = np.nan
            valid = np.isfinite(disp)
            if not valid.any():
                raise ValueError(f"Time-series raster has no valid displacement pixels: {raster_path}")
            value = float(np.median(disp[valid]))
            count = int(valid.sum())
            if family == "GUNW" and ds.count >= 2:
                coh = ds.read(2).astype(np.float64)
                coh_valid = np.isfinite(coh)
                coherence = float(np.mean(coh[coh_valid])) if coh_valid.any() else None
            elif family == "GOFF" and ds.count >= 3:
                corr = ds.read(3).astype(np.float64)
                corr_valid = np.isfinite(corr)
                coherence = float(np.mean(corr[corr_valid])) if corr_valid.any() else None
            else:
                coherence = None
        stamps = re.findall(r"_(\d{8})T\d{6}", raw_name)
        match = re.search(rf"_{family}_\d+_(\d+)_([AD])_", raw_name)
        if len(stamps) < 4 or not match:
            raise ValueError(f"Cannot parse the pinned pair identity from {raw_name}")
        pairs.append(timeseries.Pair(
            path=int(match.group(1)),
            direction=match.group(2),
            ref=datetime.strptime(stamps[0], "%Y%m%d").date(),
            sec=datetime.strptime(stamps[2], "%Y%m%d").date(),
            value=value,
            n_px=count,
            coherence=coherence,
            source=raw_name,
        ))
    if not pairs:
        raise ValueError(f"No usable {family} pairs were reconstructed from the exports")
    expected = 15 if family == "GUNW" else 18
    if len(pairs) != expected:
        raise ValueError(f"Expected {expected} {family} product rows from the pinned baseline; found {len(pairs)}")

    timeseries.describe_network(pairs)
    by_geom: dict[tuple[str, int], list[Any]] = {}
    for pair in pairs:
        by_geom.setdefault((pair.direction, pair.path), []).append(pair)
    all_rows: list[dict[str, Any]] = []
    for (direction, path), group in sorted(by_geom.items()):
        label = f"{'ASC' if direction == 'A' else 'DESC'} path {path}"
        for index, component in enumerate(timeseries.connected_components(group), 1):
            inside = [p for p in group if p.ref in component and p.sec in component]
            all_rows.extend(timeseries.report_series(
                label, index, timeseries.invert_component(inside, component)
            ))
            timeseries.jackknife(label, index, inside, component)
    if not all_rows:
        raise ValueError(f"{family} export inversion returned no rows")
    output = outputs / f"ts_{family.lower()}_source.csv"
    write_csv(output, ["geometry", "component", "epoch", "days_from_start",
                       "cumulative_mm", "error_mm"], all_rows)
    report["commands"].append({
        "name": f"{family} source-AOI time series from retained per-product TIFFs",
        "exit_code": 0,
        "product_count": len(pairs),
        "source": "AOI-clipped displacement TIFFs (not raw HDF5 and not rounded stats medians)",
        "output": f"outputs/{output.name}",
    })


def run_downstream(science_root: Path, out_root: Path, report: dict[str, Any]) -> None:
    """Run the pinned supplemental science suite and rebuild Results 4, 5 and 7."""
    outputs = science_root / "outputs"

    # Results 1, 2, 3 and 6 are independent documented experiments. Run the
    # exact entry points from the pinned SARGuardian source tree, not rewritten
    # formulas or alternate implementations. These checks happen after product
    # jobs have read/validated raw HDF5 and passed their cleanup gates; their
    # inputs are committed reference data plus public terrain/optical services.
    suite = run_suite(science_root, out_root)
    report["pinned_science_suite"] = {
        "status": suite.get("status"),
        "pinned_science_commit_expected": suite.get("pinned_science_commit_expected"),
        "pinned_science_commit_actual": suite.get("pinned_science_commit_actual"),
        "raw_hdf5_used": suite.get("raw_hdf5_used_by_supplementary_suite"),
        "source_scripts_modified": suite.get("source_scripts_modified"),
        "reference_checks": suite.get("reference_checks", []),
        "report_log": "logs/pinned-science-suite/pinned-science-suite.json",
    }
    for command in suite.get("commands", []):
        report["commands"].append({
            "name": command.get("name"),
            "exit_code": 0 if command.get("status") == "PASS" else 2,
            "status": command.get("status"),
            "argv": command.get("argv"),
            "log": command.get("log"),
            "source": "unchanged entry point from pinned SARGuardian/src/",
        })
    if suite.get("status") != "PASS":
        report["errors"].extend(suite.get("errors", []))
        return

    for family in ("GOFF", "GUNW"):
        try:
            run_time_series_from_exports(science_root, family, out_root, report)
        except Exception as exc:
            report["errors"].append({
                "problem": "time_series_reconstruction_failed",
                "family": family,
                "type": type(exc).__name__,
                "detail": str(exc)[:400],
            })
            return

    # The two source scripts that were not yet connected to this workflow are
    # now run against the retained, AOI-clipped products. This adapter measures
    # target windows from exported GeoTIFFs rather than redownloading raw HDF5.
    backend_tool = Path(__file__).resolve().parent / "run_export_science_diagnostics.py"
    diagnostics_root = out_root / "logs" / "export-science-diagnostics"
    diagnostics_argv = [
        sys.executable, str(backend_tool),
        "--science-root", str(science_root),
        "--exports-root", str(science_root / "outputs" / "export_src"),
        "--out-root", str(diagnostics_root),
        "--expected-science-commit", str(report.get("science_commit") or ""),
        "--aoi", "source",
        "--stats-csv", str(science_root / "outputs" / "gunw_stats_source.csv"),
        "--candidates-csv", str(science_root / "outputs" / "scar_candidates_source.csv"),
        "--run-candidate-check",
    ]
    diagnostics_done = subprocess.run(
        diagnostics_argv, cwd=science_root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=2400,
    )
    diagnostics_log = out_root / "logs" / "export_science_diagnostics_runner.log"
    diagnostics_log.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_log.write_text(diagnostics_done.stdout or "", encoding="utf-8")
    diagnostics_path = diagnostics_root / "science-diagnostics.json"
    if diagnostics_path.is_file():
        try:
            report["export_science_diagnostics"] = json.loads(
                diagnostics_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            report["export_science_diagnostics"] = {
                "status": "FAIL", "problem": "DIAGNOSTICS_REPORT_INVALID",
                "detail": str(exc)[:300],
            }
    else:
        report["export_science_diagnostics"] = {
            "status": "FAIL", "problem": "DIAGNOSTICS_REPORT_MISSING",
        }
    report["commands"].append({
        "name": "pixel_stack and candidate_check on retained GUNW exports",
        "argv": diagnostics_argv[1:],
        "exit_code": diagnostics_done.returncode,
        "log": str(diagnostics_log.relative_to(out_root)),
        "status": report["export_science_diagnostics"].get("status"),
        "source": "unchanged scripts from the exact pinned SARGuardian source commit",
    })
    if diagnostics_done.returncode != 0 or report["export_science_diagnostics"].get("status") == "FAIL":
        report["errors"].append({
            "problem": "EXPORT_SCIENCE_DIAGNOSTICS_FAILED",
            "exit_code": diagnostics_done.returncode,
            "diagnostics_status": report["export_science_diagnostics"].get("status"),
            "log": str(diagnostics_log.relative_to(out_root)),
        })
        return

    # Keep the pre-event cutoff explicit to prevent the event and post-event
    # observations from leaking into an alleged warning-time estimate.
    argv = [
        sys.executable, "src/inverse_velocity.py", "--ts", "outputs/ts_goff_source.csv",
        "--floors", "outputs/goff_stats_source.csv", "--floors-layer", "layer2",
        "--noise-floor", "18.6", "--event-date", "2026-08-26",
    ]
    done = subprocess.run(argv, cwd=science_root, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)
    log_path = out_root / "logs" / "inverse_velocity_source.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(done.stdout, encoding="utf-8")
    report["commands"].append({"name": "inverse_velocity pre-event cutoff", "argv": argv[1:],
                               "exit_code": done.returncode, "log": str(log_path.relative_to(out_root))})
    if done.returncode:
        report["errors"].append({"problem": "downstream_command_failed", "name": "inverse_velocity",
                                 "exit_code": done.returncode, "log_tail": done.stdout[-1200:]})
        return
    if "2026-08-26" not in done.stdout or "dropped" not in done.stdout.lower():
        report["errors"].append({"problem": "event_cutoff_diagnostic_missing",
                                 "log_tail": done.stdout[-1200:]})

    # Rebuild both troposphere reports from the retained, reader-exported rasters.
    troposphere_commands = [
        [sys.executable, "src/troposphere.py", "--dir", "outputs/export_src",
         "--aoi", "source", "--report-only", "--csv", "outputs/troposphere_gunw_source.csv"],
        [sys.executable, "src/troposphere.py", "--dir", "outputs/export_goff_src",
         "--aoi", "source", "--match", "layer2", "--report-only",
         "--csv", "outputs/troposphere_goff_source.csv"],
    ]
    for label, argv in zip(("GUNW troposphere report", "GOFF troposphere report"), troposphere_commands):
        done = subprocess.run(argv, cwd=science_root, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, check=False)
        log_path = out_root / "logs" / (label.lower().replace(" ", "_") + ".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(done.stdout, encoding="utf-8")
        report["commands"].append({"name": label, "argv": argv[1:], "exit_code": done.returncode,
                                   "log": str(log_path.relative_to(out_root)),
                                   "source": "reader-exported GeoTIFFs, not raw HDF5"})
        if done.returncode:
            report["errors"].append({"problem": "downstream_command_failed", "name": label,
                                     "exit_code": done.returncode, "log_tail": done.stdout[-1200:]})
            return
        if not (science_root / argv[-1]).is_file():
            report["errors"].append({"problem": "downstream_output_missing", "name": label,
                                     "expected_output": argv[-1]})
            return

    # These are the exact input dates/exclusions documented for Result 7.
    local_floor_commands = [
        [
            sys.executable, "src/local_floor.py", "--dir", "outputs/export_goff_src",
            "--match", "layer2", "--targets", "outputs/scar_candidates_source.csv",
            "--reading", "DETACHMENT-like", "--radius", "6", "--exclude", "20260828", "_UR_",
            "--include", "20251128", "20251210", "20251222", "20260103", "20260702",
            "20260714", "20260726", "20260819", "--csv", "outputs/local_floor_candidates.csv",
        ],
        [
            sys.executable, "src/local_floor.py", "--dir", "outputs/export_src", "--band", "1",
            "--targets", "outputs/scar_candidates_source.csv", "--reading", "DETACHMENT-like",
            "--radius", "6", "--exclude", "_UR_", "--include", "20251128", "20251210",
            "20251222", "20260103", "20260620", "20260702", "20260714", "20260726",
            "--csv", "outputs/local_floor_phase_candidates.csv",
        ],
        [
            sys.executable, "src/common_ref.py", "--dir", "outputs/export_goff_src",
            "--match", "layer2", "--include", "20260702", "20260714", "20260726",
            "--exclude", "_UR_", "--targets", "outputs/scar_candidates_source.csv",
            "--reading", "DETACHMENT-like", "--csv", "outputs/common_ref_summer.csv",
        ],
        [sys.executable, "src/bound.py"],
    ]
    labels = ["GOFF candidate floors", "GUNW candidate floors", "GOFF summer common reference", "final bound"]
    for label, argv in zip(labels, local_floor_commands):
        done = subprocess.run(argv, cwd=science_root, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, check=False)
        log_path = out_root / "logs" / (label.lower().replace(" ", "_") + ".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(done.stdout, encoding="utf-8")
        report["commands"].append({"name": label, "argv": argv[1:], "exit_code": done.returncode,
                                   "log": str(log_path.relative_to(out_root))})
        if done.returncode:
            report["errors"].append({"problem": "downstream_command_failed", "name": label,
                                     "exit_code": done.returncode, "log_tail": done.stdout[-1200:]})
            return

    # The point-level common-datum series depends on one datum across all
    # pairs of a geometry. Rebuild it from the already-verified fixed-lattice
    # GOFF exports, never by mixing per-pair arbitrary references.
    try:
        run_common_reference_target_series(science_root, report)
    except Exception as exc:
        report["errors"].append({"problem": "common_reference_target_series_failed",
                                 "type": type(exc).__name__, "detail": str(exc)[:400]})

    # Candidate-4 floor tables are required by the source project's final detector gate.
    candidate4_floor_cmd = [
        sys.executable, "src/local_floor.py", "--dir", "outputs/export_goff_src",
        "--match", "layer2", "--lat", "28.27799", "--lon", "85.52983",
        "--radius", "6", "--exclude", "_UR_", "20260828", "20260831",
        "--csv", "outputs/local_floor_cand4.csv",
        "--as-floors", "outputs/local_floor_cand4_as_floors.csv",
    ]
    done = subprocess.run(candidate4_floor_cmd, cwd=science_root, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log_path = out_root / "logs" / "candidate4_local_floors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(done.stdout, encoding="utf-8")
    report["commands"].append({
        "name": "Candidate-4 floors for common-datum time series",
        "argv": candidate4_floor_cmd[1:],
        "exit_code": done.returncode,
        "log": str(log_path.relative_to(out_root)),
        "source": "GOFF layer2 reader-exported GeoTIFFs, not raw HDF5",
    })
    if done.returncode:
        report["errors"].append({"problem": "downstream_command_failed", "name": "candidate4_local_floors",
                                 "exit_code": done.returncode, "log_tail": done.stdout[-1200:]})
        return
    if not (science_root / "outputs/local_floor_cand4.csv").is_file() or not (
        science_root / "outputs/local_floor_cand4_as_floors.csv"
    ).is_file():
        report["errors"].append({"problem": "candidate4_floor_outputs_missing"})
        return

    candidate4_velocity_cmd = [
        sys.executable, "src/inverse_velocity.py", "--ts", "outputs/ts_goff_cand4_common.csv",
        "--floors", "outputs/local_floor_cand4_as_floors.csv", "--floors-layer", "layer2",
        "--event-date", "2026-08-26",
    ]
    done = subprocess.run(candidate4_velocity_cmd, cwd=science_root, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log_path = out_root / "logs" / "candidate4_inverse_velocity.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(done.stdout, encoding="utf-8")
    report["commands"].append({
        "name": "Candidate-4 common-datum inverse-velocity gate",
        "argv": candidate4_velocity_cmd[1:],
        "exit_code": done.returncode,
        "log": str(log_path.relative_to(out_root)),
    })
    if done.returncode:
        report["errors"].append({"problem": "downstream_command_failed", "name": "candidate4_inverse_velocity",
                                 "exit_code": done.returncode, "log_tail": done.stdout[-1200:]})
        return

    # These experiments are generated from the exact pinned source entry points,
    # but the supplied SARGuardian-main.zip has no committed result file for them.
    # Record that explicitly; generation/structure checks are not baseline parity.
    report["unbaselined_outputs"] = [
        {
            "file": "outputs/detectability_blatten_phase.csv",
            "status": "GENERATED_NO_COMMITTED_BASELINE",
            "reason": "Scenario sweep has no committed CSV reference in SARGuardian-main.zip; pinned script and parameters are recorded in the science-suite report.",
        },
        {
            "file": "outputs/detectability_blatten_offsets.csv",
            "status": "GENERATED_NO_COMMITTED_BASELINE",
            "reason": "Offset/noise sweep has no committed CSV reference in SARGuardian-main.zip; pinned script and parameters are recorded in the science-suite report.",
        },
        {
            "file": "outputs/geometry_sensitivity_source.csv",
            "status": "GENERATED_NO_COMMITTED_BASELINE",
            "reason": "Live DEM stencil-sensitivity output has no committed CSV reference in SARGuardian-main.zip.",
        },
        {
            "file": "outputs/ts_gunw_source.csv",
            "status": "GENERATED_NO_COMMITTED_BASELINE",
            "reason": "The supplied SARGuardian-main.zip has no outputs/ts_gunw_source.csv baseline; this is reconstructed from the retained AOI-clipped exports.",
        },
    ]

    # Compare regenerated key outputs with the pinned repository's committed baselines.
    baseline_dir = out_root / "baseline-snapshot"
    for filename in BASELINE_DOWNSTREAM:
        baseline = baseline_dir / filename
        compare_output_file(outputs / filename, baseline, report)


def zip_run_bundle(out_root: Path, science_root: Path, manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = out_root / f"sarguardian-{manifest.get('run_id', 'run')}-results.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if manifest.get("run_profile") in {"validation-pilot", "time-window-selection"}:
            # Pilot and partial-window packages include only the product-level
            # outputs created by this run, never unrelated committed analyses.
            out = science_root / "outputs"
            for rel in (
                "gunw_stats_source.csv", "goff_stats_source.csv",
                "export_src", "export_goff_src",
            ):
                path = out / rel
                if path.is_file():
                    z.write(path, f"outputs/{rel}")
                elif path.is_dir():
                    for item in sorted(path.rglob("*")):
                        if item.is_file() and item.suffix.lower() in {".tif", ".tiff"}:
                            z.write(item, f"outputs/{rel}/{item.relative_to(path).as_posix()}")
        else:
            folder = science_root / "outputs"
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() not in {".h5", ".hdf5"}:
                    z.write(path, f"outputs/{path.relative_to(folder).as_posix()}")
        logs = out_root / "logs"
        if logs.exists():
            for path in sorted(logs.rglob("*")):
                if path.is_file():
                    z.write(path, f"logs/{path.relative_to(logs).as_posix()}")
        z.write(manifest_path, "run-manifest.json")
        report_path = out_root / "batch-equivalence-report.json"
        if report_path.exists():
            z.write(report_path, "batch-equivalence-report.json")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--science-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--cleanup-artifact-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args()
    science_root, manifest_path = args.science_root.resolve(), args.manifest.resolve()
    artifact_root, cleanup_artifact_root, out_root = (
        args.artifact_root.resolve(), args.cleanup_artifact_root.resolve(), args.out_root.resolve()
    )
    out_root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("aoi") != "source":
        raise SystemExit("ERROR=UNEXPECTED_AOI; expected the pinned source AOI")
    if manifest.get("science_commit") != "ab547ecc82bcc4d6ccef545a59852536c2beacc6":
        raise SystemExit("ERROR=UNEXPECTED_SCIENCE_COMMIT")

    outputs = science_root / "outputs"
    baseline_dir = out_root / "baseline-snapshot"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    for filename in BASELINE_DOWNSTREAM:
        src = outputs / filename
        if src.exists():
            shutil.copy2(src, baseline_dir / filename)
    # Preserve baseline terrain outputs before network-backed commands replace
    # working copies; resulting hash differences are diagnostic only.
    for filename in AUXILIARY_JSON_REFERENCES:
        src = outputs / filename
        if src.exists():
            shutil.copy2(src, baseline_dir / filename)

    report: dict[str, Any] = {
        "schema_version": "sarguardian-streaming-batch-equivalence/1.0",
        "run_id": manifest.get("run_id"),
        "run_profile": manifest.get("run_profile"),
        "requested_run_profile": manifest.get("requested_run_profile", manifest.get("run_profile")),
        "time_window": manifest.get("time_window"),
        "aoi": "source",
        "science_commit": manifest.get("science_commit"),
        "products_expected": len(manifest.get("products", [])),
        "products_validated": 0,
        "comparisons": [],
        "commands": [],
        "errors": [],
        "retention_profile": str(manifest.get("retention_profile", manifest.get("archive_profile", "full-lossless"))),
        "archive_policy": str(manifest.get("retention_profile", manifest.get("archive_profile", "full-lossless"))),
        "raw_delete_policy": (
            "raw runner copy is removed only after the full-lossless archive, reader equivalence, all derived files, and remote checksums pass; the remote archive remains retained"
            if manifest.get("retention_profile", manifest.get("archive_profile", "full-lossless")) == "full-lossless" else
            "raw runner copy is removed only after the complete derived-output baseline gate, all declared outputs, source inventory and remote checksums pass; no HDF5 archive is retained"
        ),
    }
    aggregate_stats(manifest, artifact_root, science_root, out_root, report)
    report["cleanup_evidence"] = validate_cleanup_evidence(
        manifest, artifact_root, cleanup_artifact_root, report["errors"]
    )
    report["retention_storage_accounting"] = summarize_retained_storage(
        manifest, artifact_root, cleanup_artifact_root, report["errors"]
    )
    report["products_validated"] = len({
        str(p["id"]) for p in manifest["products"]
        if (artifact_root / f"sarguardian-granule-{p['id']}" / "product-processing.json").is_file()
    })

    table_failures = [c for c in report["comparisons"] if c.get("status") != "PASS"]
    # The per-product batch equivalence gate is mandatory for both profiles.
    if not report["errors"] and not table_failures:
        if manifest.get("run_profile") == "full-source-baseline":
            run_downstream(science_root, out_root, report)
    downstream_failures = [c for c in report["comparisons"] if c.get("status") not in {"PASS", "SKIP_NO_COMMITTED_BASELINE"}]
    report["status"] = "PASS" if not report["errors"] and not downstream_failures and not table_failures else "FAIL"
    report["finished_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    report_path = out_root / "batch-equivalence-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    bundle = zip_run_bundle(out_root, science_root, manifest_path)
    report["bundle_file"] = bundle.name
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Refresh bundle with the completed report including its name.
    bundle.unlink(missing_ok=True)
    bundle = zip_run_bundle(out_root, science_root, manifest_path)
    storage = report["retention_storage_accounting"]
    print(f"BATCH_EQUIVALENCE_STATUS={report['status']}")
    print(f"PRODUCTS_VALIDATED={report['products_validated']}/{report['products_expected']}")
    print(f"COMPARISONS={len(report['comparisons'])}")
    print(f"RETENTION_STORAGE_ACCOUNTING_STATUS={storage['status']}")
    print(f"RETENTION_PRODUCTS_ACCOUNTED={storage['products_accounted']}/{storage['products_expected']}")
    print(f"ACTUAL_REMOTE_RETAINED_BYTES={storage['actual_remote_retained_bytes']}")
    print(f"ACTUAL_REMOTE_RETAINED_GIB={storage['actual_remote_retained_gib']}")
    print(f"NET_NEW_REMOTE_BYTES_IN_RUN={storage['net_new_remote_bytes_in_run']}")
    print(f"REPORT_PATH={report_path}")
    print(f"BUNDLE_PATH={bundle}")
    if report["status"] != "PASS":
        print("ERROR=BATCH_EQUIVALENCE_FAILED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
