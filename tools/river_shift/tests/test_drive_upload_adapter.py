from __future__ import annotations

import hashlib

import pytest
import requests

from drive_upload_adapter import DriveClient, DriveUploadError, _md5_file


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


