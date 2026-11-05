from __future__ import annotations

import numpy as np
import pytest
from affine import Affine

from tools.know_place.footprint_geometry import (
    AUTHOR_GEOMETRY_SHA256,
    FootprintGeometryError,
    build_per_pixel_coefficients,
)
from tools.know_place.footprint_screen import (
    EXPECTED_INTERVALS,
    project_per_pixel_offsets,
    screen_pair,
)


def source_grid(y_axis=None, x_axis=None):
    height = np.array([1000.0, 2000.0, 3000.0], dtype=np.float64)
    y = np.array([2.0, 1.0, 0.0], dtype=np.float64) if y_axis is None else np.asarray(y_axis, dtype=np.float64)
    x = np.array([10.0, 20.0, 30.0], dtype=np.float64) if x_axis is None else np.asarray(x_axis, dtype=np.float64)
    h = height[:, None, None]
    yy = y[None, :, None]
    xx = x[None, None, :]
    incidence = 28.0 + h / 1000.0 * 1.0 + yy * 0.1 + xx * 0.01
    los_x = 0.2 + h * 1e-5 + yy * 0.01 + xx * 0.001
    los_y = 0.3 + h * 2e-5 + yy * 0.02 + xx * 0.002
    along_x = 0.8 + h * 1e-5 + yy * 0.005 + xx * 0.0005
    along_y = -0.5 + h * 1e-5 - yy * 0.01 + xx * 0.0002
    return height, y, x, incidence, los_x, los_y, along_x, along_y


def dem_fixture():
    return np.array(
        [[1200.0, -9999.0, 3500.0], [500.0, 2000.0, 2500.0], [1100.0, 2100.0, 2900.0]],
        dtype=np.float32,
    )


def build(grid=None, dem=None, transform=None, **kwargs):
    grid = source_grid() if grid is None else grid
    dem = dem_fixture() if dem is None else dem
    transform = Affine(5.0, 0.0, 10.0, 0.0, -1.0, 2.5) if transform is None else transform
    kwargs.setdefault("dem_transform", transform)
    kwargs.setdefault("target_epsg", 32645)
    kwargs.setdefault("geometry_metadata_epsg", 32645)
    kwargs.setdefault("dem_epsg", 32645)
    kwargs.setdefault("dem_vertical_reference", "WGS84 ellipsoid HAE")
    kwargs.setdefault("geometry_height_reference", "WGS84 ellipsoid HAE")
    return build_per_pixel_coefficients(*grid, dem, transform, **kwargs)


def test_geometry_coefficients_match_author_linear_interpolation_and_signs():
    result = build(block_rows=2)
    coefficients = result['coefficients']
    # First target cell centre: H=1200 m, radar y=2 m, radar x=12.5 m.
    incidence_deg = 28.0 + 1200.0 / 1000.0 + 2.0 * 0.1 + 12.5 * 0.01
    los_x = 0.2 + 1200.0 * 1e-5 + 2.0 * 0.01 + 12.5 * 0.001
    los_y = 0.3 + 1200.0 * 2e-5 + 2.0 * 0.02 + 12.5 * 0.002
    along_x = 0.8 + 1200.0 * 1e-5 + 2.0 * 0.005 + 12.5 * 0.0005
    along_y = -0.5 + 1200.0 * 1e-5 - 2.0 * 0.01 + 12.5 * 0.0002
    los_norm = np.hypot(los_x, los_y)
    assert coefficients['cE'][0, 0] == pytest.approx(along_x, abs=2e-7)
    assert coefficients['cN'][0, 0] == pytest.approx(along_y, abs=2e-7)
    assert coefficients['kE'][0, 0] == pytest.approx(-(los_x / los_norm) / np.sin(np.deg2rad(incidence_deg)), abs=2e-7)
    assert coefficients['kN'][0, 0] == pytest.approx(-(los_y / los_norm) / np.sin(np.deg2rad(incidence_deg)), abs=2e-7)
    assert result['status'] == 'PER_PIXEL_GEOMETRY_COEFFICIENTS_COMPUTED'
    assert result['hazard_detection_status'] == 'NOT_EVALUATED'
    assert result['author_geometry_source_sha256'] == AUTHOR_GEOMETRY_SHA256


def test_geometry_matches_author_dem_nodata_median_fill_and_height_clipping():
    result = build()
    diagnostics = result['diagnostics']
    assert diagnostics['dem_nodata_or_nonfinite_filled_pixels'] == 1
    assert diagnostics['dem_fill_median_m'] == pytest.approx(2050.0)
    assert diagnostics['dem_height_clipped_pixels'] == 2
    assert diagnostics['target_pixels_extrapolated_in_xy'] == 0
    assert result['source_y_axis_reversed_to_ascending'] is True


def test_geometry_xy_extrapolation_is_preserved_and_counted():
    result = build(transform=Affine(5.0, 0.0, 5.0, 0.0, -1.0, 2.5))
    assert result['diagnostics']['target_pixels_extrapolated_in_xy'] == 3
    assert 'extrapolated' in result['diagnostics']['xy_policy']


def test_descending_y_and_ascending_y_cubes_produce_same_coefficients():
    desc = source_grid()
    asc = (desc[0], desc[1][::-1], desc[2], *(field[:, ::-1, :] for field in desc[3:]))
    descending = build(grid=desc)
    ascending = build(grid=asc)
    for name in ('cE', 'cN', 'kE', 'kN'):
        assert np.allclose(descending['coefficients'][name], ascending['coefficients'][name], rtol=0, atol=1e-7, equal_nan=True)
    assert descending['source_y_axis_reversed_to_ascending'] is True
    assert ascending['source_y_axis_reversed_to_ascending'] is False


def test_geometry_rejects_nonmonotonic_or_wrongly_ordered_axes():
    bad_y = source_grid(y_axis=[2.0, 0.0, 1.0])
    with pytest.raises(FootprintGeometryError, match='RADAR_Y_AXIS_NOT_STRICTLY_MONOTONIC'):
        build(grid=bad_y)
    bad_x = source_grid(x_axis=[30.0, 20.0, 10.0])
    with pytest.raises(FootprintGeometryError, match='RADAR_X_AXIS_MUST_BE_ASCENDING'):
        build(grid=bad_x)
    original = source_grid()
    bad_height = (original[0][::-1], original[1], original[2], *(field[::-1, :, :] for field in original[3:]))
    with pytest.raises(FootprintGeometryError, match='HEIGHT_AXIS_MUST_BE_ASCENDING'):
        build(grid=bad_height)


def test_geometry_rejects_unresolved_vertical_datum_mismatch_by_default():
    with pytest.raises(
        FootprintGeometryError,
        match="VERTICAL_DATUM_MISMATCH_REQUIRES_EXPLICIT_SOURCE_REPRODUCTION_OVERRIDE",
    ):
        build(
            dem_vertical_reference="Copernicus GLO-90 EGM2008 geoid",
            geometry_height_reference="NISAR heightAboveEllipsoid WGS84",
        )


def test_geometry_exposes_source_method_vertical_mismatch_only_with_explicit_override():
    result = build(
        dem_vertical_reference="Copernicus GLO-90 EGM2008 geoid",
        geometry_height_reference="NISAR heightAboveEllipsoid WGS84",
        allow_vertical_reference_mismatch=True,
    )
    reference = result["vertical_reference"]
    assert reference["declared_reference_strings_match"] is False
    assert reference["status"] == "MISMATCH_PASSED_THROUGH_FOR_EXPLICIT_SOURCE_REPRODUCTION"
    assert reference["explicit_mismatch_override"] is True
    assert reference["vertical_transformation_applied"] is False
    assert "no vertical datum transformation" in reference["warning"]


def test_geometry_rejects_shape_epsg_rotation_and_empty_dem():
    grid = list(source_grid())
    grid[3] = grid[3][:, :, :2]
    with pytest.raises(FootprintGeometryError, match='INCIDENCE_ANGLE_DEG_CUBE_SHAPE_MISMATCH'):
        build(grid=tuple(grid))
    with pytest.raises(FootprintGeometryError, match='TARGET_EPSG_MUST_MATCH_AUTHOR_32645_GRID'):
        build(target_epsg=4326)
    with pytest.raises(FootprintGeometryError, match='GEOMETRY_METADATA_CRS_MISMATCH'):
        build(geometry_metadata_epsg=4326)
    with pytest.raises(FootprintGeometryError, match='DEM_CRS_MISMATCH'):
        build(dem_epsg=4326)
    with pytest.raises(FootprintGeometryError, match='TARGET_TRANSFORM_ROTATION_OR_SHEAR_UNSUPPORTED'):
        build(transform=Affine(5.0, 0.1, 10.0, 0.0, -1.0, 2.5))
    with pytest.raises(FootprintGeometryError, match='DEM_HAS_NO_FINITE_NON_NODATA_ELEVATIONS'):
        build(dem=np.full((3, 3), -9999.0, dtype=np.float32))


def test_geometry_rejects_same_shape_dem_with_misaligned_transform():
    transform = Affine(5.0, 0.0, 10.0, 0.0, -1.0, 2.5)
    shifted_dem_transform = Affine(5.0, 0.0, 15.0, 0.0, -1.0, 2.5)
    with pytest.raises(FootprintGeometryError, match="DEM_GRID_TRANSFORM_MISMATCH"):
        build(transform=transform, dem_transform=shifted_dem_transform)


def test_geometry_coefficients_feed_per_pixel_projection_and_footprint_screen():
    geometry = build()
    elevation = dem_fixture()
    at = np.full(elevation.shape, 0.4, dtype=np.float32)
    sr = np.full(elevation.shape, 0.25, dtype=np.float32)
    snr = np.full(elevation.shape, 8.0, dtype=np.float32)
    c = geometry["coefficients"]
    projected = project_per_pixel_offsets(
        at, sr, snr, c["cE"], c["cN"], c["kE"], c["kN"]
    )
    expected_east = at * c["cE"] + sr * c["kE"]
    expected_north = at * c["cN"] + sr * c["kN"]
    assert np.array_equal(projected["valid_mask"], np.ones(elevation.shape, dtype=bool))
    assert np.allclose(projected["dE_m"], expected_east, rtol=0, atol=1e-6)
    assert np.allclose(projected["dN_m"], expected_north, rtol=0, atol=1e-6)

    screen = screen_pair(projected, interval=EXPECTED_INTERVALS[0])
    assert screen["status"] == "CANDIDATE_MOVEMENT_SCREEN_COMPUTED"
    assert screen["hit_mask"].shape == elevation.shape
    assert screen["hazard_detection_status"] == "NOT_EVALUATED"


def test_geometry_block_size_does_not_change_results():
    single_block = build(block_rows=3)
    one_row_blocks = build(block_rows=1)
    for name in ('cE', 'cN', 'kE', 'kN'):
        assert np.allclose(single_block['coefficients'][name], one_row_blocks['coefficients'][name], rtol=0, atol=0, equal_nan=True)
    assert single_block['diagnostics']['target_pixel_count'] == 9
    assert single_block['diagnostics']['pixels_with_all_four_finite_coefficients'] == 9


def test_geometry_records_nonfinite_coefficients_without_hiding_them():
    grid = list(source_grid())
    grid[4] = np.zeros_like(grid[4])
    grid[5] = np.zeros_like(grid[5])
    result = build(grid=tuple(grid))
    assert result['diagnostics']['nonfinite_coefficient_pixels_per_field']['kE'] == 9
    assert result['diagnostics']['nonfinite_coefficient_pixels_per_field']['kN'] == 9
    assert result['diagnostics']['pixels_with_all_four_finite_coefficients'] == 0
