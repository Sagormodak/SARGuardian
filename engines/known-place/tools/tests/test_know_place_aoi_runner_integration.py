from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from tools.know_place.aoi_request import REQUEST_SCHEMA
from tools.know_place.goff_io import parse_granule_identity
from tools.know_place.geometry import parse_polygon_wkt
from tools.know_place import aoi_runner
from tools.tests.test_know_place_analyze import (
    BOX_WKT,
    CROWN_WKT,
    PAIRS,
    _granule_name,
    _write_goff,
)


def _canonical_test_wkt(value: str) -> str:
    ring = parse_polygon_wkt(value)
    return "POLYGON ((" + ", ".join(f"{lon:.9f} {lat:.9f}" for lon, lat in ring) + "))"


def test_synthetic_five_pair_aoi_pipeline_emits_verified_bundle_and_deletes_ephemeral_sources(
    tmp_path, monkeypatch
):
    """End-to-end known-answer run with mocked catalog/download, real science kernels."""
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    box_points = [
        (85.500000, 28.265000),
        (85.565000, 28.265000),
        (85.565000, 28.318000),
        (85.500000, 28.318000),
    ]
    bx, by = transformer.transform(
        [point[0] for point in box_points], [point[1] for point in box_points]
    )
    # Include enough local context for the automatic 2 km background ring.
    x0 = np.floor(min(bx) / 80.0) * 80.0 - 5000.0
    x1 = np.ceil(max(bx) / 80.0) * 80.0 + 5000.0
    y0 = np.floor(min(by) / 80.0) * 80.0 - 5000.0
    y1 = np.ceil(max(by) / 80.0) * 80.0 + 5000.0
    x = np.arange(x0, x1 + 0.1, 80.0, dtype=np.float64)
    y = np.arange(y0, y1 + 0.1, 80.0, dtype=np.float64)

    original_sources = tmp_path / "fixture-sources"
    original_sources.mkdir()
    source_records = []
    for start, end in PAIRS:
        name = _granule_name(start, end)
        source = original_sources / name
        _write_goff(source, x=x, y=y, east_motion=0.5)
        source_records.append({
            "granule_name": name,
            "reference_date": start,
            "secondary_date": end,
            "track": "098",
            "direction": "A",
            "polarization": "HH",
            "release_id": "P05023",
            "maturity": "PROVISIONAL",
            "catalog_maturity": "PROVISIONAL",
            "source_bytes": source.stat().st_size,
            "source_file": source,
            "download_url": f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/{name}",
            "decision": "ELIGIBLE_CATALOG_CANDIDATE",
        })

    catalog_manifest = {
        "schema_version": "know-place-aoi-catalog-manifest/1.0",
        "catalog": "mocked ASF catalog for integration test",
        "query": {"processing_level": "GOFF", "intersects_wkt_sha256": "synthetic"},
        "result_count": 5,
        "eligible_count": 5,
        "candidates": [
            {key: value for key, value in row.items() if key not in {"source_file", "download_url"}}
            for row in source_records
        ],
    }
    monkeypatch.setattr(
        aoi_runner,
        "discover_nisar_goff",
        lambda request: (source_records, catalog_manifest),
    )
    monkeypatch.setattr(aoi_runner, "_session_from_environment", lambda: object())

    def fake_download(record, cache_dir, session):
        source = record["source_file"]
        product_dir = cache_dir / hashlib.sha256(record["granule_name"].encode("utf-8")).hexdigest()[:16]
        product_dir.mkdir(parents=True, exist_ok=True)
        target = product_dir / record["granule_name"]
        target.write_bytes(source.read_bytes())
        receipt_path = product_dir / f"{record['granule_name']}.source-receipt.json"
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps({
            "granule_name": record["granule_name"],
            "source_sha256": digest,
            "source_bytes": target.stat().st_size,
            "release_id": record["release_id"],
            "maturity": record["maturity"],
        }), encoding="utf-8")
        return target, {
            "granule_name": record["granule_name"],
            "release_id": record["release_id"],
            "maturity": record["maturity"],
            "source_sha256": digest,
            "source_bytes": target.stat().st_size,
            "cache_status": "DOWNLOADED_AND_HASHED",
        }

    monkeypatch.setattr(aoi_runner, "_download_exact_product", fake_download)
    # Keep the integration test independent of optional rasterio/affine binaries;
    # all statistics, masks, NPZ arrays, HTML and checksums are produced normally.
    monkeypatch.setattr(
        aoi_runner,
        "_write_geotiff",
        lambda path, *args, **kwargs: Path(path).write_bytes(b"synthetic-geotiff-placeholder"),
    )

    reference_wkt = (
        "POLYGON ((85.505000 28.285000, 85.520000 28.285000, "
        "85.520000 28.297000, 85.505000 28.297000, 85.505000 28.285000))"
    )
    request = {
        "schema_version": REQUEST_SCHEMA,
        "aoi": {"type": "Polygon", "crs": "EPSG:4326", "wkt": CROWN_WKT},
        "scope_aoi": {"type": "Polygon", "crs": "EPSG:4326", "wkt": BOX_WKT},
        "reference": {
            "policy": "external_reference_polygon_component_median",
            "polygon_wkt": reference_wkt,
        },
        "date_range": {"start": "2026-06-20", "end": "2026-08-31", "inclusive": True},
        "hazard_mode": "ice_rock_avalanche",
        "analysis_mode": "retrospective_validation",
        "source_adapters": ["NISAR_GOFF"],
        "polarization": "HH",
        "product_selection": {
            "track": "098",
            "direction": "A",
            "preferred_granules": [_granule_name(a, b) for a, b in PAIRS],
            "allowed_maturities": ["PROVISIONAL"],
        },
        "quality_policy": {
            "minimum_snr": 5.0,
            "maximum_horizontal_magnitude_m": 10.0,
            "magnitude_policy": "reject_above_threshold",
        },
        "coherence_policy": {"window_size": 5, "minimum_valid_neighbours": 1},
    }

    output_root = tmp_path / "results"
    cache_root = tmp_path / "ephemeral-cache"
    result = aoi_runner.run_aoi_analysis(
        request, output_root, cache_root=cache_root, ephemeral_source_cache=True,
    )

    run_dirs = [
        directory for directory in output_root.iterdir()
        if directory.is_dir() and (directory / "manifest.json").is_file()
    ]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    saved = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result["status"] == "SCIENTIFIC_METRICS_COMPUTED"
    assert result["structural_status"] == "PASS"
    assert result["measurement_status"] == "METRICS_COMPUTED_ALL_PAIRS"
    assert result["paper_reproduction_status"] == "NOT_EVALUATED_GENERIC_AOI"
    assert result["hazard_detection_status"] == "NOT_EVALUATED"
    assert result["motion_dynamics"]["status"] == "DESCRIPTIVE_MOTION_FEATURES_COMPUTED"
    assert result["motion_dynamics"]["risk_score"] is None
    assert result["motion_dynamics"]["hazard_detection_status"] == "NOT_EVALUATED"
    assert len(result["motion_dynamics"]["pairs"]) == 5
    assert result["reference_policy"] == "external_reference_polygon_component_median"
    assert result["request"]["reference"]["polygon_wkt"] == _canonical_test_wkt(reference_wkt)
    assert result["request"]["scope_aoi"]["wkt"] == _canonical_test_wkt(BOX_WKT)
    assert result["pair_measurement_counts"] == {
        "requested": 5, "metrics_computed": 5, "insufficient_data": 0,
    }
    assert result["grid_compatibility_status"] == "CONSISTENT_LATTICE_WITHIN_CHAINS"
    assert result["grid_mismatch_pair_count"] == 0
    assert all(pair["status"] == "METRICS_COMPUTED" for pair in result["pairs"])
    assert all(pair["grid_identity_sha256"] for pair in result["pairs"])
    assert all(pair["source_sha256"] for pair in result["pairs"])
    assert all(pair["reference_policy"] == "APPLIED_EXTERNAL_REFERENCE_POLYGON_COMPONENT_MEDIAN" for pair in result["pairs"])
    assert all(pair["reference_geometry"]["type"] == "INDEPENDENT_USER_POLYGON" for pair in result["pairs"])
    assert all(pair["reference_geometry"]["stability_status"] == "USER_SELECTED_NOT_INDEPENDENTLY_VERIFIED" for pair in result["pairs"])
    assert all(pair["reference_geometry"]["overlap_status"] == "NO_OVERLAP_OR_TOUCH_VERIFIED_ON_PROJECTED_POLYGONS" for pair in result["pairs"])
    assert all(pair["reference_geometry"]["outer_aoi_status"] == "BOTH_POLYGONS_VERIFIED_INSIDE_OUTER_AOI" for pair in result["pairs"])
    assert all(pair["background_correction"]["background_valid_pixels"] == pair["reference_geometry"]["reference_grid_cells"] for pair in result["pairs"])
    assert all(pair["background_correction"]["background_east_bias_m"] == pytest.approx(0.0, abs=1e-8) for pair in result["pairs"])
    assert all(pair["background_correction"]["background_north_bias_m"] == pytest.approx(0.0, abs=1e-8) for pair in result["pairs"])
    for pair in result["pairs"]:
        identity = parse_granule_identity(pair["granule_name"])
        reference_midpoint = identity.reference_start + (identity.reference_end - identity.reference_start) / 2
        secondary_midpoint = identity.secondary_start + (identity.secondary_end - identity.secondary_start) / 2
        expected_days = (secondary_midpoint - reference_midpoint).total_seconds() / 86400.0
        assert pair["interval_days"] == pytest.approx(expected_days)
        assert pair["interval_average_rate_definition"].startswith("pairwise displacement / exact acquisition-midpoint separation")
        stats = pair["statistics"]
        assert stats["aoi_median_magnitude_rate_m_per_day"] == pytest.approx(
            stats["aoi_median_horizontal_magnitude_m"] / expected_days
        )
    assert all(pair["spatial_block_bootstrap_sensitivity"]["sizes_tested_cells"] == [3, 5, 10] for pair in result["pairs"])
    assert all(pair["spatial_block_bootstrap_sensitivity"]["status"] in {"COMPUTED_EXPLORATORY", "PARTIAL_INSUFFICIENT_BLOCK_SUPPORT"} for pair in result["pairs"])
    assert all(pair["statistics"]["aoi_median_horizontal_magnitude_m"] == pair["statistics"]["crown_median_horizontal_magnitude_m"] for pair in result["pairs"])
    target = next(pair for pair in result["pairs"] if pair["reference_date"] == "2026-07-26")
    assert target["secondary_date"] == "2026-08-19"
    assert len(target["known_instrument_data_gaps"]) == 1
    assert "cannot localize onset" in target["interval_coverage_warning"]
    dashboard_html = (run_dir / "visuals" / "dashboard.html").read_text(encoding="utf-8")
    assert "2026-07-27T22:03:25Z" in dashboard_html
    assert "Descriptive motion dynamics — not a hazard score" in dashboard_html
    assert "not a calibrated probability of failure" in dashboard_html
    assert (run_dir / "timeseries.csv").is_file()
    assert (run_dir / "motion-features.csv").is_file()
    with (run_dir / "motion-features.csv").open(encoding="utf-8", newline="") as stream:
        motion_rows = list(csv.DictReader(stream))
    assert len(motion_rows) == 5
    assert "vector_rate_acceleration_m_per_day_squared" in motion_rows[0]
    assert "risk_score" in motion_rows[0]
    assert all(row["risk_score"] == "" for row in motion_rows)
    assert all(row["risk_score_status"] == "NOT_CALIBRATED" for row in motion_rows)
    assert (run_dir / "visuals" / "dashboard.html").is_file()
    assert len(manifest["files"]) >= 16
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert manifest["raw_h5_retention"]["raw_h5_in_output_bundle"] is False
    assert manifest["raw_h5_retention"]["raw_h5_retained_in_external_cache"] is False
    assert "deleted immediately" in manifest["raw_h5_retention"]["source_cache_policy"]
    assert not list(cache_root.rglob("*.h5"))
    assert len(list((run_dir / "maps").glob("*_displacement.tif"))) == 5
    assert len(saved["pairs"]) == 5
