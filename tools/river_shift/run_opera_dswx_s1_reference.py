#!/usr/bin/env python3
"""Build and validate a conservative OPERA DSWx-S1 open-water reference for RiverShift.

NISAR GCOV remains the primary measurement. OPERA DSWx-S1 (Sentinel-1 C-band)
is an independent SAR-derived cross-sensor screen, not field truth. Only WTR
classes 0 (not water) and 1 (open water) are labelled; inundated vegetation,
masked, ambiguous and fill classes remain NoData.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlsplit

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from drive_upload_adapter import (
    DriveClient,
    DriveUploadError,
    RIVERSHIFT_STORAGE_FOLDER_NAME,
    load_drive_config,
)
from publish_sentinel2_references import _load_single_json_under
from validate_independent_reference import (
    _common_support_fraction,
    _download_verified,
    _resolve_source_manifest,
    validate as validate_independent_reference,
)

COLLECTION_SHORT_NAME = "OPERA_L3_DSWX-S1_V1"
COLLECTION_CONCEPT_ID = "C2949811996-POCLOUD"
COLLECTION_DOI = "10.5067/OPDSWS1-L3V1"
CMR_UMM_GRANULE_SEARCH_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json_v1_6_7"
CMR_UMM_ACCEPT = "application/vnd.nasa.cmr.umm_results+json; version=1.6.7"
CMR_PAGE_SIZE = 2000
PRODUCT_SPEC = "OPERA DSWx-S1A/B Product Specification v1.0.0, JPL D-108761 Rev A"
DATASET_URL = "https://podaac.jpl.nasa.gov/dataset/OPERA_L3_DSWX-S1_V1"
MAX_REFERENCE_BYTES = 250_000_000
FILL = 255
FILENAME_RE = re.compile(
    r"^OPERA_L3_DSWx-S1_T(?P<tile>[0-9]{2}[A-Z]{3})_"
    r"(?P<sensing>[0-9]{8}T[0-9]{6}Z)_"
    r"(?P<generated>[0-9]{8}T[0-9]{6}Z)_"
    r"(?P<platform>S1[AB])_(?P<pixel_spacing>[0-9]+)_"
    r"v(?P<version>[0-9]+\.[0-9]+)_B(?P<layer>[0-9]{2})_"
    r"(?P<layer_name>[A-Z0-9]+)\.tif$",
    re.IGNORECASE,
)


class OperaReferenceError(ValueError):
    """A source, format, or scientific-gate error in the OPERA reference replay."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _file_metadata(value: str) -> dict[str, Any] | None:
    name = Path(unquote(urlsplit(value).path)).name or Path(value).name
    match = FILENAME_RE.fullmatch(name)
    if not match:
        return None
    groups = match.groupdict()
    sensing_time = datetime.strptime(groups["sensing"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    generated_time = datetime.strptime(groups["generated"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return {
        "filename": name,
        "tile_id": groups["tile"].upper(),
        "sensing_time_utc": sensing_time.isoformat().replace("+00:00", "Z"),
        "observation_date": sensing_time.date().isoformat(),
        "generation_time_utc": generated_time.isoformat().replace("+00:00", "Z"),
        "platform": groups["platform"].upper(),
        "pixel_spacing_m": int(groups["pixel_spacing"]),
        "product_version": groups["version"],
        "layer_number": int(groups["layer"]),
        "layer_name": groups["layer_name"].upper(),
    }


def _cmr_umm_search(
    session: Any,
    *,
    collection_concept_id: str,
    temporal: tuple[str, str] | None = None,
    bounding_box: tuple[float, float, float, float] | None = None,
    page_size: int = CMR_PAGE_SIZE,
    fetch_all: bool = True,
) -> dict[str, Any]:
    """Query CMR's UMM JSON API directly, bypassing Earthaccess GranuleQuery defaults."""
    from math import ceil

    if not 1 <= page_size <= 2000:
        raise OperaReferenceError("CMR page_size must be between 1 and 2000.")
    params: list[tuple[str, str]] = [
        ("collection_concept_id", collection_concept_id),
        ("page_size", str(page_size)),
        ("page_num", "1"),
    ]
    if temporal is not None:
        params.append(("temporal[]", f"{temporal[0]},{temporal[1]}"))
    if bounding_box is not None:
        params.append(("bounding_box", ",".join(f"{value:.9f}".rstrip("0").rstrip(".") for value in bounding_box)))

    def fetch_page(page_num: int) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        page_params = [
            (key, str(page_num) if key == "page_num" else value)
            for key, value in params
        ]
        response = session.get(
            CMR_UMM_GRANULE_SEARCH_URL,
            params=page_params,
            headers={"Accept": CMR_UMM_ACCEPT},
            timeout=(10, 60),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise OperaReferenceError("CMR UMM JSON response was not an object.")
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise OperaReferenceError("CMR UMM JSON response has an invalid items array.")
        header_hits = response.headers.get("CMR-Hits")
        try:
            hits = int(header_hits if header_hits is not None else payload.get("hits", len(items)))
        except (TypeError, ValueError) as exc:
            raise OperaReferenceError("CMR response returned an invalid hit count.") from exc
        if hits < 0:
            raise OperaReferenceError("CMR returned a negative hit count.")
        if str(response.headers.get("CMR-Time-Out", "")).lower() == "true":
            raise OperaReferenceError(
                "CMR timed out and marked its result set incomplete; refusing partial granule inventory."
            )
        if any(not isinstance(item, dict) for item in items):
            raise OperaReferenceError("CMR UMM JSON contains a non-object granule item.")
        return items, hits, {
            "http_status": int(response.status_code),
            "content_type": response.headers.get("Content-Type"),
            "page_num": page_num,
            "page_items": len(items),
            "cmr_hits": hits,
            "cmr_search_after_present": bool(response.headers.get("CMR-Search-After")),
            "cmr_timed_out": str(response.headers.get("CMR-Time-Out", "")).lower() == "true",
        }

    first_items, hits, first_audit = fetch_page(1)
    all_items = list(first_items)
    audit_pages = [first_audit]
    if fetch_all and hits > page_size:
        total_pages = min(ceil(hits / page_size), 20)
        for page_num in range(2, total_pages + 1):
            page_items, page_hits, page_audit = fetch_page(page_num)
            if page_hits != hits:
                raise OperaReferenceError(
                    "CMR hit count changed during pagination; refusing an incomplete scene inventory."
                )
            audit_pages.append(page_audit)
            if not page_items:
                break
            all_items.extend(page_items)
        if len(all_items) < min(hits, total_pages * page_size):
            raise OperaReferenceError(
                f"CMR pagination returned {len(all_items)} of at least {min(hits, total_pages * page_size)} expected granule rows."
            )
        if hits > 20 * page_size:
            raise OperaReferenceError(
                "CMR returned more than 40,000 AOI/time granules; refusing an incomplete inventory."
            )
    return {
        "items": all_items,
        "hits": hits,
        "pages": audit_pages,
        "query": {
            "url": CMR_UMM_GRANULE_SEARCH_URL,
            "collection_concept_id": collection_concept_id,
            "temporal": list(temporal) if temporal else None,
            "bounding_box_wgs84": list(bounding_box) if bounding_box else None,
            "page_size": page_size,
            "accept": CMR_UMM_ACCEPT,
        },
    }


def _cmr_related_get_data_urls(item: dict[str, Any]) -> list[str]:
    umm = item.get("umm") or {}
    related = umm.get("RelatedUrls") or []
    if not isinstance(related, list):
        return []
    urls: list[str] = []
    for link in related:
        if not isinstance(link, dict):
            continue
        link_type = str(link.get("Type") or "").strip().upper()
        url = str(link.get("URL") or "").strip()
        if link_type == "GET DATA" and url.startswith("https://"):
            urls.append(url)
    return urls


def _granule_links(granule: Any) -> list[str]:
    # Raw UMM dictionaries come from the direct authenticated CMR query.
    if isinstance(granule, dict):
        return _cmr_related_get_data_urls(granule)
    # Compatibility for Earthaccess DataGranule objects in unit fixtures.
    try:
        links = granule.data_links(access="external")
    except Exception:
        links = []
    if not isinstance(links, (list, tuple)):
        return []
    return [str(link) for link in links if isinstance(link, str) and str(link).startswith("https://") ]


def _granule_umm(granule: Any) -> dict[str, Any]:
    try:
        value = granule.get("umm", {})
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _discover_records(
    *,
    aoi_wkt: str,
    requested_date: date,
    maximum_offset_days: int,
    discovery_window_days: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import earthaccess
    from shapely import wkt as shapely_wkt

    geometry = shapely_wkt.loads(aoi_wkt)
    if geometry.is_empty or not geometry.is_valid:
        raise OperaReferenceError("The retained RiverShift AOI WKT is empty or invalid.")
    west, south, east, north = geometry.bounds
    bbox = (west, south, east, north)
    search_window_days = maximum_offset_days if discovery_window_days is None else discovery_window_days
    if not maximum_offset_days <= search_window_days <= 30:
        raise OperaReferenceError(
            "discovery_window_days must be between the strict score gate and 30 days."
        )
    start = requested_date - timedelta(days=search_window_days)
    end = requested_date + timedelta(days=search_window_days)
    temporal = (
        f"{start.isoformat()}T00:00:00Z",
        f"{end.isoformat()}T23:59:59Z",
    )
    print(
        "RIVERSHIFT_OPERA_CMR_QUERY="
        + json.dumps({
            "collection_doi": COLLECTION_DOI,
            "collection_concept_id": COLLECTION_CONCEPT_ID,
            "collection_short_name": COLLECTION_SHORT_NAME,
            "query_method": "direct authenticated CMR UMM JSON; collection_concept_id",
            "temporal_start_utc": temporal[0],
            "temporal_end_utc": temporal[1],
            "bounding_box": [west, south, east, north],
            "strict_score_maximum_date_offset_days": maximum_offset_days,
            "discovery_window_days": search_window_days,
        }, sort_keys=True),
        flush=True,
    )
    earthaccess.login(strategy="environment")
    session = earthaccess.get_requests_https_session()
    # Retrieve the small spatial inventory for the AOI first, then apply the
    # discovery date window locally from each WTR filename's sensing timestamp.
    # CMR's server-side temporal+bounding-box intersection returned zero even
    # though the independent AOI-only inventory contains 307 granules. Keeping
    # the spatial inventory avoids losing nearby scenes to CMR intersection
    # semantics while still restricting all candidate selection to this AOI.
    result = _cmr_umm_search(
        session,
        collection_concept_id=COLLECTION_CONCEPT_ID,
        bounding_box=bbox,
    )
    items = result["items"]
    diagnostics: dict[str, Any] = {
        "aoi_inventory_query": {
            "hits": result["hits"],
            "returned_items": len(items),
            "pages": result["pages"],
            "query": result["query"],
            "server_side_temporal_filter_applied": False,
        }
    }
    # Zero intersection can be either temporal coverage or spatial coverage.
    # Probe each dimension separately (1 metadata row per probe, no downloads).
    if result["hits"] == 0:
        date_probe = _cmr_umm_search(
            session,
            collection_concept_id=COLLECTION_CONCEPT_ID,
            temporal=temporal,
            page_size=1,
            fetch_all=False,
        )
        aoi_probe = _cmr_umm_search(
            session,
            collection_concept_id=COLLECTION_CONCEPT_ID,
            bounding_box=bbox,
            page_size=1,
            fetch_all=False,
        )
        collection_probe = _cmr_umm_search(
            session,
            collection_concept_id=COLLECTION_CONCEPT_ID,
            page_size=1,
            fetch_all=False,
        )
        diagnostics["zero_result_probes"] = {
            "collection_and_date": {
                "hits": date_probe["hits"],
                "one_sample_returned": len(date_probe["items"]),
                "query": date_probe["query"],
            },
            "collection_and_aoi": {
                "hits": aoi_probe["hits"],
                "one_sample_returned": len(aoi_probe["items"]),
                "query": aoi_probe["query"],
            },
            "collection_only": {
                "hits": collection_probe["hits"],
                "one_sample_returned": len(collection_probe["items"]),
                "query": collection_probe["query"],
            },
        }
    print(
        "RIVERSHIFT_OPERA_CMR_RESULT_COUNT="
        + json.dumps({
            "granules_returned": result["hits"],
            "items_loaded": len(items),
            "cmr_diagnostics": diagnostics,
        }, sort_keys=True),
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    without_get_data = 0
    non_wtr = 0
    outside_discovery_window = 0
    for item in items:
        umm = item.get("umm") or {}
        meta = item.get("meta") or {}
        granule_ur = str(umm.get("GranuleUR") or "")
        links = _granule_links(item)
        candidates = [granule_ur, *links]
        wtr_meta = None
        wtr_url = None
        for candidate in candidates:
            parsed = _file_metadata(candidate)
            if parsed and parsed["layer_name"] == "WTR":
                wtr_meta = parsed
                if candidate in links:
                    wtr_url = candidate
                break
        if not wtr_meta:
            non_wtr += 1
            continue
        observation_date = date.fromisoformat(str(wtr_meta["observation_date"]))
        if abs((observation_date - requested_date).days) > search_window_days:
            outside_discovery_window += 1
            continue
        if not wtr_url:
            # Do not advertise a reference that cannot be fetched as an
            # authenticated HTTPS GET DATA link outside AWS us-west-2.
            for link in links:
                parsed = _file_metadata(link)
                if parsed and parsed["filename"] == wtr_meta["filename"]:
                    wtr_url = link
                    break
        if not wtr_url:
            without_get_data += 1
            continue
        concept_id = str(meta.get("concept-id") or "")
        key = (wtr_meta["filename"], concept_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            **wtr_meta,
            "granule_ur": granule_ur,
            "direct_links": links,
            "wtr_download_url": wtr_url,
            "concept_id": concept_id,
        })
    query = {
        "collection_short_name": COLLECTION_SHORT_NAME,
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "collection_doi": COLLECTION_DOI,
        "collection_query_method": "direct authenticated CMR UMM JSON by collection_concept_id",
        "cloud_hosted_filter_applied": False,
        "downloadable_filter_applied": False,
        "bounding_box_wgs84": [west, south, east, north],
        "local_temporal_filter_utc": list(temporal),
        "cmr_temporal_filter_applied": False,
        "discovery_window_days": search_window_days,
        "strict_score_maximum_date_offset_days": maximum_offset_days,
        "requested_observation_date": requested_date.isoformat(),
        "granules_returned_by_cmr": result["hits"],
        "umm_items_loaded": len(items),
        "wtr_records_parsed": len(rows),
        "non_wtr_records": non_wtr,
        "records_outside_local_discovery_window": outside_discovery_window,
        "wtr_records_missing_https_get_data": without_get_data,
        "cmr_query": result["query"],
        "cmr_pages": result["pages"],
        "cmr_diagnostics": diagnostics,
    }
    return rows, query

def _select_scene_records(
    records: list[dict[str, Any]],
    requested_date: date,
) -> tuple[list[dict[str, Any]], str | None]:
    if not records:
        return [], None
    dates = sorted({
        date.fromisoformat(str(row["observation_date"]))
        for row in records
    })
    chosen_date = min(
        dates,
        key=lambda value: (abs((value - requested_date).days), value),
    )
    same_date = [row for row in records if row["observation_date"] == chosen_date.isoformat()]
    # Keep one processing generation per MGRS tile. Prefer the highest product
    # version, then latest processing timestamp, with filename as deterministic tie-break.
    chosen_by_tile: dict[str, dict[str, Any]] = {}
    for row in same_date:
        tile = str(row["tile_id"])
        current = chosen_by_tile.get(tile)
        rank = (tuple(int(v) for v in str(row["product_version"]).split(".")),
                str(row["generation_time_utc"]), str(row["filename"]))
        if current is None:
            chosen_by_tile[tile] = row
            continue
        current_rank = (
            tuple(int(v) for v in str(current["product_version"]).split(".")),
            str(current["generation_time_utc"]),
            str(current["filename"]),
        )
        if rank > current_rank:
            chosen_by_tile[tile] = row
    selected = sorted(chosen_by_tile.values(), key=lambda row: str(row["tile_id"]))
    return selected, chosen_date.isoformat()


def _download_selected(selected: list[dict[str, Any]], destination: Path) -> list[Path]:
    import earthaccess

    destination.mkdir(parents=True, exist_ok=True)
    urls = [str(row.get("wtr_download_url") or "") for row in selected]
    if any(not url.startswith("https://") for url in urls):
        raise OperaReferenceError("Every selected OPERA WTR granule requires an authenticated HTTPS GET DATA URL.")
    print(
        "RIVERSHIFT_OPERA_DOWNLOAD_START="
        + json.dumps([
            {"filename": row["filename"], "concept_id": row.get("concept_id")}
            for row in selected
        ], sort_keys=True),
        flush=True,
    )
    # Earthaccess accepts HTTP URL lists when the provider is specified. This
    # also keeps GitHub-hosted runners outside AWS us-west-2 on HTTPS access.
    earthaccess.download(urls, local_path=str(destination), provider="POCLOUD", threads=4)
    available = [path for path in destination.rglob("*") if path.is_file()]
    wanted = {row["filename"] for row in selected}
    found: dict[str, Path] = {}
    for path in available:
        if path.name in wanted:
            found[path.name] = path
    missing = sorted(wanted - set(found))
    if missing:
        raise OperaReferenceError(
            "The NASA Earthdata download completed without all selected WTR GeoTIFFs: "
            + ", ".join(missing[:8])
        )
    return [found[row["filename"]] for row in selected]


def _canonical_metadata_value(value: str | None, *, numeric: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if numeric:
        try:
            return str(int(float(text)))
        except ValueError:
            pass
    return text.upper()


def _classify_wtr(values: np.ndarray, source_valid: np.ndarray | None = None) -> np.ndarray:
    """Retain only OPERA WTR class 0 (not water) and class 1 (open water)."""
    array = np.asarray(values)
    if array.ndim != 2:
        raise OperaReferenceError("OPERA WTR source must be a two-dimensional single-band raster.")
    if source_valid is None:
        valid_mask = np.ones(array.shape, dtype=bool)
    else:
        valid_mask = np.asarray(source_valid, dtype=bool)
        if valid_mask.shape != array.shape:
            raise OperaReferenceError("OPERA WTR data and validity mask must have identical shapes.")
    result = np.full(array.shape, FILL, dtype=np.uint8)
    keep = valid_mask & np.isin(array, [0, 1])
    result[keep] = array[keep].astype(np.uint8, copy=False)
    return result


def _build_reference_on_nisar_grid(
    *,
    prediction_path: Path,
    wtr_paths: list[Path],
    selected_records: list[dict[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    with rasterio.open(prediction_path) as pred:
        if pred.count != 1 or pred.crs is None or not pred.crs.is_projected:
            raise OperaReferenceError("Retained NISAR water prediction must be a single-band projected raster.")
        pred_values = pred.read(1)
        pred_valid = (pred.read_masks(1) > 0) & np.isin(pred_values, [0, 1])
        if not pred_valid.any():
            raise OperaReferenceError("Retained NISAR water mask has no valid binary pixels.")
        profile = pred.profile.copy()
        width, height = pred.width, pred.height
        transform, crs = pred.transform, pred.crs
        output = np.full((height, width), FILL, dtype=np.uint8)
    conflict_mask = np.zeros((height, width), dtype=bool)

    tile_audits: list[dict[str, Any]] = []
    shared_geometry: dict[str, str] | None = None
    for path, metadata in zip(wtr_paths, selected_records, strict=True):
        with rasterio.open(path) as src:
            if src.count != 1 or src.crs is None:
                raise OperaReferenceError(f"Invalid OPERA WTR GeoTIFF metadata: {path.name}")
            if src.dtypes[0] != "uint8":
                raise OperaReferenceError(f"OPERA WTR must be UInt8: {path.name}")
            source_tags = {str(key).upper(): str(value).strip() for key, value in src.tags().items()}
            # V1 GeoTIFF metadata uses SPACECRAFT_NAME, ORBIT_PASS_DIRECTION
            # and TRACK_NUMBER. Some exports expose the RTC-prefixed aliases;
            # normalize both documented forms before comparing tile geometry.
            geometry_fields = {
                "SPACECRAFT_NAME": _canonical_metadata_value(source_tags.get("SPACECRAFT_NAME")),
                "ORBIT_PASS_DIRECTION": _canonical_metadata_value(
                    source_tags.get("ORBIT_PASS_DIRECTION")
                    or source_tags.get("RTC_ORBIT_PASS_DIRECTION")
                ),
                "TRACK_NUMBER": _canonical_metadata_value(
                    source_tags.get("TRACK_NUMBER") or source_tags.get("RTC_TRACK_NUMBER"),
                    numeric=True,
                ),
                "ABSOLUTE_ORBIT_NUMBER": _canonical_metadata_value(
                    source_tags.get("ABSOLUTE_ORBIT_NUMBER")
                    or source_tags.get("RTC_ABSOLUTE_ORBIT_NUMBER"),
                    numeric=True,
                ),
            }
            missing_geometry = [key for key, value in geometry_fields.items() if not value]
            if missing_geometry:
                raise OperaReferenceError(
                    f"Required OPERA source geometry metadata is missing from {path.name}: "
                    + ", ".join(missing_geometry)
                )
            if shared_geometry is None:
                shared_geometry = {key: str(value) for key, value in geometry_fields.items()}
            elif geometry_fields != shared_geometry:
                raise OperaReferenceError(
                    "Adjacent OPERA WTR tiles are not from the same spacecraft, orbit direction "
                    "and relative track; refusing to mosaic incomparable acquisitions. "
                    f"first={shared_geometry}; current={geometry_fields}."
                )
            raw = src.read(1)
            valid = src.read_masks(1) > 0
            classes = set(int(value) for value in np.unique(raw))
            if not classes.issubset({0, 1, 3, 250, 251, 255}):
                raise OperaReferenceError(
                    f"Unexpected OPERA WTR classes in {path.name}: {sorted(classes)}"
                )
            classified = _classify_wtr(raw, valid)
            warped = np.full((height, width), FILL, dtype=np.uint8)
            reproject(
                source=classified,
                destination=warped,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=FILL,
                dst_transform=transform,
                dst_crs=crs,
                dst_nodata=FILL,
                resampling=Resampling.nearest,
                init_dest_nodata=True,
            )
            current_valid = (output != FILL) & (~conflict_mask)
            tile_valid = warped != FILL
            overlap_conflict = current_valid & tile_valid & (output != warped)
            conflict_mask |= overlap_conflict
            fill = tile_valid & (~current_valid) & (~conflict_mask)
            output[fill] = warped[fill]
            # Conflicting tile labels in overlapping buffers are deliberately
            # excluded rather than resolved by arbitrary tile order. Once
            # conflicted, a pixel stays NoData even if a third tile overlaps it.
            output[conflict_mask] = FILL
            tile_audits.append({
                "filename": path.name,
                "source_file_bytes": path.stat().st_size,
                "source_file_sha256": _sha256(path),
                "tile_id": metadata["tile_id"],
                "source_crs": src.crs.to_string(),
                "source_geometry": geometry_fields,
                "absolute_orbit_number": geometry_fields["ABSOLUTE_ORBIT_NUMBER"],
                "sensing_start_time": (
                    source_tags.get("RTC_SENSING_START_TIME")
                    or source_tags.get("SENSING_START")
                ),
                "sensing_end_time": (
                    source_tags.get("RTC_SENSING_END_TIME")
                    or source_tags.get("SENSING_END")
                ),
                "polarization": source_tags.get("POLARIZATION"),
                "source_width": src.width,
                "source_height": src.height,
                "source_transform": list(src.transform)[:6],
                "source_pixel_spacing_m": [abs(float(src.transform.a)), abs(float(src.transform.e))],
                "source_wtr_class_counts": {
                    str(value): int(np.count_nonzero(raw == value))
                    for value in sorted(classes)
                },
                "mapped_open_water_pixels": int(np.count_nonzero(classified == 1)),
                "mapped_non_water_pixels": int(np.count_nonzero(classified == 0)),
                "excluded_source_pixels": int(np.count_nonzero(classified == FILL)),
                "overlap_conflict_pixels_on_target_grid": int(np.count_nonzero(overlap_conflict)),
            })

    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=FILL,
        compress="deflate",
        tiled=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(output, 1)
        dst.update_tags(
            SOURCE_PROVIDER="NASA/JPL PO.DAAC OPERA",
            COLLECTION_SHORT_NAME=COLLECTION_SHORT_NAME,
            COLLECTION_CONCEPT_ID=COLLECTION_CONCEPT_ID,
            COLLECTION_DOI=COLLECTION_DOI,
            PRODUCT_VERSION="1.0",
            INPUT_SENSOR="Sentinel-1 C-band SAR",
            SOURCE_LAYER="WTR",
            CLASS_1="open water (OPERA WTR class 1)",
            CLASS_0="not water (OPERA WTR class 0)",
            NODATA_CLASSES="3=inundated vegetation;250=HAND masked;251=layover/shadow;255=fill/no data;all other classes excluded",
            ALIGNMENT="Nearest-neighbour categorical reprojection to the retained NISAR prediction grid",
            OVERLAP_POLICY="Conflicting overlapping-tile class labels are marked NoData",
            INTERPRETATION="Independent SAR-derived cross-sensor screening only; not field truth",
            LIMITATION="30 m product; minimum mapping capability and narrow-channel limitations apply; use open-water agreement only",
            OPERA_SCENE_DATE=str(selected_records[0]["observation_date"]),
            OPERA_TILE_IDS=",".join(str(row["tile_id"]) for row in selected_records),
            OPERA_SOURCE_FILES=",".join(str(row["filename"]) for row in selected_records),
        )

    valid_reference = output != FILL
    common = pred_valid & valid_reference
    report = {
        "file": output_path.name,
        "sha256": _sha256(output_path),
        "bytes": output_path.stat().st_size,
        "crs": crs.to_string(),
        "width": width,
        "height": height,
        "transform": list(transform)[:6],
        "pixel_area_m2": abs(float(transform.a * transform.e - transform.b * transform.d)),
        "target_prediction_valid_pixels": int(pred_valid.sum()),
        "reference_valid_pixels": int(valid_reference.sum()),
        "common_valid_pixels": int(common.sum()),
        "common_support_fraction": float(common.sum() / pred_valid.sum()),
        "water_pixels": int(np.count_nonzero(output == 1)),
        "non_water_pixels": int(np.count_nonzero(output == 0)),
        "nodata_pixels": int(np.count_nonzero(output == FILL)),
        "tile_audits": tile_audits,
    }
    return report


def _upload_checked(client: DriveClient, path: Path, folder_id: str, stage: str) -> dict[str, Any]:
    print(f"RIVERSHIFT_OPERA_DRIVE_STAGE={stage}:START file={path.name}", flush=True)
    receipt = client.upload_file(path, folder_id)
    if (
        receipt.get("status") != "PASS"
        or receipt.get("remote_md5") != receipt.get("md5")
        or receipt.get("bytes") != path.stat().st_size
    ):
        raise DriveUploadError(f"Google Drive remote checksum/size verification failed for {path.name}.")
    print(
        f"RIVERSHIFT_OPERA_DRIVE_STAGE={stage}:PASS "
        f"bytes={receipt.get('bytes')} remote_checksum=PASS",
        flush=True,
    )
    return receipt


def _folder_layout(source_job_id: str, observation_date: str) -> tuple[DriveClient, str, str]:
    client = DriveClient(load_drive_config())
    client.verify_authenticated_account()
    root = client.find_or_create_folder(RIVERSHIFT_STORAGE_FOLDER_NAME, client.config.parent_folder_id)
    client.require_private_folder(root)
    job = client.find_or_create_folder(source_job_id, root)
    client.require_private_folder(job)
    validation_root = client.find_or_create_folder("opera-dswx-s1-reference", job)
    client.require_private_folder(validation_root)
    dated = client.find_or_create_folder(observation_date, validation_root)
    client.require_private_folder(dated)
    run_id = re.sub(r"[^0-9]", "", os.environ.get("GITHUB_RUN_ID", "")) or "local"
    attempt = re.sub(r"[^0-9]", "", os.environ.get("GITHUB_RUN_ATTEMPT", "")) or "1"
    run_folder = client.find_or_create_folder(f"run-{run_id}-attempt-{attempt}", dated)
    client.require_private_folder(run_folder)
    return client, job, run_folder


def run_pipeline(
    *,
    prepared_dir: Path,
    api_base_url: str,
    output_dir: Path,
    maximum_date_offset_days: int = 3,
    discovery_window_days: int = 30,
    minimum_common_support_fraction: float = 0.80,
    block_size_pixels: int = 64,
    bootstrap_replicates: int = 500,
) -> dict[str, Any]:
    if not 0 <= maximum_date_offset_days <= 30:
        raise OperaReferenceError("maximum_date_offset_days must be between 0 and 30.")
    if not maximum_date_offset_days <= discovery_window_days <= 30:
        raise OperaReferenceError(
            "discovery_window_days must be at least the strict date gate and at most 30 days."
        )
    if not 0.5 <= minimum_common_support_fraction <= 1:
        raise OperaReferenceError("minimum_common_support_fraction must be between 0.5 and 1.")
    prepared = _load_single_json_under(prepared_dir, "prepared.json")
    source_job_id = str(prepared.get("job_id") or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", source_job_id):
        raise OperaReferenceError("Prepared RiverShift manifest has no valid source job UUID.")
    requested_date_text = str(
        prepared.get("analysis_window", {}).get("event_proximal_observation")
        or prepared.get("selection", {}).get("event_window", {}).get("event_proximal_observation")
        or ""
    )
    requested_date = date.fromisoformat(requested_date_text)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"RIVERSHIFT_OPERA_SOURCE_JOB_ID={source_job_id}", flush=True)
    print(f"RIVERSHIFT_OPERA_TARGET_NISAR_DATE={requested_date.isoformat()}", flush=True)

    target_manifest = _resolve_source_manifest(source_job_id, api_base_url)
    prediction_item = target_manifest["prediction"]
    prediction_path = work_dir / "during_water_mask.tif"
    _download_verified(prediction_item, prediction_path)
    records, query = _discover_records(
        aoi_wkt=str(prepared.get("request", {}).get("aoi_wkt")
                    or prepared.get("selection", {}).get("aoi_wkt")
                    or ""),
        requested_date=requested_date,
        maximum_offset_days=maximum_date_offset_days,
        discovery_window_days=discovery_window_days,
    )
    selected, selected_date_text = _select_scene_records(records, requested_date)
    report_path = output_dir / "opera_dswx_s1_reference_report.json"
    validation_path = output_dir / "opera_dswx_s1_independent_validation.json"
    reference_path = output_dir / "reference-opera-dswx-s1-water.tif"

    if not selected:
        report = {
            "schema_version": 1,
            "status": "NO_MATCH_NO_SCORE",
            "source_job_id": source_job_id,
            "source_github_run_id": target_manifest.get("github_run_id"),
            "requested_nisar_observation_date": requested_date.isoformat(),
            "query": query,
            "discovery_window_days": discovery_window_days,
            "strict_score_maximum_date_offset_days": maximum_date_offset_days,
            "selected_observation_date": None,
            "selected_granules": [],
            "reference": None,
            "validation": None,
            "quality": {
                "release_status": "PROVISIONAL",
                "independence_verified": False,
                "review_required": True,
                "interpretation": "NO_ELIGIBLE_OPERA_DSWX_S1_SCENE_WITHIN_TEMPORAL_GATE",
            },
            "limitations": [
                (
                    "No OPERA DSWx-S1 WTR granule was found within the "
                    f"{discovery_window_days}-day discovery window."
                ),
                (
                    "No metrics were calculated; the strict "
                    f"±{maximum_date_offset_days}-day scoring gate was not relaxed."
                ),
            ],
        }
        _write_json(report_path, report)
        status = "NO_MATCH_NO_SCORE"
    else:
        selected_date = date.fromisoformat(str(selected_date_text))
        offset = abs((selected_date - requested_date).days)
        wtr_paths = _download_selected(selected, work_dir / "opera-download")
        reference_summary = _build_reference_on_nisar_grid(
            prediction_path=prediction_path,
            wtr_paths=wtr_paths,
            selected_records=selected,
            output_path=reference_path,
        )
        support = float(reference_summary["common_support_fraction"])
        score_block_reason = None
        if offset > maximum_date_offset_days:
            score_block_reason = "REFERENCE_TEMPORAL_OFFSET_EXCEEDS_GATE"
        elif support < minimum_common_support_fraction:
            score_block_reason = "INSUFFICIENT_REFERENCE_SUPPORT"
        # Retain the source-derived candidate privately even when the common
        # support gate blocks metrics. A no-score reference is still useful QA evidence.
        drive, job_folder, upload_folder = _folder_layout(source_job_id, selected_date.isoformat())
        reference_upload = _upload_checked(
            drive, reference_path, upload_folder, "upload_opera_reference_geotiff"
        )
        report = {
            "schema_version": 1,
            "status": "CANDIDATE_REFERENCE_READY" if score_block_reason is None else "BLOCKED_NO_SCORE",
            "source_job_id": source_job_id,
            "source_github_run_id": target_manifest.get("github_run_id"),
            "requested_nisar_observation_date": requested_date.isoformat(),
            "query": query,
            "discovery_window_days": discovery_window_days,
            "strict_score_maximum_date_offset_days": maximum_date_offset_days,
            "selected_observation_date": selected_date.isoformat(),
            "date_offset_days": offset,
            "product_specification": PRODUCT_SPEC,
            "dataset_url": DATASET_URL,
            "selected_granules": [
                {key: value for key, value in row.items() if key not in {"granule", "direct_links"}}
                for row in selected
            ],
            "reference": reference_summary,
            "validation": {
                "status": "PENDING" if score_block_reason is None else score_block_reason,
                "minimum_common_support_fraction": minimum_common_support_fraction,
                "observed_common_support_fraction": support,
            },
            "quality": {
                "release_status": "PROVISIONAL",
                "independence_verified": False,
                "review_required": True,
                "interpretation": "CROSS_SENSOR_SAR_OPEN_WATER_AGREEMENT_ONLY_NOT_GROUND_TRUTH",
            },
            "limitations": [
                "NISAR GCOV L-band is the primary measurement; OPERA DSWx-S1 is derived from Sentinel-1 C-band and is an independent sensor/product cross-check, not field truth.",
                "Only OPERA WTR class 0 (not water) and class 1 (open water) are labelled. Class 3 inundated vegetation and masked/ambiguous/fill classes remain NoData.",
                "The 30 m OPERA DSWx-S1 product is not suitable for validating narrow channels or small bankline displacement; its mapping capability has a minimum detectable feature scale.",
                "Agreement on water/non-water does not validate erosion/deposition cause, signed bankline migration, sediment volume, water depth or flood causality.",
                "The WTR layer includes ancillary land-cover/HAND masking; class 0 may reflect mapped non-water within those masks. Reference suitability requires a reviewer.",
                "NISAR and Sentinel-1 acquisitions can differ in time, orbit, incidence angle, and hydrological stage despite passing the date gate.",
            ],
        }
        report["private_storage"] = {
                "status": "PASS",
                "provider": "Google Drive",
                "folder_path": "RiverShift/<job-id>/opera-dswx-s1-reference/<observation-date>/run-<workflow-run>-attempt-<attempt>",
                "privacy_verified": True,
                "public_permissions_created": False,
                "reference_upload": {
                    "name": reference_upload.get("name"),
                    "bytes": reference_upload.get("bytes"),
                    "md5": reference_upload.get("md5"),
                    "remote_md5": reference_upload.get("remote_md5"),
                    "status": reference_upload.get("status"),
                },
            }
        if score_block_reason is None:
            args = argparse.Namespace(
                source_job_id=source_job_id,
                api_base_url=api_base_url,
                reference_drive_file_id=reference_upload["drive_file_id"],
                reference_source=(
                    "NASA/JPL OPERA DSWx-S1 Version 1 via PO.DAAC; "
                    "Sentinel-1 C-band SAR derived WTR classification"
                ),
                reference_date=selected_date.isoformat(),
                reference_method=(
                    "OPERA DSWx-S1 V1 WTR class 1=open water and class 0=not water; "
                    "classes 3=inundated vegetation, 250=HAND masked, 251=layover/shadow and 255=fill are NoData; "
                    "undocumented source classes are rejected instead of being re-labelled; "
                    "same-date tile revisions deduplicated by highest product version "
                    "then latest generation timestamp; nearest-neighbour categorical alignment"
                ),
                maximum_date_offset_days=maximum_date_offset_days,
                minimum_common_support_fraction=minimum_common_support_fraction,
                block_size_pixels=block_size_pixels,
                bootstrap_replicates=bootstrap_replicates,
                random_seed=42,
                work_dir=work_dir / "validation",
                output=validation_path,
            )
            result = validate_independent_reference(args)
            report["validation"] = {
                "status": result.get("quality", {}).get("status"),
                "release_status": result.get("quality", {}).get("release_status"),
                "reference_date": selected_date.isoformat(),
                "target_observation_date": (result.get("reference") or {}).get("target_observation_date"),
                "temporal_offset_days": (result.get("reference") or {}).get("temporal_offset_days"),
                "common_support_fraction": (result.get("reference") or {}).get("common_support_fraction"),
                "metrics": result.get("metrics"),
                "confusion_matrix": result.get("confusion_matrix"),
                "report_file": validation_path.name,
                "report_sha256": _sha256(validation_path),
                "independence_verified": False,
            }
            report["status"] = "METRICS_COMPUTED_REVIEW_REQUIRED"
            report["quality"]["interpretation"] = "CROSS_SENSOR_SAR_OPEN_WATER_AGREEMENT_ONLY_NOT_GROUND_TRUTH"
            validation_upload = _upload_checked(
                drive, validation_path, upload_folder, "upload_opera_validation_report"
            )
            report["private_storage"]["validation_report"] = {
                "name": validation_upload.get("name"),
                "bytes": validation_upload.get("bytes"),
                "status": validation_upload.get("status"),
            }
        _write_json(report_path, report)
        if score_block_reason is not None:
            status = "BLOCKED_NO_SCORE"
        else:
            status = "METRICS_COMPUTED_REVIEW_REQUIRED"

    if "drive" not in locals():
        drive, job_folder, upload_folder = _folder_layout(
            source_job_id, selected_date_text or requested_date.isoformat()
        )
    report_upload = _upload_checked(drive, report_path, upload_folder, "upload_opera_reference_report")
    status_payload = {
        "schema_version": 1,
        "status": status,
        "source_job_id": source_job_id,
        "source_github_run_id": target_manifest.get("github_run_id"),
        "requested_nisar_observation_date": requested_date.isoformat(),
        "selected_opera_observation_date": selected_date_text,
        "common_support_fraction": (
            (report.get("reference") or {}).get("common_support_fraction")
            if report.get("reference") else None
        ),
        "release_status": "PROVISIONAL",
        "independence_verified": False,
        "review_required": True,
        "private_storage_path": "RiverShift/<job-id>/opera-dswx-s1-reference/<observation-date>/run-<workflow-run>-attempt-<attempt>",
        "report_upload": {
            "status": report_upload.get("status"),
            "name": report_upload.get("name"),
            "bytes": report_upload.get("bytes"),
        },
        "notes": [
            "A computed cross-sensor score is not a field-validated accuracy estimate.",
            "Do not interpret C-band/L-band disagreement as an error by either sensor without reviewing acquisition geometry, vegetation, hydrological stage and class masks.",
            "Morphology and bankline change remain outside this water-mask validation.",
        ],
    }
    status_path = output_dir / "opera_dswx_s1_validation_status.json"
    _write_json(status_path, status_payload)
    status_upload = _upload_checked(drive, status_path, upload_folder, "upload_opera_validation_status")
    status_payload["status_upload"] = {
        "status": status_upload.get("status"),
        "name": status_upload.get("name"),
        "bytes": status_upload.get("bytes"),
    }
    receipt_payload = {
        **status_payload,
        "private_drive_ids": {
            "job_folder_id": job_folder,
            "validation_folder_id": upload_folder,
            "reference_file_id": (
                reference_upload["drive_file_id"]
                if "reference_upload" in locals() else None
            ),
            "validation_report_file_id": (
                validation_upload["drive_file_id"]
                if "validation_upload" in locals() else None
            ),
            "report_file_id": report_upload["drive_file_id"],
            "status_file_id": status_upload["drive_file_id"],
        },
    }
    receipt_path = output_dir / "opera_dswx_s1_drive_receipt.private.json"
    _write_json(receipt_path, receipt_payload)
    _upload_checked(drive, receipt_path, upload_folder, "upload_private_drive_receipt")
    _write_json(report_path, report)
    print(f"RIVERSHIFT_OPERA_REFERENCE_STATUS={status}", flush=True)
    print("RIVERSHIFT_OPERA_RELEASE_STATUS=PROVISIONAL", flush=True)
    print("RIVERSHIFT_OPERA_DRIVE_UPLOAD=PASS", flush=True)
    print("RIVERSHIFT_OPERA_REFERENCE_PATH=" + status_payload["private_storage_path"], flush=True)
    print("RIVERSHIFT_OPERA_STATUS_REPORT=" + str(status_path), flush=True)
    return status_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-dir", required=True, type=Path)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--maximum-date-offset-days", type=int, default=3)
    parser.add_argument(
        "--discovery-window-days",
        type=int,
        default=14,
        help="Search window for the nearest OPERA scene; does not change the strict scoring date gate.",
    )
    parser.add_argument("--minimum-common-support-fraction", type=float, default=0.80)
    parser.add_argument("--block-size-pixels", type=int, default=64)
    parser.add_argument("--bootstrap-replicates", type=int, default=500)
    args = parser.parse_args()
    try:
        run_pipeline(
            prepared_dir=args.prepared_dir,
            api_base_url=args.api_base_url,
            output_dir=args.output_dir,
            maximum_date_offset_days=args.maximum_date_offset_days,
            discovery_window_days=args.discovery_window_days,
            minimum_common_support_fraction=args.minimum_common_support_fraction,
            block_size_pixels=args.block_size_pixels,
            bootstrap_replicates=args.bootstrap_replicates,
        )
        return 0
    except (DriveUploadError, OSError, ValueError, RuntimeError) as exc:
        print(
            f"RIVERSHIFT_OPERA_REFERENCE_PIPELINE=FAIL "
            f"error_type={type(exc).__name__} detail={str(exc)[:700]}",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
