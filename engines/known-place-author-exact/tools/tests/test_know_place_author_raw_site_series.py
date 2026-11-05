from __future__ import annotations

from types import SimpleNamespace
import json
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from affine import Affine

from tools.know_place.author_raw_site_series import (
    AUTHOR_CROWN_BOUNDS,
    AUTHOR_WIDE_BOUNDS,
    _assert_author_bounds,
    compare_pair_to_archive,
    compare_p2_pair_to_archive,
    process_author_pair_arrays,
    project_author_p2_window,
)
from tools.know_place.author_parity import (
    AuthorParityError, author_crown_slice, author_local_mean_reference_statistics, author_north_up,
    author_wide_window_slices,
)
from tools.know_place.footprint_screen import local_nanmean, residual_directional_coherence


def _wkt(bounds):
    west, south, east, north = bounds
    return (
        f"POLYGON (({west} {south}, {east} {south}, {east} {north}, "
        f"{west} {north}, {west} {south}))"
    )


def _synthetic_pair():
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    corners = [
        transformer.transform(AUTHOR_WIDE_BOUNDS[0], AUTHOR_WIDE_BOUNDS[1]),
        transformer.transform(AUTHOR_WIDE_BOUNDS[0], AUTHOR_WIDE_BOUNDS[3]),
        transformer.transform(AUTHOR_WIDE_BOUNDS[2], AUTHOR_WIDE_BOUNDS[1]),
        transformer.transform(AUTHOR_WIDE_BOUNDS[2], AUTHOR_WIDE_BOUNDS[3]),
    ]
    xmin = min(point[0] for point in corners)
    xmax = max(point[0] for point in corners)
    ymin = min(point[1] for point in corners)
    ymax = max(point[1] for point in corners)

    # North-up row order (descending Y), analogous to the GOFF grid.
    x = np.linspace(xmin, xmax, 91)
    y = np.linspace(ymax, ymin, 81)
    xx, yy = np.meshgrid(x, y)
    at = (
        0.35
        + 0.45 * np.sin((xx - xmin) / 410.0)
        + 0.20 * np.cos((yy - ymin) / 370.0)
    )
    sr = 0.08 * np.sin((xx + yy) / 900.0)
    snr = np.full(at.shape, 12.0)

    gx = np.linspace(xmin - 1000.0, xmax + 1000.0, 31)
    gy = np.linspace(ymin - 1000.0, ymax + 1000.0, 29)  # increasing axes
    heights = np.array([4500.0, 5000.0, 5500.0])
    shape = (heights.size, gy.size, gx.size)
    incidence = np.empty(shape, dtype=float)
    incidence[0] = 34.0
    incidence[1] = 35.0
    incidence[2] = 36.0
    cubes = SimpleNamespace(
        metadata_epsg=32645,
        group_path="mock/radarGrid",
        x_m=gx,
        y_m=gy,
        height_m=heights,
        incidence_deg=incidence,
        los_x=np.full(shape, 0.6),
        los_y=np.full(shape, 0.8),
        along_track_x=np.full(shape, 0.4),
        along_track_y=np.full(shape, 0.9),
        unit_evidence={"incidence": "degrees", "vectors": "unitless"},
    )
    return at, sr, snr, x, y, cubes


def test_author_profile_rejects_changed_crown_or_reference_bounds():
    config = {
        "crown_wkt": _wkt(AUTHOR_CROWN_BOUNDS),
        "reference_box_wkt": _wkt(AUTHOR_WIDE_BOUNDS),
    }
    _assert_author_bounds(config)

    config["crown_wkt"] = _wkt((85.5240, 28.2847, 85.5400, 28.2970))
    with pytest.raises(ValueError, match="AUTHOR_PROFILE_CROWN_BOUNDS_MISMATCH"):
        _assert_author_bounds(config)


def test_raw_pair_uses_author_geometry_gate_reference_and_null_policy():
    at, sr, snr, x, y, cubes = _synthetic_pair()
    result = process_author_pair_arrays(
        along_track_m=at,
        slant_range_m=sr,
        snr=snr,
        x_coordinates_m=x,
        y_coordinates_m=y,
        epsg=32645,
        geometry_cubes=cubes,
        interval_days=24,
        polygon_null_rng=np.random.default_rng(20260907),
    )

    assert result["geometry"]["incidence_deg"] == pytest.approx(35.0)
    assert result["geometry"]["sample_policy"] == (
        "nearest radarGrid XY cell; nanmedian over height-axis samples"
    )
    assert result["quality"]["correlation_field_is_not_used_by_author_quality_gate"] is True
    assert result["quality"]["author_valid_cells_after_snr_and_magnitude_gates"] > 0
    assert result["reference_correction"]["ring_valid_cells"] > 200
    assert result["reference_correction"]["correction_applied"] is True

    arrays = result["arrays"]
    shape = at.shape
    for name in (
        "east_m", "north_m", "horizontal_magnitude_m",
        "directional_coherence_R", "valid_mask", "inside_aoi_mask", "crown_mask",
    ):
        assert arrays[name].shape == shape
    assert result["site_series"]["displacement_valid_crown_cells"] > 0
    assert 0.0 <= result["site_series"]["P1_R_crown"] <= 1.0
    assert result["polygon_null"]["candidate_centres_examined"] <= 1200
    assert result["polygon_null"]["accepted_draws"] > 0


def test_five_pair_archive_comparison_covers_thirteen_same_estimand_checks():
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "docs" / "know-place" / "reference" / "author_benchmark_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = fixture["published_site_series"]
    for index in range(5):
        site = {
            "displacement_valid_crown_cells": expected["displacement_valid_crown_pixels"][index],
            "crown_median_displacement_m": expected["median_crown_displacement_m"][index],
            "crown_median_rate_cm_per_day": expected["median_crown_rate_cm_per_day"][index],
            "P1_R_crown": expected["bulk_reference_crown_R"][index],
            "P1_R_background": expected["bulk_reference_background_R"][index],
        }
        null = {
            "crown_valid_R_cells": expected["polygon_null_R_valid_crown_pixels"][index],
            "crown_R": expected["single_field_crown_R"][index],
            "box_R": expected["bulk_reference_background_R"][index],
            "crown_percentile_strict_less_than": expected["polygon_null_R_percentile"][index],
            "fraction_controls_strictly_above_box": expected["polygon_null_samples_beating_box_mean_percent"][index],
            "null_p5": expected["polygon_null_R_5th_percentile"][index],
            "null_p95": expected["polygon_null_R_95th_percentile"][index],
            "accepted_draws": expected["polygon_null_accepted_draws"][index],
        }
        comparison = compare_pair_to_archive(site, null, index, fixture)
        assert comparison["status"] == "PASS_AT_ARCHIVE_ROUNDING"
        assert comparison["checks_passed"] == comparison["checks_total"] == 13


def test_archive_comparison_flags_a_real_mismatch():
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "docs" / "know-place" / "reference" / "author_benchmark_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = fixture["published_site_series"]
    site = {
        "displacement_valid_crown_cells": expected["displacement_valid_crown_pixels"][0],
        "crown_median_displacement_m": expected["median_crown_displacement_m"][0] + 0.02,
        "crown_median_rate_cm_per_day": expected["median_crown_rate_cm_per_day"][0],
        "P1_R_crown": expected["bulk_reference_crown_R"][0],
        "P1_R_background": expected["bulk_reference_background_R"][0],
    }
    null = {
        "crown_valid_R_cells": expected["polygon_null_R_valid_crown_pixels"][0],
        "crown_R": expected["single_field_crown_R"][0],
        "box_R": expected["bulk_reference_background_R"][0],
        "crown_percentile_strict_less_than": expected["polygon_null_R_percentile"][0],
        "fraction_controls_strictly_above_box": expected["polygon_null_samples_beating_box_mean_percent"][0],
        "null_p5": expected["polygon_null_R_5th_percentile"][0],
        "null_p95": expected["polygon_null_R_95th_percentile"][0],
        "accepted_draws": expected["polygon_null_accepted_draws"][0],
    }
    comparison = compare_pair_to_archive(site, null, 0, fixture)
    assert comparison["status"] == "MISMATCH"
    assert comparison["checks_passed"] == 12
    assert comparison["checks_total"] == 13


def _halo_field_arrays():
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    corners = [
        transformer.transform(AUTHOR_WIDE_BOUNDS[0], AUTHOR_WIDE_BOUNDS[1]),
        transformer.transform(AUTHOR_WIDE_BOUNDS[0], AUTHOR_WIDE_BOUNDS[3]),
        transformer.transform(AUTHOR_WIDE_BOUNDS[2], AUTHOR_WIDE_BOUNDS[1]),
        transformer.transform(AUTHOR_WIDE_BOUNDS[2], AUTHOR_WIDE_BOUNDS[3]),
    ]
    xmin = min(point[0] for point in corners)
    xmax = max(point[0] for point in corners)
    ymin = min(point[1] for point in corners)
    ymax = max(point[1] for point in corners)
    x = np.linspace(xmin - 2500.0, xmax + 2500.0, 131)
    y = np.linspace(ymax + 2500.0, ymin - 2500.0, 131)
    xx, yy = np.meshgrid(x, y)
    east = 0.8 + 0.16 * np.sin((xx - xmin) / 700.0) + 0.05 * np.cos((yy - ymin) / 510.0)
    north = 0.3 + 0.11 * np.cos((xx - xmin) / 580.0) + 0.08 * np.sin((yy - ymin) / 830.0)
    east = east.astype(float)
    north = north.astype(float)
    east[::23, ::19] = np.nan
    north[::23, ::19] = np.nan
    return east, north, x, y


def test_p2_local_mean_reference_uses_halo_and_is_translation_invariant():
    east, north, x, y = _halo_field_arrays()
    result = author_local_mean_reference_statistics(
        east, north, x, y, 32645,
        local_window=41,
        crown_bounds_lonlat=AUTHOR_CROWN_BOUNDS,
        box_bounds_lonlat=AUTHOR_WIDE_BOUNDS,
    )
    translated = author_local_mean_reference_statistics(
        east + 3.25, north - 1.75, x, y, 32645,
        local_window=41,
        crown_bounds_lonlat=AUTHOR_CROWN_BOUNDS,
        box_bounds_lonlat=AUTHOR_WIDE_BOUNDS,
    )

    assert result["required_halo_pixels_per_side"] == 22
    assert result["box_slice_in_halo"]["row_start"] >= 22
    assert result["box_slice_in_halo"]["col_start"] >= 22
    assert result["box_slice_in_halo"]["row_stop"] <= east.shape[0] - 22
    assert result["box_slice_in_halo"]["col_stop"] <= east.shape[1] - 22
    assert 0.0 <= result["P2_R_crown"] <= 1.0
    assert 0.0 <= result["P2_R_background"] <= 1.0
    assert result["P2_resolved"] is (result["P2_R_crown"] > result["P2_R_background"])
    assert translated["P2_R_crown"] == pytest.approx(result["P2_R_crown"], abs=2e-5)
    assert translated["P2_R_background"] == pytest.approx(result["P2_R_background"], abs=2e-5)
    assert translated["P2_resolved"] is result["P2_resolved"]


def test_p2_archive_comparison_covers_all_three_table_s4_columns_and_flags_mismatch():
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "docs" / "know-place" / "reference" / "author_benchmark_v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = fixture["published_site_series"]
    for index in range(5):
        p2 = {
            "P2_R_crown": expected["local_mean_reference_crown_R"][index],
            "P2_R_background": expected["local_mean_reference_background_R"][index],
            "P2_resolved": (
                expected["local_mean_reference_crown_R"][index]
                > expected["local_mean_reference_background_R"][index]
            ),
        }
        comparison = compare_p2_pair_to_archive(p2, index, fixture)
        assert comparison["status"] == "PASS_AT_ARCHIVE_ROUNDING"
        assert comparison["checks_passed"] == comparison["checks_total"] == 3

    bad = dict(p2)
    bad["P2_R_crown"] = float(bad["P2_R_crown"]) + 0.02
    mismatch = compare_p2_pair_to_archive(bad, 4, fixture)
    assert mismatch["status"] == "MISMATCH"
    assert mismatch["checks_passed"] == 2
    assert mismatch["checks_total"] == 3


def test_p2_projection_uses_per_pixel_dem_interpolated_geometry_not_crown_median():
    x = np.array([140.0, 220.0, 300.0, 380.0])
    y = np.array([220.0, 300.0, 380.0])
    heights = np.array([100.0, 500.0, 900.0])
    shape = (heights.size, y.size, x.size)
    incidence = np.broadcast_to(
        np.array([30.0, 35.0, 40.0, 45.0])[None, None, :], shape
    ).copy()
    los_x = np.broadcast_to(
        np.array([0.2, 0.4, 0.6, 0.8])[None, None, :], shape
    ).copy()
    los_y = np.sqrt(1.0 - los_x**2)
    along_x = np.broadcast_to(
        np.array([0.9, 0.7, 0.5, 0.3])[None, None, :], shape
    ).copy()
    along_y = np.broadcast_to(
        np.array([-0.4, -0.2, 0.2, 0.4])[None, None, :], shape
    ).copy()
    cubes = SimpleNamespace(
        metadata_epsg=32645,
        height_m=heights,
        y_m=y,
        x_m=x,
        incidence_deg=incidence,
        los_x=los_x,
        los_y=los_y,
        along_track_x=along_x,
        along_track_y=along_y,
    )
    # Pixel centres match the radarGrid samples; the DEM height is inside
    # the height axis, and all geometry fields vary in x across the tile.
    transform = Affine(80.0, 0.0, 100.0, 0.0, -80.0, 420.0)
    dem = np.full((3, 4), 500.0, dtype=np.float32)
    at = np.full((3, 4), 0.5, dtype=np.float32)
    sr = np.full((3, 4), 0.2, dtype=np.float32)
    snr = np.full((3, 4), 10.0, dtype=np.float32)

    projected, coefficients, evidence = project_author_p2_window(
        along_track_m=at,
        slant_range_m=sr,
        snr=snr,
        geometry_cubes=cubes,
        dem_elevation_m=dem,
        target_transform=transform,
        epsg=32645,
    )
    assert evidence["author_geometry_source_sha256"]
    assert evidence["geometry_method"].startswith("author geometry.py")
    assert evidence["vertical_transformation_applied"] is False
    assert coefficients["cE"].shape == at.shape
    assert projected["quality_gate_counts"]["final_valid_cells"] == at.size
    assert np.ptp(projected["dE_m"]) > 0.01
    assert np.ptp(projected["dN_m"]) > 0.01


def test_p2_crown_r_uses_source_pixel_box_then_box_extent_for_crown():
    east, north, x, y = _halo_field_arrays()
    result = author_local_mean_reference_statistics(
        east, north, x, y, 32645,
        local_window=41,
        crown_bounds_lonlat=AUTHOR_CROWN_BOUNDS,
        box_bounds_lonlat=AUTHOR_WIDE_BOUNDS,
    )
    east32 = east.astype(np.float32)
    north32 = north.astype(np.float32)
    residual_east = (east32 - local_nanmean(east32, 41, 0.15)).astype(np.float32)
    residual_north = (north32 - local_nanmean(north32, 41, 0.15)).astype(np.float32)
    full_r = residual_directional_coherence(
        residual_east, residual_north, window_size=5, local_support_fraction=0.15
    )
    box_rows, box_cols = author_wide_window_slices(
        x, y, 32645, wide_bounds_lonlat=AUTHOR_WIDE_BOUNDS
    )
    box_extent, (box_r,) = author_north_up(
        x[box_cols], y[box_rows], 32645, [full_r[box_rows, box_cols]]
    )
    crown_slice = author_crown_slice(box_r.shape, box_extent, AUTHOR_CROWN_BOUNDS)
    box_values = box_r[np.isfinite(box_r)]
    crown_values = box_r[crown_slice]
    crown_values = crown_values[np.isfinite(crown_values)]
    assert result["coherence_computed_before_spatial_cropping"] is True
    assert result["author_spatial_selection_order"].startswith("residual coherence on halo")
    assert result["P2_R_crown"] == pytest.approx(float(np.median(crown_values)), abs=1e-7)
    assert result["P2_R_background"] == pytest.approx(float(np.median(box_values)), abs=1e-7)
