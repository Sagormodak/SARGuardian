from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
import zipfile

import numpy as np
import rasterio
import pytest
from affine import Affine

from tools.know_place.author_footprint_replay import (
    CANDIDATE_METRIC_COLUMNS,
    _validate_source_manifest,
    _angle_difference_degrees,
    _candidate_table,
    _compare_raster_arrays,
    compare_candidate_inventory,
    compare_validated_zone_table,
    _validated_quality_zone_count,
)



def test_validated_zone_summary_uses_actual_table_s7_schema_key():
    assert _validated_quality_zone_count({
        "computed_quality_zone_count": 101,
        "matched_centroid_count": 101,
    }) == 101
    with pytest.raises(ValueError, match="VALIDATED_QUALITY_ZONE_COUNT_MISSING"):
        _validated_quality_zone_count({"computed_directional_zone_count": 101})


def test_raster_comparison_requires_finite_mask_and_numeric_parity():
    expected = np.array([[0.0, np.nan], [2.0, 3.0]], dtype=np.float32)
    assert _compare_raster_arrays(expected.copy(), expected.copy(), tolerance=0.0)["status"] == "PASS"
    wrong_mask = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)
    assert _compare_raster_arrays(wrong_mask, expected, tolerance=0.0)["finite_mask_mismatch_count"] == 1
    wrong_value = expected.copy()
    wrong_value[1, 0] += 0.001
    assert _compare_raster_arrays(wrong_value, expected, tolerance=0.0001)["status"] == "FAIL"


def test_circular_angle_difference_wraps_at_zero():
    assert _angle_difference_degrees(359.0, 1.0) == 2.0
    assert _angle_difference_degrees(280.0, 280.0) == 0.0
    assert _angle_difference_degrees(90.0, 270.0) == 180.0


def _write_candidate_pair_tif(path: Path, transform: Affine, shape: tuple[int, int]) -> None:
    east = np.full(shape, math.sin(math.radians(280.0)), dtype=np.float32)
    north = np.full(shape, math.cos(math.radians(280.0)), dtype=np.float32)
    bands = [
        np.ones(shape, dtype=np.float32),
        np.full(shape, 0.6, dtype=np.float32),
        np.full(shape, 0.9, dtype=np.float32),
        np.full(shape, 5.0, dtype=np.float32),
        east,
        north,
        np.full(shape, 0.95, dtype=np.float32),
        np.full(shape, 1.2, dtype=np.float32),
    ]
    with rasterio.open(
        path, "w", driver="GTiff", height=shape[0], width=shape[1],
        count=8, dtype="float32", crs="EPSG:32645", transform=transform,
        nodata=-9999.0,
    ) as dst:
        for idx, values in enumerate(bands, 1):
            dst.write(values, idx)


def test_candidate_component_summary_uses_pixel_area_centroid_and_directional_gate(tmp_path):
    shape = (4, 4)
    transform = Affine(80.0, 0.0, 126720.0, 0.0, -80.0, 3347280.0)
    labels = np.ones(shape, dtype=np.int32)
    epochs = np.full(shape, 3, dtype=np.uint8)
    anomaly = np.full(shape, 0.6, dtype=np.float32)
    coherence = np.full(shape, 0.8, dtype=np.float32)
    terrain = {
        "elev_m.tif": np.full(shape, 5000.0, dtype=np.float32),
        "slope_deg.tif": np.full(shape, 20.0, dtype=np.float32),
        "downslope_az_deg.tif": np.full(shape, 280.0, dtype=np.float32),
    }
    range_az = 250.0
    coefficient = {
        "kE": np.full(shape, math.sin(math.radians(range_az)), dtype=np.float32),
        "kN": np.full(shape, math.cos(math.radians(range_az)), dtype=np.float32),
    }
    pair_tif = tmp_path / "pair.tif"
    _write_candidate_pair_tif(pair_tif, transform, shape)
    rows, summary = _candidate_table(
        labels, epochs, anomaly, coherence, terrain, coefficient,
        [pair_tif] * 5, transform,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["n_px"] == 16
    assert row["area_km2"] == 0.1024
    assert row["n_epochs"] == 3
    assert row["anom_m"] == 0.6
    assert row["R"] == 0.8
    assert row["disp_az"] == pytest.approx(280.0, abs=1e-4)
    assert row["d_downslope"] == pytest.approx(0.0, abs=1e-4)
    assert row["d_range"] == pytest.approx(30.0, abs=1e-4)
    assert row["valid_directional"] is True
    assert row["score"] == pytest.approx(3 * 0.6 * 0.9, abs=1e-6)
    assert summary["directional_pass_count"] == 1
    assert summary["quality_pass_count"] == 1


def _expected_inventory_csv(rows: list[dict[str, object]]) -> str:
    stream = io.StringIO()
    columns = ["lon", "lat", *CANDIDATE_METRIC_COLUMNS, "quality"]
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        record = {column: row[column] for column in CANDIDATE_METRIC_COLUMNS}
        record["lon"] = row["lon"]
        record["lat"] = row["lat"]
        record["quality"] = bool(row["quality"])
        writer.writerow(record)
    return stream.getvalue()


def _table_s7_csv(rows: list[dict[str, object]]) -> str:
    stream = io.StringIO()
    columns = [
        "zone_id", "lon", "lat", "area_km2", "n_epochs", "res_mag_m",
        "disp_az", "downslope_az", "d_downslope", "R_res", "elev_m", "slope_deg",
        "d_glac_m", "glacier", "RGIId",
    ]
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for i, row in enumerate(rows, 1):
        writer.writerow({
            "zone_id": i,
            "lon": f"{float(row['lon']):.5f}",
            "lat": f"{float(row['lat']):.5f}",
            "area_km2": f"{float(row['area_km2']):.4f}",
            "n_epochs": int(row["n_epochs"]),
            "res_mag_m": f"{float(row['res_mag_m']):.2f}",
            "disp_az": f"{float(row['disp_az']):.1f}",
            "downslope_az": f"{float(row['downslope_az']):.1f}",
            "d_downslope": f"{float(row['d_downslope']):.1f}",
            "R_res": f"{float(row['R_res']):.3f}",
            "elev_m": f"{float(row['elev_m']):.0f}",
            "slope_deg": f"{float(row['slope_deg']):.1f}",
            "d_glac_m": "0",
            "glacier": "True",
            "RGIId": "RGI60-test",
        })
    return stream.getvalue()


def _make_candidate_rows(count: int = 106) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for i in range(count):
        directional = i < 101
        angle = 280.0 if directional else 350.0
        rows.append({
            "component_id": i + 1,
            "lon": round(80.0 + i * 0.003, 5),
            "lat": round(27.0 + i * 0.002, 5),
            "area_km2": 0.1024,
            "n_px": 16,
            "n_epochs": 3,
            "anom_m": 0.6,
            "R": 0.7,
            "score": 3.0 * 0.6 * (0.90 - i * 0.001),
            "disp_az": angle,
            "res_mag_m": 1.0,
            "R_raw": 0.95,
            "R_res": 0.90 - i * 0.001,
            "mag_m": 1.2,
            "elev_m": 5000.0,
            "slope_deg": 20.0,
            "downslope_az": 280.0,
            "range_az": 250.0,
            "d_downslope": 0.0 if directional else 70.0,
            "d_range": 30.0,
            "valid_directional": directional,
            "quality": directional,
        })
    return rows


def test_archived_candidate_inventory_comparison_covers_106_candidates_and_101_quality_pass(tmp_path):
    rows = _make_candidate_rows()
    source_csv = _expected_inventory_csv(rows)
    archive_path = tmp_path / "author.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("inventory/candidates_attributed.csv", source_csv)
        archive.writestr("tables/TableS7_all_validated_zones.csv", _table_s7_csv(rows[:101]))

    result = compare_candidate_inventory(rows, archive_path, numeric_tolerance=1e-9)
    assert result["status"] == "PASS"
    assert result["expected_candidate_count"] == result["computed_candidate_count"] == 106
    assert result["matched_centroid_count"] == 106
    assert result["expected_quality_pass_count"] == 101
    assert result["computed_quality_pass_count"] == 101
    assert result["mismatch_count"] == 0
    assert result["ranking_order_comparison"]["status"] == "PASS"
    assert result["ranking_order_comparison"]["source_inventory_sorted_descending_by_final_score"] is True
    assert result["ranking_order_comparison"]["rank_inversion_count"] == 0
    assert result["score_formula_audit"]["postprocessed_formula_matches"] == 106
    assert result["score_formula_audit"]["status"] == "PASS_POSTPROCESSED_AUTHOR_SCORE_CONVENTION"

    validated = compare_validated_zone_table(rows, archive_path)
    assert validated["status"] == "PASS"
    assert validated["expected_zone_count"] == validated["computed_quality_zone_count"] == 101
    assert validated["matched_centroid_count"] == 101
    assert validated["mismatch_count"] == 0

    reversed_archive_path = tmp_path / "author-inventory-wrong-order.zip"
    reversed_rows = list(reversed(rows))
    with zipfile.ZipFile(reversed_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("inventory/candidates_attributed.csv", _expected_inventory_csv(reversed_rows))
        archive.writestr("tables/TableS7_all_validated_zones.csv", _table_s7_csv(rows[:101]))
    wrong_order = compare_candidate_inventory(rows, reversed_archive_path, numeric_tolerance=1e-9)
    assert wrong_order["status"] == "MISMATCH"
    assert wrong_order["ranking_order_comparison"]["status"] == "MISMATCH"
    assert wrong_order["ranking_order_comparison"]["source_inventory_sorted_descending_by_final_score"] is False

    modified = [dict(row) for row in rows]
    modified[50]["R_res"] = 0.91
    mismatch = compare_candidate_inventory(modified, archive_path, numeric_tolerance=1e-9)
    assert mismatch["status"] == "MISMATCH"
    assert mismatch["mismatch_count"] == 1
    assert mismatch["mismatch_count_by_metric"] == {"R_res": 1}

    # The original wide_screen.py score is provisional. The archive runs
    # fix_zonal_attrs.py afterward, which replaces score with n_epochs * anom_m * R_res.
    # A deposited table that retains the provisional R score must not pass.
    provisional_rows = [dict(row) for row in rows]
    for row in provisional_rows:
        row["score"] = float(row["n_epochs"]) * float(row["anom_m"]) * float(row["R"])
    score_archive_path = tmp_path / "author-provisional-score.zip"
    with zipfile.ZipFile(score_archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("inventory/candidates_attributed.csv", _expected_inventory_csv(provisional_rows))
        archive.writestr("tables/TableS7_all_validated_zones.csv", _table_s7_csv(provisional_rows[:101]))
    score_contract = compare_candidate_inventory(rows, score_archive_path, numeric_tolerance=1e-9)
    assert score_contract["status"] == "MISMATCH"
    assert score_contract["mismatch_count_by_metric"] == {"score": 106}
    assert score_contract["score_formula_audit"]["postprocessed_formula_matches"] == 0
    assert score_contract["score_formula_audit"]["status"] == "POSTPROCESSED_SCORE_FORMULA_MISMATCH"



def test_source_manifest_accepts_ordered_iso_date_intervals_from_acquisition(tmp_path):
    intervals = [
        "2026-06-20/2026-07-02",
        "2026-07-02/2026-07-14",
        "2026-07-14/2026-07-26",
        "2026-07-26/2026-08-19",
        "2026-08-19/2026-08-31",
    ]
    products = []
    for interval in intervals:
        products.append({
            "interval": interval,
            "release_id": "P05023",
            "download_status": "PASS",
            "grid_validation_status": "PASS",
            "source_bytes": 100,
            "source_sha256": "a" * 64,
            "grid_epsg": 32645,
            "grid_width": 4311,
            "grid_height": 4230,
            "grid_x_posting_m": 80.0,
            "grid_y_posting_m": -80.0,
        })
    manifest = {
        "status": "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED",
        "author_release_id": "P05023",
        "source_downloads": 5,
        "author_exact_source_sha256_count": 5,
        "source_products_grid_validated": 5,
        "expected_intervals": intervals,
        "products": products,
    }
    path = tmp_path / "author-exact-source-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    indexed = _validate_source_manifest(path)

    assert list(indexed) == intervals
