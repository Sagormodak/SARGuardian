"""Author-source-compatible kernels kept separate from the exploratory runner.

Adapted from Sansar Raj Meena (2026), "Bhote Koshi 2026 ice–rock avalanche:
NISAR L2 GOFF site series and footprint-wide offset-tracking screen — data and
code", Zenodo, https://doi.org/10.5281/zenodo.22730419, CC BY 4.0.
Changes: extracted kernels into typed, independently testable functions and
added validation. These functions do not fetch data or certify a full paper
reproduction. Raw GOFF source hashes and end-to-end golden parity remain gates.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from pyproj import Transformer
from scipy.ndimage import uniform_filter

from .footprint_screen import local_nanmean, residual_directional_coherence


class AuthorParityError(ValueError):
    """An author-parity input cannot support an unambiguous calculation."""


def _pair(east_m: Any, north_m: Any) -> tuple[np.ndarray, np.ndarray]:
    east = np.asarray(east_m, dtype=float)
    north = np.asarray(north_m, dtype=float)
    if east.ndim != 2 or north.ndim != 2 or east.shape != north.shape:
        raise AuthorParityError("AUTHOR_EAST_NORTH_SHAPE_MISMATCH")
    return east, north


def author_coherence_map(east_m: Any, north_m: Any, window_size: int = 5) -> np.ndarray:
    """Return the archived 5x5 mean resultant length map.

    This matches the archived scipy.ndimage.uniform_filter default reflected
    edge policy, unit-vector normalization, and strict finite-support fraction
    greater than 0.5. Finite zero-length vectors count toward the denominator
    but contribute a zero vector, as in the original source.
    """
    east, north = _pair(east_m, north_m)
    if not isinstance(window_size, int) or window_size < 1 or window_size % 2 != 1:
        raise AuthorParityError("AUTHOR_COHERENCE_WINDOW_INVALID")
    finite = np.isfinite(east) & np.isfinite(north)
    mag = np.hypot(east, north)
    ux = np.where(finite, east / np.maximum(mag, 1e-9), np.nan)
    uy = np.where(finite, north / np.maximum(mag, 1e-9), np.nan)

    def filtered_component(values: np.ndarray) -> np.ndarray:
        smooth = uniform_filter(np.nan_to_num(values), size=window_size)
        support = uniform_filter(np.isfinite(values).astype(float), size=window_size)
        return np.where(support > 0.5, smooth / np.maximum(support, 1e-9), np.nan)

    return np.hypot(filtered_component(ux), filtered_component(uy))


def author_quality_mask(
    east_m: Any,
    north_m: Any,
    snr: Any,
    minimum_snr: float = 5.0,
    maximum_magnitude_m: float = 10.0,
) -> np.ndarray:
    """Source quality gate: finite SNR, SNR >= threshold, and magnitude <= limit.

    Correlation-peak values are not used here because the archived site-series
    code does not include that product field in its validity gate.
    """
    east, north = _pair(east_m, north_m)
    snr_values = np.asarray(snr, dtype=float)
    if snr_values.shape != east.shape:
        raise AuthorParityError("AUTHOR_SNR_SHAPE_MISMATCH")
    if not math.isfinite(minimum_snr) or minimum_snr < 0:
        raise AuthorParityError("AUTHOR_MINIMUM_SNR_INVALID")
    if not math.isfinite(maximum_magnitude_m) or maximum_magnitude_m <= 0:
        raise AuthorParityError("AUTHOR_MAXIMUM_MAGNITUDE_INVALID")
    mag = np.hypot(east, north)
    return np.isfinite(snr_values) & (snr_values >= minimum_snr) & np.isfinite(mag) & (mag <= maximum_magnitude_m)


def author_project_offsets(
    along_track_m: Any, slant_range_m: Any, geometry: Mapping[str, float]
) -> tuple[np.ndarray, np.ndarray]:
    """Project AT/SR offsets using target-to-sensor LOS sign from the archive."""
    at = np.asarray(along_track_m, dtype=float)
    sr = np.asarray(slant_range_m, dtype=float)
    if at.ndim != 2 or sr.shape != at.shape:
        raise AuthorParityError("AUTHOR_AT_SR_SHAPE_MISMATCH")
    try:
        at_x = float(geometry["along_track_x"])
        at_y = float(geometry["along_track_y"])
        los_x = float(geometry["los_x"])
        los_y = float(geometry["los_y"])
        incidence_deg = float(geometry["incidence_deg"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise AuthorParityError("AUTHOR_GEOMETRY_FIELDS_INVALID") from exc
    scalars = (at_x, at_y, los_x, los_y, incidence_deg)
    if not all(math.isfinite(value) for value in scalars):
        raise AuthorParityError("AUTHOR_GEOMETRY_NONFINITE")
    if not 0 < incidence_deg < 90 or math.hypot(los_x, los_y) <= 0:
        raise AuthorParityError("AUTHOR_GEOMETRY_OUT_OF_RANGE")
    ground_range = sr / math.sin(math.radians(incidence_deg))
    horizontal_los = math.hypot(los_x, los_y)
    east = at * at_x - ground_range * los_x / horizontal_los
    north = at * at_y - ground_range * los_y / horizontal_los
    usable = np.isfinite(at) & np.isfinite(sr) & np.isfinite(east) & np.isfinite(north)
    return np.where(usable, east, np.nan), np.where(usable, north, np.nan)


def author_crown_geometry_median(
    cubes: Any,
    crown_lonlat: tuple[float, float] = (85.52985, 28.29041),
    expected_epsg: int = 32645,
) -> dict[str, float | int | str]:
    """Nearest radarGrid XY cell; nan-median each geometry field along height."""
    if int(getattr(cubes, "metadata_epsg", -1)) != int(expected_epsg):
        raise AuthorParityError("AUTHOR_GEOMETRY_CRS_MISMATCH")
    x = np.asarray(cubes.x_m, dtype=float)
    y = np.asarray(cubes.y_m, dtype=float)
    height = np.asarray(cubes.height_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or height.ndim != 1 or not x.size or not y.size or not height.size:
        raise AuthorParityError("AUTHOR_GEOMETRY_AXES_INVALID")
    if not (np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(height).all()):
        raise AuthorParityError("AUTHOR_GEOMETRY_AXES_NONFINITE")
    lon, lat = map(float, crown_lonlat)
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise AuthorParityError("AUTHOR_CROWN_LONLAT_INVALID")
    tx = Transformer.from_crs("EPSG:4326", f"EPSG:{expected_epsg}", always_xy=True)
    cx, cy = tx.transform(lon, lat)
    ix = int(np.argmin(np.abs(x - cx)))
    iy = int(np.argmin(np.abs(y - cy)))
    arrays = {
        "incidence_deg": cubes.incidence_deg,
        "los_x": cubes.los_x,
        "los_y": cubes.los_y,
        "along_track_x": cubes.along_track_x,
        "along_track_y": cubes.along_track_y,
    }
    expected_shape = (height.size, y.size, x.size)
    result: dict[str, float | int | str] = {
        "nearest_column": ix,
        "nearest_row": iy,
        "nearest_x_m": float(x[ix]),
        "nearest_y_m": float(y[iy]),
        "sample_policy": "nearest radarGrid XY cell; nanmedian over height-axis samples",
        "metadata_group": str(getattr(cubes, "group_path", "")),
    }
    for field, raw in arrays.items():
        cube = np.asarray(raw, dtype=float)
        if cube.shape != expected_shape:
            raise AuthorParityError(f"AUTHOR_GEOMETRY_CUBE_SHAPE_MISMATCH:{field}")
        values = cube[:, iy, ix]
        values = values[np.isfinite(values)]
        if not values.size:
            raise AuthorParityError(f"AUTHOR_GEOMETRY_SAMPLE_EMPTY:{field}")
        result[field] = float(np.median(values))
    if not 0 < float(result["incidence_deg"]) < 90:
        raise AuthorParityError("AUTHOR_INCIDENCE_OUT_OF_RANGE")
    if math.hypot(float(result["los_x"]), float(result["los_y"])) <= 0:
        raise AuthorParityError("AUTHOR_HORIZONTAL_LOS_ZERO")
    return result


def author_wide_window_slices(
    x_coordinates_m: Any,
    y_coordinates_m: Any,
    epsg: int,
    wide_bounds_lonlat: tuple[float, float, float, float] = (85.500, 28.265, 85.565, 28.318),
) -> tuple[slice, slice]:
    """Select the author WIDE window with the source corner-transform/searchsorted policy."""
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size < 2 or y.size < 2:
        raise AuthorParityError("AUTHOR_GOFF_AXES_INVALID")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise AuthorParityError("AUTHOR_GOFF_AXES_NONFINITE")
    if not np.all(np.diff(x) > 0) or not (np.all(np.diff(y) > 0) or np.all(np.diff(y) < 0)):
        raise AuthorParityError("AUTHOR_GOFF_AXIS_ORDER_UNSUPPORTED")
    west, south, east, north = map(float, wide_bounds_lonlat)
    if not west < east or not south < north:
        raise AuthorParityError("AUTHOR_WIDE_BOUNDS_INVALID")
    tx = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    x0, y0 = tx.transform(west, south)
    x1, y1 = tx.transform(east, north)
    col0 = int(np.searchsorted(x, min(x0, x1)))
    col1 = int(np.searchsorted(x, max(x0, x1)))
    descending = bool(y[0] > y[-1])
    y_up = y[::-1] if descending else y
    row0 = int(np.searchsorted(y_up, min(y0, y1)))
    row1 = int(np.searchsorted(y_up, max(y0, y1)))
    if descending:
        row0, row1 = y.size - row1, y.size - row0
    if col0 >= col1 or row0 >= row1:
        raise AuthorParityError("AUTHOR_WIDE_WINDOW_EMPTY")
    return slice(row0, row1), slice(col0, col1)


def author_inside_aoi_mask(
    x_coordinates_m: Any,
    y_coordinates_m: Any,
    epsg: int,
    aoi_bounds_lonlat: tuple[float, float, float, float] = (85.5245, 28.2847, 85.5400, 28.2970),
) -> np.ndarray:
    """Build the source's rectangular AOI mask from middle-row/column axes."""
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or not x.size or not y.size:
        raise AuthorParityError("AUTHOR_AOI_AXES_INVALID")
    west, south, east, north = map(float, aoi_bounds_lonlat)
    if not west < east or not south < north:
        raise AuthorParityError("AUTHOR_AOI_BOUNDS_INVALID")
    inverse = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    longitude_axis = np.asarray([inverse.transform(float(xv), float(y[len(y) // 2]))[0] for xv in x])
    latitude_axis = np.asarray([inverse.transform(float(x[len(x) // 2]), float(yv))[1] for yv in y])
    lon_grid, lat_grid = np.meshgrid(longitude_axis, latitude_axis)
    return (
        (lon_grid >= west) & (lon_grid <= east)
        & (lat_grid >= south) & (lat_grid <= north)
    )


def author_reference_correct(
    east_m: Any,
    north_m: Any,
    valid: Any,
    inside_aoi: Any,
    minimum_ring_count_exclusive: int = 200,
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int | bool]]:
    """Subtract ring medians only when ring-valid count is strictly greater than 200."""
    east, north = _pair(east_m, north_m)
    mask = np.asarray(valid, dtype=bool)
    inside = np.asarray(inside_aoi, dtype=bool)
    if mask.shape != east.shape or inside.shape != east.shape:
        raise AuthorParityError("AUTHOR_REFERENCE_MASK_SHAPE_MISMATCH")
    if not isinstance(minimum_ring_count_exclusive, int) or minimum_ring_count_exclusive < 0:
        raise AuthorParityError("AUTHOR_REFERENCE_THRESHOLD_INVALID")
    usable = mask & np.isfinite(east) & np.isfinite(north)
    ring = usable & ~inside
    count = int(ring.sum())
    applied = count > minimum_ring_count_exclusive
    off_e = float(np.median(east[ring])) if applied else 0.0
    off_n = float(np.median(north[ring])) if applied else 0.0
    out_e = np.full(east.shape, np.nan, dtype=float)
    out_n = np.full(north.shape, np.nan, dtype=float)
    out_e[usable] = east[usable] - off_e
    out_n[usable] = north[usable] - off_n
    return out_e, out_n, {
        "ring_valid_cells": count,
        "correction_applied": applied,
        "east_offset_m": off_e,
        "north_offset_m": off_n,
    }


def author_north_up(
    x_coordinates_m: Any,
    y_coordinates_m: Any,
    epsg: int,
    arrays: Sequence[Any],
) -> tuple[tuple[float, float, float, float], tuple[np.ndarray, ...]]:
    """Match source endpoint-derived display extent and flip arrays when required."""
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or not x.size or not y.size:
        raise AuthorParityError("AUTHOR_NORTH_UP_AXES_INVALID")
    copied = tuple(np.asarray(a).copy() for a in arrays)
    if any(a.ndim != 2 or a.shape != (y.size, x.size) for a in copied):
        raise AuthorParityError("AUTHOR_NORTH_UP_ARRAY_SHAPE_MISMATCH")
    inverse = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lon0, lat0 = inverse.transform(float(x[0]), float(y[0]))
    lon1, lat1 = inverse.transform(float(x[-1]), float(y[-1]))
    if lat0 < lat1:
        copied = tuple(np.flip(a, axis=0) for a in copied)
        lat0, lat1 = lat1, lat0
    extent = (min(lon0, lon1), max(lon0, lon1), min(lat0, lat1), max(lat0, lat1))
    if not all(math.isfinite(v) for v in extent):
        raise AuthorParityError("AUTHOR_EXTENT_NONFINITE")
    return tuple(map(float, extent)), copied


def author_crown_slice(
    shape: tuple[int, int],
    extent_lonlat: Sequence[float],
    crown_bounds_lonlat: tuple[float, float, float, float] = (85.5245, 28.2847, 85.5400, 28.2970),
) -> tuple[slice, slice]:
    """Match the source's endpoint-linear extent and numpy.searchsorted crown crop."""
    if len(shape) != 2 or shape[0] <= 0 or shape[1] <= 0 or len(extent_lonlat) != 4:
        raise AuthorParityError("AUTHOR_CROWN_SLICE_SHAPE_OR_EXTENT_INVALID")
    left, right, bottom, top = map(float, extent_lonlat)
    west, south, east, north = map(float, crown_bounds_lonlat)
    if not left < right or not bottom < top or not west < east or not south < north:
        raise AuthorParityError("AUTHOR_CROWN_SLICE_BOUNDS_INVALID")
    longitude = np.linspace(left, right, shape[1])
    latitude = np.linspace(top, bottom, shape[0])
    r0 = int(np.searchsorted(-latitude, -north))
    r1 = int(np.searchsorted(-latitude, -south))
    c0 = int(np.searchsorted(longitude, west))
    c1 = int(np.searchsorted(longitude, east))
    if r0 >= r1 or c0 >= c1:
        raise AuthorParityError("AUTHOR_CROWN_SLICE_EMPTY")
    return slice(r0, r1), slice(c0, c1)



def author_local_mean_reference_statistics(
    east_m: Any,
    north_m: Any,
    x_coordinates_m: Any,
    y_coordinates_m: Any,
    epsg: int,
    *,
    local_window: int = 41,
    crown_bounds_lonlat: tuple[float, float, float, float] = (85.5245, 28.2847, 85.5400, 28.2970),
    box_bounds_lonlat: tuple[float, float, float, float] = (85.500, 28.265, 85.565, 28.318),
) -> dict[str, Any]:
    """Compute P2 using the author's pixel-box crop then crown-extent crop.

    Residual coherence is computed on a contextual halo. The reported WIDE box
    is then selected directly from the projected GOFF x/y axes, and the crown
    mask is selected from that cropped box's endpoint-derived lon/lat extent,
    matching the author site-series spatial selection order. This avoids
    reflected-edge artifacts and the subtle crop shifts caused by applying the
    crown mask to the halo's extent directly.
    """
    east, north = _pair(east_m, north_m)
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or east.shape != (y.size, x.size):
        raise AuthorParityError("AUTHOR_P2_AXIS_SHAPE_MISMATCH")
    if int(epsg) <= 0:
        raise AuthorParityError("AUTHOR_P2_EPSG_INVALID")
    if not isinstance(local_window, int) or local_window < 3 or local_window % 2 != 1:
        raise AuthorParityError("AUTHOR_P2_LOCAL_WINDOW_INVALID")

    # Match wide_screen.py's float32 local-mean and residual operations.
    east_source = east.astype(np.float32, copy=False)
    north_source = north.astype(np.float32, copy=False)
    residual_east = (
        east_source - local_nanmean(east_source, local_window, 0.15)
    ).astype(np.float32)
    residual_north = (
        north_source - local_nanmean(north_source, local_window, 0.15)
    ).astype(np.float32)
    full_r = residual_directional_coherence(
        residual_east, residual_north, window_size=5, local_support_fraction=0.15
    )

    # Match make_pot_figure.read_pair(): select the box from projected x/y axes,
    # not from a second interpolation of the halo's geographic extent.
    box_rows, box_cols = author_wide_window_slices(
        x, y, int(epsg), wide_bounds_lonlat=box_bounds_lonlat
    )
    box_r_source = np.asarray(full_r[box_rows, box_cols], dtype=np.float32)
    box_x = x[box_cols]
    box_y = y[box_rows]
    box_extent, oriented = author_north_up(
        box_x, box_y, int(epsg), [box_r_source]
    )
    box_r = np.asarray(oriented[0], dtype=float)
    box_finite = box_r[np.isfinite(box_r)]
    if not box_finite.size:
        raise AuthorParityError("AUTHOR_P2_BOX_HAS_NO_VALID_R")

    # Match make_fig_timeseries.crown_slice(): the crown is selected from the
    # WIDE crop shape and that crop's own endpoint-derived extent.
    crown_slice = author_crown_slice(box_r.shape, box_extent, crown_bounds_lonlat)
    crown_r = np.asarray(box_r[crown_slice], dtype=float)
    crown_finite = crown_r[np.isfinite(crown_r)]
    if not crown_finite.size:
        raise AuthorParityError("AUTHOR_P2_CROWN_HAS_NO_VALID_R")

    crown_median = float(np.median(crown_finite))
    box_median = float(np.median(box_finite))
    return {
        "P2_R_crown": crown_median,
        "P2_R_background": box_median,
        "P2_resolved": bool(crown_median > box_median),
        "P2_crown_valid_R_cells": int(crown_finite.size),
        "P2_box_valid_R_cells": int(box_finite.size),
        "local_mean_window_pixels": local_window,
        "required_halo_pixels_per_side": local_window // 2 + 2,
        "box_shape": [int(box_r.shape[0]), int(box_r.shape[1])],
        "box_slice_in_halo": {
            "row_start": int(box_rows.start), "row_stop": int(box_rows.stop),
            "col_start": int(box_cols.start), "col_stop": int(box_cols.stop)
        },
        "coherence_computed_before_spatial_cropping": True,
        "author_spatial_selection_order": "residual coherence on halo -> WIDE box from projected x/y axes -> crown slice from WIDE endpoint extent",
    }



def author_site_series_statistics(
    east_m: Any,
    north_m: Any,
    extent_lonlat: Sequence[float],
    interval_days: int,
    crown_bounds_lonlat: tuple[float, float, float, float] = (85.5245, 28.2847, 85.5400, 28.2970),
) -> dict[str, float | int | list[int]]:
    """Produce the archived P1 crown/background summaries using crown-cropped R."""
    east, north = _pair(east_m, north_m)
    if not isinstance(interval_days, int) or interval_days <= 0:
        raise AuthorParityError("AUTHOR_INTERVAL_DAYS_INVALID")
    magnitude = np.hypot(east, north)
    magnitude[~(np.isfinite(east) & np.isfinite(north))] = np.nan
    crop = author_crown_slice(east.shape, extent_lonlat, crown_bounds_lonlat)
    crop_mag = magnitude[crop]
    crown_mag = crop_mag[np.isfinite(crop_mag)]
    if not crown_mag.size:
        raise AuthorParityError("AUTHOR_CROWN_HAS_NO_VALID_DISPLACEMENTS")
    crop_r = author_coherence_map(east[crop], north[crop])
    scene_r = author_coherence_map(east, north)
    crown_r = crop_r[np.isfinite(crop_r)]
    background_r = scene_r[np.isfinite(scene_r)]
    if not crown_r.size or not background_r.size:
        raise AuthorParityError("AUTHOR_COHERENCE_HAS_NO_VALID_WINDOWS")
    median_mag = float(np.median(crown_mag))
    return {
        "displacement_valid_crown_cells": int(crown_mag.size),
        "crown_slice_shape": [int(crop_mag.shape[0]), int(crop_mag.shape[1])],
        "crown_median_displacement_m": median_mag,
        "crown_median_rate_cm_per_day": median_mag / interval_days * 100.0,
        "P1_crown_R_valid_cells": int(crown_r.size),
        "P1_background_R_valid_cells": int(background_r.size),
        "P1_R_crown": float(np.median(crown_r)),
        "P1_R_background": float(np.median(background_r)),
    }


def author_polygon_null_statistics(
    east_m: Any,
    north_m: Any,
    extent_lonlat: Sequence[float],
    rng: np.random.Generator,
    n_draw: int = 1200,
    acceptance_fraction: float = 0.60,
    crown_bounds_lonlat: tuple[float, float, float, float] = (85.5245, 28.2847, 85.5400, 28.2970),
) -> dict[str, float | int | str]:
    """Mirror polygon_null.py; caller shares one RNG across ordered time pairs."""
    east, north = _pair(east_m, north_m)
    if not isinstance(rng, np.random.Generator):
        raise AuthorParityError("AUTHOR_NULL_RNG_TYPE_INVALID")
    if not isinstance(n_draw, int) or n_draw < 1:
        raise AuthorParityError("AUTHOR_NULL_DRAW_COUNT_INVALID")
    if not math.isfinite(acceptance_fraction) or not 0 < acceptance_fraction <= 1:
        raise AuthorParityError("AUTHOR_NULL_ACCEPTANCE_INVALID")
    R = author_coherence_map(east, north)
    crop = author_crown_slice(east.shape, extent_lonlat, crown_bounds_lonlat)
    crown = np.zeros(R.shape, dtype=bool)
    crown[crop] = True
    ok = np.isfinite(R)
    target_cells = int((crown & ok).sum())
    if target_cells == 0:
        raise AuthorParityError("AUTHOR_NULL_CROWN_HAS_NO_VALID_R")
    crown_R = float(np.median(R[crown & ok]))
    box_R = float(np.median(R[ok]))
    ys, xs = np.nonzero(ok)
    if not ys.size:
        raise AuthorParityError("AUTHOR_NULL_NO_VALID_BOX_R")
    selected = rng.choice(ys.size, size=min(n_draw, ys.size), replace=False)
    radius = math.sqrt(target_cells / math.pi)
    yy, xx = np.ogrid[:R.shape[0], :R.shape[1]]
    values: list[float] = []
    for idx in selected:
        disk = ((yy - ys[idx]) ** 2 + (xx - xs[idx]) ** 2) <= radius ** 2
        region = disk & ok
        if int(region.sum()) >= acceptance_fraction * target_cells:
            values.append(float(np.median(R[region])))
    if not values:
        raise AuthorParityError("AUTHOR_NULL_NO_ACCEPTED_DRAWS")
    draws = np.asarray(values, dtype=float)
    return {
        "crown_valid_R_cells": target_cells,
        "crown_R": crown_R,
        "box_R": box_R,
        "candidate_centres_examined": int(len(selected)),
        "accepted_draws": int(draws.size),
        "rejected_draws": int(len(selected) - draws.size),
        "rng_policy": "shared numpy.default_rng(20260907), one sequence across the five pairs",
        "crown_percentile_strict_less_than": float(np.mean(draws < crown_R) * 100.0),
        "fraction_controls_strictly_above_box": float(np.mean(draws > box_R) * 100.0),
        "null_p5": float(np.percentile(draws, 5)),
        "null_p95": float(np.percentile(draws, 95)),
    }
