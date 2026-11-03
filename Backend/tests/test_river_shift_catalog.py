from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.river_shift import RiverShiftCatalogRequest, search_gcov_catalogue


GRANULE = (
    "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_"
    "20260718T155041_20260718T155059_P05023_N_F_J_001"
)
PRODUCT_URL = (
    "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
    f"NISAR_L2_GCOV_PROVISIONAL_V1/{GRANULE}/{GRANULE}.h5"
)


def _umm_item() -> dict:
    return {
        "meta": {"concept-id": "G1234567890-ASF"},
        "umm": {
            "GranuleUR": GRANULE,
            "TemporalExtents": [{
                "RangeDateTimes": [{
                    "BeginningDateTime": "2026-07-18T15:50:41.000Z",
                    "EndingDateTime": "2026-07-18T15:50:59.000Z",
                }]
            }],
            "SpatialExtent": {
                "HorizontalSpatialDomain": {
                    "Geometry": {
                        "GPolygons": [{
                            "Boundary": {"Points": [
                                {"Longitude": 89.5, "Latitude": 24.4},
                                {"Longitude": 89.8, "Latitude": 24.4},
                                {"Longitude": 89.8, "Latitude": 24.7},
                                {"Longitude": 89.5, "Latitude": 24.7},
                                {"Longitude": 89.5, "Latitude": 24.4},
                            ]}
                        }]
                    }
                }
            },
            "RelatedUrls": [{
                "URL": PRODUCT_URL,
                "Type": "GET DATA",
                "URLContentType": "DistributionURL",
            }],
            "DataGranule": {
                "ArchiveAndDistributionInformation": [
                    {"Size": "100", "SizeUnit": "MB"}
                ]
            },
        },
    }


class _FakeResponse:
    def __init__(self, body: dict, hits: int = 1) -> None:
        self.headers = {"CMR-Hits": str(hits)}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")


def _request(**overrides) -> RiverShiftCatalogRequest:
    values = {
        "coordinates": [
            [89.5, 24.4],
            [89.8, 24.4],
            [89.8, 24.7],
            [89.5, 24.7],
            [89.5, 24.4],
        ],
        "start_date": date(2026, 6, 17),
        "end_date": date(2026, 10, 31),
        "maturity": "PROVISIONAL",
        "frame_coverage": "ALL",
        "max_results": 100,
    }
    values.update(overrides)
    return RiverShiftCatalogRequest(**values)


def test_search_uses_official_cmr_collection_and_returns_catalogue_only_metadata(monkeypatch):
    captured: list[str] = []

    def fake_urlopen(request, timeout):
        captured.append(request.full_url)
        assert timeout > 0
        return _FakeResponse({"hits": 1, "items": [_umm_item()]})

    monkeypatch.setattr("app.river_shift.urllib.request.urlopen", fake_urlopen)
    result = search_gcov_catalogue(_request())

    assert len(captured) == 1
    params = parse_qs(urlparse(captured[0]).query)
    assert params["short_name"] == ["NISAR_L2_GCOV_PROVISIONAL_V1"]
    assert params["temporal[]"] == ["2026-06-17T00:00:00Z,2026-10-31T23:59:59Z"]
    assert "polygon" in params

    assert result.status == "ready"
    assert result.product_count == 1
    assert result.data_downloaded is False
    assert result.scientific_analysis_performed is False
    product = result.products[0]
    assert product.granule_name == GRANULE
    assert product.maturity == "PROVISIONAL"
    assert product.start_time_utc == "2026-07-18T15:50:41.000Z"
    assert product.main_band_polarization == "HH+HV"
    assert product.frame_coverage == "FULL"
    assert product.download_url == PRODUCT_URL
    assert product.footprint and product.footprint["type"] == "Polygon"
    assert product.size_mb == 100.0


def test_search_all_maturity_queries_beta_and_provisional_separately(monkeypatch):
    captured: list[str] = []

    def fake_urlopen(request, timeout):
        captured.append(request.full_url)
        return _FakeResponse({"hits": 0, "items": []}, hits=0)

    monkeypatch.setattr("app.river_shift.urllib.request.urlopen", fake_urlopen)
    result = search_gcov_catalogue(_request(maturity="ALL"))

    assert len(captured) == 2
    short_names = [parse_qs(urlparse(url).query)["short_name"][0] for url in captured]
    assert short_names == [
        "NISAR_L2_GCOV_BETA_V1",
        "NISAR_L2_GCOV_PROVISIONAL_V1",
    ]
    assert result.status == "no_data"
    assert result.product_count == 0
    assert result.query["collection_short_names"] == short_names


def test_search_rejects_open_invalid_or_over_limit_aoi_before_network(monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("CMR must not be called for invalid AOIs.")

    monkeypatch.setattr("app.river_shift.urllib.request.urlopen", fail_if_called)
    with pytest.raises(HTTPException):
        search_gcov_catalogue(_request(coordinates=[
            [89.5, 24.4], [89.8, 24.4], [89.8, 24.7], [89.5, 24.7],
        ]))
    assert called is False


def test_search_reports_cmr_upstream_errors_as_gateway_failures(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("temporary catalogue outage")

    monkeypatch.setattr("app.river_shift.urllib.request.urlopen", fail)
    with pytest.raises(HTTPException) as raised:
        search_gcov_catalogue(_request())
    assert raised.value.status_code == 504
