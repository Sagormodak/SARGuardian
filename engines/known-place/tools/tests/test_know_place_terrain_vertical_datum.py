from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tools.know_place.terrain_vertical_datum import (
    VerticalDatumSensitivityError,
    _json_has_grid,
    calculate_height_offset_m,
    select_required_vertical_transformer,
)


def test_signed_height_offset_is_ellipsoidal_minus_orthometric() -> None:
    orthometric = np.array([[100.0, 200.0], [300.0, np.nan]])
    ellipsoidal = np.array([[125.25, 190.0], [302.5, np.nan]])
    actual = calculate_height_offset_m(orthometric, ellipsoidal)
    np.testing.assert_allclose(actual[:1], np.array([[25.25, -10.0]]))
    assert actual[1, 0] == pytest.approx(2.5)
    assert np.isnan(actual[1, 1])


def test_height_offset_rejects_shape_mismatch() -> None:
    with pytest.raises(VerticalDatumSensitivityError, match="HEIGHT_ARRAY_SHAPE_MISMATCH"):
        calculate_height_offset_m(np.zeros((2, 2)), np.zeros((4,)))


def test_height_offset_rejects_changed_valid_mask() -> None:
    orthometric = np.array([100.0, np.nan, 300.0])
    ellipsoidal = np.array([120.0, 200.0, 320.0])
    with pytest.raises(
        VerticalDatumSensitivityError, match="HEIGHT_CONVERSION_VALID_MASK_CHANGED"
    ):
        calculate_height_offset_m(orthometric, ellipsoidal)


def test_height_offset_rejects_nonfinite_difference() -> None:
    orthometric = np.array([1.0])
    ellipsoidal = np.array([np.inf])
    with pytest.raises(
        VerticalDatumSensitivityError, match="HEIGHT_CONVERSION_VALID_MASK_CHANGED"
    ):
        calculate_height_offset_m(orthometric, ellipsoidal)


def test_recursive_grid_reference_detection() -> None:
    definition = {
        "steps": [
            {"proj": "unitconvert"},
            {"proj": "vgridshift", "grids": [{"short_name": "us_nga_egm08_25.tif"}]},
        ]
    }
    assert _json_has_grid(definition, "us_nga_egm08_25.tif")
    assert not _json_has_grid(definition, "missing_grid.tif")


def test_grid_selection_fails_closed_when_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(
        VerticalDatumSensitivityError, match="EGM2008_GRID_MISSING_OR_EMPTY"
    ):
        select_required_vertical_transformer(tmp_path / "us_nga_egm08_25.tif")


def test_grid_selection_rejects_wrong_filename_even_if_present(tmp_path: Path) -> None:
    wrong = tmp_path / "a-different-grid.tif"
    wrong.write_bytes(b"not-a-real-grid")
    with pytest.raises(
        VerticalDatumSensitivityError, match="UNEXPECTED_EGM2008_GRID_FILENAME"
    ):
        select_required_vertical_transformer(wrong)


def test_offset_preserves_signed_values_across_zero() -> None:
    orthometric = np.array([10.0, 10.0, 10.0])
    ellipsoidal = np.array([9.5, 10.0, 10.5])
    delta = calculate_height_offset_m(orthometric, ellipsoidal)
    np.testing.assert_allclose(delta, np.array([-0.5, 0.0, 0.5]))
