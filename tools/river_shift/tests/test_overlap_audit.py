import json

import numpy as np
import pytest

from pyproj import CRS
from shapely.geometry import box, mapping

from process_gcov_job import preview_geometry_overlap_metrics
from river_shift.overlap_audit import audit_candidate_mask_overlap, audit_scene_mosaic_overlap


def test_candidate_mask_overlap_audit_reports_exact_pairwise_pixels(tmp_path, raster_writer):
    erosion = np.zeros((8, 8), dtype=np.uint8)
    deposition = np.zeros((8, 8), dtype=np.uint8)
    new_water = np.zeros((8, 8), dtype=np.uint8)
    erosion[2:4, 2:4] = 1
    deposition[5:7, 5:7] = 1
    new_water[3:5, 3:5] = 1

    paths = {
        "erosion": raster_writer("erosion.tif", erosion),
        "deposition": raster_writer("deposition.tif", deposition),
        "new_water": raster_writer("new-water.tif", new_water),
    }
    output = tmp_path / "qa" / "candidate_overlap_audit.json"
    result = audit_candidate_mask_overlap(
        paths, output,
        comparison_window={"baseline": "2026-01-01", "comparison_one": "2026-01-10"},
    )

    assert result["pairwise"]["erosion__deposition"]["intersection_pixels"] == 0
    assert result["pairwise"]["erosion__new_water"]["intersection_pixels"] == 1
    assert result["pairwise"]["deposition__new_water"]["intersection_pixels"] == 0
    assert result["pairwise"]["erosion__new_water"]["jaccard"] == pytest.approx(1 / 7)
    assert result["status"] == "COMPUTED_DIAGNOSTIC_ONLY"
    assert json.loads(output.read_text())["comparison_window"]["baseline"] == "2026-01-01"
    assert len(result["report_sha256"]) == 64


def test_candidate_mask_overlap_rejects_erosion_deposition_conflict(tmp_path, raster_writer):
    erosion = np.zeros((5, 5), dtype=np.uint8)
    deposition = np.zeros((5, 5), dtype=np.uint8)
    new_water = np.zeros((5, 5), dtype=np.uint8)
    erosion[2, 2] = 1
    deposition[2, 2] = 1
    paths = {
        "erosion": raster_writer("erosion.tif", erosion),
        "deposition": raster_writer("deposition.tif", deposition),
        "new_water": raster_writer("new-water.tif", new_water),
    }

    with pytest.raises(ValueError, match="Erosion and deposition masks overlap"):
        audit_candidate_mask_overlap(paths, tmp_path / "audit.json")


def test_candidate_mask_overlap_rejects_grid_mismatch(tmp_path, raster_writer):
    base = np.zeros((5, 5), dtype=np.uint8)
    paths = {
        "erosion": raster_writer("erosion.tif", base),
        "deposition": raster_writer("deposition.tif", base, crs="EPSG:32645"),
        "new_water": raster_writer("new-water.tif", base),
    }

    with pytest.raises(ValueError, match="not on one exact grid"):
        audit_candidate_mask_overlap(paths, tmp_path / "audit.json")


def test_scene_mosaic_overlap_reports_backscatter_difference(tmp_path, raster_writer):
    first = np.full((6, 6), 0.01, dtype=np.float32)
    second = np.full((6, 6), 0.02, dtype=np.float32)
    first_path = raster_writer("scene-a.tif", first)
    second_path = raster_writer("scene-b.tif", second)
    reference_path = raster_writer("mosaic.tif", first)

    result = audit_scene_mosaic_overlap([first_path, second_path], reference_path)

    assert result["status"] == "COMPUTED_REVIEW_REQUIRED"
    assert result["pairwise"][0]["shared_valid_pixels"] == 36
    assert result["pairwise"][0]["absolute_delta_db_median"] == pytest.approx(10 * np.log10(2), abs=1e-5)
    assert len(result["scenes"][0]["sha256"]) == 64


def test_preview_geometry_overlap_is_reported_separately_from_source_masks():
    features = [
        {
            "type": "Feature",
            "properties": {"river_shift_layer": "erosion"},
            "geometry": mapping(box(89.50, 24.50, 89.70, 24.70)),
        },
        {
            "type": "Feature",
            "properties": {"river_shift_layer": "deposition"},
            "geometry": mapping(box(89.60, 24.50, 89.80, 24.70)),
        },
        {
            "type": "Feature",
            "properties": {"river_shift_layer": "new_water"},
            "geometry": mapping(box(89.90, 24.50, 90.00, 24.60)),
        },
    ]

    result = preview_geometry_overlap_metrics(features, CRS.from_epsg(32646))

    pair = result["pairwise"]["erosion__deposition"]
    assert result["status"] == "DISPLAY_ONLY_DIAGNOSTIC"
    assert pair["intersection_area_km2"] > 0
    assert 0 < pair["jaccard"] < 1
    assert pair["intersection_fraction_of_smaller_class"] > 0
    assert result["pairwise"]["erosion__new_water"]["intersection_area_km2"] == 0
    assert "never use these areas for measurements" in result["warning"]
