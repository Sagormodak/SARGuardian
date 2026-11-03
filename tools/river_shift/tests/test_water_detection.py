import numpy as np
import pytest

from river_shift.water_detection import classify_open_water, otsu_threshold_db


def test_classify_open_water_uses_gamma0_power_threshold():
    values = np.full((10, 10), 0.3, dtype=float)
    values[2:8, 2:8] = 0.01
    valid = np.ones(values.shape, dtype=bool)
    mask = classify_open_water(values, valid, units="linear", threshold_db=-12.0)
    assert int(mask.sum()) == 36


def test_classify_open_water_respects_invalid_pixels():
    values = np.full((10, 10), 0.01, dtype=float)
    valid = np.ones(values.shape, dtype=bool)
    valid[:2, :] = False
    mask = classify_open_water(values, valid, units="linear", threshold_db=-12.0)
    assert not mask[:2, :].any()
    assert int(mask.sum()) == 80


def test_otsu_rejects_too_few_valid_pixels():
    values = np.array([-20.0, -19.0, -5.0])
    with pytest.raises(ValueError, match="100 valid pixels"):
        otsu_threshold_db(values, np.ones(values.shape, dtype=bool))
