"""Author-derived footprint-wide moving-surface screen kernels.

Adapted with attribution from S. R. Meena (2026), Zenodo record
https://doi.org/10.5281/zenodo.22730419, code/wide_screen.py (SHA-256
60e4238b9a10510f52a4673939a9708bf513d8bae460ba797d2dd27a1357d7c9)
and tables/TableS6_screen_params.json (SHA-256
85743e828c4d684046acf43bdb0bfbc8b8c194626aacad8fd58e154e925d8e76).
The audited archive labels its main code/data as CC BY 4.0; the separate
CC BY-NC extent/runout outline is excluded and is not used by this module.

This module separates the footprint-wide candidate screen from the crown/site
series metric. Geometry coefficients must already be interpolated per pixel
from the verified GOFF radarGrid geometry/DEM path; this module does not open
HDF5 files or construct geometry coefficients.

The original author describes the result as moving surfaces worth review, not
a prediction of failure. Active glaciers dominate the screened candidates.
Presence is not a hazard label, and absence is not proof of safety.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from scipy.ndimage import label, uniform_filter

SCREEN_SCHEMA = "know-place-author-footprint-screen/1.0"
EXPECTED_INTERVALS = (
    ("20260620", "20260702"),
    ("20260702", "20260714"),
    ("20260714", "20260726"),
    ("20260726", "20260819"),
    ("20260819", "20260831"),
)

SNR_THRESHOLD = 5.0
MAGNITUDE_CLIP_M = 10.0
LOCAL_WINDOW_PIXELS = 41
LOCAL_SUPPORT_FRACTION = 0.15
COHERENCE_WINDOW_PIXELS = 5
Z_THRESHOLD = 4.0
MAGNITUDE_ANOMALY_MIN_M = 0.50
RESIDUAL_COHERENCE_MIN = 0.75
MINIMUM_FLAGGED_INTERVALS = 2
MINIMUM_COMPONENT_PIXELS = 10


class FootprintScreenError(ValueError):
    """Footprint screen input does not satisfy its declared contract."""


def _raster(value: Any, name: str, shape: tuple[int, int] | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2:
        raise FootprintScreenError(f"{name.upper()}_MUST_BE_2D")
    if shape is not None and array.shape != shape:
        raise FootprintScreenError(f"{name.upper()}_SHAPE_MISMATCH")
    return array


def _positive_odd_window(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value % 2 != 1:
        raise FootprintScreenError(f"{name.upper()}_MUST_BE_POSITIVE_ODD_INTEGER")


def _finite_float(
    value: float,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise FootprintScreenError(f"{name.upper()}_MUST_BE_FINITE")
    result = float(value)
    if minimum is not None and result < minimum:
        raise FootprintScreenError(f"{name.upper()}_BELOW_MINIMUM")
    if maximum is not None and result > maximum:
        raise FootprintScreenError(f"{name.upper()}_ABOVE_MAXIMUM")
    return result


def local_nanmean(
    values: Any,
    window_size: int = LOCAL_WINDOW_PIXELS,
    minimum_support_fraction: float = LOCAL_SUPPORT_FRACTION,
) -> np.ndarray:
    """Match archived wide_screen.lmean, including float32 and reflected edges."""
    _positive_odd_window(window_size, "window_size")
    support_limit = _finite_float(
        minimum_support_fraction,
        "minimum_support_fraction",
        minimum=0.0,
        maximum=1.0,
    )
    array = _raster(values, "values")
    # These steps intentionally follow the archived source, including its
    # numerator/finite-support construction and scipy.ndimage default mode.
    numerator = np.nan_to_num(array).astype(np.float32, copy=False)
    valid = np.isfinite(array).astype(np.float32)
    local_sum = uniform_filter(numerator, size=window_size)
    support = uniform_filter(valid, size=window_size)
    return np.where(
        support > support_limit,
        local_sum / np.maximum(support, np.float32(1e-6)),
        np.nan,
    ).astype(np.float32, copy=False)


def project_per_pixel_offsets(
    along_track_m: Any,
    slant_range_m: Any,
    snr: Any,
    c_east: Any,
    c_north: Any,
    k_east: Any,
    k_north: Any,
    *,
    minimum_snr: float = SNR_THRESHOLD,
    maximum_magnitude_m: float = MAGNITUDE_CLIP_M,
) -> dict[str, Any]:
    """Project raw AT/SR offsets with per-pixel coefficients; apply source gates.

    The source formula is dE = AT*cE + SR*kE and dN = AT*cN + SR*kN.
    All inputs, including coefficients, must be 2-D rasters of identical shape.
    Scalar or implicit spatial broadcasting is intentionally forbidden so a
    scene-median/crown geometry cannot silently replace per-pixel geometry.
    Coefficients must already come from a verified radarGrid/DEM interpolation;
    this function neither reads the product metadata nor builds those rasters.
    """
    snr_min = _finite_float(minimum_snr, "minimum_snr", minimum=0.0)
    magnitude_limit = _finite_float(
        maximum_magnitude_m, "maximum_magnitude_m", minimum=1e-12
    )
    at = _raster(along_track_m, "along_track_m")
    shape = at.shape
    sr = _raster(slant_range_m, "slant_range_m", shape)
    snr_values = _raster(snr, "snr", shape)
    ce = _raster(c_east, "c_east", shape)
    cn = _raster(c_north, "c_north", shape)
    ke = _raster(k_east, "k_east", shape)
    kn = _raster(k_north, "k_north", shape)

    with np.errstate(invalid="ignore", over="ignore"):
        east_raw = at * ce + sr * ke
        north_raw = at * cn + sr * kn
        magnitude_raw = np.hypot(east_raw, north_raw)

    finite_offsets_and_geometry = (
        np.isfinite(at) & np.isfinite(sr)
        & np.isfinite(ce) & np.isfinite(cn)
        & np.isfinite(ke) & np.isfinite(kn)
        & np.isfinite(east_raw) & np.isfinite(north_raw)
        & np.isfinite(magnitude_raw)
    )
    finite_snr = np.isfinite(snr_values)
    snr_pass = finite_snr & (snr_values >= snr_min) & np.isfinite(magnitude_raw)
    magnitude_pass = np.isfinite(magnitude_raw) & (magnitude_raw <= magnitude_limit)
    valid = snr_pass & magnitude_pass
    east = np.where(valid, east_raw, np.nan).astype(np.float32, copy=False)
    north = np.where(valid, north_raw, np.nan).astype(np.float32, copy=False)
    magnitude = np.where(valid, magnitude_raw, np.nan).astype(np.float32, copy=False)

    return {
        "schema_version": SCREEN_SCHEMA,
        "status": "PER_PIXEL_OFFSET_PROJECTION_COMPUTED",
        "dE_m": east,
        "dN_m": north,
        "magnitude_m": magnitude,
        "valid_mask": valid,
        "quality_gate_counts": {
            "total_cells": int(valid.size),
            "finite_offsets_snr_and_geometry": int((finite_offsets_and_geometry & finite_snr).sum()),
            "snr_pass_with_finite_projection": int(snr_pass.sum()),
            "magnitude_within_limit": int(magnitude_pass.sum()),
            "final_valid_cells": int(valid.sum()),
            "rejected_snr_or_nonfinite": int((~snr_pass).sum()),
            "rejected_magnitude": int((snr_pass & ~magnitude_pass).sum()),
        },
        "geometry_policy": "PER_PIXEL_INTERPOLATED_COEFFICIENT_RASTERS_REQUIRED",
        "hazard_detection_status": "NOT_EVALUATED",
        "limitations": [
            "The source radarGrid geometry-cube interpolation and DEM handling are upstream prerequisites, not executed here.",
            "Projection parity is not established until the exact author inputs and geometry rasters are independently verified.",
        ],
    }


def residual_directional_coherence(
    residual_east_m: Any,
    residual_north_m: Any,
    window_size: int = COHERENCE_WINDOW_PIXELS,
    local_support_fraction: float = LOCAL_SUPPORT_FRACTION,
) -> np.ndarray:
    """Match archived 5x5 residual-vector coherence with >0.5 finite support."""
    _positive_odd_window(window_size, "window_size")
    support_limit = _finite_float(
        local_support_fraction,
        "local_support_fraction",
        minimum=0.0,
        maximum=1.0,
    )
    east = _raster(residual_east_m, "residual_east_m")
    north = _raster(residual_north_m, "residual_north_m", east.shape)
    with np.errstate(invalid="ignore", over="ignore"):
        residual_magnitude = np.hypot(east, north)
        ux = east / np.maximum(residual_magnitude, np.float32(1e-9))
        uy = north / np.maximum(residual_magnitude, np.float32(1e-9))
    support = uniform_filter(np.isfinite(ux).astype(np.float32), size=window_size)
    mean_x = local_nanmean(ux, window_size, support_limit)
    mean_y = local_nanmean(uy, window_size, support_limit)
    return np.where(
        support > 0.5,
        np.hypot(mean_x, mean_y),
        np.nan,
    ).astype(np.float32, copy=False)


def screen_pair(
    projection_result: dict[str, Any],
    *,
    interval: tuple[str, str],
    local_window_size: int = LOCAL_WINDOW_PIXELS,
    coherence_window_size: int = COHERENCE_WINDOW_PIXELS,
    local_support_fraction: float = LOCAL_SUPPORT_FRACTION,
    z_min: float = Z_THRESHOLD,
    anomaly_min_m: float = MAGNITUDE_ANOMALY_MIN_M,
    residual_r_min: float = RESIDUAL_COHERENCE_MIN,
) -> dict[str, Any]:
    """Apply the author footprint-screen anomaly + residual-coherence rules.

    Inputs must be the structured result of project_per_pixel_offsets, which
    applies SNR >= 5 and magnitude <= 10 m before screening. This requirement
    prevents accidental use of unfiltered or scalar-geometry displacement maps.
    The local MAD-like scale is the local mean of absolute magnitude anomaly,
    not a median absolute deviation.
    """
    _positive_odd_window(local_window_size, "local_window_size")
    _positive_odd_window(coherence_window_size, "coherence_window_size")
    support_min = _finite_float(
        local_support_fraction,
        "local_support_fraction",
        minimum=0.0,
        maximum=1.0,
    )
    z_threshold = _finite_float(z_min, "z_min")
    anomaly_threshold = _finite_float(anomaly_min_m, "anomaly_min_m", minimum=0.0)
    r_threshold = _finite_float(
        residual_r_min,
        "residual_r_min",
        minimum=0.0,
        maximum=1.0,
    )
    if not isinstance(interval, tuple) or len(interval) != 2 or any(
        not isinstance(item, str) or not item for item in interval
    ):
        raise FootprintScreenError("PAIR_INTERVAL_MUST_BE_TWO_NONEMPTY_STRINGS")

    if not isinstance(projection_result, dict):
        raise FootprintScreenError("SCREEN_REQUIRES_PROJECTION_RESULT_OBJECT")
    if (
        projection_result.get("schema_version") != SCREEN_SCHEMA
        or projection_result.get("status") != "PER_PIXEL_OFFSET_PROJECTION_COMPUTED"
        or projection_result.get("geometry_policy") != "PER_PIXEL_INTERPOLATED_COEFFICIENT_RASTERS_REQUIRED"
    ):
        raise FootprintScreenError("SCREEN_REQUIRES_DECLARED_PER_PIXEL_PROJECTION")
    east = _raster(projection_result.get("dE_m"), "projected_east_m")
    north = _raster(projection_result.get("dN_m"), "projected_north_m", east.shape)
    supplied_valid_mask = np.asarray(projection_result.get("valid_mask"))
    if supplied_valid_mask.shape != east.shape or supplied_valid_mask.dtype.kind != "b":
        raise FootprintScreenError("PROJECTION_VALID_MASK_SHAPE_OR_DTYPE_INVALID")
    finite_projected = np.isfinite(east) & np.isfinite(north)
    if not np.array_equal(supplied_valid_mask, finite_projected):
        raise FootprintScreenError("PROJECTION_VALID_MASK_MISMATCH")
    if interval not in EXPECTED_INTERVALS:
        raise FootprintScreenError("PAIR_INTERVAL_NOT_IN_AUTHOR_FIVE_PAIR_SET")
    with np.errstate(invalid="ignore", over="ignore", divide="ignore"):
        magnitude = np.hypot(east, north).astype(np.float32, copy=False)
        local_magnitude = local_nanmean(magnitude, local_window_size, support_min)
        anomaly = (magnitude - local_magnitude).astype(np.float32, copy=False)
        scale = local_nanmean(np.abs(anomaly), local_window_size, support_min)
        z_score = anomaly / np.maximum(scale, np.float32(0.05))
        residual_east = (east - local_nanmean(east, local_window_size, support_min)).astype(np.float32)
        residual_north = (north - local_nanmean(north, local_window_size, support_min)).astype(np.float32)
        residual_r = residual_directional_coherence(
            residual_east,
            residual_north,
            coherence_window_size,
            support_min,
        )
    hit = (
        np.isfinite(z_score) & (z_score >= z_threshold)
        & np.isfinite(anomaly) & (anomaly >= anomaly_threshold)
        & np.isfinite(residual_r) & (residual_r >= r_threshold)
    )

    return {
        "schema_version": SCREEN_SCHEMA,
        "status": "CANDIDATE_MOVEMENT_SCREEN_COMPUTED",
        "interval": interval,
        "hit_mask": hit,
        "hit_magnitude_anomaly_m": np.where(hit, anomaly, np.nan).astype(np.float32, copy=False),
        "hit_residual_R": np.where(hit, residual_r, np.nan).astype(np.float32, copy=False),
        "hit_z_score": np.where(hit, z_score, np.nan).astype(np.float32, copy=False),
        "hit_residual_east_m": np.where(hit, residual_east, np.nan).astype(np.float32, copy=False),
        "hit_residual_north_m": np.where(hit, residual_north, np.nan).astype(np.float32, copy=False),
        "diagnostic_maps": {
            "magnitude_m": magnitude,
            "magnitude_anomaly_m": anomaly,
            "local_magnitude_m": local_magnitude,
            "local_absolute_deviation_m": scale,
            "z_score": z_score.astype(np.float32, copy=False),
            "residual_R": residual_r,
        },
        "counts": {
            "total_grid_cells": int(hit.size),
            "valid_projected_cells": int((np.isfinite(east) & np.isfinite(north)).sum()),
            "finite_anomaly_cells": int(np.isfinite(anomaly).sum()),
            "finite_residual_R_cells": int(np.isfinite(residual_r).sum()),
            "candidate_cells": int(hit.sum()),
        },
        "policy": {
            "local_window_pixels": local_window_size,
            "local_support_fraction_strictly_greater_than": support_min,
            "coherence_window_pixels": coherence_window_size,
            "coherence_finite_support_strictly_greater_than": 0.5,
            "z_min": z_threshold,
            "minimum_magnitude_anomaly_m": anomaly_threshold,
            "minimum_residual_R": r_threshold,
            "interpretation": "Candidate surface with coherent local-residual motion; not a hazard classification or failure prediction.",
        },
        "hazard_detection_status": "NOT_EVALUATED",
    }


def aggregate_persistent_pairs(
    pair_results: Sequence[dict[str, Any]],
    minimum_epochs: int = MINIMUM_FLAGGED_INTERVALS,
) -> dict[str, Any]:
    """Require hits in >=N of the author's five exact, ordered date intervals."""
    if not isinstance(pair_results, (list, tuple)) or len(pair_results) != len(EXPECTED_INTERVALS):
        raise FootprintScreenError("EXACTLY_FIVE_ORDERED_PAIR_RESULTS_REQUIRED")
    if isinstance(minimum_epochs, bool) or not isinstance(minimum_epochs, int) or not 1 <= minimum_epochs <= len(EXPECTED_INTERVALS):
        raise FootprintScreenError("MINIMUM_EPOCHS_OUT_OF_RANGE")

    hit_masks: list[np.ndarray] = []
    anomaly_sum: np.ndarray | None = None
    residual_r_sum: np.ndarray | None = None
    for index, (expected_interval, result) in enumerate(zip(EXPECTED_INTERVALS, pair_results)):
        if not isinstance(result, dict) or result.get("status") != "CANDIDATE_MOVEMENT_SCREEN_COMPUTED":
            raise FootprintScreenError(f"PAIR_{index}_SCREEN_RESULT_INVALID")
        if tuple(result.get("interval", ())) != expected_interval:
            raise FootprintScreenError(f"PAIR_{index}_INTERVAL_ORDER_MISMATCH")
        hit = np.asarray(result.get("hit_mask"))
        if hit.ndim != 2 or hit.dtype.kind != "b":
            raise FootprintScreenError(f"PAIR_{index}_HIT_MASK_MUST_BE_2D_BOOL")
        if hit_masks and hit.shape != hit_masks[0].shape:
            raise FootprintScreenError(f"PAIR_{index}_GRID_SHAPE_MISMATCH")
        anomaly = _raster(result.get("hit_magnitude_anomaly_m"), f"pair_{index}_anomaly", hit.shape)
        residual_r = _raster(result.get("hit_residual_R"), f"pair_{index}_residual_R", hit.shape)
        hit_masks.append(hit)
        # Match the archive: out-of-hit NaNs become zero before accumulation;
        # means are then divided by the number of intervals that flagged a cell.
        if anomaly_sum is None:
            anomaly_sum = np.nan_to_num(anomaly).astype(np.float32)
            residual_r_sum = np.nan_to_num(residual_r).astype(np.float32)
        else:
            anomaly_sum += np.nan_to_num(anomaly)
            residual_r_sum += np.nan_to_num(residual_r)

    epoch_count = np.sum(np.stack(hit_masks, axis=0), axis=0, dtype=np.uint8)
    persistent = epoch_count >= minimum_epochs
    divisor = np.maximum(epoch_count, 1).astype(np.float32)
    mean_anomaly = np.where(persistent, anomaly_sum / divisor, np.nan).astype(np.float32, copy=False)
    mean_r = np.where(persistent, residual_r_sum / divisor, np.nan).astype(np.float32, copy=False)
    return {
        "schema_version": SCREEN_SCHEMA,
        "status": "PERSISTENT_CANDIDATE_SCREEN_COMPUTED",
        "n_epochs_flagged": epoch_count,
        "persistent_mask": persistent,
        "mean_hit_magnitude_anomaly_m": mean_anomaly,
        "mean_hit_residual_R": mean_r,
        "counts": {
            "grid_cells": int(persistent.size),
            "cells_flagged_at_least_once": int((epoch_count > 0).sum()),
            "cells_persistent": int(persistent.sum()),
        },
        "policy": {
            "ordered_intervals": [f"{a}->{b}" for a, b in EXPECTED_INTERVALS],
            "minimum_flagged_intervals": minimum_epochs,
        },
        "hazard_detection_status": "NOT_EVALUATED",
    }


def filter_persistent_components(
    persistent_mask: Any,
    minimum_component_pixels: int = MINIMUM_COMPONENT_PIXELS,
) -> dict[str, Any]:
    """Match archived scipy.ndimage.label default connectivity and 10-pixel gate."""
    mask = np.asarray(persistent_mask)
    if mask.ndim != 2 or mask.dtype.kind != "b":
        raise FootprintScreenError("PERSISTENT_MASK_MUST_BE_2D_BOOL")
    if (
        isinstance(minimum_component_pixels, bool)
        or not isinstance(minimum_component_pixels, int)
        or minimum_component_pixels < 1
    ):
        raise FootprintScreenError("MINIMUM_COMPONENT_PIXELS_INVALID")
    component_labels, component_count = label(mask)
    sizes = np.bincount(component_labels.ravel(), minlength=component_count + 1)
    retained_ids = [
        component
        for component in range(1, component_count + 1)
        if int(sizes[component]) >= minimum_component_pixels
    ]
    retained = np.isin(component_labels, retained_ids)
    retained_labels = np.where(retained, component_labels, 0).astype(np.int32, copy=False)
    return {
        "schema_version": SCREEN_SCHEMA,
        "status": "PERSISTENT_COMPONENT_FILTER_COMPUTED",
        "candidate_mask": retained,
        "component_labels": retained_labels,
        "counts": {
            "input_persistent_cells": int(mask.sum()),
            "input_connected_components": int(component_count),
            "retained_components": len(retained_ids),
            "retained_candidate_cells": int(retained.sum()),
            "minimum_component_pixels": minimum_component_pixels,
        },
        "retained_component_sizes_pixels": [int(sizes[component]) for component in retained_ids],
        "hazard_detection_status": "NOT_EVALUATED",
    }
