from __future__ import annotations

import numpy as np
import rasterio
import pytest
from rasterio.transform import Affine

import validate_with_sentinel2 as crosscheck


def _grid_meta():
    return {
        "sentinel2_crs": "EPSG:32645",
        "sentinel2_width": 3,
        "sentinel2_height": 2,
        "sentinel2_transform": [20.0, 0.0, 500000.0, 0.0, -20.0, 2700000.0],
        "pixel_area_m2": 400.0,
    }


def test_binary_reference_geotiff_preserves_water_nonwater_and_nodata(tmp_path):
    water = np.array([[True, False, True], [False, False, True]], dtype=bool)
    valid = np.array([[True, True, False], [False, True, True]], dtype=bool)
    path = tmp_path / "reference-scl-water.tif"

    receipt = crosscheck._write_binary_reference_geotiff(
        path,
        water,
        valid,
        raster_meta=_grid_meta(),
        classification_method="SCL class 6 water; classes 4 and 5 non-water",
        observation_date="2026-08-17",
        item_ids=["S2B_item_1", "S2B_item_2"],
    )

    with rasterio.open(path) as source:
        assert source.count == 1
        assert source.dtypes == ("uint8",)
        assert source.nodata == 255
        assert source.crs.to_epsg() == 32645
        assert source.transform == Affine(20, 0, 500000, 0, -20, 2700000)
        assert source.read(1).tolist() == [[1, 0, 255], [255, 0, 1]]
        assert source.dataset_mask().tolist() == [[255, 255, 0], [0, 255, 255]]
        tags = source.tags()
        assert tags["OBSERVATION_DATE"] == "2026-08-17"
        assert tags["CLASS_1"] == "water"
        assert tags["CLASS_0"] == "non-water"
        assert "not ground truth" in tags["INTERPRETATION"]

    assert receipt["valid_pixels"] == 4
    assert receipt["water_pixels"] == 2
    assert receipt["non_water_pixels"] == 2
    assert receipt["nodata_pixels"] == 2
    assert len(receipt["sha256"]) == 64


def test_binary_reference_geotiff_rejects_mismatched_arrays(tmp_path):
    with pytest.raises(crosscheck.CrosscheckError, match="share one 2-D grid"):
        crosscheck._write_binary_reference_geotiff(
            tmp_path / "bad.tif",
            np.ones((2, 2), dtype=bool),
            np.ones((2, 1), dtype=bool),
            raster_meta=_grid_meta(),
            classification_method="test",
            observation_date="2026-08-17",
            item_ids=["item"],
        )


def test_prepared_manifest_loader_finds_exact_file_in_download_artifact_subfolder(tmp_path):
    from publish_sentinel2_references import _load_single_json_under

    artifact_dir = tmp_path / "prepared"
    nested = artifact_dir / "rivershift-prepared-job-uuid"
    nested.mkdir(parents=True)
    (nested / "prepared.json").write_text(
        '{"job_id":"4e6e4071-fb9d-4e20-a331-867f3f2bd88f"}',
        encoding="utf-8",
    )

    loaded = _load_single_json_under(artifact_dir, "prepared.json")
    assert loaded["job_id"] == "4e6e4071-fb9d-4e20-a331-867f3f2bd88f"


def test_prepared_manifest_loader_rejects_missing_or_ambiguous_json(tmp_path):
    from publish_sentinel2_references import _load_single_json_under

    artifact_dir = tmp_path / "prepared"
    artifact_dir.mkdir()
    with pytest.raises(ValueError, match="found 0"):
        _load_single_json_under(artifact_dir, "prepared.json")

    for folder in ("artifact-a", "artifact-b"):
        nested = artifact_dir / folder
        nested.mkdir()
        (nested / "prepared.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="found 2"):
        _load_single_json_under(artifact_dir, "prepared.json")
