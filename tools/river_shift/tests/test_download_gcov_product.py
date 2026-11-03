from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from download_gcov_product import (
    HDF5_SIGNATURE,
    _earthaccess_granule_name,
    download_product,
    is_hdf5_file,
)


GRANULE = (
    "NISAR_L2_PR_GCOV_023_091_D_076_2005_QPDH_A_"
    "20260620T123424_20260620T123459_P05023_N_F_J_001"
)


class FakeEarthaccess:
    def __init__(self, results=None, payload=None):
        self.results = list(results or [])
        self.payload = payload if payload is not None else HDF5_SIGNATURE + b"fake-hdf5-content"
        self.login_calls = []
        self.search_calls = []
        self.download_calls = []

    def login(self, **kwargs):
        self.login_calls.append(kwargs)
        return True

    def search_data(self, **kwargs):
        self.search_calls.append(kwargs)
        return self.results

    def download(self, granules, *, local_path, threads, show_progress):
        self.download_calls.append({
            "granules": list(granules),
            "local_path": local_path,
            "threads": threads,
            "show_progress": show_progress,
        })
        destination = Path(local_path) / f"{GRANULE}.h5"
        destination.write_bytes(self.payload)
        return [destination]


def _catalogue_row():
    return {
        "granule_name": GRANULE,
        "maturity": "PROVISIONAL",
        "download_url": "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/example.h5",
    }


def _cmr_result(name=GRANULE):
    return {"umm": {"GranuleUR": name}}


def test_hdf5_signature_is_the_exact_eight_byte_format_signature(tmp_path):
    assert HDF5_SIGNATURE == bytes.fromhex("894844460d0a1a0a")
    assert len(HDF5_SIGNATURE) == 8
    path = tmp_path / "valid.h5"
    path.write_bytes(HDF5_SIGNATURE + b"content")
    assert is_hdf5_file(path)


def test_hdf5_signature_is_recognized_after_a_valid_user_block(tmp_path):
    path = tmp_path / "user-block.h5"
    path.write_bytes((b"\\x00" * 512) + HDF5_SIGNATURE + b"content")
    assert is_hdf5_file(path)


def test_earthaccess_granule_identity_comes_from_exact_cmr_umm_granule_ur():
    assert _earthaccess_granule_name(_cmr_result()) == GRANULE
    assert _earthaccess_granule_name({"umm": {}}) is None
    assert _earthaccess_granule_name({"umm": {"GranuleUR": f"{GRANULE}.h5"}}) == GRANULE


def test_download_resolves_and_downloads_only_the_exact_maturity_granule(monkeypatch, tmp_path):
    fake = FakeEarthaccess(results=[_cmr_result()])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    result = download_product(_catalogue_row(), tmp_path)

    assert fake.login_calls == [{"strategy": "environment"}]
    assert fake.search_calls == [{
        "short_name": "NISAR_L2_GCOV_PROVISIONAL_V1",
        "granule_name": GRANULE,
        "downloadable": True,
        "count": 2,
    }]
    assert len(fake.download_calls) == 1
    assert fake.download_calls[0]["granules"] == [_cmr_result()]
    assert fake.download_calls[0]["threads"] == 1
    assert fake.download_calls[0]["show_progress"] is False

    product_path = tmp_path / f"{GRANULE}.h5"
    assert product_path.is_file()
    assert product_path.read_bytes() == fake.payload
    assert result["downloaded"] is True
    assert result["download_method"] == "earthaccess.download"
    assert result["collection_short_name"] == "NISAR_L2_GCOV_PROVISIONAL_V1"
    assert result["size_bytes"] == len(fake.payload)
    assert result["sha256"] == hashlib.sha256(fake.payload).hexdigest()

    receipt_path = tmp_path / f"{GRANULE}.download.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["granule_name"] == GRANULE
    assert receipt["sha256"] == result["sha256"]
    assert not list(tmp_path.glob(".*.earthaccess-download"))


def test_download_refuses_missing_exact_cmr_match(monkeypatch, tmp_path):
    fake = FakeEarthaccess(results=[_cmr_result(name="NISAR_OTHER_GRANULE")])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    with pytest.raises(RuntimeError, match="did not return exactly one"):
        download_product(_catalogue_row(), tmp_path)

    assert fake.download_calls == []
    assert not (tmp_path / f"{GRANULE}.h5").exists()


def test_download_refuses_ambiguous_exact_cmr_matches(monkeypatch, tmp_path):
    fake = FakeEarthaccess(results=[_cmr_result(), _cmr_result()])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    with pytest.raises(RuntimeError, match="did not return exactly one"):
        download_product(_catalogue_row(), tmp_path)

    assert fake.download_calls == []


def test_download_rejects_http_200_html_or_login_content_and_cleans_temp(monkeypatch, tmp_path):
    fake = FakeEarthaccess(payload=b"<html>Earthdata Login Required</html>", results=[_cmr_result()])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    with pytest.raises(RuntimeError, match="does not contain the HDF5 signature"):
        download_product(_catalogue_row(), tmp_path)

    assert not (tmp_path / f"{GRANULE}.h5").exists()
    assert not (tmp_path / f"{GRANULE}.h5.download.json").exists()
    assert not list(tmp_path.glob(".*.earthaccess-download"))


def test_download_refuses_to_overwrite_existing_exact_raw_source(monkeypatch, tmp_path):
    fake = FakeEarthaccess(results=[_cmr_result()])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)
    existing = tmp_path / f"{GRANULE}.h5"
    existing.write_bytes(HDF5_SIGNATURE + b"previous")

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        download_product(_catalogue_row(), tmp_path)

    assert fake.download_calls == []


@pytest.mark.parametrize("maturity", ["", "UNKNOWN", "BETA;PROVISIONAL"])
def test_download_requires_one_known_collection_maturity(maturity, monkeypatch, tmp_path):
    fake = FakeEarthaccess(results=[_cmr_result()])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)
    product = _catalogue_row()
    product["maturity"] = maturity

    with pytest.raises(ValueError, match="known BETA or PROVISIONAL"):
        download_product(product, tmp_path)

    assert fake.login_calls == []
    assert fake.search_calls == []
    assert fake.download_calls == []
