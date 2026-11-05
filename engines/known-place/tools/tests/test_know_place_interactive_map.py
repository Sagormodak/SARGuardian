from __future__ import annotations

import re
import shutil
import subprocess

from tools.know_place.interactive_map import (
    _map_payload,
    _preview_bounds_wgs84,
    build_interactive_map_html,
    write_interactive_map,
)


def sample_report():
    return {
        "schema_version": "know-place-aoi-result/1.0",
        "structural_status": "PASS",
        "measurement_status": "METRICS_COMPUTED",
        "paper_reproduction_status": "NOT_EVALUATED_GENERIC_AOI",
        "hazard_detection_status": "NOT_EVALUATED",
        "request": {
            "aoi": {
                "type": "Polygon", "crs": "EPSG:4326",
                "wkt": "POLYGON ((85.0 28.0, 85.01 28.0, 85.01 28.01, 85.0 28.01, 85.0 28.0))",
            },
            "date_range": {"start": "2026-06-20", "end": "2026-08-31", "inclusive": True},
        },
        "pairs": [{
            "reference_date": "2026-07-26", "secondary_date": "2026-08-19", "interval_days": 24.0,
            "release_id": "P05023", "status": "METRICS_COMPUTED", "epsg": 32645,
            "valid_aoi_pixels": 147, "aoi_total_grid_cells": 160,
            "valid_aoi_fraction": 147 / 160, "high_magnitude_flagged_pixels": 2,
            "source_sha256": "b" * 64, "geotiff_file": "maps/pair_displacement.tif",
            "statistics": {"aoi_median_horizontal_magnitude_m": 0.96, "aoi_median_magnitude_rate_m_per_day": 0.04},
            "map_preview": {
                "values": [[0.1, 0.2], [None, 0.5]],
                "min_x_m": 300000.0, "max_y_m": 3100000.0,
                "pixel_size_x_m": 80.0, "pixel_size_y_m": 80.0, "stride_cells": 4,
            },
        }],
    }


def test_preview_bounds_transform_projected_grid_to_wgs84():
    bounds = _preview_bounds_wgs84({
        "values": [[0.1, 0.2], [0.3, 0.4]],
        "min_x_m": 300000.0, "max_y_m": 3100000.0,
        "pixel_size_x_m": 80.0, "pixel_size_y_m": 80.0,
    }, 32645)
    assert bounds is not None
    (south, west), (north, east) = bounds
    assert 27.0 < south < north < 29.0
    assert 84.0 < west < east < 86.0


def test_preview_bounds_fail_closed_for_missing_or_invalid_inputs():
    assert _preview_bounds_wgs84({}, 32645) is None
    assert _preview_bounds_wgs84({
        "values": [[1.0]], "min_x_m": 0, "max_y_m": 0,
        "pixel_size_x_m": 0, "pixel_size_y_m": 80,
    }, 32645) is None
    assert _preview_bounds_wgs84({
        "values": [[1.0]], "min_x_m": 0, "max_y_m": 0,
        "pixel_size_x_m": 80, "pixel_size_y_m": 80,
    }, "bad-epsg") is None


def test_interactive_map_has_aoi_pair_controls_preview_download_and_statuses(tmp_path):
    report = sample_report()
    rendered = build_interactive_map_html(report)
    payload = _map_payload(report)
    assert "Interactive measurement map" in rendered
    assert "tile.openstreetmap.org" in rendered
    assert "pair-select" in rendered
    assert "opacity" in rendered.lower()
    assert "show-aoi" in rendered
    assert "Zoom to both polygons" in rendered or "Zoom to all polygons" in rendered
    assert "Download native-grid GeoTIFF" in rendered
    assert "A native-grid GeoTIFF is available only if a link is shown" in rendered
    assert 'id="valid-pixels-label">Valid AOI pixels</small>' in rendered
    assert 'pair.high_magnitude_flagged_pixels==null?"—":String(pair.high_magnitude_flagged_pixels)' in rendered
    assert "Source measurement grid: " in rendered
    assert "PARTIAL — numeric checks match; original null-generator identity unverified" in rendered
    assert 'id="transparency-note"' in rendered
    assert "Transparent pixels mean no preview value, not zero motion." in rendered
    assert "P05023" in rendered
    assert payload["aoi_ring_lon_lat"][0] == [85.0, 28.0]
    assert payload["pairs"][0]["preview"]["bounds"] is not None
    assert payload["pairs"][0]["preview"]["stride_cells"] == 4
    assert payload["pairs"][0]["interval_days"] == 24.0
    assert 'id="preview-pixel-readout"' in rendered
    assert 'interactive:true' in rendered
    assert "Preview block median:" in rendered
    assert "not a native-pixel value or instantaneous velocity" in rendered
    assert "Download native-grid GeoTIFF" in rendered
    assert payload["pairs"][0]["geotiff_href"] == "../maps/pair_displacement.tif"
    assert payload["hazard_detection_status"] == "NOT_EVALUATED"
    target = write_interactive_map(report, tmp_path / "visuals" / "interactive-map.html")
    assert target.is_file() and target.read_text(encoding="utf-8") == rendered


def test_form_controls_are_constrained_to_the_mobile_panel_width():
    rendered = build_interactive_map_html(sample_report())
    assert ".layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:14px;min-width:0;width:100%;max-width:100%}" in rendered
    assert ".controls{display:grid;gap:12px;align-content:start;min-width:0;width:100%;max-width:100%}" in rendered
    assert ".field{display:grid;gap:5px;min-width:0;width:100%;max-width:100%}" in rendered
    assert "select,input[type=range]{display:block;width:100%;min-width:0;max-width:100%;box-sizing:border-box}" in rendered
    assert "#source-hash{overflow-wrap:anywhere;word-break:break-word}" in rendered
    assert 'const conciseLabel=dates+" · "+(pair.release_id||"release unknown")' in rendered
    assert "@media(max-width:920px){main{padding:12px}.layout{grid-template-columns:minmax(0,1fr);width:100%;max-width:100%}#map{height:55vh;min-height:340px}}" in rendered


def test_geometry_note_is_visible_escaped_and_absent_note_is_hidden():
    report = sample_report()
    report["request"]["aoi"]["geometry_note"] = "Published-bounds rectangle approximation; not the author vector. <script>alert(1)</script>"
    rendered = build_interactive_map_html(report)
    assert 'id="geometry-note"' in rendered
    assert "Published-bounds rectangle approximation; not the author vector." in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered

    report["request"]["aoi"].pop("geometry_note")
    hidden = build_interactive_map_html(report)
    assert 'class="muted hidden" id="geometry-note"' in hidden


def test_interactive_map_escapes_untrusted_html_and_script_payload():
    report = sample_report()
    report["request"]["aoi"]["wkt"] = "POLYGON ((85 28, 86 28, 86 29, 85 29, 85 28)) </script><script>alert(1)</script>"
    report["pairs"][0]["release_id"] = "</script><script>alert(1)</script>"
    rendered = build_interactive_map_html(report)
    assert "</script><script>alert(1)" not in rendered
    assert "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert r"\u003c/script\u003e\u003cscript\u003e" in rendered


def test_catalog_only_map_shows_aoi_without_claiming_zero_motion():
    report = sample_report()
    report["pairs"] = []
    report["measurement_status"] = "NOT_RUN_DRY_RUN"
    rendered = build_interactive_map_html(report)
    assert "NOT_RUN_DRY_RUN" in rendered
    assert "No measured pairs (catalog-only run)" in rendered
    assert "Missing product coverage or insufficient valid pixels must never be interpreted as evidence of safety." in rendered


def test_interactive_map_inline_javascript_syntax_if_node_available(tmp_path):
    if shutil.which("node") is None:
        import pytest
        pytest.skip("Node.js is not installed")
    rendered = build_interactive_map_html(sample_report())
    match = re.search(r"<script>\s*(.*?)\s*</script>", rendered, flags=re.DOTALL)
    assert match
    script_path = tmp_path / "interactive-map.js"
    script_path.write_text(match.group(1), encoding="utf-8")
    checked = subprocess.run([shutil.which("node"), "--check", str(script_path)], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr

def test_interactive_map_keeps_outer_measurement_and_reference_polygons_distinct():
    report = sample_report()
    report["request"]["scope_aoi"] = {
        "type": "Polygon",
        "crs": "EPSG:4326",
        "role": "outer_selection_boundary",
        "wkt": "POLYGON ((84.99 27.99, 85.02 27.99, 85.02 28.02, 84.99 28.02, 84.99 27.99))",
    }
    report["request"]["reference"] = {
        "policy": "external_reference_polygon_component_median",
        "polygon_wkt": "POLYGON ((84.995 28.001, 85.002 28.001, 85.002 28.008, 84.995 28.008, 84.995 28.001))",
        "warning": "User-selected comparison area; stability is not independently verified.",
    }
    rendered = build_interactive_map_html(report)
    payload = _map_payload(report)

    assert payload["scope_aoi_ring_lon_lat"][0] == [84.99, 27.99]
    assert payload["aoi_ring_lon_lat"][0] == [85.0, 28.0]
    assert payload["reference_ring_lon_lat"][0] == [84.995, 28.001]
    assert "Outer AOI boundary:" in rendered
    assert "Measurement polygon:" in rendered
    assert "Reference polygon:" in rendered
    assert 'id="show-scope-aoi"' in rendered
    assert 'id="show-aoi"' in rendered
    assert 'id="show-reference"' in rendered
    assert "Zoom to all polygons" in rendered
    assert "User-selected comparison area; stability is not independently verified." in rendered

