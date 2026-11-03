from __future__ import annotations

import hashlib
import json

import pytest
import requests

from drive_upload_adapter import (
    DRIVE_API,
    DriveClient,
    DriveUploadError,
    _md5_file,
    _parse_oauth_client,
    _parse_refresh_token,
    _run_drive_stage,
    load_drive_config,
)


def test_drive_md5_checksum_streams_file_and_matches_google_drive_checksum(tmp_path, monkeypatch):
    path = tmp_path / "large-result.tif"
    payload = (b"RiverShift artifact bytes\x00" * 500_000)
    path.write_bytes(payload)

    def reject_read_bytes(_self):
        raise AssertionError("large artifact verification must not read the whole file into memory")

    monkeypatch.setattr(type(path), "read_bytes", reject_read_bytes)

    assert _md5_file(path) == hashlib.md5(payload).hexdigest()


class FakeResponse:
    def __init__(self, status_code, *, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload or {}
        self.content = b"{}"
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *, request_response, put_responses):
        self.request_response = request_response
        self.put_responses = list(put_responses)
        self.request_calls = []
        self.put_calls = []

    def request(self, method, url, **kwargs):
        self.request_calls.append((method, url, kwargs))
        return self.request_response

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        result = self.put_responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _drive_for_upload(session):
    drive = DriveClient.__new__(DriveClient)
    drive.session = session
    drive.access_token = "test-access-token"
    return drive


def test_resumable_upload_respects_partial_308_acknowledgement(monkeypatch, tmp_path):
    monkeypatch.setattr("drive_upload_adapter.RESUMABLE_CHUNK_BYTES", 8)
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"abcdefgh")
    final = {"id": "drive-file-1", "name": path.name, "size": "8", "md5Checksum": hashlib.md5(b"abcdefgh").hexdigest()}
    session = FakeSession(
        request_response=FakeResponse(200, headers={"Location": "https://www.googleapis.com/upload/session"}),
        put_responses=[
            FakeResponse(308, headers={"Range": "bytes=0-3"}),
            FakeResponse(201, payload=final),
        ],
    )

    result = _drive_for_upload(session)._upload_resumable(path, {"name": path.name}, "POST", "https://www.googleapis.com/upload/drive/v3/files")

    assert result["id"] == "drive-file-1"
    assert session.put_calls[0][1]["headers"]["Content-Range"] == "bytes 0-7/8"
    assert session.put_calls[1][1]["headers"]["Content-Range"] == "bytes 4-7/8"
    assert session.put_calls[1][1]["data"] == b"efgh"


def test_resumable_upload_queries_server_offset_after_ambiguous_network_error(monkeypatch, tmp_path):
    monkeypatch.setattr("drive_upload_adapter.RESUMABLE_CHUNK_BYTES", 8)
    monkeypatch.setattr("drive_upload_adapter.time.sleep", lambda _seconds: None)
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"abcdefgh")
    final = {"id": "drive-file-2", "name": path.name, "size": "8", "md5Checksum": hashlib.md5(b"abcdefgh").hexdigest()}
    session = FakeSession(
        request_response=FakeResponse(200, headers={"Location": "https://upload.googleapis.com/session"}),
        put_responses=[
            requests.ConnectionError("ambiguous network failure"),
            FakeResponse(308, headers={"Range": "bytes=0-3"}),
            FakeResponse(201, payload=final),
        ],
    )

    result = _drive_for_upload(session)._upload_resumable(path, {"name": path.name}, "POST", "https://www.googleapis.com/upload/drive/v3/files")

    assert result["id"] == "drive-file-2"
    assert session.put_calls[0][1]["headers"]["Content-Range"] == "bytes 0-7/8"
    assert session.put_calls[1][1]["headers"]["Content-Range"] == "bytes */8"
    assert session.put_calls[1][1]["data"] == b""
    assert session.put_calls[2][1]["headers"]["Content-Range"] == "bytes 4-7/8"
    assert session.put_calls[2][1]["data"] == b"efgh"


def test_resumable_upload_rejects_untrusted_session_url(tmp_path):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"data")
    session = FakeSession(
        request_response=FakeResponse(200, headers={"Location": "https://attacker.example/upload/session"}),
        put_responses=[],
    )

    with pytest.raises(DriveUploadError, match="untrusted resumable upload URL"):
        _drive_for_upload(session)._upload_resumable(path, {"name": path.name}, "POST", "https://www.googleapis.com/upload/drive/v3/files")



def test_existing_byte_identical_scientific_artifact_is_reused(tmp_path):
    path = tmp_path / "water-mask.tif"
    data = b"immutable scientific raster"
    path.write_bytes(data)
    md5 = hashlib.md5(data).hexdigest()
    drive = DriveClient.__new__(DriveClient)
    drive._find_named_file = lambda *_args: "existing-drive-id"
    drive._json = lambda *_args, **_kwargs: {
        "id": "existing-drive-id", "name": path.name,
        "size": str(len(data)), "md5Checksum": md5,
    }
    drive._upload_multipart = lambda *_args: (_ for _ in ()).throw(AssertionError("identical output must be reused"))
    drive._upload_resumable = drive._upload_multipart

    receipt = drive.upload_file(path, "job-output-folder")

    assert receipt["status"] == "PASS"
    assert receipt["reused"] is True
    assert receipt["drive_file_id"] == "existing-drive-id"


def test_existing_different_scientific_artifact_is_never_overwritten(tmp_path):
    path = tmp_path / "water-mask.tif"
    path.write_bytes(b"new scientific raster")
    drive = DriveClient.__new__(DriveClient)
    drive._find_named_file = lambda *_args: "existing-drive-id"
    drive._json = lambda *_args, **_kwargs: {
        "id": "existing-drive-id", "name": path.name,
        "size": "19", "md5Checksum": hashlib.md5(b"old raster bytes").hexdigest(),
    }
    drive._upload_multipart = lambda *_args: (_ for _ in ()).throw(AssertionError("must not overwrite"))
    drive._upload_resumable = drive._upload_multipart

    with pytest.raises(DriveUploadError, match="immutable overwrite is blocked"):
        drive.upload_file(path, "job-output-folder")


@pytest.mark.parametrize("permission_type", ["anyone", "domain", "group"])
def test_result_folder_rejects_public_or_shared_drive_permissions(permission_type):
    drive = DriveClient.__new__(DriveClient)
    drive._json = lambda *_args, **_kwargs: {
        "permissions": [{"type": "user", "role": "owner"}, {"type": permission_type, "role": "reader"}]
    }

    with pytest.raises(DriveUploadError, match="shared beyond its owner"):
        drive.require_private_folder("parent-folder-id")


def test_result_manifest_is_the_only_artifact_that_can_be_refreshed(tmp_path):
    path = tmp_path / "result-manifest.json"
    data = b'{"storage_verification":{"status":"PASS"}}'
    path.write_bytes(data)
    md5 = hashlib.md5(data).hexdigest()
    drive = DriveClient.__new__(DriveClient)
    drive._find_named_file = lambda *_args: "existing-manifest-id"
    calls = []
    drive._upload_multipart = lambda _path, _metadata, method, _url: (
        calls.append(method) or {"id": "existing-manifest-id"}
    )
    drive._json = lambda *_args, **_kwargs: {
        "id": "existing-manifest-id", "name": path.name,
        "size": str(len(data)), "md5Checksum": md5,
    }

    receipt = drive.upload_file(path, "job-folder")

    assert calls == ["PATCH"]
    assert receipt["status"] == "PASS"
    assert receipt["reused"] is False



@pytest.mark.parametrize(
    ("raw_secret", "expected_token", "expected_format"),
    [
        ("bare-refresh-token", "bare-refresh-token", "bare"),
        ('{"refresh_token":"json-refresh-token","token":"ignored"}', "json-refresh-token", "token_json"),
        ('"quoted-refresh-token"', "quoted-refresh-token", "json_string"),
    ],
)
def test_refresh_token_parser_matches_working_uploader(raw_secret, expected_token, expected_format):
    assert _parse_refresh_token(raw_secret) == (expected_token, expected_format)


@pytest.mark.parametrize(
    ("document", "expected_format"),
    [
        ({"installed": {"client_id": "id", "client_secret": "secret"}}, "installed"),
        ({"web": {"client_id": "id", "client_secret": "secret"}}, "web"),
        ({"client_id": "id", "client_secret": "secret"}, "root"),
    ],
)
def test_oauth_client_parser_accepts_working_uploader_formats(document, expected_format):
    client_id, client_secret, token_uri, credential_format = _parse_oauth_client(json.dumps(document))
    assert (client_id, client_secret) == ("id", "secret")
    assert token_uri == "https://oauth2.googleapis.com/token"
    assert credential_format == expected_format


def test_load_drive_config_accepts_token_json_and_prefers_canonical_parent_folder():
    config = load_drive_config({
        "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({
            "client_id": "client-id",
            "client_secret": "client-secret",
        }),
        "GOOGLE_DRIVE_REFRESH_TOKEN": json.dumps({"refresh_token": "refresh-token"}),
        "GOOGLE_DRIVE_FOLDER_ID": "folder-alias-123",
        "GOOGLE_DRIVE_PARENT_FOLDER_ID": "canonical-parent-123",
    })
    assert config.refresh_token == "refresh-token"
    assert config.parent_folder_id == "canonical-parent-123"


def test_drive_file_list_requests_include_shared_drive_compatibility_flags():
    session = FakeSession(
        request_response=FakeResponse(200, payload={"files": []}),
        put_responses=[],
    )
    drive = _drive_for_upload(session)

    drive._json("GET", f"{DRIVE_API}/files", params={"q": "trashed = false"})

    params = session.request_calls[0][2]["params"]
    assert params["supportsAllDrives"] == "true"
    assert params["includeItemsFromAllDrives"] == "true"
    assert params["spaces"] == "drive"


def test_authenticated_account_verification_requires_established_storage_account():
    drive = DriveClient.__new__(DriveClient)
    drive._json = lambda *_args, **_kwargs: {"user": {"emailAddress": "sarguardian.org@gmail.com"}}
    drive.verify_authenticated_account()

    drive._json = lambda *_args, **_kwargs: {"user": {"emailAddress": "other@example.com"}}
    with pytest.raises(DriveUploadError, match="account does not match"):
        drive.verify_authenticated_account()


def test_parent_folder_verification_requires_an_accessible_folder():
    drive = DriveClient.__new__(DriveClient)
    drive._json = lambda *_args, **_kwargs: {
        "id": "parent-folder-123",
        "mimeType": "application/vnd.google-apps.folder",
    }
    drive.verify_parent_folder("parent-folder-123")

    drive._json = lambda *_args, **_kwargs: {"id": "parent-folder-123", "mimeType": "text/plain"}
    with pytest.raises(DriveUploadError, match="not an accessible folder"):
        drive.verify_parent_folder("parent-folder-123")


def test_drive_stage_logger_emits_pass_and_failure_without_suppressing_errors(capsys):
    assert _run_drive_stage("test_stage", lambda: "ok", safe_detail="present") == "ok"
    with pytest.raises(RuntimeError, match="expected safe error"):
        _run_drive_stage("failing_stage", lambda: (_ for _ in ()).throw(RuntimeError("expected safe error")))
    output = capsys.readouterr().out
    assert '"stage": "test_stage"' in output
    assert '"status": "PASS"' in output
    assert '"stage": "failing_stage"' in output
    assert '"status": "FAIL"' in output
    assert '"error": "expected safe error"' in output
