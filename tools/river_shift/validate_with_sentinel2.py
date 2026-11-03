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
from rasterio.transform import Affine
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely import segmentize
from shapely.geometry import box, shape
from shapely.ops import transform as transform_geometry, unary_union


STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
COLLECTION = "sentinel-2-l2a"
SCL_VALID_CLASSES = (4, 5, 6)
MAX_TARGET_PIXELS = 12_000_000
MAX_SOURCE_PIXELS = 40_000_000
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


def _is_projected_metre_crs(crs: CRS) -> bool:
    """Require a projected CRS whose horizontal axes use true metres."""
    if not crs.is_projected or not crs.axis_info:
        return False
    for axis in crs.axis_info[:2]:
        unit_name = str(axis.unit_name or "").strip().lower()
        conversion = axis.unit_conversion_factor
        if unit_name not in {"metre", "meter", "metres", "meters", "m"}:
            return False
        if conversion is None or not math.isclose(float(conversion), 1.0, rel_tol=0.0, abs_tol=1e-12):
            return False
    return True


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


def _items_coverage_fraction(
    items: list[dict[str, Any]],
    aoi_geometry_wgs84: Any,
    analysis_crs: CRS,
) -> float:
    """Measure same-datatake tile union coverage in a densified metric projection."""
    try:
        # Densify geographic edges before projection. Without this, a rectangle
        # projected as one long edge is not identical to two adjacent half-edge
        # polygons, creating a small artificial gap at MGRS tile boundaries.
        project = Transformer.from_crs("EPSG:4326", analysis_crs, always_xy=True).transform
        dense_aoi = segmentize(aoi_geometry_wgs84, max_segment_length=0.001)
        aoi_projected = transform_geometry(project, dense_aoi)
        if aoi_projected.is_empty or aoi_projected.area <= 0:
            return 0.0
        footprints = []
        for item in items:
            geometry = item.get("geometry")
            if not isinstance(geometry, dict):
                continue
            dense_footprint = segmentize(shape(geometry), max_segment_length=0.001)
            projected = transform_geometry(project, dense_footprint)
            if not projected.is_empty:
                footprints.append(projected)
        if not footprints:
            return 0.0
        covered = unary_union(footprints).intersection(aoi_projected)
        return float(min(1.0, max(0.0, covered.area / aoi_projected.area)))
    except Exception:
        return 0.0


def _processing_baseline(item: dict[str, Any]) -> str:
    properties = item.get("properties") or {}
    # STAC Sentinel-2 extension deprecates s2:processing_baseline in favour
    # of the common processing:version field. Keep the legacy fallback for
    # existing Planetary Computer catalogue records.
    return str(properties.get("processing:version") or properties.get("s2:processing_baseline") or "unknown-baseline")


def _generation_time(item: dict[str, Any]) -> str:
    properties = item.get("properties") or {}
    # Canonical STAC processing extension field first; Sentinel-2 legacy alias
    # remains supported for existing catalogue items.
    return str(properties.get("processing:datetime") or properties.get("s2:generation_time") or "")


def _datatake_group_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    properties = item.get("properties") or {}
    platform = str(properties.get("platform") or properties.get("constellation") or "unknown-platform")
    datatake = properties.get("s2:datatake_id") or properties.get("instrument:datatake_id")
    observed_date = _item_date(item).isoformat()
    processing_baseline = _processing_baseline(item)
    # Never mosaic unrelated scenes just because they happen to share a UTC date.
    # If a provider omits datatake metadata, the item remains its own singleton.
    if isinstance(datatake, str) and datatake.strip():
        return platform, datatake.strip(), observed_date, processing_baseline
    item_id = item.get("id") or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
    return platform, f"item:{item_id}", observed_date, processing_baseline


def select_best_items(
    items: list[dict[str, Any]],
    *,
    observation_date: date,
    aoi_geometry_wgs84: Any,
    analysis_crs: CRS,
    max_day_offset: int = 3,
    max_cloud_cover: float = 40.0,
) -> list[dict[str, Any]] | None:
    """Select one datatake and processing baseline; mosaic adjacent MGRS tiles."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
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
            if _item_coverage_fraction(item, aoi_geometry_wgs84, analysis_crs) <= 0:
                continue
            groups.setdefault(_datatake_group_key(item), []).append(item)
        except (TypeError, ValueError):
            continue

    ranked: list[
        tuple[tuple[float, int, float, str, str, str], list[dict[str, Any]]]
    ] = []
    for (platform, datatake, observed_date, processing_baseline), candidates in groups.items():
        # Reprocessed STAC records can duplicate one MGRS tile within the same
        # datatake and baseline. Keep only the latest generation for each tile.
        latest_by_tile: dict[str, dict[str, Any]] = {}
        for row in candidates:
            properties = row.get("properties") or {}
            tile_key = str(properties.get("s2:mgrs_tile") or row.get("id") or "")
            current = latest_by_tile.get(tile_key)
            if current is None:
                latest_by_tile[tile_key] = row
                continue
            current_properties = current.get("properties") or {}
            candidate_revision = (
                _generation_time(row),
                str(row.get("id") or ""),
            )
            current_revision = (
                _generation_time(current),
                str(current.get("id") or ""),
            )
            if candidate_revision > current_revision:
                latest_by_tile[tile_key] = row

        group = sorted(
            latest_by_tile.values(),
            key=lambda row: (
                float((row.get("properties") or {}).get("eo:cloud_cover", 100.0)),
                str((row.get("properties") or {}).get("s2:mgrs_tile") or row.get("id") or ""),
            ),
        )
        coverage = _items_coverage_fraction(group, aoi_geometry_wgs84, analysis_crs)
        if coverage <= 0:
            continue
        acquisition = date.fromisoformat(observed_date)
        offset = abs((acquisition - observation_date).days)
        clouds = [float((row.get("properties") or {}).get("eo:cloud_cover")) for row in group]
        mean_cloud = float(sum(clouds) / len(clouds))
        ranked.append((
            (-coverage, offset, mean_cloud, platform, datatake, processing_baseline),
            group,
        ))
    if not ranked:
        return None
    ranked.sort(key=lambda value: value[0])
    return ranked[0][1]


def select_best_item(
    items: list[dict[str, Any]],
    *,
    observation_date: date,
    aoi_geometry_wgs84: Any,
    analysis_crs: CRS,
    max_day_offset: int = 3,
    max_cloud_cover: float = 40.0,
) -> dict[str, Any] | None:
    """Compatibility wrapper returning the clearest tile from the best datatake."""
    selected = select_best_items(
        items,
        observation_date=observation_date,
        aoi_geometry_wgs84=aoi_geometry_wgs84,
        analysis_crs=analysis_crs,
        max_day_offset=max_day_offset,
        max_cloud_cover=max_cloud_cover,
    )
    return selected[0] if selected else None


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
    item: dict[str, Any] | list[dict[str, Any]],
    max_target_pixels: int = MAX_TARGET_PIXELS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Read a same-datatake Sentinel-2 tile group onto one full-AOI B11-resolution grid."""
    items = [item] if isinstance(item, dict) else list(item)
    if not items:
        raise CrosscheckError("At least one Sentinel-2 tile is required for raster alignment.")
    datatake_groups = {_datatake_group_key(row) for row in items}
    if len(datatake_groups) != 1:
        raise CrosscheckError(
            "A Sentinel-2 mosaic may contain only one platform, datatake, acquisition date and processing baseline."
        )
    with rasterio.open(nisar_path) as nisar:
        if nisar.count < 1 or nisar.crs is None:
            raise CrosscheckError("NISAR mask must be a single-band georeferenced raster.")
        if nisar.width * nisar.height > MAX_SOURCE_PIXELS:
            raise CrosscheckError(
                f"NISAR source mask has {nisar.width * nisar.height:,} pixels, over the safe limit {MAX_SOURCE_PIXELS:,}."
            )
        nisar_crs = CRS.from_user_input(nisar.crs)
        if not _is_projected_metre_crs(nisar_crs):
            units = [axis.unit_name for axis in nisar_crs.axis_info[:2]]
            raise CrosscheckError(
                f"NISAR mask CRS must be projected in metres; found axis units {units!r}."
            )
        nisar_transform = nisar.transform
        nisar_bounds_native = tuple(nisar.bounds)
        nisar_bounds_wgs84 = transform_bounds(nisar.crs, "EPSG:4326", *nisar.bounds, densify_pts=21)
        nisar_src = nisar.read(1, masked=True)
        nisar_valid = ~np.ma.getmaskarray(nisar_src)
        nisar_raw = np.asarray(np.ma.getdata(nisar_src))
        if np.any(nisar_valid & ~np.isin(nisar_raw, (0, 1))):
            raise CrosscheckError("NISAR source mask must contain only 0=non-water, 1=water and NoData.")
        nisar_data = np.full(nisar_raw.shape, 255, dtype=np.uint8)
        nisar_data[nisar_valid] = nisar_raw[nisar_valid].astype(np.uint8)

    signed_items = [
        {
            "item": row,
            "assets": {
                key: _signed_asset_url(_asset_href(row, key))
                for key in ("B03", "B11", "SCL")
            },
        }
        for row in items
    ]
    try:
        with rasterio.open(signed_items[0]["assets"]["B11"]) as reference_b11:
            if reference_b11.crs is None:
                raise CrosscheckError("Sentinel-2 B11 asset must have a CRS.")
            target_crs = CRS.from_user_input(reference_b11.crs)
            if not _is_projected_metre_crs(target_crs):
                units = [axis.unit_name for axis in target_crs.axis_info[:2]]
                raise CrosscheckError(
                    f"Sentinel-2 B11 grid must use projected metre units; found {units!r}."
                )
            if (
                not math.isclose(reference_b11.transform.b, 0.0, abs_tol=1e-12)
                or not math.isclose(reference_b11.transform.d, 0.0, abs_tol=1e-12)
            ):
                raise CrosscheckError("Sentinel-2 B11 reference grid must be north-up and unrotated.")
            pixel_size_x = abs(float(reference_b11.transform.a))
            pixel_size_y = abs(float(reference_b11.transform.e))
            if pixel_size_x <= 0 or pixel_size_y <= 0:
                raise CrosscheckError("Sentinel-2 B11 reference pixel size is invalid.")

            # Transform directly from the exact NISAR source bounds. Sending
            # projected bounds through WGS84 and back can introduce tiny edge
            # drift that expands an aligned raster by an extra row/column.
            projected_aoi_bounds = transform_bounds(
                nisar_crs, target_crs, *nisar_bounds_native, densify_pts=21
            )
            # Keep the native 20 m B11 pixel spacing and align the expanded
            # target grid to the first tile's pixel origin. The target covers
            # the full NISAR mask extent, even when it crosses MGRS tile edges.
            left = reference_b11.transform.c + math.floor(
                (projected_aoi_bounds[0] - reference_b11.transform.c) / pixel_size_x
            ) * pixel_size_x
            top = reference_b11.transform.f - math.floor(
                (reference_b11.transform.f - projected_aoi_bounds[3]) / pixel_size_y
            ) * pixel_size_y
            width = max(1, int(math.ceil((projected_aoi_bounds[2] - left) / pixel_size_x)))
            height = max(1, int(math.ceil((top - projected_aoi_bounds[1]) / pixel_size_y)))
            if width * height > max_target_pixels:
                raise CrosscheckError(
                    f"Sentinel-2 full-AOI comparison grid has {width * height:,} pixels, over the safe limit {max_target_pixels:,}."
                )
            target_transform = Affine(pixel_size_x, 0.0, left, 0.0, -pixel_size_y, top)

        mosaic_b03 = np.full((height, width), np.nan, dtype=np.float32)
        mosaic_b11 = np.full((height, width), np.nan, dtype=np.float32)
        mosaic_scl = np.zeros((height, width), dtype=np.uint8)
        mosaic_valid = np.zeros((height, width), dtype=bool)
        tile_valid_pixel_counts: dict[str, int] = {}

        # Tiles are already sorted by cloud cover. In overlaps, the clearest
        # eligible tile fills first; subsequent tiles fill only still-empty
        # clear-sky pixels. No dates or datatakes are mixed in one mosaic.
        for record in signed_items:
            row = record["item"]
            properties = row.get("properties") or {}
            item_id = str(row.get("id") or "")
            with ExitStack() as stack:
                b11 = stack.enter_context(rasterio.open(record["assets"]["B11"]))
                b11_nodata = b11.nodata if b11.nodata is not None else 0
                b11_vrt = stack.enter_context(WarpedVRT(
                    b11,
                    crs=target_crs,
                    transform=target_transform,
                    width=width,
                    height=height,
                    resampling=Resampling.bilinear,
                    src_nodata=b11_nodata,
                    nodata=0,
                ))
                b11_array = b11_vrt.read(1, masked=True)
                b11_values = np.asarray(b11_array.astype(np.float32).filled(np.nan), dtype=np.float32)
                b11_valid = (~np.ma.getmaskarray(b11_array)) & np.isfinite(b11_values) & (b11_values > 0)

                b03 = stack.enter_context(rasterio.open(record["assets"]["B03"]))
                b03_nodata = b03.nodata if b03.nodata is not None else 0
                b03_vrt = stack.enter_context(WarpedVRT(
                    b03,
                    crs=target_crs,
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

                scl = stack.enter_context(rasterio.open(record["assets"]["SCL"]))
                scl_nodata = scl.nodata if scl.nodata is not None else 0
                scl_vrt = stack.enter_context(WarpedVRT(
                    scl,
                    crs=target_crs,
                    transform=target_transform,
                    width=width,
                    height=height,
                    resampling=Resampling.nearest,
                    src_nodata=scl_nodata,
                    nodata=0,
                ))
                scl_values = scl_vrt.read(1).astype(np.uint8)
                _scl_water, scl_valid = _scl_water_reference(scl_values)

                tile_valid = b11_valid & b03_valid & scl_valid
                take = tile_valid & ~mosaic_valid
                mosaic_b03[take] = b03_values[take]
                mosaic_b11[take] = b11_values[take]
                mosaic_scl[take] = scl_values[take]
                mosaic_valid[take] = True
                tile_valid_pixel_counts[item_id] = int(np.count_nonzero(take))

        nisar_on_s2 = np.full((height, width), 255, dtype=np.uint8)
        reproject(
            source=nisar_data,
            destination=nisar_on_s2,
            src_transform=nisar_transform,
            src_crs=nisar_crs,
            src_nodata=255,
            dst_transform=target_transform,
            dst_crs=target_crs,
            dst_nodata=255,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
        # Warp NISAR valid support separately so NoData cannot turn into zero.
        nisar_valid_on_s2 = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=nisar_valid.astype(np.uint8),
            destination=nisar_valid_on_s2,
            src_transform=nisar_transform,
            src_crs=nisar_crs,
            src_nodata=0,
            dst_transform=target_transform,
            dst_crs=target_crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
        nisar_support = (nisar_valid_on_s2 == 1) & (nisar_on_s2 != 255)
        index, index_valid = _mndwi(mosaic_b03, mosaic_b11)
        common_valid = nisar_support & mosaic_valid & index_valid
        pixel_area = abs(target_transform.a * target_transform.e - target_transform.b * target_transform.d)
        tile_ids = [
            str((row.get("properties") or {}).get("s2:mgrs_tile") or row.get("id") or "")
            for row in items
        ]
        metadata = {
            "nisar_bounds_wgs84": list(nisar_bounds_wgs84),
            "sentinel2_crs": target_crs.to_string(),
            "sentinel2_width": width,
            "sentinel2_height": height,
            "sentinel2_pixel_area_m2": float(pixel_area),
            "sentinel2_tile_count": len(items),
            "sentinel2_mgrs_tiles": tile_ids,
            "tile_common_clear_pixel_counts": tile_valid_pixel_counts,
            "nisar_valid_pixels_on_sentinel2_grid": int(np.count_nonzero(nisar_support)),
            "common_valid_pixels": int(np.count_nonzero(common_valid)),
            "common_support_fraction": (
                float(np.count_nonzero(common_valid) / np.count_nonzero(nisar_support))
                if np.count_nonzero(nisar_support) else 0.0
            ),
        }
        return nisar_on_s2 == 1, mosaic_scl == 6, index, common_valid, nisar_support, {
            **metadata,
            "pixel_area_m2": float(pixel_area),
        }
    except CrosscheckError:
        raise
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise CrosscheckError(f"Could not read or align Sentinel-2 datatake mosaic: {type(exc).__name__}.") from None


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
    selected_items = select_best_items(
        items,
        observation_date=observation_date,
        aoi_geometry_wgs84=aoi_geometry,
        analysis_crs=nisar_crs,
        max_day_offset=max_day_offset,
        max_cloud_cover=max_cloud_cover,
    )
    if selected_items is None:
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
                "No Sentinel-2 L2A datatake with the required B03/B11/SCL assets met the requested date, cloud and AOI-overlap filters.",
                "No comparison metrics were calculated; absence of a match is not zero agreement.",
            ],
            "sources": {"stac_api": STAC_SEARCH_URL, "collection": COLLECTION, "provider": "Copernicus Sentinel-2 via Microsoft Planetary Computer"},
        }
        _write_json(report_path, report)
        return report

    primary = selected_items[0]
    properties = primary.get("properties") or {}
    acquisition_datetimes = sorted(
        str((row.get("properties") or {}).get("datetime") or "")
        for row in selected_items
    )
    acquisition_datetime = acquisition_datetimes[0]
    acquisition_dates = {_item_date(row) for row in selected_items}
    if len(acquisition_dates) != 1:
        raise CrosscheckError("Selected Sentinel-2 datatake contains inconsistent acquisition dates.")
    acquisition_date = next(iter(acquisition_dates))
    coverage_fraction = _items_coverage_fraction(
        selected_items, aoi_geometry, nisar_crs
    )
    nisar_water, scl_water, mndwi_index, common_valid, nisar_support, raster_meta = _read_cross_sensor_arrays(
        nisar_path=nisar_mask_path,
        item=selected_items,
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
            "The selected same-datatake Sentinel-2 tile mosaic and/or clear common-valid support covers less than the configured threshold; no agreement score is published."
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
            "sentinel2_datetimes_utc": acquisition_datetimes,
            "sentinel2_date": acquisition_date.isoformat(),
            "absolute_date_offset_days": abs((acquisition_date - observation_date).days),
            "sentinel2_item_id": primary.get("id"),
            "sentinel2_item_ids": [row.get("id") for row in selected_items],
            "sentinel2_product_uri": properties.get("s2:product_uri"),
            "sentinel2_datatake_id": properties.get("s2:datatake_id") or properties.get("instrument:datatake_id"),
            "sentinel2_processing_baseline": _processing_baseline(primary),
            "mgrs_tile": properties.get("s2:mgrs_tile"),
            "mgrs_tiles": raster_meta["sentinel2_mgrs_tiles"],
            "sentinel2_tile_count": len(selected_items),
            "platform": properties.get("platform"),
            "cloud_cover_percent": float(
                sum(float((row.get("properties") or {}).get("eo:cloud_cover")) for row in selected_items)
                / len(selected_items)
            ),
            "maximum_tile_cloud_cover_percent": max(
                float((row.get("properties") or {}).get("eo:cloud_cover"))
                for row in selected_items
            ),
            "aoi_footprint_overlap_fraction": coverage_fraction,
        },
        "method": {
            "sentinel2_collection": COLLECTION,
            "water_classification_1": "SCL == 6 (water)",
            "water_classification_2": f"MNDWI = (B03 - B11) / (B03 + B11) > {mndwi_threshold}",
            "mndwi_threshold": float(mndwi_threshold),
            "scl_clear_classes_used": list(SCL_VALID_CLASSES),
            "common_grid": "Sentinel-2 B11 20 m grid expanded to the full NISAR extent; adjacent MGRS tiles from one datatake are mosaicked",
            "tile_mosaic_method": "same platform, datatake ID, acquisition date and processing baseline; duplicate MGRS items retain the latest processing:datetime (or legacy s2:generation_time); clearest valid tile fills overlaps first",
            "b03_resampling": "bilinear",
            "b11_resampling": "bilinear",
            "scl_and_nisar_mask_resampling": "nearest",
            "minimum_common_support_fraction": minimum_common_support,
        },
        "spatial_support": {
            "nisar_valid_pixels_on_sentinel2_grid": nisar_count,
            "common_valid_pixels": common_count,
            "common_support_fraction": support_fraction,
            "sentinel2_tile_count": len(selected_items),
            "sentinel2_mgrs_tiles": raster_meta["sentinel2_mgrs_tiles"],
            "tile_common_clear_pixel_counts": raster_meta["tile_common_clear_pixel_counts"],
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
            "item_id": primary.get("id"),
            "item_ids": [row.get("id") for row in selected_items],
            "tile_items": [
                {
                    "item_id": row.get("id"),
                    "mgrs_tile": (row.get("properties") or {}).get("s2:mgrs_tile"),
                    "processing_baseline": _processing_baseline(row),
                    "generation_time": _generation_time(row) or None,
                    "cloud_cover_percent": float((row.get("properties") or {}).get("eo:cloud_cover")),
                    "unsigned_assets": {
                        key: _asset_href(row, key)
                        for key in ("B03", "B11", "SCL")
                    },
                }
                for row in selected_items
            ],
            "unsigned_assets": {
                key: _asset_href(primary, key)
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
