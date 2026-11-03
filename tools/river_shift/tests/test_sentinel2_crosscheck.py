from datetime import date
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping
from pyproj import CRS

import validate_with_sentinel2 as crosscheck


def _item(
    item_id,
    footprint,
    acquisition_date,
    cloud_cover,
    *,
    datatake_id=None,
    platform="sentinel-2b",
    mgrs_tile=None,
    processing_baseline="05.11",
    generation_time=None,
):
    properties = {
        "datetime": f"{acquisition_date}T05:00:00Z",
        "eo:cloud_cover": cloud_cover,
        "platform": platform,
        "s2:processing_baseline": processing_baseline,
    }
    if datatake_id is not None:
        properties["s2:datatake_id"] = datatake_id
    if mgrs_tile is not None:
        properties["s2:mgrs_tile"] = mgrs_tile
    if generation_time is not None:
        properties["s2:generation_time"] = generation_time
    return {
        "id": item_id,
        "geometry": mapping(footprint),
        "properties": properties,
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


def _write_geotiff(path: Path, data: np.ndarray, *, pixel_size: float, nodata=None):
    data = np.asarray(data)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=data.dtype,
        crs="EPSG:32645",
        transform=from_origin(500000, 2700000, pixel_size, pixel_size),
        nodata=nodata,
    ) as destination:
        destination.write(data, 1)
    return path


def test_window_for_aoi_constructs_and_clips_a_valid_raster_window(tmp_path):
    from rasterio.windows import Window

    raster_path = _write_geotiff(
        tmp_path / "b11.tif",
        np.ones((8, 8), dtype=np.uint16),
        pixel_size=20,
    )
    with rasterio.open(raster_path) as dataset:
        window = crosscheck._window_for_aoi(
            dataset,
            (500020, 2699880, 500080, 2699940),
        )

    assert isinstance(window, Window)
    assert (window.col_off, window.row_off) == (1, 3)
    assert (window.width, window.height) == (3, 3)


def test_window_for_aoi_rejects_an_extent_outside_the_selected_scene(tmp_path):
    raster_path = _write_geotiff(
        tmp_path / "b11.tif",
        np.ones((8, 8), dtype=np.uint16),
        pixel_size=20,
    )
    with rasterio.open(raster_path) as dataset:
        with pytest.raises(crosscheck.CrosscheckError, match="does not overlap"):
            crosscheck._window_for_aoi(
                dataset,
                (501000, 2699880, 501080, 2699940),
            )


def test_cross_sensor_reader_aligns_real_local_nisar_and_sentinel_assets(tmp_path, monkeypatch):
    nisar_data = np.array(
        [
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0, 0, 1, 1],
            [0, 0, 1, 1],
        ],
        dtype=np.uint8,
    )
    b03_data = np.array(
        [
            [30, 30, 10, 10],
            [30, 30, 10, 10],
            [25, 25, 15, 15],
            [25, 25, 15, 15],
        ],
        dtype=np.uint16,
    )
    b11_data = np.array([[10, 30], [10, 20]], dtype=np.uint16)
    scl_data = np.array([[6, 4], [5, 3]], dtype=np.uint8)

    nisar_path = _write_geotiff(
        tmp_path / "nisar.tif", nisar_data, pixel_size=10, nodata=255
    )
    b03_path = _write_geotiff(
        tmp_path / "B03.tif", b03_data, pixel_size=10, nodata=0
    )
    b11_path = _write_geotiff(
        tmp_path / "B11.tif", b11_data, pixel_size=20, nodata=0
    )
    scl_path = _write_geotiff(
        tmp_path / "SCL.tif", scl_data, pixel_size=20, nodata=0
    )
    paths = {
        "B03": str(b03_path),
        "B11": str(b11_path),
        "SCL": str(scl_path),
    }
    monkeypatch.setattr(
        crosscheck,
        "_signed_asset_url",
        lambda href: paths[href.rsplit("/", 1)[-1].split(".")[0]],
    )
    item = _item(
        "local-raster-fixture",
        box(88.0, 24.0, 89.0, 25.0),
        "2026-07-12",
        10.0,
    )

    nisar_water, scl_water, mndwi, common_valid, nisar_support, meta = (
        crosscheck._read_cross_sensor_arrays(
            nisar_path=nisar_path,
            item=item,
        )
    )

    assert nisar_water.shape == (2, 2)
    assert scl_water.tolist() == [[True, False], [False, False]]
    assert mndwi.shape == (2, 2)
    assert np.isfinite(mndwi[common_valid]).all()
    assert common_valid.shape == (2, 2)
    assert common_valid.tolist() == [[True, True], [True, False]]
    assert nisar_support.all()
    assert meta["common_valid_pixels"] == 3
    assert meta["sentinel2_width"] == 2
    assert meta["sentinel2_height"] == 2
    assert meta["pixel_area_m2"] == 400.0


def test_cross_sensor_reader_rejects_oversized_nisar_input_before_asset_access(tmp_path, monkeypatch):
    nisar_path = _write_geotiff(
        tmp_path / "large-mask.tif",
        np.zeros((2, 2), dtype=np.uint8),
        pixel_size=10,
        nodata=255,
    )
    monkeypatch.setattr(crosscheck, "MAX_SOURCE_PIXELS", 3)

    def unexpected_sign(_href):
        raise AssertionError("Assets should not be opened after the source-mask size guard fails.")

    monkeypatch.setattr(crosscheck, "_signed_asset_url", unexpected_sign)
    item = _item(
        "too-large",
        box(88.0, 24.0, 89.0, 25.0),
        "2026-07-12",
        10.0,
    )

    with pytest.raises(crosscheck.CrosscheckError, match="safe limit 3"):
        crosscheck._read_cross_sensor_arrays(
            nisar_path=nisar_path,
            item=item,
        )


def test_projected_crs_must_use_true_metre_axes():
    assert crosscheck._is_projected_metre_crs(CRS.from_epsg(32645))
    assert not crosscheck._is_projected_metre_crs(CRS.from_epsg(4326))
    assert not crosscheck._is_projected_metre_crs(CRS.from_epsg(2263))


def test_select_best_items_combines_adjacent_tiles_from_one_datatake_only():
    aoi = box(88.0, 24.0, 88.02, 24.01)
    left = _item(
        "tile-left",
        box(88.0, 24.0, 88.011, 24.01),
        "2026-09-15",
        35.0,
        datatake_id="S2B_DATATAKE_001",
        mgrs_tile="45RYJ",
    )
    right = _item(
        "tile-right",
        box(88.009, 24.0, 88.02, 24.01),
        "2026-09-15",
        42.0,
        datatake_id="S2B_DATATAKE_001",
        mgrs_tile="45RZJ",
    )
    other_datatake = _item(
        "unrelated-partial",
        box(88.0, 24.0, 88.011, 24.01),
        "2026-09-15",
        5.0,
        datatake_id="S2B_DATATAKE_002",
        mgrs_tile="45RYJ",
    )
    selected = crosscheck.select_best_items(
        [other_datatake, right, left],
        observation_date=date(2026, 9, 10),
        aoi_geometry_wgs84=aoi,
        analysis_crs=CRS.from_epsg(32645),
        max_day_offset=5,
        max_cloud_cover=60,
    )

    assert selected is not None
    assert [item["id"] for item in selected] == ["tile-left", "tile-right"]
    assert crosscheck._items_coverage_fraction(selected, aoi, CRS.from_epsg(32645)) > 0.99


def test_datatake_group_key_does_not_mix_platforms_or_dates():
    footprint = box(88.0, 24.0, 88.01, 24.01)
    first = _item(
        "first",
        footprint,
        "2026-09-15",
        20.0,
        datatake_id="DATATAKE-1",
        platform="sentinel-2a",
    )
    same_id_other_platform = _item(
        "other-platform",
        footprint,
        "2026-09-15",
        20.0,
        datatake_id="DATATAKE-1",
        platform="sentinel-2b",
    )
    same_id_other_date = _item(
        "other-date",
        footprint,
        "2026-09-16",
        20.0,
        datatake_id="DATATAKE-1",
        platform="sentinel-2a",
    )
    same_id_other_baseline = _item(
        "other-baseline",
        footprint,
        "2026-09-15",
        20.0,
        datatake_id="DATATAKE-1",
        platform="sentinel-2a",
        processing_baseline="05.12",
    )

    keys = {
        crosscheck._datatake_group_key(first),
        crosscheck._datatake_group_key(same_id_other_platform),
        crosscheck._datatake_group_key(same_id_other_date),
        crosscheck._datatake_group_key(same_id_other_baseline),
    }
    assert len(keys) == 4


def _write_masked_tile(
    directory: Path,
    prefix: str,
    *,
    data: np.ndarray,
    valid: np.ndarray,
    dtype,
    nodata: int,
    pixel_size: float,
):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}.tif"
    data = np.asarray(data, dtype=dtype)
    mask = np.asarray(valid, dtype=bool)
    output = data.copy()
    output[~mask] = nodata
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=data.dtype,
        crs="EPSG:32645",
        transform=from_origin(500000, 2700040, pixel_size, pixel_size),
        nodata=nodata,
    ) as dst:
        dst.write(output, 1)
        dst.write_mask(mask.astype(np.uint8) * 255)
    return path


def test_same_datatake_tile_mosaic_fills_full_aoi_support_from_adjacent_tiles(tmp_path, monkeypatch):
    nisar = _write_masked_tile(
        tmp_path,
        "nisar",
        data=np.array([[1, 0, 1, 0], [0, 1, 0, 1]], dtype=np.uint8),
        valid=np.ones((2, 4), dtype=bool),
        dtype=np.uint8,
        nodata=255,
        pixel_size=10,
    )
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    b03_left = _write_masked_tile(
        left_dir, "B03",
        data=np.array([[30, 30]], dtype=np.uint16),
        valid=np.array([[True, False]]),
        dtype=np.uint16, nodata=0, pixel_size=20,
    )
    b11_left = _write_masked_tile(
        left_dir, "B11",
        data=np.array([[10, 10]], dtype=np.uint16),
        valid=np.array([[True, False]]),
        dtype=np.uint16, nodata=0, pixel_size=20,
    )
    scl_left = _write_masked_tile(
        left_dir, "SCL",
        data=np.array([[6, 0]], dtype=np.uint8),
        valid=np.array([[True, False]]),
        dtype=np.uint8, nodata=0, pixel_size=20,
    )
    b03_right = _write_masked_tile(
        right_dir, "B03",
        data=np.array([[30, 30]], dtype=np.uint16),
        valid=np.array([[False, True]]),
        dtype=np.uint16, nodata=0, pixel_size=20,
    )
    b11_right = _write_masked_tile(
        right_dir, "B11",
        data=np.array([[10, 10]], dtype=np.uint16),
        valid=np.array([[False, True]]),
        dtype=np.uint16, nodata=0, pixel_size=20,
    )
    scl_right = _write_masked_tile(
        right_dir, "SCL",
        data=np.array([[0, 4]], dtype=np.uint8),
        valid=np.array([[False, True]]),
        dtype=np.uint8, nodata=0, pixel_size=20,
    )
    href_to_path = {
        "https://example.test/same-datatake-left/B03.tif": str(b03_left),
        "https://example.test/same-datatake-left/B11.tif": str(b11_left),
        "https://example.test/same-datatake-left/SCL.tif": str(scl_left),
        "https://example.test/same-datatake-right/B03.tif": str(b03_right),
        "https://example.test/same-datatake-right/B11.tif": str(b11_right),
        "https://example.test/same-datatake-right/SCL.tif": str(scl_right),
    }
    monkeypatch.setattr(
        crosscheck,
        "_signed_asset_url",
        lambda href: href_to_path[href],
    )
    left = _item(
        "same-datatake-left",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-07-12",
        12.0,
        datatake_id="S2B_SAME_PASS_001",
        mgrs_tile="45RYJ",
    )
    right = _item(
        "same-datatake-right",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-07-12",
        18.0,
        datatake_id="S2B_SAME_PASS_001",
        mgrs_tile="45RZJ",
    )

    nisar_water, scl_water, mndwi, common_valid, nisar_support, metadata = (
        crosscheck._read_cross_sensor_arrays(
            nisar_path=nisar,
            item=[left, right],
        )
    )

    assert metadata["sentinel2_tile_count"] == 2
    assert metadata["sentinel2_mgrs_tiles"] == ["45RYJ", "45RZJ"]
    assert metadata["tile_common_clear_pixel_counts"] == {
        "same-datatake-left": 1,
        "same-datatake-right": 1,
    }
    assert nisar_support.all()
    assert common_valid.all()
    assert scl_water.tolist() == [[True, False]]
    assert np.isfinite(mndwi).all()
    assert nisar_water.shape == (1, 2)



def test_best_sentinel_datatake_groups_adjacent_tiles_without_mixing_dates_or_platforms():
    aoi = box(88.0, 24.0, 89.0, 25.0)
    left = _item(
        "same-datatake-left",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        18.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
    )
    right = _item(
        "same-datatake-right",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-09-15",
        24.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RZJ",
    )
    different_datatake = _item(
        "different-datatake",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        1.0,
        datatake_id="S2B_OTHER_PASS",
        mgrs_tile="45RYJ",
    )
    different_platform = _item(
        "different-platform",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-09-15",
        1.0,
        datatake_id="S2B_20260915T043701",
        platform="sentinel-2a",
        mgrs_tile="45RZJ",
    )
    different_date = _item(
        "different-date",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-09-16",
        1.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RZJ",
    )

    selected = crosscheck.select_best_items(
        [left, right, different_datatake, different_platform, different_date],
        observation_date=date(2026, 9, 15),
        aoi_geometry_wgs84=aoi,
        analysis_crs=CRS.from_epsg(32645),
        max_day_offset=1,
        max_cloud_cover=40,
    )

    assert selected is not None
    assert {row["id"] for row in selected} == {"same-datatake-left", "same-datatake-right"}
    assert len(selected) == 2
    assert crosscheck._items_coverage_fraction(selected, aoi, CRS.from_epsg(32645)) == pytest.approx(1.0)


def _write_geotiff_at(
    path: Path,
    data: np.ndarray,
    *,
    x_origin: float,
    pixel_size: float = 20.0,
    nodata=None,
):
    data = np.asarray(data)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=data.dtype,
        crs="EPSG:32645",
        transform=from_origin(x_origin, 2700000, pixel_size, pixel_size),
        nodata=nodata,
    ) as destination:
        destination.write(data, 1)
    return path


def test_cross_sensor_reader_mosaics_adjacent_same_datatake_tiles_across_full_nisar_extent(tmp_path, monkeypatch):
    nisar_data = np.array(
        [
            [1, 1, 0, 0],
            [1, 1, 0, 0],
        ],
        dtype=np.uint8,
    )
    nisar_path = _write_geotiff_at(
        tmp_path / "nisar-mask.tif",
        nisar_data,
        x_origin=500000,
        pixel_size=20,
        nodata=255,
    )
    signed_paths = {}
    items = []
    for tile_id, x_origin, green_value, water_class, mgrs_tile in (
        ("left", 500000, 30, 6, "45RYJ"),
        ("right", 500040, 10, 4, "45RZJ"),
    ):
        arrays = {
            "B03": np.full((2, 2), green_value, dtype=np.uint16),
            "B11": np.full((2, 2), 10, dtype=np.uint16),
            "SCL": np.full((2, 2), water_class, dtype=np.uint8),
        }
        for band, values in arrays.items():
            asset_path = _write_geotiff_at(
                tmp_path / f"{tile_id}-{band}.tif",
                values,
                x_origin=x_origin,
                pixel_size=20,
                nodata=0,
            )
            signed_paths[f"https://example.test/tile-{tile_id}/{band}.tif"] = str(asset_path)
        items.append(_item(
            f"tile-{tile_id}",
            box(88.0, 24.0, 89.0, 25.0),
            "2026-09-15",
            20.0,
            datatake_id="S2B_20260915T043701",
            mgrs_tile=mgrs_tile,
        ))

    monkeypatch.setattr(
        crosscheck,
        "_signed_asset_url",
        lambda href: signed_paths[href],
    )

    nisar_water, scl_water, mndwi, common_valid, nisar_support, metadata = (
        crosscheck._read_cross_sensor_arrays(
            nisar_path=nisar_path,
            item=items,
        )
    )

    assert nisar_water.tolist() == nisar_data.astype(bool).tolist()
    assert scl_water.tolist() == [
        [True, True, False, False],
        [True, True, False, False],
    ]
    assert np.allclose(mndwi[:, :2], 0.5)
    assert np.allclose(mndwi[:, 2:], 0.0)
    assert common_valid.all()
    assert nisar_support.all()
    assert metadata["sentinel2_width"] == 4
    assert metadata["sentinel2_height"] == 2
    assert metadata["sentinel2_tile_count"] == 2
    assert metadata["sentinel2_mgrs_tiles"] == ["45RYJ", "45RZJ"]
    assert metadata["tile_common_clear_pixel_counts"] == {
        "tile-left": 4,
        "tile-right": 4,
    }
    assert metadata["common_support_fraction"] == pytest.approx(1.0)



def test_cross_sensor_reader_rejects_mixed_sentinel_datatakes_before_signing_assets(tmp_path, monkeypatch):
    nisar_path = _write_geotiff_at(
        tmp_path / "nisar-mixed-datatake-guard.tif",
        np.zeros((2, 2), dtype=np.uint8),
        x_origin=500000,
        nodata=255,
    )
    first = _item(
        "first-pass",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        20,
        datatake_id="S2B_PASS_A",
    )
    second = _item(
        "second-pass",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-09-15",
        20,
        datatake_id="S2B_PASS_B",
    )

    def unexpected_sign(_href):
        raise AssertionError("Mixed-datatake validation must happen before asset access.")

    monkeypatch.setattr(crosscheck, "_signed_asset_url", unexpected_sign)
    with pytest.raises(crosscheck.CrosscheckError, match="only one platform, datatake, acquisition date and processing baseline"):
        crosscheck._read_cross_sensor_arrays(
            nisar_path=nisar_path,
            item=[first, second],
        )



def test_best_datatake_keeps_latest_generation_per_tile_within_one_processing_baseline():
    aoi = box(88.0, 24.0, 89.0, 25.0)
    left_old = _item(
        "left-old-generation",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        10.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
        processing_baseline="05.11",
        generation_time="2026-09-16T01:00:00Z",
    )
    left_latest = _item(
        "left-latest-generation",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        25.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
        processing_baseline="05.11",
        generation_time="2026-09-17T01:00:00Z",
    )
    right = _item(
        "right-tile",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-09-15",
        30.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RZJ",
        processing_baseline="05.11",
        generation_time="2026-09-17T01:01:00Z",
    )
    other_baseline = _item(
        "other-baseline-left",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        1.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
        processing_baseline="05.12",
        generation_time="2026-09-18T01:00:00Z",
    )

    selected = crosscheck.select_best_items(
        [left_old, left_latest, right, other_baseline],
        observation_date=date(2026, 9, 15),
        aoi_geometry_wgs84=aoi,
        analysis_crs=CRS.from_epsg(32645),
        max_day_offset=1,
        max_cloud_cover=40,
    )

    assert selected is not None
    assert {row["id"] for row in selected} == {"left-latest-generation", "right-tile"}
    assert len(selected) == 2
    assert {row["properties"]["s2:processing_baseline"] for row in selected} == {"05.11"}



def test_canonical_stac_processing_fields_group_and_select_latest_tile_generation():
    aoi = box(88.0, 24.0, 89.0, 25.0)
    left_old = _item(
        "canonical-left-old",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        15.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
        processing_baseline="05.11",
    )
    left_old["properties"].pop("s2:processing_baseline")
    left_old["properties"]["processing:version"] = "05.11"
    left_old["properties"].pop("s2:generation_time")
    left_old["properties"]["processing:datetime"] = "2026-09-16T01:00:00Z"

    left_latest = _item(
        "canonical-left-latest",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        25.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
        processing_baseline="05.11",
    )
    left_latest["properties"].pop("s2:processing_baseline")
    left_latest["properties"]["processing:version"] = "05.11"
    left_latest["properties"].pop("s2:generation_time")
    left_latest["properties"]["processing:datetime"] = "2026-09-17T01:00:00Z"

    right = _item(
        "canonical-right",
        box(88.5, 24.0, 89.0, 25.0),
        "2026-09-15",
        30.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RZJ",
        processing_baseline="05.11",
    )
    right["properties"].pop("s2:processing_baseline")
    right["properties"]["processing:version"] = "05.11"
    right["properties"].pop("s2:generation_time")
    right["properties"]["processing:datetime"] = "2026-09-17T01:01:00Z"

    old_baseline = _item(
        "canonical-other-baseline",
        box(88.0, 24.0, 88.5, 25.0),
        "2026-09-15",
        1.0,
        datatake_id="S2B_20260915T043701",
        mgrs_tile="45RYJ",
        processing_baseline="05.12",
    )
    old_baseline["properties"].pop("s2:processing_baseline")
    old_baseline["properties"]["processing:version"] = "05.12"
    old_baseline["properties"].pop("s2:generation_time")
    old_baseline["properties"]["processing:datetime"] = "2026-09-18T01:00:00Z"

    selected = crosscheck.select_best_items(
        [left_old, left_latest, right, old_baseline],
        observation_date=date(2026, 9, 15),
        aoi_geometry_wgs84=aoi,
        analysis_crs=CRS.from_epsg(32645),
        max_day_offset=1,
        max_cloud_cover=40,
    )

    assert selected is not None
    assert {row["id"] for row in selected} == {"canonical-left-latest", "canonical-right"}
    assert {crosscheck._processing_baseline(row) for row in selected} == {"05.11"}
    assert crosscheck._generation_time(left_latest) == "2026-09-17T01:00:00Z"
