from __future__ import annotations

import pytest

from tools.know_place.goff_io import parse_granule_identity
from tools.know_place.motion_features import (
    MotionFeatureError,
    build_motion_dynamics_features,
)
from tools.know_place.series import build_pairwise_series_plan

PAIR_NAMES = [
    "NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_P05023_N_F_J_001.h5",
    "NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_N_F_J_001.h5",
    "NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001.h5",
]


def plan(names):
    return build_pairwise_series_plan(
        [
            {"granule_name": name, "polarization": "HH", "catalog_maturity": "PROVISIONAL"}
            for name in names
        ],
        start_date=__import__("datetime").date(2026, 6, 20),
        end_date=__import__("datetime").date(2026, 7, 26),
        polarization="HH",
        track="098",
        direction="A",
    )


def pair_result(name, *, east, north, gap=False, grid_ok=None, status="METRICS_COMPUTED"):
    identity = parse_granule_identity(name)
    ref_mid = identity.reference_start + (identity.reference_end - identity.reference_start) / 2
    sec_mid = identity.secondary_start + (identity.secondary_end - identity.secondary_start) / 2
    days = (sec_mid - ref_mid).total_seconds() / 86400
    mag = (east ** 2 + north ** 2) ** 0.5
    return {
        "granule_name": name,
        "reference_date": identity.reference_start.date().isoformat(),
        "secondary_date": identity.secondary_start.date().isoformat(),
        "chain_id": "098-A-HH-PROVISIONAL-P05023",
        "relation_to_previous": "FIRST_PAIR" if name == PAIR_NAMES[0] else "CONTIGUOUS",
        "known_instrument_data_gaps": [{"start_utc": "2026-07-27T22:03:25Z"}] if gap else [],
        "grid_lattice_compatible_with_previous": grid_ok,
        "interval_days": days,
        "status": status,
        "valid_aoi_pixels": 100,
        "aoi_total_grid_cells": 120,
        "valid_aoi_fraction": 100 / 120,
        "high_magnitude_flagged_pixels": 2,
        "statistics": {
            "aoi_median_horizontal_magnitude_m": mag,
            "aoi_median_magnitude_rate_m_per_day": mag / days,
            "aoi_mean_vector_east_m": east,
            "aoi_mean_vector_north_m": north,
            "aoi_mean_vector_magnitude_m": mag,
            "aoi_mean_vector_azimuth_deg_clockwise_from_north": 90.0,
            "aoi_median_directional_coherence_R": 0.9,
        },
    }


def test_contiguous_gap_free_same_grid_chain_yields_known_vector_rate_change():
    series_plan = plan(PAIR_NAMES)
    measured = [
        pair_result(PAIR_NAMES[0], east=1.0, north=0.0, grid_ok=None),
        pair_result(PAIR_NAMES[1], east=2.0, north=0.0, grid_ok=True),
        pair_result(PAIR_NAMES[2], east=4.0, north=0.0, grid_ok=True),
    ]
    features = build_motion_dynamics_features(
        measured,
        pairwise_series_plan=series_plan,
        global_grid_compatibility_status="CONSISTENT_LATTICE_WITHIN_CHAINS",
    )

    assert features["status"] == "DESCRIPTIVE_MOTION_FEATURES_COMPUTED"
    assert features["hazard_detection_status"] == "NOT_EVALUATED"
    assert features["risk_score"] is None
    first, second, third = features["pairs"]
    assert first["rate_change_block_reason"] == "FIRST_PAIR_IN_CHAIN"
    assert second["vector_rate_change_eligible"] is True
    assert second["vector_rate_change_magnitude_m_per_day"] == pytest.approx(
        second["mean_vector_east_rate_m_per_day"] - first["mean_vector_east_rate_m_per_day"]
    )
    assert second["vector_rate_acceleration_m_per_day_squared"] > 0
    assert third["vector_rate_change_eligible"] is True
    assert "not instantaneous" in features["interpretation"]["median_horizontal_displacement_rate"]


def test_registered_mission_gap_blocks_vector_rate_acceleration_but_keeps_interval_rate():
    gap_name = (
        "NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_"
        "20260726T233919_20260726T233954_20260819T233918_20260819T233953_"
        "P05023_N_F_J_001.h5"
    )
    base_names = [PAIR_NAMES[2], gap_name]
    series_plan = build_pairwise_series_plan(
        [{"granule_name": name, "polarization": "HH", "catalog_maturity": "PROVISIONAL"} for name in base_names],
        start_date=__import__("datetime").date(2026, 7, 14),
        end_date=__import__("datetime").date(2026, 8, 19),
        polarization="HH",
        track="098",
        direction="A",
    )
    measured = [
        pair_result(PAIR_NAMES[2], east=4.0, north=0.0, grid_ok=None),
        pair_result(gap_name, east=8.0, north=0.0, gap=True, grid_ok=True),
    ]
    result = build_motion_dynamics_features(measured, pairwise_series_plan=series_plan)
    row = result["pairs"][1]
    assert row["median_horizontal_displacement_rate_m_per_day"] is not None
    assert row["vector_rate_change_eligible"] is False
    assert "INSTRUMENT_GAP_CROSSES_INTERVAL" in row["rate_change_block_reason"]
    assert row["risk_score"] is None


@pytest.mark.parametrize("block_reason,grid_ok,gap,status", [
    ("GRID", False, False, "METRICS_COMPUTED"),
    ("GAP", True, True, "METRICS_COMPUTED"),
    ("NO_METRICS", True, False, "INSUFFICIENT_AOI_VALID_PIXELS"),
])
def test_uncomparable_pair_blocks_rate_change(block_reason, grid_ok, gap, status):
    names = [PAIR_NAMES[0], PAIR_NAMES[1]]
    measured = [
        pair_result(names[0], east=1.0, north=0.0, grid_ok=None),
        pair_result(names[1], east=2.0, north=0.0, grid_ok=grid_ok, gap=gap, status=status),
    ]
    result = build_motion_dynamics_features(measured, pairwise_series_plan=plan(names))
    row = result["pairs"][1]
    assert row["vector_rate_change_eligible"] is False
    assert row["vector_rate_acceleration_m_per_day_squared"] is None
    assert row["risk_score_status"] == "NOT_CALIBRATED"
    if block_reason == "GRID":
        assert "PROJECTED_GRID_LATTICE_NOT_VERIFIED_COMPATIBLE" in row["rate_change_block_reason"]
    elif block_reason == "GAP":
        assert "INSTRUMENT_GAP_CROSSES_INTERVAL" in row["rate_change_block_reason"]
    else:
        assert "PAIR_MEASUREMENT_NOT_COMPUTED" in row["rate_change_block_reason"]


def test_invalid_filename_fails_closed():
    with pytest.raises(MotionFeatureError, match="FEATURE_GRANULE_IDENTITY_INVALID"):
        build_motion_dynamics_features([{"granule_name": "not-a-GOFF.h5", "status": "METRICS_COMPUTED"}])


def test_all_unmeasurable_pairs_report_insufficient_feature_coverage():
    names = [PAIR_NAMES[0], PAIR_NAMES[1]]
    plan_payload = plan(names)
    measured = [
        pair_result(names[0], east=1.0, north=0.0, grid_ok=None, status="INSUFFICIENT_AOI_VALID_PIXELS"),
        pair_result(names[1], east=2.0, north=0.0, grid_ok=True, status="INSUFFICIENT_AOI_VALID_PIXELS"),
    ]
    result = build_motion_dynamics_features(measured, pairwise_series_plan=plan_payload)
    assert result["status"] == "INSUFFICIENT_MEASUREMENT_FEATURES"
    assert result["measured_feature_count"] == 0
    assert result["unmeasured_feature_count"] == 2
    assert all(row["median_horizontal_displacement_rate_m_per_day"] is None for row in result["pairs"])
    assert result["hazard_detection_status"] == "NOT_EVALUATED"
