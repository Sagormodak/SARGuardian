import pytest

from types import SimpleNamespace

import json

from download_gcov_product import build_product_url, download_product, trusted_asf_url, trusted_redirect_chain


def test_build_official_provisional_asset_url_from_exact_gcove_granule():
    name = "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_20260718T155041_20260718T155059_P05023_N_F_J_001"
    url = build_product_url(name, "PROVISIONAL")
    assert url == (
        "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
        "NISAR_L2_GCOV_PROVISIONAL_V1/" + name + "/" + name + ".h5"
    )
    assert trusted_asf_url(url)


def test_url_builder_rejects_unknown_maturity_and_invalid_name():
    with pytest.raises(ValueError, match="known BETA or PROVISIONAL"):
        build_product_url("NISAR_L2_PR_GCOV_invalid", "UNKNOWN")
    with pytest.raises(ValueError, match="official NISAR"):
        build_product_url("NISAR_L2_GUNW_invalid", "PROVISIONAL")


def test_asf_url_allowlist_rejects_lookalike_hosts_credentials_and_non_https():
    assert not trusted_asf_url("https://nisar.asf.earthdatacloud.nasa.gov.attacker.example/product.h5")
    assert not trusted_asf_url("https://attacker.asf.earthdatacloud.nasa.gov/product.h5")
    assert not trusted_asf_url("https://user@nisar.asf.earthdatacloud.nasa.gov/product.h5")
    assert not trusted_asf_url("http://nisar.asf.earthdatacloud.nasa.gov/product.h5")


def test_redirect_chain_allows_official_earthdata_login_but_rejects_foreign_host():
    allowed = SimpleNamespace(
        history=[SimpleNamespace(url="https://nisar.asf.earthdatacloud.nasa.gov/login"),
                 SimpleNamespace(url="https://urs.earthdata.nasa.gov/oauth/authorize")],
        url="https://nisar.asf.earthdatacloud.nasa.gov/NISAR/product.h5",
    )
    blocked = SimpleNamespace(
        history=[SimpleNamespace(url="https://nisar.asf.earthdatacloud.nasa.gov/login"),
                 SimpleNamespace(url="https://attacker.example/collect")],
        url="https://nisar.asf.earthdatacloud.nasa.gov/NISAR/product.h5",
    )

    assert trusted_redirect_chain(allowed)
    assert not trusted_redirect_chain(blocked)


class FakeDownloadResponse:
    def __init__(self, payload, *, url, history=None):
        self.payload = payload
        self.url = url
        self.history = history or []
        self.headers = {"Content-Length": str(len(payload))}
        self.status_code = 200
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.payload), chunk_size):
            yield self.payload[offset:offset + chunk_size]


class FakeDownloadSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.trust_env = False
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _download_product_row():
    name = "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_20260718T155041_20260718T155059_P05023_N_F_J_001"
    return {"granule_name": name, "maturity": "PROVISIONAL"}


def test_download_rejects_foreign_redirect_before_writing_product(monkeypatch, tmp_path):
    name = _download_product_row()["granule_name"]
    response = FakeDownloadResponse(
        b"not an HDF5 product",
        url="https://nisar.asf.earthdatacloud.nasa.gov/product.h5",
        history=[SimpleNamespace(url="https://attacker.example/redirect")],
    )
    session = FakeDownloadSession(response)
    monkeypatch.setattr("download_gcov_product._build_authenticated_asf_session", lambda: session)

    with pytest.raises(RuntimeError, match="redirected outside"):
        download_product(_download_product_row(), tmp_path, 30)

    assert not (tmp_path / f"{name}.h5.part").exists()
    assert not (tmp_path / f"{name}.h5").exists()


def test_download_rejects_http_200_html_login_page(monkeypatch, tmp_path):
    name = _download_product_row()["granule_name"]
    response = FakeDownloadResponse(
        b"<html>Earthdata Login Required</html>",
        url="https://nisar.asf.earthdatacloud.nasa.gov/product.h5",
    )
    session = FakeDownloadSession(response)
    monkeypatch.setattr("download_gcov_product.requests.Session", lambda: session)

    with pytest.raises(RuntimeError, match="not a valid HDF5 product"):
        download_product(_download_product_row(), tmp_path, 30)

    assert not (tmp_path / f"{name}.h5").exists()
    assert not (tmp_path / f"{name}.h5.part").exists()


def test_download_accepts_hdf5_signature_and_writes_hash_receipt(monkeypatch, tmp_path):
    name = _download_product_row()["granule_name"]
    payload = b"\\x89HDF\\r\\n\\x1a\\n" + (b"sample-payload" * 100)
    response = FakeDownloadResponse(
        payload,
        url="https://nisar.asf.earthdatacloud.nasa.gov/NISAR/product.h5",
    )
    session = FakeDownloadSession(response)
    monkeypatch.setattr("download_gcov_product.requests.Session", lambda: session)

    result = download_product(_download_product_row(), tmp_path, 30)

    assert result["downloaded"] is True
    assert result["size_bytes"] == len(payload)
    assert (tmp_path / f"{name}.h5").read_bytes() == payload
    receipt = json.loads((tmp_path / f"{name}.download.json").read_text())
    assert receipt["sha256"] == result["sha256"]

def test_hdf5_signature_is_the_exact_eight_byte_format_signature(tmp_path):
    from download_gcov_product import HDF5_SIGNATURE, is_hdf5_file

    assert HDF5_SIGNATURE == bytes.fromhex("894844460d0a1a0a")
    assert len(HDF5_SIGNATURE) == 8
    path = tmp_path / "valid.h5"
    path.write_bytes(HDF5_SIGNATURE + b"content")
    assert is_hdf5_file(path)


def test_hdf5_signature_is_recognized_after_a_valid_user_block(tmp_path):
    from download_gcov_product import HDF5_SIGNATURE, is_hdf5_file

    path = tmp_path / "user-block.h5"
    path.write_bytes((b"\x00" * 512) + HDF5_SIGNATURE + b"content")
    assert is_hdf5_file(path)


def test_redirect_chain_allows_cloudfront_only_when_authorized_by_asf_session():
    cloudfront = SimpleNamespace(
        history=[SimpleNamespace(url="https://nisar.asf.earthdatacloud.nasa.gov/product.h5")],
        url="https://d123example.cloudfront.net/signed/product.h5",
    )
    attacker = SimpleNamespace(
        history=[SimpleNamespace(url="https://nisar.asf.earthdatacloud.nasa.gov/product.h5")],
        url="https://attacker.example/product.h5",
    )

    assert trusted_redirect_chain(cloudfront, {"cloudfront.net"})
    assert not trusted_redirect_chain(attacker, {"cloudfront.net"})
    assert not trusted_redirect_chain(cloudfront, set())
