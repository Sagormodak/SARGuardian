"""Target-free, AOI-wide spatial anomaly screening on retained NISAR rasters.

This stage finds candidate regions without a user-specified point. It is deliberately
a conservative screening layer: a spatial outlier is not, by itself, validated ground
movement. Candidate pixels are scored separately for GUNW LOS displacement, GOFF
range offset, and GOFF along-track offset, with product quality masks applied first.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform_geom
from scipy.ndimage import binary_dilation, label, median_filter


_IDENTITY = re.compile(
    r"^NISAR_L2_(?P<processing>PR|UR)_(?P<product>GUNW|GOFF)_"
    r"(?P<cycle>\d{3})_(?P<path>\d{3})_(?P<direction>[AD])_"
    r"(?P<frame>\d{3})_(?P<subswath>\d{3})_(?P<bandwidth>\d{4})_"
    r"(?P<polarisation>[A-Z]{2})_.*?_(?P<crid>[PX]\d{5})_(?:N|F)_",
    re.IGNORECASE,
)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _safe_export_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def _source_stem(value: Any) -> str:
    name = Path(str(value or "")).name
    return name[:-3] if name.lower().endswith(".h5") else name


def _identity(granule_name: str, product_type: str) -> dict[str, str] | None:
    match = _IDENTITY.search(Path(granule_name).name)
    if not match or match.group("product").upper() != product_type.upper():
        return None
    return {key: str(value).upper() if key in {"processing", "product", "direction", "polarisation", "crid"} else str(value)
            for key, value in match.groupdict().items()}


def _robust_sigma(values: np.ndarray) -> float | None:
    sample = values[np.isfinite(values)]
    if sample.size < 200:
        return None
    median = float(np.median(sample))
    mad = float(np.median(np.abs(sample - median)))
    if not math.isfinite(mad) or mad <= np.finfo(np.float32).eps:
        return None
    return 1.4826 * mad


def _empty_report(status: str, reason: str, aoi_wkt_sha256: str | None) -> dict[str, Any]:
    return {
        "schema_version": "sarguardian-aoi-spatial-candidates/1.0",
        "status": status,
        "aoi_wkt_sha256": aoi_wkt_sha256,
        "analysis_scope": "target-free spatial anomaly screening of retained AOI-clipped raster exports",
        "target_required": False,
        "candidate_features": 0,
        "products_examined": 0,
        "product_metrics_examined": 0,
        "groups": [],
        "features": [],
        "movement_confirmed": False,
        "hazard_detected": False,
        "warnings": [
            "Spatial anomalies are candidate regions, not confirmed ground movement.",
            "The screen measures relative spatial contrast within each pair; it cannot detect uniform AOI-wide motion from its own background.",
            "The robust AOI/background scale is not an independently validated stable-ground reference.",
            "GUNW LOS, GOFF range offset and GOFF along-track offset are separate metrics and must never be combined as if they shared one measurement axis.",
            "Robust-score thresholds are exploratory screening parameters, not calibrated false-alarm probabilities.",
            "GOFF marginal range/along-track variances are used separately when exported; crossOffsetVariance is preserved but is not assumed to be covariance.",
            "Variance-normalized component scores are exploratory marginal scores, not a joint-vector probability or a calibrated false-alarm rate.",
            "Candidate-raster NoData means insufficient observation support; it is not zero motion.",
            "Pairwise candidate recurrence is screening evidence only; cumulative time series and velocity require a compatible, redundant, independently reference-checked temporal network.",
        ],
        "reason": reason,
    }


def _grid_key(dataset: rasterio.io.DatasetReader) -> tuple[Any, ...]:
    return (
        dataset.crs.to_string(),
        int(dataset.width),
        int(dataset.height),
        tuple(round(float(value), 9) for value in dataset.transform),
    )


def _write_analysis_raster(
    path: Path,
    source_item: dict[str, Any],
    values: np.ndarray,
    valid: np.ndarray,
    *,
    aoi_hash: str | None,
    metric: str,
    units: str,
    network: str,
) -> dict[str, Any]:
    """Write a derived AOI-grid raster without converting NoData to zero."""
    source_path = Path(source_item["raster_path"])
    with rasterio.open(source_path) as src:
        profile = src.profile.copy()
        source_tags = src.tags()
    profile.update(
        count=1,
        dtype="float32",
        nodata=-9999.0,
        compress="deflate",
        predictor=3,
    )
    out = np.full(values.shape, -9999.0, dtype="float32")
    mask = valid & np.isfinite(values)
    out[mask] = values[mask].astype("float32", copy=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(out, 1)
        dst.set_band_description(1, metric)
        dst.update_tags(
            schema_version="sarguardian-aoi-spatial-candidates-raster/1.0",
            aoi_wkt_sha256=str(aoi_hash or ""),
            target_required="false",
            metric=metric,
            units=units,
            network=network,
            source_product=str(source_tags.get("source") or ""),
            reference_policy="pair-local robust spatial background; not stable-ground reference",
            movement_confirmed="false",
            hazard_detected="false",
            nodata_policy="-9999 means unobserved/invalid; zero means observed with no candidate",
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "role": metric,
        "relative_path": (Path(path.parent.name) / path.name).as_posix(),
        "bytes": path.stat().st_size,
        "valid_pixels": int(np.count_nonzero(mask)),
        "units": units,
        "sha256": digest.hexdigest(),
        "crs": profile.get("crs").to_string() if profile.get("crs") else None,
        "width": int(profile["width"]),
        "height": int(profile["height"]),
    }


def _read_metric_rasters(
    products: list[dict[str, Any]],
    output_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for product in products:
        family = str(product.get("product_type") or "").upper()
        if family not in {"GUNW", "GOFF"}:
            continue
        name = str(product.get("granule_name") or "")
        identity = _identity(name, family)
        if identity is None:
            rejected.append({"product_id": product.get("id"), "product_type": family,
                             "status": "REJECTED_UNPARSEABLE_IDENTITY",
                             "reason": "The exact product identity could not be parsed; cross-pair grouping would be unsafe."})
            continue
        exports = product.get("exports") if isinstance(product.get("exports"), list) else []
        if len(exports) != 1 or not isinstance(exports[0], dict):
            rejected.append({"product_id": product.get("id"), "product_type": family,
                             "status": "REJECTED_EXPORT_COUNT",
                             "reason": "Exactly one validated multi-band raster export is required per product."})
            continue
        try:
            raster_path = _safe_export_path(output_root, str(exports[0].get("relative_path") or ""))
            if not raster_path.is_file():
                raise ValueError("EXPORT_MISSING")
            with rasterio.open(raster_path) as ds:
                tags = ds.tags()
                if ds.crs is None or not ds.crs.is_projected or ds.crs.to_epsg() is None:
                    raise ValueError("PROJECTED_CRS_REQUIRED")
                if tags.get("aoi_name") != "custom" or str(tags.get("aoi_mask_applied", "")).lower() != "true":
                    raise ValueError("CUSTOM_AOI_MASK_NOT_PROVEN")
                if tags.get("grid_policy") != "common_aoi_lattice":
                    raise ValueError("COMMON_AOI_LATTICE_NOT_PROVEN")
                if tags.get("export_status") != "WRITTEN":
                    raise ValueError("EXPORT_STATUS_NOT_WRITTEN")
                if _source_stem(tags.get("source")) != _source_stem(name):
                    raise ValueError("EXPORT_SOURCE_IDENTITY_MISMATCH")
                if family == "GUNW":
                    if ds.count < 2:
                        raise ValueError("GUNW_REQUIRES_DISPLACEMENT_AND_COHERENCE_BANDS")
                    displacement = ds.read(1, masked=True).filled(np.nan).astype("float32")
                    coherence = ds.read(2, masked=True).filled(np.nan).astype("float32")
                    valid = np.isfinite(displacement) & np.isfinite(coherence) & (coherence >= 0.3)
                    metrics = [("GUNW_LOS_DISPLACEMENT_MM", displacement, valid, None, None)]
                    quality_description = "finite LOS displacement, finite coherence >= 0.3"
                else:
                    if ds.count < 3 or "layer2" not in str(tags.get("layer", "")).lower():
                        raise ValueError("GOFF_REQUIRES_LAYER2_RANGE_AZIMUTH_AND_CORRELATION")
                    range_offset = ds.read(1, masked=True).filled(np.nan).astype("float32")
                    azimuth_offset = ds.read(2, masked=True).filled(np.nan).astype("float32")
                    correlation = ds.read(3, masked=True).filled(np.nan).astype("float32")

                    def optional_variance(tag_name: str, description_fragment: str) -> np.ndarray | None:
                        raw_index = str(tags.get(tag_name) or "").strip()
                        if not raw_index or raw_index.lower() == "not_exported":
                            return None
                        try:
                            band_index = int(raw_index)
                        except (TypeError, ValueError, OverflowError):
                            raise ValueError(f"INVALID_GOFF_VARIANCE_BAND_INDEX:{tag_name}")
                        if band_index < 1 or band_index > ds.count:
                            raise ValueError(f"GOFF_VARIANCE_BAND_INDEX_OUT_OF_RANGE:{tag_name}")
                        description = str(ds.descriptions[band_index - 1] or "").lower()
                        if description_fragment not in description:
                            raise ValueError(f"GOFF_VARIANCE_BAND_DESCRIPTION_MISMATCH:{tag_name}")
                        return ds.read(band_index, masked=True).filled(np.nan).astype("float32")

                    range_variance = optional_variance("range_variance_band", "slant-range offset variance")
                    azimuth_variance = optional_variance("along_track_variance_band", "along-track offset variance")
                    # The product also carries a crossOffsetVariance field. Preserve its identity
                    # and provenance, but do not treat it as covariance until the exact product
                    # specification and convention are verified.
                    cross_offset_variance = optional_variance("cross_offset_variance_band", "cross offset variance")
                    corr_limit = max(0.3, _finite(tags.get("correlation_min")) or 0.3)
                    valid = np.isfinite(range_offset) & np.isfinite(azimuth_offset) & np.isfinite(correlation) & (correlation >= corr_limit)
                    metrics = [
                        ("GOFF_SLANT_RANGE_OFFSET_MM", range_offset, valid, range_variance, cross_offset_variance),
                        ("GOFF_ALONG_TRACK_OFFSET_MM", azimuth_offset, valid, azimuth_variance, cross_offset_variance),
                    ]
                    quality_description = (
                        f"finite range/azimuth/correlation; correlation >= {corr_limit:g}; "
                        "marginal per-component variance used when available; crossOffsetVariance preserved but not interpreted as covariance"
                    )
                grid = _grid_key(ds)
                transform = ds.transform
                crs = ds.crs
                resolution = (abs(float(ds.res[0])), abs(float(ds.res[1])))
        except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
            reason = str(exc)[:180] or type(exc).__name__
            rejected.append({"product_id": product.get("id"), "product_type": family,
                             "status": "REJECTED_RASTER_CONTRACT", "reason": reason})
            continue

        ref_date = str(product.get("reference_date") or tags.get("reference") or "")[:10]
        sec_date = str(product.get("secondary_date") or tags.get("secondary") or "")[:10]
        if not ref_date or not sec_date or sec_date <= ref_date:
            rejected.append({"product_id": product.get("id"), "product_type": family,
                             "status": "REJECTED_ACQUISITION_DATES",
                             "reason": "Valid, ordered reference and secondary dates are required."})
            continue
        # Sub-swath is reported as provenance but is not a separate recurrence
        # group when the exact projected AOI lattice/grid and every other geometry
        # discriminator match. Pixel masks are unioned per acquisition interval,
        # so overlapping swaths never count as independent temporal votes.
        network = (
            family, identity["processing"], identity["path"], identity["frame"], identity["direction"],
            identity["bandwidth"], identity["polarisation"], identity["crid"], grid,
        )
        for metric_name, values, valid_metric, variance_values, cross_offset_variance_values in metrics:
            variance_valid = (
                valid_metric & np.isfinite(variance_values) & (variance_values > 0)
                if variance_values is not None else np.zeros(valid_metric.shape, dtype=bool)
            )
            accepted.append({
                "product": product, "product_id": str(product.get("id") or ""),
                "granule_name": name, "product_type": family,
                "metric": metric_name, "values": values, "valid": valid_metric,
                "variance_values": variance_values,
                "variance_valid": variance_valid,
                "cross_offset_variance_values": cross_offset_variance_values,
                "identity": identity, "network_key": network, "grid": grid,
                "transform": transform, "crs": crs, "resolution": resolution,
                "reference_date": ref_date, "secondary_date": sec_date,
                "raster_path": raster_path, "valid_pixels": int(np.count_nonzero(valid_metric)),
                "quality_description": quality_description,
                "variance_valid_pixels": int(np.count_nonzero(variance_valid)),
                "variance_coverage": (
                    float(np.count_nonzero(variance_valid) / max(1, np.count_nonzero(valid_metric)))
                    if variance_values is not None else 0.0
                ),
            })
    return accepted, rejected


def _score_pair(item: dict[str, Any], *, threshold_z: float, background_window_pixels: int, minimum_valid_pixels: int) -> dict[str, Any]:
    values = item["values"]
    valid = item["valid"]
    valid_count = int(np.count_nonzero(valid))
    if valid_count < minimum_valid_pixels:
        return item | {"score_status": "INSUFFICIENT_VALID_PIXELS", "candidate_mask": np.zeros(valid.shape, dtype=bool),
                       "score": np.zeros(valid.shape, dtype="float32"), "robust_background_sigma": None,
                       "robust_local_sigma": None, "local_residual": None, "valid_pixels": valid_count}

    center = float(np.median(values[valid]))
    centered = values - center
    global_sigma = _robust_sigma(centered[valid])
    if global_sigma is None:
        return item | {"score_status": "INSUFFICIENT_ROBUST_BACKGROUND_SCALE", "candidate_mask": np.zeros(valid.shape, dtype=bool),
                       "score": np.zeros(valid.shape, dtype="float32"), "robust_background_sigma": None,
                       "robust_local_sigma": None, "local_residual": None, "valid_pixels": valid_count}

    window = int(max(5, background_window_pixels))
    if window % 2 == 0:
        window += 1
    max_window = max(3, min(values.shape))
    if max_window % 2 == 0:
        max_window -= 1
    window = min(window, max_window)
    if window < 3:
        return item | {"score_status": "INSUFFICIENT_SPATIAL_SUPPORT", "candidate_mask": np.zeros(valid.shape, dtype=bool),
                       "score": np.zeros(valid.shape, dtype="float32"), "robust_background_sigma": global_sigma,
                       "robust_local_sigma": None, "local_residual": None, "valid_pixels": valid_count}
    # Fill invalid pixels with the robust centre before filtering; invalid pixels
    # remain excluded in the final candidate mask.
    filled = np.where(valid, values, center).astype("float32", copy=False)
    local_background = median_filter(filled, size=window, mode="nearest")
    local_residual = values - local_background
    local_sigma = _robust_sigma(local_residual[valid])
    if local_sigma is None:
        return item | {"score_status": "INSUFFICIENT_ROBUST_LOCAL_SCALE", "candidate_mask": np.zeros(valid.shape, dtype=bool),
                       "score": np.zeros(valid.shape, dtype="float32"), "robust_background_sigma": global_sigma,
                       "robust_local_sigma": None, "local_residual": None, "valid_pixels": valid_count}

    # GOFF marginal offset variances are in mm^2. Use their square root as
    # a conservative per-pixel noise floor, never as a stand-alone score that
    # could turn tiny reported variance into an artificially large z-score.
    # The larger of product variance and spatially empirical robust scatter wins.
    variance_values = item.get("variance_values")
    variance_valid = np.asarray(item.get("variance_valid", np.zeros(valid.shape, dtype=bool)), dtype=bool)
    variance_score = np.full(valid.shape, np.nan, dtype="float32")
    effective_global_sigma = np.full(valid.shape, global_sigma, dtype="float32")
    effective_local_sigma = np.full(valid.shape, local_sigma, dtype="float32")
    if variance_values is not None:
        variance_values = np.asarray(variance_values, dtype="float32")
        use_variance = valid & variance_valid & np.isfinite(variance_values) & (variance_values > 0)
        if np.any(use_variance):
            marginal_sigma = np.sqrt(variance_values[use_variance])
            effective_global_sigma[use_variance] = np.maximum(global_sigma, marginal_sigma)
            effective_local_sigma[use_variance] = np.maximum(local_sigma, marginal_sigma)
            variance_score[use_variance] = (
                np.abs(local_residual[use_variance]) / effective_local_sigma[use_variance]
            ).astype("float32")

    z_global = np.abs(centered) / effective_global_sigma
    z_local = np.abs(local_residual) / effective_local_sigma
    score = np.maximum(z_global, z_local).astype("float32")
    score[~valid] = 0.0
    candidate_mask = valid & np.isfinite(score) & (score >= threshold_z)
    return item | {
        "score_status": "SCORED",
        "candidate_mask": candidate_mask,
        "score": score,
        "robust_background_sigma": global_sigma,
        "robust_local_sigma": local_sigma,
        "local_residual": local_residual.astype("float32", copy=False),
        "variance_score_used": bool(np.isfinite(variance_score).any()),
        "variance_valid_pixels": int(np.count_nonzero(np.isfinite(variance_score))),
        "variance_coverage": float(np.count_nonzero(np.isfinite(variance_score)) / max(1, valid_count)),
        "maximum_marginal_variance_z": (
            float(np.nanmax(variance_score)) if np.isfinite(variance_score).any() else None
        ),
        "variance_model": (
            "per-component marginal variance normalization; crossOffsetVariance is retained but not used as covariance"
            if np.isfinite(variance_score).any() else "robust-MAD fallback; no usable marginal variance band"
        ),
        "valid_pixels": valid_count,
        "background_median_mm": center,
        "candidate_pixels": int(np.count_nonzero(candidate_mask)),
        "threshold_robust_z": threshold_z,
        "background_window_pixels": window,
    }


def _candidate_local_floor_rows(region_mask, scored_rows):
    """Measure one conservative local floor per distinct acquisition interval."""
    rows = []
    row_ids = np.flatnonzero(np.any(region_mask, axis=1))
    col_ids = np.flatnonzero(np.any(region_mask, axis=0))
    if row_ids.size == 0 or col_ids.size == 0:
        return rows
    pad = 5
    row0 = max(0, int(row_ids[0]) - pad)
    row1 = min(region_mask.shape[0], int(row_ids[-1]) + pad + 1)
    col0 = max(0, int(col_ids[0]) - pad)
    col1 = min(region_mask.shape[1], int(col_ids[-1]) + pad + 1)
    region_crop = region_mask[row0:row1, col0:col1]

    by_interval = defaultdict(list)
    for item in scored_rows:
        key = (str(item.get("reference_date") or ""), str(item.get("secondary_date") or ""))
        by_interval[key].append(item)

    for (ref, sec), interval_items in sorted(by_interval.items()):
        try:
            span = (date.fromisoformat(sec[:10]) - date.fromisoformat(ref[:10])).days
        except ValueError:
            span = 0
        variant_rows = []
        candidate_union = np.zeros(region_crop.shape, dtype=bool)
        for item in interval_items:
            candidate = np.asarray(item.get("candidate_mask"), dtype=bool)[row0:row1, col0:col1]
            cm = region_crop & candidate
            if not np.any(cm):
                continue
            candidate_union |= cm
            residual = item.get("local_residual")
            valid = np.asarray(item.get("valid"), dtype=bool)[row0:row1, col0:col1]
            ring = binary_dilation(cm, iterations=pad) & ~region_crop & valid & ~candidate
            residual_crop = (
                np.asarray(residual)[row0:row1, col0:col1].astype("float64", copy=False)
                if residual is not None else np.array([])
            )
            bg = residual_crop[ring] if residual is not None else np.array([])
            bg = bg[np.isfinite(bg)]
            if span <= 0 or bg.size < 30:
                sigma, floor, status = None, None, "WITHHELD_INSUFFICIENT_LOCAL_BACKGROUND"
            else:
                sigma = 1.4826 * float(np.median(np.abs(bg - np.median(bg))))
                floor = 3.0 * sigma / span if math.isfinite(sigma) and sigma > 0 else None
                status = "MEASURED_CANDIDATE_REGION_LOCAL_FLOOR" if floor is not None else "WITHHELD_DEGENERATE_LOCAL_BACKGROUND_MAD"
            # Phase-ceiling review uses candidate LOS contrast against this
            # pair's AOI median, not the locally detrended residual used by
            # the local noise-floor estimator.
            pair_values = np.asarray(item.get("values"))[row0:row1, col0:col1].astype("float64", copy=False)
            pair_centre = _finite(item.get("background_median_mm"))
            candidate_values = pair_values[cm] - float(pair_centre) if pair_centre is not None else np.array([])
            candidate_values = candidate_values[np.isfinite(candidate_values)]
            variant_rows.append({
                "product_id": str(item.get("product_id") or ""),
                "candidate_pixels": int(cm.sum()),
                "background_pixels": int(bg.size),
                "minimum_background_pixels": 30,
                "background_ring_pixels": pad,
                "residual_background_window_pixels": int(item.get("background_window_pixels") or 11),
                "noise_scale_method": "1.4826 * median absolute deviation",
                "local_background_sigma_mm": sigma,
                "candidate_median_aoi_relative_residual_mm": (
                    float(np.median(candidate_values)) if candidate_values.size else None
                ),
                "local_detection_floor_3sigma_mm_day": floor,
                "status": status,
            })
        if not variant_rows:
            continue
        measured = [
            item for item in variant_rows
            if item["status"] == "MEASURED_CANDIDATE_REGION_LOCAL_FLOOR"
        ]
        if measured:
            # Subswaths/duplicate variants of one interval are not independent
            # temporal samples. Keep one interval row and its largest measured
            # local floor so the detectability gate is conservative.
            selected = max(
                measured,
                key=lambda item: (float(item["local_detection_floor_3sigma_mm_day"]), item["product_id"]),
            )
            status = "MEASURED_CANDIDATE_REGION_LOCAL_FLOOR"
            floor = selected["local_detection_floor_3sigma_mm_day"]
            sigma = selected["local_background_sigma_mm"]
        else:
            selected = max(variant_rows, key=lambda item: (item["background_pixels"], item["product_id"]))
            status = selected["status"]
            floor = None
            sigma = selected["local_background_sigma_mm"]
        phase_variants = [
            item for item in variant_rows
            if item.get("candidate_median_aoi_relative_residual_mm") is not None
        ]
        phase_selected = max(
            phase_variants,
            key=lambda item: (abs(float(item["candidate_median_aoi_relative_residual_mm"])), item["product_id"]),
        ) if phase_variants else selected
        rows.append({
            "product_id": selected["product_id"],
            "phase_review_source_product_id": phase_selected["product_id"],
            "reference_date": ref,
            "secondary_date": sec,
            "candidate_pixels": int(candidate_union.sum()),
            "background_pixels": int(selected["background_pixels"]),
            "minimum_background_pixels": int(selected["minimum_background_pixels"]),
            "background_ring_pixels": int(selected["background_ring_pixels"]),
            "residual_background_window_pixels": int(selected["residual_background_window_pixels"]),
            "noise_scale_method": selected["noise_scale_method"],
            "floor_formula": "3 * (1.4826 * MAD) / acquisition_span_days",
            "contributing_variants": len(variant_rows),
            "floor_selection_policy": "maximum measured floor among same-interval variants; one interval counts once",
            "local_background_sigma_mm": sigma,
            "candidate_median_aoi_relative_residual_mm": phase_selected.get("candidate_median_aoi_relative_residual_mm"),
            "local_detection_floor_3sigma_mm_day": floor,
            "span_days": span or None,
            "status": status,
            "interpretation": "Pair-specific local residual floor; same-interval subswaths/variants are not independent temporal samples. Nearby background is not independently validated stable ground.",
        })
    return rows

def build_aoi_spatial_candidate_report(
    products: list[dict[str, Any]],
    output_root: Path,
    aoi_wkt_sha256: str | None,
    *,
    minimum_valid_pixels: int = 200,
    minimum_component_pixels: int = 4,
    minimum_repeat_pairs: int = 2,
    threshold_robust_z: float = 4.5,
    background_window_pixels: int = 11,
) -> dict[str, Any]:
    """Generate target-free spatial candidate polygons from retained raster exports."""
    output_root = output_root.resolve()
    report = _empty_report(
        "NOT_STARTED",
        "Candidate screen evaluates spatially unusual raster regions, not confirmed movement.",
        aoi_wkt_sha256,
    )
    try:
        accepted, rejected = _read_metric_rasters(products, output_root)
    except Exception as exc:
        report.update({
            "status": "UNAVAILABLE",
            "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            "rejected_products": [],
        })
        _write_outputs(output_root, report, [])
        return report

    report["rejected_products"] = rejected
    report["products_examined"] = len({item["product_id"] for item in accepted})
    if not accepted:
        report.update({
            "status": "NO_ELIGIBLE_RASTER_EXPORTS",
            "reason": "No retained raster satisfied the product identity, projection, AOI-mask, common-lattice and quality-band contracts.",
        })
        _write_outputs(output_root, report, [])
        return report

    accepted = [
        _score_pair(item, threshold_z=threshold_robust_z, background_window_pixels=background_window_pixels,
                    minimum_valid_pixels=minimum_valid_pixels)
        for item in accepted
    ]
    report["product_metrics_examined"] = len(accepted)
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in accepted:
        groups[(item["network_key"], item["metric"])].append(item)

    all_features: list[dict[str, Any]] = []
    group_reports: list[dict[str, Any]] = []
    for group_key, rows in sorted(groups.items(), key=lambda pair: str(pair[0])):
        scored = [item for item in rows if item["score_status"] == "SCORED"]
        sample = rows[0]
        subswaths = sorted({item["identity"]["subswath"] for item in rows})
        subswath_label = ",".join(subswaths)
        group_label = (
            f"{sample['product_type']} {sample['identity']['direction']} path {sample['identity']['path']} "
            f"frame {sample['identity']['frame']} subswaths {subswath_label} "
            f"bandwidth {sample['identity']['bandwidth']} pol {sample['identity']['polarisation']} "
            f"CRID {sample['identity']['crid']} · {sample['metric']}"
        )
        unique_pairs = sorted({(item["reference_date"], item["secondary_date"]) for item in scored})
        if not scored:
            group_reports.append({
                "network": group_label, "status": "WITHHELD_INSUFFICIENT_ROBUST_SUPPORT",
                "pairs": len(rows), "reason": "No pair met the valid-pixel and robust-scale requirements.",
            })
            continue

        # Merge swath exports into one spatial mask per acquisition interval.
        # A date pair may vote at most once for each pixel, even when overlapping
        # swaths or duplicate variants were retained.
        pair_masks: dict[tuple[str, str], dict[str, Any]] = {}
        for item in sorted(scored, key=lambda value: (
            value["reference_date"], value["secondary_date"], -int(value["valid_pixels"]), value["product_id"]
        )):
            pair_key = (item["reference_date"], item["secondary_date"])
            if pair_key not in pair_masks:
                pair_masks[pair_key] = {
                    "mask": np.zeros(sample["valid"].shape, dtype=bool),
                    "valid": np.zeros(sample["valid"].shape, dtype=bool),
                    "score": np.zeros(sample["valid"].shape, dtype="float32"),
                    "product_ids": set(),
                    "items": [],
                }
            pair = pair_masks[pair_key]
            mask = item["candidate_mask"]
            pair["mask"] |= mask
            pair["valid"] |= item["valid"]
            pair["score"] = np.maximum(pair["score"], item["score"] * mask.astype("float32"))
            pair["product_ids"].add(item["product_id"])
            pair["items"].append(item)

        support = np.zeros(sample["valid"].shape, dtype="uint16")
        observation_support = np.zeros(sample["valid"].shape, dtype="uint16")
        maximum_score = np.zeros(sample["valid"].shape, dtype="float32")
        for pair in pair_masks.values():
            support += pair["mask"].astype("uint16")
            observation_support += pair["valid"].astype("uint16")
            maximum_score = np.maximum(maximum_score, pair["score"])

        # Publish the raster evidence as well as polygons. A zero candidate count
        # is meaningful only where observation_support is positive; outside that
        # support remains NoData, never silently rendered as zero motion.
        slug = hashlib.sha256(group_label.encode("utf-8")).hexdigest()[:12]
        raster_dir = output_root / "aoi-spatial-candidates"
        raster_valid = observation_support > 0
        raster_artifacts = [
            _write_analysis_raster(
                raster_dir / f"candidate-mask-{slug}.tif", sample,
                (support > 0).astype("float32"), raster_valid,
                aoi_hash=aoi_wkt_sha256, metric="AOI spatial candidate mask",
                units="binary candidate flag", network=group_label,
            ),
            _write_analysis_raster(
                raster_dir / f"candidate-pair-count-{slug}.tif", sample,
                support.astype("float32"), raster_valid,
                aoi_hash=aoi_wkt_sha256, metric="Candidate pair support count",
                units="pair count", network=group_label,
            ),
            _write_analysis_raster(
                raster_dir / f"valid-observation-count-{slug}.tif", sample,
                observation_support.astype("float32"), raster_valid,
                aoi_hash=aoi_wkt_sha256, metric="Valid observation pair count",
                units="pair count", network=group_label,
            ),
            _write_analysis_raster(
                raster_dir / f"candidate-robust-score-{slug}.tif", sample,
                maximum_score, raster_valid,
                aoi_hash=aoi_wkt_sha256, metric="Maximum exploratory robust anomaly score",
                units="robust z-like score (not probability)", network=group_label,
            ),
        ]
        labels, component_count = label(support > 0, structure=np.ones((3, 3), dtype=np.uint8))
        group_features: list[dict[str, Any]] = []

        def emit_feature(region_mask: np.ndarray, repeated: bool) -> None:
            pixel_count = int(np.count_nonzero(region_mask))
            if pixel_count < minimum_component_pixels:
                return
            relevant_pairs = []
            for pair_key, pair_data in sorted(pair_masks.items()):
                if np.any(region_mask & pair_data["mask"]):
                    # A repeated candidate must be spatially co-supported at the same pixels.
                    if repeated and not np.any(region_mask & (support >= minimum_repeat_pairs) & pair_data["mask"]):
                        continue
                    relevant_pairs.append((pair_key, pair_data))
            if not relevant_pairs:
                return
            max_support = int(np.max(support[region_mask]))
            if repeated and max_support < minimum_repeat_pairs:
                return
            geom_shapes = list(shapes(
                np.ones(region_mask.shape, dtype="uint8"),
                mask=region_mask,
                transform=sample["transform"],
                connectivity=8,
            ))
            if not geom_shapes:
                return
            geometry = transform_geom(sample["crs"], "EPSG:4326", geom_shapes[0][0], precision=7)
            pixel_width, pixel_height = sample["resolution"]
            max_score = float(np.max(maximum_score[region_mask]))
            pair_keys = [pair_key for pair_key, _ in relevant_pairs]
            local_floor_scored_rows = [
                item for _, pair_data in relevant_pairs for item in pair_data["items"]
            ]
            local_floor_rows = _candidate_local_floor_rows(region_mask, local_floor_scored_rows)
            local_floor_measured = sum(
                row.get("status") == "MEASURED_CANDIDATE_REGION_LOCAL_FLOOR"
                for row in local_floor_rows
            )
            product_ids = sorted({
                product_id
                for _, pair_data in relevant_pairs
                for product_id in pair_data["product_ids"]
            })
            product_family = sample["product_type"]
            metric_name = sample["metric"]
            evidence_class = (
                "GOFF_OFFSET_ANOMALY_NOT_GROUND_MOTION"
                if product_family == "GOFF"
                else "GUNW_LOS_DISPLACEMENT_ANOMALY_UNCONFIRMED"
            )
            season_months = []
            for floor_row in local_floor_rows:
                try:
                    first_day = date.fromisoformat(str(floor_row["reference_date"])[:10])
                    last_day = date.fromisoformat(str(floor_row["secondary_date"])[:10])
                    midpoint = first_day + timedelta(days=max(0, (last_day - first_day).days // 2))
                    season_months.append(midpoint.month)
                except (KeyError, TypeError, ValueError):
                    continue
            monsoon_pairs = sum(6 <= month <= 9 for month in season_months)
            dry_pairs = len(season_months) - monsoon_pairs
            seasonality_inventory = {
                "status": (
                    "MULTI_SEASON_SUPPORT_PRESENT" if monsoon_pairs and dry_pairs
                    else "INSUFFICIENT_SEASONAL_COVERAGE"
                ),
                "monsoon_pairs": monsoon_pairs,
                "dry_season_pairs": dry_pairs,
                "months_used": sorted(set(season_months)),
                "interpretation": "Descriptive acquisition-season coverage only; not a causal monsoon test and not evidence for or against motion.",
            }
            phase_ceiling_mm = 0.25 * (299792458.0 / 1257500000.0) * 1000.0
            phase_values_available = [
                row for row in local_floor_rows
                if row.get("candidate_median_aoi_relative_residual_mm") is not None
            ] if sample["product_type"] == "GUNW" else []
            phase_review_pairs = [
                row for row in phase_values_available
                if abs(float(row["candidate_median_aoi_relative_residual_mm"])) > phase_ceiling_mm
            ]
            phase_ceiling_review = {
                "status": (
                    "EXCEEDS_SINGLE_FRINGE_REVIEW_THRESHOLD"
                    if phase_review_pairs else (
                        "WITHIN_SINGLE_FRINGE_REVIEW_THRESHOLD"
                        if phase_values_available
                        else "NOT_APPLICABLE_NON_GUNW_OFFSET_METRIC"
                        if sample["product_type"] != "GUNW"
                        else "NOT_TESTABLE_NO_CANDIDATE_PAIR_RESIDUAL"
                    )
                ),
                "threshold_mm": round(phase_ceiling_mm, 3),
                "pairs_tested": len(phase_values_available),
                "pairs_exceeding_threshold": [
                    {
                        "reference_date": row["reference_date"],
                        "secondary_date": row["secondary_date"],
                        "candidate_median_aoi_relative_residual_mm": row["candidate_median_aoi_relative_residual_mm"],
                    } for row in phase_review_pairs
                ],
                "interpretation": "A review trigger for pairwise GUNW LOS differential only; phase unwrapping may recover cycles, so exceedance is not automatic rejection or proof of error.",
            }
            properties = {
                "network": group_label,
                "product_type": product_family,
                "metric": metric_name,
                "evidence_class": evidence_class,
                # support_pairs is the maximum same-pixel temporal support;
                # intervals that merely touch different parts of a connected
                # candidate polygon are reported separately and do not count as
                # repeated support.
                "support_pairs": max_support,
                "overlapping_pair_count": len(pair_keys),
                "required_repeat_pairs": minimum_repeat_pairs,
                "max_pixel_pair_support": max_support,
                "pixel_count": pixel_count,
                "approx_area_m2": round(pixel_count * pixel_width * pixel_height, 2),
                "max_robust_score": round(max_score, 3),
                "product_ids": product_ids,
                "pair_intervals": [f"{a}/{b}" for a, b in pair_keys],
                "candidate_local_floor_status": "MEASURED_FOR_ONE_OR_MORE_PAIRS" if local_floor_measured else "WITHHELD_INSUFFICIENT_LOCAL_BACKGROUND",
                "candidate_local_floor_measured_pairs": local_floor_measured,
                "candidate_local_floor_by_pair": local_floor_rows,
                "candidate_seasonality_inventory": seasonality_inventory,
                "candidate_phase_ceiling_review": phase_ceiling_review,
                "candidate_cross_geometry_status": "WITHHELD_NO_PIXELWISE_LOOK_VECTOR_AND_RATE_COVARIANCE",
                "status": "REPEATED_SPATIAL_CANDIDATE" if repeated else "SINGLE_PAIR_CANDIDATE_UNCONFIRMED",
                "interpretation": (
                    (
                        "GOFF range/along-track offset anomaly recurs in the same pixels across compatible pairs. "
                        "This remains an image-offset anomaly, not ground displacement; validate correlation, geometry, "
                        "systematic error and independent geophysical evidence."
                    )
                    if product_family == "GOFF" and repeated else
                    (
                        "GOFF range/along-track offset anomaly from one pair only. This is not ground displacement; "
                        "validate correlation, geometry and systematic error before any movement interpretation."
                    )
                    if product_family == "GOFF" else
                    (
                        "A GUNW LOS displacement-field anomaly recurs in the same pixels across compatible pairs. "
                        "It is still relative to product/AOI reference and requires reference-stability, uncertainty "
                        "and independent geophysical validation; it is not a hazard declaration."
                    )
                    if repeated else
                    (
                        "A single-pair GUNW LOS displacement-field anomaly. It requires temporal/reference validation "
                        "before it can support a movement interpretation; it is not a hazard declaration."
                    )
                ),
            }
            feature = {"type": "Feature", "geometry": geometry, "properties": properties}
            group_features.append(feature)
            all_features.append(feature)

        for component_id in range(1, component_count + 1):
            component_mask = labels == component_id
            if int(np.count_nonzero(component_mask)) < minimum_component_pixels:
                continue
            recurring_mask = component_mask & (support >= minimum_repeat_pairs)
            recurring_labels, recurring_count = label(recurring_mask, structure=np.ones((3, 3), dtype=np.uint8))
            emitted_recurring = np.zeros(component_mask.shape, dtype=bool)
            for recurring_id in range(1, recurring_count + 1):
                region_mask = recurring_labels == recurring_id
                if int(np.count_nonzero(region_mask)) >= minimum_component_pixels:
                    emit_feature(region_mask, repeated=True)
                    emitted_recurring |= region_mask
            # Single-pair candidates must contain only pixels whose own temporal support
            # is below the recurrence threshold. Do not let a small recurring patch
            # fall back into a larger single-pair polygon merely because the recurring
            # patch was below the minimum polygon-size gate.
            unconfirmed_mask = component_mask & (support < minimum_repeat_pairs)
            unconfirmed_labels, unconfirmed_count = label(unconfirmed_mask, structure=np.ones((3, 3), dtype=np.uint8))
            for unconfirmed_id in range(1, unconfirmed_count + 1):
                region_mask = unconfirmed_labels == unconfirmed_id
                if int(np.count_nonzero(region_mask)) >= minimum_component_pixels:
                    emit_feature(region_mask, repeated=False)

        group_reports.append({
            "network": group_label,
            "status": "CANDIDATES_FOUND_NEED_VALIDATION" if group_features else "NO_CANDIDATES_AT_SCREEN_THRESHOLD",
            "product_pairs": len(unique_pairs),
            "products_scored": len(scored),
            "candidate_features": len(group_features),
            "candidate_pixels": int(np.count_nonzero(support)),
            "repeated_pair_candidate_features": sum(f["properties"]["status"] == "REPEATED_SPATIAL_CANDIDATE" for f in group_features),
            "single_pair_unconfirmed_features": sum(f["properties"]["status"] == "SINGLE_PAIR_CANDIDATE_UNCONFIRMED" for f in group_features),
            "threshold_robust_z": threshold_robust_z,
            "minimum_valid_pixels": minimum_valid_pixels,
            "minimum_component_pixels": minimum_component_pixels,
            "robust_scale_source": "per-pair AOI-valid pixels; median/MAD; not an independently stable-ground measurement",
            "reference_policy": "pair-local spatial median/MAD; common translation across the AOI is not observable",
            "valid_observation_pixels": int(np.count_nonzero(raster_valid)),
            "raster_artifacts": raster_artifacts,
            "pair_results": [{
                "product_id": item["product_id"],
                "granule_name": item["granule_name"],
                "reference_date": item["reference_date"],
                "secondary_date": item["secondary_date"],
                "metric": item["metric"],
                "status": item["score_status"],
                "valid_pixels": item["valid_pixels"],
                "candidate_pixels": item.get("candidate_pixels", 0),
                "background_median_mm": _finite(item.get("background_median_mm")),
                "robust_background_sigma_mm": _finite(item.get("robust_background_sigma")),
                 "robust_local_sigma_mm": _finite(item.get("robust_local_sigma")),
                 "variance_score_used": bool(item.get("variance_score_used")),
                 "variance_valid_pixels": int(item.get("variance_valid_pixels") or 0),
                 "variance_coverage": _finite(item.get("variance_coverage")),
                 "maximum_marginal_variance_z": _finite(item.get("maximum_marginal_variance_z")),
                 "variance_model": str(item.get("variance_model") or "not_available"),
                 "cross_offset_variance_interpreted_as_covariance": False,
                "quality_mask": item["quality_description"],
            } for item in rows],
        })

    repeated_count = sum(
        feature["properties"]["status"] == "REPEATED_SPATIAL_CANDIDATE" for feature in all_features
    )
    report.update({
        "raster_artifacts": [artifact for group in group_reports for artifact in group.get("raster_artifacts", [])],
        "status": (
            "REPEATED_SPATIAL_CANDIDATES_NEED_GEOPHYSICAL_VALIDATION" if repeated_count
            else "SINGLE_PAIR_CANDIDATES_NEED_TEMPORAL_CONFIRMATION" if all_features
            else "NO_CANDIDATES_AT_CONFIGURED_THRESHOLD"
        ),
        "reason": (
            "At least one region is spatially unusual in more than one compatible pair; validate reference stability, uncertainty and temporal consistency before calling movement."
            if repeated_count else
            "Candidate regions were found in individual pairs, but no region met the configured repeated-pair support."
            if all_features else
            "No spatial components met the configured robust-score and minimum-area screen. This is not evidence of zero movement."
        ),
        "candidate_features": len(all_features),
        "candidate_local_floor_measurements": sum(
            int(feature.get("properties", {}).get("candidate_local_floor_measured_pairs") or 0)
            for feature in all_features
        ),
        "candidate_features_with_local_floor": sum(
            int(feature.get("properties", {}).get("candidate_local_floor_measured_pairs") or 0) > 0
            for feature in all_features
        ),
        "candidate_local_floor_policy": {
            "method": "Empirical pair-local residual scatter around each target-free candidate polygon",
            "residual": "metric raster minus spatial median filter",
            "residual_background_window_pixels": background_window_pixels,
            "background_ring_pixels": 5,
            "minimum_background_pixels": 30,
            "robust_sigma": "1.4826 * MAD",
            "detection_floor": "3 * robust_sigma / acquisition_span_days",
            "duplicate_interval_policy": "One interval counts once; maximum measured floor across same-interval subswath/variant exports is retained",
            "stable_ground_validation": "NOT_PERFORMED",
            "false_alarm_probability": "NOT_CALIBRATED",
        },
        "products_examined": len({item["product_id"] for item in accepted}),
        "product_metrics_examined": len(accepted),
        "groups": group_reports,
        "features": all_features,
        "repeated_pair_candidate_features": repeated_count,
        "minimum_repeat_pairs": minimum_repeat_pairs,
        "threshold_robust_z": threshold_robust_z,
        "movement_confirmed": False,
        "hazard_detected": False,
    })
    _write_outputs(output_root, report, all_features)
    return report


def _write_outputs(output_root: Path, report: dict[str, Any], features: list[dict[str, Any]]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "aoi-displacement-candidates.json"
    geojson_path = output_root / "aoi-displacement-candidates.geojson"
    csv_path = output_root / "aoi-displacement-candidates.csv"
    # Remove in-memory raster arrays before JSON serialization.
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    geojson_path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "schema_version": "sarguardian-aoi-spatial-candidates/1.0",
            "aoi_wkt_sha256": report.get("aoi_wkt_sha256"),
            "movement_confirmed": False,
            "hazard_detected": False,
        },
    }, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    rows = [feature["properties"] for feature in features]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        fields = ["network", "product_type", "metric", "status", "support_pairs", "pixel_count",
                  "approx_area_m2", "max_robust_score", "product_ids", "pair_intervals"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **row,
                "product_ids": ";".join(row.get("product_ids", [])),
                "pair_intervals": ";".join(row.get("pair_intervals", [])),
            })
