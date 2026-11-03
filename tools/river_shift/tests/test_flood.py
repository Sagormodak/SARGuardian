import json

import numpy as np

from river_shift.flood import run_flood_analysis


def test_flood_analysis_outputs_masks_metrics_and_provenance(tmp_path, raster_writer):
    before = np.full((20, 20), 0.3, dtype=np.float32)
    before[5:10, 5:10] = 0.01
    during = np.full((20, 20), 0.3, dtype=np.float32)
    during[4:15, 4:15] = 0.01
    after = np.full((20, 20), 0.3, dtype=np.float32)
    after[5:11, 5:11] = 0.01

    paths = {
        "before": raster_writer("before.tif", before),
        "during": raster_writer("during.tif", during),
        "after": raster_writer("after.tif", after),
    }
    result = run_flood_analysis(
        before_path=str(paths["before"]),
        during_path=str(paths["during"]),
        after_path=str(paths["after"]),
        output_dir=str(tmp_path / "out"),
        units="linear",
        threshold_db=-12.0,
        use_otsu=False,
        dates={"before": "2026-06-01", "during": "2026-07-01", "after": "2026-08-01"},
        maturity="PROVISIONAL",
        frequency="frequencyA",
        polarization_term="HHHH",
    )
    assert result["source"]["product"] == "GCOV"
    assert result["quality"]["status"] == "SCREENING_NOT_INDEPENDENTLY_VALIDATED"
    assert result["quality"]["release_status"] == "PROVISIONAL"
    assert len(result["uncertainty"]["classification_threshold_sensitivity"]["scenarios"]) == 5
    assert result["method"]["threshold_sensitivity_is_statistical_confidence_interval"] is False
    assert len(result["outputs"]["new_water_geojson_sha256"]) == 64
    assert result["metrics"]["newly_water_covered_area_km2"] > 0
    assert "event_proximal_water_area_km2" in result["metrics"]
    assert "peak_water_area_km2" not in result["metrics"]
    assert "not a measured peak-stage observation" in " ".join(result["quality"]["warnings"])
    assert (tmp_path / "out" / "newly_water_covered.geojson").exists()
    saved = json.loads((tmp_path / "out" / "river_shift_result.json").read_text())
    assert saved["inputs"]["dates"]["during"] == "2026-07-01"


def test_flood_analysis_rejects_different_grids(tmp_path, raster_writer):
    before = np.full((10, 10), 0.3, dtype=np.float32)
    during = np.full((10, 10), 0.3, dtype=np.float32)
    after = np.full((10, 10), 0.3, dtype=np.float32)
    paths = [
        raster_writer("before.tif", before),
        raster_writer("during.tif", during),
        raster_writer("after.tif", after, crs="EPSG:32645"),
    ]
    import pytest
    with pytest.raises(ValueError, match="CRS mismatch"):
        run_flood_analysis(
            before_path=str(paths[0]), during_path=str(paths[1]), after_path=str(paths[2]),
            output_dir=str(tmp_path / "out"), units="linear", threshold_db=-12.0,
            use_otsu=False,
        )
