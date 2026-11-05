from __future__ import annotations

from datetime import date

import pytest

from tools.know_place.series import SeriesPlanError, build_pairwise_series_plan


PAIR_NAMES = [
    "NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_X05026_N_F_J_001.h5",
    "NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001.h5",
    "NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001.h5",
]


def row(name, *, polarization="HH", maturity="PROVISIONAL"):
    return {"granule_name": name, "polarization": polarization, "catalog_maturity": maturity}


def build(rows, **kwargs):
    start_date = kwargs.pop("start_date", date(2026, 6, 20))
    end_date = kwargs.pop("end_date", date(2026, 7, 26))
    return build_pairwise_series_plan(
        rows,
        start_date=start_date,
        end_date=end_date,
        polarization="HH",
        **kwargs,
    )


def test_arbitrary_pair_series_separates_processing_release_chains():
    result = build([row(name) for name in PAIR_NAMES])
    assert result["status"] == "PAIRWISE_SERIES_PLANNED"
    assert result["pair_count"] == 3
    assert result["chain_count"] == 2
    assert result["continuous_chain_eligible"] is False
    assert result["cumulative_displacement_status"] == "SEPARATE_CHAINS_REVIEW_REQUIRED"
    assert [item["release_id"] for item in result["pairs"]] == ["X05026", "P05023", "P05023"]
    assert [item["relation_to_previous"] for item in result["pairs"]] == [
        "FIRST_PAIR", "FIRST_PAIR", "CONTIGUOUS"
    ]
    assert {item["chain_id"] for item in result["pairs"]} == {
        "098-A-HH-PROVISIONAL-X05026",
        "098-A-HH-PROVISIONAL-P05023",
    }
    assert result["pairwise_metrics_are_not_cumulative"] is True


def test_products_crossing_request_boundary_are_excluded():
    with pytest.raises(SeriesPlanError, match="NO_GOFF_PRODUCTS_FULLY_WITHIN_REQUEST_DATE_RANGE"):
        build([row(PAIR_NAMES[0])], start_date=date(2026, 6, 21))


def test_release_variants_are_not_silently_substituted():
    duplicate = PAIR_NAMES[0].replace("_X05026_", "_P05023_")
    with pytest.raises(SeriesPlanError, match="AMBIGUOUS_PRODUCT_RELEASE_VARIANTS"):
        build([row(PAIR_NAMES[0]), row(duplicate)])


def test_user_can_pin_exact_granule_variant():
    duplicate = PAIR_NAMES[0].replace("_X05026_", "_P05023_")
    result = build(
        [row(PAIR_NAMES[0]), row(duplicate)],
        preferred_granules=[PAIR_NAMES[0]],
    )
    assert result["pair_count"] == 1
    assert result["pairs"][0]["granule_name"] == PAIR_NAMES[0]


def test_multiple_orbit_geometries_are_returned_as_separate_chains():
    descending = PAIR_NAMES[0].replace("_098_A_", "_048_D_")
    result = build([row(PAIR_NAMES[0]), row(descending)])
    assert result["chain_count"] == 2
    assert result["geometry_key"] is None
    assert result["cumulative_displacement_status"] == "SEPARATE_CHAINS_REVIEW_REQUIRED"
    assert {item["chain_id"] for item in result["pairs"]} == {
        "098-A-HH-PROVISIONAL-X05026",
        "048-D-HH-PROVISIONAL-X05026",
    }


def test_date_window_filters_products_by_both_acquisition_dates():
    with pytest.raises(SeriesPlanError, match="NO_GOFF_PRODUCTS_FULLY_WITHIN_REQUEST_DATE_RANGE"):
        build([row(PAIR_NAMES[0])], end_date=date(2026, 6, 30))


def test_gap_disables_cumulative_displacement_within_the_same_release_chain():
    # Both are P05023, so the gap is assessed inside one exact processing chain.
    gapped = (
        "NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_"
        "20260726T233919_20260726T233954_20260819T233918_20260819T233953_"
        "P05023_N_F_J_001.h5"
    )
    result = build(
        [row(PAIR_NAMES[1]), row(gapped)],
        end_date=date(2026, 8, 19),
    )
    assert result["chain_count"] == 1
    assert result["continuous_chain_eligible"] is False
    assert result["cumulative_displacement_status"] == "NOT_ELIGIBLE_GAPS_OR_OVERLAPS_OR_SINGLE_PAIR"
    assert [item["relation_to_previous"] for item in result["pairs"]] == ["FIRST_PAIR", "GAP"]


def test_documented_nisar_instrument_gap_is_attached_to_intersecting_pair():
    gap_pair = (
        "NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_"
        "20260726T233919_20260726T233954_20260819T233918_20260819T233953_"
        "P05023_N_F_J_001.h5"
    )
    result = build([row(gap_pair)], end_date=date(2026, 8, 19))
    pair = result["pairs"][0]
    assert len(pair["known_instrument_data_gaps"]) == 1
    gap = pair["known_instrument_data_gaps"][0]
    assert gap["start_utc"] == "2026-07-27T22:03:25Z"
    assert gap["end_utc"] == "2026-08-10T00:55:27Z"
    assert "cannot localize onset" in pair["interval_coverage_warning"]
    assert len(result["known_nisar_data_gaps_intersecting_requested_pairs"]) == 1


def test_single_pair_is_not_a_continuous_or_cumulative_time_series():
    result = build([row(PAIR_NAMES[0])])
    assert result["pair_count"] == 1
    assert result["chain_count"] == 1
    assert result["continuous_chain_eligible"] is False
    assert result["cumulative_displacement_status"] == "NOT_ELIGIBLE_GAPS_OR_OVERLAPS_OR_SINGLE_PAIR"
