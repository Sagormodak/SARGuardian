import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from process_gcov_job import (
    MAX_WEB_PREVIEW_BYTES,
    create_web_previews,
    sha256_file,
    write_mask_web_preview,
)


def _write_mask(path, values):
    height, width = values.shape
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:32645",
        "transform": from_origin(500000, 2700000, 10, 10),
        "nodata": 255,
        "compress": "deflate",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as destination:
        destination.write(values.astype(np.uint8), 1)
    return path


def test_isolated_source_candidate_is_a_sparse_marker_not_a_coarse_polygon(tmp_path):
    source = np.zeros((512, 512), dtype=np.uint8)
    source[257, 251] = 1
    source_path = _write_mask(tmp_path / "isolated_mask.tif", source)
    original_digest = sha256_file(source_path)
    preview_path = tmp_path / "isolated_preview.geojson"

    preview = write_mask_web_preview(
        source_path,
        preview_path,
        class_name="erosion",
        max_bytes=50_000,
        max_dimension=64,
    )

    diagnostics = preview["river_shift_preview"]
    assert len(preview["features"]) == 1
    assert preview["features"][0]["geometry"]["type"] == "MultiPoint"
    assert preview["features"][0]["properties"]["preview_sparse_marker"] is True
    assert diagnostics["source_candidate_pixels"] == 1
    assert diagnostics["preview_candidate_cells"] == 1
    assert diagnostics["preview_polygon_cells"] == 0
    assert diagnostics["preview_sparse_marker_cells"] == 1
    assert diagnostics["minimum_polygon_occupancy_fraction"] == 0.5
    assert diagnostics["features_omitted_for_size"] == 0
    assert diagnostics["method"] == "average_occupancy_gt_0_5_polygonize_plus_sparse_cell_centres"
    assert preview_path.stat().st_size <= 50_000
    assert sha256_file(source_path) == original_digest


def test_preview_uses_majority_occupancy_for_polygons_and_sparse_markers_for_ties(tmp_path):
    source = np.zeros((128, 128), dtype=np.uint8)
    # At 64x64, each preview cell represents an exact 2x2 source block.
    source[0:2, 0:2] = [[1, 1], [1, 0]]  # 75% occupancy -> polygon cell
    source[0:2, 2:4] = [[1, 0], [0, 1]]  # 50% occupancy -> sparse marker
    source_path = _write_mask(tmp_path / "mixed_occupancy_mask.tif", source)

    preview = write_mask_web_preview(
        source_path,
        tmp_path / "mixed_occupancy_preview.geojson",
        class_name="deposition",
        max_bytes=50_000,
        max_dimension=64,
    )

    diagnostics = preview["river_shift_preview"]
    by_geometry = {feature["geometry"]["type"]: feature for feature in preview["features"]}
    assert set(by_geometry) == {"Polygon", "MultiPoint"}
    assert diagnostics["source_candidate_pixels"] == 5
    assert diagnostics["preview_candidate_cells"] == 2
    assert diagnostics["preview_polygon_cells"] == 1
    assert diagnostics["preview_sparse_marker_cells"] == 1


def test_empty_mask_is_explicitly_distinguished_from_a_lost_preview(tmp_path):
    source = np.zeros((128, 128), dtype=np.uint8)
    source_path = _write_mask(tmp_path / "empty_mask.tif", source)

    preview = write_mask_web_preview(
        source_path,
        tmp_path / "empty_preview.geojson",
        class_name="deposition",
        max_dimension=64,
    )

    assert preview["features"] == []
    assert preview["river_shift_preview"]["feature_count"] == 0
    assert preview["river_shift_preview"]["source_candidate_pixels"] == 0
    assert preview["river_shift_preview"]["preview_candidate_cells"] == 0
    assert "no candidate pixels" in preview["river_shift_preview"]["empty_reason"]


def test_raster_first_job_previews_keep_each_change_class_and_each_observed_date(tmp_path):
    morphology_dir = tmp_path / "morphology"
    flood_dir = tmp_path / "flood"
    time_dir = tmp_path / "time_series"
    work_dir = tmp_path / "work"
    morphology_dir.mkdir()
    flood_dir.mkdir()
    time_dir.mkdir()

    erosion = np.zeros((160, 160), dtype=np.uint8)
    erosion[12:35, 14:43] = 1
    deposition = np.zeros((160, 160), dtype=np.uint8)
    deposition[48:76, 55:91] = 1
    new_water = np.zeros((160, 160), dtype=np.uint8)
    new_water[103:145, 109:148] = 1
    water_one = np.zeros((160, 160), dtype=np.uint8)
    water_one[22:55, 80:120] = 1
    water_two = np.zeros((160, 160), dtype=np.uint8)
    water_two[30:70, 70:115] = 1

    source_masks = {
        morphology_dir / "erosion_candidate_mask.tif": erosion,
        morphology_dir / "deposition_candidate_mask.tif": deposition,
        flood_dir / "newly_water_covered_mask.tif": new_water,
        time_dir / "water_2026-06-30_mask.tif": water_one,
        time_dir / "water_2026-07-12_mask.tif": water_two,
    }
    original_digests = {
        path: sha256_file(_write_mask(path, values))
        for path, values in source_masks.items()
    }
    reference = _write_mask(
        tmp_path / "reference.tif",
        np.zeros((160, 160), dtype=np.uint8),
    )
    report_path = time_dir / "river_shift_timeseries.json"
    report_path.write_text(json.dumps({
        "analysis_type": "water_timeseries_screening",
        "quality": {"warnings": []},
        "time_series": [
            {
                "date": "2026-06-30",
                "water_mask": "water_2026-06-30_mask.tif",
                "water_geojson": "water_2026-06-30.geojson",
                "water_geojson_sha256": "0" * 64,
            },
            {
                "date": "2026-07-12",
                "water_mask": "water_2026-07-12_mask.tif",
                "water_geojson": "water_2026-07-12.geojson",
                "water_geojson_sha256": "0" * 64,
            },
        ],
    }), encoding="utf-8")

    layers = create_web_previews(
        work_dir,
        time_dir,
        flood_dir,
        morphology_dir,
        reference,
        report_path,
    )

    combined_path = work_dir / "outputs" / "map" / "river_change_candidates_preview.geojson"
    combined = json.loads(combined_path.read_text(encoding="utf-8"))
    class_names = {
        feature["properties"]["river_shift_layer"]
        for feature in combined["features"]
    }
    assert class_names == {"erosion", "deposition", "new_water"}
    assert len(combined["features"]) == 3
    assert combined["river_shift_preview"]["features_omitted_for_size"] == 0
    assert combined_path.stat().st_size <= MAX_WEB_PREVIEW_BYTES

    map_dir = work_dir / "outputs" / "map"
    class_previews = {
        "erosion": map_dir / "erosion_candidates_preview.geojson",
        "deposition": map_dir / "deposition_candidates_preview.geojson",
        "new_water": map_dir / "newly_water_covered_preview.geojson",
    }
    expected_class_pixels = {
        "erosion": int(erosion.sum()),
        "deposition": int(deposition.sum()),
        "new_water": int(new_water.sum()),
    }
    observed_class_pixels = {}
    for class_name, preview_path in class_previews.items():
        class_preview = json.loads(preview_path.read_text(encoding="utf-8"))
        diagnostics = class_preview["river_shift_preview"]
        observed_class_pixels[class_name] = diagnostics["source_candidate_pixels"]
        assert diagnostics["source_candidate_pixels"] == expected_class_pixels[class_name]
        # These fixtures fit without downsampling, so preview cells must be an
        # exact one-to-one count of the class-specific source mask positives.
        assert diagnostics["preview_candidate_cells"] == expected_class_pixels[class_name]
        assert diagnostics["preview_polygon_cells"] == expected_class_pixels[class_name]
        assert diagnostics["preview_sparse_marker_cells"] == 0
    assert len(set(observed_class_pixels.values())) == 3

    updated_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(updated_report["time_series"]) == 2
    for frame in updated_report["time_series"]:
        frame_path = work_dir / "outputs" / "map" / frame["water_geojson"]
        frame_preview = json.loads(frame_path.read_text(encoding="utf-8"))
        assert len(frame_preview["features"]) == 1
        expected_frame_pixels = {
            "2026-06-30": int(water_one.sum()),
            "2026-07-12": int(water_two.sum()),
        }[frame["date"]]
        assert frame_preview["river_shift_preview"]["source_candidate_pixels"] == expected_frame_pixels
        assert frame_preview["river_shift_preview"]["preview_candidate_cells"] == expected_frame_pixels
        assert frame_preview["river_shift_preview"]["preview_polygon_cells"] == expected_frame_pixels
        assert frame_preview["river_shift_preview"]["preview_sparse_marker_cells"] == 0
        assert frame["water_preview_source_candidate_pixels"] == expected_frame_pixels
        assert frame["water_preview_feature_count"] == 1
        assert frame["water_geojson_sha256"] == sha256_file(frame_path)

    for source_path, digest in original_digests.items():
        assert sha256_file(source_path) == digest
    for layer in layers:
        layer_path = work_dir / layer["path"]
        assert sha256_file(layer_path) == layer["sha256"]
