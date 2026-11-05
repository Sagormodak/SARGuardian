"""Offline integrity tests for the downloaded Zenodo author archive audit fixture."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs" / "know-place" / "reference"
FIXTURE_PATH = REFERENCE / "author_archive_golden_v1.json"
BENCHMARK_PATH = REFERENCE / "author_benchmark_v1.json"
ZONES_PATH = REFERENCE / "author_validated_zones_supplementary_data_1.csv"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_uploaded_archive_integrity_fixture_records_manifest_and_raw_data_gap() -> None:
    fixture = _read_json(FIXTURE_PATH)
    archive = fixture["uploaded_files"]["archive"]
    assert archive["md5"] == "b07b7eb3b3178d3f69d5bca009cb0db4"
    assert archive["sha256"] == "002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3"
    assert archive["zip_integrity"] == "PASS"
    manifest = fixture["manifest_audit"]
    assert manifest["manifest_listed_payload_entries_present_and_exact_size_md5"] == 90
    assert manifest["size_or_md5_mismatches"] == 0
    assert len(manifest["manifest_paths_missing_from_zip"]) == 7
    assert manifest["zip_entries_not_self_listed_in_manifest"] == ["MANIFEST.json"]
    inventory = fixture["archive_inventory"]
    assert inventory["raw_goff_h5_granules_in_zip"] is False
    assert inventory["full_footprint_per_pair_offset_rasters_in_zip"] is False
    assert inventory["site_field_geotiff_profile"]["shape_pixels"] == [73, 80]
    assert inventory["site_field_geotiff_profile"]["crs"] == "EPSG:4326"
    assert inventory["site_field_geotiff_profile"]["band_count"] == 3


def test_archive_granule_ids_and_published_series_match_benchmark_fixture() -> None:
    fixture = _read_json(FIXTURE_PATH)
    benchmark = _read_json(BENCHMARK_PATH)
    author_ids = [row["id"] for row in benchmark["exact_author_granules"]]
    assert author_ids == fixture["author_method_facts"]["exact_granule_ids"]
    assert all("_P05023_" in granule_id for granule_id in author_ids)

    rows = fixture["archived_site_series"]
    published = benchmark["published_site_series"]
    assert len(rows) == len(published["columns"]) == 5
    comparisons = [
        ("crown_disp_m", "median_crown_displacement_m"),
        ("crown_rate_cm_per_day", "median_crown_rate_cm_per_day"),
        ("P1_R_crown", "bulk_reference_crown_R"),
        ("P1_R_bg", "bulk_reference_background_R"),
        ("polynull_crown_pctile", "polygon_null_R_percentile"),
    ]
    for source_key, benchmark_key in comparisons:
        source_values = [row[source_key] for row in rows]
        expected = published[benchmark_key]
        assert len(source_values) == len(expected) == 5
        assert all(abs(float(a) - float(b)) <= 1e-9 for a, b in zip(source_values, expected))


def test_repository_inventory_round_trips_to_source_hash_after_git_newline_normalization() -> None:
    fixture = _read_json(FIXTURE_PATH)
    expected = fixture["archive_inventory"]["table_s7_inventory"]
    repository_bytes = ZONES_PATH.read_bytes()

    # The author/uploaded CSV uses CRLF; Git's text checkout uses LF and this
    # checked-in copy has no terminal newline. Normalize line endings and restore
    # the final record delimiter before verifying the original source-byte hash.
    normalized_lf = repository_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if not normalized_lf.endswith(b"\n"):
        normalized_lf += b"\n"
    source_style = normalized_lf.replace(b"\n", b"\r\n")
    assert len(source_style) == expected["bytes"] == 9085
    assert hashlib.sha256(source_style).hexdigest() == expected["sha256"]
    assert expected["rows"] == 101
    assert expected["columns"] == 15

    with ZONES_PATH.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 101
    assert sum(row["glacier"] == "True" for row in rows) == 93
    assert sum(row["glacier"] == "False" for row in rows) == 8
    source = next(row for row in rows if row["zone_id"] == "43")
    assert source["lon"] == "85.5294"
    assert source["lat"] == "28.29161"
    assert source["res_mag_m"] == "4.38"
    assert source["RGIId"] == "RGI60-15.04173"


def test_exported_field_displacement_and_R_crown_counts_are_separate_estimands() -> None:
    fixture = _read_json(FIXTURE_PATH)
    assert fixture["schema_version"] == "know-place-author-archive-audit/1.2"
    diagnostic = fixture["exported_field_crown_mask_diagnostic"]

    displacement = diagnostic["count_estimands"]["displacement_valid_crown_cells"]
    assert displacement["source_table"] == "tables/nisar_pot_series.json"
    assert displacement["source_key"] == "n"
    assert displacement["exported_geotiff_bounds_counts"] == [283, 294, 296, 292, 195]
    assert displacement["published_counts"] == [283, 294, 296, 292, 195]
    assert displacement["difference_export_minus_published"] == [0, 0, 0, 0, 0]
    assert displacement["count_parity"] == "PASS_ON_EXPORTED_FIELD_DIAGNOSTIC"

    r_valid = diagnostic["count_estimands"]["R_valid_crown_cells"]
    assert r_valid["source_table"] == "tables/polygon_null.json"
    assert r_valid["source_key"] == "n_px"
    assert r_valid["exported_geotiff_bounds_counts"] == [302, 299, 302, 298, 202]
    assert r_valid["published_counts"] == [302, 299, 302, 298, 202]
    assert r_valid["difference_export_minus_published"] == [0, 0, 0, 0, 0]
    assert r_valid["count_parity"] == "PASS_ON_EXPORTED_FIELD_DIAGNOSTIC"

    pair_rows = diagnostic["per_pair_results"]
    assert len(pair_rows) == 5
    assert [row["displacement_valid_crown_cells_export"] for row in pair_rows] == displacement["exported_geotiff_bounds_counts"]
    assert [row["R_valid_crown_cells_export"] for row in pair_rows] == r_valid["exported_geotiff_bounds_counts"]
    assert [row["finite_R_mask_equals_archived_band3"] for row in pair_rows] == [True] * 5
    assert max(row["max_absolute_R_error"] for row in pair_rows) < diagnostic["R_band_crosscheck"]["comparison_tolerance"]
    assert diagnostic["R_band_crosscheck"]["finite_masks_equal_for_all_five_fields"] is True
    assert diagnostic["R_band_crosscheck"]["result"] == "PASS_STORED_R_BAND_MATCHES_D_E_D_N"

    # Equal aggregate counts on exported TIFFs do not prove pixelwise parity on the original GOFF grid.
    assert diagnostic["exact_source_grid_pixel_mask_parity"] == "UNVERIFIED"
    assert diagnostic["gate"] == "BLOCKED_SOURCE_GRID_PIXEL_MASK_PARITY_UNVERIFIED"
    assert "no cause is inferred" in diagnostic["remaining_uncertainty"]


def test_author_method_parity_blockers_and_nonhazard_status_are_explicit() -> None:
    fixture = _read_json(FIXTURE_PATH)
    assert fixture["raw_replay_status"] == "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED"
    assert len(fixture["branch_method_mismatches"]) >= 5
    assert fixture["hazard_detection_status"] == "NOT_EVALUATED"
    assert "extent_CC-BY-NC-4.0/" in fixture["source"]["record_license"]

    table_parity = fixture["processed_field_table_parity"]
    assert table_parity["status"] == "PASS_EXPORTED_FIELDS_MATCH_ARCHIVED_TABLES"
    assert table_parity["summary"]["pairs_checked"] == 5
    assert table_parity["summary"]["total_same_estimand_checks"] == 120
    assert table_parity["summary"]["passed_checks"] == 120
    assert table_parity["summary"]["failed_checks"] == 0
    assert table_parity["summary"]["displacement_valid_crown_cells"] == [283, 294, 296, 292, 195]
    assert table_parity["summary"]["polygon_null_R_valid_crown_cells"] == [302, 299, 302, 298, 202]
    assert table_parity["comparison_policy"]["pixelwise_source_grid_parity"] == "UNVERIFIED"
    assert all(row["status"] == "PASS" for row in table_parity["pair_results"])
    assert table_parity["interpretation"].startswith("The matched estimands agree")

