"""Pure scientific kernels for isolated Know Place Analysis.

These functions accept raw GOFF layer-2 offsets and verified metadata. They do
not consume the existing reader's already corrected GeoTIFFs as raw data.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

PAPER_INTERVALS = (
    ("2026-06-20", "2026-07-02"),
    ("2026-07-02", "2026-07-14"),
    ("2026-07-14", "2026-07-26"),
    ("2026-07-26", "2026-08-19"),
    ("2026-08-19", "2026-08-31"),
)
PAPER_TRACK = "098"
PAPER_DIRECTION = "A"
PAPER_POLARIZATION = "HH"
PAPER_LAYER = "layer2"


class ScientificInputError(ValueError):
    """An input is incomplete or incompatible with the declared method."""


@dataclass(frozen=True)
class GateCounts:
    total_cells: int
    input_valid: int
    finite_offsets_and_snr: int
    snr_pass: int
    projected_magnitude_pass: int
    final_valid: int
    rejected_nonfinite: int
    rejected_snr: int
    rejected_magnitude: int


def _raster_arrays(**arrays: Any) -> dict[str, np.ndarray]:
    """Convert inputs to floats; allow scalar geometry but no spatial broadcasting."""
    result: dict[str, np.ndarray] = {}
    shape = None
    for name, value in arrays.items():
        arr = np.asarray(value)
        if arr.ndim == 0:
            result[name] = arr.astype(float)
        elif arr.ndim == 2:
            if shape is None:
                shape = arr.shape
            elif arr.shape != shape:
                raise ScientificInputError(
                    f"shape mismatch: {name}={arr.shape}, expected={shape}"
                )
            result[name] = arr.astype(float, copy=False)
        else:
            raise ScientificInputError(f"{name} must be a 2-D raster or scalar")
    if shape is None:
        raise ScientificInputError("at least one 2-D raster array is required")
    for name, arr in list(result.items()):
        if arr.ndim == 0:
            result[name] = np.full(shape, float(arr), dtype=float)
    return result


def project_offsets_to_horizontal(
    along_track_m: Any,
    slant_range_m: Any,
    atu_x: Any,
    atu_y: Any,
    los_x: Any,
    los_y: Any,
    incidence_deg: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Project raw AT/SR offsets to east/north displacement (metres).

    Implements the product-convention equations in Meena (2026), Eqs. 1-2.
    Vertical motion is assumed zero. Geometry must be read from verified
    product metadata; signs must never be adjusted to force an expected result.
    """
    a = _raster_arrays(
        at=along_track_m, sr=slant_range_m, atu_x=atu_x, atu_y=atu_y,
        los_x=los_x, los_y=los_y, incidence_deg=incidence_deg,
    )
    theta = np.deg2rad(a["incidence_deg"])
    sin_theta = np.sin(theta)
    los_h = np.hypot(a["los_x"], a["los_y"])
    finite_angle = np.isfinite(theta)
    if np.any(finite_angle & ((theta <= 0) | (theta >= math.pi / 2))):
        raise ScientificInputError("incidence must be strictly between 0 and 90 degrees")
    finite_los = np.isfinite(los_h)
    if np.any(finite_los & (los_h <= 0)):
        raise ScientificInputError("horizontal LOS-vector norm must be positive")
    geometry_ok = (
        np.isfinite(a["atu_x"]) & np.isfinite(a["atu_y"])
        & np.isfinite(a["los_x"]) & np.isfinite(a["los_y"])
        & np.isfinite(sin_theta) & np.isfinite(los_h)
        & (sin_theta > 0) & (los_h > 0)
    )
    east = np.full(a["at"].shape, np.nan, dtype=float)
    north = np.full_like(east, np.nan)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        e = a["at"] * a["atu_x"] - (a["sr"] / sin_theta) * (a["los_x"] / los_h)
        n = a["at"] * a["atu_y"] - (a["sr"] / sin_theta) * (a["los_y"] / los_h)
    good = geometry_ok & np.isfinite(a["at"]) & np.isfinite(a["sr"])
    east[good] = e[good]
    north[good] = n[good]
    return east, north


def apply_paper_quality_gates(
    east_m: Any,
    north_m: Any,
    snr: Any,
    *,
    input_valid: Any | None = None,
    minimum_snr: float = 5.0,
    maximum_horizontal_magnitude_m: float = 10.0,
) -> tuple[np.ndarray, GateCounts, np.ndarray]:
    """Apply SNR >= 5 and reject (never clip) projected magnitude > 10 m."""
    if not math.isfinite(minimum_snr) or minimum_snr < 0:
        raise ScientificInputError("minimum_snr must be finite and nonnegative")
    if not math.isfinite(maximum_horizontal_magnitude_m) or maximum_horizontal_magnitude_m <= 0:
        raise ScientificInputError("maximum magnitude must be finite and positive")
    a = _raster_arrays(east=east_m, north=north_m, snr=snr)
    shape = a["east"].shape
    upstream = np.ones(shape, dtype=bool) if input_valid is None else np.asarray(input_valid, bool)
    if upstream.shape != shape:
        raise ScientificInputError("input_valid shape mismatch")
    finite = upstream & np.isfinite(a["east"]) & np.isfinite(a["north"]) & np.isfinite(a["snr"])
    snr_pass = finite & (a["snr"] >= minimum_snr)
    magnitude = np.hypot(a["east"], a["north"])
    final = snr_pass & np.isfinite(magnitude) & (magnitude <= maximum_horizontal_magnitude_m)
    counts = GateCounts(
        total_cells=int(upstream.size),
        input_valid=int(upstream.sum()),
        finite_offsets_and_snr=int(finite.sum()),
        snr_pass=int(snr_pass.sum()),
        projected_magnitude_pass=int(final.sum()),
        final_valid=int(final.sum()),
        rejected_nonfinite=int((upstream & ~finite).sum()),
        rejected_snr=int((finite & (a["snr"] < minimum_snr)).sum()),
        rejected_magnitude=int((snr_pass & (magnitude > maximum_horizontal_magnitude_m)).sum()),
    )
    return final, counts, magnitude


def componentwise_background_correction(
    east_m: Any,
    north_m: Any,
    valid: Any,
    background_box: Any,
    crown: Any,
) -> tuple[np.ndarray, np.ndarray, dict[str, float | int]]:
    """Subtract component medians from valid box cells outside the crown."""
    a = _raster_arrays(east=east_m, north=north_m)
    east, north = a["east"], a["north"]
    masks = [np.asarray(x, dtype=bool) for x in (valid, background_box, crown)]
    if any(x.shape != east.shape for x in masks):
        raise ScientificInputError("all masks and displacement arrays must share shape")
    valid_mask, box, target = masks
    if np.any(target & ~box):
        raise ScientificInputError("crown must be contained by the reference box")
    usable = valid_mask & np.isfinite(east) & np.isfinite(north)
    reference = usable & box & ~target
    target_valid = usable & target
    if not target_valid.any():
        raise ScientificInputError("NO_VALID_CROWN_PIXELS")
    if not reference.any():
        raise ScientificInputError("NO_VALID_BACKGROUND_PIXELS_OUTSIDE_CROWN")
    east_bias = float(np.median(east[reference]))
    north_bias = float(np.median(north[reference]))
    corrected_east = np.full(east.shape, np.nan, dtype=float)
    corrected_north = np.full(north.shape, np.nan, dtype=float)
    corrected_east[usable] = east[usable] - east_bias
    corrected_north[usable] = north[usable] - north_bias
    return corrected_east, corrected_north, {
        "background_valid_pixels": int(reference.sum()),
        "crown_valid_pixels": int(target_valid.sum()),
        "background_east_bias_m": east_bias,
        "background_north_bias_m": north_bias,
    }


def directional_coherence(
    east_m: Any,
    north_m: Any,
    valid: Any,
    *,
    window_size: int = 5,
    minimum_valid_cells: int = 1,
) -> np.ndarray:
    """Centred-window mean resultant length R of unit horizontal vectors.

    Windows are zero-padded at edges, not reflected. Zero-length vectors have
    no direction and do not contribute. The minimum valid count is explicit
    and must be aligned with the author-supplement implementation before
    declaring an exact reproduction.
    """
    if window_size < 1 or window_size % 2 != 1:
        raise ScientificInputError("window_size must be a positive odd integer")
    if not (1 <= minimum_valid_cells <= window_size * window_size):
        raise ScientificInputError("minimum_valid_cells outside valid range")
    a = _raster_arrays(east=east_m, north=north_m)
    east, north = a["east"], a["north"]
    mask = np.asarray(valid, dtype=bool)
    if mask.shape != east.shape:
        raise ScientificInputError("valid shape mismatch")
    mag = np.hypot(east, north)
    good = mask & np.isfinite(east) & np.isfinite(north) & np.isfinite(mag) & (mag > 0)
    ux = np.zeros(east.shape, dtype=float)
    uy = np.zeros(east.shape, dtype=float)
    ux[good] = east[good] / mag[good]
    uy[good] = north[good] / mag[good]
    radius = window_size // 2
    px = np.pad(ux, radius, mode="constant")
    py = np.pad(uy, radius, mode="constant")
    pm = np.pad(good.astype(np.int16), radius, mode="constant")
    h, w = east.shape
    sx = np.zeros(east.shape, dtype=float)
    sy = np.zeros(east.shape, dtype=float)
    count = np.zeros(east.shape, dtype=np.int16)
    for dy in range(window_size):
        for dx in range(window_size):
            view = (slice(dy, dy + h), slice(dx, dx + w))
            sx += px[view]
            sy += py[view]
            count += pm[view]
    result = np.full(east.shape, np.nan, dtype=float)
    use = count >= minimum_valid_cells
    result[use] = np.minimum(1.0, np.hypot(sx[use], sy[use]) / count[use])
    return result


def summarize_crown(
    east_m: Any,
    north_m: Any,
    valid: Any,
    crown: Any,
    coherence: Any,
    *,
    interval_days: int,
) -> dict[str, float | int]:
    """Report crown median magnitude and mean vector as distinct statistics."""
    if interval_days <= 0:
        raise ScientificInputError("interval_days must be positive")
    a = _raster_arrays(east=east_m, north=north_m, coherence=coherence)
    east, north, R = a["east"], a["north"], a["coherence"]
    valid_mask, target = np.asarray(valid, bool), np.asarray(crown, bool)
    if valid_mask.shape != east.shape or target.shape != east.shape:
        raise ScientificInputError("valid/crown mask shape mismatch")
    use = valid_mask & target & np.isfinite(east) & np.isfinite(north)
    if not use.any():
        raise ScientificInputError("NO_VALID_CROWN_PIXELS")
    magnitude = np.hypot(east[use], north[use])
    mean_east, mean_north = float(np.mean(east[use])), float(np.mean(north[use]))
    mean_mag = math.hypot(mean_east, mean_north)
    azimuth = (math.degrees(math.atan2(mean_east, mean_north)) + 360.0) % 360.0
    r_use = use & np.isfinite(R)
    return {
        "valid_crown_pixels": int(use.sum()),
        "crown_median_horizontal_magnitude_m": float(np.median(magnitude)),
        "crown_mean_vector_east_m": mean_east,
        "crown_mean_vector_north_m": mean_north,
        "crown_mean_vector_magnitude_m": mean_mag,
        "crown_mean_vector_azimuth_deg_clockwise_from_north": azimuth,
        "crown_median_magnitude_rate_m_per_day": float(np.median(magnitude) / interval_days),
        "crown_median_directional_coherence_R": float(np.median(R[r_use])) if r_use.any() else float("nan"),
        "coherence_valid_crown_pixels": int(r_use.sum()),
    }


def empirical_percentile(reference_distribution: Any, observed: float) -> float:
    """100 times the fraction of null draws less than or equal to observation."""
    values = np.asarray(reference_distribution, dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        raise ScientificInputError("EMPTY_NULL_DISTRIBUTION")
    if not math.isfinite(observed):
        raise ScientificInputError("OBSERVED_STATISTIC_NONFINITE")
    return float(100.0 * np.count_nonzero(values <= observed) / values.size)


def size_matched_spatial_controls(
    magnitude_m: Any,
    coherence_R: Any,
    valid: Any,
    background_box: Any,
    crown: Any,
    *,
    pixel_size_x_m: float = 80.0,
    pixel_size_y_m: float = 80.0,
    draws: int = 1000,
    seed: int = 260826,
    minimum_valid_fraction: float = 0.60,
) -> dict[str, Any]:
    """Deterministic circular controls; exact paper parity needs supplement review."""
    if pixel_size_x_m <= 0 or pixel_size_y_m <= 0:
        raise ScientificInputError("pixel dimensions must be positive")
    if draws < 1 or not (0 < minimum_valid_fraction <= 1):
        raise ScientificInputError("invalid draw count or minimum valid fraction")
    a = _raster_arrays(magnitude=magnitude_m, coherence=coherence_R)
    magnitude, R = a["magnitude"], a["coherence"]
    mask, box, target = (np.asarray(x, bool) for x in (valid, background_box, crown))
    if any(x.shape != magnitude.shape for x in (mask, box, target)):
        raise ScientificInputError("control arrays and masks must share shape")
    usable = mask & np.isfinite(magnitude) & box
    crown_usable = usable & target
    background_usable = usable & ~target
    target_count = int(crown_usable.sum())
    if target_count < 1:
        raise ScientificInputError("NO_VALID_CROWN_PIXELS_FOR_CONTROLS")
    # A control center and its measured cells must be outside the crown; otherwise
    # the target signal contaminates its own null distribution.
    centers = np.argwhere(background_usable)
    if not len(centers):
        raise ScientificInputError("NO_VALID_BACKGROUND_CELLS_FOR_CONTROLS")
    radius_m = math.sqrt(target_count * pixel_size_x_m * pixel_size_y_m / math.pi)
    max_r = int(math.ceil(max(radius_m / pixel_size_x_m, radius_m / pixel_size_y_m)))
    rng = np.random.default_rng(seed)
    h, w = magnitude.shape
    yy, xx = np.ogrid[:h, :w]
    min_count = int(math.ceil(target_count * minimum_valid_fraction))
    mag_values: list[float] = []
    r_values: list[float] = []
    valid_counts: list[int] = []
    rejected = 0
    for _ in range(draws):
        cy, cx = map(int, centers[int(rng.integers(0, len(centers)))])
        y0, y1 = max(0, cy - max_r), min(h, cy + max_r + 1)
        x0, x1 = max(0, cx - max_r), min(w, cx + max_r + 1)
        circle = (((yy[y0:y1] - cy) * pixel_size_y_m) ** 2
                  + ((xx[:, x0:x1] - cx) * pixel_size_x_m) ** 2) <= radius_m ** 2
        sample = circle & background_usable[y0:y1, x0:x1]
        count = int(sample.sum())
        if count < min_count:
            rejected += 1
            continue
        mag_values.append(float(np.median(magnitude[y0:y1, x0:x1][sample])))
        r_sample = R[y0:y1, x0:x1][sample]
        r_sample = r_sample[np.isfinite(r_sample)]
        r_values.append(float(np.median(r_sample)) if len(r_sample) else float("nan"))
        valid_counts.append(count)
    if not mag_values:
        raise ScientificInputError("NO_ACCEPTED_SIZE_MATCHED_CONTROL_DRAWS")
    mag_array = np.asarray(mag_values, float)
    r_array = np.asarray(r_values, float)
    return {
        "draws_requested": draws,
        "draws_accepted": len(mag_values),
        "draws_rejected": rejected,
        "seed": seed,
        "prng": "numpy.default_rng/PCG64",
        "target_valid_pixels": target_count,
        "minimum_valid_pixels_per_draw": min_count,
        "nominal_control_radius_m": radius_m,
        "minimum_valid_fraction": minimum_valid_fraction,
        "control_median_of_median_displacement_m": float(np.median(mag_array)),
        "displacement_empirical_percentile": None,
        "directional_coherence_empirical_percentile": None,
        "displacement_control_values_m": mag_values,
        "directional_coherence_control_values_R": r_values,
        "valid_pixel_counts": valid_counts,
        "mag_distribution_for_percentile": mag_array,
        "R_distribution_for_percentile": r_array[np.isfinite(r_array)],
    }


def validate_five_pair_inventory(products: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Select the five target dates and fail closed on missing/duplicate/wrong IDs."""
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for product in products:
        pair = (str(product.get("reference_date", "")), str(product.get("secondary_date", "")))
        if pair in PAPER_INTERVALS:
            indexed.setdefault(pair, []).append(product)
    missing = [pair for pair in PAPER_INTERVALS if pair not in indexed]
    duplicates = [pair for pair, rows in indexed.items() if len(rows) != 1]
    if missing:
        raise ScientificInputError(f"MISSING_PAPER_PAIRS={missing}")
    if duplicates:
        raise ScientificInputError(f"DUPLICATE_PAPER_PAIRS={duplicates}")
    selected: dict[str, dict[str, Any]] = {}
    expected = {
        "product_type": "GOFF", "track": PAPER_TRACK, "direction": PAPER_DIRECTION,
        "polarization": PAPER_POLARIZATION, "layer": PAPER_LAYER,
    }
    for pair in PAPER_INTERVALS:
        product = indexed[pair][0]
        actual = {
            "product_type": str(product.get("product_type", "")).upper(),
            "track": str(product.get("track", "")),
            "direction": str(product.get("direction", "")).upper(),
            "polarization": str(product.get("polarization", "")).upper(),
            "layer": str(product.get("layer", "")).lower(),
        }
        mismatch = {k: {"expected": v, "actual": actual[k]} for k, v in expected.items() if actual[k] != v}
        if mismatch:
            raise ScientificInputError(f"TARGET_PAIR_IDENTITY_MISMATCH pair={pair} fields={mismatch}")
        selected[f"{pair[0]}__{pair[1]}"] = product
    return selected
