from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from tools.know_place.dashboard import build_dashboard_html, write_dashboard


def test_dashboard_contains_displacement_chart_spatial_preview_and_scientific_gates(tmp_path):
    report = {
        "schema_version": "know-place-aoi-result/1.0",
        "engine_version": "1.0.0",
        "status": "SCIENTIFIC_METRICS_COMPUTED",
        "structural_status": "PASS",
        "measurement_status": "METRICS_COMPUTED",
        "paper_reproduction_status": "NOT_EVALUATED_GENERIC_AOI",
        "hazard_detection_status": "NOT_EVALUATED",
        "request_sha256": "a" * 64,
        "source_adapters": ["NISAR_GOFF"],
        "reference_policy": "explicit test",
        "request": {
            "aoi": {"wkt": "POLYGON ((85 28, 86 28, 86 29, 85 29, 85 28))"},
            "date_range": {"start": "2026-06-20", "end": "2026-08-31"},
        },
        "motion_dynamics": {
            "status": "DESCRIPTIVE_MOTION_FEATURES_COMPUTED",
            "hazard_detection_status": "NOT_EVALUATED",
            "pairs": [{
                "reference_date": "2026-07-26",
                "secondary_date": "2026-08-19",
                "chain_id": "098-A-HH-PROVISIONAL-P05023",
                "median_horizontal_displacement_rate_m_per_day": 0.04,
                "mean_vector_magnitude_rate_m_per_day": 0.0717,
                "vector_rate_acceleration_m_per_day_squared": None,
                "vector_rate_change_eligible": False,
                "rate_change_block_reason": "INSTRUMENT_GAP_CROSSES_INTERVAL",
            }],
        },
        "pairs": [{
            "reference_date": "2026-07-26",
            "secondary_date": "2026-08-19",
            "interval_days": 24.0,
            "granule_name": "NISAR_L2_PR_GOFF_TEST.h5",
            "release_id": "P05023",
            "epsg": 32645,
            "status": "METRICS_COMPUTED",
            "valid_aoi_pixels": 147,
            "aoi_total_grid_cells": 160,
            "valid_aoi_fraction": 147 / 160,
            "high_magnitude_flagged_pixels": 2,
            "grid_lattice_compatible_with_previous": True,
            "grid_identity_sha256": "b" * 64,
            "geotiff_file": "maps/pair_displacement.tif",
            "statistics": {
                "crown_median_horizontal_magnitude_m": 0.96,
                "crown_mean_vector_magnitude_m": 1.72,
                "crown_mean_vector_azimuth_deg_clockwise_from_north": 278.0,
                "crown_median_directional_coherence_R": 0.87,
                "aoi_median_magnitude_rate_m_per_day": 0.04,
            },
            "map_preview": {
                "values": [[0.1, 0.2], [None, 0.5]],
                "east_values_m": [[1.0, 0.0], [None, -1.0]],
                "north_values_m": [[0.0, 1.0], [None, 0.0]],
                "min_x_m": 100.0, "max_y_m": 200.0,
                "pixel_size_x_m": 80.0, "pixel_size_y_m": 80.0,
                "aoi_ring_xy": [[100.0,200.0],[180.0,200.0],[180.0,120.0],[100.0,120.0],[100.0,200.0]],
                "reference_ring_xy": [[20.0,200.0],[80.0,200.0],[80.0,160.0],[20.0,160.0],[20.0,200.0]],
            },
            "spatial_block_bootstrap_uncertainty": {
                "status": "COMPUTED_EXPLORATORY",
                "statistics": {
                    "median_horizontal_magnitude_95pct_interval_m": [0.8, 1.1],
                },
            },
            "spatial_block_bootstrap_sensitivity": {
                "status": "COMPUTED_EXPLORATORY",
                "rows": [
                    {"block_size_cells": 3, "status": "COMPUTED_EXPLORATORY", "median_horizontal_magnitude_95pct_interval_m": [0.7, 1.2]},
                    {"block_size_cells": 5, "status": "COMPUTED_EXPLORATORY", "median_horizontal_magnitude_95pct_interval_m": [0.8, 1.1]},
                    {"block_size_cells": 10, "status": "COMPUTED_EXPLORATORY", "median_horizontal_magnitude_95pct_interval_m": [0.6, 1.3]},
                ],
            },
        }],
    }
    rendered = build_dashboard_html(report)

    assert "SARGuardian — Know Place Analysis" in rendered
    assert "0.960 m" in rendered
    assert "PAPER_REPRODUCTION" not in rendered or "NOT_EVALUATED_GENERIC_AOI" in rendered
    assert "Hazard detection" in rendered
    assert "No raster preview available" in rendered or "pairMaps" in rendered
    assert "map-canvas-0" in rendered
    assert "pair_displacement.tif" in rendered
    assert "Valid / total AOI pixels" in rendered
    assert "147 / 160" in rendered
    assert "Block-size CI sensitivity" in rendered
    assert "3-cell: 0.700–1.200 m" in rendered
    assert "Direction arrows are orientation-only" in rendered
    assert "referenceRing" in rendered and "setLineDash([5,3])" in rendered
    assert "White outline: measurement polygon. Dashed blue outline: reference/background polygon." in rendered
    assert "Interval-average magnitude rate" in rendered
    assert "0.0400 m/day" in rendered
    assert "Midpoint separation: 24.000 d" in rendered
    assert "not instantaneous velocity" in rendered
    assert "Descriptive motion dynamics — not a hazard score" in rendered
    assert "INSTRUMENT_GAP_CROSSES_INTERVAL" in rendered
    assert "0.0717 m/day" in rendered
    assert "Grid identity SHA-256" in rendered
    assert "b" * 64 in rendered
    assert "https://" not in rendered  # no CDN/external dependency
    target = write_dashboard(report, tmp_path / "dashboard.html")
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == rendered


def test_dashboard_escapes_user_html_and_script_terminator():
    report = {
        "request": {
            "aoi": {"wkt": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"},
            "date_range": {"start": "2026-01-01", "end": "2026-01-02"},
            "label": "</script><script>alert(1)</script>",
        },
        "pairs": [{
            "reference_date": "2026-01-01",
            "secondary_date": "2026-01-02",
            "granule_name": "</script><script>alert(1)</script>",
            "map_preview": {"values": [[0.1]], "aoi_ring_xy": []},
        }],
    }
    rendered = build_dashboard_html(report)
    assert "</script><script>alert(1)" not in rendered
    assert "&lt;/script&gt;&lt;script&gt;alert(1)" in rendered


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_rendered_dashboard_javascript_passes_node_syntax_check(tmp_path):
    rendered = build_dashboard_html({
        "request": {
            "aoi": {"wkt": "POLYGON ((85 28, 86 28, 86 29, 85 29, 85 28))"},
            "date_range": {"start": "2026-06-20", "end": "2026-08-31"},
        },
        "pairs": [{
            "reference_date": "2026-07-26",
            "secondary_date": "2026-08-19",
            "chain_id": "098-A-HH-PROVISIONAL-P05023",
            "relation_to_previous": "CONTIGUOUS",
            "grid_lattice_compatible_with_previous": True,
            "map_preview": {
                "values": [[0.1, 0.2], [0.3, 0.4]],
                "east_values_m": [[1.0, 0.0], [0.0, -1.0]],
                "north_values_m": [[0.0, 1.0], [-1.0, 0.0]],
                "aoi_ring_xy": [[0,0],[1,0],[1,1],[0,1],[0,0]],
            },
        }],
    })
    match = re.search(r"<script>\s*(.*?)\s*</script>", rendered, flags=re.DOTALL)
    assert match, "dashboard must contain its self-contained JavaScript"
    script_path = tmp_path / "dashboard.js"
    script_path.write_text(match.group(1), encoding="utf-8")
    checked = subprocess.run(
        [shutil.which("node"), "--check", str(script_path)],
        capture_output=True, text=True, check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
