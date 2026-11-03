#!/usr/bin/env python3
"""Discover NISAR GCOV products via official NASA CMR collection short names."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

CMR_SEARCH_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json_v1_6_7"
CMR_ACCEPT = "application/vnd.nasa.cmr.umm_results+json; version=1.6.7"
MATURITY_PATTERN = re.compile(r"NISAR_L2_GCOV_(BETA|PROVISIONAL)_V1", re.IGNORECASE)


def validate_aoi(value: str) -> str:
    geometry = shapely_wkt.loads(value)
    if not isinstance(geometry, Polygon) or geometry.is_empty or not geometry.is_valid:
        raise ValueError("AOI must be one valid, non-empty WGS84 POLYGON.")
    if geometry.area <= 0:
        raise ValueError("AOI polygon must have positive area.")
    return orient(geometry, sign=1.0).wkt


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = payload.get("results") or payload.get("features") or payload.get("items") or []
    else:
        candidates = []

    rows = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties")
        row = dict(properties) if isinstance(properties, dict) else dict(item)
        for key in ("geometry", "id", "type"):
            if key in item and key not in row:
                row[key] = item[key]
        rows.append(row)
    return rows


def first_string(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def detect_maturity(url: str | None, row: dict[str, Any]) -> str:
    for key in ("dataMaturity", "maturity"):
        declared = row.get(key)
        if isinstance(declared, str) and declared.strip().upper() in {"BETA", "PROVISIONAL"}:
            return declared.strip().upper()

    values = [url or ""]
    values.extend(str(row.get(key, "")) for key in (
        "granuleName", "fileName", "productName", "collectionName", "collection", "shortName",
    ))
    for value in values:
        match = MATURITY_PATTERN.search(value)
        if match:
            return match.group(1).upper()
    return "UNKNOWN"


def parse_granule_metadata(name: str) -> dict[str, str | None]:
    """Parse the official 18-token NISAR single-acquisition GCOV filename."""
    base_name = name.removesuffix(".h5")
    parts = base_name.split("_")
    if (
        len(parts) != 18
        or parts[0] != "NISAR"
        or parts[1] != "L2"
        or parts[2] not in {"PR", "UR", "OD"}
        or parts[3] != "GCOV"
        or parts[6] not in {"A", "D"}
        or parts[15] not in {"F", "P"}
    ):
        raise ValueError(f"Not a supported NISAR L2 GCOV granule name: {name}")

    try:
        start = datetime.strptime(parts[11], "%Y%m%dT%H%M%S")
        end = datetime.strptime(parts[12], "%Y%m%dT%H%M%S")
    except ValueError:
        raise ValueError(f"Invalid acquisition timestamp in GCOV granule name: {name}") from None
    if end < start:
        raise ValueError(f"GCOV acquisition end precedes acquisition start: {name}")

    return {
        "processing_type": parts[2],
        "cycle": parts[4],
        "relative_orbit": parts[5],
        "orbit_direction": parts[6],
        "frame": parts[7],
        "bandwidth_mode": parts[8],
        "polarization_code": parts[9],
        "acquisition_start_utc": parts[11],
        "acquisition_end_utc": parts[12],
        "crid": parts[13],
        "orbit_accuracy": parts[14],
        "frame_coverage": "FULL" if parts[15] == "F" else "PARTIAL",
        "science_data_system": parts[16],
        "product_counter": parts[17],
    }


def normalize_product(row: dict[str, Any]) -> dict[str, Any] | None:
    name = first_string(row, ("granuleName", "fileName", "sceneName", "fileID", "productName"))
    product_level = first_string(row, ("processingLevel", "productType", "scienceProduct"))
    if not name or (product_level and product_level.upper() != "GCOV"):
        return None

    name = name.removesuffix(".h5")
    url = first_string(row, ("url", "downloadUrl", "downloadURL", "productUrl", "product_url"))
    metadata = parse_granule_metadata(name)
    maturity = detect_maturity(url, row)
    collection = first_string(row, ("collectionName", "collection", "shortName"))
    if maturity == "UNKNOWN" and collection:
        match = MATURITY_PATTERN.search(collection)
        if match:
            maturity = match.group(1).upper()
    if not url and maturity in {"BETA", "PROVISIONAL"}:
        url = (
            "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
            f"NISAR_L2_GCOV_{maturity}_V1/{name}/{name}.h5"
        )
    start_time = first_string(row, ("startTime", "acquisitionDate", "start_date")) or metadata["acquisition_start_utc"]
    stop_time = first_string(row, ("stopTime", "endTime", "stop_date")) or metadata["acquisition_end_utc"]
    size = row.get("sizeMB")
    if isinstance(size, dict):
        sizes = [
            item.get("bytes")
            for item in size.values()
            if isinstance(item, dict) and isinstance(item.get("bytes"), (int, float))
        ]
        size_mb = sum(sizes) / 1_000_000 if sizes else None
    elif isinstance(size, (int, float)):
        size_mb = float(size)
    else:
        size_mb = None

    direction = first_string(row, ("flightDirection", "direction")) or metadata["orbit_direction"]
    if direction:
        direction = {"A": "ASCENDING", "D": "DESCENDING", "ASC": "ASCENDING", "DESC": "DESCENDING"}.get(direction.upper(), direction.upper())
    frame_coverage_raw = first_string(row, ("frameCoverage", "coverage"))
    frame_coverage = (
        {"F": "FULL", "FULL": "FULL", "P": "PARTIAL", "PARTIAL": "PARTIAL"}.get(frame_coverage_raw.upper())
        if frame_coverage_raw else metadata["frame_coverage"]
    )

    return {
        "granule_name": name,
        "product": "GCOV",
        "maturity": maturity,
        "download_url": url,
        "start_time_utc": start_time,
        "stop_time_utc": stop_time,
        "flight_direction": direction,
        "frame_coverage": frame_coverage,
        "footprint": row.get("geometry") or row.get("footprint"),
        "footprint_wkt": first_string(row, ("wkt", "footprintWkt", "footprint_wkt")),
        "main_band_polarization": first_string(row, ("mainBandPolarization", "polarization")) or {
            "SH": "HH", "SV": "VV", "DH": "HH+HV", "DV": "VV+VH",
            "CL": "LH+LV", "CR": "RH+RV",
        }.get((metadata["polarization_code"] or "")[:2]),
        "size_mb": size_mb,
        **metadata,
    }



def _umm_geometry(umm: dict[str, Any]) -> dict[str, Any] | None:
    """Convert CMR UMM-G spatial geometry into GeoJSON for footprint auditing."""
    spatial = (
        umm.get("SpatialExtent", {})
        .get("HorizontalSpatialDomain", {})
        .get("Geometry", {})
    )
    polygons: list[list[list[list[float]]]] = []

    for item in spatial.get("GPolygons", []) if isinstance(spatial, dict) else []:
        if not isinstance(item, dict):
            continue
        boundary = item.get("Boundary", {})
        points = boundary.get("Points", []) if isinstance(boundary, dict) else []
        exterior = [
            [float(point["Longitude"]), float(point["Latitude"])]
            for point in points
            if isinstance(point, dict) and "Longitude" in point and "Latitude" in point
        ]
        if len(exterior) < 3:
            continue
        if exterior[0] != exterior[-1]:
            exterior.append(exterior[0])
        rings = [exterior]

        for hole in item.get("ExclusiveZone", []) if isinstance(item.get("ExclusiveZone"), list) else []:
            hole_points = hole.get("Boundary", {}).get("Points", []) if isinstance(hole, dict) else []
            ring = [
                [float(point["Longitude"]), float(point["Latitude"])]
                for point in hole_points
                if isinstance(point, dict) and "Longitude" in point and "Latitude" in point
            ]
            if len(ring) >= 3:
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                rings.append(ring)
        polygons.append(rings)

    for rectangle in spatial.get("BoundingRectangles", []) if isinstance(spatial, dict) else []:
        if not isinstance(rectangle, dict):
            continue
        try:
            west = float(rectangle["WestBoundingCoordinate"])
            east = float(rectangle["EastBoundingCoordinate"])
            south = float(rectangle["SouthBoundingCoordinate"])
            north = float(rectangle["NorthBoundingCoordinate"])
        except (KeyError, TypeError, ValueError):
            continue
        if east <= west or north <= south:
            continue
        polygons.append([[
            [west, south], [east, south], [east, north],
            [west, north], [west, south],
        ]])

    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def normalize_umm_product(item: dict[str, Any], maturity: str) -> dict[str, Any] | None:
    """Normalize one NASA CMR UMM-G item from an official NISAR GCOV short-name collection."""
    umm = item.get("umm")
    if not isinstance(umm, dict):
        return None
    name = first_string(umm, ("GranuleUR",))
    if not name:
        return None
    name = name.removesuffix(".h5")
    try:
        metadata = parse_granule_metadata(name)
    except ValueError:
        return None

    temporal_extents = umm.get("TemporalExtents") or []
    start_time = None
    stop_time = None
    for extent in temporal_extents:
        if not isinstance(extent, dict):
            continue
        ranges = extent.get("RangeDateTimes") or []
        if ranges and isinstance(ranges[0], dict):
            start_time = ranges[0].get("BeginningDateTime")
            stop_time = ranges[0].get("EndingDateTime")
            break
        singles = extent.get("SingleDateTimes") or []
        if singles and isinstance(singles[0], dict):
            start_time = singles[0].get("DateTime")
            stop_time = start_time
            break

    related_urls = umm.get("RelatedUrls") or []
    product_url = None
    for relation in related_urls:
        if not isinstance(relation, dict):
            continue
        relation_type = str(relation.get("Type", "")).upper()
        content_type = str(relation.get("URLContentType", "")).upper()
        url = relation.get("URL")
        if isinstance(url, str) and url.startswith("https://") and (
            relation_type in {"GET DATA", "GET DATA VIA DIRECT ACCESS"}
            or content_type == "DISTRIBUTIONURL"
        ):
            product_url = url
            if relation_type == "GET DATA":
                break
    if not product_url:
        product_url = (
            "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
            f"NISAR_L2_GCOV_{maturity}_V1/{name}/{name}.h5"
        )

    main_polarization = {
        "SH": "HH", "SV": "VV", "DH": "HH+HV", "DV": "VV+VH",
        "CL": "LH+LV", "CR": "RH+RV",
    }.get((metadata.get("polarization_code") or "")[:2])

    data_granule = umm.get("DataGranule") or {}
    size_mb = None
    if isinstance(data_granule, dict):
        distribution_info = data_granule.get("ArchiveAndDistributionInformation") or []
        for info in distribution_info:
            if not isinstance(info, dict):
                continue
            try:
                size = float(info.get("Size"))
            except (TypeError, ValueError):
                continue
            unit = str(info.get("SizeUnit", "MB")).upper()
            multipliers = {"B": 1 / 1_000_000, "KB": 1 / 1_000, "MB": 1, "GB": 1_000}
            if unit in multipliers:
                size_mb = size * multipliers[unit]
                break

    return {
        "granule_name": name,
        "product": "GCOV",
        "maturity": maturity,
        "download_url": product_url,
        "start_time_utc": start_time or metadata["acquisition_start_utc"],
        "stop_time_utc": stop_time or metadata["acquisition_end_utc"],
        "flight_direction": {"A": "ASCENDING", "D": "DESCENDING"}[metadata["orbit_direction"]],
        "frame_coverage": metadata["frame_coverage"],
        "footprint": _umm_geometry(umm),
        "footprint_wkt": None,
        "main_band_polarization": main_polarization,
        "size_mb": size_mb,
        "cmr_concept_id": (item.get("meta") or {}).get("concept-id"),
        "collection_short_name": f"NISAR_L2_GCOV_{maturity}_V1",
        **metadata,
    }

def search_catalogue(
    aoi_wkt: str,
    start_date: date,
    end_date: date,
    maturity: str,
    main_band_polarization: str | None,
    flight_direction: str | None,
    max_results: int,
    timeout: int,
    frame_coverage: str = "ALL",
) -> dict[str, Any]:
    """Search official NISAR GCOV CMR collections by short name and AOI."""
    if maturity not in {"BETA", "PROVISIONAL", "ALL"}:
        raise ValueError("maturity must be BETA, PROVISIONAL or ALL.")
    if frame_coverage not in {"ALL", "FULL", "PARTIAL"}:
        raise ValueError("frame-coverage must be ALL, FULL or PARTIAL.")
    if end_date < start_date:
        raise ValueError("end-date must not be earlier than start-date.")
    if not 1 <= max_results <= 2000:
        raise ValueError("max-results must be between 1 and 2000.")

    geometry = shapely_wkt.loads(aoi_wkt)
    if not isinstance(geometry, Polygon) or geometry.is_empty or not geometry.is_valid:
        raise ValueError("AOI must be one valid WGS84 polygon.")
    aoi_wkt = orient(geometry, sign=1.0).wkt
    polygon = ",".join(
        f"{x:.8f},{y:.8f}"
        for x, y in list(geometry.exterior.coords)
    )
    temporal = (
        f"{start_date.isoformat()}T00:00:00Z,"
        f"{end_date.isoformat()}T23:59:59Z"
    )

    maturities = ("BETA", "PROVISIONAL") if maturity == "ALL" else (maturity,)
    products: list[dict[str, Any]] = []
    query_records: list[dict[str, Any]] = []
    total_hits = 0
    pages_truncated = False

    def cmr_request(collection_short_name: str, page_num: int) -> tuple[dict[str, Any], str, int]:
        params = {
            "short_name": collection_short_name,
            "temporal[]": temporal,
            "polygon": polygon,
            "page_size": str(min(2000, max_results)),
            "page_num": str(page_num),
        }
        query_url = f"{CMR_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            query_url,
            headers={
                "Accept": CMR_ACCEPT,
                "User-Agent": "SARGuardian-RiverShift/0.2",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                cmr_hits = int(response.headers.get("CMR-Hits", payload.get("hits", 0)))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()[:1200]
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"NASA CMR returned HTTP {exc.code}{suffix}") from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError("NASA CMR request could not be reached before the timeout.") from None
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise RuntimeError("NASA CMR returned invalid UMM-JSON metadata.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RuntimeError("NASA CMR returned an unexpected UMM-JSON response shape.")
        return payload, query_url, cmr_hits

    for collection_maturity in maturities:
        collection_short_name = f"NISAR_L2_GCOV_{collection_maturity}_V1"
        page_num = 1
        collection_hits = 0
        collection_records = 0
        while len(products) < max_results:
            payload, query_url, cmr_hits = cmr_request(collection_short_name, page_num)
            items = payload["items"]
            if page_num == 1:
                collection_hits = cmr_hits
                total_hits += cmr_hits
            collection_records += len(items)

            for item in items:
                if not isinstance(item, dict):
                    continue
                product = normalize_umm_product(item, collection_maturity)
                if product is None:
                    continue
                if main_band_polarization and product["main_band_polarization"] != main_band_polarization:
                    continue
                if flight_direction and product["flight_direction"] != flight_direction:
                    continue
                if frame_coverage != "ALL" and product["frame_coverage"] != frame_coverage:
                    continue
                products.append(product)
                if len(products) >= max_results:
                    break

            query_records.append({
                "collection_short_name": collection_short_name,
                "page_num": page_num,
                "request_url": query_url,
                "reported_cmr_hits": collection_hits,
                "records_received": collection_records,
                "page_records_received": len(items),
            })
            if not items or collection_records >= collection_hits:
                break
            if len(products) >= max_results:
                pages_truncated = True
                break
            page_num += 1

    products.sort(key=lambda item: str(item.get("start_time_utc") or ""))
    warnings = [
        "NISAR products were discovered by official CMR collection short name. This is catalogue discovery, not raster download or scientific analysis.",
        "Each product footprint must still pass the separate AOI coverage audit before a multi-date raster comparison.",
    ]
    if total_hits > len(products) and len(products) >= max_results:
        pages_truncated = True
    if pages_truncated:
        warnings.append("The selected product result cap was reached; increase --max-results or narrow the AOI/date window.")
    if not products:
        warnings.append(
            "NASA CMR returned no GCOV granules for the selected collection short name, AOI and temporal range. This result applies only to this exact query."
        )

    return {
        "schema_version": 1,
        "mission": "NISAR",
        "agency": "NASA-ISRO",
        "archive": "Alaska Satellite Facility DAAC via NASA CMR",
        "product": "GCOV",
        "maturity_filter": maturity,
        "query": {
            "aoi_wkt": aoi_wkt,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "main_band_polarization": main_band_polarization,
            "frame_coverage": frame_coverage,
            "flight_direction": flight_direction,
            "max_results": max_results,
            "endpoint": CMR_SEARCH_URL,
            "response_format": "UMM-G 1.6.7",
            "collection_short_names": [f"NISAR_L2_GCOV_{value}_V1" for value in maturities],
            "spatial_parameter": "polygon",
            "temporal_parameter": "temporal[]",
        },
        "raw_record_count": total_hits,
        "product_count": len(products),
        "search_diagnostics": {
            "search_provider": "NASA CMR",
            "collection_queries": query_records,
            "pages_truncated": pages_truncated,
            "cmr_reported_hit_count": total_hits,
        },
        "products": products,
        "warnings": warnings,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aoi-wkt", required=True, help="One valid WGS84 POLYGON WKT.")
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--maturity", choices=("BETA", "PROVISIONAL", "ALL"), default="PROVISIONAL")
    parser.add_argument("--main-band-polarization", choices=("HH", "HH+HV", "HH+VV", "HH+HV+VH+VV", "VV", "VV+VH", "LH+LV", "RH+RV"))
    parser.add_argument("--flight-direction", choices=("ASCENDING", "DESCENDING"))
    parser.add_argument("--frame-coverage", choices=("ALL", "FULL", "PARTIAL"), default="ALL")
    parser.add_argument("--max-results", type=int, default=500)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--out", required=True, help="Output JSON manifest path.")
    args = parser.parse_args()

    try:
        if args.end_date < args.start_date:
            raise ValueError("end-date must not be earlier than start-date.")
        if not 1 <= args.max_results <= 2000:
            raise ValueError("max-results must be between 1 and 2000.")
        aoi = validate_aoi(args.aoi_wkt)
        result = search_catalogue(
            aoi, args.start_date, args.end_date, args.maturity,
            args.main_band_polarization, args.flight_direction,
            args.max_results, args.timeout, args.frame_coverage,
        )
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"RIVERSHIFT_GCOV_PRODUCTS={result['product_count']}")
        print(f"RIVERSHIFT_CATALOGUE_MANIFEST={output}")
        for warning in result["warnings"]:
            print(f"WARNING={warning}", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
