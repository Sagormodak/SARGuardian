from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from typing import Any

import numpy as np

from .raster_io import (
    assert_same_grid,
    read_band,
    require_projected_metre_grid,
    safe_float,
    save_json,
    sha256_file,
)


def _metric_values(counts: np.ndarray) -> dict[str, float]:
    tp, tn, fp, fn = (int(value) for value in counts)
    total = tp + tn + fp + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "accuracy": (tp + tn) / total if total else 0.0,
        "precision_user_accuracy": precision,
        "recall_producer_accuracy": recall,
        "f1_score": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "intersection_over_union": tp / (tp + fp + fn) if tp + fp + fn else 0.0,
        "area_bias_percent": ((tp + fp) - (tp + fn)) / (tp + fn) * 100 if tp + fn else float("nan"),
    }


def _block_confusion_counts(
    prediction: np.ndarray, reference: np.ndarray, valid: np.ndarray, block_size: int
) -> np.ndarray:
    rows, cols = valid.shape
    counts = []
    for row in range(0, rows, block_size):
        for col in range(0, cols, block_size):
            block_valid = valid[row:row + block_size, col:col + block_size]
            if not block_valid.any():
                continue
            pred = prediction[row:row + block_size, col:col + block_size][block_valid].astype(bool)
            ref = reference[row:row + block_size, col:col + block_size][block_valid].astype(bool)
            tp = int(np.sum(pred & ref))
            tn = int(np.sum(~pred & ~ref))
            fp = int(np.sum(pred & ~ref))
            fn = int(np.sum(~pred & ref))
            counts.append((tp, tn, fp, fn))
    return np.asarray(counts, dtype=np.int64).reshape((-1, 4))


def _block_bootstrap(
    blocks: np.ndarray, *, replicates: int, random_seed: int, minimum_blocks: int = 20
) -> dict[str, Any]:
    if len(blocks) < minimum_blocks:
        return {
            "status": "NOT_ESTIMATED_TOO_FEW_SPATIAL_BLOCKS",
            "block_count": int(len(blocks)),
            "minimum_blocks": minimum_blocks,
            "confidence_level": 0.95,
            "replicates": 0,
            "intervals": None,
        }
    rng = np.random.default_rng(random_seed)
    metric_draws: dict[str, list[float]] = {}
    block_count = len(blocks)
    for _ in range(replicates):
        chosen = rng.integers(0, block_count, size=block_count)
        aggregate = blocks[chosen].sum(axis=0)
        for name, value in _metric_values(aggregate).items():
            if np.isfinite(value):
                metric_draws.setdefault(name, []).append(float(value))
    intervals = {
        name: {
            "lower_95": float(np.percentile(values, 2.5)),
            "upper_95": float(np.percentile(values, 97.5)),
            "valid_replicates": len(values),
        }
        for name, values in metric_draws.items()
    }
    return {
        "status": "ESTIMATED_SPATIAL_BLOCK_BOOTSTRAP",
        "block_count": int(block_count),
        "minimum_blocks": minimum_blocks,
        "block_size_pixels": None,
        "confidence_level": 0.95,
        "replicates": replicates,
        "random_seed": random_seed,
        "intervals": intervals,
    }


def _prediction_parent_provenance(prediction_path: str | Path) -> dict[str, Any] | None:
    """Match a prediction raster to its RiverShift result report and source granules."""
    raster_path = Path(prediction_path).resolve()
    report_path = raster_path.parent / "river_shift_result.json"
    if not report_path.is_file():
        return None
    try:
        parent = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(parent, dict) or parent.get("analysis_type") not in {
        "flood_inundation_screening", "river_morphology_screening"
    }:
        return None
    source = parent.get("source")
    outputs = parent.get("outputs")
    quality = parent.get("quality")
    if not isinstance(source, dict) or not isinstance(outputs, dict) or not isinstance(quality, dict):
        return None
    granule_names = source.get("granule_names")
    granule_hashes = source.get("source_granule_sha256")
    if (
        source.get("mission") != "NISAR"
        or source.get("product") != "GCOV"
        or not source.get("maturity")
        or source.get("frequency") not in {"A", "B"}
        or not source.get("covariance_term")
        or not isinstance(granule_names, list)
        or not granule_names
        or not isinstance(granule_hashes, list)
        or len(granule_hashes) != len(granule_names)
        or not all(isinstance(name, str) and name for name in granule_names)
        or not all(isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest) for digest in granule_hashes)
        or quality.get("provenance_complete") is not True
    ):
        return None

    prediction_sha256 = sha256_file(raster_path)
    matched_output = None
    for key, value in outputs.items():
        if not key.endswith("_mask_sha256") or not isinstance(value, str):
            continue
        output_key = key.removesuffix("_sha256")
        relative_path = outputs.get(output_key)
        if not isinstance(relative_path, str):
            continue
        if (report_path.parent / relative_path).resolve() == raster_path and value == prediction_sha256:
            matched_output = key
            break
    if matched_output is None:
        return None

    return {
        "analysis_type": parent["analysis_type"],
        "report_path": str(report_path),
        "report_sha256": sha256_file(report_path),
        "matched_output_digest_field": matched_output,
        "mission": source["mission"],
        "product": source["product"],
        "maturity": source["maturity"],
        "frequency": source["frequency"],
        "covariance_term": source["covariance_term"],
        "granule_names": granule_names,
        "source_granule_sha256": granule_hashes,
    }
def validate_binary_classification(
    prediction_path: str,
    reference_path: str,
    *,
    reference_source: str,
    reference_date: str,
    reference_method: str,
    block_size_pixels: int = 64,
    bootstrap_replicates: int = 500,
    random_seed: int = 42,
) -> dict[str, Any]:
    """Compare a binary map to a declared reference and estimate spatial block variability.

    The reference is not assumed independent or error-free merely because its source is
    declared. A reviewer must establish suitability before results are released.
    """
    for label, value in {
        "reference_source": reference_source,
        "reference_date": reference_date,
        "reference_method": reference_method,
    }.items():
        if not value.strip():
            raise ValueError(f"{label} is required for a reproducible validation report.")
    date.fromisoformat(reference_date)
    if block_size_pixels < 1:
        raise ValueError("block_size_pixels must be at least 1.")
    if bootstrap_replicates < 100:
        raise ValueError("bootstrap_replicates must be at least 100.")
    if random_seed < 0:
        raise ValueError("random_seed cannot be negative.")

    prediction, prediction_valid, prediction_profile = read_band(prediction_path)
    reference, reference_valid, reference_profile = read_band(reference_path)
    assert_same_grid({"prediction": prediction_profile, "reference": reference_profile})
    pixel_area_m2 = require_projected_metre_grid(prediction_profile)
    parent_provenance = _prediction_parent_provenance(prediction_path)

    valid = prediction_valid & reference_valid
    if not valid.any():
        raise ValueError("No overlapping valid pixels are available for validation.")
    if not np.isin(prediction[valid], [0, 1]).all():
        raise ValueError("Prediction raster must be binary: 0=non-water, 1=water.")
    if not np.isin(reference[valid], [0, 1]).all():
        raise ValueError("Reference raster must be binary: 0=non-water, 1=water.")

    pred = prediction[valid].astype(bool)
    ref = reference[valid].astype(bool)
    tp = int(np.sum(pred & ref))
    tn = int(np.sum(~pred & ~ref))
    fp = int(np.sum(pred & ~ref))
    fn = int(np.sum(~pred & ref))
    total = tp + tn + fp + fn
    counts = np.asarray([tp, tn, fp, fn], dtype=np.int64)
    point_metrics = _metric_values(counts)
    specificity = tn / (tn + fp) if tn + fp else 0.0
    expected = (((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (total * total))
    kappa = (point_metrics["accuracy"] - expected) / (1 - expected) if expected < 1 else None

    block_counts = _block_confusion_counts(prediction, reference, valid, block_size_pixels)
    uncertainty = _block_bootstrap(block_counts, replicates=bootstrap_replicates, random_seed=random_seed)
    uncertainty["block_size_pixels"] = block_size_pixels
    uncertainty["interpretation"] = (
        "Intervals describe variation across the declared spatial blocks only; they do not include "
        "reference-label error, sensor/calibration error, geolocation error, temporal mismatch or model uncertainty."
    )

    return {
        "schema_version": 1,
        "engine": "RiverShift",
        "analysis_type": "classification_validation",
        "source": {
            "prediction": str(prediction_path),
            "reference": str(reference_path),
            "prediction_sha256": sha256_file(prediction_path),
            "reference_sha256": sha256_file(reference_path),
            "prediction_analysis": parent_provenance,
        },
        "reference": {
            "source": reference_source,
            "date": reference_date,
            "method": reference_method,
            "independent_reference_required": True,
            "independence_verified": False,
        },
        "confusion_matrix": {"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn},
        "metrics": {
            "valid_pixel_count": total,
            **{name: safe_float(value) for name, value in point_metrics.items()},
            "specificity": safe_float(specificity),
            "cohen_kappa": safe_float(kappa),
            "prediction_water_area_km2": float(pred.sum() * pixel_area_m2 / 1_000_000),
            "reference_water_area_km2": float(ref.sum() * pixel_area_m2 / 1_000_000),
        },
        "uncertainty": {"spatial_block_bootstrap": uncertainty},
        "quality": {
            "status": "VALIDATION_METRICS_COMPUTED_REVIEW_REQUIRED",
            "release_status": "PROVISIONAL",
            "provenance_complete": parent_provenance is not None,
            "warnings": [
                "Declared reference provenance does not automatically establish independence, positional accuracy or label quality.",
                "Prediction provenance is complete only when its checksum matches a mask output in an adjacent NISAR GCOV RiverShift report with source granule checksums.",
                "A cloud-free Sentinel-2-derived mask is a reference source, not automatically ground truth; document its date, cloud filtering and classification method.",
                "Report class imbalance and the confusion matrix alongside aggregate accuracy.",
                uncertainty["interpretation"],
            ],
        },
    }


def save_validation_report(result: dict[str, Any], output_path: str | Path) -> None:
    save_json(output_path, result)
