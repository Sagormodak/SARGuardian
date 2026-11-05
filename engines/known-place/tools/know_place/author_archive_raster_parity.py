"""Compare one retained Know Place run with author-published site-field GeoTIFFs.

This audit needs only the workflow artifact ZIP and the pinned Zenodo archive;
it never needs raw HDF5 inputs and does not test the full-footprint screen.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.io import MemoryFile

AUTHOR_ARCHIVE_SHA256 = "002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3"
DEFAULT_TOLERANCE = 1e-6
CHANNELS = (
    ("east_m", 1, "dE_m ground-referenced east displacement"),
    ("north_m", 2, "dN_m ground-referenced north displacement"),
    ("directional_coherence_R", 3, "R directional coherence, 5x5 window"),
)
PAIRS = (
    ("2026-06-20/2026-07-02", "20260620__20260702_author_site_series_arrays.npz", "fields/offsets_20260620_20260702.tif"),
    ("2026-07-02/2026-07-14", "20260702__20260714_author_site_series_arrays.npz", "fields/offsets_20260702_20260714.tif"),
    ("2026-07-14/2026-07-26", "20260714__20260726_author_site_series_arrays.npz", "fields/offsets_20260714_20260726.tif"),
    ("2026-07-26/2026-08-19", "20260726__20260819_author_site_series_arrays.npz", "fields/offsets_20260726_20260819.tif"),
    ("2026-08-19/2026-08-31", "20260819__20260831_author_site_series_arrays.npz", "fields/offsets_20260819_20260831.tif"),
)


class AuditError(ValueError):
    """Raised when provenance or artifact structure is inconsistent."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_member(archive: zipfile.ZipFile, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        payload = archive.read(name)
    except KeyError as exc:
        raise AuditError(f"REQUIRED_RUN_MEMBER_MISSING:{name}") from exc
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise AuditError(f"RUN_JSON_MEMBER_NOT_OBJECT:{name}")
    return value, payload


def compare_channel(actual: Any, expected: Any, tolerance: float = DEFAULT_TOLERANCE) -> dict[str, Any]:
    """Compare shape, finite mask, then finite values within absolute tolerance."""
    a = np.asarray(actual)
    b = np.asarray(expected)
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape:
        return {"status": "FAIL", "reason": "SHAPE_MISMATCH",
                "actual_shape": list(a.shape), "expected_shape": list(b.shape)}
    av, bv = np.isfinite(a), np.isfinite(b)
    mismatches = int(np.count_nonzero(av ^ bv))
    overlap = av & bv
    delta = np.abs(a[overlap].astype(np.float64) - b[overlap].astype(np.float64))
    maximum = float(np.max(delta)) if delta.size else None
    median = float(np.median(delta)) if delta.size else None
    passed = mismatches == 0 and delta.size > 0 and bool(np.all(delta <= tolerance))
    return {
        "status": "PASS" if passed else "FAIL",
        "finite_mask_mismatch_count": mismatches,
        "finite_cells_compared": int(overlap.sum()),
        "max_absolute_difference": maximum,
        "median_absolute_difference": median,
        "absolute_tolerance": tolerance,
    }


def _validate_run_provenance(run_zip: zipfile.ZipFile) -> dict[str, Any]:
    source, source_bytes = _json_member(run_zip, "author-exact-source-manifest.json")
    cleanup, _ = _json_member(run_zip, "author-exact-raw-cleanup-receipt.json")
    status, _ = _json_member(run_zip, "author-exact-analysis-status.json")
    site_report, _ = _json_member(run_zip, "author-raw-site-series-report.json")
    problems: list[str] = []

    if source.get("status") != "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED":
        problems.append("EXACT_SOURCE_MANIFEST_NOT_PASS")
    if len(source.get("products", [])) != 5 or source.get("expected_intervals") != [p[0] for p in PAIRS]:
        problems.append("SOURCE_PRODUCT_COUNT_OR_ORDER_MISMATCH")
    manifest_sha = sha256_bytes(source_bytes)
    if cleanup.get("source_manifest_sha256") != manifest_sha or cleanup.get("source_manifest_verified") is not True:
        problems.append("SOURCE_MANIFEST_RECEIPT_HASH_MISMATCH")
    if status.get("status") != "OUTPUTS_WRITTEN" or status.get("analysis_metrics_complete") is not True:
        problems.append("ANALYSIS_STATUS_NOT_COMPLETE")
    if cleanup.get("status") != "PASS" or cleanup.get("raw_hdf5_deleted_count") != 5:
        problems.append("RAW_CLEANUP_RECEIPT_NOT_PASS")
    if cleanup.get("raw_hdf5_files_remaining_count") != 0 or cleanup.get("raw_hdf5_uploaded") is not False:
        problems.append("RAW_HDF5_REMAINS_OR_WAS_UPLOADED")
    if cleanup.get("remote_derived_bundle_verification") != "PASS" or cleanup.get("remote_upload_receipt_copy_verification") != "PASS":
        problems.append("DRIVE_DERIVED_OR_RECEIPT_VERIFICATION_NOT_PASS")

    deleted = {row.get("source_filename"): row for row in cleanup.get("deleted_sources", [])}
    source_rows = []
    total_bytes = 0
    for product in source.get("products", []):
        filename = product.get("source_filename")
        digest = product.get("source_sha256")
        size = product.get("source_bytes")
        if product.get("release_id") != "P05023":
            problems.append(f"NON_AUTHOR_RELEASE:{filename}")
        if product.get("download_status") != "PASS" or product.get("grid_validation_status") != "PASS":
            problems.append(f"SOURCE_GRID_OR_DOWNLOAD_NOT_PASS:{filename}")
        if (product.get("grid_epsg") != 32645 or product.get("grid_width") != 4311
                or product.get("grid_height") != 4230 or product.get("grid_x_posting_m") != 80.0):
            problems.append(f"SOURCE_GRID_IDENTITY_MISMATCH:{filename}")
        row = deleted.get(filename)
        if not row or row.get("source_sha256") != digest or row.get("source_bytes") != size or row.get("deleted") is not True:
            problems.append(f"DELETE_RECEIPT_SOURCE_IDENTITY_MISMATCH:{filename}")
        if not isinstance(size, int) or not isinstance(digest, str) or len(digest) != 64:
            problems.append(f"SOURCE_SIZE_OR_SHA_MISSING:{filename}")
            continue
        total_bytes += size
        source_rows.append({"interval": product.get("interval"), "filename": filename,
                            "release_id": product.get("release_id"), "bytes": size,
                            "sha256": digest, "deleted_after_retention": bool(row and row.get("deleted") is True)})

    comparison = site_report.get("author_site_series_table_comparison", {})
    if comparison.get("status") != "PASS_AT_ARCHIVE_ROUNDING" or comparison.get("checks_passed") != 65 or comparison.get("checks_total") != 65 or comparison.get("mismatch_count") != 0:
        problems.append("SITE_SERIES_ARCHIVE_CHECKS_NOT_65_OF_65")
    return {
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "run_id": cleanup.get("workflow_run_id"),
        "branch": source.get("repository_branch"),
        "commit": source.get("repository_commit"),
        "source_manifest_sha256": manifest_sha,
        "source_product_count": len(source_rows),
        "source_bytes_total": total_bytes,
        "source_products": source_rows,
        "site_series_checks": comparison,
        "p2_table_comparison": site_report.get("author_p2_table_comparison"),
        "cleanup": {
            "status": cleanup.get("status"),
            "deleted_count": cleanup.get("raw_hdf5_deleted_count"),
            "remaining_count": cleanup.get("raw_hdf5_files_remaining_count"),
            "raw_uploaded": cleanup.get("raw_hdf5_uploaded"),
            "drive_derived_bundle_verification": cleanup.get("remote_derived_bundle_verification"),
            "drive_receipt_copy_verification": cleanup.get("remote_upload_receipt_copy_verification"),
        },
        "paper_reproduction_status": site_report.get("paper_reproduction_status"),
        "hazard_detection_status": site_report.get("hazard_detection_status"),
    }


def audit_archives(
    run_artifact: Path,
    author_archive: Path,
    *,
    expected_archive_sha256: str | None = AUTHOR_ARCHIVE_SHA256,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    run_artifact = Path(run_artifact)
    author_archive = Path(author_archive)
    if not run_artifact.is_file() or not author_archive.is_file():
        raise AuditError("INPUT_FILE_MISSING")
    run_sha, author_sha = sha256_file(run_artifact), sha256_file(author_archive)
    if expected_archive_sha256 is not None and author_sha != expected_archive_sha256:
        raise AuditError("AUTHOR_ARCHIVE_SHA256_MISMATCH")

    with zipfile.ZipFile(run_artifact) as run_zip, zipfile.ZipFile(author_archive) as author_zip:
        provenance = _validate_run_provenance(run_zip)
        results = []
        for interval, npz_name, tif_name in PAIRS:
            try:
                npz_bytes = run_zip.read(npz_name)
                tif_bytes = author_zip.read(tif_name)
            except KeyError as exc:
                raise AuditError(f"PAIR_MEMBER_MISSING:{interval}:{exc}") from exc
            with np.load(io.BytesIO(npz_bytes), allow_pickle=False) as arrays:
                with MemoryFile(tif_bytes) as memory:
                    with memory.open() as dataset:
                        if dataset.count != 3 or dataset.crs is None or dataset.crs.to_epsg() != 4326:
                            raise AuditError(f"AUTHOR_TIFF_SCHEMA_INVALID:{tif_name}")
                        if dataset.descriptions != tuple(row[2] for row in CHANNELS):
                            raise AuditError(f"AUTHOR_TIFF_BANDS_INVALID:{tif_name}")
                        expected = {
                            name: dataset.read(band, masked=True).filled(np.nan).astype(np.float32)
                            for name, band, _ in CHANNELS
                        }
                        grid = {"shape": list(dataset.shape), "crs": str(dataset.crs),
                                "bounds": [float(dataset.bounds.left), float(dataset.bounds.bottom),
                                           float(dataset.bounds.right), float(dataset.bounds.top)]}
                channels = []
                for name, _, _ in CHANNELS:
                    if name not in arrays.files:
                        raise AuditError(f"RUN_ARRAY_MISSING:{interval}:{name}")
                    row = compare_channel(arrays[name], expected[name], tolerance)
                    channels.append({"channel": name, **row})
                if not np.array_equal(np.isfinite(arrays["east_m"]), np.isfinite(arrays["north_m"])):
                    raise AuditError(f"RUN_EAST_NORTH_MASK_MISMATCH:{interval}")
            results.append({"interval": interval, "npz": npz_name, "author_geotiff": tif_name,
                            "grid": grid, "channels": channels,
                            "status": "PASS" if all(row["status"] == "PASS" for row in channels) else "FAIL"})

    failures = [f"{pair['interval']}:{channel['channel']}" for pair in results
                for channel in pair["channels"] if channel["status"] != "PASS"]
    problems = list(provenance["problems"])
    problems.extend(f"RASTER_COMPARISON_FAILED:{row}" for row in failures)
    return {
        "schema_version": "know-place-author-archive-raster-parity/1.0",
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "run_artifact": {"path": run_artifact.name, "bytes": run_artifact.stat().st_size, "sha256": run_sha},
        "author_archive": {"path": author_archive.name, "bytes": author_archive.stat().st_size, "sha256": author_sha},
        "source_provenance": provenance,
        "raster_comparison": {
            "scope": "6-km site-series crop only; no full-footprint parity is inferred",
            "pairs_total": len(results),
            "channels_total": sum(len(pair["channels"]) for pair in results),
            "finite_mask_mismatches_total": sum(row.get("finite_mask_mismatch_count", 0)
                                                for pair in results for row in pair["channels"]),
            "max_absolute_difference": max(
                row.get("max_absolute_difference", 0.0) or 0.0
                for pair in results for row in pair["channels"]
            ),
            "tolerance": tolerance,
            "pairs": results,
        },
        "table_s4_coverage": {
            "workflow_checks": "65/65",
            "workflow_checks_are_full_table_s4_parity": False,
            "table_s4_cells_directly_checked_by_workflow": 45,
            "additional_p1_resolved_and_core_scale_cells_independently_verified": 20,
            "combined_cells_verified_at_published_precision": 65,
            "table_s4_cells_total": 95,
            "table_s4_cells_not_verified": 30,
            "unverified_columns": ["P2_R_crown", "P2_R_bg", "P2_resolved",
                                   "dispnull_crown_m", "dispnull_null_med_m", "dispnull_pctile"],
        },
        "p2_presence_in_run_report": "NOT_PRESENT_AT_RUN_TIME" if not provenance.get("p2_table_comparison") else provenance["p2_table_comparison"].get("status"),
        "paper_reproduction_status": "PARTIAL_AUTHOR_TABLE_S4_METRICS_MATCH_FULL_FOOTPRINT_SCREEN_NOT_REPRODUCED",
        "hazard_detection_status": "NOT_EVALUATED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-artifact", required=True, type=Path)
    parser.add_argument("--author-archive", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args()
    try:
        result = audit_archives(args.run_artifact, args.author_archive, tolerance=args.tolerance)
    except (AuditError, OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        result = {"schema_version": "know-place-author-archive-raster-parity/1.0",
                  "status": "FAIL", "error_type": type(exc).__name__,
                  "error": str(exc).split(":", 1)[0]}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print("AUTHOR_ARCHIVE_RASTER_AUDIT=FAIL")
        print("ERROR=" + result["error"])
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("AUTHOR_ARCHIVE_RASTER_AUDIT=" + result["status"])
    print("RASTER_CHANNELS=" + str(result["raster_comparison"]["channels_total"]))
    print("FINITE_MASK_MISMATCHES=" + str(result["raster_comparison"]["finite_mask_mismatches_total"]))
    print("MAX_ABS_DIFFERENCE=" + str(result["raster_comparison"]["max_absolute_difference"]))
    print("PAPER_REPRODUCTION_STATUS=" + result["paper_reproduction_status"])
    print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
    print("AUDIT_REPORT=" + str(args.out))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
