from __future__ import annotations

import math

import numpy as np
import pytest

from tools.know_place.uncertainty import spatial_block_bootstrap_sensitivity, spatial_block_bootstrap_summary


def test_spatial_block_bootstrap_recovers_constant_vector_known_answer_and_is_reproducible():
    east = np.full((30, 30), 3.0)
    north = np.full((30, 30), 4.0)
    valid = np.ones((30, 30), dtype=bool)
    aoi = np.ones((30, 30), dtype=bool)

    first = spatial_block_bootstrap_summary(
        east, north, valid, aoi, block_size_cells=5, replicates=100, seed=123,
    )
    second = spatial_block_bootstrap_summary(
        east, north, valid, aoi, block_size_cells=5, replicates=100, seed=123,
    )

    assert first["status"] == "COMPUTED_EXPLORATORY"
    assert first["valid_block_count"] == 36
    assert first["statistics"]["median_horizontal_magnitude_m"] == pytest.approx(5.0)
    assert first["statistics"]["median_horizontal_magnitude_95pct_interval_m"] == pytest.approx([5.0, 5.0])
    assert first["statistics"]["mean_vector_magnitude_m"] == pytest.approx(5.0)
    assert first["statistics"]["mean_vector_azimuth_deg_clockwise_from_north"] == pytest.approx(
        math.degrees(math.atan2(3.0, 4.0))
    )
    assert first["statistics"] == second["statistics"]


def test_spatial_block_bootstrap_marks_small_aoi_as_insufficient_not_false_zero():
    east = np.ones((4, 4))
    north = np.zeros((4, 4))
    valid = np.ones((4, 4), dtype=bool)
    aoi = valid.copy()

    result = spatial_block_bootstrap_summary(
        east, north, valid, aoi, block_size_cells=5, replicates=100,
    )

    assert result["status"] == "INSUFFICIENT_SPATIAL_BLOCKS"
    assert result["valid_block_count"] == 1
    assert "statistics" not in result


def test_spatial_block_bootstrap_rejects_shape_and_policy_errors():
    with pytest.raises(ValueError, match="UNCERTAINTY_ARRAY_SHAPE_MISMATCH"):
        spatial_block_bootstrap_summary(
            np.ones((3, 4)), np.ones((4, 3)), np.ones((3, 4), bool),
            np.ones((3, 4), bool), replicates=100,
        )
    with pytest.raises(ValueError, match="UNCERTAINTY_REPLICATES_MUST_BE_AT_LEAST_100"):
        spatial_block_bootstrap_summary(
            np.ones((20, 20)), np.ones((20, 20)),
            np.ones((20, 20), bool), np.ones((20, 20), bool),
            replicates=20,
        )


def test_block_size_sensitivity_reports_3_5_10_cell_scales_deterministically():
    east = np.full((60, 60), 3.0)
    north = np.full((60, 60), 4.0)
    valid = np.ones((60, 60), dtype=bool)
    aoi = np.ones((60, 60), dtype=bool)

    first = spatial_block_bootstrap_sensitivity(
        east, north, valid, aoi, block_sizes_cells=(3, 5, 10),
        replicates_per_size=100, seed=42, minimum_blocks=8,
    )
    second = spatial_block_bootstrap_sensitivity(
        east, north, valid, aoi, block_sizes_cells=(3, 5, 10),
        replicates_per_size=100, seed=42, minimum_blocks=8,
    )

    assert first == second
    assert first["status"] == "COMPUTED_EXPLORATORY"
    assert first["sizes_tested_cells"] == [3, 5, 10]
    assert [row["block_size_cells"] for row in first["rows"]] == [3, 5, 10]
    assert all(row["status"] == "COMPUTED_EXPLORATORY" for row in first["rows"])
    assert all(row["median_horizontal_magnitude_95pct_interval_m"] == pytest.approx([5.0, 5.0]) for row in first["rows"])


def test_block_size_sensitivity_fails_closed_for_invalid_scales():
    east = np.ones((20, 20))
    valid = np.ones((20, 20), dtype=bool)
    with pytest.raises(ValueError, match="UNCERTAINTY_BLOCK_SIZES_MUST_BE_NONEMPTY_AND_UNIQUE"):
        spatial_block_bootstrap_sensitivity(east, east, valid, valid, block_sizes_cells=())
    with pytest.raises(ValueError, match="UNCERTAINTY_BLOCK_SIZES_INVALID"):
        spatial_block_bootstrap_sensitivity(east, east, valid, valid, block_sizes_cells=(3, 0))
