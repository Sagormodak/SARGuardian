from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from tools.know_place.author_archive_raster_parity import (
    CHANNELS,
    PAIRS,
    audit_archives,
    compare_channel,
)


def test_compare_channel_requires_same_mask_and_values_within_tolerance():
    expected = np.array([[1.0, np.nan], [2.0, 3.0]], dtype=np.float32)
    same = compare_channel(expected.copy(), expected.copy())
    assert same["status"] == "PASS"
    assert same["finite_mask_mismatch_count"] == 0

    mask_bad = np.array([[1.0, 0.0], [2.0, 3.0]], dtype=np.float32)
    assert compare_channel(mask_bad, expected)["status"] == "FAIL"

    values_bad = expected.copy()
    values_bad[1, 0] += 0.01
    assert compare_channel(values_bad, expected)["status"] == "FAIL"


def _write_author_tif() -> bytes:
    payload = io.BytesIO()
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=8, height=7, count=3, dtype="float32",
            crs="EPSG:4326", transform=from_origin(85.50, 28.32, 0.001, 0.001),
        ) as dataset:
            arrays = [
                np.full((7, 8), 1.25, dtype=np.float32),
                np.full((7, 8), -0.75, dtype=np.float32),
                np.full((7, 8), 0.86, dtype=np.float32),
            ]
            arrays[0][0, 0] = np.nan
            arrays[1][0, 0] = np.nan
            for band, (array, (_, _, description)) in enumerate(zip(arrays, CHANNELS, strict=True), 1):
                dataset.write(array, band)
                dataset.set_band_description(band, description)
        payload.write(memory.read())
    return payload.getvalue()


def _make_run_artifact(path: Path, *, release: str = "P05023", mismatch: bool = False) -> None:
    intervals = [row[0] for row in PAIRS]
    products = []
    deleted = []
    for i, interval in enumerate(intervals):
        filename = f"product-{i}.h5"
        digest = hashlib.sha256(f"source-{i}".encode()).hexdigest()
        size = 1000 + i
        products.append({
            "interval": interval,
            "granule_name": f"NISAR_L2_PR_GOFF_test_{i}_{release}",
            "release_id": release,
            "source_filename": filename,
            "source_bytes": size,
            "source_sha256": digest,
            "download_status": "PASS",
            "grid_validation_status": "PASS",
            "grid_epsg": 32645,
            "grid_width": 4311,
            "grid_height": 4230,
            "grid_x_posting_m": 80.0,
        })
        deleted.append({"source_filename": filename, "source_bytes": size,
                        "source_sha256": digest, "deleted": True})

    source = {
        "status": "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED",
        "expected_intervals": intervals,
        "products": products,
        "repository_branch": "feat/know-place-analysis",
        "repository_commit": "a" * 40,
    }
    source_bytes = (json.dumps(source, separators=(",", ":")) + "\n").encode()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    cleanup = {
        "workflow_run_id": 12345,
        "status": "PASS",
        "source_manifest_sha256": source_sha,
        "source_manifest_verified": True,
        "remote_derived_bundle_verification": "PASS",
        "remote_upload_receipt_copy_verification": "PASS",
        "raw_hdf5_deleted_count": 5,
        "raw_hdf5_files_remaining_count": 0,
        "raw_hdf5_uploaded": False,
        "deleted_sources": deleted,
    }
    status = {"status": "OUTPUTS_WRITTEN", "analysis_metrics_complete": True}
    site_report = {
        "author_site_series_table_comparison": {
            "status": "PASS_AT_ARCHIVE_ROUNDING",
            "checks_passed": 65, "checks_total": 65, "mismatch_count": 0,
        },
        "paper_reproduction_status": "PARTIAL_AUTHOR_TABLE_S4_METRICS_MATCH_FULL_FOOTPRINT_SCREEN_NOT_REPRODUCED",
        "hazard_detection_status": "NOT_EVALUATED",
    }
    author_tif = _write_author_tif()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as run_zip:
        run_zip.writestr("author-exact-source-manifest.json", source_bytes)
        run_zip.writestr("author-exact-raw-cleanup-receipt.json", json.dumps(cleanup))
        run_zip.writestr("author-exact-analysis-status.json", json.dumps(status))
        run_zip.writestr("author-raw-site-series-report.json", json.dumps(site_report))
        for i, (interval, npz_name, _) in enumerate(PAIRS):
            values = [
                np.full((7, 8), 1.25, dtype=np.float32),
                np.full((7, 8), -0.75, dtype=np.float32),
                np.full((7, 8), 0.86, dtype=np.float32),
            ]
            values[0][0, 0] = np.nan
            values[1][0, 0] = np.nan
            if mismatch and i == 0:
                values[1][2, 3] = -0.72
            buf = io.BytesIO()
            np.savez_compressed(buf, east_m=values[0], north_m=values[1], directional_coherence_R=values[2])
            run_zip.writestr(npz_name, buf.getvalue())


def _make_author_archive(path: Path) -> None:
    payload = _write_author_tif()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for _, _, tif_name in PAIRS:
            archive.writestr(tif_name, payload)


def test_archive_parity_audit_reconciles_five_products_receipts_and_15_channels(tmp_path):
    run_path = tmp_path / "run.zip"
    author_path = tmp_path / "author.zip"
    _make_run_artifact(run_path)
    _make_author_archive(author_path)

    report = audit_archives(run_path, author_path, expected_archive_sha256=None)
    assert report["status"] == "PASS"
    assert report["source_provenance"]["source_product_count"] == 5
    assert report["source_provenance"]["source_bytes_total"] == sum(1000 + i for i in range(5))
    assert report["raster_comparison"]["channels_total"] == 15
    assert report["raster_comparison"]["finite_mask_mismatches_total"] == 0


def test_archive_parity_fails_on_numeric_mismatch_and_wrong_release(tmp_path):
    run_path = tmp_path / "run.zip"
    author_path = tmp_path / "author.zip"
    _make_run_artifact(run_path, mismatch=True)
    _make_author_archive(author_path)
    report = audit_archives(run_path, author_path, expected_archive_sha256=None)
    assert report["status"] == "FAIL"
    assert any("RASTER_COMPARISON_FAILED" in row for row in report["problems"])

    _make_run_artifact(run_path, release="X05026")
    report = audit_archives(run_path, author_path, expected_archive_sha256=None)
    assert report["status"] == "FAIL"
    assert any("NON_AUTHOR_RELEASE" in row for row in report["problems"])
