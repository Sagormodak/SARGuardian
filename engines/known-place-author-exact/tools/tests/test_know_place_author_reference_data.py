"""Integrity checks for the transcribed author paper/supplement reference fixture."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs" / "know-place" / "reference"
CSV_PATH = REFERENCE / "author_validated_zones_supplementary_data_1.csv"
BENCHMARK_PATH = REFERENCE / "author_benchmark_v1.json"


def _load_inventory() -> list[dict[str, str]]:
    with CSV_PATH.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames == [
            "zone_id", "lon", "lat", "area_km2", "n_epochs", "res_mag_m",
            "disp_az", "downslope_az", "d_downslope", "R_res", "elev_m",
            "slope_deg", "d_glac_m", "glacier", "RGIId",
        ]
    return rows


def _load_benchmark() -> dict:
    with BENCHMARK_PATH.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def test_author_inventory_has_101_ordered_unique_zones_and_expected_glacier_counts() -> None:
    rows = _load_inventory()
    assert len(rows) == 101
    zone_ids = [int(row["zone_id"]) for row in rows]
    assert zone_ids == list(range(1, 102))
    assert len(set(zone_ids)) == 101
    assert Counter(row["glacier"] for row in rows) == {"True": 93, "False": 8}
    assert all(len(row) == 15 for row in rows)


def test_source_zone_matches_published_rounded_measurements() -> None:
    rows = _load_inventory()
    source = next(row for row in rows if row["zone_id"] == "43")
    # Supplementary Data 1; main text rounds this to 0.19 km^2, 4.4 m,
    # 276 degrees against 296 degrees downslope, and R approximately 0.92.
    assert abs(float(source["lon"]) - 85.5294) < 1e-8
    assert abs(float(source["lat"]) - 28.29161) < 1e-8
    assert abs(float(source["area_km2"]) - 0.192) < 1e-9
    assert int(source["n_epochs"]) == 3
    assert abs(float(source["res_mag_m"]) - 4.38) < 1e-9
    assert abs(float(source["disp_az"]) - 276.3) < 1e-9
    assert abs(float(source["downslope_az"]) - 296.1) < 1e-9
    assert abs(float(source["d_downslope"]) - 19.8) < 1e-9
    assert abs(float(source["R_res"]) - 0.915) < 1e-9
    assert source["glacier"] == "True"
    assert source["RGIId"] == "RGI60-15.04173"


def test_benchmark_contains_exact_paper_pair_ids_and_five_interval_statistics() -> None:
    benchmark = _load_benchmark()
    assert benchmark["schema_version"] == "know-place-author-benchmark/1.1"
    pairs = benchmark["exact_author_granules"]
    assert len(pairs) == 5
    assert all("_P05023_" in item["id"] for item in pairs)
    assert all("X05026" not in item["id"] for item in pairs)
    assert [item["days"] for item in pairs] == [12, 12, 12, 24, 12]
    metrics = benchmark["published_site_series"]
    assert metrics["columns"] == [
        "20 Jun-2 Jul", "2-14 Jul", "14-26 Jul", "26 Jul-19 Aug", "19-31 Aug"
    ]
    assert metrics["displacement_valid_crown_pixels"] == [283, 294, 296, 292, 195]
    assert metrics["polygon_null_R_valid_crown_pixels"] == [302, 299, 302, 298, 202]
    assert metrics["count_estimand_sources"] == {
        "displacement_valid_crown_pixels": {"archive_file": "tables/nisar_pot_series.json", "field": "n"},
        "polygon_null_R_valid_crown_pixels": {"archive_file": "tables/polygon_null.json", "field": "n_px"},
        "note": "These are distinct estimands. The former valid_crown_pixels key was ambiguous and has been removed.",
    }
    assert "valid_crown_pixels" not in metrics
    assert metrics["median_crown_displacement_m"] == [0.99, 0.54, 0.30, 0.96, 0.33]
    assert metrics["median_crown_rate_cm_per_day"] == [8.3, 4.5, 2.5, 4.0, 2.7]
    assert metrics["displacement_null_percentile"] == [94.9, 87.5, 81.0, 94.7, 81.3]
    assert metrics["polygon_null_R_percentile"] == [77.2, 23.3, 39.8, 85.2, 29.1]


def test_published_crown_geometry_and_detection_claim_boundary_are_frozen() -> None:
    benchmark = _load_benchmark()
    spatial = benchmark["spatial_definition"]
    assert spatial["crs"] == "EPSG:4326"
    assert spatial["crown_wkt"] == (
        "POLYGON ((85.5245 28.2847, 85.5400 28.2847, "
        "85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))"
    )
    assert abs(float(spatial["crown_area_km2"]) - 2.07) < 1e-9
    interpretation = benchmark["interpretation"]
    assert interpretation["hazard_detection_status"] == "NOT_EVALUATED"
    assert interpretation["paper_reproduction_status"].startswith("BLOCKED_")
    assert "X05026" in interpretation["source_variant_mismatch"]
    assert "no acceleration is resolved" in interpretation["paper_conclusion"].lower()
