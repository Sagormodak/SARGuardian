#!/usr/bin/env python3
"""Compare a NISAR water mask with a nearby cloud-screened Sentinel-2 L2A scene.

This optional cross-sensor agreement screen is not ground truth or field
validation. It uses Copernicus Sentinel-2 L2A SCL and MNDWI classifications
on the B11 20 m grid and compares them with a user-supplied NISAR binary mask.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds, transform as window_transform
from shapely.geometry import box, shape
from shapely.ops import transform as transform_geometry


STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
COLLECTION = "sentinel-2-l2a"
SCL_VALID_CLASSES = (4, 5, 6)
MAX_TARGET_PIXELS = 12_000_000
USER_AGENT = "SARGuardian-RiverShift-Sentinel2-Crosscheck/1.0"


class CrosscheckError(RuntimeError):
    """Raised when a safe cross-sensor comparison cannot be performed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _item_date(item: dict[str, Any]) -> date:
    properties = item.get("properties") or {}
    value = properties.get("datetime")
    if not isinstance(value, str):
        raise ValueError("STAC item has no valid properties.datetime.")
    return _utc_datetime(value).date()


def _asset_href(item: dict[str, Any], key: str) -> str:
    assets = item.get("assets") or {}
    asset = assets.get(key)
    href = asset.get("href") if isinstance(asset, dict) else None
    if not isinstance(href, str) or not href.startswith("https://"):
        raise ValueError(f"Sentinel-2 item is missing a valid HTTPS {key} asset href.")
    return href


def _item_coverage_fraction(
    item: dict[str, Any],
    aoi_geometry_wgs84: Any,
    analysis_crs: CRS,
) -> float:
    geometry = item.get("geometry")
    if not isinstance(geometry, dict):
        return 0.0
    try:
        item_geometry = shape(geometry)
        project = Transformer.from_crs("EPSG:4326", analysis_crs, always_xy=True).transform
        aoi_projected = transform_geometry(project, aoi_geometry_wgs84)
        item_projected = transform_geometry(project, item_geometry)
        if aoi_projected.is_empty or item_projected.is_empty or aoi_projected.area <= 0:
            return 0.0
        return float(aoi_projected.intersection(item_projected).area / aoi_projected.area)
    except Exception:
        return 0.0


def select_best_item(
    items: list[dict[str, Any]],
    *,
    observation_date: date,
    aoi_geometry_wgs84: Any,
    analysis_crs: CRS,
    max_day_offset: int = 3,
    max_cloud_cover: float = 40.0,
) -> dict[str, Any] | None:
    """Select one scene by coverage first, then date proximity and cloud cover."""
    ranked: list[tuple[tuple[float, int, float, str], dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            properties = item.get("properties") or {}
            cloud = float(properties.get("eo:cloud_cover"))
            acquisition = _item_date(item)
            offset = abs((acquisition - observation_date).days)
            if not math.isfinite(cloud) or cloud > max_cloud_cover or offset > max_day_offset:
                continue
            for key in ("B03", "B11", "SCL"):
                _asset_href(item, key)
            coverage = _item_coverage_fraction(item, aoi_geometry_wgs84, analysis_crs)
            if coverage <= 0:
                continue
            item_id = str(item.get("id") or "")
            ranked.append(((-coverage, offset, cloud, item_id), item))
        except (TypeError, ValueError):
            continue
    if not ranked:
        return None
    ranked.sort(key=lambda value: value[0])
    return ranked[0][1]


def _confusion_metrics(
    predicted_water: np.ndarray,
    reference_water: np.ndarray,
    valid: np.ndarray,
    pixel_area_m2: float,
) -> dict[str, Any]:
    predicted = np.asarray(predicted_water, dtype=bool)
    reference = np.asarray(reference_water, dtype=bool)
    support = np.asarray(valid, dtype=bool)
    if predicted.shape != reference.shape or predicted.shape != support.shape:
        raise CrosscheckError("Prediction, reference and validity arrays must share one grid.")
    if not math.isfinite(pixel_area_m2) or pixel_area_m2 <= 0:
        raise CrosscheckError("Pixel area must be a finite positive value.")
    count = int(np.count_nonzero(support))
    if count == 0:
        raise CrosscheckError("No common valid pixels remain for cross-sensor comparison.")

    tp = int(np.count_nonzero(support & predicted & reference))
    fp = int(np.count_nonzero(support & predicted & ~reference))
    fn = int(np.count_nonzero(support & ~predicted & reference))
    tn = int(np.count_nonzero(support & ~predicted & ~reference))

    def ratio(numerator: int, denominator: int) -> float | None:
        return float(numerator / denominator) if denominator else None

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = (
        float(2 * precision * recall / (precision + recall))
        if precision is not None and recall is not None and precision + recall > 0
        else (0.0 if precision == 0 or recall == 0 else None)
    )
    iou = ratio(tp, tp + fp + fn)
    agreement = ratio(tp + tn, count)
    specificity = ratio(tn, tn + fp)
    balanced_accuracy = (
        float((recall + specificity) / 2)
        if recall is not None and specificity is not None else None
    )
    expected_agreement = (
        ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / float(count * count)
    )
    cohen_kappa = (
        float((agreement - expected_agreement) / (1.0 - expected_agreement))
        if agreement is not None and expected_agreement < 1.0 else None
    )
    predicted_water_pixels = tp + fp
    reference_water_pixels = tp + fn

    return {
        "valid_pixel_count": count,
        "confusion_matrix": {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn},
        "agreement": agreement,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "balanced_accuracy": balanced_accuracy,
        "f1_score": f1,
        "intersection_over_union": iou,
        "cohen_kappa": cohen_kappa,
        "predicted_water_area_km2": float(predicted_water_pixels * pixel_area_m2 / 1_000_000),
        "reference_water_area_km2": float(reference_water_pixels * pixel_area_m2 / 1_000_000),
        "area_bias_km2": float((predicted_water_pixels - reference_water_pixels) * pixel_area_m2 / 1_000_000),
    }


def _scl_water_reference(scl_values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(scl_values, dtype=np.uint8)
    valid = np.isin(values, SCL_VALID_CLASSES)
    return values == 6, valid


def _mndwi(green: np.ndarray, swir1: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    green_values = np.asarray(green, dtype=np.float64)
    swir_values = np.asarray(swir1, dtype=np.float64)
    if green_values.shape != swir_values.shape:
        raise CrosscheckError("Sentinel-2 B03 and B11 grids must match after reprojection.")
    denominator = green_values + swir_values
    valid = (
        np.isfinite(green_values)
        & np.isfinite(swir_values)
        & (green_values > 0)
        & (swir_values > 0)
        & np.isfinite(denominator)
        & (denominator > 0)
    )
    index = np.full(green_values.shape, np.nan, dtype=np.float32)
    index[valid] = ((green_values[valid] - swir_values[valid]) / denominator[valid]).astype(np.float32)
    return index, valid


def _signed_asset_url(href: str, *, timeout: int = 60) -> str:
    try:
        response = requests.get(
            SAS_SIGN_URL,
            params={"href": href},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        signed = payload.get("href") if isinstance(payload, dict) else None
        if not isinstance(signed, str) or not signed.startswith("https://"):
            raise CrosscheckError("Planetary Computer did not return a signed HTTPS asset URL.")
        return signed
    except requests.RequestException as exc:
        raise CrosscheckError(f"Could not obtain a temporary Sentinel-2 asset access URL: {type(exc).__name__}.") from None


def _search_items(
    *,
    aoi_geometry_wgs84: Any,
    observation_date: date,
    max_day_offset: int,
    max_cloud_cover: float,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    start = observation_date - timedelta(days=max_day_offset)
    end = observation_date + timedelta(days=max_day_offset)
    body = {
        "collections": [COLLECTION],
        "intersects": aoi_geometry_wgs84.__geo_interface__,
        "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": float(max_cloud_cover)}},
        "limit": 100,
    }
    try:
        response = requests.post(
            STAC_SEARCH_URL,
            json=body,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        features = payload.get("features") if isinstance(payload, dict) else None
        return features if isinstance(features, list) else []
    except requests.RequestException as exc:
        raise CrosscheckError(f"Sentinel-2 STAC search failed: {type(exc).__name__}.") from None
    except ValueError:
        raise CrosscheckError("Sentinel-2 STAC search returned invalid JSON.") from None


def _window_for_aoi(dataset: rasterio.io.DatasetReader, bounds: tuple[float, float, float, float]) -> Window:
    window = from_bounds(*bounds, transform=dataset.transform).round_offsets().round_lengths()
    full = Window(0, 0, dataset.width, dataset.height)
    try:
        clipped = window.intersection(full)
    except rasterio.errors.WindowError:
        raise CrosscheckError("Selected Sentinel-2 tile does not overlap the NISAR mask extent.") from None
    if clipped.width <= 0 or clipped.height <= 0:
        raise CrosscheckError("Selected Sentinel-2 tile has no pixels over the NISAR mask extent.")
    return clipped


def _read_cross_sensor_arrays(
    *,
    nisar_path: Path,
    item: dict[str, Any],
    max_target_pixels: int = MAX_TARGET_PIXELS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    with rasterio.open(nisar_path) as nisar:
        if nisar.count < 1 or nisar.crs is None:
            raise CrosscheckError("NISAR mask must be a single-band georeferenced raster.")
        nisar_crs = CRS.from_user_input(nisar.crs)
        if not nisar_crs.is_projected:
            raise CrosscheckError("NISAR water mask must use a projected CRS.")
        units = str(nisar_crs.linear_units or "").lower()
        if units not in {"metre", "meter", "metres", "meters", "m"}:
            raise CrosscheckError(f"NISAR mask CRS must use metres; found {units!r}.")
        nisar_transform = nisar.transform
        nisar_bounds_wgs84 = transform_bounds(nisar.crs, "EPSG:4326", *nisar.bounds, densify_pts=21)
        nisar_aoi_wgs84 = box(*nisar_bounds_wgs84)
        nisar_src = nisar.read(1, masked=True)
        nisar_valid = ~np.ma.getmaskarray(nisar_src)
        nisar_raw = np.asarray(np.ma.getdata(nisar_src))
        if np.any(nisar_valid & ~np.isin(nisar_raw, (0, 1))):
            raise CrosscheckError("NISAR source mask must contain only 0=non-water, 1=water and NoData.")
        nisar_data = np.full(nisar_raw.shape, 255, dtype=np.uint8)
        nisar_data[nisar_valid] = nisar_raw[nisar_valid].astype(np.uint8)

    signed = {
        key: _signed_asset_url(_asset_href(item, key))
        for key in ("B03", "B11", "SCL")
    }
    try:
        with ExitStack() as stack:
            b11 = stack.enter_context(rasterio.open(signed["B11"]))
            if b11.crs is None or not CRS.from_user_input(b11.crs).is_projected:
                raise CrosscheckError("Sentinel-2 B11 asset must use a projected CRS.")
            b11_crs = CRS.from_user_input(b11.crs)
            b11_units = str(b11_crs.linear_units or "").lower()
            if b11_units not in {"metre", "meter", "metres", "meters", "m"}:
                raise CrosscheckError("Sentinel-2 B11 grid must use metre units.")
            projected_aoi_bounds = transform_bounds(
                "EPSG:4326", b11.crs, *nisar_bounds_wgs84, densify_pts=21
            )
            window = _window_for_aoi(b11, projected_aoi_bounds)
            width = int(window.width)
            height = int(window.height)
            if width * height > max_target_pixels:
                raise CrosscheckError(
                    f"Sentinel-2 comparison window has {width * height:,} pixels, over the safe limit {max_target_pixels:,}."
                )
            target_transform = window_transform(window, b11.transform)
            b11_array = b11.read(1, window=window, masked=True)
            b11_values = np.asarray(b11_array.astype(np.float32).filled(np.nan), dtype=np.float32)
            b11_valid = (~np.ma.getmaskarray(b11_array)) & np.isfinite(b11_values) & (b11_values > 0)

            b03 = stack.enter_context(rasterio.open(signed["B03"]))
            b03_nodata = b03.nodata if b03.nodata is not None else 0
            b03_vrt = stack.enter_context(WarpedVRT(
                b03,
                crs=b11.crs,
                transform=target_transform,
                width=width,
                height=height,
                resampling=Resampling.bilinear,
                src_nodata=b03_nodata,
                nodata=0,
            ))
            b03_array = b03_vrt.read(1, masked=True)
            b03_values = np.asarray(b03_array.astype(np.float32).filled(np.nan), dtype=np.float32)
            b03_valid = (~np.ma.getmaskarray(b03_array)) & np.isfinite(b03_values) & (b03_values > 0)

            scl = stack.enter_context(rasterio.open(signed["SCL"]))
            scl_nodata = scl.nodata if scl.nodata is not None else 0
            scl_vrt = stack.enter_context(WarpedVRT(
                scl,
                crs=b11.crs,
                transform=target_transform,
                width=width,
                height=height,
                resampling=Resampling.nearest,
                src_nodata=scl_nodata,
                nodata=0,
            ))
            scl_values = scl_vrt.read(1).astype(np.uint8)
            scl_water, scl_valid = _scl_water_reference(scl_values)

            nisar_on_b11 = np.full((height, width), 255, dtype=np.uint8)
            reproject(
                source=nisar_data,
                destination=nisar_on_b11,
                src_transform=nisar_transform,
                src_crs=nisar_crs,
                src_nodata=255,
                dst_transform=target_transform,
                dst_crs=b11.crs,
                dst_nodata=255,
                resampling=Resampling.nearest,
                init_dest_nodata=True,
            )
            # A valid-mask warp is separate so masked NISAR cells cannot
            # accidentally become valid zeros during categorical reprojection.
            nisar_valid_on_b11 = np.zeros((height, width), dtype=np.uint8)
            reproject(
                source=nisar_valid.astype(np.uint8),
                destination=nisar_valid_on_b11,
                src_transform=nisar_transform,
                src_crs=nisar_crs,
                src_nodata=0,
                dst_transform=target_transform,
                dst_crs=b11.crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
                init_dest_nodata=True,
            )
            nisar_valid_on_b11 = (nisar_valid_on_b11 == 1) & (nisar_on_b11 != 255)
            index, index_valid = _mndwi(b03_values, b11_values)
            common_valid = nisar_valid_on_b11 & scl_valid & b11_valid & b03_valid & index_valid
            pixel_area = abs(target_transform.a * target_transform.e - target_transform.b * target_transform.d)
            metadata = {
                "nisar_bounds_wgs84": list(nisar_bounds_wgs84),
                "sentinel2_crs": b11.crs.to_string(),
                "sentinel2_width": width,
                "sentinel2_height": height,
                "sentinel2_pixel_area_m2": float(pixel_area),
                "nisar_valid_pixels_on_sentinel2_grid": int(np.count_nonzero(nisar_valid_on_b11)),
                "common_valid_pixels": int(np.count_nonzero(common_valid)),
                "common_support_fraction": (
                    float(np.count_nonzero(common_valid) / np.count_nonzero(nisar_valid_on_b11))
                    if np.count_nonzero(nisar_valid_on_b11) else 0.0
                ),
            }
            return nisar_on_b11 == 1, scl_water, index, common_valid, nisar_valid_on_b11, {
                **metadata,
                "mndwi_valid": index_valid,
                "pixel_area_m2": float(pixel_area),
                "b11_values": b11_values,
                "b03_values": b03_values,
            }
    except CrosscheckError:
        raise
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise CrosscheckError(f"Could not read or align signed Sentinel-2 assets: {type(exc).__name__}.") from None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def run_crosscheck(
    *,
    nisar_mask_path: Path,
    observation_date: date,
    output_dir: Path,
    max_day_offset: int = 3,
    max_cloud_cover: float = 40.0,
    mndwi_threshold: float = 0.0,
    minimum_common_support: float = 0.80,
) -> dict[str, Any]:
    nisar_mask_path = nisar_mask_path.resolve()
    if not nisar_mask_path.is_file():
        raise CrosscheckError("The NISAR water mask file does not exist.")
    if max_day_offset < 0 or max_day_offset > 30:
        raise CrosscheckError("Maximum date offset must be between 0 and 30 days.")
    if not math.isfinite(max_cloud_cover) or not 0 <= max_cloud_cover <= 100:
        raise CrosscheckError("Maximum Sentinel-2 cloud cover must be between 0 and 100 percent.")
    if not math.isfinite(mndwi_threshold) or not -1 <= mndwi_threshold <= 1:
        raise CrosscheckError("MNDWI threshold must be between -1 and 1.")
    if not 0 < minimum_common_support <= 1:
        raise CrosscheckError("Minimum common support must be greater than 0 and at most 1.")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "sentinel2_cross_sensor_agreement.json"
    input_hash = sha256_file(nisar_mask_path)
    with rasterio.open(nisar_mask_path) as nisar:
        if nisar.crs is None or not CRS.from_user_input(nisar.crs).is_projected:
            raise CrosscheckError("NISAR water mask needs a projected CRS.")
        nisar_crs = CRS.from_user_input(nisar.crs)
        bounds = transform_bounds(nisar.crs, "EPSG:4326", *nisar.bounds, densify_pts=21)
        aoi_geometry = box(*bounds)

    items = _search_items(
        aoi_geometry_wgs84=aoi_geometry,
        observation_date=observation_date,
        max_day_offset=max_day_offset,
        max_cloud_cover=max_cloud_cover,
    )
    selected = select_best_item(
        items,
        observation_date=observation_date,
        aoi_geometry_wgs84=aoi_geometry,
        analysis_crs=nisar_crs,
        max_day_offset=max_day_offset,
        max_cloud_cover=max_cloud_cover,
    )
    if selected is None:
        report = {
            "status": "NO_MATCHING_SENTINEL2_SCENE_WITHIN_FILTER",
            "analysis_type": "sentinel2_cross_sensor_agreement_screen",
            "nisar_mask": str(nisar_mask_path.name),
            "nisar_mask_sha256": input_hash,
            "requested_observation_date": observation_date.isoformat(),
            "filters": {
                "collection": COLLECTION,
                "maximum_day_offset_days": max_day_offset,
                "maximum_cloud_cover_percent": max_cloud_cover,
            },
            "metrics": None,
            "warnings": [
                "No Sentinel-2 L2A scene with the required B03/B11/SCL assets met the requested date, cloud and AOI-overlap filters.",
                "No comparison metrics were calculated; absence of a match is not zero agreement.",
            ],
            "sources": {"stac_api": STAC_SEARCH_URL, "collection": COLLECTION, "provider": "Copernicus Sentinel-2 via Microsoft Planetary Computer"},
        }
        _write_json(report_path, report)
        return report

    properties = selected.get("properties") or {}
    acquisition_datetime = str(properties.get("datetime"))
    acquisition_date = _item_date(selected)
    coverage_fraction = _item_coverage_fraction(selected, aoi_geometry, nisar_crs)
    nisar_water, scl_water, mndwi_index, common_valid, nisar_support, raster_meta = _read_cross_sensor_arrays(
        nisar_path=nisar_mask_path,
        item=selected,
    )
    common_valid = common_valid & np.isfinite(mndwi_index)
    common_count = int(np.count_nonzero(common_valid))
    nisar_count = int(np.count_nonzero(nisar_support))
    support_fraction = float(common_count / nisar_count) if nisar_count else 0.0
    metrics: dict[str, Any] | None = None
    status = "CROSS_SENSOR_AGREEMENT_SCREEN"
    warnings = [
        "This is a cross-sensor agreement screen, not ground truth, field validation or a formal accuracy assessment.",
        "Sentinel-2 is optical and NISAR is radar; their acquisition dates and physical sensitivities differ.",
        "SCL classes 4, 5 and 6 are treated as clear vegetation, bare soil and water. Cloud, shadow, snow, unclassified and invalid classes are excluded.",
        "MNDWI uses Sentinel-2 B03 green and B11 SWIR1 on the B11 20 m grid; threshold sensitivity should be reviewed for the local river and season.",
        "Do not treat the map basemap as a measurement or validation input.",
    ]
    if coverage_fraction < minimum_common_support or support_fraction < minimum_common_support:
        status = "INSUFFICIENT_OPTICAL_SPATIAL_SUPPORT"
        warnings.append(
            "The selected single Sentinel-2 tile and/or clear common-valid support covers less than the configured threshold; no agreement score is published."
        )
    else:
        metrics = {
            "scl_water_class": _confusion_metrics(
                nisar_water, scl_water, common_valid, raster_meta["pixel_area_m2"]
            ),
            "mndwi_threshold": float(mndwi_threshold),
            "mndwi_water_class": _confusion_metrics(
                nisar_water, mndwi_index > mndwi_threshold, common_valid, raster_meta["pixel_area_m2"]
            ),
        }

    report = {
        "status": status,
        "analysis_type": "sentinel2_cross_sensor_agreement_screen",
        "nisar_mask": {
            "filename": nisar_mask_path.name,
            "sha256": input_hash,
        },
        "observation": {
            "requested_nisar_date": observation_date.isoformat(),
            "sentinel2_datetime_utc": acquisition_datetime,
            "sentinel2_date": acquisition_date.isoformat(),
            "absolute_date_offset_days": abs((acquisition_date - observation_date).days),
            "sentinel2_item_id": selected.get("id"),
            "sentinel2_product_uri": properties.get("s2:product_uri"),
            "mgrs_tile": properties.get("s2:mgrs_tile"),
            "platform": properties.get("platform"),
            "cloud_cover_percent": float(properties.get("eo:cloud_cover")),
            "aoi_footprint_overlap_fraction": coverage_fraction,
        },
        "method": {
            "sentinel2_collection": COLLECTION,
            "water_classification_1": "SCL == 6 (water)",
            "water_classification_2": f"MNDWI = (B03 - B11) / (B03 + B11) > {mndwi_threshold}",
            "mndwi_threshold": float(mndwi_threshold),
            "scl_clear_classes_used": list(SCL_VALID_CLASSES),
            "common_grid": "Sentinel-2 B11 20 m grid",
            "b03_resampling": "bilinear",
            "scl_and_nisar_mask_resampling": "nearest",
            "minimum_common_support_fraction": minimum_common_support,
        },
        "spatial_support": {
            "nisar_valid_pixels_on_sentinel2_grid": nisar_count,
            "common_valid_pixels": common_count,
            "common_support_fraction": support_fraction,
            "sentinel2_grid": {
                "crs": raster_meta["sentinel2_crs"],
                "width": raster_meta["sentinel2_width"],
                "height": raster_meta["sentinel2_height"],
                "pixel_area_m2": raster_meta["pixel_area_m2"],
            },
        },
        "metrics": metrics,
        "source": {
            "provider": "Copernicus Sentinel-2",
            "catalogue": "Microsoft Planetary Computer STAC",
            "stac_api": "https://planetarycomputer.microsoft.com/api/stac/v1/",
            "collection": COLLECTION,
            "item_id": selected.get("id"),
            "unsigned_assets": {
                key: _asset_href(selected, key)
                for key in ("B03", "B11", "SCL")
            },
        },
        "warnings": warnings,
        "quality": {
            "release_status": "PROVISIONAL",
            "interpretation": "CROSS_SENSOR_AGREEMENT_ONLY_NOT_GROUND_TRUTH",
        },
    }
    _write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nisar-water-mask", required=True, type=Path, help="Full-resolution NISAR-derived binary mask: 1=water, 0=non-water, NoData excluded.")
    parser.add_argument("--observation-date", required=True, help="NISAR observation date YYYY-MM-DD.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-day-offset", type=int, default=3)
    parser.add_argument("--max-cloud-cover", type=float, default=40.0)
    parser.add_argument("--mndwi-threshold", type=float, default=0.0)
    parser.add_argument("--minimum-common-support", type=float, default=0.80)
    args = parser.parse_args()
    try:
        report = run_crosscheck(
            nisar_mask_path=args.nisar_water_mask,
            observation_date=date.fromisoformat(args.observation_date),
            output_dir=args.output_dir,
            max_day_offset=args.max_day_offset,
            max_cloud_cover=args.max_cloud_cover,
            mndwi_threshold=args.mndwi_threshold,
            minimum_common_support=args.minimum_common_support,
        )
        print("SENTINEL2_CROSSCHECK_STATUS=" + str(report["status"]))
        print("SENTINEL2_ITEM=" + str((report.get("observation") or {}).get("sentinel2_item_id", "not-found")))
        print("SENTINEL2_REPORT=" + str(args.output_dir / "sentinel2_cross_sensor_agreement.json"))
        return 0
    except (CrosscheckError, OSError, ValueError) as exc:
        detail = str(exc).strip() or type(exc).__name__
        print("SENTINEL2_CROSSCHECK_ERROR=" + detail[:300], flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
