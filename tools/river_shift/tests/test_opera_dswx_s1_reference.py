from __future__ import annotations

from datetime import date
import hashlib

import numpy as np
import rasterio
from rasterio.transform import from_origin

import run_opera_dswx_s1_reference as opera


def _write_wtr(path, values, *, transform=None, tags=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.asarray(values, dtype=np.uint8)
    profile = {
        "driver": "GTiff",
        "height": array.shape[0],
        "width": array.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:32645",
        "transform": transform or from_origin(500000, 2700000, 10, 10),
        "nodata": 255,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)
        dst.update_tags(**(tags or {
            "SPACECRAFT_NAME": "Sentinel-1A",
            "RTC_ORBIT_PASS_DIRECTION": "Ascending",
            "RTC_TRACK_NUMBER": "014",
            "RTC_ABSOLUTE_ORBIT_NUMBER": "12345",
        }))
    return path


def _name(tile, sensing, generated, layer="WTR", version="1.0"):
    return (
        f"OPERA_L3_DSWx-S1_T{tile}_{sensing}_{generated}_"
        f"S1A_30_v{version}_B01_{layer}.tif"
    )


def test_filename_metadata_uses_sensing_time_not_generation_time():
    name = _name(
        "45RVM",
        "20260818T120000Z",
        "20260819T010203Z",
    )
    result = opera._file_metadata(name)
    assert result is not None
    assert result["tile_id"] == "45RVM"
    assert result["observation_date"] == "2026-08-18"
    assert result["generation_time_utc"] == "2026-08-19T01:02:03Z"
    assert result["layer_name"] == "WTR"
    assert result["platform"] == "S1A"
    assert opera._file_metadata(name.replace("_WTR.tif", "_BWTR.tif"))["layer_name"] == "BWTR"


def test_wtr_reference_labels_only_open_water_and_not_water():
    source = np.array(
        [[0, 1, 3, 250], [251, 255, 0, 1]],
        dtype=np.uint8,
    )
    result = opera._classify_wtr(source)
    assert result.tolist() == [
        [0, 1, 255, 255],
        [255, 255, 0, 1],
    ]
    assert set(np.unique(result)).issubset({0, 1, 255})


def test_wtr_classification_preserves_source_invalid_mask():
    source = np.array([[0, 1], [0, 1]], dtype=np.uint8)
    valid = np.array([[True, False], [False, True]])
    result = opera._classify_wtr(source, valid)
    assert result.tolist() == [[0, 255], [255, 1]]


def test_scene_selection_uses_closest_date_and_latest_generation_per_tile():
    rows = [
        {
            "tile_id": "45RVM",
            "observation_date": "2026-08-16",
            "product_version": "1.0",
            "generation_time_utc": "2026-08-16T20:00:00Z",
            "filename": "old",
        },
        {
            "tile_id": "45RVM",
            "observation_date": "2026-08-16",
            "product_version": "1.0",
            "generation_time_utc": "2026-08-17T20:00:00Z",
            "filename": "new",
        },
        {
            "tile_id": "45RWM",
            "observation_date": "2026-08-16",
            "product_version": "1.0",
            "generation_time_utc": "2026-08-17T21:00:00Z",
            "filename": "adjacent",
        },
        {
            "tile_id": "45RVM",
            "observation_date": "2026-08-18",
            "product_version": "1.0",
            "generation_time_utc": "2026-08-18T21:00:00Z",
            "filename": "later-tie-date",
        },
    ]
    selected, observation_date = opera._select_scene_records(
        rows, date.fromisoformat("2026-08-17")
    )
    assert observation_date == "2026-08-16"
    assert [row["filename"] for row in selected] == ["new", "adjacent"]


def test_reference_grid_alignment_keeps_opera_masked_classes_as_nodata(tmp_path):
    prediction = _write_wtr(
        tmp_path / "prediction.tif",
        [[1, 0, 1, 0], [1, 0, 1, 0]],
    )
    source = _write_wtr(
        tmp_path / "tile.tif",
        [[1, 0, 3, 250], [0, 1, 251, 255]],
    )
    output = tmp_path / "reference.tif"
    row = {"tile_id": "45RVM", "observation_date": "2026-08-18", "filename": source.name}
    summary = opera._build_reference_on_nisar_grid(
        prediction_path=prediction,
        wtr_paths=[source],
        selected_records=[row],
        output_path=output,
    )
    with rasterio.open(output) as dataset:
        values = dataset.read(1)
        assert values.tolist() == [[1, 0, 255, 255], [0, 1, 255, 255]]
        assert dataset.nodata == 255
        assert dataset.crs.to_epsg() == 32645
        assert dataset.tags()["CLASS_1"] == "open water (OPERA WTR class 1)"
    assert summary["water_pixels"] == 2
    assert summary["non_water_pixels"] == 2
    assert summary["nodata_pixels"] == 4
    assert len(summary["sha256"]) == 64
    tile_audit = summary["tile_audits"][0]
    assert tile_audit["source_file_bytes"] == source.stat().st_size
    assert tile_audit["source_file_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_conflicting_overlapping_tile_labels_remain_nodata(tmp_path):
    prediction = _write_wtr(
        tmp_path / "prediction.tif",
        [[1, 0], [1, 0]],
    )
    tile_a = _write_wtr(tmp_path / "a.tif", [[1, 0], [1, 0]])
    tile_b = _write_wtr(tmp_path / "b.tif", [[0, 0], [1, 0]])
    tile_c = _write_wtr(tmp_path / "c.tif", [[1, 0], [1, 0]])
    records = [
        {"tile_id": name, "observation_date": "2026-08-18", "filename": path.name}
        for name, path in (("45RVM", tile_a), ("45RWM", tile_b), ("45RXM", tile_c))
    ]
    output = tmp_path / "reference.tif"
    opera._build_reference_on_nisar_grid(
        prediction_path=prediction,
        wtr_paths=[tile_a, tile_b, tile_c],
        selected_records=records,
        output_path=output,
    )
    with rasterio.open(output) as dataset:
        assert dataset.read(1).tolist() == [[255, 0], [1, 0]]


def test_reference_mosaic_rejects_mixed_opera_tracks(tmp_path):
    prediction = _write_wtr(tmp_path / "prediction.tif", [[1, 0], [1, 0]])
    tile_a = _write_wtr(tmp_path / "a.tif", [[1, 0], [1, 0]])
    tile_b = _write_wtr(
        tmp_path / "b.tif",
        [[1, 0], [1, 0]],
        tags={
            "SPACECRAFT_NAME": "Sentinel-1A",
            "ORBIT_PASS_DIRECTION": "Ascending",
            "TRACK_NUMBER": "015",
            "ABSOLUTE_ORBIT_NUMBER": "12346",
        },
    )
    records = [
        {"tile_id": name, "observation_date": "2026-08-18", "filename": path.name}
        for name, path in (("45RVM", tile_a), ("45RWM", tile_b))
    ]
    try:
        opera._build_reference_on_nisar_grid(
            prediction_path=prediction,
            wtr_paths=[tile_a, tile_b],
            selected_records=records,
            output_path=tmp_path / "reference.tif",
        )
    except opera.OperaReferenceError as exc:
        assert "not from the same spacecraft, orbit direction and relative track" in str(exc)
    else:
        raise AssertionError("Mismatched Sentinel-1 tracks must not be mosaicked")


def test_granule_link_discovery_uses_external_https_access():
    class FakeGranule:
        def __init__(self):
            self.requested_access = None

        def data_links(self, *, access=None):
            self.requested_access = access
            return ["https://archive.example.test/OPERA_L3_DSWx-S1_T45RVM_20260818T120000Z_20260819T010203Z_S1A_30_v1.0_B01_WTR.tif"]

    granule = FakeGranule()
    links = opera._granule_links(granule)
    assert granule.requested_access == "external"
    assert len(links) == 1
    assert links[0].startswith("https://")


def test_discovery_pins_pocloud_downloadable_scene_and_parses_wtr(monkeypatch):
    import sys
    from types import SimpleNamespace

    class FakeGranule:
        def get(self, key, default=None):
            if key == "umm":
                return {"GranuleUR": "OPERA test granule"}
            if key == "meta":
                return {"concept-id": "G123456-PODAAC"}
            return default

        def data_links(self, *, access=None):
            assert access == "external"
            return [
                "https://archive.example.test/OPERA_L3_DSWx-S1_T45RVM_"
                "20260818T120000Z_20260819T010203Z_S1A_30_v1.0_B01_WTR.tif"
            ]

    captured = {}

    def fake_search_data(**kwargs):
        captured.update(kwargs)
        return [FakeGranule()]

    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(login=lambda **kwargs: captured.setdefault("login", kwargs),
                         search_data=fake_search_data),
    )

    records, query = opera._discover_records(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        maximum_offset_days=3,
    )

    assert captured["provider"] == "POCLOUD"
    assert captured["cloud_hosted"] is True
    assert captured["downloadable"] is True
    assert captured["count"] == -1
    assert query["collection_short_name"] == opera.COLLECTION_SHORT_NAME
    assert len(records) == 1
    assert records[0]["tile_id"] == "45RVM"
    assert records[0]["observation_date"] == "2026-08-18"
    assert records[0]["layer_name"] == "WTR"


def test_reference_mosaic_rejects_mixed_absolute_orbits(tmp_path):
    prediction = _write_wtr(tmp_path / "prediction.tif", [[1, 0], [1, 0]])
    tile_a = _write_wtr(tmp_path / "a.tif", [[1, 0], [1, 0]])
    tile_b = _write_wtr(
        tmp_path / "b.tif",
        [[1, 0], [1, 0]],
        tags={
            "SPACECRAFT_NAME": "Sentinel-1A",
            "RTC_ORBIT_PASS_DIRECTION": "Ascending",
            "RTC_TRACK_NUMBER": "014",
            "RTC_ABSOLUTE_ORBIT_NUMBER": "12346",
        },
    )
    records = [
        {"tile_id": name, "observation_date": "2026-08-18", "filename": path.name}
        for name, path in (("45RVM", tile_a), ("45RWM", tile_b))
    ]
    try:
        opera._build_reference_on_nisar_grid(
            prediction_path=prediction,
            wtr_paths=[tile_a, tile_b],
            selected_records=records,
            output_path=tmp_path / "reference.tif",
        )
    except opera.OperaReferenceError as exc:
        assert "not from the same spacecraft, orbit direction and relative track" in str(exc)
    else:
        raise AssertionError("Mismatched absolute orbits must not be mosaicked")


def test_unknown_v1_wtr_class_codes_are_rejected(tmp_path):
    prediction = _write_wtr(tmp_path / "prediction.tif", [[1, 0], [1, 0]])
    source = _write_wtr(tmp_path / "unknown-class.tif", [[1, 2], [0, 1]])
    row = {"tile_id": "45RVM", "observation_date": "2026-08-18", "filename": source.name}
    try:
        opera._build_reference_on_nisar_grid(
            prediction_path=prediction,
            wtr_paths=[source],
            selected_records=[row],
            output_path=tmp_path / "reference.tif",
        )
    except opera.OperaReferenceError as exc:
        assert "Unexpected OPERA WTR classes" in str(exc)
    else:
        raise AssertionError("Undocumented WTR class codes must not enter the reference")
