from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import requests

import download_gcov_product as download_module

from download_gcov_product import (
    HDF5_SIGNATURE,
    _earthaccess_granule_name,
    download_product,
    is_hdf5_file,
    _earthdata_http_auth_rejection,
    _reauthenticate_with_username_password,
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


class FakeRangeResponse:
    def __init__(self, *, status_code, headers=None, payload=b""):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.payload = payload
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        if self.payload:
            yield self.payload

    def close(self):
        self.closed = True


class FakeRangeSession:
    def __init__(self, owner):
        self.owner = owner

    def get(self, url, *, headers, stream, allow_redirects, timeout):
        del url, stream, allow_redirects, timeout
        value = headers["Range"]
        start, end = (int(item) for item in value.removeprefix("bytes=").split("-", 1))
        key = (start, end)
        with self.owner.range_lock:
            self.owner.range_calls.append(key)
            self.owner.range_counts[key] = self.owner.range_counts.get(key, 0) + 1
            call_number = self.owner.range_counts[key]

        if not self.owner.range_supported:
            return FakeRangeResponse(status_code=200, payload=b"")
        if self.owner.fail_once_for == key and call_number == 1:
            raise requests.exceptions.ConnectionError("simulated transient range connection drop")

        payload = self.owner.payload[start:end + 1]
        return FakeRangeResponse(
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{len(self.owner.payload)}",
                "Content-Length": str(len(payload)),
                "ETag": self.owner.etag,
            },
            payload=payload,
        )


class RangedFakeEarthaccess(FakeEarthaccess):
    def __init__(self, *, range_supported=True, fail_once_for=None):
        super().__init__(results=[_cmr_result()])
        import threading
        self.range_supported = range_supported
        self.fail_once_for = fail_once_for
        self.range_calls = []
        self.range_counts = {}
        self.range_lock = threading.Lock()
        self.etag = '"fixture-etag"'

    def get_requests_https_session(self):
        return FakeRangeSession(self)


def _exact_range_catalogue_row():
    return {
        **_catalogue_row(),
        "download_url": (
            "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
            f"{GRANULE}/{GRANULE}.h5"
        ),
    }


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

def test_first_wave_token_rejection_is_queued_without_immediate_password_retry(monkeypatch, tmp_path, capsys):
    class TokenRejectingOnDownload(FakeEarthaccess):
        def __init__(self):
            super().__init__(results=[_cmr_result()])
            self._auth = object()
            self._store = object()

        def login(self, **kwargs):
            self.login_calls.append(kwargs)
            return True

        def download(self, granules, *, local_path, threads, show_progress):
            self.download_calls.append({"attempt": "first-wave"})
            raise RuntimeError("Download failed for product. Status code: 401")

    fake = TokenRejectingOnDownload()
    monkeypatch.setenv("EARTHDATA_TOKEN", "stale-token-test-value")
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "password-test-value")
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    with pytest.raises(RuntimeError, match="queued for the single delayed retry wave"):
        download_product(_catalogue_row(), tmp_path)

    assert fake.login_calls == [{"strategy": "environment"}]
    assert len(fake.download_calls) == 1
    output = capsys.readouterr().out
    assert "stale-token-test-value" not in output
    assert '"immediate_retry_performed": false' in output
    assert not (tmp_path / f"{GRANULE}.h5").exists()
    assert not list(tmp_path.glob(".*.earthaccess-download"))


def test_earthdata_auth_rejection_classifier_only_matches_401_or_403():
    assert _earthdata_http_auth_rejection(RuntimeError("Download failed. Status code: 401")) == 401
    assert _earthdata_http_auth_rejection(RuntimeError("Download failed. Status code: 403")) == 403
    assert _earthdata_http_auth_rejection(RuntimeError("network timeout")) is None
    assert _earthdata_http_auth_rejection(RuntimeError("Download failed. Status code: 503")) is None


def test_username_password_fallback_resets_cached_earthaccess_token_auth(monkeypatch):
    class FakeAuth:
        pass

    class FakeEarthaccess:
        Auth = FakeAuth

        def __init__(self):
            self._auth = object()
            self._store = object()
            self.login_calls = []

        def login(self, **kwargs):
            self.login_calls.append({
                **kwargs,
                "token_present": bool(os.environ.get("EARTHDATA_TOKEN")),
            })
            self._store = "new-user-password-store"

    fake = FakeEarthaccess()
    monkeypatch.setenv("EARTHDATA_TOKEN", "rejected-token")
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "password-test-value")

    assert _reauthenticate_with_username_password(fake) is True

    assert fake.login_calls == [{
        "strategy": "environment",
        "token_present": False,
    }]
    assert isinstance(fake._auth, FakeAuth)
    assert fake._store == "new-user-password-store"
    assert os.environ["EARTHDATA_TOKEN"] == "rejected-token"


def test_delayed_retry_uses_password_auth_before_one_fresh_download(monkeypatch, tmp_path):
    class FakeAuth:
        pass

    class RetryRunnerEarthaccess(FakeEarthaccess):
        Auth = FakeAuth

        def __init__(self):
            super().__init__(results=[_cmr_result()])
            self._auth = object()
            self._store = object()
            self.login_token_modes = []

        def login(self, **kwargs):
            self.login_token_modes.append(bool(os.environ.get("EARTHDATA_TOKEN")))
            self.login_calls.append(kwargs)
            return True

    fake = RetryRunnerEarthaccess()
    monkeypatch.setenv("EARTHDATA_TOKEN", "rejected-token")
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "password-test-value")
    monkeypatch.setenv("RIVERSHIFT_RETRY_ATTEMPT", "1")
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    result = download_product(_catalogue_row(), tmp_path)

    assert result["downloaded"] is True
    assert fake.login_token_modes == [False]
    assert len(fake.download_calls) == 1
    assert os.environ["EARTHDATA_TOKEN"] == "rejected-token"


def test_network_download_failure_does_not_trigger_username_password_fallback(monkeypatch, tmp_path):
    class NetworkFailure(FakeEarthaccess):
        def __init__(self):
            super().__init__(results=[_cmr_result()])
            self._auth = object()
            self._store = object()
            self.download_count = 0

        def login(self, **kwargs):
            return True

        def download(self, granules, *, local_path, threads, show_progress):
            self.download_count += 1
            raise RuntimeError("network connection timed out")

    fake = NetworkFailure()
    monkeypatch.setenv("EARTHDATA_TOKEN", "token")
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "password-test-value")
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    with pytest.raises(RuntimeError, match="no immediate re-download was performed"):
        download_product(_catalogue_row(), tmp_path)

    assert fake.download_count == 1

def test_authenticated_range_download_uses_parallel_parts_and_verifies_final_hdf5(monkeypatch, tmp_path):
    fake = RangedFakeEarthaccess()
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)
    monkeypatch.setattr(download_module, "RANGE_PART_BYTES", 8)
    monkeypatch.setattr(download_module, "RANGE_DOWNLOAD_WORKERS", 2)

    result = download_product(_exact_range_catalogue_row(), tmp_path)

    expected = fake.payload
    product_path = tmp_path / f"{GRANULE}.h5"
    assert product_path.read_bytes() == expected
    assert is_hdf5_file(product_path)
    assert result["download_method"] == "earthaccess_authenticated_http_range"
    assert result["size_bytes"] == len(expected)
    assert result["sha256"] == hashlib.sha256(expected).hexdigest()
    assert fake.download_calls == []
    assert (0, 0) in fake.range_calls
    assert (0, 7) in fake.range_calls
    assert (8, 15) in fake.range_calls
    receipt = json.loads((tmp_path / f"{GRANULE}.download.json").read_text())
    assert receipt["download_method"] == "earthaccess_authenticated_http_range"
    assert receipt["sha256"] == result["sha256"]


def test_authenticated_range_download_retries_only_the_failed_byte_range(monkeypatch, tmp_path):
    fake = RangedFakeEarthaccess(fail_once_for=(0, 7))
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)
    monkeypatch.setattr(download_module, "RANGE_PART_BYTES", 8)
    monkeypatch.setattr(download_module.time, "sleep", lambda *_args: None)

    result = download_product(_exact_range_catalogue_row(), tmp_path)

    assert result["downloaded"] is True
    assert fake.range_counts[(0, 0)] == 1
    assert fake.range_counts[(0, 7)] == 2
    assert fake.range_counts[(8, 15)] == 1
    assert fake.download_calls == []


def test_unsupported_http_range_falls_back_to_earthaccess_download(monkeypatch, tmp_path):
    fake = RangedFakeEarthaccess(range_supported=False)
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)

    result = download_product(_exact_range_catalogue_row(), tmp_path)

    assert result["download_method"] == "earthaccess.download"
    assert fake.download_calls and len(fake.download_calls) == 1
    assert (tmp_path / f"{GRANULE}.h5").read_bytes() == fake.payload


def test_transient_earthdata_login_connection_error_is_retried_once(monkeypatch, tmp_path):
    class FlakyLogin(FakeEarthaccess):
        def login(self, **kwargs):
            self.login_calls.append(kwargs)
            if len(self.login_calls) == 1:
                raise requests.exceptions.ConnectionError("temporary EDL handshake failure")
            return True

    fake = FlakyLogin(results=[_cmr_result()])
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)
    monkeypatch.setattr(download_module.time, "sleep", lambda *_args: None)

    result = download_product(_catalogue_row(), tmp_path)

    assert result["downloaded"] is True
    assert fake.login_calls == [{"strategy": "environment"}, {"strategy": "environment"}]


def test_http_range_response_with_wrong_content_range_is_rejected(monkeypatch, tmp_path):
    class CorruptRangeSession(FakeRangeSession):
        def get(self, url, *, headers, stream, allow_redirects, timeout):
            response = super().get(
                url,
                headers=headers,
                stream=stream,
                allow_redirects=allow_redirects,
                timeout=timeout,
            )
            if headers["Range"] == "bytes=0-7" and response.status_code == 206:
                response.headers["Content-Range"] = "bytes 0-6/999"
            return response

    class CorruptRangeEarthaccess(RangedFakeEarthaccess):
        def get_requests_https_session(self):
            return CorruptRangeSession(self)

    fake = CorruptRangeEarthaccess()
    monkeypatch.setattr("download_gcov_product._load_earthaccess", lambda: fake)
    monkeypatch.setattr(download_module, "RANGE_PART_BYTES", 8)

    with pytest.raises(RuntimeError, match="inconsistent Content-Range"):
        download_product(_exact_range_catalogue_row(), tmp_path)

    assert not (tmp_path / f"{GRANULE}.h5").exists()
    assert not (tmp_path / f"{GRANULE}.download.json").exists()
    assert not list(tmp_path.glob(".*.earthaccess-download"))

