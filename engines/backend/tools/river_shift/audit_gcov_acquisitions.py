#!/usr/bin/env python3
"""Audit whether ASF NISAR GCOV catalog results form a comparable multi-date AOI stack."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pyproj import CRS, Transformer
from shapely import wkt as shapely_wkt
from shapely.geometry import shape
from shapely.ops import transform, unary_union


_BANDWIDTH_PIXEL_SPACING_M = {"05": 80, "20": 20, "40": 10, "77": 20, "00": None}
_DIAGONAL_TERMS_BY_POLARIZATION = {
    "SH": ("HHHH",),
    "SV": ("VVVV",),
    "DH": ("HHHH", "HVHV"),
    "DV": ("VVVV", "VHVH"),
    "QP": ("HHHH", "HVHV", "VVVV", "VHVH"),
    "CL": ("RHRH", "RVRV"),
    "CR": ("RHRH", "RVRV"),
}


def _product_geometry(product: dict[str, Any]):
    geometry = product.get("footprint")
    if isinstance(geometry, dict):
        try:
            if geometry.get("type") == "Feature":
                geometry = geometry.get("geometry")
            if not isinstance(geometry, dict):
                return None
            return shape(geometry)
        except Exception:
            return None

    footprint_wkt = product.get("footprint_wkt") or product.get("wkt")
    if isinstance(footprint_wkt, str) and footprint_wkt.strip():
        try:
            return shapely_wkt.loads(footprint_wkt)
        except Exception:
            return None
    return None


def _utm_crs_for_aoi(aoi):
    centroid = aoi.centroid
    zone = int(math.floor((centroid.x + 180.0) / 6.0)) + 1
    zone = max(1, min(60, zone))
    epsg = (32600 if centroid.y >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def _to_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    compact = value.replace("-", "")[:8]
    try:
        return datetime.strptime(compact, "%Y%m%d").date()
    except ValueError:
        return None


def _signature(product: dict[str, Any], *, frequency: str, term: str) -> tuple[str, ...] | None:
    keys = (
        "maturity",
        "flight_direction",
        "relative_orbit",
        "bandwidth_mode",
        "polarization_code",
    )
    values = [product.get(key) for key in keys]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        return None
    if values[0] not in {"BETA", "PROVISIONAL"}:
        return None
    if product.get("product") and str(product["product"]).upper() != "GCOV":
        return None
    collection = product.get("collection_short_name") or product.get("collection_name")
    if collection:
        maturity_match = re.search(r"NISAR_L2_GCOV_(BETA|PROVISIONAL)_V1", str(collection), re.IGNORECASE)
        if maturity_match and maturity_match.group(1).upper() != values[0].upper():
            return None

    granule = str(product.get("granule_name") or "")
    parts = granule.split("_")
    if len(parts) != 18 or parts[0] != "NISAR" or parts[1] != "L2" or parts[3] != "GCOV":
        return None
    if parts[2] not in {"PR", "UR", "OD"} or parts[10] not in {"A", "M"}:
        return None
    if parts[8] != values[3] or parts[9] != values[4]:
        return None
    if values[1].upper() != {"A": "ASCENDING", "D": "DESCENDING"}.get(parts[6]):
        return None
    if values[2].zfill(3) != parts[5]:
        return None
    if product.get("frame") and str(product["frame"]).zfill(3) != parts[7]:
        return None
    if product.get("processing_type") and str(product["processing_type"]).upper() != parts[2]:
        return None

    token_checks = {
        "cycle": parts[4],
        "crid": parts[13],
        "processing_center": parts[16],
        "science_data_system": parts[16],
        "product_counter": parts[17],
    }
    for field, expected in token_checks.items():
        actual = product.get(field)
        if actual is not None and str(actual).strip() and str(actual).strip().upper() != expected.upper():
            return None

    observation_source = product.get("observation_source")
    if observation_source is not None:
        source_code = {"ACQUIRED_SINGLE_MODE": "A", "MIXED_MODE": "M"}.get(
            str(observation_source).strip().upper(), str(observation_source).strip().upper()
        )
        if source_code != parts[10]:
            return None

    orbit_accuracy = product.get("orbit_accuracy")
    if orbit_accuracy is not None:
        accuracy_code = {
            "PRECISE": "P", "MEDIUM": "M", "NEAR_REAL_TIME": "N", "FORECAST": "F",
        }.get(str(orbit_accuracy).strip().upper(), str(orbit_accuracy).strip().upper())
        if accuracy_code != parts[14]:
            return None

    for field in ("frame_coverage", "coverage"):
        coverage = product.get(field)
        if coverage is not None:
            coverage_code = {"FULL": "F", "PARTIAL": "P"}.get(
                str(coverage).strip().upper(), str(coverage).strip().upper()
            )
            if coverage_code != parts[15]:
                return None
    if frequency not in {"frequencyA", "frequencyB"}:
        raise ValueError("frequency must be frequencyA or frequencyB.")

    band_index = 0 if frequency == "frequencyA" else 1
    bandwidth_code = parts[8][band_index * 2:band_index * 2 + 2]
    polarization_code = parts[9][band_index * 2:band_index * 2 + 2]
    if bandwidth_code == "00" or term not in _DIAGONAL_TERMS_BY_POLARIZATION.get(polarization_code, ()):
        return None

    frame_coverage = str(product.get("frame_coverage") or parts[15]).upper()
    if frame_coverage not in {"F", "P", "FULL", "PARTIAL"}:
        return None
    normalized_coverage = {"F": "FULL", "P": "PARTIAL"}.get(frame_coverage, frame_coverage)
    name_coverage = {"F": "FULL", "P": "PARTIAL"}.get(parts[15], parts[15])
    if normalized_coverage != name_coverage:
        return None
    return tuple(str(value) for value in values) + (
        parts[2],  # processing type
        parts[10],  # acquired or mixed source
        parts[13],  # composite release ID
        parts[14],  # orbit/radar-pointing accuracy
        normalized_coverage,
        parts[16],  # processing center
        parts[7],  # NISAR frame
        frequency,
        term,
    )


def _frequency_selection(group_signature: tuple[str, ...]) -> dict[str, Any]:
    frequency, term = group_signature[12], group_signature[13]
    band_index = 0 if frequency == "frequencyA" else 1
    bandwidth_code = group_signature[3][band_index * 2:band_index * 2 + 2]
    polarization_code = group_signature[4][band_index * 2:band_index * 2 + 2]
    return {
        "frequency": frequency,
        "diagonal_term": term,
        "bandwidth_code_mhz": None if bandwidth_code == "00" else int(bandwidth_code),
        "expected_pixel_spacing_m": _BANDWIDTH_PIXEL_SPACING_M.get(bandwidth_code),
        "polarization_code": polarization_code,
        "term_encoded_as_available": True,
        "hdf5_layer_verified": False,
    }


def audit_manifest(
    manifest: dict[str, Any],
    *,
    minimum_dates: int = 3,
    minimum_aoi_coverage_percent: float = 90.0,
    frequency: str = "frequencyA",
    term: str = "HHHH",
) -> dict[str, Any]:
    if minimum_dates < 3:
        raise ValueError("minimum_dates cannot be lower than 3 for a multi-date screening workflow.")
    if not 1 <= minimum_aoi_coverage_percent <= 100:
        raise ValueError("minimum_aoi_coverage_percent must be in the range 1..100.")
    if frequency not in {"frequencyA", "frequencyB"}:
        raise ValueError("frequency must be frequencyA or frequencyB.")
    if term not in {"HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"}:
        raise ValueError("term must be a diagonal GCOV covariance term.")

    query = manifest.get("query")
    products = manifest.get("products")
    if not isinstance(query, dict) or not isinstance(products, list):
        raise ValueError("Catalogue manifest must contain query and products fields.")
    aoi_wkt = query.get("aoi_wkt")
    if not isinstance(aoi_wkt, str):
        raise ValueError("Catalogue manifest is missing query.aoi_wkt.")

    aoi_wgs84 = shapely_wkt.loads(aoi_wkt)
    if aoi_wgs84.geom_type != "Polygon" or aoi_wgs84.is_empty or not aoi_wgs84.is_valid:
        raise ValueError("Manifest AOI must be one valid, non-empty WGS84 Polygon.")

    metric_crs = _utm_crs_for_aoi(aoi_wgs84)
    to_metric = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True).transform
    aoi_metric = transform(to_metric, aoi_wgs84)
    if aoi_metric.area <= 0:
        raise ValueError("AOI area is invalid after metric projection.")

    grouped: dict[tuple[str, ...], dict[date, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    rejected: list[dict[str, Any]] = []
    missing_footprints = 0

    for product in products:
        if not isinstance(product, dict):
            rejected.append({"granule_name": None, "reason": "INVALID_PRODUCT_RECORD"})
            continue
        signature = _signature(product, frequency=frequency, term=term)
        acquisition_date = _to_date(product.get("acquisition_start_utc") or product.get("start_time_utc"))
        if signature is None or acquisition_date is None:
            rejected.append({
                "granule_name": product.get("granule_name"),
                "reason": "INCOMPLETE_METADATA_OR_REQUESTED_BAND_TERM_UNAVAILABLE",
            })
            continue

        geometry = _product_geometry(product)
        if geometry is None or geometry.is_empty or not geometry.is_valid:
            missing_footprints += 1
            rejected.append({
                "granule_name": product.get("granule_name"),
                "reason": "FOOTPRINT_GEOMETRY_UNAVAILABLE_OR_INVALID",
            })
            continue

        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            rejected.append({
                "granule_name": product.get("granule_name"),
                "reason": "FOOTPRINT_IS_NOT_POLYGONAL",
            })
            continue

        metric_geometry = transform(to_metric, geometry)
        if metric_geometry.is_empty or metric_geometry.area <= 0:
            rejected.append({
                "granule_name": product.get("granule_name"),
                "reason": "FOOTPRINT_HAS_NO_METRIC_AREA",
            })
            continue

        grouped[signature][acquisition_date].append({
            "granule_name": product.get("granule_name"),
            "maturity": product.get("maturity"),
            "relative_orbit": product.get("relative_orbit"),
            "flight_direction": product.get("flight_direction"),
            "frame": product.get("frame"),
            "bandwidth_mode": product.get("bandwidth_mode"),
            "polarization_code": product.get("polarization_code"),
            "frame_coverage": product.get("frame_coverage"),
            "acquisition_start_utc": product.get("acquisition_start_utc") or product.get("start_time_utc"),
            "footprint_metric": metric_geometry,
        })

    groups_out = []
    qualifying = []
    for signature, date_groups in grouped.items():
        dates_out = []
        selected_granules: list[str] = []
        for acquisition_date, scene_rows in sorted(date_groups.items()):
            footprints = [row["footprint_metric"] for row in scene_rows]
            mosaic = unary_union(footprints)
            overlap_area = aoi_metric.intersection(mosaic).area
            coverage = max(0.0, min(100.0, overlap_area / aoi_metric.area * 100.0))
            names = sorted({str(row["granule_name"]) for row in scene_rows})
            dates_out.append({
                "acquisition_date": acquisition_date.isoformat(),
                "granule_count": len(names),
                "granule_names": names,
                "aoi_coverage_percent": round(coverage, 3),
                "passes_coverage_gate": coverage >= minimum_aoi_coverage_percent,
            })
            if coverage >= minimum_aoi_coverage_percent:
                selected_granules.extend(names)

        eligible_dates = [row for row in dates_out if row["passes_coverage_gate"]]
        group = {
            "maturity": signature[0],
            "flight_direction": signature[1],
            "relative_orbit": signature[2],
            "bandwidth_mode": signature[3],
            "polarization_code": signature[4],
            "processing_type": signature[5],
            "unique_acquisition_dates": len(dates_out),
            "eligible_acquisition_dates": len(eligible_dates),
            "dates": dates_out,
            "observation_source": {"A": "ACQUIRED_SINGLE_MODE", "M": "MIXED_MODE"}.get(signature[6], signature[6]),
            "crid": signature[7],
            "orbit_accuracy": {"P": "PRECISE", "M": "MEDIUM", "N": "NEAR_REAL_TIME", "F": "FORECAST"}.get(signature[8], signature[8]),
            "frame_coverage": signature[9],
            "processing_center": signature[10],
            "frame": signature[11],
            "frequency_selection": _frequency_selection(signature),
            "qualifies_for_product_level_review": len(eligible_dates) >= minimum_dates,
        }
        groups_out.append(group)
        if group["qualifies_for_product_level_review"]:
            qualifying.append({
                **group,
                "selected_granule_names": sorted(set(selected_granules)),
            })

    qualifying.sort(
        key=lambda group: (
            -group["eligible_acquisition_dates"],
            group["maturity"] != "PROVISIONAL",
            group["flight_direction"],
            group["relative_orbit"],
            group["bandwidth_mode"],
            group["polarization_code"],
            group["frame"],
        )
    )
    status = "READY_FOR_PRODUCT_LEVEL_COMPATIBILITY_CHECK" if qualifying else (
        "FOOTPRINT_DATA_INCOMPLETE" if missing_footprints else "INSUFFICIENT_COMPARABLE_ACQUISITIONS"
    )
    warnings = [
        "This is catalogue and footprint feasibility only; no product bytes, raster values, water labels or scientific results were inspected.",
        "The requested frequency and diagonal term are checked against the granule's encoded bandwidth/polarization mode only; inspect the exact HDF5 datasets before analysis.",
        "Footprint coverage is not valid-pixel coverage. Apply the matching GCOV valid-sample mask, compare CRS/dimensions/affine grids, and review incidence geometry before pixel-wise analysis.",
        "Mode 4005 means 40 MHz for Frequency A and 5 MHz for Frequency B; their expected pixel postings differ (10 m versus 80 m).",
        "A common track and acquisition mode do not establish comparable water stage or a flood-event date; use official station observations.",
    ]
    if missing_footprints:
        warnings.append(
            f"{missing_footprints} product(s) had no usable footprint geometry. Their AOI coverage was not assumed."
        )
    if not qualifying:
        warnings.append(
            f"No compatible group reached {minimum_dates} unique dates with at least "
            f"{minimum_aoi_coverage_percent:.1f}% AOI footprint coverage."
        )

    return {
        "schema_version": 2,
        "engine": "RiverShift",
        "analysis_type": "gcov_time_series_feasibility_audit",
        "status": status,
        "source": {
            "mission": "NISAR",
            "instrument": "L-SAR",
            "product": "GCOV",
            "archive": "ASF DAAC",
        },
        "query": query,
        "spatial_validation": {
            "aoi_crs": "EPSG:4326",
            "area_measurement_crs": metric_crs.to_string(),
            "aoi_area_km2": round(aoi_metric.area / 1_000_000, 3),
            "minimum_aoi_coverage_percent": float(minimum_aoi_coverage_percent),
            "frequency_selection": {
                "frequency": frequency,
                "diagonal_term": term,
                "verified_from_hdf5": False,
            },
        },
        "acceptance": {
            "minimum_unique_acquisition_dates": minimum_dates,
            "requires_same_maturity": True,
            "requires_same_orbit_direction": True,
            "requires_same_relative_orbit": True,
            "requires_same_frame": True,
            "requires_same_bandwidth_mode": True,
            "requires_same_polarization": True,
            "requires_same_processing_type": True,
            "requires_same_processing_center": True,
            "requires_same_observation_source": True,
            "requires_same_crid": True,
            "requires_same_orbit_accuracy": True,
            "requires_same_frame_coverage": True,
            "requires_requested_frequency_and_diagonal_term": True,
            "requires_aoi_footprint_coverage": True,
            "requires_exact_raster_grid": True,
            "requires_gcov_valid_sample_mask": True,
            "catalogue_proves_raster_compatibility": False,
        },
        "metrics": {
            "catalogue_product_count": len(products),
            "compatible_signature_group_count": len(groups_out),
            "qualifying_group_count": len(qualifying),
            "products_rejected_or_not_groupable": len(rejected),
            "products_without_usable_footprint": missing_footprints,
        },
        "groups": groups_out,
        "qualifying_groups": qualifying,
        "rejected_products": rejected,
        "quality": {
            "status": status,
            "warnings": warnings,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--minimum-dates", type=int, default=3)
    parser.add_argument("--minimum-aoi-coverage-percent", type=float, default=90.0)
    parser.add_argument("--frequency", choices=("frequencyA", "frequencyB"), default="frequencyA")
    parser.add_argument("--term", choices=("HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"), default="HHHH")
    args = parser.parse_args()

    try:
        manifest = json.loads(args.catalogue.read_text(encoding="utf-8"))
        report = audit_manifest(
            manifest,
            minimum_dates=args.minimum_dates,
            minimum_aoi_coverage_percent=args.minimum_aoi_coverage_percent,
            frequency=args.frequency,
            term=args.term,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        print(f"RIVERSHIFT_AUDIT_STATUS={report['status']}")
        print(f"RIVERSHIFT_QUALIFYING_GROUPS={report['metrics']['qualifying_group_count']}")
        print(f"RIVERSHIFT_AUDIT_REPORT={args.out}")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
