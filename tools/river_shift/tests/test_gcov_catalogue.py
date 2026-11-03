import json
from datetime import date
from urllib.parse import parse_qs, urlparse

from discover_gcov_products import normalize_product, parse_granule_metadata, search_catalogue, validate_aoi


GRANULE = "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_20260718T155041_20260718T155059_P05023_N_F_J_001"
PROVISIONAL_URL = (
    "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
    "NISAR_L2_GCOV_PROVISIONAL_V1/" + GRANULE + "/" + GRANULE + ".h5"
)


def test_parse_gcov_granule_metadata_from_official_single_acquisition_name():
    result = parse_granule_metadata(GRANULE)
    assert result["cycle"] == "025"
    assert result["relative_orbit"] == "151"
    assert result["orbit_direction"] == "A"
    assert result["frame"] == "011"
    assert result["bandwidth_mode"] == "4005"
    assert result["polarization_code"] == "DHDH"
    assert result["acquisition_start_utc"] == "20260718T155041"
    assert result["acquisition_end_utc"] == "20260718T155059"
    assert result["crid"] == "P05023"
    assert result["frame_coverage"] == "FULL"


def test_normalize_product_preserves_url_maturity_dates_and_polarization():
    product = normalize_product({
        "granuleName": GRANULE,
        "url": PROVISIONAL_URL,
        "processingLevel": "GCOV",
    })
    assert product is not None
    assert product["product"] == "GCOV"
    assert product["maturity"] == "PROVISIONAL"
    assert product["relative_orbit"] == "151"
    assert product["start_time_utc"] == "20260718T155041"
    assert product["main_band_polarization"] == "HH+HV"
    assert product["frame_coverage"] == "FULL"


def test_normalize_product_constructs_url_only_from_explicit_collection_maturity():
    product = normalize_product({
        "granuleName": GRANULE,
        "processingLevel": "GCOV",
        "collectionName": "NISAR_L2_GCOV_PROVISIONAL_V1",
    })
    assert product is not None
    assert product["maturity"] == "PROVISIONAL"
    assert product["download_url"] == PROVISIONAL_URL


def test_unknown_maturity_is_not_guessed_from_the_crid():
    product = normalize_product({"granuleName": GRANULE, "processingLevel": "GCOV"})
    assert product is not None
    assert product["maturity"] == "UNKNOWN"
    assert product["download_url"] is None


def test_explicit_maturity_enum_is_respected_without_collection_path():
    product = normalize_product({
        "granuleName": GRANULE,
        "processingLevel": "GCOV",
        "dataMaturity": "PROVISIONAL",
    })
    assert product is not None
    assert product["maturity"] == "PROVISIONAL"
    assert product["download_url"].endswith("/" + GRANULE + ".h5")


def test_search_uses_official_cmr_collection_short_name_and_umm_json(monkeypatch):
    captured = []

    def fake_umm_item():
        return {
            "meta": {"concept-id": "G1234567890-ASF"},
            "umm": {
                "GranuleUR": GRANULE,
                "TemporalExtents": [{
                    "RangeDateTimes": [{
                        "BeginningDateTime": "2026-07-18T15:50:41.000Z",
                        "EndingDateTime": "2026-07-18T15:50:59.000Z"
                    }]
                }],
                "SpatialExtent": {
                    "HorizontalSpatialDomain": {
                        "Geometry": {
                            "GPolygons": [{
                                "Boundary": {
                                    "Points": [
                                        {"Longitude": 89.5, "Latitude": 24.4},
                                        {"Longitude": 89.8, "Latitude": 24.4},
                                        {"Longitude": 89.8, "Latitude": 24.7},
                                        {"Longitude": 89.5, "Latitude": 24.7},
                                        {"Longitude": 89.5, "Latitude": 24.4}
                                    ]
                                }
                            }]
                        }
                    }
                },
                "RelatedUrls": [{"URL": PROVISIONAL_URL, "Type": "GET DATA", "URLContentType": "DistributionURL"}],
                "DataGranule": {
                    "ArchiveAndDistributionInformation": [{"Size": "100", "SizeUnit": "MB"}]
                }
            }
        }

    class FakeHeaders(dict):
        pass

    class FakeResponse:
        headers = FakeHeaders({"CMR-Hits": "1"})
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({"hits": 1, "items": [fake_umm_item()]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured.append(request.full_url)
        assert "NISAR_L2_GCOV_PROVISIONAL_V1" in request.full_url
        assert "processingLevel" not in request.full_url
        return FakeResponse()

    monkeypatch.setattr("discover_gcov_products.urllib.request.urlopen", fake_urlopen)
    result = search_catalogue(
        "POLYGON ((89.5 24.4, 89.8 24.4, 89.8 24.7, 89.5 24.7, 89.5 24.4))",
        date(2026, 6, 17),
        date(2026, 10, 31),
        "PROVISIONAL",
        None,
        None,
        100,
        20,
        "FULL",
    )
    assert len(captured) == 1
    params = parse_qs(urlparse(captured[0]).query)
    assert params["short_name"] == ["NISAR_L2_GCOV_PROVISIONAL_V1"]
    assert params["temporal[]"] == ["2026-06-17T00:00:00Z,2026-10-31T23:59:59Z"]
    assert "polygon" in params
    assert result["product_count"] == 1
    product = result["products"][0]
    assert product["maturity"] == "PROVISIONAL"
    assert product["granule_name"] == GRANULE
    assert product["main_band_polarization"] == "HH+HV"
    assert product["footprint"]["type"] == "Polygon"
    assert product["size_mb"] == 100.0
    assert result["query"]["response_format"] == "UMM-G 1.6.7"


def test_validate_aoi_rejects_non_polygon():
    import pytest
    with pytest.raises(ValueError):
        validate_aoi("POINT (90 25)")


def test_validate_aoi_rejects_self_intersection():
    import pytest
    with pytest.raises(ValueError):
        validate_aoi("POLYGON ((0 0, 2 2, 0 2, 2 0, 0 0))")
