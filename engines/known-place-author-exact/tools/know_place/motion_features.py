"""Interpretable motion-dynamics features, not a calibrated hazard detector.

Rates are displacement divided by each product's exact acquisition-midpoint
separation. Rate-change/acceleration is emitted only when adjacent observations
belong to the same verified series chain, have compatible projected lattices,
have sufficient measurements, and neither interval crosses a registered
instrument-data gap. These features must not be treated as an alarm or risk
probability until independently calibrated on held-out event and non-event cases.
"""
from __future__ import annotations

from datetime import timezone
import math
from typing import Any

from .goff_io import GoffReadError, parse_granule_identity

FEATURES_SCHEMA = "know-place-motion-features/1.0"


class MotionFeatureError(ValueError):
    """Motion feature input violates the declared observation contract."""


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _acquisition_midpoints(granule_name: str):
    """Return reference, secondary, and pair midpoints from exact filename times."""
    try:
        identity = parse_granule_identity(granule_name)
    except GoffReadError as exc:
        raise MotionFeatureError(f"FEATURE_GRANULE_IDENTITY_INVALID:{granule_name}") from exc
    reference_midpoint = identity.reference_start + (
        identity.reference_end - identity.reference_start
    ) / 2
    secondary_midpoint = identity.secondary_start + (
        identity.secondary_end - identity.secondary_start
    ) / 2
    interval_seconds = (secondary_midpoint - reference_midpoint).total_seconds()
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise MotionFeatureError(f"FEATURE_INTERVAL_DURATION_INVALID:{granule_name}")
    pair_midpoint = reference_midpoint + (secondary_midpoint - reference_midpoint) / 2
    return reference_midpoint, secondary_midpoint, pair_midpoint


def _feature_row(pair: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(pair, dict):
        raise MotionFeatureError("MOTION_FEATURE_PAIR_MUST_BE_OBJECT")
    status = pair.get("status", "UNKNOWN")
    name = str(pair.get("granule_name", ""))
    interval_days = _finite_number(pair.get("interval_days"))
    midpoints = _acquisition_midpoints(name) if name else None
    if midpoints is not None:
        reference_midpoint, secondary_midpoint, _ = midpoints
        identity_days = (secondary_midpoint - reference_midpoint).total_seconds() / 86400.0
        # The exact duration is recomputed from granule endpoints. A recorded
        # interval field must agree within 1 ms in time, otherwise stop.
        if interval_days is not None and not math.isclose(
            interval_days, identity_days, rel_tol=0.0, abs_tol=1.0 / 86400.0
        ):
            raise MotionFeatureError(f"FEATURE_INTERVAL_DURATION_MISMATCH:{name}")
        interval_days = identity_days
    if interval_days is None or interval_days <= 0:
        return {
            "granule_name": name or None,
            "status": "NOT_COMPUTABLE_INVALID_INTERVAL",
            "interval_days": interval_days,
            "risk_score": None,
            "risk_score_status": "NOT_CALIBRATED",
        }

    stats = pair.get("statistics", {})
    if not isinstance(stats, dict):
        stats = {}
    measurement_computed = status == "METRICS_COMPUTED"
    magnitude_rate = (
        _finite_number(stats.get(
            "aoi_median_magnitude_rate_m_per_day",
            stats.get("crown_median_magnitude_rate_m_per_day"),
        ))
        if measurement_computed else None
    )
    vector_magnitude = (
        _finite_number(stats.get(
            "aoi_mean_vector_magnitude_m",
            stats.get("crown_mean_vector_magnitude_m"),
        ))
        if measurement_computed else None
    )
    east = (
        _finite_number(stats.get("aoi_mean_vector_east_m", stats.get("crown_mean_vector_east_m")))
        if measurement_computed else None
    )
    north = (
        _finite_number(stats.get("aoi_mean_vector_north_m", stats.get("crown_mean_vector_north_m")))
        if measurement_computed else None
    )
    valid_pixels = _finite_number(pair.get("valid_aoi_pixels"))
    total_pixels = _finite_number(pair.get("aoi_total_grid_cells"))
    high_motion = _finite_number(pair.get("high_magnitude_flagged_pixels"))
    valid_fraction = (
        valid_pixels / total_pixels
        if valid_pixels is not None and total_pixels is not None and total_pixels > 0
        else _finite_number(pair.get("valid_aoi_fraction"))
    )
    high_motion_fraction = (
        high_motion / total_pixels
        if high_motion is not None and total_pixels is not None and total_pixels > 0
        else None
    )
    gap_rows = pair.get("known_instrument_data_gaps", [])
    crosses_gap = isinstance(gap_rows, list) and bool(gap_rows)
    grid_ok = pair.get("grid_lattice_compatible_with_previous")
    return {
        "granule_name": name,
        "reference_date": pair.get("reference_date"),
        "secondary_date": pair.get("secondary_date"),
        "chain_id": pair.get("chain_id"),
        "relation_to_previous": pair.get("relation_to_previous"),
        "measurement_status": status,
        "interval_days": interval_days,
        "median_horizontal_displacement_rate_m_per_day": magnitude_rate,
        "mean_vector_east_rate_m_per_day": east / interval_days if east is not None else None,
        "mean_vector_north_rate_m_per_day": north / interval_days if north is not None else None,
        "mean_vector_magnitude_rate_m_per_day": (
            vector_magnitude / interval_days if vector_magnitude is not None else None
        ),
        "mean_vector_azimuth_deg_clockwise_from_north": _finite_number(
            stats.get("aoi_mean_vector_azimuth_deg_clockwise_from_north",
                      stats.get("crown_mean_vector_azimuth_deg_clockwise_from_north"))
        ),
        "median_directional_coherence_R": _finite_number(
            stats.get("aoi_median_directional_coherence_R",
                      stats.get("crown_median_directional_coherence_R"))
        ),
        "valid_aoi_pixels": int(valid_pixels) if valid_pixels is not None else None,
        "valid_aoi_fraction": valid_fraction,
        "high_magnitude_flagged_pixels": int(high_motion) if high_motion is not None else None,
        "high_magnitude_flagged_fraction": high_motion_fraction,
        "spatial_uncertainty_status": pair.get("spatial_block_bootstrap_uncertainty", {}).get("status"),
        "crosses_registered_instrument_gap": crosses_gap,
        "grid_lattice_compatible_with_previous": grid_ok,
        "vector_rate_change_eligible": False,
        "vector_rate_change_magnitude_m_per_day": None,
        "vector_rate_acceleration_m_per_day_squared": None,
        "rate_change_block_reason": (
            "PAIR_MEASUREMENT_NOT_COMPUTED" if status != "METRICS_COMPUTED"
            else "INSTRUMENT_GAP_CROSSES_INTERVAL" if crosses_gap
            else "NOT_AN_ADJACENT_PAIR"
        ),
        "risk_score": None,
        "risk_score_status": "NOT_CALIBRATED",
        "detection_status": "NOT_EVALUATED",
    }


def build_motion_dynamics_features(
    pairs: list[dict[str, Any]],
    *,
    pairwise_series_plan: dict[str, Any] | None = None,
    global_grid_compatibility_status: str = "NOT_EVALUATED",
) -> dict[str, Any]:
    """Build pair-level interval rates and gated changes between adjacent vectors."""
    if not isinstance(pairs, list):
        raise MotionFeatureError("MOTION_FEATURE_PAIRS_MUST_BE_ARRAY")
    features = [_feature_row(pair) for pair in pairs]
    index_by_granule = {
        row["granule_name"]: index for index, row in enumerate(features)
        if isinstance(row.get("granule_name"), str) and row["granule_name"]
    }

    for chain in (pairwise_series_plan or {}).get("chains", []):
        chain_id = chain.get("chain_id")
        chain_pairs = chain.get("pairs", [])
        if not isinstance(chain_pairs, list):
            continue
        ordered_features: list[dict[str, Any]] = []
        for planned in chain_pairs:
            index = index_by_granule.get(planned.get("granule_name"))
            if index is not None:
                ordered_features.append(features[index])
        previous: dict[str, Any] | None = None
        for current in ordered_features:
            current["chain_id"] = chain_id
            if previous is None:
                current["rate_change_block_reason"] = "FIRST_PAIR_IN_CHAIN"
                previous = current
                continue
            reasons: list[str] = []
            if current.get("measurement_status") != "METRICS_COMPUTED" or previous.get("measurement_status") != "METRICS_COMPUTED":
                reasons.append("PAIR_MEASUREMENT_NOT_COMPUTED")
            if current.get("relation_to_previous") != "CONTIGUOUS":
                reasons.append(str(current.get("relation_to_previous") or "PAIR_NOT_CONTIGUOUS"))
            if current.get("crosses_registered_instrument_gap") or previous.get("crosses_registered_instrument_gap"):
                reasons.append("INSTRUMENT_GAP_CROSSES_INTERVAL")
            if current.get("grid_lattice_compatible_with_previous") is not True:
                reasons.append("PROJECTED_GRID_LATTICE_NOT_VERIFIED_COMPATIBLE")
            prev_granule = previous.get("granule_name")
            current_granule = current.get("granule_name")
            if not prev_granule or not current_granule:
                reasons.append("GRANULE_IDENTITY_MISSING")
            if previous.get("chain_id") != current.get("chain_id"):
                reasons.append("PROCESSING_CHAIN_MISMATCH")
            if (
                previous.get("mean_vector_east_rate_m_per_day") is None
                or previous.get("mean_vector_north_rate_m_per_day") is None
                or current.get("mean_vector_east_rate_m_per_day") is None
                or current.get("mean_vector_north_rate_m_per_day") is None
            ):
                reasons.append("VECTOR_RATE_UNAVAILABLE")

            if not reasons:
                _, _, previous_pair_midpoint = _acquisition_midpoints(str(prev_granule))
                _, _, current_pair_midpoint = _acquisition_midpoints(str(current_granule))
                midpoint_delta_days = abs(
                    (current_pair_midpoint - previous_pair_midpoint).total_seconds()
                ) / 86400.0
                if not math.isfinite(midpoint_delta_days) or midpoint_delta_days <= 0:
                    reasons.append("PAIR_MIDPOINT_ORDER_INVALID")
                else:
                    delta_e = (
                        current["mean_vector_east_rate_m_per_day"]
                        - previous["mean_vector_east_rate_m_per_day"]
                    )
                    delta_n = (
                        current["mean_vector_north_rate_m_per_day"]
                        - previous["mean_vector_north_rate_m_per_day"]
                    )
                    change = math.hypot(delta_e, delta_n)
                    current["vector_rate_change_eligible"] = True
                    current["vector_rate_change_magnitude_m_per_day"] = change
                    current["vector_rate_acceleration_m_per_day_squared"] = change / midpoint_delta_days
                    current["rate_change_time_separation_days"] = midpoint_delta_days
                    current["rate_change_block_reason"] = None
            if reasons:
                current["vector_rate_change_eligible"] = False
                current["vector_rate_change_magnitude_m_per_day"] = None
                current["vector_rate_acceleration_m_per_day_squared"] = None
                current["rate_change_block_reason"] = ";".join(sorted(set(reasons)))
            previous = current

    measured_feature_count = sum(
        row.get("median_horizontal_displacement_rate_m_per_day") is not None
        and row.get("mean_vector_east_rate_m_per_day") is not None
        and row.get("mean_vector_north_rate_m_per_day") is not None
        for row in features
    )
    if measured_feature_count == 0:
        overall_status = "INSUFFICIENT_MEASUREMENT_FEATURES"
    elif measured_feature_count < len(features):
        overall_status = "PARTIAL_DESCRIPTIVE_MOTION_FEATURES"
    else:
        overall_status = "DESCRIPTIVE_MOTION_FEATURES_COMPUTED"
    return {
        "schema_version": FEATURES_SCHEMA,
        "status": overall_status,
        "measured_feature_count": measured_feature_count,
        "unmeasured_feature_count": len(features) - measured_feature_count,
        "grid_compatibility_status": global_grid_compatibility_status,
        "pair_count": len(features),
        "pairs": features,
        "risk_score": None,
        "hazard_detection_status": "NOT_EVALUATED",
        "interpretation": {
            "median_horizontal_displacement_rate": "Median pixelwise pairwise horizontal displacement magnitude divided by exact acquisition-midpoint separation; interval average, not instantaneous speed.",
            "mean_vector_rate": "AOI mean vector displacement divided by the same exact interval; horizontal only under zero-vertical-motion projection assumptions.",
            "vector_rate_acceleration": "Magnitude of the change between adjacent mean horizontal vector rates divided by separation between interval midpoints. Emitted only for contiguous, grid-compatible, gap-free, same-chain computed pairs.",
            "risk_score": "Not provided: no calibrated hazard model has been validated on independent event and non-event sites.",
        },
        "limitations": [
            "A pairwise interval average cannot locate the motion onset or trajectory inside the interval.",
            "Geometry/DEM, stable-reference bias, release differences and systematic sensor errors are not fully represented by the spatial bootstrap interval.",
            "Rate change is a descriptive feature, not a calibrated event probability or operational alarm.",
        ],
    }
