from __future__ import annotations

from datetime import date
from pathlib import Path
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


def _name(tile, sensing, generated, layer="WTR", version="1.0", platform="S1A"):
    return (
        f"OPERA_L3_DSWx-S1_T{tile}_{sensing}_{generated}_"
        f"{platform}_30_v{version}_B01_{layer}.tif"
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


def test_filename_metadata_accepts_live_catalog_sentinel1c_granule():
    # Exact platform/date/generation tuple observed in the NASA/JPL PO.DAAC
    # virtual directory for 2026-08-18. The WTR asset is linked as a COG.
    name = _name(
        "46UCG",
        "20260818T001104Z",
        "20260818T131526Z",
        platform="S1C",
    )
    result = opera._file_metadata(
        "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/"
        + name
    )
    assert result is not None
    assert result["tile_id"] == "46UCG"
    assert result["observation_date"] == "2026-08-18"
    assert result["generation_time_utc"] == "2026-08-18T13:15:26Z"
    assert result["platform"] == "S1C"
    assert result["layer_number"] == 1
    assert result["layer_name"] == "WTR"


def test_wtr_reference_labels_only_open_water_and_not_water():
    source = np.array(
        [[0, 1, 3, 250, 254], [251, 255, 0, 1, 254]],
        dtype=np.uint8,
    )
    result = opera._classify_wtr(source)
    assert result.tolist() == [
        [0, 1, 255, 255, 255],
        [255, 255, 0, 1, 255],
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
        [[1, 0, 1, 0, 1], [1, 0, 1, 0, 1]],
    )
    source = _write_wtr(
        tmp_path / "tile.tif",
        [[1, 0, 3, 250, 254], [0, 1, 251, 255, 254]],
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
        assert values.tolist() == [[1, 0, 255, 255, 255], [0, 1, 255, 255, 255]]
        assert dataset.nodata == 255
        assert dataset.crs.to_epsg() == 32645
        assert dataset.tags()["CLASS_1"] == "open water (OPERA WTR class 1)"
    assert summary["water_pixels"] == 2
    assert summary["non_water_pixels"] == 2
    assert summary["nodata_pixels"] == 6
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


def _cmr_item(tile="45RVM", sensing="20260818T120000Z", generated="20260819T010203Z", concept="G123456-PODAAC"):
    filename = (
        f"OPERA_L3_DSWx-S1_T{tile}_{sensing}_{generated}_"
        f"S1A_30_v1.0_B01_WTR.tif"
    )
    return {
        "meta": {"concept-id": concept},
        "umm": {
            "GranuleUR": filename,
            "RelatedUrls": [
                {"Type": "GET DATA", "URL": f"https://archive.example.test/{filename}"},
                {"Type": "GET DATA VIA DIRECT ACCESS", "URL": f"s3://example/{filename}"},
            ],
        },
    }


class _FakeCMRResponse:
    def __init__(self, items, hits):
        self.status_code = 200
        self.headers = {"CMR-Hits": str(hits), "Content-Type": "application/vnd.nasa.cmr.umm_results+json"}
        self._payload = {"hits": hits, "items": items}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeCMRSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append({"url": url, "params": list(params), "headers": dict(headers), "timeout": timeout})
        if not self.responses:
            raise AssertionError("Unexpected additional CMR request")
        return self.responses.pop(0)


def test_direct_cmr_discovery_uses_concept_id_and_get_data_https_links(monkeypatch):
    import sys
    from types import SimpleNamespace

    item = _cmr_item()
    session = _FakeCMRSession([_FakeCMRResponse([item], 1)])
    captured_login = {}
    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(
            login=lambda **kwargs: captured_login.update(kwargs),
            get_requests_https_session=lambda: session,
        ),
    )

    records, query = opera._discover_records(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        maximum_offset_days=3,
    )

    assert captured_login == {"strategy": "environment"}
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == opera.CMR_UMM_GRANULE_SEARCH_URL
    assert call["headers"]["Accept"] == opera.CMR_UMM_ACCEPT
    params = dict(call["params"])
    assert params["collection_concept_id"] == opera.COLLECTION_CONCEPT_ID
    assert "temporal[]" not in params
    assert params["bounding_box"] == "89.6,24,89.8,24.2"
    assert params["page_num"] == "1"
    assert params["page_size"] == str(opera.CMR_PAGE_SIZE)
    assert query["collection_query_method"].startswith("direct authenticated CMR UMM JSON")
    assert query["granules_returned_by_cmr"] == 1
    assert query["wtr_records_parsed"] == 1
    assert query["cmr_temporal_filter_applied"] is False
    assert query["local_temporal_filter_utc"] == [
        "2026-08-14T00:00:00Z",
        "2026-08-20T23:59:59Z",
    ]
    assert records[0]["tile_id"] == "45RVM"
    assert records[0]["observation_date"] == "2026-08-18"
    assert records[0]["layer_name"] == "WTR"
    assert records[0]["wtr_download_url"].startswith("https://")
    assert records[0]["wtr_download_url"].endswith("_WTR.tif")
    assert "s3://" not in records[0]["wtr_download_url"]


def test_cmr_zero_result_probes_isolate_temporal_and_aoi_coverage(monkeypatch):
    import sys
    from types import SimpleNamespace

    item = _cmr_item()
    session = _FakeCMRSession([
        _FakeCMRResponse([], 0),        # AOI + date
        _FakeCMRResponse([item], 15),   # collection + date only
        _FakeCMRResponse([], 0),        # collection + AOI only
        _FakeCMRResponse([item], 3015), # collection inventory
    ])
    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(login=lambda **kwargs: None, get_requests_https_session=lambda: session),
    )

    records, query = opera._discover_records(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        maximum_offset_days=3,
    )

    assert records == []
    assert len(session.calls) == 4
    diagnostics = query["cmr_diagnostics"]
    assert diagnostics["aoi_inventory_query"]["hits"] == 0
    assert diagnostics["aoi_inventory_query"]["server_side_temporal_filter_applied"] is False
    probes = diagnostics["zero_result_probes"]
    assert probes["collection_and_date"]["hits"] == 15
    assert probes["collection_and_aoi"]["hits"] == 0
    assert probes["collection_only"]["hits"] == 3015
    assert probes["collection_and_date"]["query"]["bounding_box_wgs84"] is None
    assert probes["collection_and_aoi"]["query"]["temporal"] is None


def test_cmr_search_paginates_using_cmr_hits_header():
    first_items = [{"meta": {"concept-id": f"G{i}-POCLOUD"}, "umm": {}} for i in range(2)]
    second_items = [{"meta": {"concept-id": "G2-POCLOUD"}, "umm": {}}]
    session = _FakeCMRSession([
        _FakeCMRResponse(first_items, 3),
        _FakeCMRResponse(second_items, 3),
    ])

    result = opera._cmr_umm_search(
        session,
        collection_concept_id=opera.COLLECTION_CONCEPT_ID,
        temporal=("2026-08-14T00:00:00Z", "2026-08-20T23:59:59Z"),
        bounding_box=(89.6, 24.0, 89.8, 24.2),
        page_size=2,
    )

    assert result["hits"] == 3
    assert len(result["items"]) == 3
    assert len(result["pages"]) == 2
    assert dict(session.calls[0]["params"])["page_num"] == "1"
    assert dict(session.calls[1]["params"])["page_num"] == "2"


def test_raw_cmr_umm_items_expose_only_https_get_data_links():
    item = _cmr_item()
    links = opera._granule_links(item)
    assert len(links) == 1
    assert links[0].startswith("https://")
    assert links[0].endswith("_WTR.tif")



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


def test_selected_wtr_download_uses_authenticated_https_urls_and_pocloud_provider(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    captured = {}

    def fake_download(urls, *, local_path, provider, threads):
        captured.update({"urls": list(urls), "local_path": local_path, "provider": provider, "threads": threads})
        target = Path(local_path) / Path(urls[0]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"test-opera-wtr")
        return [target]

    monkeypatch.setitem(sys.modules, "earthaccess", SimpleNamespace(download=fake_download))
    filename = (
        "OPERA_L3_DSWx-S1_T45RVM_20260818T120000Z_"
        "20260819T010203Z_S1A_30_v1.0_B01_WTR.tif"
    )
    url = f"https://archive.example.test/{filename}"
    paths = opera._download_selected(
        [{"filename": filename, "wtr_download_url": url}],
        tmp_path / "downloads",
    )
    assert captured["urls"] == [url]
    assert captured["provider"] == "POCLOUD"
    assert captured["threads"] == 4
    assert paths == [tmp_path / "downloads" / filename]
    assert paths[0].read_bytes() == b"test-opera-wtr"


def test_cmr_scene_discovery_window_can_be_wider_without_changing_strict_score_gate(monkeypatch):
    import sys
    from types import SimpleNamespace

    item = _cmr_item()
    session = _FakeCMRSession([_FakeCMRResponse([item], 1)])
    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(
            login=lambda **kwargs: None,
            get_requests_https_session=lambda: session,
        ),
    )

    records, query = opera._discover_records(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        maximum_offset_days=3,
        discovery_window_days=14,
    )

    params = dict(session.calls[0]["params"])
    assert "temporal[]" not in params
    assert params["bounding_box"] == "89.6,24,89.8,24.2"
    assert query["local_temporal_filter_utc"] == [
        "2026-08-03T00:00:00Z",
        "2026-08-31T23:59:59Z",
    ]
    assert query["cmr_temporal_filter_applied"] is False
    assert query["discovery_window_days"] == 14
    assert query["strict_score_maximum_date_offset_days"] == 3
    assert records[0]["observation_date"] == "2026-08-18"


def test_aoi_inventory_is_filtered_locally_by_discovery_window(monkeypatch):
    import sys
    from types import SimpleNamespace

    in_window = _cmr_item(sensing="20260818T120000Z", concept="G-IN-POCLOUD")
    out_of_window = _cmr_item(
        sensing="20260710T120000Z",
        generated="20260711T010203Z",
        concept="G-OUT-POCLOUD",
    )
    session = _FakeCMRSession([_FakeCMRResponse([in_window, out_of_window], 2)])
    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(
            login=lambda **kwargs: None,
            get_requests_https_session=lambda: session,
        ),
    )

    records, query = opera._discover_records(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        maximum_offset_days=3,
        discovery_window_days=14,
    )

    assert len(session.calls) == 1
    params = dict(session.calls[0]["params"])
    assert "temporal[]" not in params
    assert len(records) == 1
    assert records[0]["concept_id"] == "G-IN-POCLOUD"
    assert query["granules_returned_by_cmr"] == 2
    assert query["wtr_records_parsed"] == 1
    assert query["records_outside_local_discovery_window"] == 1
    assert query["discovery_window_days"] == 14
    assert query["strict_score_maximum_date_offset_days"] == 3


def _rtc_cmr_item(
    burst="T069-147170-IW1",
    sensing="20260818T232134Z",
    generated="20260819T010203Z",
    platform="S1A",
    concept="RTC123456-ASF",
    layers=("VV", "VH", "MASK"),
):
    base = (
        f"OPERA_L2_RTC-S1_{burst}_{sensing}_{generated}_"
        f"{platform}_30_v1.0"
    )
    related = [
        {
            "Type": "GET DATA",
            "URL": f"https://datapool.asf.alaska.edu/OPERA-S1/{base}_{layer}.tif",
        }
        for layer in layers
    ]
    related.append({
        "Type": "GET DATA",
        "URL": f"https://datapool.asf.alaska.edu/OPERA-S1/{base}.h5",
    })
    return {
        "meta": {"concept-id": concept},
        "umm": {
            "GranuleUR": f"{base}.h5",
            "RelatedUrls": related,
        },
    }


def test_rtc_filename_metadata_parses_burst_and_layer():
    base = (
        "OPERA_L2_RTC-S1_T069-147170-IW1_20260818T232134Z_"
        "20260819T010203Z_S1A_30_v1.0_VV.tif"
    )
    parsed = opera._rtc_file_metadata(f"https://datapool.example.test/{base}")
    assert parsed is not None
    assert parsed["burst_id"] == "T069-147170-IW1"
    assert parsed["observation_date"] == "2026-08-18"
    assert parsed["platform"] == "S1A"
    assert parsed["pixel_spacing_m"] == 30
    assert parsed["layer_name"] == "VV"
    assert opera._rtc_file_metadata(base.replace("_VV.tif", "_BROWSE.png")) is None


def test_rtc_filename_metadata_accepts_sentinel1c_platform():
    filename = (
        "OPERA_L2_RTC-S1_T069-147170-IW1_20260818T232134Z_"
        "20260819T010203Z_S1C_30_v1.0_VV.tif"
    )
    parsed = opera._rtc_file_metadata(filename)
    assert parsed is not None
    assert parsed["platform"] == "S1C"
    assert parsed["layer_name"] == "VV"
    assert parsed["observation_date"] == "2026-08-18"


def test_rtc_inventory_discovers_same_aoi_sentinel1_bursts_without_water_labels(monkeypatch):
    import sys
    from types import SimpleNamespace

    near = _rtc_cmr_item(
        burst="T069-147170-IW1",
        sensing="20260818T232134Z",
        generated="20260819T010203Z",
        concept="RTC-NEAR-ASF",
    )
    outside = _rtc_cmr_item(
        burst="T069-147171-IW1",
        sensing="20260710T232134Z",
        generated="20260711T010203Z",
        concept="RTC-OUTSIDE-ASF",
        layers=("VV", "MASK"),
    )
    session = _FakeCMRSession([_FakeCMRResponse([near, outside], 2)])
    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(
            login=lambda **kwargs: None,
            get_requests_https_session=lambda: session,
        ),
    )

    candidates, query = opera._discover_opera_rtc_s1_inventory(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        discovery_window_days=30,
        strict_score_maximum_date_offset_days=3,
    )

    assert len(session.calls) == 1
    params = dict(session.calls[0]["params"])
    assert params["collection_concept_id"] == opera.RTC_COLLECTION_CONCEPT_ID
    assert params["bounding_box"] == "89.6,24,89.8,24.2"
    assert "temporal[]" not in params
    assert len(candidates) == 1
    assert candidates[0]["burst_id"] == "T069-147170-IW1"
    assert candidates[0]["available_layers"] == ["MASK", "VH", "VV"]
    assert candidates[0]["has_validity_mask"] is True
    assert query["cmr_aoi_inventory_hits"] == 2
    assert query["parsed_rtc_burst_groups_with_vv"] == 2
    assert query["bursts_within_discovery_window"] == 1
    assert query["bursts_within_strict_score_window"] == 1
    assert query["acquisition_dates_within_strict_score_window"][0]["observation_date"] == "2026-08-18"
    assert "water_labels_generated" not in query
    assert query["collection_concept_id"] == "C2777436413-ASF"


def test_rtc_inventory_separates_wide_discovery_from_strict_score_window(monkeypatch):
    import sys
    from types import SimpleNamespace

    scene = _rtc_cmr_item(
        burst="T069-147170-IW1",
        sensing="20260825T232134Z",
        generated="20260826T010203Z",
        concept="RTC-OUTSIDE-STRICT-ASF",
    )
    session = _FakeCMRSession([_FakeCMRResponse([scene], 1)])
    monkeypatch.setitem(
        sys.modules,
        "earthaccess",
        SimpleNamespace(
            login=lambda **kwargs: None,
            get_requests_https_session=lambda: session,
        ),
    )

    candidates, query = opera._discover_opera_rtc_s1_inventory(
        aoi_wkt="POLYGON((89.6 24.0,89.8 24.0,89.8 24.2,89.6 24.2,89.6 24.0))",
        requested_date=date.fromisoformat("2026-08-17"),
        discovery_window_days=30,
        strict_score_maximum_date_offset_days=3,
    )

    assert len(candidates) == 1
    assert query["bursts_within_discovery_window"] == 1
    assert query["bursts_within_strict_score_window"] == 0
    assert candidates[0]["observation_date"] == "2026-08-25"
    assert query["acquisition_dates_within_discovery_window"][0]["date_offset_days"] == 8


