"""Author-derived per-pixel GOFF geometry-coefficient builder.

Adapted with attribution from S. R. Meena (2026), Zenodo
https://doi.org/10.5281/zenodo.22730419, code/geometry.py (SHA-256
0f056c46f2f5f9418dd1735b666edaa5c055514694fcd2c66490e09b6bb63004).

This array kernel transcribes the archived RegularGridInterpolator recipe:
linear interpolation over (height-above-ellipsoid, radarGrid y, radarGrid x),
Copernicus DEM nodata/median fill and height-axis clipping, then the four
projection coefficients used by wide_screen.py. It neither reads HDF5 nor
loads/verifies the DEM file, CRS, source product identity or vertical datum.
Those inputs and their provenance must be verified by the calling workflow.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.interpolate import RegularGridInterpolator

GEOMETRY_SCHEMA = "know-place-author-footprint-geometry/1.0"
AUTHOR_GEOMETRY_SHA256 = "0f056c46f2f5f9418dd1735b666edaa5c055514694fcd2c66490e09b6bb63004"
REQUIRED_TARGET_EPSG = 32645
GEOMETRY_FIELDS = ("incidence_angle_deg", "los_x", "los_y", "along_x", "along_y")
COEFFICIENT_FIELDS = ("cE", "cN", "kE", "kN")


class FootprintGeometryError(ValueError):
    """Input geometry cube, DEM or target grid violates the declared contract."""


def _axis(values: Any, name: str, *, require_ascending: bool = False) -> np.ndarray:
    axis = np.asarray(values, dtype=np.float64)
    if axis.ndim != 1 or axis.size < 2:
        raise FootprintGeometryError(f"{name.upper()}_AXIS_MUST_BE_1D_WITH_AT_LEAST_TWO_VALUES")
    if not np.isfinite(axis).all():
        raise FootprintGeometryError(f"{name.upper()}_AXIS_HAS_NONFINITE_VALUES")
    difference = np.diff(axis)
    ascending = bool(np.all(difference > 0))
    descending = bool(np.all(difference < 0))
    if not (ascending or descending):
        raise FootprintGeometryError(f"{name.upper()}_AXIS_NOT_STRICTLY_MONOTONIC")
    if require_ascending and not ascending:
        raise FootprintGeometryError(f"{name.upper()}_AXIS_MUST_BE_ASCENDING")
    return axis


def _cube(values: Any, name: str, expected_shape: tuple[int, int, int]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 3 or array.shape != expected_shape:
        raise FootprintGeometryError(f"{name.upper()}_CUBE_SHAPE_MISMATCH")
    return array


def _target_transform(transform: Any) -> tuple[float, float, float, float]:
    try:
        a, b, c = float(transform.a), float(transform.b), float(transform.c)
        d, e, f = float(transform.d), float(transform.e), float(transform.f)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FootprintGeometryError("TARGET_TRANSFORM_MUST_BE_AFFINE") from exc
    if not np.isfinite([a, b, c, d, e, f]).all():
        raise FootprintGeometryError("TARGET_TRANSFORM_HAS_NONFINITE_VALUES")
    # The archived geometry builder uses only c/a and f/e; fail closed rather
    # than silently mis-handle a rotated or sheared target affine.
    if abs(b) > 1e-12 or abs(d) > 1e-12:
        raise FootprintGeometryError("TARGET_TRANSFORM_ROTATION_OR_SHEAR_UNSUPPORTED")
    if a <= 0 or e >= 0:
        raise FootprintGeometryError("TARGET_GRID_MUST_BE_NORTH_UP_WITH_POSITIVE_X_NEGATIVE_Y_POSTING")
    return a, c, e, f


def build_per_pixel_coefficients(
    height_axis_m: Any,
    radar_y_axis_m: Any,
    radar_x_axis_m: Any,
    incidence_angle_deg_cube: Any,
    los_unit_vector_x_cube: Any,
    los_unit_vector_y_cube: Any,
    along_track_unit_vector_x_cube: Any,
    along_track_unit_vector_y_cube: Any,
    dem_elevation_m: Any,
    target_transform: Any,
    *,
    dem_transform: Any,
    target_epsg: int,
    geometry_metadata_epsg: int,
    dem_epsg: int,
    dem_vertical_reference: str,
    geometry_height_reference: str,
    allow_vertical_reference_mismatch: bool = False,
    dem_nodata: float = -9999.0,
    block_rows: int = 400,
) -> dict[str, Any]:
    """Build four float32 per-pixel offset-projection coefficients.

    Axis/data order must be (height, radar y, radar x). Height and x axes must
    be strictly ascending. A strictly descending y axis is reversed with all
    corresponding cube arrays, as in the author implementation.

    XY coordinates outside the radarGrid sample-point domain are linearly
    extrapolated because the archived source uses RegularGridInterpolator with
    bounds_error=False and fill_value=None. DEM values equal to dem_nodata and
    other nonfinite elevations are replaced by the median valid DEM elevation;
    all elevations are then clipped to the radarGrid height-axis limits.
    Diagnostics disclose extrapolated target pixels, filled elevations and
    clipped elevations instead of silently hiding these operations.
    """
    for name, value in (
        ("target_epsg", target_epsg),
        ("geometry_metadata_epsg", geometry_metadata_epsg),
        ("dem_epsg", dem_epsg),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise FootprintGeometryError(f"{name.upper()}_MUST_BE_INTEGER")
    if target_epsg != REQUIRED_TARGET_EPSG:
        raise FootprintGeometryError("TARGET_EPSG_MUST_MATCH_AUTHOR_32645_GRID")
    if geometry_metadata_epsg != target_epsg:
        raise FootprintGeometryError("GEOMETRY_METADATA_CRS_MISMATCH")
    if dem_epsg != target_epsg:
        raise FootprintGeometryError("DEM_CRS_MISMATCH")
    if not isinstance(dem_vertical_reference, str) or not dem_vertical_reference.strip():
        raise FootprintGeometryError("DEM_VERTICAL_REFERENCE_REQUIRED")
    if not isinstance(geometry_height_reference, str) or not geometry_height_reference.strip():
        raise FootprintGeometryError("GEOMETRY_HEIGHT_REFERENCE_REQUIRED")
    if not isinstance(allow_vertical_reference_mismatch, bool):
        raise FootprintGeometryError("ALLOW_VERTICAL_REFERENCE_MISMATCH_MUST_BE_BOOLEAN")
    dem_vertical = dem_vertical_reference.strip()
    geometry_vertical = geometry_height_reference.strip()
    vertical_refs_match = dem_vertical.casefold() == geometry_vertical.casefold()
    if not vertical_refs_match and not allow_vertical_reference_mismatch:
        raise FootprintGeometryError("VERTICAL_DATUM_MISMATCH_REQUIRES_EXPLICIT_SOURCE_REPRODUCTION_OVERRIDE")
    if isinstance(block_rows, bool) or not isinstance(block_rows, int) or block_rows < 1:
        raise FootprintGeometryError("BLOCK_ROWS_MUST_BE_POSITIVE_INTEGER")
    if isinstance(dem_nodata, bool) or not isinstance(dem_nodata, (int, float)) or not np.isfinite(float(dem_nodata)):
        raise FootprintGeometryError("DEM_NODATA_MUST_BE_FINITE")

    heights = _axis(height_axis_m, "height", require_ascending=True)
    radar_y = _axis(radar_y_axis_m, "radar_y")
    radar_x = _axis(radar_x_axis_m, "radar_x", require_ascending=True)
    source_shape = (len(heights), len(radar_y), len(radar_x))
    cubes = {
        "incidence_angle_deg": _cube(incidence_angle_deg_cube, "incidence_angle_deg", source_shape),
        "los_x": _cube(los_unit_vector_x_cube, "los_x", source_shape),
        "los_y": _cube(los_unit_vector_y_cube, "los_y", source_shape),
        "along_x": _cube(along_track_unit_vector_x_cube, "along_x", source_shape),
        "along_y": _cube(along_track_unit_vector_y_cube, "along_y", source_shape),
    }
    reverse_y = bool(radar_y[0] > radar_y[-1])
    ascending_y = radar_y[::-1].copy() if reverse_y else radar_y.copy()
    if reverse_y:
        cubes = {name: cube[:, ::-1, :] for name, cube in cubes.items()}

    dem = np.asarray(dem_elevation_m, dtype=np.float32)
    if dem.ndim != 2 or min(dem.shape) < 1:
        raise FootprintGeometryError("DEM_MUST_BE_2D_AND_MATCH_TARGET_GRID")
    height, width = dem.shape
    target_grid_transform = _target_transform(target_transform)
    dem_grid_transform = _target_transform(dem_transform)
    if not np.allclose(target_grid_transform, dem_grid_transform, rtol=0.0, atol=1e-9):
        raise FootprintGeometryError("DEM_GRID_TRANSFORM_MISMATCH")
    a, c, e, f = target_grid_transform
    dem_a, dem_c, dem_e, dem_f = dem_grid_transform
    elevation = dem.copy()
    elevation[elevation == np.float32(dem_nodata)] = np.nan
    finite_dem = np.isfinite(elevation)
    if not finite_dem.any():
        raise FootprintGeometryError("DEM_HAS_NO_FINITE_NON_NODATA_ELEVATIONS")
    dem_median = float(np.nanmedian(elevation))
    if not np.isfinite(dem_median):
        raise FootprintGeometryError("DEM_MEDIAN_IS_NONFINITE")
    dem_fill_mask = ~np.isfinite(elevation)
    dem_fill_count = int(dem_fill_mask.sum())
    elevation[dem_fill_mask] = np.float32(dem_median)
    clip_mask = (elevation < heights[0]) | (elevation > heights[-1])
    dem_height_clipped_count = int(clip_mask.sum())
    np.clip(elevation, heights[0], heights[-1], out=elevation)

    interpolators = {
        name: RegularGridInterpolator(
            (heights, ascending_y, radar_x),
            values,
            method="linear",
            bounds_error=False,
            fill_value=None,
        )
        for name, values in cubes.items()
    }
    coefficients = {name: np.empty((height, width), dtype=np.float32) for name in COEFFICIENT_FIELDS}
    x_coordinates = c + (np.arange(width, dtype=np.float64) + 0.5) * a
    xy_extrapolated_pixels = 0
    target_pixel_count = int(height * width)
    for row_start in range(0, height, block_rows):
        row_end = min(row_start + block_rows, height)
        y_coordinates = f + (np.arange(row_start, row_end, dtype=np.float64) + 0.5) * e
        yy, xx = np.meshgrid(y_coordinates, x_coordinates, indexing="ij")
        block_height = elevation[row_start:row_end]
        xy_extrapolated_pixels += int((
            (xx < radar_x[0]) | (xx > radar_x[-1])
            | (yy < ascending_y[0]) | (yy > ascending_y[-1])
        ).sum())
        points = np.column_stack([block_height.ravel(), yy.ravel(), xx.ravel()])
        interpolated = {name: interp(points) for name, interp in interpolators.items()}
        incidence_radians = np.deg2rad(interpolated["incidence_angle_deg"])
        los_x = interpolated["los_x"]
        los_y = interpolated["los_y"]
        along_x = interpolated["along_x"]
        along_y = interpolated["along_y"]
        horizontal_los_norm = np.hypot(los_x, los_y)
        block_shape = (row_end - row_start, width)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            coefficients["cE"][row_start:row_end] = along_x.reshape(block_shape)
            coefficients["cN"][row_start:row_end] = along_y.reshape(block_shape)
            coefficients["kE"][row_start:row_end] = (-(los_x / horizontal_los_norm) / np.sin(incidence_radians)).reshape(block_shape)
            coefficients["kN"][row_start:row_end] = (-(los_y / horizontal_los_norm) / np.sin(incidence_radians)).reshape(block_shape)

    coefficient_nonfinite_counts = {
        name: int((~np.isfinite(array)).sum()) for name, array in coefficients.items()
    }
    finite_all_coefficients = np.logical_and.reduce([np.isfinite(array) for array in coefficients.values()])
    return {
        "schema_version": GEOMETRY_SCHEMA,
        "status": "PER_PIXEL_GEOMETRY_COEFFICIENTS_COMPUTED",
        "author_geometry_source_sha256": AUTHOR_GEOMETRY_SHA256,
        "target_epsg": target_epsg,
        "geometry_metadata_epsg": geometry_metadata_epsg,
        "dem_epsg": dem_epsg,
        "vertical_reference": {
            "dem_vertical_reference_declared": dem_vertical,
            "geometry_height_reference_declared": geometry_vertical,
            "declared_reference_strings_match": vertical_refs_match,
            "status": (
                "DECLARED_REFERENCE_STRINGS_MATCH"
                if vertical_refs_match
                else "MISMATCH_PASSED_THROUGH_FOR_EXPLICIT_SOURCE_REPRODUCTION"
            ),
            "explicit_mismatch_override": allow_vertical_reference_mismatch,
            "vertical_transformation_applied": False,
            "warning": (
                None if vertical_refs_match else
                "The DEM elevation values are used directly against the geometry height axis with no vertical datum transformation, to expose source-method behavior only; do not treat as datum-corrected geometry."
            ),
        },
        "target_shape": [height, width],
        "target_transform": {"a": a, "c": c, "e": e, "f": f},
        "dem_transform": {"a": dem_a, "c": dem_c, "e": dem_e, "f": dem_f},
        "dem_transform_matches_target": True,
        "source_radar_grid_shape": list(source_shape),
        "source_height_axis_bounds_m": [float(heights[0]), float(heights[-1])],
        "source_y_axis_reversed_to_ascending": reverse_y,
        "block_rows": block_rows,
        "coefficients": coefficients,
        "diagnostics": {
            "target_pixel_count": target_pixel_count,
            "dem_nodata_or_nonfinite_filled_pixels": dem_fill_count,
            "dem_fill_median_m": dem_median,
            "dem_height_clipped_pixels": dem_height_clipped_count,
            "target_pixels_extrapolated_in_xy": xy_extrapolated_pixels,
            "target_xy_extrapolation_fraction": float(xy_extrapolated_pixels / target_pixel_count),
            "nonfinite_coefficient_pixels_per_field": coefficient_nonfinite_counts,
            "pixels_with_all_four_finite_coefficients": int(finite_all_coefficients.sum()),
            "xy_policy": "RegularGridInterpolator linear interpolation with bounds_error=False and fill_value=None; XY out-of-range points are linearly extrapolated and counted.",
            "dem_policy": "Replace values equal to dem_nodata and other nonfinite elevations by median valid DEM elevation, then clip to inclusive radarGrid height-axis bounds.",
            "coefficient_policy": "cE=alongTrackUnitVectorX; cN=alongTrackUnitVectorY; kE=-(losUnitVectorX/hypot(losX,losY))/sin(incidence); kN uses losY.",
        },
        "limitations": [
            "This function interpolates supplied arrays; it does not open or hash the HDF5 product or DEM source file.",
            "Vertical references must be declared explicitly. If they differ, the builder fails unless a clearly labeled source-method reproduction override is supplied; no vertical transformation is implemented here.",
            "Per-pixel coefficient construction is not full author-screen reproduction until exact raw inputs, target grid and resulting coefficient maps are independently compared.",
        ],
        "hazard_detection_status": "NOT_EVALUATED",
    }
