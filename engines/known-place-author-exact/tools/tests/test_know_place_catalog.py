from __future__ import annotations

from copy import deepcopy

import pytest

from tools.know_place.catalog import (
    CatalogIdentityError,
    EXPECTED_COLLECTION,
    TARGET_PRODUCTS,
    validate_exact_catalog_product,
)


class FakeProduct:
    def __init__(self, properties, urls):
        self.properties = properties
        self._urls = urls

    def get_urls(self):
        return self._urls


def valid_result(target=None, *, maturity="PROVISIONAL", collection=EXPECTED_COLLECTION,
                 bytes_value=None, host="nisar.asf.earthdatacloud.nasa.gov"):
    target = target or TARGET_PRODUCTS[0]
    name = target["granule_name"]
    byte_count = target["expected_source_bytes"] if bytes_value is None else bytes_value
    url = f"https://{host}/NISAR/{collection}/{name}/{name}.h5"
    return FakeProduct(
        {
            "fileName": name + ".h5",
            "granuleName": name,
            "dataMaturity": maturity,
            "collectionName": collection,
            "bytes": byte_count,
        },
        [url],
    )


def test_exact_catalog_entry_preserves_pair_release_size_and_reference_hash():
    target = TARGET_PRODUCTS[0]
    row = validate_exact_catalog_product(target, [valid_result(target)])
    assert row["granule_name"] == target["granule_name"]
    assert row["reference_date"] == "2026-06-20"
    assert row["secondary_date"] == "2026-07-02"
    assert row["release_id"] == "X05026"
    assert row["catalog_maturity"] == "PROVISIONAL"
    assert row["catalog_size_bytes"] == 1090519040
    assert row["expected_source_sha256"] == target["historical_source_sha256"]
    assert row["author_product_variant_status"] == "NOT_VERIFIED_AGAINST_AUTHOR_SUPPLEMENT"


def test_catalog_gate_fails_when_exact_product_is_missing():
    with pytest.raises(CatalogIdentityError, match="ASF_EXACT_GRANULE_NOT_FOUND"):
        validate_exact_catalog_product(TARGET_PRODUCTS[0], [])


def test_catalog_gate_rejects_maturity_mismatch():
    record = valid_result(maturity="BETA")
    with pytest.raises(CatalogIdentityError, match="ASF_MATURITY_CONFLICT"):
        validate_exact_catalog_product(TARGET_PRODUCTS[0], [record])


def test_catalog_gate_rejects_collection_mismatch():
    record = valid_result(collection="NISAR_L2_GOFF_BETA_V1")
    with pytest.raises(CatalogIdentityError, match="ASF_COLLECTION_CONFLICT|ASF_EXACT_GRANULE_NOT_FOUND"):
        validate_exact_catalog_product(TARGET_PRODUCTS[0], [record])


def test_catalog_gate_rejects_untrusted_download_host():
    record = valid_result(host="example.com")
    with pytest.raises(CatalogIdentityError, match="ASF_EXACT_GRANULE_NOT_FOUND"):
        validate_exact_catalog_product(TARGET_PRODUCTS[0], [record])


def test_catalog_gate_rejects_duplicate_exact_records():
    target = TARGET_PRODUCTS[0]
    with pytest.raises(CatalogIdentityError, match="ASF_EXACT_GRANULE_AMBIGUOUS"):
        validate_exact_catalog_product(target, [valid_result(target), valid_result(target)])


def test_catalog_gate_rejects_changed_source_size():
    target = TARGET_PRODUCTS[0]
    with pytest.raises(CatalogIdentityError, match="ASF_BYTE_SIZE_CHANGED"):
        validate_exact_catalog_product(
            target, [valid_result(target, bytes_value=target["expected_source_bytes"] + 1)]
        )


def test_catalog_gate_rejects_wrong_pair_dates_even_with_matching_granule_url():
    target = deepcopy(TARGET_PRODUCTS[0])
    target["secondary_date"] = "2026-07-03"
    with pytest.raises(CatalogIdentityError, match="PINNED_TARGET_DATE_CONFLICT"):
        validate_exact_catalog_product(target, [valid_result(TARGET_PRODUCTS[0])])


def test_exact_object_url_must_name_expected_provisional_collection():
    target = TARGET_PRODUCTS[0]
    wrong = FakeProduct(
        {
            "fileName": target["granule_name"] + ".h5",
            "dataMaturity": "PROVISIONAL",
            "collectionName": EXPECTED_COLLECTION,
        },
        [f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_BETA_V1/"
         f"{target['granule_name']}/{target['granule_name']}.h5"],
    )
    with pytest.raises(CatalogIdentityError, match="ASF_EXACT_GRANULE_NOT_FOUND"):
        validate_exact_catalog_product(target, [wrong])

def test_catalog_gate_defers_formatted_file_size_to_downloaded_sha256():
    target = TARGET_PRODUCTS[0]
    formatted = {
        target["granule_name"] + ".h5": {"bytes": 1.09, "format": "GB"}
    }
    row = validate_exact_catalog_product(
        target, [valid_result(target, bytes_value=formatted)]
    )
    assert row["catalog_size_bytes"] is None
    assert row["catalog_size_evidence"]["status"] == (
        "NON_EXACT_FORMATTED_SIZE_DEFERRED_TO_SOURCE_SHA256"
    )
    assert row["expected_source_sha256"] == target["historical_source_sha256"]


def test_catalog_gate_rejects_exact_raw_umm_size_mismatch():
    target = TARGET_PRODUCTS[0]
    record = valid_result(target)
    record.umm = {
        "DataGranule": {
            "ArchiveAndDistributionInformation": [{
                "Name": target["granule_name"] + ".h5",
                "SizeInBytes": target["expected_source_bytes"] + 2,
            }]
        }
    }
    with pytest.raises(CatalogIdentityError, match="ASF_BYTE_SIZE_CHANGED"):
        validate_exact_catalog_product(target, [record])

