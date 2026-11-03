from datetime import date

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping
from pyproj import CRS

import validate_with_sentinel2 as crosscheck


def _item(item_id, footprint, acquisition_date, cloud_cover):
    return {
        "id": item_id,
        "geometry": mapping(footprint),
        "properties": {
            "datetime": f"{acquisition_date}T05:00:00Z",
            "eo:cloud_cover": cloud_cover,
        },
        "assets": {
            "B03": {"href": f"https://example.test/{item_id}/B03.tif"},
            "B11": {"href": f"https://example.test/{item_id}/B11.tif"},
            "SCL": {"href": f"https://example.test/{item_id}/SCL.tif"},
        },
    }


def test_confusion_metrics_are_calculated_from_common_valid_pixels():
    predicted = np.array([[1, 1], [0, 0]], dtype=bool)
    reference = np.array([[1, 0], [1, 0]], dtype=bool)
    valid = np.ones((2, 2), dtype=bool)

    metrics = crosscheck._confusion_metrics(predicted, reference, valid, 400.0)

    assert metrics["valid_pixel_count"] == 4
    assert metrics["confusion_matrix"] == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 1,
    }
    assert metrics["agreement"] == 0.5
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["specificity"] == 0.5
    assert metrics["balanced_accuracy"] == 0.5
    assert metrics["f1_score"] == 0.5
    assert metrics["intersection_over_union"] == 1 / 3
    assert metrics["cohen_kappa"] == 0.0
    assert metrics["predicted_water_area_km2"] == 0.0008
    assert metrics["reference_water_area_km2"] == 0.0008
    assert metrics["area_bias_km2"] == 0.0


def test_scl_water_reference_excludes_cloud_shadow_snow_and_unclassified():
    scl = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]], dtype=np.uint8)

    water, valid = crosscheck._scl_water_reference(scl)

    assert water.tolist() == [[False, False, False, False, False, False, True, False, False, False, False, False]]
    assert valid.tolist() == [[False, False, False, False, True, True, True, False, False, False, False, False]]


def test_mndwi_is_finite_and_excludes_invalid_reflectance():
    green = np.array([[30.0, 10.0, 5.0, 0.0]])
    swir1 = np.array([[10.0, 30.0, 0.0, 4.0]])

    index, valid = crosscheck._mndwi(green, swir1)

    assert np.isclose(index[0, 0], 0.5)
    assert np.isclose(index[0, 1], -0.5)
    assert valid.tolist() == [[True, True, False, False]]
    assert np.isnan(index[0, 2:]).all()


def test_best_sentinel_scene_prioritizes_aoi_overlap_before_date_and_cloud():
    aoi = box(88.0, 24.0, 89.0, 25.0)
    full_cover = _item(
        "full-cover",
        box(87.9, 23.9, 89.1, 25.1),
        "2026-07-15",
        25.0,
    )
    partial_near_date = _item(
        "partial-near-date",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-07-12",
        1.0,
    )
    too_cloudy = _item(
        "cloudy",
        box(87.9, 23.9, 89.1, 25.1),
        "2026-07-12",
        80.0,
    )
    too_far = _item(
        "too-far",
        box(87.9, 23.9, 89.1, 25.1),
        "2026-07-20",
        1.0,
    )

    selected = crosscheck.select_best_item(
        [partial_near_date, too_cloudy, too_far, full_cover],
        observation_date=date(2026, 7, 12),
        aoi_geometry_wgs84=aoi,
        analysis_crs=CRS.from_epsg(32645),
        max_day_offset=3,
        max_cloud_cover=40,
    )

    assert selected["id"] == "full-cover"


def test_no_matching_scene_is_reported_not_as_zero_agreement(tmp_path, monkeypatch):
    mask_path = tmp_path / "nisar-water-mask.tif"
    data = np.array([[0, 1], [1, 0]], dtype=np.uint8)
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs="EPSG:32645",
        transform=from_origin(500000, 2700000, 20, 20),
        nodata=255,
    ) as destination:
        destination.write(data, 1)

    monkeypatch.setattr(crosscheck, "_search_items", lambda **kwargs: [])
    report = crosscheck.run_crosscheck(
        nisar_mask_path=mask_path,
        observation_date=date(2026, 7, 12),
        output_dir=tmp_path / "results",
    )

    assert report["status"] == "NO_MATCHING_SENTINEL2_SCENE_WITHIN_FILTER"
    assert report["metrics"] is None
    assert "not zero agreement" in " ".join(report["warnings"])
    saved = tmp_path / "results" / "sentinel2_cross_sensor_agreement.json"
    assert saved.is_file()
    assert report["nisar_mask_sha256"] == crosscheck.sha256_file(mask_path)
