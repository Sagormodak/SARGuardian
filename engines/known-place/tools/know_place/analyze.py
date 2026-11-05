"""One-site GOFF analysis orchestrator for Know Place Analysis.

The output is explicitly exploratory until exact source geometry and
author-supplement parity have been independently verified.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any

import numpy as np

from .geometry import build_analysis_roi
from .goff_io import GoffReadError, inspect_goff_grid, read_geometry_cubes, read_raw_goff, sample_geometry
from .paper_method import (
    PAPER_INTERVALS,
    ScientificInputError,
    apply_paper_quality_gates,
    componentwise_background_correction,
    directional_coherence,
    empirical_percentile,
    project_offsets_to_horizontal,
    size_matched_spatial_controls,
    summarize_crown,
    validate_five_pair_inventory,
)

CONFIG_SCHEMA = "know-place-analysis-inputs/1.0"
OUTPUT_SCHEMA = "know-place-analysis-report/1.0"
TARGET_PAIR = ("2026-07-26", "2026-08-19")
PUBLISHED_TARGET = {
    "crown_median_horizontal_magnitude_m": 0.96,
    "crown_mean_vector_magnitude_m": 1.72,
    "crown_mean_vector_azimuth_deg_clockwise_from_north": 278.0,
    "crown_median_directional_coherence_R": 0.87,
    "reference_box_median_directional_coherence_R": 0.69,
    "size_matched_control_median_displacement_m": 0.14,
    "size_matched_displacement_percentile": 94.7,
}



def _runtime_environment() -> dict[str, Any]:
    """Record numerical/runtime versions needed to interpret a reproducible run."""
    package_names = (
        "numpy", "h5py", "scipy", "pyproj", "asf_search",
        "rasterio", "matplotlib", "requests",
    )
    versions: dict[str, str | None] = {}
    for name in package_names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": versions,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> tuple[dict[str, Any], Path]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise GoffReadError(f"ANALYSIS_CONFIG_NOT_FOUND:{config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoffReadError(f"ANALYSIS_CONFIG_INVALID:{exc}") from exc
    if config.get("schema_version") != CONFIG_SCHEMA:
        raise GoffReadError(f"ANALYSIS_CONFIG_SCHEMA_MISMATCH:{config.get('schema_version')}")
    for field in ("reference_box_wkt", "crown_wkt", "crown_geometry_kind",
                  "crown_geometry_source", "geometry_height_m", "products"):
        if field not in config:
            raise GoffReadError(f"ANALYSIS_CONFIG_FIELD_MISSING:{field}")
    allowed_crown_kinds = {
        "author-supplement-geometry",
        "user-digitized-geometry",
        "bounding-box-approximation",
    }
    if config["crown_geometry_kind"] not in allowed_crown_kinds:
        raise GoffReadError(
            f"CROWN_GEOMETRY_KIND_INVALID:{config['crown_geometry_kind']}"
        )
    if not str(config["crown_geometry_source"]).strip():
        raise GoffReadError("CROWN_GEOMETRY_SOURCE_NOT_DECLARED")
    try:
        height = float(config["geometry_height_m"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise GoffReadError("GEOMETRY_HEIGHT_NOT_NUMERIC") from exc
    if not math.isfinite(height):
        raise GoffReadError("GEOMETRY_HEIGHT_NONFINITE")
    products = config["products"]
    if not isinstance(products, list) or len(products) != 5:
        raise GoffReadError("EXACTLY_FIVE_PAPER_PAIR_PRODUCTS_REQUIRED")
    for i, item in enumerate(products):
        if not isinstance(item, dict):
            raise GoffReadError(f"PRODUCT_ENTRY_NOT_OBJECT:index={i}")
        for field in ("path", "catalog_maturity", "catalog_maturity_evidence"):
            if field not in item or not str(item[field]).strip():
                raise GoffReadError(f"PRODUCT_ENTRY_FIELD_MISSING:index={i}:field={field}")
        if str(item["catalog_maturity"]).upper() not in {"BETA", "PROVISIONAL"}:
            raise GoffReadError(
                f"PRODUCT_CATALOG_MATURITY_UNRESOLVED:index={i}:"
                f"{item['catalog_maturity']}"
            )
    return config, config_path.parent


def _resolve_product_path(item: dict[str, Any], config_dir: Path) -> Path:
    path = Path(str(item["path"])).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    result = path.resolve()
    if not result.is_file():
        raise GoffReadError(f"RAW_GOFF_FILE_NOT_FOUND:{result}")
    expected_name = str(item.get("expected_granule_name", "")).strip()
    if expected_name and result.name != expected_name:
        raise GoffReadError(
            f"RAW_GRANULE_NAME_MISMATCH:expected={expected_name}:actual={result.name}"
        )
    return result


def _median_or_none(values: np.ndarray) -> float | None:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else None


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _pair_key(start: str, end: str) -> str:
    return f"{start.replace('-', '')}__{end.replace('-', '')}"


def _load_and_validate_inputs(config: dict[str, Any], config_dir: Path):
    """Inspect only grid metadata first; do not hold five full GOFF rasters in memory."""
    products = []
    for item in config["products"]:
        path = _resolve_product_path(item, config_dir)
        grid = inspect_goff_grid(
            path, polarization="HH", layer=2,
            expected_track="098", expected_direction="A", expected_processing="PR",
        )
        start = grid.identity.reference_start.date().isoformat()
        end = grid.identity.secondary_start.date().isoformat()
        products.append({
            "path": path,
            "grid": grid,
            "reference_date": start,
            "secondary_date": end,
            "product_type": "GOFF",
            "track": grid.identity.track,
            "direction": grid.identity.direction,
            "polarization": grid.polarization,
            "layer": grid.layer,
            "catalog_maturity": str(item["catalog_maturity"]).upper(),
            "catalog_maturity_evidence": str(item["catalog_maturity_evidence"]),
            "expected_granule_name": str(item.get("expected_granule_name") or ""),
        })
    indexed = validate_five_pair_inventory(products)
    ordered = []
    for start, end in PAPER_INTERVALS:
        item = indexed[f"{start}__{end}"]
        grid = item["grid"]
        if grid.epsg != 32645:
            raise GoffReadError(
                f"TARGET_GRID_EPSG_MISMATCH:{grid.identity.granule_name}:{grid.epsg}"
            )
        if not np.allclose(np.abs(np.diff(grid.x_coordinates_m)), 80.0, atol=1e-4, rtol=0):
            raise GoffReadError(f"TARGET_GRID_X_POSTING_NOT_80M:{grid.identity.granule_name}")
        if not np.allclose(np.abs(np.diff(grid.y_coordinates_m)), 80.0, atol=1e-4, rtol=0):
            raise GoffReadError(f"TARGET_GRID_Y_POSTING_NOT_80M:{grid.identity.granule_name}")
        ordered.append(item)
    first = ordered[0]["grid"]
    reference_x, reference_y = first.x_coordinates_m.copy(), first.y_coordinates_m.copy()
    reference_epsg = first.epsg
    for item in ordered[1:]:
        grid = item["grid"]
        if grid.epsg != reference_epsg:
            raise GoffReadError(f"TARGET_GRID_CRS_MISMATCH:{grid.identity.granule_name}")
        if not np.array_equal(grid.x_coordinates_m, reference_x):
            raise GoffReadError(f"TARGET_GRID_X_COORDINATES_NOT_IDENTICAL:{grid.identity.granule_name}")
        if not np.array_equal(grid.y_coordinates_m, reference_y):
            raise GoffReadError(f"TARGET_GRID_Y_COORDINATES_NOT_IDENTICAL:{grid.identity.granule_name}")
    return ordered


def _report_controls(
    magnitude: np.ndarray,
    coherence: np.ndarray,
    valid: np.ndarray,
    box_mask: np.ndarray,
    crown_mask: np.ndarray,
    *,
    crown_median: float,
    crown_R: float | None,
    pixel_size_x_m: float,
    pixel_size_y_m: float,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    try:
        controls = size_matched_spatial_controls(
            magnitude, coherence, valid, box_mask, crown_mask,
            pixel_size_x_m=pixel_size_x_m, pixel_size_y_m=pixel_size_y_m,
            draws=draws, seed=seed,
        )
        magnitude_distribution = np.asarray(controls.pop("mag_distribution_for_percentile"), dtype=float)
        r_distribution = np.asarray(controls.pop("R_distribution_for_percentile"), dtype=float)
        magnitude_draws = list(controls.get("displacement_control_values_m", []))
        coherence_draws = list(controls.get("directional_coherence_control_values_R", []))
        valid_counts = list(controls.get("valid_pixel_counts", []))
        # Hash the actual ordered control sample, not the summary statistic.
        controls["spatial_control_sample_sha256"] = _sha256_text(json.dumps(
            _json_safe({
                "seed": controls.get("seed"),
                "prng": controls.get("prng"),
                "displacement_m": magnitude_draws,
                "coherence_R": coherence_draws,
                "valid_pixel_counts": valid_counts,
            }),
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ))
        magnitude_percentile = empirical_percentile(magnitude_distribution, crown_median)
        coherence_percentile = None
        if crown_R is not None and r_distribution.size:
            coherence_percentile = empirical_percentile(r_distribution, crown_R)
        controls["displacement_empirical_percentile"] = magnitude_percentile
        controls["directional_coherence_empirical_percentile"] = coherence_percentile
        controls["method_label"] = (
            "exploratory deterministic circular controls matching valid-cell count; "
            "not asserted equivalent to author-supplement spatial sampling"
        )
        controls.pop("displacement_control_values_m", None)
        controls.pop("directional_coherence_control_values_R", None)
        controls.pop("valid_pixel_counts", None)
        return controls
    except (ScientificInputError, ValueError) as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}:{exc}",
            "method_label": "exploratory deterministic circular controls; not paper-validated",
        }


def _coherence_sensitivity(
    east: np.ndarray,
    north: np.ndarray,
    valid: np.ndarray,
    valid_box: np.ndarray,
    box_mask: np.ndarray,
    crown_mask: np.ndarray,
    magnitude: np.ndarray,
    *,
    include_published_magnitude_window: bool,
) -> dict[str, Any]:
    """Report how 5x5 R depends on its undocumented minimum valid-neighbour rule.

    The preprint defines a 5x5 mean resultant length but does not state a minimum
    neighbour count. The primary policy therefore permits any count from 1 to 25;
    values are only summarized at centres that themselves pass the quality gate.
    Sensitivity rows expose the effect of stronger neighbour-count requirements.
    """
    thresholds = (1, 5, 10, 15, 20, 25)
    result: dict[str, Any] = {
        "method_note": (
            "The preprint specifies a 5x5 mean resultant length but does not "
            "publish a minimum valid-neighbour count. Primary result uses >=1 "
            "valid direction, and each summary is restricted to valid centre pixels. "
            "Sensitivity is reported for >=1,5,10,15,20,25 neighbours."
        ),
        "primary_minimum_valid_neighbours": 1,
        "thresholds": {},
    }
    centre_box = valid_box & box_mask & np.isfinite(east) & np.isfinite(north)
    centre_crown = centre_box & crown_mask
    centre_background = centre_box & ~crown_mask
    mag_window = centre_box & np.isfinite(magnitude) & (magnitude >= 0.17) & (magnitude <= 2.75)

    for minimum in thresholds:
        R = directional_coherence(
            east, north, valid, window_size=5, minimum_valid_cells=minimum,
        )
        def median_on(mask: np.ndarray) -> tuple[float | None, int]:
            selected = mask & np.isfinite(R)
            if not selected.any():
                return None, 0
            return float(np.median(R[selected])), int(selected.sum())

        crown_value, crown_n = median_on(centre_crown)
        box_value, box_n = median_on(centre_box)
        background_value, background_n = median_on(centre_background)
        record: dict[str, Any] = {
            "minimum_valid_neighbours": minimum,
            "crown_median_R": crown_value,
            "crown_valid_centres": crown_n,
            "reference_box_median_R_including_crown": box_value,
            "reference_box_valid_centres": box_n,
            "outside_crown_median_R": background_value,
            "outside_crown_valid_centres": background_n,
        }
        if include_published_magnitude_window:
            window_value, window_n = median_on(centre_crown & mag_window)
            box_window_value, box_window_n = median_on(mag_window)
            record["target_pair_0_17_to_2_75_m_sensitivity"] = {
                "crown_median_R": window_value,
                "crown_valid_centres": window_n,
                "box_median_R_at_centres_with_same_pointwise_magnitude_window": box_window_value,
                "box_valid_centres_at_same_pointwise_magnitude_window": box_window_n,
                "note": (
                    "This pointwise magnitude-window comparison is a sensitivity "
                    "diagnostic only; it is not the paper's matched-control sample."
                ),
            }
        result["thresholds"][str(minimum)] = record
    return result


def analyze_config(config_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Process the five paper date intervals separately and emit auditable outputs."""
    config, config_dir = load_config(config_path)
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    products = _load_and_validate_inputs(config, config_dir)
    first = products[0]["grid"]
    roi = build_analysis_roi(
        first.x_coordinates_m, first.y_coordinates_m, first.epsg,
        box_wkt=config["reference_box_wkt"], crown_wkt=config["crown_wkt"],
    )
    yy, xx = np.meshgrid(roi.y_coordinates_m, roi.x_coordinates_m, indexing="ij")
    y0, y1 = roi.row_slice.start, roi.row_slice.stop
    x0, x1 = roi.col_slice.start, roi.col_slice.stop
    row_reports: list[dict[str, Any]] = []
    full_records: list[dict[str, Any]] = []

    seed = int(config.get("control_seed", 260826))
    draws = int(config.get("control_draws", 1000))
    minimum_R = int(config.get("coherence_minimum_valid_cells", 1))
    if not (1 <= minimum_R <= 25):
        raise GoffReadError("COHERENCE_MINIMUM_VALID_CELLS_MUST_BE_1_TO_25")
    if draws < 1:
        raise GoffReadError("CONTROL_DRAWS_MUST_BE_POSITIVE")

    for item in products:
        raw = read_raw_goff(
            item["path"], polarization="HH", layer=2,
            expected_track="098", expected_direction="A", expected_processing="PR",
            window_slices=(roi.row_slice, roi.col_slice), expected_grid=item["grid"],
        )
        start, end = item["reference_date"], item["secondary_date"]
        pair_report: dict[str, Any] = {
            "pair": f"{start} -> {end}",
            "reference_date": start,
            "secondary_date": end,
            "interval_days": _days_between(start, end),
            "granule_name": raw.identity.granule_name,
            "processing": raw.identity.processing,
            "frame": raw.identity.frame,
            "track": raw.identity.track,
            "direction": raw.identity.direction,
            "polarization": raw.polarization,
            "layer": raw.layer,
            "release_id": raw.identity.release_id,
            "catalog_maturity": item["catalog_maturity"],
            "catalog_maturity_evidence": item["catalog_maturity_evidence"],
            "source_sha256": raw.source_sha256,
            "epsg": raw.epsg,
            "geometry_height_m": float(config["geometry_height_m"]),
            "status": "STARTED",
        }
        cubes = read_geometry_cubes(item["path"], expected_epsg=raw.epsg)
        sample = sample_geometry(
            cubes,
            x_m=xx, y_m=yy,
            height_m=float(config["geometry_height_m"]),
            expected_epsg=raw.epsg,
        )
        if not np.array_equal(raw.x_coordinates_m, roi.x_coordinates_m) or not np.array_equal(
            raw.y_coordinates_m, roi.y_coordinates_m
        ):
            raise GoffReadError(f"WINDOW_GRID_MISMATCH_AFTER_RAW_READ:{raw.identity.granule_name}")
        at = raw.along_track_m
        sr = raw.slant_range_m
        snr = raw.snr
        corr = raw.correlation
        east, north = project_offsets_to_horizontal(
            at, sr,
            sample.along_track_x, sample.along_track_y,
            sample.los_x, sample.los_y,
            sample.incidence_deg,
        )
        # The read window includes a two-cell halo. Its valid pixels may
        # supply neighbouring vectors for R windows centred inside the box;
        # only roi.box_mask cells enter the box/crown scalar summaries.
        input_valid = np.isfinite(corr)
        valid, gates, uncorrected_magnitude = apply_paper_quality_gates(
            east, north, snr, input_valid=input_valid,
            minimum_snr=5.0, maximum_horizontal_magnitude_m=10.0,
        )
        pair_report["quality_gate_counts"] = gates.__dict__
        pair_report["quality_policy"] = {
            "minimum_snr": 5.0,
            "maximum_projected_horizontal_magnitude_m": 10.0,
            "gross_magnitude_policy": "reject pixel, do not clip",
            "correlation_policy": "finite correlation required for source-valid flag; no correlation threshold applied",
            "coherence_context_halo_cells": 2,
            "off_box_halo_pixels_may_support_neighbourhood_R": True,
            "off_box_halo_pixels_excluded_from_box_crown_summaries": True,
        }
        pair_report["geometry_metadata_group"] = sample.metadata_group
        pair_report["geometry_unit_evidence"] = cubes.unit_evidence
        pair_report["valid_correlation_pixels_in_box"] = int((input_valid & roi.box_mask).sum())
        pair_report["valid_correlation_pixels_in_coherence_halo"] = int((input_valid & ~roi.box_mask).sum())
        pair_report["valid_pixels_in_box_after_paper_gates"] = int((valid & roi.box_mask).sum())
        pair_report["valid_pixels_outside_box_for_coherence_context"] = int((valid & ~roi.box_mask).sum())
        pair_report["valid_pixels_in_crown_after_paper_gates"] = int((valid & roi.crown_mask).sum())

        if not np.any(valid & roi.crown_mask):
            pair_report["status"] = "INSUFFICIENT_CROWN_VALID_PIXELS"
            pair_report["reason"] = "No crown pixels pass finite-data, SNR and projected-magnitude gates"
            pair_reportsafe = _json_safe(pair_report)
            row_reports.append(pair_reportsafe)
            full_records.append(pair_reportsafe)
            continue

        try:
            corrected_east, corrected_north, bias = componentwise_background_correction(
                east, north, valid, roi.box_mask, roi.crown_mask,
            )
        except ScientificInputError as exc:
            pair_report["status"] = "INSUFFICIENT_BACKGROUND_SUPPORT"
            pair_report["reason"] = f"{type(exc).__name__}:{exc}"
            pair_reportsafe = _json_safe(pair_report)
            row_reports.append(pair_reportsafe)
            full_records.append(pair_reportsafe)
            continue
        valid_box = valid & roi.box_mask & np.isfinite(corrected_east) & np.isfinite(corrected_north)
        magnitude = np.full(valid.shape, np.nan, dtype=float)
        magnitude[valid_box] = np.hypot(corrected_east[valid_box], corrected_north[valid_box])
        coherence = directional_coherence(
            corrected_east, corrected_north, valid,
            window_size=5, minimum_valid_cells=minimum_R,
        )
        summary = summarize_crown(
            corrected_east, corrected_north, valid_box, roi.crown_mask,
            coherence, interval_days=pair_report["interval_days"],
        )
        full_box_R = _median_or_none(coherence[valid_box & roi.box_mask])
        outside_crown = valid_box & roi.box_mask & ~roi.crown_mask
        outside_crown_R = _median_or_none(coherence[outside_crown])
        pair_report["background_correction"] = bias
        pair_report["crown_statistics"] = summary
        pair_report["reference_box_median_directional_coherence_R"] = full_box_R
        pair_report["outside_crown_median_directional_coherence_R"] = outside_crown_R
        pair_report["coherence_policy"] = {
            "window": "5x5",
            "minimum_valid_direction_vectors_per_window": minimum_R,
            "edge_policy": "zero-padded; only windows meeting minimum count are reported",
            "primary_policy_rationale": (
                "The preprint does not specify a minimum valid-neighbour count; "
                "the default is 1, with an explicit 1/5/10/15/20/25 sensitivity table."
            ),
        }
        pair_report["directional_coherence_sensitivity"] = _coherence_sensitivity(
            corrected_east, corrected_north, valid, valid_box, roi.box_mask,
            roi.crown_mask, magnitude,
            include_published_magnitude_window=(start, end) == TARGET_PAIR,
        )
        pair_report["status"] = "METRICS_COMPUTED"

        crown_median = float(summary["crown_median_horizontal_magnitude_m"])
        crown_R = summary.get("crown_median_directional_coherence_R")
        pair_report["exploratory_control_comparison"] = _report_controls(
            magnitude, coherence, valid_box, roi.box_mask, roi.crown_mask,
            crown_median=crown_median,
            crown_R=float(crown_R) if crown_R is not None and math.isfinite(float(crown_R)) else None,
            pixel_size_x_m=float(np.median(np.abs(np.diff(roi.x_coordinates_m)))),
            pixel_size_y_m=float(np.median(np.abs(np.diff(roi.y_coordinates_m)))),
            draws=draws, seed=seed,
        )
        pair_report["interpretation"] = (
            "Measurement summary only. No alarm or landslide detection conclusion is emitted."
        )
        npz_path = out / f"{_pair_key(start, end)}_diagnostic_arrays.npz"
        np.savez_compressed(
            npz_path,
            east_m=corrected_east.astype(np.float32),
            north_m=corrected_north.astype(np.float32),
            horizontal_magnitude_m=magnitude.astype(np.float32),
            directional_coherence_R=coherence.astype(np.float32),
            valid_mask=valid_box.astype(np.uint8),
            reference_box_mask=roi.box_mask.astype(np.uint8),
            crown_mask=roi.crown_mask.astype(np.uint8),
            x_coordinates_m=roi.x_coordinates_m.astype(np.float64),
            y_coordinates_m=roi.y_coordinates_m.astype(np.float64),
        )
        pair_report["diagnostic_arrays_file"] = npz_path.name
        pair_report["diagnostic_arrays_sha256"] = hashlib.sha256(npz_path.read_bytes()).hexdigest()
        full_records.append(_json_safe(pair_report))
        row_reports.append(_json_safe(pair_report))

    focus = next((r for r in full_records if
                  r.get("reference_date") == TARGET_PAIR[0]
                  and r.get("secondary_date") == TARGET_PAIR[1]), None)
    crown_kind = config["crown_geometry_kind"]
    exact_geometry = crown_kind == "author-supplement-geometry"
    complete_metrics = sum(r.get("status") == "METRICS_COMPUTED" for r in full_records)
    if complete_metrics == 5:
        analysis_status = "SCIENTIFIC_METRICS_COMPUTED"
    else:
        analysis_status = "PARTIAL_INSUFFICIENT_DATA"
    paper_status = "BLOCKED_AUTHOR_GOLDEN_DATA_PARITY_NOT_VERIFIED"
    if not exact_geometry:
        paper_status = "BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED"
    result = {
        "schema_version": OUTPUT_SCHEMA,
        "project": "Know Place Analysis",
        "runtime_environment": _runtime_environment(),
        "status": analysis_status,
        "structural_status": "PASS",
        "paper_reproduction_status": paper_status,
        "hazard_detection_status": "NOT_EVALUATED",
        "run_scope": {
            "site": "Bhote Koshi source/crown, Nepal",
            "requested_pair_count": 5,
            "pair_count_with_metrics": complete_metrics,
            "geometry_height_m": float(config["geometry_height_m"]),
            "reference_box_wkt": config["reference_box_wkt"],
            "crown_wkt": config["crown_wkt"],
            "crown_geometry_kind": crown_kind,
            "crown_geometry_source": config["crown_geometry_source"],
            "crown_wkt_sha256": _sha256_text(str(config["crown_wkt"]).strip()),
            "control_seed": seed,
            "control_draws": draws,
            "coherence_minimum_valid_cells": minimum_R,
        },
        "method_contract": {
            "input": "raw GOFF layer2 arrays; no existing reader exports consumed",
            "required_pairs": list(PAPER_INTERVALS),
            "geometry": "product metadata cubes interpolated in map x/y and explicit HAE",
            "vertical_motion_assumption": "zero; result is horizontal displacement estimate only",
            "quality": "SNR >= 5; projected horizontal magnitude <= 10 m; gross blunders rejected, never clipped",
            "background": "component-wise median from valid reference-box pixels outside crown",
            "directional_coherence": "mean resultant length of unit vectors in 5x5 neighbourhood",
            "control_sampling": "separate exploratory circular controls; not asserted equivalent to author method",
            "comparison_policy": "no output is forced to match published summary values",
        },
        "published_reference_targets": PUBLISHED_TARGET,
        "26jul_19aug_comparison": {
            "published_targets": PUBLISHED_TARGET,
            "computed_statistics": (
                focus.get("crown_statistics") if focus and focus.get("status") == "METRICS_COMPUTED" else None
            ),
            "status": (
                "NOT_COMPARABLE_EXACT_CROWN_GEOMETRY_UNVERIFIED"
                if not exact_geometry
                else "NOT_VERIFIED_AUTHOR_SUPPLEMENT_GOLDEN_OUTPUT_MISSING"
            ),
        },
        "products": full_records,
        "limitations": [
            "Structural PASS means the five raw products passed identity, schema, grid and output checks; it is not scientific reproduction.",
            "The input crown must be the exact author-supplied polygon for pixel-level comparison; a bounding-box approximation is not equivalent.",
            "Exact product release variants and author-supplement reference outputs must be verified before parity can pass.",
            "The circular spatial controls are an exploratory implementation until matched to the author's control-generation method.",
            "No landslide alarm is generated; the cited preprint itself reports no pre-event statistic above its 95th-percentile spatial comparison threshold.",
        ],
    }
    result = _json_safe(result)
    summary_path = out / "know-place-analysis-report.json"
    summary_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    csv_path = out / "know-place-analysis-pairs.csv"
    flattened: list[dict[str, Any]] = []
    for item in full_records:
        stats = item.get("crown_statistics") or {}
        gates = item.get("quality_gate_counts") or {}
        flattened.append({
            "reference_date": item.get("reference_date"),
            "secondary_date": item.get("secondary_date"),
            "granule_name": item.get("granule_name"),
            "status": item.get("status"),
            "crown_valid_pixels": item.get("valid_pixels_in_crown_after_paper_gates"),
            "crown_median_horizontal_magnitude_m": stats.get("crown_median_horizontal_magnitude_m"),
            "crown_mean_vector_magnitude_m": stats.get("crown_mean_vector_magnitude_m"),
            "crown_mean_vector_azimuth_deg_clockwise_from_north": stats.get("crown_mean_vector_azimuth_deg_clockwise_from_north"),
            "crown_median_directional_coherence_R": stats.get("crown_median_directional_coherence_R"),
            "reference_box_median_directional_coherence_R": item.get("reference_box_median_directional_coherence_R"),
            "outside_crown_median_directional_coherence_R": item.get("outside_crown_median_directional_coherence_R"),
            "finite_offsets_and_snr": gates.get("finite_offsets_and_snr"),
            "snr_pass": gates.get("snr_pass"),
            "final_valid": gates.get("final_valid"),
            "source_sha256": item.get("source_sha256"),
        })
    csv_fields = list(flattened[0].keys()) if flattened else ["reference_date"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(flattened)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strict exploratory analysis of five raw GOFF pairs; does not issue hazard alarms."
    )
    parser.add_argument("--config", required=True, help="JSON input manifest with five exact raw HDF5 paths")
    parser.add_argument("--out", required=True, help="Output directory for JSON, CSV and diagnostic NPZ files")
    args = parser.parse_args(argv)
    try:
        report = analyze_config(args.config, args.out)
    except Exception as exc:
        # Preserve a compact, path-free machine-readable failure report so
        # failed science runs remain auditable and can be retained by the
        # isolated workflow. The process still returns non-zero.
        output = Path(args.out).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        message = str(exc)
        error_code = message.split(":", 1)[0].strip() or type(exc).__name__
        failed = {
            "schema_version": OUTPUT_SCHEMA,
            "project": "Know Place Analysis",
            "runtime_environment": _runtime_environment(),
            "status": "FAILED",
            "structural_status": "FAIL",
            "paper_reproduction_status": "BLOCKED_ANALYSIS_FAILED",
            "hazard_detection_status": "NOT_EVALUATED",
            "failure": {
                "type": type(exc).__name__,
                "code": error_code[:160],
                "detail_policy": "Full tool output is in analysis.log; this report omits filesystem paths and credentials.",
            },
            "limitations": [
                "No scientific measurements or hazard alarm are claimed from a failed run.",
                "A non-zero process exit remains a failure even when this report is emitted.",
            ],
        }
        failure_path = output / "know-place-analysis-report.json"
        failure_path.write_text(
            json.dumps(failed, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print("KNOW_PLACE_ANALYSIS_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:{error_code[:160]}")
        print(f"REPORT={failure_path}")
        return 2
    print(f"KNOW_PLACE_ANALYSIS_STATUS={report['status']}")
    print(f"STRUCTURAL_STATUS={report['structural_status']}")
    print(f"PAPER_REPRODUCTION_STATUS={report['paper_reproduction_status']}")
    print(f"HAZARD_DETECTION_STATUS={report['hazard_detection_status']}")
    print(f"REPORT={Path(args.out).resolve() / 'know-place-analysis-report.json'}")
    return 0 if report["structural_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
