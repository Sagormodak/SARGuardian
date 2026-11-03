from __future__ import annotations

import numpy as np
from scipy import ndimage


def otsu_threshold_db(values_db: np.ndarray, valid: np.ndarray, bins: int = 512) -> float:
    """Estimate one global Otsu threshold in dB from all selected dates."""
    values = np.asarray(values_db, dtype=np.float64)[np.asarray(valid, dtype=bool)]
    values = values[np.isfinite(values)]
    if values.size < 100:
        raise ValueError("At least 100 valid pixels are required for Otsu threshold estimation.")

    low, high = np.percentile(values, [1.0, 99.0])
    if not np.isfinite(low + high) or high <= low:
        raise ValueError("Backscatter distribution has insufficient variation for Otsu.")
    histogram, edges = np.histogram(values, bins=bins, range=(low, high))
    centers = (edges[:-1] + edges[1:]) / 2.0

    weight_left = np.cumsum(histogram, dtype=np.float64)
    weighted_left = np.cumsum(histogram * centers, dtype=np.float64)
    total = weight_left[-1]
    total_weighted = weighted_left[-1]
    weight_right = total - weight_left
    valid_split = (weight_left > 0) & (weight_right > 0)

    between = np.full(histogram.shape, -np.inf, dtype=np.float64)
    numerator = (total_weighted * weight_left - weighted_left * total) ** 2
    between[valid_split] = numerator[valid_split] / (
        weight_left[valid_split] * weight_right[valid_split]
    )
    best = int(np.argmax(between))
    threshold = float(centers[best])
    if not np.isfinite(threshold):
        raise ValueError("Could not estimate a finite Otsu threshold.")
    return threshold


def remove_small_components(mask: np.ndarray, valid: np.ndarray, minimum_pixels: int) -> np.ndarray:
    """Remove connected components smaller than the requested pixel count."""
    result = np.asarray(mask, dtype=bool) & np.asarray(valid, dtype=bool)
    if minimum_pixels <= 1 or not result.any():
        return result

    labels, count = ndimage.label(result, structure=np.ones((3, 3), dtype=np.uint8))
    if count == 0:
        return result
    sizes = np.bincount(labels.ravel())
    keep = sizes >= int(minimum_pixels)
    keep[0] = False
    return keep[labels]


def classify_open_water(
    backscatter: np.ndarray,
    valid: np.ndarray,
    *,
    units: str,
    threshold_db: float,
    minimum_pixels: int = 1,
) -> np.ndarray:
    """Classify low-backscatter open-water candidates using a declared threshold.

    This is an intensity-screening method, not a universal water classifier.
    Flooded vegetation can produce strong double-bounce returns and may be missed.
    """
    array = np.asarray(backscatter, dtype=np.float64)
    valid_mask = np.asarray(valid, dtype=bool) & np.isfinite(array)
    if units == "linear":
        valid_mask &= array > 0
        values_db = np.full(array.shape, np.nan, dtype=np.float64)
        values_db[valid_mask] = 10.0 * np.log10(array[valid_mask])
    elif units == "db":
        values_db = array
    else:
        raise ValueError("units must be either 'linear' or 'db'.")

    water = valid_mask & (values_db <= float(threshold_db))
    return remove_small_components(water, valid_mask, minimum_pixels)
