"""Versioned request contract for arbitrary polygon/date-range Know Place jobs.

This parser intentionally validates requests only. It does not assert that
catalog coverage exists, that a displacement is measurable, or that an event
has been detected. Source-adapter availability and scientific status are
reported by later pipeline stages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re
from typing import Any

from .geometry import parse_polygon_wkt
from .goff_io import GoffReadError

REQUEST_SCHEMA = "know-place-aoi-request/1.0"
SUPPORTED_HAZARDS = {"landslide", "glacier_collapse", "ice_rock_avalanche", "mixed"}
SUPPORTED_ADAPTERS = {"NISAR_GOFF"}
SUPPORTED_MODES = {"retrospective_validation", "operational_monitoring", "exploratory"}


class AOIRequestError(ValueError):
    """A user AOI request is malformed, unsupported or scientifically ambiguous."""


@dataclass(frozen=True)
class AOIRequest:
    schema_version: str
    aoi_wkt: str
    scope_aoi_wkt: str | None
    aoi_crs: str
    start_date: date
    end_date: date
    hazard_mode: str
    analysis_mode: str
    source_adapters: tuple[str, ...]
    polarization: str
    track: str | None
    direction: str | None
    preferred_granules: tuple[str, ...]
    allowed_release_ids: tuple[str, ...]
    allowed_maturities: tuple[str, ...]
    reference_wkt: str | None
    background_correction_policy: str
    reference_buffer_m: float
    geometry_height_m: float | None
    min_snr: float
    max_horizontal_magnitude_m: float
    magnitude_policy: str
    coherence_window: int
    minimum_valid_neighbours: int
    request_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return stable, JSON-safe normalized parameters (not raw secrets)."""
        return {
            "schema_version": self.schema_version,
            "aoi": {"type": "Polygon", "wkt": self.aoi_wkt, "crs": self.aoi_crs, "role": "measurement"},
            "scope_aoi": (
                {"type": "Polygon", "wkt": self.scope_aoi_wkt, "crs": self.aoi_crs, "role": "outer_selection_boundary"}
                if self.scope_aoi_wkt else None
            ),
            "date_range": {
                "start": self.start_date.isoformat(),
                "end": self.end_date.isoformat(),
                "inclusive": True,
                "timezone": "UTC",
            },
            "hazard_mode": self.hazard_mode,
            "analysis_mode": self.analysis_mode,
            "source_adapters": list(self.source_adapters),
            "polarization": self.polarization,
            "product_selection": {"track": self.track, "direction": self.direction, "preferred_granules": list(self.preferred_granules), "allowed_release_ids": list(self.allowed_release_ids), "allowed_maturities": list(self.allowed_maturities)},
            "reference": {
                "policy": self.background_correction_policy,
                "polygon_wkt": self.reference_wkt,
                "fallback_buffer_m": self.reference_buffer_m,
                "warning": (
                    "Local context assumes most valid pixels outside the AOI are stable; inspect the reference map and sensitivity."
                    if self.background_correction_policy == "local_context_component_median"
                    else "Background correction is not applied."
                    if self.background_correction_policy == "none"
                    else "Independent user-drawn background polygon; geometry and grid support are checked, but stability is not independently verified."
                ),
            },
            "geometry_policy": {
                "constant_hae_m": self.geometry_height_m,
                "source": "explicit_user_constant_hae" if self.geometry_height_m is not None else "product_height_axis_midpoint_approximation",
                "warning": "A constant height is an approximation, not a DEM-derived per-pixel terrain height.",
            },
            "quality_policy": {
                "name": "nisar_goff_exploratory_v1",
                "minimum_snr": self.min_snr,
                "maximum_horizontal_magnitude_m": self.max_horizontal_magnitude_m,
                "magnitude_policy": self.magnitude_policy,
                "gross_outlier_policy": (
                    "reject_above_threshold_not_clip"
                    if self.magnitude_policy == "reject_above_threshold"
                    else "preserve_but_flag_above_threshold"
                ),
            },
            "coherence_policy": {
                "window_size": self.coherence_window,
                "minimum_valid_neighbours": self.minimum_valid_neighbours,
                "policy_status": "explicit_versioned_user_request_not_author_parity",
            },
            "request_sha256": self.request_sha256,
        }


def _strict_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise AOIRequestError(f"{field.upper()}_MUST_BE_ISO_DATE")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AOIRequestError(f"{field.upper()}_MUST_BE_ISO_DATE") from exc
    if parsed.isoformat() != value:
        raise AOIRequestError(f"{field.upper()}_MUST_BE_CANONICAL_ISO_DATE")
    return parsed


def _canonical_wkt(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AOIRequestError(f"{field.upper()}_WKT_REQUIRED")
    try:
        ring = parse_polygon_wkt(value)
    except GoffReadError as exc:
        raise AOIRequestError(f"{field.upper()}_GEOMETRY_INVALID:{exc}") from exc
    return "POLYGON ((" + ", ".join(f"{lon:.9f} {lat:.9f}" for lon, lat in ring) + "))"


def validate_aoi_request(payload: dict[str, Any]) -> AOIRequest:
    """Validate and normalize a v1 request; fail closed on unsupported geometry."""
    if not isinstance(payload, dict):
        raise AOIRequestError("REQUEST_MUST_BE_JSON_OBJECT")
    if payload.get("schema_version") != REQUEST_SCHEMA:
        raise AOIRequestError("REQUEST_SCHEMA_VERSION_UNSUPPORTED")

    aoi = payload.get("aoi")
    if not isinstance(aoi, dict):
        raise AOIRequestError("AOI_OBJECT_REQUIRED")
    crs = str(aoi.get("crs", "EPSG:4326")).upper()
    if crs not in {"EPSG:4326", "OGC:CRS84"}:
        raise AOIRequestError("AOI_CRS_MUST_BE_EPSG4326_OR_CRS84")
    aoi_wkt = _canonical_wkt(aoi.get("wkt"), "aoi")
    scope_config = payload.get("scope_aoi")
    if scope_config is not None and not isinstance(scope_config, dict):
        raise AOIRequestError("SCOPE_AOI_MUST_BE_OBJECT")
    scope_aoi_wkt = None
    if isinstance(scope_config, dict):
        scope_crs = str(scope_config.get("crs", "EPSG:4326")).upper()
        if scope_crs not in {"EPSG:4326", "OGC:CRS84"}:
            raise AOIRequestError("SCOPE_AOI_CRS_MUST_BE_EPSG4326_OR_CRS84")
        scope_aoi_wkt = _canonical_wkt(scope_config.get("wkt"), "scope_aoi")

    dates = payload.get("date_range")
    if not isinstance(dates, dict):
        raise AOIRequestError("DATE_RANGE_OBJECT_REQUIRED")
    start_date = _strict_date(dates.get("start"), "start_date")
    end_date = _strict_date(dates.get("end"), "end_date")
    if start_date > end_date:
        raise AOIRequestError("DATE_RANGE_START_AFTER_END")
    if dates.get("inclusive", True) is not True:
        raise AOIRequestError("DATE_RANGE_MUST_BE_INCLUSIVE")

    hazard_mode = str(payload.get("hazard_mode", "mixed")).lower()
    if hazard_mode not in SUPPORTED_HAZARDS:
        raise AOIRequestError("HAZARD_MODE_UNSUPPORTED")
    analysis_mode = str(payload.get("analysis_mode", "exploratory")).lower()
    if analysis_mode not in SUPPORTED_MODES:
        raise AOIRequestError("ANALYSIS_MODE_UNSUPPORTED")

    adapters = payload.get("source_adapters", ["NISAR_GOFF"])
    if not isinstance(adapters, list) or not adapters:
        raise AOIRequestError("AT_LEAST_ONE_SOURCE_ADAPTER_REQUIRED")
    normalized_adapters = tuple(sorted({str(item).upper() for item in adapters}))
    unsupported = sorted(set(normalized_adapters) - SUPPORTED_ADAPTERS)
    if unsupported:
        raise AOIRequestError("SOURCE_ADAPTER_UNSUPPORTED:" + ",".join(unsupported))

    polarization = str(payload.get("polarization", "HH")).upper()
    if polarization not in {"HH", "HV", "VV", "VH"}:
        raise AOIRequestError("POLARIZATION_UNSUPPORTED")
    selection = payload.get("product_selection", {})
    if not isinstance(selection, dict):
        raise AOIRequestError("PRODUCT_SELECTION_MUST_BE_OBJECT")
    raw_track = selection.get("track")
    track = None if raw_track in (None, "") else str(raw_track).zfill(3)
    if track is not None and (len(track) != 3 or not track.isdigit()):
        raise AOIRequestError("TRACK_MUST_BE_THREE_DIGITS")
    raw_direction = selection.get("direction")
    direction = None if raw_direction in (None, "") else str(raw_direction).upper()
    direction_aliases = {"A": "A", "ASC": "A", "ASCENDING": "A", "D": "D", "DESC": "D", "DESCENDING": "D"}
    if direction is not None:
        if direction not in direction_aliases:
            raise AOIRequestError("DIRECTION_MUST_BE_ASCENDING_OR_DESCENDING")
        direction = direction_aliases[direction]
    raw_preferred = selection.get("preferred_granules", [])
    if not isinstance(raw_preferred, list) or any(not isinstance(item, str) or not item.strip() for item in raw_preferred):
        raise AOIRequestError("PREFERRED_GRANULES_MUST_BE_STRING_ARRAY")
    preferred_granules = tuple(sorted(set(item.strip() for item in raw_preferred)))
    raw_release_ids = selection.get("allowed_release_ids", [])
    if not isinstance(raw_release_ids, list) or any(not isinstance(item, str) or not item.strip() for item in raw_release_ids):
        raise AOIRequestError("ALLOWED_RELEASE_IDS_MUST_BE_STRING_ARRAY")
    allowed_release_ids = tuple(sorted({item.strip().upper() for item in raw_release_ids}))
    if any(re.fullmatch(r"[A-Z][0-9]{5}", item) is None for item in allowed_release_ids):
        raise AOIRequestError("ALLOWED_RELEASE_ID_FORMAT_INVALID")
    raw_maturities = selection.get("allowed_maturities", ["PROVISIONAL"])
    if not isinstance(raw_maturities, list) or not raw_maturities:
        raise AOIRequestError("ALLOWED_MATURITIES_MUST_BE_NONEMPTY_ARRAY")
    allowed_maturities = tuple(sorted({str(item).upper() for item in raw_maturities}))
    if set(allowed_maturities) - {"PROVISIONAL", "BETA"}:
        raise AOIRequestError("CATALOG_MATURITY_UNSUPPORTED")

    reference = payload.get("reference")
    if reference is not None and not isinstance(reference, dict):
        raise AOIRequestError("REFERENCE_MUST_BE_OBJECT")
    reference_config = reference or {}
    reference_policy = str(
        reference_config.get("policy", "local_context_component_median")
    )
    allowed_reference_policies = {
        "external_reference_polygon_component_median",
        "local_context_component_median",
        "none",
    }
    if reference_policy not in allowed_reference_policies:
        raise AOIRequestError("REFERENCE_POLICY_UNSUPPORTED")
    reference_wkt = None
    if reference_policy == "external_reference_polygon_component_median":
        reference_wkt = _canonical_wkt(reference_config.get("polygon_wkt"), "reference")
    elif reference_config.get("polygon_wkt") is not None:
        raise AOIRequestError("REFERENCE_POLYGON_NOT_ALLOWED_FOR_SELECTED_POLICY")
    # Independent measurement/reference disjointness and native-grid support
    # are revalidated after the exact GOFF grid has been inspected.
    try:
        reference_buffer_m = float(reference_config.get("fallback_buffer_m", 2000.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AOIRequestError("REFERENCE_BUFFER_MUST_BE_NUMERIC") from exc
    if not math.isfinite(reference_buffer_m) or reference_buffer_m < 0:
        raise AOIRequestError("REFERENCE_BUFFER_M_INVALID")
    if reference_wkt is None and reference_buffer_m <= 0:
        raise AOIRequestError("POSITIVE_REFERENCE_BUFFER_REQUIRED_WITHOUT_REFERENCE_POLYGON")

    geometry = payload.get("geometry_policy", {})
    if not isinstance(geometry, dict):
        raise AOIRequestError("GEOMETRY_POLICY_MUST_BE_OBJECT")
    raw_height = geometry.get("constant_hae_m")
    geometry_height_m = None
    if raw_height is not None:
        try:
            geometry_height_m = float(raw_height)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AOIRequestError("GEOMETRY_HEIGHT_MUST_BE_NUMERIC") from exc
        if not math.isfinite(geometry_height_m):
            raise AOIRequestError("GEOMETRY_HEIGHT_MUST_BE_FINITE")
    if analysis_mode == "operational_monitoring":
        raise AOIRequestError(
            "OPERATIONAL_MODE_BLOCKED_DEM_BACKED_GEOMETRY_REQUIRED",
        )

    quality = payload.get("quality_policy", {})
    if not isinstance(quality, dict):
        raise AOIRequestError("QUALITY_POLICY_MUST_BE_OBJECT")
    try:
        min_snr = float(quality.get("minimum_snr", 5.0))
        max_magnitude = float(quality.get("maximum_horizontal_magnitude_m", 10.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AOIRequestError("QUALITY_THRESHOLDS_MUST_BE_NUMERIC") from exc
    if not math.isfinite(min_snr) or min_snr < 0:
        raise AOIRequestError("MINIMUM_SNR_INVALID")
    if not math.isfinite(max_magnitude) or max_magnitude <= 0:
        raise AOIRequestError("MAXIMUM_HORIZONTAL_MAGNITUDE_INVALID")
    # A >10 m vector may be either a GOFF blunder or real rapid movement.
    # Generic requests preserve and flag it; method-specific paper replay must
    # explicitly choose reject_above_threshold in its versioned request.
    default_magnitude_policy = "flag_above_threshold_keep"
    magnitude_policy = str(quality.get("magnitude_policy", default_magnitude_policy))
    if magnitude_policy not in {"reject_above_threshold", "flag_above_threshold_keep"}:
        raise AOIRequestError("MAGNITUDE_POLICY_UNSUPPORTED")
    if analysis_mode == "operational_monitoring":
        raise AOIRequestError("OPERATIONAL_MODE_BLOCKED_UNVALIDATED_SCIENCE")

    coherence = payload.get("coherence_policy", {})
    if not isinstance(coherence, dict):
        raise AOIRequestError("COHERENCE_POLICY_MUST_BE_OBJECT")
    window = coherence.get("window_size", 5)
    neighbours = coherence.get("minimum_valid_neighbours", 1)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1 or window % 2 == 0:
        raise AOIRequestError("COHERENCE_WINDOW_MUST_BE_POSITIVE_ODD_INTEGER")
    if isinstance(neighbours, bool) or not isinstance(neighbours, int) or not (1 <= neighbours <= window * window):
        raise AOIRequestError("COHERENCE_NEIGHBOURS_OUT_OF_RANGE")

    normalized = {
        "schema_version": REQUEST_SCHEMA,
        "aoi": {"wkt": aoi_wkt, "crs": "EPSG:4326", "role": "measurement"},
        "scope_aoi": {"wkt": scope_aoi_wkt, "crs": "EPSG:4326", "role": "outer_selection_boundary"} if scope_aoi_wkt else None,
        "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat(), "inclusive": True},
        "hazard_mode": hazard_mode,
        "analysis_mode": analysis_mode,
        "source_adapters": list(normalized_adapters),
        "polarization": polarization,
        "product_selection": {"track": track, "direction": direction, "preferred_granules": list(preferred_granules), "allowed_release_ids": list(allowed_release_ids), "allowed_maturities": list(allowed_maturities)},
        "reference": {"polygon_wkt": reference_wkt, "policy": reference_policy, "fallback_buffer_m": reference_buffer_m},
        "geometry_policy": {"constant_hae_m": geometry_height_m},
        "quality_policy": {
            "minimum_snr": min_snr,
            "maximum_horizontal_magnitude_m": max_magnitude,
            "magnitude_policy": magnitude_policy,
        },
        "coherence_policy": {"window_size": window, "minimum_valid_neighbours": neighbours},
    }
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return AOIRequest(
        schema_version=REQUEST_SCHEMA,
        aoi_wkt=aoi_wkt,
        scope_aoi_wkt=scope_aoi_wkt,
        aoi_crs="EPSG:4326",
        start_date=start_date,
        end_date=end_date,
        hazard_mode=hazard_mode,
        analysis_mode=analysis_mode,
        source_adapters=normalized_adapters,
        polarization=polarization,
        track=track,
        direction=direction,
        preferred_granules=preferred_granules,
        allowed_release_ids=allowed_release_ids,
        allowed_maturities=allowed_maturities,
        reference_wkt=reference_wkt,
        background_correction_policy=reference_policy,
        reference_buffer_m=reference_buffer_m,
        geometry_height_m=geometry_height_m,
        min_snr=min_snr,
        max_horizontal_magnitude_m=max_magnitude,
        magnitude_policy=magnitude_policy,
        coherence_window=window,
        minimum_valid_neighbours=neighbours,
        request_sha256=digest,
    )
