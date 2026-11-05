from __future__ import annotations

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from tools.know_place.aoi_runner import _write_geotiff


def test_geotiff_has_exact_band_contract_crs_pixel_centres_and_nodata(tmp_path):
    path = tmp_path / "pair_displacement.tif"
    east = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=float)
    north = np.array([[0.0, 0.0], [1.0, 1.0]], dtype=float)
    magnitude = np.hypot(east, north)
    coherence = np.array([[1.0, 0.9], [0.8, np.nan]], dtype=float)
    valid = np.array([[True, True], [True, False]])
    high_flag = np.array([[False, True], [False, False]])
    uncorrected = np.array([[1.0, 12.0], [3.2, np.nan]], dtype=float)
    x = np.array([100.0, 180.0])
    y = np.array([220.0, 140.0])

    _write_geotiff(
        path, east, north, magnitude, coherence, valid, high_flag, uncorrected,
        x, y, 32645,
    )

    with rasterio.open(path) as raster:
        assert raster.crs.to_epsg() == 32645
        assert (raster.width, raster.height, raster.count) == (2, 2, 7)
        assert raster.nodata == -9999.0
        assert raster.transform.c == pytest.approx(60.0)
        assert raster.transform.f == pytest.approx(260.0)
        assert raster.descriptions == (
            "Eastward horizontal displacement (m)",
            "Northward horizontal displacement (m)",
            "Horizontal displacement magnitude (m)",
            "5x5 directional coherence R (unitless)",
            "Valid measurement mask (1=valid)",
            "High-magnitude review flag (1=above configured threshold)",
            "Uncorrected projected horizontal magnitude (m)",
        )
        assert raster.read(1).tolist() == [[1.0, 2.0], [3.0, -9999.0]]
        assert raster.read(5).tolist() == [[1.0, 1.0], [1.0, 0.0]]
        assert raster.read(6).tolist() == [[0.0, 1.0], [0.0, 0.0]]
        assert raster.read(7)[0, 1] == pytest.approx(12.0)
