"""Pixel-level overlap diagnostics for RiverShift candidate masks and date mosaics.

These reports diagnose spatial support and compositing behaviour. They do not
validate the geomorphic meaning of any candidate class.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_binary_mask(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Candidate mask is missing: {path.name}")
    with rasterio.open(path) as src:
        values = src.read(1)
        valid = (src.dataset_mask() > 0) & np.isfinite(values)
        if valid.any() and not np.isin(values[valid], (0, 1)).all():
            raise ValueError(f"Candidate mask {path.name} contains values outside binary 0/1.")
        profile = {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
            "pixel_area_m2": abs(src.transform.a * src.transform.e - src.transform.b * src.transform.d),
        }
    return (values == 1) & valid, valid, profile


def _same_grid(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left["crs"] == right["crs"]
        and left["transform"] == right["transform"]
        and left["width"] == right["width"]
        and left["height"] == right["height"]
    )


def audit_candidate_mask_overlap(
    mask_paths: dict[str, str | Path],
    output_path: str | Path,
    *,
    comparison_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure exact full-resolution overlap between erosion, deposition and new-water masks."""
    required = ("erosion", "deposition", "new_water")
    if set(mask_paths) != set(required):
        raise ValueError("Candidate overlap audit requires erosion, deposition and new_water masks.")

    masks: dict[str, np.ndarray] = {}
    valids: dict[str, np.ndarray] = {}
    profiles: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, str]] = {}
    for name in required:
        path = Path(mask_paths[name])
        masks[name], valids[name], profiles[name] = _read_binary_mask(path)
        sources[name] = {"file": path.name, "sha256": _sha256(path)}

    base = profiles["erosion"]
    for name in required[1:]:
        if not _same_grid(base, profiles[name]):
            raise ValueError(f"Candidate masks are not on one exact grid: erosion vs {name}.")

    pairwise: dict[str, Any] = {}
    for left_name, right_name in combinations(required, 2):
        shared_valid = valids[left_name] & valids[right_name]
        left = masks[left_name] & shared_valid
        right = masks[right_name] & shared_valid
        intersection = left & right
        union = left | right
        overlap_count = int(intersection.sum())
        union_count = int(union.sum())
        shared_count = int(shared_valid.sum())
        if {left_name, right_name} == {"erosion", "deposition"} and overlap_count:
            raise ValueError(
                "Erosion and deposition masks overlap on shared valid support; "
                "their mutually exclusive transition rules have been violated."
            )
        pairwise[f"{left_name}__{right_name}"] = {
            "left_candidate_pixels_on_shared_support": int(left.sum()),
            "right_candidate_pixels_on_shared_support": int(right.sum()),
            "intersection_pixels": overlap_count,
            "union_pixels": union_count,
            "jaccard": (float(overlap_count / union_count) if union_count else None),
            "intersection_fraction_of_smaller_class": (
                float(overlap_count / min(int(left.sum()), int(right.sum())))
                if min(int(left.sum()), int(right.sum())) else None
            ),
            "shared_valid_pixel_count": shared_count,
            "shared_valid_pixel_fraction_of_grid": (
                float(shared_count / (base["width"] * base["height"]))
                if base["width"] and base["height"] else 0.0
            ),
            "interpretation": (
                "A non-zero overlap is not automatically an error: these classes can represent "
                "different date comparisons. Review the pair's temporal basis."
            ),
        }

    triple_valid = valids["erosion"] & valids["deposition"] & valids["new_water"]
    triple_overlap = masks["erosion"] & masks["deposition"] & masks["new_water"] & triple_valid
    per_class = {}
    for name in required:
        support = valids[name]
        per_class[name] = {
            "candidate_pixels": int((masks[name] & support).sum()),
            "valid_pixels": int(support.sum()),
            "valid_pixel_fraction_of_grid": (
                float(support.sum() / (base["width"] * base["height"]))
                if base["width"] and base["height"] else 0.0
            ),
            "source_mask": sources[name],
        }

    result = {
        "schema_version": 1,
        "engine": "RiverShift",
        "audit_type": "full_resolution_candidate_mask_overlap",
        "status": "COMPUTED_DIAGNOSTIC_ONLY",
        "grid": {
            "crs": str(base["crs"]),
            "width": base["width"],
            "height": base["height"],
            "transform": list(base["transform"]),
            "pixel_area_m2": float(base["pixel_area_m2"]),
        },
        "comparison_window": comparison_window or {},
        "class_temporal_basis": {
            "erosion": "baseline land -> both later comparison observations water",
            "deposition": "baseline water -> both later comparison observations land",
            "new_water": "baseline water comparison -> first comparison-date new water",
        },
        "per_class": per_class,
        "pairwise": pairwise,
        "triple_overlap_pixels_on_common_support": int(triple_overlap.sum()),
        "triple_common_valid_pixel_count": int(triple_valid.sum()),
        "warnings": [
            "This is a pixel-overlap diagnostic, not independent scientific validation.",
            "Erosion and deposition must be disjoint by construction on shared valid support.",
            "New-water candidates and persistent morphology candidates may overlap because they use different temporal comparisons.",
            "Compare these full-resolution counts with the separately reported display-preview geometry; preview overlap can be introduced by downsampling.",
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    result["report_sha256"] = _sha256(destination)
    return result


def audit_scene_mosaic_overlap(
    scene_paths: list[str | Path],
    reference_path: str | Path,
) -> dict[str, Any]:
    """Compare same-date scene backscatter where their valid footprints overlap.

    Inputs are the exported linear gamma0-power COGs. Every scene is sampled
    onto the final date-mosaic grid with nearest-neighbour resampling; this is
    diagnostic only and does not alter the first-valid-pixel mosaic.
    """
    if len(scene_paths) < 2:
        return {
            "status": "NOT_APPLICABLE_SINGLE_SCENE",
            "scene_count": len(scene_paths),
            "pairwise": [],
        }

    with rasterio.open(reference_path) as reference:
        if reference.crs is None or not reference.crs.is_projected:
            raise ValueError("Mosaic overlap audit requires a projected reference grid.")
        width, height = reference.width, reference.height
        transform = reference.transform
        crs = reference.crs

    scene_data: list[dict[str, Any]] = []
    for raw_path in scene_paths:
        path = Path(raw_path)
        with rasterio.open(path) as src:
            if src.crs is None:
                raise ValueError(f"Mosaic source {path.name} has no CRS.")
            values = np.full((height, width), np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=values,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=np.nan,
                resampling=Resampling.nearest,
            )
            source_valid = src.dataset_mask()
            aligned_valid = np.zeros((height, width), dtype=np.uint8)
            reproject(
                source=source_valid,
                destination=aligned_valid,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=0,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
        valid = (aligned_valid > 0) & np.isfinite(values) & (values > 0)
        db = np.full(values.shape, np.nan, dtype=np.float32)
        db[valid] = 10.0 * np.log10(values[valid])
        scene_data.append({
            "name": path.name,
            "sha256": _sha256(path),
            "db": db,
            "valid": valid,
        })

    pairwise = []
    for first, second in combinations(scene_data, 2):
        shared = first["valid"] & second["valid"]
        count = int(shared.sum())
        if count:
            delta = first["db"][shared].astype(np.float64) - second["db"][shared].astype(np.float64)
            absolute = np.abs(delta)
            pairwise.append({
                "scene_a": first["name"],
                "scene_b": second["name"],
                "shared_valid_pixels": count,
                "signed_delta_db_median": float(np.median(delta)),
                "absolute_delta_db_median": float(np.median(absolute)),
                "absolute_delta_db_p95": float(np.percentile(absolute, 95)),
                "absolute_delta_db_max": float(np.max(absolute)),
                "rmse_db": float(np.sqrt(np.mean(np.square(delta)))),
            })
        else:
            pairwise.append({
                "scene_a": first["name"],
                "scene_b": second["name"],
                "shared_valid_pixels": 0,
                "signed_delta_db_median": None,
                "absolute_delta_db_median": None,
                "absolute_delta_db_p95": None,
                "absolute_delta_db_max": None,
                "rmse_db": None,
            })

    return {
        "status": "COMPUTED_REVIEW_REQUIRED",
        "method": "nearest_neighbour_to_final_date_mosaic_grid_then_linear_gamma0_to_db_difference",
        "scene_count": len(scene_data),
        "reference_grid": {
            "crs": str(crs),
            "width": width,
            "height": height,
            "transform": list(transform),
        },
        "scenes": [{"name": row["name"], "sha256": row["sha256"]} for row in scene_data],
        "pairwise": pairwise,
        "interpretation": (
            "Backscatter differences in overlap areas are diagnostic. Interpret them with "
            "incidence geometry, calibration, source quality and resampling in mind; no universal "
            "dB acceptance threshold is assumed."
        ),
    }
