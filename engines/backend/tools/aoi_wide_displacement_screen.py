#!/usr/bin/env python3
"""Target-free AOI-wide exploratory displacement-candidate screen over retained GOFF exports.

This stage is for Find Displacements. It does not require a target point or crown
polygon, never uses the AOI centre as a target, and never merges GOFF with GUNW.
Outputs are spatial review candidates, not verified landslides or hazard alerts.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import geometry_mask, shapes
from rasterio.warp import transform_geom

SCHEMA = "sarguardian-find-displacements-aoi-screen/1.0"
GRANULE_ID = re.compile(
    r"NISAR_L2_(?P<processing>PR|UR|OD)_GOFF_(?P<granule>\d{3})_"
    r"(?P<track>\d{3})_(?P<direction>[AD])_(?P<frame>\d{3})_"
    r"(?P<subswath>\d{3})_(?P<bandwidth>\d{4})_(?P<polarization>[A-Z]{2})_"
    r"(?P<ref>\d{8})T\d{6}_\d{8}T\d{6}_"
    r"(?P<sec>\d{8})T\d{6}_\d{8}T\d{6}_"
    r"(?P<crid>[PX]\d{5})_"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _identity(row: dict[str, Any]) -> dict[str, str] | None:
    match = GRANULE_ID.search(str(row.get("granule_name") or ""))
    if not match:
        return None
    result = match.groupdict()
    result["reference_date"] = str(row.get("reference_date") or result["ref"])[:10]
    result["secondary_date"] = str(row.get("secondary_date") or result["sec"])[:10]
    return result


def _safe_id(identity: dict[str, str]) -> str:
    return (
        "GOFF_" + identity["processing"] + "_" + identity["crid"] + "_"
        + identity["direction"] + identity["track"] + "_F" + identity["frame"]
        + "_BW" + identity["bandwidth"] + "_" + identity["polarization"]
    )


def _pair_offset_threshold_m(
    row: dict[str, Any], identity: dict[str, str], fallback_m: float
) -> tuple[float, float | None]:
    """Use the reader's 3-sigma range floor over this pair when it is reported.

    The reader's detect_floor_mm_day is 3 * robust range sigma / pair span.
    Multiplying by this pair's actual elapsed days returns the corresponding
    3-sigma offset floor. It is a conservative AOI-wide screen gate, not a local
    candidate-specific floor or a formal probability of detection.
    """
    stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
    try:
        floor_rate = float(stats.get("detect_floor_mm_day"))
    except (TypeError, ValueError, OverflowError):
        floor_rate = float("nan")
    try:
        ref_day = date.fromisoformat(identity["reference_date"][:10])
        sec_day = date.fromisoformat(identity["secondary_date"][:10])
        elapsed_days = (sec_day - ref_day).days
    except (TypeError, ValueError, OverflowError):
        elapsed_days = 0
    if not math.isfinite(floor_rate) or floor_rate < 0 or elapsed_days <= 0:
        return float(fallback_m), None
    return max(float(fallback_m), floor_rate * elapsed_days / 1000.0), floor_rate


def _box_sum(values: np.ndarray, window: int) -> np.ndarray:
    """Constant-zero padded integral-image sum; output keeps the exact HxW grid."""
    if window < 3 or window % 2 != 1:
        raise ValueError("LOCAL_WINDOW_MUST_BE_ODD_AND_AT_LEAST_3")
    radius = window // 2
    padded = np.pad(np.asarray(values, dtype=np.float64),
                    ((radius, radius), (radius, radius)), mode="constant")
    integral = np.pad(
        np.cumsum(np.cumsum(padded, axis=0, dtype=np.float64), axis=1, dtype=np.float64),
        ((1, 0), (1, 0)), mode="constant",
    )
    k = window
    return (
        integral[k:, k:] - integral[:-k, k:]
        - integral[k:, :-k] + integral[:-k, :-k]
    )


def _local_mean(values: np.ndarray, valid: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    count = _box_sum(np.asarray(valid, dtype=np.float32), window)
    total = _box_sum(np.where(valid, values, 0.0).astype(np.float32), window)
    mean = np.full(values.shape, np.nan, dtype=np.float32)
    enough = count > 0
    mean[enough] = (total[enough] / count[enough]).astype(np.float32)
    return mean, count


def _screen_pair(
    path: Path,
    aoi_geometry: dict[str, Any],
    *,
    expected_crid: str,
    window: int,
    direction_window: int,
    min_offset_m: float,
    min_robust_z: float,
    min_directional_coherence: float,
) -> dict[str, Any]:
    with rasterio.open(path) as src:
        if src.crs is None or src.count < 3:
            raise ValueError("GOFF_EXPORT_NEEDS_CRS_AND_THREE_BANDS:" + path.name)
        tags = src.tags()
        if not src.crs.is_projected or str(src.crs.linear_units).lower() not in {"metre", "meter", "metres", "meters"}:
            raise ValueError("GOFF_EXPORT_GRID_MUST_BE_PROJECTED_METRES:" + path.name)
        tagged_crid = str(tags.get("crid") or "").strip().upper()
        if tagged_crid and tagged_crid != expected_crid:
            raise ValueError("GOFF_EXPORT_CRID_MISMATCH_EXPECTED_" + expected_crid + "_GOT_" + tagged_crid)
        if str(tags.get("aoi_mask_applied", "")).lower() != "true":
            raise ValueError("GOFF_EXPORT_AOI_MASK_PROVENANCE_MISSING:" + path.name)
        if tags.get("grid_policy") != "common_aoi_lattice":
            raise ValueError("GOFF_EXPORT_GRID_IS_NOT_COMMON_AOI_LATTICE:" + path.name)
        crs, transform = src.crs, src.transform
        shape = (src.height, src.width)
        polygon = transform_geom("EPSG:4326", crs, aoi_geometry)
        inside_aoi = geometry_mask(
            [polygon], out_shape=shape, transform=transform, invert=True, all_touched=False
        )
        range_mm, azimuth_mm, corr = [
            src.read(i).astype(np.float32, copy=False) for i in (1, 2, 3)
        ]
        nodata = src.nodata
        if nodata is not None and math.isfinite(float(nodata)):
            range_mm[range_mm == nodata] = np.nan
            azimuth_mm[azimuth_mm == nodata] = np.nan
            corr[corr == nodata] = np.nan
        corr_min = float(tags.get("correlation_min", "0.3"))
        valid = (
            inside_aoi
            & np.isfinite(range_mm) & np.isfinite(azimuth_mm) & np.isfinite(corr)
            & (corr >= corr_min)
        )
        range_m = range_mm / 1000.0
        azimuth_m = azimuth_mm / 1000.0
        count = int(valid.sum())
        aoi_pixels = int(inside_aoi.sum())
        grid_meta = {
            "crs": crs,
            "shape": shape,
            "transform": transform,
            "inside_aoi": inside_aoi,
        }
    result = {
        "path": path, "grid": grid_meta, "valid": valid,
        "valid_pixels": count, "aoi_pixels": aoi_pixels,
        "source_sha256": sha256_file(path), "source_bytes": path.stat().st_size,
        "correlation_min": corr_min,
    }
    if count == 0:
        result.update({
            "candidate": np.zeros(valid.shape, dtype=bool),
            "range_residual_m": np.full(valid.shape, np.nan, dtype=np.float32),
            "azimuth_residual_m": np.full(valid.shape, np.nan, dtype=np.float32),
            "candidate_pixels": 0, "status": "NO_VALID_AOI_PIXELS",
        })
        return result

    local_count = _box_sum(valid.astype(np.float32), window)
    local_minimum = max(10, int(window * window * 0.20))
    enough = valid & (local_count >= local_minimum)
    range_mean, _ = _local_mean(range_m, valid, window)
    azimuth_mean, _ = _local_mean(azimuth_m, valid, window)
    range_residual = range_m - range_mean
    azimuth_residual = azimuth_m - azimuth_mean
    magnitude = np.hypot(range_residual, azimuth_residual).astype(np.float32)
    # Estimate the background noise scale robustly over the AOI after local
    # detrending. A local MAD computed from anomaly magnitude itself is biased
    # upward inside a coherent moving patch and can suppress the very signal
    # being screened. The global component-wise MAD is resilient while fewer
    # than half the valid AOI cells belong to an anomaly.
    rr = range_residual[valid & np.isfinite(range_residual)].astype(np.float64)
    ar = azimuth_residual[valid & np.isfinite(azimuth_residual)].astype(np.float64)
    range_median = float(np.median(rr)) if rr.size else 0.0
    azimuth_median = float(np.median(ar)) if ar.size else 0.0
    range_sigma = 1.4826 * float(np.median(np.abs(rr - range_median))) if rr.size else 0.0
    azimuth_sigma = 1.4826 * float(np.median(np.abs(ar - azimuth_median))) if ar.size else 0.0
    robust_scale_m = max(range_sigma, azimuth_sigma, 0.03)
    robust_z = magnitude / robust_scale_m

    vector_valid = valid & np.isfinite(magnitude) & (magnitude > 1e-5)
    ux = np.zeros(magnitude.shape, dtype=np.float32)
    uy = np.zeros(magnitude.shape, dtype=np.float32)
    ux[vector_valid] = range_residual[vector_valid] / magnitude[vector_valid]
    uy[vector_valid] = azimuth_residual[vector_valid] / magnitude[vector_valid]
    ux_mean, direction_count = _local_mean(ux, vector_valid, direction_window)
    uy_mean, _ = _local_mean(uy, vector_valid, direction_window)
    direction_coherence = np.hypot(ux_mean, uy_mean)
    candidate = (
        enough
        & np.isfinite(magnitude) & (magnitude >= min_offset_m)
        & np.isfinite(robust_z) & (robust_z >= min_robust_z)
        & (direction_count >= max(5, int(direction_window * direction_window * 0.35)))
        & np.isfinite(direction_coherence)
        & (direction_coherence >= min_directional_coherence)
    )
    result.update({
        "candidate": candidate,
        "range_residual_m": range_residual.astype(np.float32),
        "azimuth_residual_m": azimuth_residual.astype(np.float32),
        "robust_z": robust_z.astype(np.float32),
        "directional_coherence": direction_coherence.astype(np.float32),
        "candidate_pixels": int(candidate.sum()),
        "max_offset_anomaly_m": float(np.nanmax(magnitude[candidate])) if candidate.any() else None,
        "robust_background_scale_m": float(robust_scale_m),
        "status": "SCREENED_NOT_DETECTION",
    })
    return result


def _same_grid(first: dict[str, Any], other: dict[str, Any]) -> bool:
    return (
        first["crs"] == other["crs"] and first["shape"] == other["shape"]
        and np.allclose(tuple(first["transform"]), tuple(other["transform"]), rtol=0, atol=1e-7)
        and np.array_equal(first["inside_aoi"], other["inside_aoi"])
    )


def _component_features(
    mask: np.ndarray,
    hit_count: np.ndarray,
    pair_direction_coherence: np.ndarray,
    transform: Any,
    crs: Any,
    series_id: str,
    identity: dict[str, str],
    pair_count: int,
    persistence: int,
    minimum_pixels: int,
) -> list[dict[str, Any]]:
    pixel_area = abs(float(transform.a * transform.e))
    result: list[dict[str, Any]] = []
    for geom, value in shapes(
        mask.astype(np.uint8), mask=mask, transform=transform, connectivity=8
    ):
        if int(value) != 1:
            continue
        coordinates = geom.get("coordinates", [[]])[0]
        twice_area = 0.0
        centroid_x = centroid_y = 0.0
        for i in range(max(0, len(coordinates) - 1)):
            x0, y0 = coordinates[i]
            x1, y1 = coordinates[i + 1]
            cross = x0 * y1 - x1 * y0
            twice_area += cross
            centroid_x += (x0 + x1) * cross
            centroid_y += (y0 + y1) * cross
        area_m2 = abs(twice_area) / 2.0
        pixels = int(round(area_m2 / pixel_area)) if pixel_area > 0 else 0
        if pixels < minimum_pixels or abs(twice_area) < 1e-9:
            continue
        centroid_x /= 3.0 * twice_area
        centroid_y /= 3.0 * twice_area
        projected_center = {"type": "Point", "coordinates": [centroid_x, centroid_y]}
        center_wgs = transform_geom(crs, "EPSG:4326", projected_center)["coordinates"]
        geometry_wgs = transform_geom(crs, "EPSG:4326", geom)
        from rasterio.features import rasterize
        component_mask = rasterize(
            [(geom, 1)], out_shape=mask.shape, transform=transform,
            fill=0, dtype=np.uint8,
        ).astype(bool) & mask
        persistence_values = hit_count[component_mask]
        persistence_min = int(persistence_values.min()) if persistence_values.size else int(persistence)
        persistence_median = float(np.median(persistence_values)) if persistence_values.size else float(persistence)
        persistence_max = int(persistence_values.max()) if persistence_values.size else int(persistence)
        result.append({
            "type": "Feature",
            "properties": {
                "candidate_id": "",
                "series_id": series_id,
                "product_family": "GOFF",
                "track": identity["track"],
                "direction": "ASCENDING" if identity["direction"] == "A" else "DESCENDING",
                "frame": identity["frame"],
                "crid": identity["crid"],
                "processing": identity["processing"],
                "pairs_in_series": pair_count,
                "pairs_with_candidate": persistence_min,
                "pair_persistence_median": persistence_median,
                "pair_persistence_max": persistence_max,
                "mean_cross_pair_directional_coherence": round(
                    float(np.nanmean(pair_direction_coherence[component_mask])), 4
                ) if np.isfinite(pair_direction_coherence[component_mask]).any() else None,
                "pixels_approx": pixels,
                "area_km2_approx": round(area_m2 / 1e6, 6),
                "centroid_lon": round(float(center_wgs[0]), 6),
                "centroid_lat": round(float(center_wgs[1]), 6),
                "interpretation": "AOI-wide offset-anomaly review candidate; not a confirmed displacement or hazard",
            },
            "geometry": geometry_wgs,
        })
    result.sort(key=lambda feature: (
        -int(feature["properties"]["pixels_approx"]),
        feature["properties"]["centroid_lat"],
        feature["properties"]["centroid_lon"],
    ))
    for index, feature in enumerate(result, 1):
        feature["properties"]["candidate_id"] = f"{series_id}-C{index:03d}"
    return result


def _write_float_raster(
    path: Path, array: np.ndarray, meta: dict[str, Any], description: str
) -> None:
    """Write a float32 diagnostic raster on the exact AOI grid."""
    path.parent.mkdir(parents=True, exist_ok=True)
    output = np.asarray(array, dtype=np.float32).copy()
    output[~meta["inside_aoi"]] = np.nan
    with rasterio.open(
        path, "w", driver="GTiff", width=output.shape[1], height=output.shape[0],
        count=1, dtype="float32", crs=meta["crs"], transform=meta["transform"],
        nodata=np.nan, compress="deflate", predictor=3,
    ) as dst:
        dst.write(output, 1)
        dst.set_band_description(1, description)
        dst.update_tags(
            schema=SCHEMA, interpretation="EXPLORATORY_REVIEW_CANDIDATE_NOT_HAZARD",
            target_required="false", family="GOFF", series_id=path.stem,
        )


def _write_count_raster(
    path: Path, array: np.ndarray, meta: dict[str, Any], nodata: int, description: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
        count=1, dtype=array.dtype, crs=meta["crs"], transform=meta["transform"],
        nodata=nodata, compress="deflate", predictor=2,
    ) as dst:
        dst.write(array, 1)
        dst.set_band_description(1, description)
        dst.update_tags(
            schema=SCHEMA, interpretation="EXPLORATORY_REVIEW_CANDIDATE_NOT_HAZARD",
            target_required="false", family="GOFF", series_id=path.stem,
        )


def run_aoi_wide_screen(
    products: list[dict[str, Any]],
    root: Path,
    out_dir: Path,
    aoi_wkt: str,
    *,
    minimum_pairs: int = 2,
    minimum_component_pixels: int = 10,
    local_window_px: int = 41,
    direction_window_px: int = 5,
    minimum_offset_anomaly_m: float = 0.25,
    minimum_robust_z: float = 4.0,
    minimum_directional_coherence: float = 0.75,
    minimum_cross_pair_directional_coherence: float = 0.75,
) -> dict[str, Any]:
    """Scan the entire submitted AOI without requiring any local target polygon."""
    if minimum_pairs < 2 or minimum_component_pixels < 1:
        raise ValueError("TEMPORAL_AND_COMPONENT_GATES_INVALID")
    if local_window_px < 3 or local_window_px % 2 != 1:
        raise ValueError("LOCAL_WINDOW_MUST_BE_ODD_AND_AT_LEAST_3")
    if direction_window_px < 3 or direction_window_px % 2 != 1:
        raise ValueError("DIRECTION_WINDOW_MUST_BE_ODD_AND_AT_LEAST_3")
    if not (math.isfinite(minimum_offset_anomaly_m) and minimum_offset_anomaly_m > 0):
        raise ValueError("MINIMUM_OFFSET_ANOMALY_MUST_BE_POSITIVE")
    if not (math.isfinite(minimum_robust_z) and minimum_robust_z > 0):
        raise ValueError("MINIMUM_ROBUST_Z_MUST_BE_POSITIVE")
    if not (0 <= minimum_directional_coherence <= 1):
        raise ValueError("MINIMUM_DIRECTIONAL_COHERENCE_OUT_OF_RANGE")
    if not (0 <= minimum_cross_pair_directional_coherence <= 1):
        raise ValueError("MINIMUM_CROSS_PAIR_DIRECTIONAL_COHERENCE_OUT_OF_RANGE")
    match = re.fullmatch(
        r"\s*POLYGON\s*\(\(\s*(.*?)\s*\)\)\s*", aoi_wkt, flags=re.IGNORECASE
    )
    if not match:
        raise ValueError("AOI_WKT_MUST_BE_A_SINGLE_RING_POLYGON")
    ring: list[list[float]] = []
    for item in match.group(1).split(","):
        parts = item.split()
        if len(parts) != 2:
            raise ValueError("AOI_WKT_COORDINATE_MALFORMED")
        lon, lat = float(parts[0]), float(parts[1])
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("AOI_WKT_COORDINATE_OUTSIDE_WGS84")
        ring.append([lon, lat])
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("AOI_WKT_RING_MUST_BE_CLOSED")
    aoi_geometry = {"type": "Polygon", "coordinates": [ring]}

    # Build metadata-only descriptors first; do not read raster arrays until a
    # deduplicated, compatible series is known.
    descriptors: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for row in products:
        if str(row.get("product_type") or "").upper() != "GOFF":
            continue
        identity = _identity(row)
        if identity is None:
            rejected.append({"product_id": str(row.get("id") or ""), "reason": "GOFF_GRANULE_ID_UNPARSEABLE"})
            continue
        candidates = []
        for export in row.get("exports") or []:
            relative = str(export.get("relative_path") or "")
            if relative.lower().endswith((".tif", ".tiff")) and "GOFF" in Path(relative).name.upper():
                candidates.append(relative)
        if len(candidates) != 1:
            rejected.append({"product_id": str(row.get("id") or ""), "reason": "EXPECTED_ONE_GOFF_TIFF_EXPORT"})
            continue
        path = (root / candidates[0]).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            rejected.append({"product_id": str(row.get("id") or ""), "reason": "EXPORT_PATH_ESCAPES_ROOT"})
            continue
        if not path.is_file():
            rejected.append({"product_id": str(row.get("id") or ""), "reason": "GOFF_EXPORT_FILE_MISSING"})
            continue
        key = (
            identity["processing"], identity["track"], identity["direction"], identity["frame"],
            identity["bandwidth"], identity["polarization"], identity["crid"],
        )
        interval = (identity["reference_date"], identity["secondary_date"])
        record_crid = str(row.get("crid") or "").strip().upper()
        if record_crid and record_crid != identity["crid"]:
            rejected.append({
                "product_id": str(row.get("id") or ""),
                "reason": "CATALOG_AND_GRANULE_CRID_MISMATCH",
            })
            continue
        pair_threshold_m, reader_floor_rate = _pair_offset_threshold_m(
            row, identity, minimum_offset_anomaly_m
        )
        descriptors.append({
            "row": row, "identity": identity, "path": path, "series_key": key,
            "interval": interval, "minimum_offset_threshold_m": pair_threshold_m,
            "reader_detect_floor_mm_day": reader_floor_rate,
        })

    # One interval is one independent temporal pair. If duplicate swaths/variants
    # exist in one series, retain the export with the highest validated support.
    by_series: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for item in descriptors:
        by_series.setdefault(item["series_key"], []).append(item)
    deduped_series: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    duplicate_exclusions: list[dict[str, Any]] = []
    for key, items in by_series.items():
        by_interval: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in items:
            by_interval.setdefault(item["interval"], []).append(item)
        selected = []
        for interval, duplicates in by_interval.items():
            duplicates.sort(
                key=lambda item: (
                    int(item["row"].get("valid_pixels") or 0),
                    str(item["row"].get("id") or ""),
                ), reverse=True
            )
            selected.append(duplicates[0])
            for skipped in duplicates[1:]:
                duplicate_exclusions.append({
                    "product_id": skipped["row"].get("id"),
                    "series_key": list(key), "interval": list(interval),
                    "reason": "DUPLICATE_ACQUISITION_INTERVAL; lower validated pixel support than retained variant",
                })
        deduped_series[key] = sorted(selected, key=lambda item: item["interval"])

    out_dir.mkdir(parents=True, exist_ok=True)
    all_features: list[dict[str, Any]] = []
    series_reports: list[dict[str, Any]] = []
    for key, items in sorted(deduped_series.items()):
        identity = items[0]["identity"]
        series_id = _safe_id(identity)
        pair_results: list[dict[str, Any]] = []
        series_grid = None
        hit_count = None
        valid_union = None
        direction_range_sum = None
        direction_azimuth_sum = None
        good_pair_count = 0
        grid_error = None

        # Stream a single export's arrays at a time. Only compact accumulators
        # are retained, so large AOIs do not hold every pair raster in memory.
        for item in items:
            try:
                pair = _screen_pair(
                    item["path"], aoi_geometry, expected_crid=identity["crid"],
                    window=local_window_px,
                    direction_window=direction_window_px,
                    min_offset_m=float(item["minimum_offset_threshold_m"]),
                    min_robust_z=minimum_robust_z,
                    min_directional_coherence=minimum_directional_coherence,
                )
            except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
                pair_results.append({
                    "product_id": item["row"].get("id"), "granule_name": item["row"].get("granule_name"),
                    "reference_date": item["identity"]["reference_date"],
                    "secondary_date": item["identity"]["secondary_date"],
                    "status": "PAIR_SCREEN_FAILED", "error": type(exc).__name__ + ":" + str(exc)[:220],
                    "valid_aoi_pixels": 0, "candidate_pixels": 0,
                })
                grid_error = "PAIR_SCREEN_FAILED"
                continue

            if series_grid is None:
                series_grid = pair["grid"]
                hit_count = np.zeros(pair["grid"]["shape"], dtype=np.uint16)
                valid_union = np.zeros(pair["grid"]["shape"], dtype=bool)
                direction_range_sum = np.zeros(pair["grid"]["shape"], dtype=np.float32)
                direction_azimuth_sum = np.zeros(pair["grid"]["shape"], dtype=np.float32)
            elif not _same_grid(series_grid, pair["grid"]):
                pair_results.append({
                    "product_id": item["row"].get("id"), "granule_name": item["row"].get("granule_name"),
                    "reference_date": item["identity"]["reference_date"],
                    "secondary_date": item["identity"]["secondary_date"],
                    "status": "INCOMPATIBLE_GRID_SERIES_WITHHELD",
                    "valid_aoi_pixels": pair["valid_pixels"], "candidate_pixels": 0,
                })
                grid_error = "INCOMPATIBLE_GRID_SERIES_WITHHELD"
                del pair
                continue

            if grid_error is None:
                valid_union |= pair["valid"]
                hit = pair["candidate"]
                hit_count += hit.astype(np.uint16)
                magnitude = np.hypot(pair["range_residual_m"], pair["azimuth_residual_m"])
                direction_valid = hit & np.isfinite(magnitude) & (magnitude > 1e-5)
                range_direction = np.zeros(magnitude.shape, dtype=np.float32)
                azimuth_direction = np.zeros(magnitude.shape, dtype=np.float32)
                range_direction[direction_valid] = pair["range_residual_m"][direction_valid] / magnitude[direction_valid]
                azimuth_direction[direction_valid] = pair["azimuth_residual_m"][direction_valid] / magnitude[direction_valid]
                direction_range_sum += range_direction
                direction_azimuth_sum += azimuth_direction
                good_pair_count += 1

            pair_results.append({
                "product_id": item["row"].get("id"), "granule_name": item["row"].get("granule_name"),
                "reference_date": item["identity"]["reference_date"],
                "secondary_date": item["identity"]["secondary_date"],
                "source_asset": str(item["path"].relative_to(root.resolve())).replace("\\", "/"),
                "source_sha256": pair["source_sha256"], "source_bytes": pair["source_bytes"],
                "aoi_grid_pixels": pair["aoi_pixels"], "valid_aoi_pixels": pair["valid_pixels"],
                "valid_aoi_fraction": pair["valid_pixels"] / pair["aoi_pixels"] if pair["aoi_pixels"] else 0.0,
                "candidate_pixels": pair["candidate_pixels"],
                "minimum_offset_threshold_m": item["minimum_offset_threshold_m"],
                "reader_detect_floor_mm_day": item["reader_detect_floor_mm_day"],
                "max_offset_anomaly_m": pair.get("max_offset_anomaly_m"),
                "robust_background_scale_m": pair.get("robust_background_scale_m"),
                "correlation_min": pair["correlation_min"], "status": pair["status"],
            })
            del pair

        if grid_error or good_pair_count != len(items) or series_grid is None:
            series_reports.append({
                "series_id": series_id, "product_family": "GOFF",
                "processing": identity["processing"], "crid": identity["crid"],
                "track": identity["track"], "direction": "ASCENDING" if identity["direction"] == "A" else "DESCENDING",
                "frame": identity["frame"], "bandwidth": identity["bandwidth"],
                "polarization": identity["polarization"], "pair_count": len(items),
                "status": grid_error or ("SERIES_WITHHELD_PAIR_FAILURE" if good_pair_count else "NO_USABLE_PAIRS"),
                "candidate_components": 0, "pairs": pair_results,
            })
            continue

        assert hit_count is not None and valid_union is not None
        assert direction_range_sum is not None and direction_azimuth_sum is not None
        cross_pair_coherence = np.full(hit_count.shape, np.nan, dtype=np.float32)
        hit_pixels = hit_count > 0
        cross_pair_coherence[hit_pixels] = np.hypot(
            direction_range_sum[hit_pixels] / hit_count[hit_pixels],
            direction_azimuth_sum[hit_pixels] / hit_count[hit_pixels],
        )
        persistent_before_direction = hit_count >= minimum_pairs if good_pair_count >= minimum_pairs else np.zeros(hit_count.shape, dtype=bool)
        persistent = (
            persistent_before_direction
            & np.isfinite(cross_pair_coherence)
            & (cross_pair_coherence >= minimum_cross_pair_directional_coherence)
        )
        components = _component_features(
            persistent, hit_count, cross_pair_coherence,
            series_grid["transform"], series_grid["crs"], series_id,
            identity, good_pair_count, int(minimum_pairs), minimum_component_pixels,
        )
        all_features.extend(components)

        group_dir = out_dir / series_id
        group_dir.mkdir(parents=True, exist_ok=True)
        counts_out = hit_count.copy()
        counts_out[~valid_union] = np.uint16(65535)
        counts_out[~series_grid["inside_aoi"]] = np.uint16(65535)
        mask_out = persistent.astype(np.uint8)
        mask_out[~valid_union] = np.uint8(255)
        mask_out[~series_grid["inside_aoi"]] = np.uint8(255)
        counts_path = group_dir / "candidate_pair_count.tif"
        mask_path = group_dir / "persistent_candidate_mask.tif"
        coherence_path = group_dir / "cross_pair_directional_coherence.tif"
        _write_count_raster(
            counts_path, counts_out, series_grid, 65535,
            "Number of compatible GOFF pairs with an AOI-wide offset anomaly",
        )
        _write_count_raster(
            mask_path, mask_out, series_grid, 255,
            "Persistent, cross-pair direction-consistent AOI-wide candidate mask; 1=review candidate, not hazard",
        )
        _write_float_raster(
            coherence_path, cross_pair_coherence, series_grid,
            "Cross-pair resultant coherence of range/along-track anomaly directions; not 3-D motion",
        )

        series_reports.append({
            "series_id": series_id, "product_family": "GOFF",
            "processing": identity["processing"], "crid": identity["crid"],
            "track": identity["track"], "direction": "ASCENDING" if identity["direction"] == "A" else "DESCENDING",
            "frame": identity["frame"], "bandwidth": identity["bandwidth"],
            "polarization": identity["polarization"], "pair_count": good_pair_count,
            "minimum_pairs_for_persistence": minimum_pairs,
            "minimum_cross_pair_directional_coherence": minimum_cross_pair_directional_coherence,
            "aoi_grid_pixels": int(series_grid["inside_aoi"].sum()),
            "valid_union_pixels": int(valid_union.sum()),
            "pairs_with_any_candidate": sum(int(p.get("candidate_pixels") or 0) > 0 for p in pair_results),
            "persistent_pixels_before_direction_gate": int(persistent_before_direction.sum()),
            "persistent_pixels_after_direction_gate": int(persistent.sum()),
            "candidate_components": len(components),
            "status": "EXPLORATORY_RANKING_ONLY" if good_pair_count >= minimum_pairs else "INSUFFICIENT_TEMPORAL_SUPPORT",
            "candidate_count_raster": str(counts_path.relative_to(root.resolve())).replace("\\", "/"),
            "candidate_mask_raster": str(mask_path.relative_to(root.resolve())).replace("\\", "/"),
            "cross_pair_directional_coherence_raster": str(coherence_path.relative_to(root.resolve())).replace("\\", "/"),
            "pairs": pair_results,
        })

    geojson_path = out_dir / "candidates.geojson"
    geojson = {
        "type": "FeatureCollection",
        "features": all_features,
        "properties": {
            "schema_version": SCHEMA, "target_required": False,
            "interpretation": "AOI-wide exploratory GOFF offset-anomaly candidates; not confirmed displacement or hazard detections.",
        },
    }
    geojson_path.write_text(json.dumps(geojson, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    candidate_rows = [feature["properties"] for feature in all_features]
    csv_path = out_dir / "candidates.csv"
    csv_fields = [
        "candidate_id", "series_id", "product_family", "track", "direction", "frame",
        "crid", "pairs_in_series", "pairs_with_candidate", "pair_persistence_median",
        "pair_persistence_max", "pixels_approx", "area_km2_approx", "centroid_lon",
        "centroid_lat", "mean_cross_pair_directional_coherence", "interpretation",
    ]
    import csv
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in csv_fields} for row in candidate_rows)

    usable = [s for s in series_reports if s["status"] in {"EXPLORATORY_RANKING_ONLY", "INSUFFICIENT_TEMPORAL_SUPPORT"}]
    status = (
        "COMPLETED_EXPLORATORY_RANKING"
        if any(s["status"] == "EXPLORATORY_RANKING_ONLY" for s in usable)
        else ("INSUFFICIENT_TEMPORAL_SUPPORT" if usable else "NO_USABLE_GOFF_SERIES")
    )
    summary = {
        "schema_version": SCHEMA,
        "status": status,
        "purpose": "FIND_DISPLACEMENTS_AOI_WIDE",
        "target_required": False,
        "target_coordinates_used": False,
        "aoi_wkt": aoi_wkt,
        "method": {
            "family": "GOFF_ONLY", "series_grouping": ["processing", "track", "direction", "frame", "bandwidth", "polarization", "CRID"],
            "local_window_px": local_window_px, "direction_window_px": direction_window_px,
            "minimum_offset_anomaly_m_floor_m": minimum_offset_anomaly_m,
            "minimum_robust_z": minimum_robust_z,
            "minimum_directional_coherence": minimum_directional_coherence,
            "minimum_cross_pair_directional_coherence": minimum_cross_pair_directional_coherence,
            "minimum_pairs_for_persistence": minimum_pairs,
            "minimum_component_pixels": minimum_component_pixels,
            "quality": "Uses the exported reader-valid mask and the GOFF product's correlation gate. It does not recover SNR or redo raw-HDF5 processing.",
            "background_scale": "Global component-wise robust MAD after local detrending, with a 0.03 m floor; exploratory noise proxy, not a validated per-pixel detection floor.",
            "reader_floor_policy": "Per pair, min offset anomaly is max(configured absolute floor, reader detect_floor_mm_day × elapsed pair days ÷ 1000); missing reader floor falls back to configured absolute floor and is reported per pair.",
        },
        "series_count": len(series_reports),
        "series": series_reports,
        "candidate_count": len(all_features),
        "candidates_geojson": str(geojson_path.relative_to(root.resolve())).replace("\\", "/"),
        "candidates_csv": str(csv_path.relative_to(root.resolve())).replace("\\", "/"),
        "duplicate_intervals_excluded": duplicate_exclusions,
        "rejected_products": rejected,
        "warnings": [
            "This is a target-free spatial anomaly screen, not an operational landslide or glacier-collapse detector.",
            "GOFF range and along-track values are offset components, not a 3-D ground-motion vector.",
            "GUNW LOS time-series output is calculated separately; no cross-family fusion is performed.",
            "Persistence requires spatial overlap across compatible acquisition pairs and can miss motion if valid support changes.",
            "Thresholds are exploratory and have not been calibrated by held-out AOI-specific positive and null controls.",
            "A zero candidate count does not prove zero displacement or absence of hazard.",
        ],
        "outputs": {
            "candidates_geojson": str(geojson_path.relative_to(root.resolve())).replace("\\", "/"),
            "candidates_csv": str(csv_path.relative_to(root.resolve())).replace("\\", "/"),
        },
    }
    summary["output_sha256"] = {
        "candidates_geojson": sha256_file(geojson_path),
        "candidates_csv": sha256_file(csv_path),
    }
    (out_dir / "screen-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    return summary
