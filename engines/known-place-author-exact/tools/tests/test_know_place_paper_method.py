from __future__ import annotations

import numpy as np
import pytest

from tools.know_place.paper_method import (
    PAPER_INTERVALS,
    ScientificInputError,
    apply_paper_quality_gates,
    componentwise_background_correction,
    directional_coherence,
    empirical_percentile,
    project_offsets_to_horizontal,
    size_matched_spatial_controls,
    summarize_crown,
    validate_five_pair_inventory,
)


def test_horizontal_projection_matches_hand_calculated_vectors():
    # AT=1m east; SR=0.1m, incidence=30deg, horizontal LOS points north.
    east, north = project_offsets_to_horizontal(
        np.array([[1.0]]), np.array([[0.1]]), 1.0, 0.0,
        0.0, 1.0, 30.0,
    )
    assert east[0, 0] == pytest.approx(1.0)
    assert north[0, 0] == pytest.approx(-0.2)


def test_projection_fails_on_zero_horizontal_los_vector():
    with pytest.raises(ScientificInputError, match="LOS-vector norm"):
        project_offsets_to_horizontal(
            np.ones((2, 2)), np.ones((2, 2)), 1.0, 0.0,
            0.0, 0.0, 39.1,
        )


def test_quality_gates_reject_snr_and_gross_offsets_without_clipping():
    east = np.array([[3.0, 11.0, 1.0, np.nan]])
    north = np.zeros_like(east)
    snr = np.array([[5.0, 9.0, 4.0, 8.0]])
    valid, counts, magnitude = apply_paper_quality_gates(east, north, snr)
    assert valid.tolist() == [[True, False, False, False]]
    assert magnitude[0, 1] == 11.0
    assert counts.input_valid == 4
    assert counts.finite_offsets_and_snr == 3
    assert counts.snr_pass == 2
    assert counts.final_valid == 1
    assert counts.rejected_snr == 1
    assert counts.rejected_magnitude == 1
    assert counts.rejected_nonfinite == 1


def test_componentwise_background_correction_removes_known_bias():
    east = np.full((5, 5), 2.0)
    north = np.full((5, 5), -3.0)
    crown = np.zeros((5, 5), bool)
    crown[2, 2] = True
    east[2, 2] = 4.5
    north[2, 2] = 1.0
    box = np.ones((5, 5), bool)
    valid = np.ones((5, 5), bool)
    ce, cn, evidence = componentwise_background_correction(east, north, valid, box, crown)
    assert ce[2, 2] == pytest.approx(2.5)
    assert cn[2, 2] == pytest.approx(4.0)
    assert np.nanmedian(ce[box & ~crown]) == pytest.approx(0.0)
    assert np.nanmedian(cn[box & ~crown]) == pytest.approx(0.0)
    assert evidence["background_valid_pixels"] == 24
    assert evidence["crown_valid_pixels"] == 1


def test_background_correction_fails_if_reference_has_no_valid_pixels():
    box = np.ones((2, 2), bool)
    crown = box.copy()
    with pytest.raises(ScientificInputError, match="NO_VALID_BACKGROUND_PIXELS"):
        componentwise_background_correction(
            np.ones((2, 2)), np.ones((2, 2)), box, box, crown
        )


def test_directional_coherence_is_one_for_uniform_vectors():
    east = np.ones((7, 7))
    north = np.zeros((7, 7))
    valid = np.ones((7, 7), bool)
    R = directional_coherence(east, north, valid)
    assert np.allclose(R, 1.0)


def test_directional_coherence_detects_opposing_vectors():
    east = np.ones((5, 5))
    north = np.zeros((5, 5))
    east[:, 3:] = -1.0
    R = directional_coherence(east, north, np.ones((5, 5), bool))
    assert R[2, 2] < 1.0
    assert 0.0 <= R[2, 2] <= 1.0


def test_crown_summary_does_not_confuse_median_magnitude_with_mean_vector():
    east = np.array([[1.0, 0.0]])
    north = np.array([[0.0, 1.0]])
    valid = np.ones((1, 2), bool)
    crown = valid.copy()
    R = np.ones((1, 2))
    summary = summarize_crown(east, north, valid, crown, R, interval_days=12)
    assert summary["crown_median_horizontal_magnitude_m"] == pytest.approx(1.0)
    assert summary["crown_mean_vector_magnitude_m"] == pytest.approx(np.sqrt(0.5))
    assert summary["crown_mean_vector_azimuth_deg_clockwise_from_north"] == pytest.approx(45.0)
    assert summary["crown_median_magnitude_rate_m_per_day"] == pytest.approx(1 / 12)


def test_empirical_percentile_uses_explicit_less_than_or_equal_convention():
    assert empirical_percentile([1.0, 2.0, 3.0, 4.0], 3.0) == pytest.approx(75.0)
    with pytest.raises(ScientificInputError, match="EMPTY_NULL"):
        empirical_percentile([], 1.0)


def test_spatial_controls_are_deterministic_and_report_rejections():
    h = w = 35
    mag = np.arange(h * w, dtype=float).reshape(h, w) / 100.0
    R = np.full((h, w), 0.7)
    valid = np.ones((h, w), bool)
    box = np.ones((h, w), bool)
    crown = np.zeros((h, w), bool)
    crown[15:20, 15:20] = True
    first = size_matched_spatial_controls(
        mag, R, valid, box, crown, draws=100, seed=1234,
    )
    second = size_matched_spatial_controls(
        mag, R, valid, box, crown, draws=100, seed=1234,
    )
    assert first["displacement_control_values_m"] == second["displacement_control_values_m"]
    assert first["draws_accepted"] + first["draws_rejected"] == 100
    assert first["seed"] == 1234
    assert np.allclose(first["R_distribution_for_percentile"], 0.7)


def test_five_pair_inventory_is_strict_and_excludes_unrelated_pairs():
    products = []
    for start, end in PAPER_INTERVALS:
        products.append({
            "reference_date": start,
            "secondary_date": end,
            "product_type": "GOFF",
            "track": "098",
            "direction": "A",
            "polarization": "HH",
            "layer": "layer2",
            "granule_name": f"GOFF_{start}_{end}",
        })
    products.append({
        "reference_date": "2026-06-08",
        "secondary_date": "2026-06-20",
        "product_type": "GOFF",
        "track": "048",
        "direction": "D",
        "polarization": "HH",
        "layer": "layer2",
        "granule_name": "unrelated-descending-pair",
    })
    selected = validate_five_pair_inventory(products)
    assert len(selected) == 5
    assert all(v["direction"] == "A" for v in selected.values())


def test_five_pair_inventory_fails_on_missing_pair_or_wrong_geometry():
    products = [{
        "reference_date": start,
        "secondary_date": end,
        "product_type": "GOFF",
        "track": "098",
        "direction": "A",
        "polarization": "HH",
        "layer": "layer2",
    } for start, end in PAPER_INTERVALS[:-1]]
    with pytest.raises(ScientificInputError, match="MISSING_PAPER_PAIRS"):
        validate_five_pair_inventory(products)
    products.append({
        "reference_date": PAPER_INTERVALS[-1][0],
        "secondary_date": PAPER_INTERVALS[-1][1],
        "product_type": "GOFF",
        "track": "048",
        "direction": "D",
        "polarization": "HH",
        "layer": "layer2",
    })
    with pytest.raises(ScientificInputError, match="IDENTITY_MISMATCH"):
        validate_five_pair_inventory(products)


def test_directional_coherence_has_explicit_truncated_edge_window_known_answer():
    # This is a kernel regression contract, not a claim about the author's
    # edge policy: a 3x3 window has 4/6/9 in-bounds cells at corner/edge/centre.
    east = np.ones((3, 3))
    north = np.zeros((3, 3))
    valid = np.ones((3, 3), dtype=bool)

    R = directional_coherence(
        east, north, valid, window_size=3, minimum_valid_cells=9,
    )

    assert R[1, 1] == pytest.approx(1.0)
    assert np.isfinite(R).sum() == 1
    assert np.isnan(R[0, 0])
    assert np.isnan(R[0, 1])
    assert np.isnan(R[1, 0])


def test_directional_coherence_at_missing_centre_uses_valid_neighbours_only():
    # Current policy: R is a neighbourhood statistic, so it can be defined at
    # a centre with no valid vector when the neighbourhood has enough others.
    # This remains unverified against the author's supplement implementation.
    east = np.ones((3, 3))
    north = np.zeros((3, 3))
    valid = np.ones((3, 3), dtype=bool)
    valid[1, 1] = False

    R = directional_coherence(
        east, north, valid, window_size=3, minimum_valid_cells=8,
    )

    assert not valid[1, 1]
    assert R[1, 1] == pytest.approx(1.0)
