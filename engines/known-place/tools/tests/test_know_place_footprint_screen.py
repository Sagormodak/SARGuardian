from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import label, uniform_filter

from tools.know_place.footprint_screen import (
    EXPECTED_INTERVALS,
    MAGNITUDE_ANOMALY_MIN_M,
    MAGNITUDE_CLIP_M,
    MINIMUM_COMPONENT_PIXELS,
    MINIMUM_FLAGGED_INTERVALS,
    RESIDUAL_COHERENCE_MIN,
    SNR_THRESHOLD,
    Z_THRESHOLD,
    FootprintScreenError,
    aggregate_persistent_pairs,
    filter_persistent_components,
    local_nanmean,
    project_per_pixel_offsets,
    residual_directional_coherence,
    screen_pair,
)


def author_lmean(values, window_size):
    array = np.asarray(values, dtype=np.float32)
    numerator = np.nan_to_num(array).astype(np.float32)
    support_mask = np.isfinite(array).astype(np.float32)
    local_sum = uniform_filter(numerator, window_size)
    support = uniform_filter(support_mask, window_size)
    return np.where(support > 0.15, local_sum / np.maximum(support, 1e-6), np.nan)


def author_residual_coherence(east, north):
    magnitude = np.hypot(east, north)
    ux = east / np.maximum(magnitude, 1e-9)
    uy = north / np.maximum(magnitude, 1e-9)
    support = uniform_filter(np.isfinite(ux).astype(np.float32), 5)
    return np.where(
        support > 0.5,
        np.hypot(author_lmean(ux, 5), author_lmean(uy, 5)),
        np.nan,
    )


def author_pair_screen(east, north):
    magnitude = np.hypot(east, north)
    anomaly = magnitude - author_lmean(magnitude, 41)
    scale = author_lmean(np.abs(anomaly), 41)
    z_score = anomaly / np.maximum(scale, 0.05)
    residual_east = (east - author_lmean(east, 41)).astype(np.float32)
    residual_north = (north - author_lmean(north, 41)).astype(np.float32)
    residual_r = author_residual_coherence(residual_east, residual_north)
    hit = (
        np.isfinite(z_score)
        & (z_score >= 4.0)
        & (anomaly >= 0.50)
        & np.isfinite(residual_r)
        & (residual_r >= 0.75)
    )
    return {
        "magnitude_m": magnitude,
        "magnitude_anomaly_m": anomaly,
        "local_magnitude_m": author_lmean(magnitude, 41),
        "local_absolute_deviation_m": scale,
        "z_score": z_score,
        "residual_R": residual_r,
        "hit": hit,
    }


def test_screen_parameters_match_archived_author_source():
    assert SNR_THRESHOLD == 5.0
    assert MAGNITUDE_CLIP_M == 10.0
    assert Z_THRESHOLD == 4.0
    assert MAGNITUDE_ANOMALY_MIN_M == 0.50
    assert RESIDUAL_COHERENCE_MIN == 0.75
    assert MINIMUM_FLAGGED_INTERVALS == 2
    assert MINIMUM_COMPONENT_PIXELS == 10
    assert EXPECTED_INTERVALS == (
        ("20260620", "20260702"),
        ("20260702", "20260714"),
        ("20260714", "20260726"),
        ("20260726", "20260819"),
        ("20260819", "20260831"),
    )


def test_local_nanmean_matches_archive_formula_including_reflected_edges_and_support():
    values = np.arange(63, dtype=np.float32).reshape(7, 9) / 13.0
    values[0, 0] = np.nan
    values[3, 4] = np.nan
    values[5, 2] = np.nan
    expected = author_lmean(values, 5)
    actual = local_nanmean(values, 5)
    assert np.array_equal(np.isfinite(actual), np.isfinite(expected))
    assert np.allclose(actual, expected, rtol=0, atol=1e-7, equal_nan=True)


def test_per_pixel_projection_matches_archive_formula_and_quality_gates():
    at = np.array([[1.0, 2.0, 5.0, 15.0], [1.0, np.nan, 1.0, 2.0]], dtype=np.float32)
    sr = np.array([[0.1, 0.2, 0.5, 0.0], [0.2, 0.1, 0.2, 0.3]], dtype=np.float32)
    snr = np.array([[5.0, 4.0, 6.0, 6.0], [8.0, 8.0, np.nan, 9.0]], dtype=np.float32)
    ce = np.ones_like(at)
    cn = np.zeros_like(at)
    ke = np.zeros_like(at)
    kn = np.ones_like(at)

    result = project_per_pixel_offsets(at, sr, snr, ce, cn, ke, kn)
    raw_east = at * ce + sr * ke
    raw_north = at * cn + sr * kn
    raw_magnitude = np.hypot(raw_east, raw_north)
    valid = np.isfinite(snr) & (snr >= 5.0) & np.isfinite(raw_magnitude) & (raw_magnitude <= 10.0)

    assert np.array_equal(result["valid_mask"], valid)
    assert np.allclose(result["dE_m"], np.where(valid, raw_east, np.nan), equal_nan=True)
    assert np.allclose(result["dN_m"], np.where(valid, raw_north, np.nan), equal_nan=True)
    assert result["quality_gate_counts"]["final_valid_cells"] == int(valid.sum())
    assert result["hazard_detection_status"] == "NOT_EVALUATED"


def test_per_pixel_projection_rejects_scalar_broadcast_and_shape_mismatch():
    grid = np.ones((4, 5), dtype=np.float32)
    with pytest.raises(FootprintScreenError, match="C_EAST_MUST_BE_2D"):
        project_per_pixel_offsets(grid, grid, grid * 5, 1.0, grid, grid, grid)
    with pytest.raises(FootprintScreenError, match="C_EAST_SHAPE_MISMATCH"):
        project_per_pixel_offsets(grid, grid, grid * 5, grid[:, :2], grid, grid, grid)


def test_screen_pair_diagnostic_maps_match_archived_author_formula():
    rng = np.random.default_rng(20261024)
    shape = (73, 69)
    at = rng.normal(0.1, 0.22, size=shape).astype(np.float32)
    sr = rng.normal(-0.05, 0.16, size=shape).astype(np.float32)
    snr = rng.uniform(4.0, 12.0, size=shape).astype(np.float32)
    ce = np.broadcast_to(np.linspace(0.85, 0.99, shape[1]), shape).copy().astype(np.float32)
    cn = np.broadcast_to(np.linspace(-0.48, -0.1, shape[1]), shape).copy().astype(np.float32)
    ke = np.broadcast_to(np.linspace(-0.7, -0.2, shape[1]), shape).copy().astype(np.float32)
    kn = np.broadcast_to(np.linspace(0.1, 0.7, shape[1]), shape).copy().astype(np.float32)
    # Include a coherent, elevated-magnitude patch and invalid source pixels.
    at[23:47, 20:45] += np.float32(1.15)
    sr[23:47, 20:45] += np.float32(0.35)
    snr[0:3, 0:5] = 3.0
    at[6, 7] = np.nan
    snr[10, 12] = np.nan

    projection = project_per_pixel_offsets(at, sr, snr, ce, cn, ke, kn)
    actual = screen_pair(projection, interval=("20260620", "20260702"))
    expected = author_pair_screen(projection["dE_m"], projection["dN_m"])
    diag = actual["diagnostic_maps"]

    for key in (
        "magnitude_m",
        "magnitude_anomaly_m",
        "local_magnitude_m",
        "local_absolute_deviation_m",
        "z_score",
        "residual_R",
    ):
        assert np.allclose(diag[key], expected[key], rtol=0, atol=2e-6, equal_nan=True), key
    assert np.array_equal(actual["hit_mask"], expected["hit"])
    assert actual["interval"] == ("20260620", "20260702")
    assert actual["hazard_detection_status"] == "NOT_EVALUATED"


def test_screen_pair_rejects_forged_valid_mask_and_unknown_interval():
    grid = np.ones((9, 9), dtype=np.float32)
    projection = project_per_pixel_offsets(grid, grid * 0, grid * 5, grid, grid * 0, grid * 0, grid * 0)
    broken = dict(projection)
    broken["valid_mask"] = np.zeros_like(grid, dtype=bool)
    with pytest.raises(FootprintScreenError, match="PROJECTION_VALID_MASK_MISMATCH"):
        screen_pair(broken, interval=("20260901", "20260902"))
    with pytest.raises(FootprintScreenError, match="PAIR_INTERVAL_NOT_IN_AUTHOR_FIVE_PAIR_SET"):
        screen_pair(projection, interval=("20260901", "20260902"))


def test_residual_coherence_matches_archived_formula():
    rng = np.random.default_rng(44)
    east = rng.normal(size=(17, 19)).astype(np.float32)
    north = rng.normal(size=(17, 19)).astype(np.float32)
    east[0:5, 0:4] = np.nan
    north[8:10, 7:12] = np.nan
    expected = author_residual_coherence(east, north)
    actual = residual_directional_coherence(east, north)
    assert np.array_equal(np.isfinite(actual), np.isfinite(expected))
    assert np.allclose(actual, expected, rtol=0, atol=1e-7, equal_nan=True)


def _pair_result(interval, hit):
    anomaly = np.where(hit, 1.0 + EXPECTED_INTERVALS.index(interval), np.nan).astype(np.float32)
    residual_r = np.where(hit, 0.75 + EXPECTED_INTERVALS.index(interval) / 100.0, np.nan).astype(np.float32)
    return {
        "status": "CANDIDATE_MOVEMENT_SCREEN_COMPUTED",
        "interval": interval,
        "hit_mask": hit,
        "hit_magnitude_anomaly_m": anomaly,
        "hit_residual_R": residual_r,
    }


def test_five_interval_persistence_and_mean_only_over_flagged_intervals():
    hits = []
    for index, interval in enumerate(EXPECTED_INTERVALS):
        mask = np.zeros((2, 2), dtype=bool)
        if index in (0, 1, 2):
            mask[0, 0] = index in (0, 1)
            mask[1, 0] = index in (1, 2)
        if index == 0:
            mask[0, 1] = True
        if index == 4:
            mask[1, 1] = True
        hits.append(_pair_result(interval, mask))

    result = aggregate_persistent_pairs(hits)
    expected_count = np.array([[2, 1], [2, 1]], dtype=np.uint8)
    assert np.array_equal(result["n_epochs_flagged"], expected_count)
    assert np.array_equal(result["persistent_mask"], expected_count >= 2)
    assert result["counts"]["cells_persistent"] == 2
    assert result["mean_hit_magnitude_anomaly_m"][0, 0] == pytest.approx((1.0 + 2.0) / 2)
    assert result["mean_hit_magnitude_anomaly_m"][1, 0] == pytest.approx((2.0 + 3.0) / 2)
    assert result["hazard_detection_status"] == "NOT_EVALUATED"


def test_persistence_rejects_non_author_pair_order_and_grid_mismatch():
    results = [
        _pair_result(interval, np.ones((2, 2), dtype=bool))
        for interval in EXPECTED_INTERVALS
    ]
    results[0], results[1] = results[1], results[0]
    with pytest.raises(FootprintScreenError, match="PAIR_0_INTERVAL_ORDER_MISMATCH"):
        aggregate_persistent_pairs(results)

    results[0], results[1] = (
        _pair_result(EXPECTED_INTERVALS[0], np.ones((2, 2), dtype=bool)),
        _pair_result(EXPECTED_INTERVALS[1], np.ones((3, 2), dtype=bool)),
    )
    with pytest.raises(FootprintScreenError, match="PAIR_1_GRID_SHAPE_MISMATCH"):
        aggregate_persistent_pairs(results)


def test_component_filter_matches_four_connected_default_and_minimum_ten_pixels():
    mask = np.zeros((9, 9), dtype=bool)
    mask[0:2, 0:5] = True  # exactly 10 connected cells
    mask[4, 4] = True
    mask[5, 5] = True  # diagonal-only contact must not connect
    reference_labels, reference_n = label(mask)
    actual = filter_persistent_components(mask)

    sizes = np.bincount(reference_labels.ravel(), minlength=reference_n + 1)
    expected_keep = np.zeros_like(mask)
    for component_id in range(1, reference_n + 1):
        if sizes[component_id] >= 10:
            expected_keep |= reference_labels == component_id
    assert np.array_equal(actual["candidate_mask"], expected_keep)
    assert int(actual["candidate_mask"].sum()) == 10
    assert actual["counts"]["input_connected_components"] == 3
    assert actual["counts"]["retained_components"] == 1
    assert actual["hazard_detection_status"] == "NOT_EVALUATED"


def test_component_filter_rejects_non_boolean_masks():
    with pytest.raises(FootprintScreenError, match="PERSISTENT_MASK_MUST_BE_2D_BOOL"):
        filter_persistent_components(np.ones((3, 3), dtype=np.uint8))
