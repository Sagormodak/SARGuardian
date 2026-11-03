from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/river-shift", tags=["RiverShift"])

CMR_SEARCH_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json_v1_6_7"
CMR_ACCEPT = "application/vnd.nasa.cmr.umm_results+json; version=1.6.7"
MAX_RESULTS = 200
MAX_AOI_AREA_KM2 = 1_000.0
TIMEOUT_SECONDS = 25
EARTH_RADIUS_METERS = 6_371_000.0

Maturity = Literal["BETA", "PROVISIONAL", "ALL"]
Polarization = Literal["HH", "HH+HV", "HH+VV", "HH+HV+VH+VV", "VV", "VV+VH", "LH+LV", "RH+RV"]
FlightDirection = Literal["ASCENDING", "DESCENDING"]
FrameCoverage = Literal["FULL", "PARTIAL", "ALL"]


class RiverShiftCatalogRequest(BaseModel):
    coordinates: list[list[float]] = Field(min_length=4, max_length=400)
    start_date: date
    end_date: date
    maturity: Maturity = "PROVISIONAL"
    main_band_polarization: Polarization | None = None
    flight_direction: FlightDirection | None = None
    frame_coverage: FrameCoverage = "ALL"
    max_results: int = Field(default=100, ge=1, le=MAX_RESULTS)


class RiverShiftProduct(BaseModel):
    granule_name: str
    product_type: Literal["GCOV"] = "GCOV"
    processing_type: str | None = None
    crid: str | None = None
    maturity: Literal["BETA", "PROVISIONAL", "UNKNOWN"]
    download_url: str | None = None
    start_time_utc: str | None = None
    stop_time_utc: str | None = None
    flight_direction: str | None = None
    relative_orbit: str | None = None
    cycle: str | None = None
    frame: str | None = None
    bandwidth_mode: str | None = None
    polarization_code: str | None = None
    main_band_polarization: str | None = None
    frame_coverage: str | None = None
    size_mb: float | None = None
    footprint: dict[str, Any] | None = None
    cmr_concept_id: str | None = None


class RiverShiftCatalogResponse(BaseModel):
    mode: Literal["catalogue_only"] = "catalogue_only"
    mission: Literal["NISAR"] = "NISAR"
    product: Literal["GCOV"] = "GCOV"
    status: Literal["ready", "no_data", "upstream_error"]
    message: str
    data_downloaded: Literal[False] = False
    scientific_analysis_performed: Literal[False] = False
    query: dict[str, Any]
    product_count: int = 0
    products: list[RiverShiftProduct] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _validate_coordinates(coordinates: list[list[float]]) -> list[tuple[float, float]]:
    if len(coordinates) < 4:
        raise HTTPException(status_code=422, detail="AOI must be a closed polygon with at least 3 vertices.")
    normalized: list[tuple[float, float]] = []
    for point in coordinates:
        if len(point) != 2:
            raise HTTPException(status_code=422, detail="Each coordinate must be [longitude, latitude].")
        lon, lat = point
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise HTTPException(status_code=422, detail="AOI coordinates must be finite numbers.")
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise HTTPException(status_code=422, detail="AOI coordinates must use WGS84 longitude/latitude.")
        normalized.append((float(lon), float(lat)))
    if normalized[0] != normalized[-1]:
        raise HTTPException(status_code=422, detail="AOI polygon must repeat its first coordinate at the end.")
    if len(set(normalized[:-1])) < 3:
        raise HTTPException(status_code=422, detail="AOI must contain at least 3 distinct vertices.")
    return normalized


def _area_km2(coordinates: list[tuple[float, float]]) -> float:
    ring = [*coordinates, coordinates[0]]
    total = 0.0
    for (lon_a, lat_a), (lon_b, lat_b) in zip(ring, ring[1:]):
        delta_lon = math.radians(lon_b - lon_a)
        if delta_lon > math.pi:
            delta_lon -= 2 * math.pi
        if delta_lon < -math.pi:
            delta_lon += 2 * math.pi
        total += delta_lon * (
            math.sin(math.radians(lat_a)) + math.sin(math.radians(lat_b))
        )
    return abs(total) * EARTH_RADIUS_METERS ** 2 / 2 / 1_000_000

def _polygon_wkt(coordinates: list[tuple[float, float]]) -> str:
    return "POLYGON ((" + ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in coordinates) + "))"


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = payload.get("results") or payload.get("features") or payload.get("items") or []
    else:
        candidates = []
    rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties")
        row = dict(properties) if isinstance(properties, dict) else dict(item)
        rows.append(row)
    return rows


def _first_string(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _maturity(url: str | None, row: dict[str, Any] | None = None) -> str:
    if row:
        for key in ("dataMaturity", "maturity"):
            declared = row.get(key)
            if isinstance(declared, str) and declared.strip().upper() in {"BETA", "PROVISIONAL"}:
                return declared.strip().upper()

    values = [url or ""]
    if row:
        values.extend(str(row.get(key, "")) for key in ("collectionName", "collection", "shortName"))
    for value in values:
        value = value.upper()
        if "NISAR_L2_GCOV_PROVISIONAL_V1" in value:
            return "PROVISIONAL"
        if "NISAR_L2_GCOV_BETA_V1" in value:
            return "BETA"
    return "UNKNOWN"


def _granule_parts(name: str) -> dict[str, str | None]:
    parts = name.removesuffix(".h5").split("_")
    if (
        len(parts) != 18 or parts[0] != "NISAR" or parts[1] != "L2"
        or parts[2] not in {"PR", "UR", "OD"} or parts[3] != "GCOV"
        or parts[6] not in {"A", "D"} or parts[15] not in {"F", "P"}
    ):
        return {}
    return {
        "processing_type": parts[2],
        "cycle": parts[4],
        "relative_orbit": parts[5],
        "flight_direction": {"A": "ASCENDING", "D": "DESCENDING"}[parts[6]],
        "frame": parts[7],
        "bandwidth_mode": parts[8],
        "polarization_code": parts[9],
        "acquisition_start_utc": parts[11],
        "acquisition_end_utc": parts[12],
        "crid": parts[13],
        "frame_coverage": "FULL" if parts[15] == "F" else "PARTIAL",
    }


def _product(row: dict[str, Any]) -> RiverShiftProduct | None:
    name = _first_string(row, ("granuleName", "fileName", "sceneName", "fileID", "productName"))
    level = _first_string(row, ("processingLevel", "productType", "scienceProduct"))
    if not name or (level and level.upper() != "GCOV"):
        return None
    name = name.removesuffix(".h5")
    url = _first_string(row, ("url", "downloadUrl", "downloadURL", "productUrl", "product_url"))
    parts = _granule_parts(name)
    if not parts:
        return None
    maturity = _maturity(url, row)
    if not url and maturity in {"BETA", "PROVISIONAL"}:
        url = (
            "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
            f"NISAR_L2_GCOV_{maturity}_V1/{name}/{name}.h5"
        )
    size = row.get("sizeMB")
    if isinstance(size, dict):
        byte_values = [
            value.get("bytes")
            for value in size.values()
            if isinstance(value, dict) and isinstance(value.get("bytes"), (int, float)) and value["bytes"] >= 0
        ]
        size_mb = sum(byte_values) / 1_000_000 if byte_values else None
    elif isinstance(size, (int, float)) and size >= 0:
        size_mb = float(size)
    else:
        size_mb = None

    direction = _first_string(row, ("flightDirection", "direction")) or parts["flight_direction"]
    if direction:
        direction = {"A": "ASCENDING", "D": "DESCENDING", "ASC": "ASCENDING", "DESC": "DESCENDING"}.get(direction.upper(), direction.upper())
    coverage_raw = _first_string(row, ("frameCoverage", "coverage"))
    coverage = (
        {"F": "FULL", "FULL": "FULL", "P": "PARTIAL", "PARTIAL": "PARTIAL"}.get(coverage_raw.upper())
        if coverage_raw else parts["frame_coverage"]
    )

    return RiverShiftProduct(
        granule_name=name,
        processing_type=parts["processing_type"],
        crid=parts["crid"],
        maturity=maturity,
        download_url=url,
        start_time_utc=_first_string(row, ("startTime", "acquisitionDate")) or parts["acquisition_start_utc"],
        stop_time_utc=_first_string(row, ("stopTime", "endTime")) or parts["acquisition_end_utc"],
        flight_direction=direction,
        relative_orbit=parts["relative_orbit"],
        cycle=parts["cycle"],
        frame=parts["frame"],
        bandwidth_mode=parts["bandwidth_mode"],
        polarization_code=parts["polarization_code"],
        main_band_polarization=_first_string(row, ("mainBandPolarization", "polarization")) or {
            "SH": "HH", "SV": "VV", "DH": "HH+HV", "DV": "VV+VH",
            "CL": "LH+LV", "CR": "RH+RV",
        }.get((parts["polarization_code"] or "")[:2]),
        frame_coverage=coverage,
        size_mb=size_mb,
    )



def _umm_footprint(umm: dict[str, Any]) -> dict[str, Any] | None:
    spatial = (
        umm.get("SpatialExtent", {})
        .get("HorizontalSpatialDomain", {})
        .get("Geometry", {})
    )
    polygons = []
    for item in spatial.get("GPolygons", []) if isinstance(spatial, dict) else []:
        if not isinstance(item, dict):
            continue
        points = item.get("Boundary", {}).get("Points", [])
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

    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _umm_product(item: dict[str, Any], maturity: str) -> RiverShiftProduct | None:
    umm = item.get("umm")
    if not isinstance(umm, dict):
        return None
    name = _first_string(umm, ("GranuleUR",))
    if not name:
        return None
    name = name.removesuffix(".h5")
    parts = _granule_parts(name)
    if not parts:
        return None

    temporal = umm.get("TemporalExtents") or []
    start_time = parts["acquisition_start_utc"]
    stop_time = parts["acquisition_end_utc"]
    for extent in temporal:
        if not isinstance(extent, dict):
            continue
        ranges = extent.get("RangeDateTimes") or []
        if ranges and isinstance(ranges[0], dict):
            start_time = ranges[0].get("BeginningDateTime") or start_time
            stop_time = ranges[0].get("EndingDateTime") or stop_time
            break

    url = None
    for relation in umm.get("RelatedUrls") or []:
        if not isinstance(relation, dict):
            continue
        url_type = str(relation.get("Type", "")).upper()
        content_type = str(relation.get("URLContentType", "")).upper()
        candidate = relation.get("URL")
        if isinstance(candidate, str) and candidate.startswith("https://") and (
            url_type in {"GET DATA", "GET DATA VIA DIRECT ACCESS"}
            or content_type == "DISTRIBUTIONURL"
        ):
            url = candidate
            if url_type == "GET DATA":
                break
    if not url:
        url = (
            "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
            f"NISAR_L2_GCOV_{maturity}_V1/{name}/{name}.h5"
        )

    polarization = {
        "SH": "HH", "SV": "VV", "DH": "HH+HV", "DV": "VV+VH",
        "CL": "LH+LV", "CR": "RH+RV",
    }.get((parts["polarization_code"] or "")[:2])

    size_mb = None
    data_granule = umm.get("DataGranule") or {}
    if isinstance(data_granule, dict):
        for info in data_granule.get("ArchiveAndDistributionInformation") or []:
            if not isinstance(info, dict):
                continue
            try:
                value = float(info.get("Size"))
            except (TypeError, ValueError):
                continue
            unit = str(info.get("SizeUnit", "MB")).upper()
            factor = {"B": 1 / 1_000_000, "KB": 1 / 1_000, "MB": 1, "GB": 1_000}.get(unit)
            if factor is not None:
                size_mb = value * factor
                break

    meta = item.get("meta") or {}
    return RiverShiftProduct(
        granule_name=name,
        processing_type=parts["processing_type"],
        crid=parts["crid"],
        maturity=maturity,
        download_url=url,
        start_time_utc=start_time,
        stop_time_utc=stop_time,
        flight_direction=parts["flight_direction"],
        relative_orbit=parts["relative_orbit"],
        cycle=parts["cycle"],
        frame=parts["frame"],
        bandwidth_mode=parts["bandwidth_mode"],
        polarization_code=parts["polarization_code"],
        main_band_polarization=polarization,
        frame_coverage=parts["frame_coverage"],
        size_mb=size_mb,
        footprint=_umm_footprint(umm),
        cmr_concept_id=meta.get("concept-id") if isinstance(meta, dict) else None,
    )

def search_gcov_catalogue(request: RiverShiftCatalogRequest) -> RiverShiftCatalogResponse:
    coordinates = _validate_coordinates(request.coordinates)
    area = _area_km2(coordinates)
    if not math.isfinite(area) or area <= 0 or area > MAX_AOI_AREA_KM2:
        raise HTTPException(
            status_code=422,
            detail=f"AOI area must be positive and no larger than {MAX_AOI_AREA_KM2:g} km2.",
        )
    if request.end_date < request.start_date:
        raise HTTPException(status_code=422, detail="end_date must not be earlier than start_date.")
    if (request.end_date - request.start_date).days > 366:
        raise HTTPException(status_code=422, detail="Search window cannot exceed 366 days.")

    oriented = list(coordinates)
    signed_area = sum(
        oriented[index][0] * oriented[index + 1][1]
        - oriented[index + 1][0] * oriented[index][1]
        for index in range(len(oriented) - 1)
    )
    if signed_area < 0:
        open_ring = list(reversed(oriented[:-1]))
        oriented = [*open_ring, open_ring[0]]

    polygon = ",".join(f"{lon:.8f},{lat:.8f}" for lon, lat in oriented)
    temporal = f"{request.start_date.isoformat()}T00:00:00Z,{request.end_date.isoformat()}T23:59:59Z"
    maturities = ("BETA", "PROVISIONAL") if request.maturity == "ALL" else (request.maturity,)
    products: list[RiverShiftProduct] = []
    query_records = []
    total_hits = 0

    for maturity in maturities:
        collection_short_name = f"NISAR_L2_GCOV_{maturity}_V1"
        page_num = 1
        collection_hits = 0
        collection_records = 0
        while len(products) < request.max_results:
            params = {
                "short_name": collection_short_name,
                "temporal[]": temporal,
                "polygon": polygon,
                "page_size": str(request.max_results),
                "page_num": str(page_num),
            }
            url = f"{CMR_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            http_request = urllib.request.Request(
                url,
                headers={"Accept": CMR_ACCEPT, "User-Agent": "SARGuardian-RiverShift/0.2"},
            )
            try:
                with urllib.request.urlopen(http_request, timeout=TIMEOUT_SECONDS) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    hits = int(response.headers.get("CMR-Hits", payload.get("hits", 0)))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()[:800]
                suffix = f": {detail}" if detail else ""
                raise HTTPException(status_code=502, detail=f"NASA CMR returned HTTP {exc.code}{suffix}") from None
            except (urllib.error.URLError, TimeoutError):
                raise HTTPException(status_code=504, detail="NASA CMR request timed out or could not be reached.") from None
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                raise HTTPException(status_code=502, detail="NASA CMR returned invalid UMM-JSON metadata.") from None

            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise HTTPException(status_code=502, detail="NASA CMR returned an unexpected UMM-JSON response shape.")
            if page_num == 1:
                collection_hits = hits
                total_hits += hits
            page_items = payload["items"]
            collection_records += len(page_items)
            for item in page_items:
                if not isinstance(item, dict):
                    continue
                product = _umm_product(item, maturity)
                if product is None:
                    continue
                if request.main_band_polarization and product.main_band_polarization != request.main_band_polarization:
                    continue
                if request.flight_direction and product.flight_direction != request.flight_direction:
                    continue
                if request.frame_coverage != "ALL" and product.frame_coverage != request.frame_coverage:
                    continue
                products.append(product)
                if len(products) >= request.max_results:
                    break

            query_records.append({
                "collection_short_name": collection_short_name,
                "request_url": url,
                "page_num": page_num,
                "cmr_reported_hits": collection_hits,
                "records_received": collection_records,
                "page_records_received": len(page_items),
            })
            if not page_items or collection_records >= collection_hits:
                break
            if len(products) >= request.max_results:
                break
            page_num += 1

    products.sort(key=lambda item: str(item.start_time_utc or ""))
    warnings = [
        "NISAR GCOV products are discovered by official CMR collection short name. Catalogue discovery does not download data or run scientific analysis.",
        "Use the separate footprint audit to verify AOI coverage on every acquisition date before selecting a time series.",
    ]
    if total_hits > len(products) and len(products) >= request.max_results:
        warnings.append("Product result cap reached. Narrow the AOI/date interval or query one maturity at a time.")
    if not products:
        warnings.append("NASA CMR returned no granules for the selected collection short name(s), AOI and temporal interval.")

    status = "ready" if products else "no_data"
    message = (
        f"Found {len(products)} GCOV product(s). CMR catalogue discovery only; no data has been downloaded or analysed."
        if products else "No matching NISAR GCOV products were returned by NASA CMR for this query."
    )
    return RiverShiftCatalogResponse(
        status=status,
        message=message,
        query={
            "aoi_wkt": _polygon_wkt(oriented),
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "maturity": request.maturity,
            "collection_short_names": [f"NISAR_L2_GCOV_{value}_V1" for value in maturities],
            "main_band_polarization": request.main_band_polarization,
            "flight_direction": request.flight_direction,
            "frame_coverage": request.frame_coverage,
            "archive": "NASA CMR / ASF DAAC",
            "endpoint": CMR_SEARCH_URL,
            "response_format": "UMM-G 1.6.7",
            "reported_cmr_hits": total_hits,
            "collection_queries": query_records,
        },
        product_count=len(products),
        products=products,
        warnings=warnings,
    )

@router.post("/catalog/search", response_model=RiverShiftCatalogResponse)
def river_shift_catalog_search(request: RiverShiftCatalogRequest) -> RiverShiftCatalogResponse:
    """Public, read-only NISAR GCOV catalogue search. This endpoint never downloads products."""
    return search_gcov_catalogue(request)
