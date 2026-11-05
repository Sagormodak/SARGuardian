"""Exploratory spatial-block bootstrap uncertainty for GOFF displacement summaries.

The interval estimates represent spatial sampling variability conditional on the
chosen block scale and valid mask. They do not include orbit, DEM, projection,
instrument, product-release, model-selection, or reference-frame systematic error.
They are not calibrated event probabilities.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def _ci(values: list[float] | np.ndarray) -> list[float] | None:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        return None
    q = np.percentile(array, [2.5, 97.5])
    return [float(q[0]), float(q[1])]


def _azimuth(east: float, north: float) -> float:
    if not (math.isfinite(east) and math.isfinite(north)) or math.hypot(east, north) <= 0:
        return float("nan")
    return (math.degrees(math.atan2(east, north)) + 360.0) % 360.0


def _wrap_360(value: float) -> float:
    return float(value % 360.0)


def spatial_block_bootstrap_summary(
    east_m: Any,
    north_m: Any,
    valid: Any,
    aoi_mask: Any,
    *,
    block_size_cells: int = 5,
    replicates: int = 1000,
    seed: int = 260826,
    minimum_blocks: int = 8,
) -> dict[str, Any]:
    """Return block-bootstrap percentile intervals for median/vector summaries.

    Non-overlapping raster-aligned blocks are sampled with replacement. Only
    valid AOI cells inside each selected block contribute. The block origin,
    block size, random seed and generator are part of the analysis policy.
    """
    east = np.asarray(east_m, dtype=float)
    north = np.asarray(north_m, dtype=float)
    mask = np.asarray(valid, dtype=bool)
    aoi = np.asarray(aoi_mask, dtype=bool)
    if east.ndim != 2 or north.shape != east.shape or mask.shape != east.shape or aoi.shape != east.shape:
        raise ValueError("UNCERTAINTY_ARRAY_SHAPE_MISMATCH")
    if isinstance(block_size_cells, bool) or not isinstance(block_size_cells, int) or block_size_cells < 1:
        raise ValueError("UNCERTAINTY_BLOCK_SIZE_INVALID")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 100:
        raise ValueError("UNCERTAINTY_REPLICATES_MUST_BE_AT_LEAST_100")
    if isinstance(minimum_blocks, bool) or not isinstance(minimum_blocks, int) or minimum_blocks < 4:
        raise ValueError("UNCERTAINTY_MINIMUM_BLOCKS_MUST_BE_AT_LEAST_4")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("UNCERTAINTY_SEED_INVALID")

    usable = mask & aoi & np.isfinite(east) & np.isfinite(north)
    valid_pixels = int(usable.sum())
    if not valid_pixels:
        return {
            "status": "INSUFFICIENT_VALID_AOI_PIXELS",
            "valid_aoi_pixels": 0,
            "method": "spatial_block_bootstrap",
            "policy_version": "spatial-block-bootstrap-v1",
        }

    h, w = east.shape
    blocks: list[tuple[np.ndarray, np.ndarray]] = []
    block_coordinates: list[tuple[int, int]] = []
    for r0 in range(0, h, block_size_cells):
        for c0 in range(0, w, block_size_cells):
            window_mask = usable[r0:min(h, r0 + block_size_cells), c0:min(w, c0 + block_size_cells)]
            if not window_mask.any():
                continue
            es = east[r0:min(h, r0 + block_size_cells), c0:min(w, c0 + block_size_cells)][window_mask]
            ns = north[r0:min(h, r0 + block_size_cells), c0:min(w, c0 + block_size_cells)][window_mask]
            blocks.append((es, ns))
            block_coordinates.append((r0 // block_size_cells, c0 // block_size_cells))

    block_count = len(blocks)
    base = {
        "method": "non-overlapping raster-aligned spatial-block bootstrap",
        "policy_version": "spatial-block-bootstrap-v1",
        "block_size_cells": block_size_cells,
        "replicates": replicates,
        "seed": seed,
        "prng": "numpy.default_rng/PCG64",
        "valid_aoi_pixels": valid_pixels,
        "valid_block_count": block_count,
        "minimum_blocks_required": minimum_blocks,
        "block_origin": "upper-left array index (0,0)",
        "coverage": "conditional spatial sampling variability; not a complete sensor/model uncertainty budget",
        "limitations": [
            "Block scale is a versioned working assumption and must be compared with GOFF matching-window support.",
            "Intervals exclude systematic errors from geometry, height/DEM, registration, release variants and reference correction.",
            "A confidence interval is not a calibrated probability of landslide or glacier collapse.",
        ],
    }
    if block_count < minimum_blocks:
        return {
            **base,
            "status": "INSUFFICIENT_SPATIAL_BLOCKS",
            "reason": "Too few spatially distinct valid AOI blocks for the configured bootstrap policy",
        }

    all_east = np.concatenate([es for es, _ in blocks])
    all_north = np.concatenate([ns for _, ns in blocks])
    observed_mag = np.hypot(all_east, all_north)
    observed_mean_e = float(np.mean(all_east))
    observed_mean_n = float(np.mean(all_north))
    observed_mean_mag = math.hypot(observed_mean_e, observed_mean_n)
    observed_azimuth = _azimuth(observed_mean_e, observed_mean_n)

    rng = np.random.default_rng(seed)
    medians: list[float] = []
    mean_magnitudes: list[float] = []
    azimuths: list[float] = []
    for _ in range(replicates):
        indices = rng.integers(0, block_count, size=block_count)
        e_sample = np.concatenate([blocks[i][0] for i in indices])
        n_sample = np.concatenate([blocks[i][1] for i in indices])
        mag_sample = np.hypot(e_sample, n_sample)
        mean_e, mean_n = float(np.mean(e_sample)), float(np.mean(n_sample))
        medians.append(float(np.median(mag_sample)))
        mean_magnitudes.append(math.hypot(mean_e, mean_n))
        azimuths.append(_azimuth(mean_e, mean_n))

    azimuth_array = np.asarray(azimuths, dtype=float)
    finite_azimuth = azimuth_array[np.isfinite(azimuth_array)]
    if math.isfinite(observed_azimuth) and finite_azimuth.size:
        wrapped_delta = ((finite_azimuth - observed_azimuth + 180.0) % 360.0) - 180.0
        lower_delta, upper_delta = np.percentile(wrapped_delta, [2.5, 97.5])
        lower_az = _wrap_360(observed_azimuth + float(lower_delta))
        upper_az = _wrap_360(observed_azimuth + float(upper_delta))
        azimuth_arc = {
            "start_deg_clockwise_from_north": lower_az,
            "end_deg_clockwise_from_north": upper_az,
            "width_deg": float(upper_delta - lower_delta),
            "crosses_0_deg": lower_az > upper_az,
            "note": "Wrapped 95% arc centred on the observed vector direction; start may numerically exceed end when it crosses north.",
        }
    else:
        azimuth_arc = None

    return {
        **base,
        "status": "COMPUTED_EXPLORATORY",
        "statistics": {
            "median_horizontal_magnitude_m": float(np.median(observed_mag)),
            "median_horizontal_magnitude_95pct_interval_m": _ci(medians),
            "mean_vector_magnitude_m": observed_mean_mag,
            "mean_vector_magnitude_95pct_interval_m": _ci(mean_magnitudes),
            "mean_vector_east_m": observed_mean_e,
            "mean_vector_north_m": observed_mean_n,
            "mean_vector_azimuth_deg_clockwise_from_north": observed_azimuth,
            "mean_vector_azimuth_95pct_arc": azimuth_arc,
        },
    }


def spatial_block_bootstrap_sensitivity(
    east_m: Any,
    north_m: Any,
    valid: Any,
    aoi_mask: Any,
    *,
    block_sizes_cells: tuple[int, ...] = (3, 5, 10),
    replicates_per_size: int = 300,
    seed: int = 260826,
    minimum_blocks: int = 8,
) -> dict[str, Any]:
    """Quantify how spatial-block size changes uncertainty intervals.

    Each block size gets its own recorded, deterministic seed. This sensitivity
    table is required because a single arbitrary block size can materially
    understate or overstate spatial uncertainty. The 5-cell row can be compared
    with the runner's higher-replicate primary estimate.
    """
    if not block_sizes_cells or len(set(block_sizes_cells)) != len(block_sizes_cells):
        raise ValueError("UNCERTAINTY_BLOCK_SIZES_MUST_BE_NONEMPTY_AND_UNIQUE")
    if any(isinstance(size, bool) or not isinstance(size, int) or size < 1 for size in block_sizes_cells):
        raise ValueError("UNCERTAINTY_BLOCK_SIZES_INVALID")
    if isinstance(replicates_per_size, bool) or not isinstance(replicates_per_size, int) or replicates_per_size < 100:
        raise ValueError("UNCERTAINTY_REPLICATES_MUST_BE_AT_LEAST_100")

    rows: list[dict[str, Any]] = []
    for index, block_size in enumerate(block_sizes_cells):
        # Deterministic distinct substreams, stable for the ordered size list.
        child_seed = seed + 1009 * index
        result = spatial_block_bootstrap_summary(
            east_m, north_m, valid, aoi_mask,
            block_size_cells=block_size,
            replicates=replicates_per_size,
            seed=child_seed,
            minimum_blocks=minimum_blocks,
        )
        stats = result.get("statistics", {})
        rows.append({
            "block_size_cells": block_size,
            "seed": child_seed,
            "replicates": replicates_per_size,
            "status": result["status"],
            "valid_block_count": result.get("valid_block_count", 0),
            "median_horizontal_magnitude_m": stats.get("median_horizontal_magnitude_m"),
            "median_horizontal_magnitude_95pct_interval_m": stats.get("median_horizontal_magnitude_95pct_interval_m"),
            "mean_vector_magnitude_m": stats.get("mean_vector_magnitude_m"),
            "mean_vector_magnitude_95pct_interval_m": stats.get("mean_vector_magnitude_95pct_interval_m"),
            "mean_vector_azimuth_95pct_arc": stats.get("mean_vector_azimuth_95pct_arc"),
        })
    complete = all(row["status"] == "COMPUTED_EXPLORATORY" for row in rows)
    return {
        "schema_version": "spatial-block-uncertainty-sensitivity/1.0",
        "status": "COMPUTED_EXPLORATORY" if complete else "PARTIAL_INSUFFICIENT_BLOCK_SUPPORT",
        "sizes_tested_cells": list(block_sizes_cells),
        "rows": rows,
        "interpretation": (
            "Compare how confidence intervals and valid-block support respond to block size. "
            "These are conditional spatial-sampling intervals, not systematic-error intervals "
            "or calibrated hazard probabilities."
        ),
    }
