import json

import numpy as np
import pytest

from river_shift.timeseries import run_water_timeseries_analysis


def test_timeseries_exports_each_observed_date_and_sensitivity(tmp_path, raster_writer):
    first = np.full((20, 20), 0.3, dtype=np.float32)
    first[5:9, 5:9] = 0.01
    second = np.full((20, 20), 0.3, dtype=np.float32)
    second[4:12, 4:12] = 0.01
    paths = [
        raster_writer("first.tif", first),
        raster_writer("second.tif", second),
    ]
    report = run_water_timeseries_analysis(
        observations=[
            {"date": "2026-07-01", "path": str(paths[1])},
            {"date": "2026-06-18", "path": str(paths[0])},
        ],
        output_dir=str(tmp_path / "series"),
        units="linear",
        threshold_db=-12.0,
        use_otsu=False,
        maturity="PROVISIONAL",
        frequency="frequencyA",
        polarization_term="HHHH",
    )
    assert report["analysis_type"] == "water_timeseries_screening"
    assert [frame["date"] for frame in report["time_series"]] == ["2026-06-18", "2026-07-01"]
    assert report["time_series"][1]["water_area_km2"] > report["time_series"][0]["water_area_km2"]
    assert report["quality"]["release_status"] == "PROVISIONAL"
    assert report["method"]["playback_semantics"].endswith("no temporal interpolation")
    assert len(report["uncertainty"]["classification_threshold_sensitivity"]["scenarios"]) == 5
    assert (tmp_path / "series" / "water_2026-06-18.geojson").is_file()
    saved = json.loads((tmp_path / "series" / "river_shift_timeseries.json").read_text())
    assert saved["time_series"][0]["water_geojson_sha256"]


def test_timeseries_requires_two_unique_dates(tmp_path, raster_writer):
    path = raster_writer("one.tif", np.full((10, 10), 0.3, dtype=np.float32))
    common = {
        "output_dir": str(tmp_path / "out"),
        "units": "linear",
        "threshold_db": -12.0,
        "use_otsu": False,
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "polarization_term": "HHHH",
    }
    with pytest.raises(ValueError, match="At least two"):
        run_water_timeseries_analysis(observations=[{"date": "2026-06-18", "path": str(path)}], **common)
    with pytest.raises(ValueError, match="unique"):
        run_water_timeseries_analysis(observations=[
            {"date": "2026-06-18", "path": str(path)},
            {"date": "2026-06-18", "path": str(path)},
        ], **common)
