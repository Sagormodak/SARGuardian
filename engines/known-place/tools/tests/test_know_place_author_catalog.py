"""Offline tests for exact author catalog identity and safe fallback provenance."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from tools.know_place.author_catalog import (
    _discover_author_products_with_fallback,
    load_author_granules,
    query_cmr_exact_author_product,
    validate_author_catalog_product,
)
from tools.know_place.catalog import EXPECTED_COLLECTION, CatalogIdentityError


def _fake_product_name(name: str, *, maturity: str = "PROVISIONAL") -> dict:
    return {
        "properties": {
            "granuleName": name,
            "url": f"https://asf.alaska.edu/{EXPECTED_COLLECTION}/{name}",
            "dataMaturity": maturity,
            "collectionName": EXPECTED_COLLECTION,
        }
    }


def _fake_product(target: dict, *, maturity: str = "PROVISIONAL") -> dict:
    return _fake_product_name(target["granule_name"], maturity=maturity)


def _cmr_entry(target: dict, *, collection_id: str = "C2854341702-ASF") -> dict:
    return {
        "id": "G1234567890-" + collection_id,
        "producer_granule_id": target["granule_name"],
        "granule_ur": target["granule_name"],
        "title": target["granule_name"],
        "collection_concept_id": collection_id,
        "time_start": "2026-06-20T23:39:21.000Z",
        "time_end": "2026-07-02T23:39:55.000Z",
        "updated": "2026-10-24T00:00:00.000Z",
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                "title": "Download data",
                "type": "application/x-hdf5",
                "href": "https://example.invalid/not-fetched.h5",
            }
        ],
    }


def test_author_manifest_contains_exactly_five_p05023_pairs_and_no_historical_x05026() -> None:
    products = load_author_granules()
    assert len(products) == 5
    assert [row["days"] for row in products] == [12, 12, 12, 24, 12]
    assert all("_P05023_" in row["granule_name"] for row in products)
    assert all("X05026" not in row["granule_name"] for row in products)
    assert products[0]["interval"] == "2026-06-20/2026-07-02"


def test_exact_author_product_identity_accepts_trusted_single_asf_result_without_source_hash() -> None:
    target = load_author_granules()[0]
    output = validate_author_catalog_product(target, [_fake_product(target)])
    assert output["granule_name"] == target["granule_name"]
    assert output["release_id"] == "P05023"
    assert output["catalog_identity_status"] == "EXACT_URL_CONFIRMED"
    assert output["source_sha256"] is None
    assert output["source_sha256_status"] == "NOT_DOWNLOADED"


def test_author_identity_gate_rejects_missing_or_ambiguous_product() -> None:
    target = load_author_granules()[0]
    with pytest.raises(CatalogIdentityError, match="ASF_AUTHOR_EXACT_GRANULE_NOT_FOUND"):
        validate_author_catalog_product(target, [])
    with pytest.raises(CatalogIdentityError, match="ASF_AUTHOR_EXACT_GRANULE_AMBIGUOUS"):
        validate_author_catalog_product(target, [_fake_product(target), _fake_product(target)])


def test_author_identity_gate_rejects_conflicting_maturity() -> None:
    target = load_author_granules()[0]
    with pytest.raises(CatalogIdentityError, match="ASF_AUTHOR_MATURITY_CONFLICT"):
        validate_author_catalog_product(target, [_fake_product(target, maturity="OPERATIONAL")])


def test_cmr_collection_scoped_exact_query_confirms_metadata_without_downloading_source(monkeypatch) -> None:
    import tools.know_place.author_catalog as module

    target = load_author_granules()[0]
    payload = json.dumps({"feed": {"entry": [_cmr_entry(target)]}}).encode("utf-8")

    class FakeResponse:
        status = 200

        def __init__(self, data: bytes):
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._data

    urls: list[str] = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return FakeResponse(payload)

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    row, receipt = query_cmr_exact_author_product(target)

    assert row is not None
    assert row["granule_name"] == target["granule_name"]
    assert row["release_id"] == "P05023"
    assert row["catalog_identity_status"] == "EXACT_CMR_GRANULE_CONFIRMED"
    assert row["catalog_identity_discovery_method"] == "NASA_CMR_COLLECTION_SCOPED_EXACT_QUERY"
    assert row["cmr_collection_concept_id"] == "C2854341702-ASF"
    assert row["source_sha256"] is None
    assert row["source_sha256_status"] == "NOT_DOWNLOADED"
    assert row["cmr_source_payload_downloaded"] is False
    assert receipt["exact_author_id_found"] is True
    assert receipt["source_downloads"] == 0
    assert len(urls) == 2
    assert all("collection_concept_id=C2854341702-ASF" in url for url in urls)
    assert all("producer_granule_id%5B%5D=" in url or "readable_granule_name%5B%5D=" in url for url in urls)


def test_cmr_rejects_same_filename_from_wrong_collection(monkeypatch) -> None:
    import tools.know_place.author_catalog as module

    target = load_author_granules()[0]
    payload = json.dumps({"feed": {"entry": [_cmr_entry(target, collection_id="C_WRONG")]}}).encode()

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return payload

    monkeypatch.setattr(module, "urlopen", lambda request, timeout: FakeResponse())
    row, receipt = query_cmr_exact_author_product(target)
    assert row is None
    assert receipt["exact_author_id_found"] is False
    assert receipt["metadata_match_count"] == 0
    assert receipt["status"] == "NOT_FOUND"


def test_discovery_records_missing_author_pair_and_continues_all_queries(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    targets = load_author_granules()
    missing = targets[0]["granule_name"]
    direct_calls: list[str] = []
    spatial_calls: list[dict] = []
    wildcard_calls: list[dict] = []

    def fake_search(*, dataset: str, granule_list=None, **kwargs):
        assert dataset == "NISAR"
        if granule_list is not None:
            assert len(granule_list) == 1
            pattern = granule_list[0]
            if "*" in pattern:
                wildcard_calls.append({"granule_list": granule_list, **kwargs})
                return []
            direct_calls.append(pattern)
            if pattern == missing:
                return []
            target = next(row for row in targets if row["granule_name"] == pattern)
            return [_fake_product(target)]
        spatial_calls.append(kwargs)
        return []

    monkeypatch.setitem(sys.modules, "asf_search", SimpleNamespace(search=fake_search))
    rows, fallbacks = _discover_author_products_with_fallback()

    assert direct_calls == [row["granule_name"] for row in targets]
    assert len(spatial_calls) == len(wildcard_calls) == 1
    assert spatial_calls[0]["start"] == "2026-06-20T00:00:00Z"
    assert spatial_calls[0]["end"] == "2026-07-02T23:59:59Z"
    assert spatial_calls[0]["processingLevel"] == "GOFF"
    assert spatial_calls[0]["mainBandPolarization"] == "HH"
    assert "intersectsWith" in spatial_calls[0]
    assert wildcard_calls[0]["granule_list"] == [missing.replace("_P05023_", "_*_", 1)]
    assert wildcard_calls[0]["maxResults"] == 100
    assert len(rows) == 5
    assert rows[0]["catalog_identity_status"] == "NOT_FOUND"
    assert rows[0]["spatiotemporal_fallback_search_status"] == "COMPLETED_NO_EXACT_AUTHOR_ID_FOUND"
    assert rows[0]["source_sha256"] is None
    assert rows[0]["same_interval_candidates"] == []
    assert fallbacks[0]["source_downloads"] == 0
    assert fallbacks[0]["cmr_fallback"]["status"] == "NOT_RUN_OFFLINE_TEST_MODE"
    assert fallbacks[0]["exact_author_id_found"] is False
    assert all(row["catalog_identity_status"] == "EXACT_URL_CONFIRMED" for row in rows[1:])


def test_aoi_fallback_can_confirm_exact_p05023_if_direct_id_query_misses(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    targets = load_author_granules()
    missing = targets[0]["granule_name"]

    def fake_search(*, dataset: str, granule_list=None, **kwargs):
        assert dataset == "NISAR"
        if granule_list is not None:
            pattern = granule_list[0]
            if "*" in pattern:
                return []
            return [] if pattern == missing else [_fake_product(next(row for row in targets if row["granule_name"] == pattern))]
        return [_fake_product(targets[0])]

    monkeypatch.setitem(sys.modules, "asf_search", SimpleNamespace(search=fake_search))
    rows, fallbacks = _discover_author_products_with_fallback()

    assert rows[0]["catalog_identity_status"] == "EXACT_URL_CONFIRMED"
    assert rows[0]["catalog_identity_discovery_method"] == "AOI_DATE_FALLBACK_QUERY_AFTER_DIRECT_ID_MISS"
    assert rows[0]["release_id"] == "P05023"
    assert rows[0]["source_sha256"] is None
    assert fallbacks[0]["exact_author_id_found"] is True
    assert fallbacks[0]["source_downloads"] == 0


def test_wildcard_fallback_can_confirm_exact_p05023_when_spatiotemporal_query_misses(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    targets = load_author_granules()
    target = targets[0]
    missing = target["granule_name"]

    def fake_search(*, dataset: str, granule_list=None, **kwargs):
        assert dataset == "NISAR"
        if granule_list is not None:
            pattern = granule_list[0]
            if "*" in pattern:
                return [_fake_product(target)]
            return [] if pattern == missing else [_fake_product(next(row for row in targets if row["granule_name"] == pattern))]
        return []

    monkeypatch.setitem(sys.modules, "asf_search", SimpleNamespace(search=fake_search))
    rows, fallbacks = _discover_author_products_with_fallback()

    assert rows[0]["catalog_identity_status"] == "EXACT_URL_CONFIRMED"
    assert rows[0]["catalog_identity_discovery_method"] == "GRANULE_WILDCARD_QUERY_AFTER_DIRECT_ID_MISS"
    assert rows[0]["source_sha256"] is None
    assert fallbacks[0]["exact_author_id_found"] is True
    assert fallbacks[0]["wildcard_query_result_count"] == 1
    assert fallbacks[0]["source_downloads"] == 0


def test_cmr_fallback_recovers_first_p05023_after_all_asf_paths_miss(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace
    import tools.know_place.author_catalog as module

    targets = load_author_granules()
    missing = targets[0]["granule_name"]
    x05026 = _fake_product_name(missing.replace("_P05023_", "_X05026_"))

    def fake_search(*, dataset: str, granule_list=None, **kwargs):
        assert dataset == "NISAR"
        if granule_list is not None:
            pattern = granule_list[0]
            if "*" in pattern:
                return [x05026]
            if pattern == missing:
                return []
            return [_fake_product(next(row for row in targets if row["granule_name"] == pattern))]
        return [x05026]

    def fake_cmr(target):
        row = {
            "granule_name": target["granule_name"],
            "interval": target["interval"],
            "processing": "PR",
            "track": "098",
            "direction": "A",
            "release_id": "P05023",
            "collection": EXPECTED_COLLECTION,
            "catalog_maturity": "PROVISIONAL",
            "catalog_url_host": "cmr.earthdata.nasa.gov",
            "catalog_identity_status": "EXACT_CMR_GRANULE_CONFIRMED",
            "catalog_identity_discovery_method": "NASA_CMR_COLLECTION_SCOPED_EXACT_QUERY",
            "cmr_collection_concept_id": "C2854341702-ASF",
            "source_sha256": None,
            "source_sha256_status": "NOT_DOWNLOADED",
            "cmr_source_payload_downloaded": False,
        }
        receipt = {"status": "EXACT_AUTHOR_ID_CONFIRMED", "exact_author_id_found": True, "source_downloads": 0}
        return row, receipt

    monkeypatch.setitem(sys.modules, "asf_search", SimpleNamespace(search=fake_search))
    monkeypatch.setattr(module, "query_cmr_exact_author_product", fake_cmr)
    rows, fallbacks = _discover_author_products_with_fallback(include_cmr=True)

    assert rows[0]["catalog_identity_status"] == "EXACT_CMR_GRANULE_CONFIRMED"
    assert rows[0]["catalog_identity_discovery_method"] == "NASA_CMR_COLLECTION_SCOPED_EXACT_QUERY"
    assert rows[0]["release_id"] == "P05023"
    assert rows[0]["source_sha256"] is None
    assert rows[0]["asf_catalog_identity_status"] == "NOT_FOUND"
    assert rows[0]["same_interval_variant_candidates"][0]["release_id"] == "X05026"
    assert fallbacks[0]["cmr_exact_author_id_found"] is True
    assert fallbacks[0]["exact_author_id_found"] is True
    assert fallbacks[0]["source_downloads"] == 0


def test_cmr_lookup_failure_does_not_relabel_x05026_as_author_p05023(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace
    import tools.know_place.author_catalog as module

    targets = load_author_granules()
    missing = targets[0]["granule_name"]
    x05026 = _fake_product_name(missing.replace("_P05023_", "_X05026_"))

    def fake_search(*, dataset: str, granule_list=None, **kwargs):
        assert dataset == "NISAR"
        if granule_list is not None:
            pattern = granule_list[0]
            if "*" in pattern: return [x05026]
            if pattern == missing: return []
            return [_fake_product(next(row for row in targets if row["granule_name"] == pattern))]
        return [x05026]

    def fake_cmr(target):
        return None, {"status": "QUERY_FAILED", "exact_author_id_found": False, "source_downloads": 0}

    monkeypatch.setitem(sys.modules, "asf_search", SimpleNamespace(search=fake_search))
    monkeypatch.setattr(module, "query_cmr_exact_author_product", fake_cmr)
    rows, fallbacks = _discover_author_products_with_fallback(include_cmr=True)

    assert rows[0]["catalog_identity_status"] == "NOT_FOUND"
    assert rows[0]["release_id"] == "P05023"
    assert rows[0]["same_interval_candidates"][0]["release_id"] == "X05026"
    assert rows[0]["source_sha256"] is None
    assert fallbacks[0]["status"] == "CMR_QUERY_FAILED"
    assert fallbacks[0]["cmr_exact_author_id_found"] is False
    assert fallbacks[0]["source_downloads"] == 0


def test_fallback_query_failure_is_recorded_without_relabeling_product(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    targets = load_author_granules()
    missing = targets[0]["granule_name"]

    def fake_search(*, dataset: str, granule_list=None, **kwargs):
        assert dataset == "NISAR"
        if granule_list is not None:
            if "*" in granule_list[0]:
                raise TimeoutError("simulated wildcard catalog timeout")
            return [] if granule_list[0] == missing else [_fake_product(next(row for row in targets if row["granule_name"] == granule_list[0]))]
        raise TimeoutError("simulated spatiotemporal catalog timeout")

    monkeypatch.setitem(sys.modules, "asf_search", SimpleNamespace(search=fake_search))
    rows, fallbacks = _discover_author_products_with_fallback()

    assert rows[0]["catalog_identity_status"] == "NOT_FOUND"
    assert rows[0]["spatiotemporal_fallback_search_status"] == "QUERY_FAILED"
    assert rows[0]["source_sha256"] is None
    assert fallbacks[0]["status"] == "QUERY_FAILED"
    assert fallbacks[0]["spatiotemporal_query_exception_type"] == "TimeoutError"
    assert fallbacks[0]["wildcard_query_exception_type"] == "TimeoutError"
    assert fallbacks[0]["source_downloads"] == 0
