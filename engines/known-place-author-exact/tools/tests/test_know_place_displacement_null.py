from __future__ import annotations

import numpy as np
import pytest
from affine import Affine

from tools.know_place.displacement_null import (
    DisplacementNullError,
    displacement_null_for_pair,
    masks_from_north_up_grid,
)


def test_reconstruction_is_deterministic_and_retains_all_draw_diagnostics():
    east = np.full((40, 40), 3.0, dtype=float)
    north = np.full((40, 40), 4.0, dtype=float)
    valid = np.ones((40, 40), dtype=bool)
    crown = np.zeros_like(valid)
    crown[17:24, 17:24] = True

    first = displacement_null_for_pair(
        east, north, crown, valid, np.random.default_rng(12345),
        candidate_centres=120, pair="fixture", include_draws=True,
    )
    second = displacement_null_for_pair(
        east, north, crown, valid, np.random.default_rng(12345),
        candidate_centres=120, pair="fixture", include_draws=True,
    )

    assert first == second
    assert first["status"] == "COMPUTED_INDEPENDENT_METHOD_DERIVED"
    assert first["policy_version"] == "method-derived-displacement-null-v1"
    assert first["observed_crown_valid_pixels"] == 49
    assert first["observed_crown_median_displacement_m"] == pytest.approx(5.0)
    assert first["null_median_displacement_m"] == pytest.approx(5.0)
    assert first["observed_crown_percentile"] == 0.0  # ties are not counted as below
    diagnostics = first["draw_diagnostics"]
    assert len(diagnostics) == 120
    assert sum(row["accepted"] for row in diagnostics) == first["accepted_draws"]
    assert sum(not row["accepted"] for row in diagnostics) == first["rejected_draws"]
    assert first["accepted_draws"] + first["rejected_draws"] == 120
    assert all(row["median_displacement_m"] == pytest.approx(5.0) for row in diagnostics if row["accepted"])


def test_reconstruction_uses_only_finite_offsets_within_analysis_and_crown_masks():
    east = np.ones((20, 20), dtype=float)
    north = np.zeros((20, 20), dtype=float)
    analysis = np.zeros((20, 20), dtype=bool)
    analysis[2:18, 2:18] = True
    crown = np.zeros((20, 20), dtype=bool)
    crown[0:2, 0:2] = True

    with pytest.raises(DisplacementNullError, match="DISPLACEMENT_NULL_NO_VALID_CROWN_PIXELS"):
        displacement_null_for_pair(east, north, crown, analysis, np.random.default_rng(5), candidate_centres=10)

    crown[:] = False
    crown[5:8, 5:8] = True
    east[6, 6] = np.nan
    north[6, 7] = np.nan
    result = displacement_null_for_pair(
        east, north, crown, analysis, np.random.default_rng(5), candidate_centres=30,
    )
    assert result["observed_crown_valid_pixels"] == 7
    assert result["accepted_draws"] > 0


def test_reconstruction_rejects_invalid_shapes_policies_and_rng():
    east = np.ones((10, 12), dtype=float)
    north = np.ones((10, 12), dtype=float)
    mask = np.ones((10, 12), dtype=bool)
    crown = np.zeros_like(mask)
    crown[4:6, 4:6] = True

    with pytest.raises(DisplacementNullError, match="DISPLACEMENT_NULL_OFFSET_SHAPE_MISMATCH"):
        displacement_null_for_pair(east, np.ones((12, 10)), crown, mask, np.random.default_rng(1))
    with pytest.raises(DisplacementNullError, match="DISPLACEMENT_NULL_RNG_TYPE_INVALID"):
        displacement_null_for_pair(east, north, crown, mask, np.random.RandomState(1))
    with pytest.raises(DisplacementNullError, match="DISPLACEMENT_NULL_CANDIDATE_CENTRES_INVALID"):
        displacement_null_for_pair(east, north, crown, mask, np.random.default_rng(1), candidate_centres=0)
    with pytest.raises(DisplacementNullError, match="DISPLACEMENT_NULL_VALID_FRACTION_INVALID"):
        displacement_null_for_pair(east, north, crown, mask, np.random.default_rng(1), minimum_valid_fraction=1.1)


def test_processed_grid_masks_recover_archive_crown_window_count():
    transform = Affine(
        0.0008143041357902448, 0.0, 85.49978731371755,
        0.0, -0.0007025390534413834, 28.317068471931638,
    )
    crown, wide = masks_from_north_up_grid((73, 80), transform)
    assert int(crown.sum()) == 323
    assert int(wide.sum()) == 73 * 80

    east = np.ones((73, 80), dtype=float)
    north = np.zeros((73, 80), dtype=float)
    east[~crown] = np.nan
    north[~crown] = np.nan
    y, x = np.argwhere(crown)[0]
    east[y, x] = np.nan
    result = displacement_null_for_pair(east, north, crown, wide, np.random.default_rng(3), candidate_centres=100)
    assert result["observed_crown_valid_pixels"] == 322

def test_region_shape_policy_is_explicit_and_reproducible():
    y, x = np.mgrid[:45, :45]
    east = (x - 22) / 8.0
    north = (y - 22) / 9.0
    analysis = np.ones((45, 45), dtype=bool)
    crown = np.zeros_like(analysis)
    crown[18:25, 18:25] = True

    results = {}
    for region_shape in ("disk", "square", "diamond"):
        first = displacement_null_for_pair(
            east, north, crown, analysis, np.random.default_rng(9876),
            candidate_centres=200, region_shape=region_shape,
        )
        second = displacement_null_for_pair(
            east, north, crown, analysis, np.random.default_rng(9876),
            candidate_centres=200, region_shape=region_shape,
        )
        assert first == second
        assert first["region_shape"] == region_shape
        assert first["candidate_centres_examined"] == 200
        assert first["accepted_draws"] + first["rejected_draws"] == 200
        results[region_shape] = first["observed_crown_percentile"]
    assert len(set(results.values())) > 1

    with pytest.raises(DisplacementNullError, match="DISPLACEMENT_NULL_REGION_SHAPE_INVALID"):
        displacement_null_for_pair(
            east, north, crown, analysis, np.random.default_rng(1), region_shape="ellipse",
        )

