from __future__ import annotations
import hashlib
import io
import json
import zipfile

import numpy as np
import pytest

import tools.know_place.crown_mask_audit as audit


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _npz_bytes(**arrays) -> bytes:
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()



_AUTHOR_PRODUCT_FIXTURES = (
    (
        "2026-06-20/2026-07-02", "G4248299988-ASF",
        "NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_P05023_N_F_J_001.h5",
        1090519040, "d3670f0504576feac52f75a7e8f0ff12f5f5c2ef676a0329a16f66cb91300f05",
    ),
    (
        "2026-07-02/2026-07-14", "G4261120661-ASF",
        "NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001.h5",
        1090519040, "8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c",
    ),
    (
        "2026-07-14/2026-07-26", "G4264302811-ASF",
        "NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001.h5",
        1092616192, "ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313",
    ),
    (
        "2026-07-26/2026-08-19", "G4286855543-ASF",
        "NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001.h5",
        1101004800, "45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f",
    ),
    (
        "2026-08-19/2026-08-31", "G4296814366-ASF",
        "NISAR_L2_PR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_N_F_J_001.h5",
        1098907648, "4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371",
    ),
)


def _source_manifest_fixture(pairs):
    products = []
    for interval, cmr_id, filename, byte_count, sha256 in _AUTHOR_PRODUCT_FIXTURES:
        start, end = interval.split("/")
        stem = filename[:-3]
        checks = {
            "filename": {"expected": filename, "actual": filename, "passed": True},
            "granule_stem": {"expected": stem, "actual": stem, "passed": True},
            "release_id": {"expected": "P05023", "actual": "P05023", "passed": True},
            "reference_start_date": {"expected": start, "actual": start, "passed": True},
            "secondary_start_date": {"expected": end, "actual": end, "passed": True},
            "epsg": {"expected": 32645, "actual": 32645, "passed": True},
        }
        products.append({
            "granule_name": stem,
            "interval": interval,
            "release_id": "P05023",
            "collection_concept_id": "C2854341702-ASF",
            "cmr_granule_concept_id": cmr_id,
            "source_filename": filename,
            "download_url_host": "nisar.asf.earthdatacloud.nasa.gov",
            "remote_content_length_bytes": byte_count,
            "download_status": "PASS",
            "source_bytes": byte_count,
            "source_sha256": sha256,
            "hdf5_container_valid": True,
            "byte_count_validation": "PASS",
            "content_validation_status": "PASS",
            "grid_validation_status": "PASS",
            "identity_validation": {
                "status": "PASS",
                "expected_granule_name_without_extension": stem,
                "expected_source_filename_with_extension": filename,
                "actual_identity_filename": filename,
                "checks": checks,
                "mismatch_fields": [],
            },
            "grid_epsg": 32645,
            "grid_width": 4311,
            "grid_height": 4230,
            "grid_x_min_m": 126760.0,
            "grid_x_max_m": 471560.0,
            "grid_y_min_m": 3008920.0,
            "grid_y_max_m": 3347240.0,
            "grid_x_posting_m": 80.0,
            "grid_y_posting_m": -80.0,
            "polarization": "HH",
            "layer": "layer2",
            "validated_at_utc": "2026-10-25T06:48:36.306946+00:00",
        })
    return {
        "schema_version": "know-place-author-exact-acquisition/1.0",
        "repository_branch": "test",
        "repository_commit": "deadbeef",
        "collection_concept_id": "C2854341702-ASF",
        "expected_collection_short_name": "NISAR_L2_GOFF_PROVISIONAL_V1",
        "expected_maturity": "PROVISIONAL",
        "author_release_id": "P05023",
        "expected_intervals": [row[0] for row in _AUTHOR_PRODUCT_FIXTURES],
        "author_product_count": 5,
        "exact_cmr_confirmed_count": 5,
        "blocking_count": 0,
        "source_sha256_count": 5,
        "author_exact_source_sha256_count": 5,
        "status": "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED",
        "products": products,
    }


def _write_fixture(tmp_path, monkeypatch, *, corrupt_pair_zero_mask=False, source_mutation=None, receipt_mutation=None):
    # Tiny but internally complete native grid; monkeypatching keeps the audit
    # logic identical while making its zip/manifest contract test run in CI.
    monkeypatch.setattr(audit, "EPSG", 4326)
    monkeypatch.setattr(audit, "WIDTH", 8)
    monkeypatch.setattr(audit, "HEIGHT", 8)
    monkeypatch.setattr(audit, "X0", 0.0)
    monkeypatch.setattr(audit, "Y0", 6.0)
    monkeypatch.setattr(audit, "DX", 1.0)
    monkeypatch.setattr(audit, "DY", -1.0)
    monkeypatch.setattr(audit, "CROWN", (1.0, 1.0, 4.0, 4.0))
    monkeypatch.setattr(audit, "BOX", (0.0, 0.0, 7.0, 7.0))
    monkeypatch.setattr(audit, "EXPECTED_CROWN_CELLS", 9)
    pairs = tuple((row[0], row[1], 4, 3) for row in audit.PAIRS)
    monkeypatch.setattr(audit, "PAIRS", pairs)

    x_site = (np.arange(6, dtype=float) + 0.5)
    y_site = 6.0 - (np.arange(6, dtype=float) + 0.5)
    site_mask = audit.geographic_mask(x_site, y_site)
    extent = [0.5, 5.5, 0.5, 5.5]
    crop = audit.endpoint_crop((6, 6), extent)
    np.testing.assert_array_equal(site_mask, crop)
    assert int(site_mask.sum()) == 9

    x_diag = np.arange(8, dtype=float) + 0.5
    y_diag = 6.0 - (np.arange(8, dtype=float) + 0.5)
    diag_mask = audit.geographic_mask(x_diag, y_diag)
    assert int(diag_mask.sum()) == 9

    site_files = {}
    diag_files = {}
    report_rows = []
    for i, (interval, prefix, _, _) in enumerate(pairs):
        site = site_mask.astype(np.uint8).copy()
        if i == 0 and corrupt_pair_zero_mask:
            site[0, 0] = 1
        valid = np.zeros((6, 6), dtype=np.uint8)
        positions = np.argwhere(site_mask)[:4]
        for row, col in positions:
            valid[row, col] = 1
        r = np.full((6, 6), np.nan, dtype=np.float32)
        for row, col in np.argwhere(site_mask)[:3]:
            r[row, col] = 0.5
        site_name = prefix + "_author_site_series_arrays.npz"
        diag_name = prefix + "_diagnostic_arrays.npz"
        site_bytes = _npz_bytes(
            east_m=np.ones((6, 6), dtype=np.float32),
            north_m=np.ones((6, 6), dtype=np.float32),
            horizontal_magnitude_m=np.ones((6, 6), dtype=np.float32),
            directional_coherence_R=r,
            valid_mask=valid,
            crown_mask=site,
        )
        diag_r = np.full((8, 8), np.nan, dtype=np.float32)
        diag_bytes = _npz_bytes(
            east_m=np.ones((8, 8), dtype=np.float32),
            north_m=np.ones((8, 8), dtype=np.float32),
            horizontal_magnitude_m=np.ones((8, 8), dtype=np.float32),
            directional_coherence_R=diag_r,
            valid_mask=np.zeros((8, 8), dtype=np.uint8),
            crown_mask=diag_mask.astype(np.uint8),
            x_coordinates_m=x_diag,
            y_coordinates_m=y_diag,
        )
        site_files[site_name] = site_bytes
        diag_files[diag_name] = diag_bytes
        start, end = interval.split("/")
        report_rows.append({
            "pair": start + "->" + end,
            "source_grid": {
                "epsg": 4326,
                "original_width": 8,
                "original_height": 8,
                "window_shape": [6, 6],
                "x_posting_m": 1.0,
                "y_posting_m": -1.0,
                "window_slices": {
                    "row_start": 0, "row_stop": 6,
                    "column_start": 0, "column_stop": 6,
                },
            },
            "extent_lonlat": extent,
            # Historical author report uses this field for the site-array NPZ.
            "diagnostic_npz": site_name,
            "diagnostic_arrays_sha256": hashlib.sha256(site_bytes).hexdigest(),
        })

    crown_wkt = "POLYGON ((1.0 1.0, 4.0 1.0, 4.0 4.0, 1.0 4.0, 1.0 1.0))"
    box_wkt = "POLYGON ((0.0 0.0, 7.0 0.0, 7.0 7.0, 0.0 7.0, 0.0 0.0))"
    inputs = {"crown_wkt": crown_wkt, "reference_box_wkt": box_wkt}
    source = _source_manifest_fixture(pairs)
    if source_mutation == "missing-sha":
        source["products"][0]["source_sha256"] = None
    elif source_mutation == "duplicate-sha":
        source["products"][1]["source_sha256"] = source["products"][0]["source_sha256"]
    elif source_mutation == "wrong-interval":
        source["products"][0]["interval"] = "2026-06-19/2026-07-02"
    elif source_mutation == "wrong-grid":
        source["products"][0]["grid_validation_status"] = "FAIL"
    elif source_mutation == "historical-release-filename":
        source["products"][0]["source_filename"] = source["products"][0]["source_filename"].replace("_P05023_", "_X05026_")
    elif source_mutation == "zero-bytes":
        source["products"][0]["source_bytes"] = 0
    elif source_mutation == "wrong-source-collection":
        source["products"][0]["collection_concept_id"] = "C0000000000-ASF"
    source_manifest_bytes = _json_bytes(source)
    cleanup = {
        "workflow_run_id": "fixture-123",
        "status": "PASS",
        "source_manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
        "source_manifest_verified": True,
        "remote_derived_bundle_verification": "PASS",
        "remote_upload_receipt_copy_verification": "PASS",
        "expected_source_count": 5,
        "source_files_hash_verified_before_delete": 5,
        "raw_hdf5_files_before_delete": 5,
        "raw_hdf5_deleted_count": 5,
        "raw_hdf5_files_remaining_count": 0,
        "raw_hdf5_remaining_count": 0,
        "raw_hdf5_remaining": [],
        "raw_hdf5_uploaded": False,
        "raw_hdf5_deleted_after_verified_drive_retention": True,
        "raw_cleanup_evidence_is_post_delete": True,
        "raw_directory_removed": True,
        "drive_derived_bundle_bytes": 123456,
        "drive_derived_bundle_sha256": "a" * 64,
        "drive_derived_bundle_file_id": "drive-file-id",
        "drive_derived_bundle_name": "author-exact-derived-results.zip",
        "drive_upload_receipt_copy_id": "drive-receipt-id",
        "deleted_sources": [
            {
                "source_filename": product["source_filename"],
                "source_bytes": product["source_bytes"],
                "source_sha256": product["source_sha256"],
                "deleted": True,
            }
            for product in source["products"]
        ],
    }
    if receipt_mutation == "manifest-sha":
        cleanup["source_manifest_sha256"] = "0" * 64
    elif receipt_mutation == "deleted-source-sha":
        cleanup["deleted_sources"][0]["source_sha256"] = "0" * 64
    status = {"status": "OUTPUTS_WRITTEN", "analysis_metrics_complete": True}
    report = {"pair_reports": report_rows}
    inner_zip = _zip_bytes({"derived-only-placeholder.txt": b"no raw products"})
    outer_files = {
        "author-exact-derived-results.zip": inner_zip,
        "know-place-inputs.json": _json_bytes(inputs),
        "author-exact-source-manifest.json": source_manifest_bytes,
        "author-exact-raw-cleanup-receipt.json": _json_bytes(cleanup),
        "author-exact-analysis-status.json": _json_bytes(status),
        "author-raw-site-series-report.json": _json_bytes(report),
        **site_files,
        **diag_files,
    }
    run_path = tmp_path / "synthetic-run.zip"
    run_path.write_bytes(_zip_bytes(outer_files))

    author_rows = []
    null_rows = []
    for interval, _, disp_n, r_n in pairs:
        start, end = interval.split("/")
        author_rows.append({"a": start.replace("-", ""), "b": end.replace("-", ""), "n": disp_n})
        null_rows.append({"pair": start + "->" + end, "n_px": r_n})
    author_path = tmp_path / "synthetic-author.zip"
    author_path.write_bytes(_zip_bytes({
        "tables/nisar_pot_series.json": _json_bytes(author_rows),
        "tables/polygon_null.json": _json_bytes(null_rows),
    }))
    monkeypatch.setattr(audit, "AUTHOR_ARCHIVE_SHA256", hashlib.sha256(author_path.read_bytes()).hexdigest())
    return run_path, author_path


def test_full_archive_audit_passes_on_synthetic_known_answer_package(tmp_path, monkeypatch):
    run_path, author_path = _write_fixture(tmp_path, monkeypatch)
    result = audit.audit_crown_masks(run_path, author_path)
    assert result["status"] == "PASS"
    assert result["pair_count"] == 5
    assert all(row["status"] == "PASS" for row in result["pairs"])
    assert all(row["site_vs_geographic_xor_cells"] == 0 for row in result["pairs"])
    assert all(row["site_vs_endpoint_crop_xor_cells"] == 0 for row in result["pairs"])
    assert all(row["site_vs_diagnostic_global_xor_cells"] == 0 for row in result["pairs"])
    assert result["inputs"]["raw_hdf5_outer_members"] == 0
    assert result["inputs"]["raw_hdf5_nested_members"] == 0
    assert result["author_original_vector_mask_parity"].startswith("UNVERIFIED")
    assert result["hazard_detection_status"] == "NOT_EVALUATED"


def test_full_archive_audit_fails_closed_when_a_saved_mask_is_corrupted(tmp_path, monkeypatch):
    run_path, author_path = _write_fixture(tmp_path, monkeypatch, corrupt_pair_zero_mask=True)
    result = audit.audit_crown_masks(run_path, author_path)
    assert result["status"] == "FAIL"
    assert result["pairs"][0]["status"] == "FAIL"
    assert result["pairs"][0]["site_vs_geographic_xor_cells"] == 1
    assert result["pairs"][0]["site_vs_endpoint_crop_xor_cells"] == 1
    assert "CROSS_PAIR_MASK_HASH_MISMATCH" in result["failures"]


def test_audit_rejects_author_archive_hash_mismatch(tmp_path, monkeypatch):
    run_path, author_path = _write_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(audit, "AUTHOR_ARCHIVE_SHA256", "0" * 64)
    with pytest.raises(audit.CrownMaskAuditError, match="AUTHOR_ARCHIVE_SHA256_MISMATCH"):
        audit.audit_crown_masks(run_path, author_path)

@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("missing-sha", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
        ("duplicate-sha", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
        ("wrong-interval", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
        ("wrong-grid", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
        ("historical-release-filename", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
        ("zero-bytes", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
        ("wrong-source-collection", "AUTHOR_SOURCE_ROW_PROVENANCE_INVALID"),
    ],
)
def test_source_manifest_requires_exact_unique_author_product_provenance(
    tmp_path, monkeypatch, mutation, error_code
):
    run_path, author_path = _write_fixture(tmp_path, monkeypatch, source_mutation=mutation)
    with pytest.raises(audit.CrownMaskAuditError, match=error_code):
        audit.audit_crown_masks(run_path, author_path)


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("manifest-sha", "SOURCE_MANIFEST_RECEIPT_HASH_MISMATCH"),
        ("deleted-source-sha", "RAW_SOURCE_DELETE_RECEIPT_MISMATCH"),
    ],
)
def test_source_delete_receipts_must_match_manifest_and_each_pinned_product(
    tmp_path, monkeypatch, mutation, error_code
):
    run_path, author_path = _write_fixture(tmp_path, monkeypatch, receipt_mutation=mutation)
    with pytest.raises(audit.CrownMaskAuditError, match=error_code):
        audit.audit_crown_masks(run_path, author_path)


def test_manifest_interval_list_is_a_frozen_five_pair_contract(tmp_path, monkeypatch):
    run_path, author_path = _write_fixture(tmp_path, monkeypatch)
    with zipfile.ZipFile(run_path, "r") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    source = json.loads(members["author-exact-source-manifest.json"])
    source["expected_intervals"][0] = "2026-06-19/2026-07-02"
    members["author-exact-source-manifest.json"] = _json_bytes(source)
    cleanup = json.loads(members["author-exact-raw-cleanup-receipt.json"])
    cleanup["source_manifest_sha256"] = hashlib.sha256(members["author-exact-source-manifest.json"]).hexdigest()
    members["author-exact-raw-cleanup-receipt.json"] = _json_bytes(cleanup)
    run_path.write_bytes(_zip_bytes(members))
    with pytest.raises(audit.CrownMaskAuditError, match="AUTHOR_SOURCE_IDENTITY_MANIFEST_INVALID"):
        audit.audit_crown_masks(run_path, author_path)
