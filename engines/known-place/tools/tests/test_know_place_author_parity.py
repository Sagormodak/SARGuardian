from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from pyproj import Transformer

from tools.know_place.author_parity import (
    AuthorParityError,
    author_coherence_map,
    author_crown_geometry_median,
    author_crown_slice,
    author_inside_aoi_mask,
    author_polygon_null_statistics,
    author_quality_mask,
    author_reference_correct,
    author_site_series_statistics,
    author_wide_window_slices,
)


def test_author_coherence_reflect_edges_and_uses_strict_half_support():
    east = np.ones((5, 5))
    north = np.zeros((5, 5))
    assert np.allclose(author_coherence_map(east, north), 1.0)

    east[:] = np.nan
    north[:] = np.nan
    east[2, 2] = 1.0
    north[2, 2] = 0.0
    assert np.isnan(author_coherence_map(east, north)).all()

    east[:] = np.nan
    north[:] = np.nan
    positions = [(r, c) for r in range(5) for c in range(5)][:13]
    for row, col in positions:
        east[row, col] = 1.0
        north[row, col] = 0.0
    assert author_coherence_map(east, north)[2, 2] == pytest.approx(1.0)


def test_author_coherence_finite_zero_vectors_count_in_denominator():
    east = np.ones((5, 5))
    north = np.zeros((5, 5))
    east[2, 2] = 0.0
    north[2, 2] = 0.0
    assert author_coherence_map(east, north)[2, 2] == pytest.approx(24.0 / 25.0)


def test_author_quality_mask_does_not_apply_extra_correlation_filter():
    east = np.array([[3.0, 11.0, 0.0, np.nan]])
    north = np.zeros_like(east)
    snr = np.array([[5.0, 9.0, 5.0, 10.0]])
    assert author_quality_mask(east, north, snr).tolist() == [[True, False, True, False]]


def test_author_crown_slice_matches_archived_searchsorted_policy():
    crop = author_crown_slice((4, 4), (0.0, 4.0, 0.0, 4.0), (1.0, 1.0, 3.0, 3.0))
    assert crop == (slice(1, 3), slice(1, 3))


def test_author_reference_correction_requires_more_than_200_ring_cells():
    east = np.full((20, 20), 2.0)
    north = np.full((20, 20), -3.0)
    valid = np.zeros((20, 20), dtype=bool)
    valid.flat[:200] = True
    inside = np.zeros((20, 20), dtype=bool)
    ce, cn, evidence = author_reference_correct(east, north, valid, inside)
    assert evidence["ring_valid_cells"] == 200
    assert evidence["correction_applied"] is False
    assert ce.flat[0] == pytest.approx(2.0)
    assert cn.flat[0] == pytest.approx(-3.0)

    valid.flat[200] = True
    ce, cn, evidence = author_reference_correct(east, north, valid, inside)
    assert evidence["ring_valid_cells"] == 201
    assert evidence["correction_applied"] is True
    assert ce.flat[0] == pytest.approx(0.0)
    assert cn.flat[0] == pytest.approx(0.0)


def test_author_geometry_uses_nearest_xy_and_height_axis_median():
    tx = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    cx, cy = tx.transform(85.52985, 28.29041)
    cubes = SimpleNamespace(
        metadata_epsg=32645,
        group_path="mock/radarGrid",
        x_m=np.array([cx - 100.0, cx + 100.0]),
        y_m=np.array([cy + 100.0, cy - 100.0]),
        height_m=np.array([4500.0, 5000.0, 5500.0]),
        incidence_deg=np.array([
            [[30.0, 80.0], [30.0, 80.0]],
            [[31.0, 81.0], [31.0, 81.0]],
            [[32.0, 82.0], [32.0, 82.0]],
        ]),
        los_x=np.full((3, 2, 2), 0.6),
        los_y=np.full((3, 2, 2), 0.8),
        along_track_x=np.full((3, 2, 2), 0.4),
        along_track_y=np.full((3, 2, 2), 0.9),
    )
    result = author_crown_geometry_median(cubes)
    assert result["nearest_column"] == 0
    assert result["nearest_row"] == 0
    assert result["incidence_deg"] == pytest.approx(31.0)


def test_author_wide_window_and_midline_aoi_mask_preserve_axis_orientation():
    x = np.arange(0.0, 11.0)
    y_descending = np.arange(10.0, -1.0, -1.0)
    assert author_wide_window_slices(x, y_descending, epsg=4326, wide_bounds_lonlat=(2, 2, 8, 8)) == (
        slice(3, 9), slice(2, 8)
    )
    mask = author_inside_aoi_mask(x, y_descending, epsg=4326, aoi_bounds_lonlat=(3, 3, 6, 6))
    assert int(mask.sum()) == 16


def test_author_site_series_uses_cropped_crown_coherence():
    east = np.ones((9, 9))
    north = np.zeros((9, 9))
    result = author_site_series_statistics(
        east, north, (0.0, 8.0, 0.0, 8.0), 12,
        crown_bounds_lonlat=(2.0, 2.0, 6.0, 6.0),
    )
    assert result["displacement_valid_crown_cells"] == 16
    assert result["P1_crown_R_valid_cells"] > 0
    assert result["P1_background_R_valid_cells"] > 0
    assert result["P1_R_crown"] == pytest.approx(1.0)
    assert result["P1_R_background"] == pytest.approx(1.0)
    assert result["crown_median_rate_cm_per_day"] == pytest.approx(100.0 / 12.0)


def test_author_polygon_null_is_deterministic_and_uses_strict_quantiles():
    east = np.ones((21, 21))
    north = np.zeros((21, 21))
    args = dict(
        extent_lonlat=(0.0, 20.0, 0.0, 20.0),
        crown_bounds_lonlat=(9.0, 9.0, 12.0, 12.0),
        n_draw=40,
    )
    first = author_polygon_null_statistics(east, north, rng=np.random.default_rng(20260907), **args)
    second = author_polygon_null_statistics(east, north, rng=np.random.default_rng(20260907), **args)
    assert first == second
    assert first["candidate_centres_examined"] == 40
    assert first["accepted_draws"] > 0
    assert first["null_p5"] == pytest.approx(1.0)
    assert first["null_p95"] == pytest.approx(1.0)
    assert first["crown_percentile_strict_less_than"] == pytest.approx(0.0)


def test_author_reference_rejects_mask_shape_mismatch():
    with pytest.raises(AuthorParityError, match="MASK_SHAPE_MISMATCH"):
        author_reference_correct(
            np.ones((2, 2)), np.ones((2, 2)), np.ones((2, 2), dtype=bool), np.ones((2, 3), dtype=bool)
        )
