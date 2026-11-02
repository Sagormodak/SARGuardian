from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile
import sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest

import app.storage.drive_client as drive_client_module

from app.storage.drive_client import DriveClient, DriveClientError
import tools.know_place.upload_bundle_to_drive as uploader


def make_run(root: Path) -> Path:
    run_dir = root / "20261024T000000Z_abcd1234"
    (run_dir / "visuals").mkdir(parents=True)
    (run_dir / "maps").mkdir()
    (run_dir / "result.json").write_text('{"status":"SCIENTIFIC_METRICS_COMPUTED"}\n', encoding="utf-8")
    (run_dir / "manifest.json").write_text('{"raw_h5_included":false}\n', encoding="utf-8")
    (run_dir / "timeseries.csv").write_text("reference_date,secondary_date\n2026-07-26,2026-08-19\n", encoding="utf-8")
    (run_dir / "visuals" / "dashboard.html").write_text("<html><body>preview</body></html>", encoding="utf-8")
    (run_dir / "maps" / "preview.tif").write_bytes(b"not-a-real-tiff-for-bundle-unit-test")
    return run_dir


def test_derived_bundle_contains_all_run_outputs_and_hashes(tmp_path):
    run_dir = make_run(tmp_path)
    archive = tmp_path / "run.zip"

    result = uploader.create_derived_bundle(run_dir, archive)

    assert result["raw_h5_included"] is False
    assert "parent" in client.listed_parents
    assert result["archive_bytes"] == archive.stat().st_size
    assert result["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
    assert "result.json" in names
    assert "manifest.json" in names
    assert "visuals/dashboard.html" in names
    assert "maps/preview.tif" in names


def test_derived_bundle_rejects_any_raw_hdf5_file(tmp_path):
    run_dir = make_run(tmp_path)
    (run_dir / "secret-source.h5").write_bytes(b"must-not-upload")

    with pytest.raises(uploader.BundleUploadError, match="RAW_HDF5_MUST_NOT_BE_INCLUDED_IN_DERIVED_BUNDLE"):
        uploader.create_derived_bundle(run_dir, tmp_path / "run.zip")


def test_drive_bundle_upload_checks_identity_and_downloaded_bytes(tmp_path, monkeypatch):
    class FakeDrive:
        def __init__(self):
            self.children = {"parent": []}
            self.data = {}
            self.next_id = 0

        @classmethod
        def from_environment(cls):
            return client

        def refresh_access_token(self):
            return 200

        def about_email(self):
            return 200, uploader.EXPECTED_ACCOUNT

        def get_file(self, file_id):
            raise AssertionError("Known Place uploader must not require files.get(parent_id)")

        def list_children(self, parent_id):
            self.listed_parents = getattr(self, "listed_parents", [])
            self.listed_parents.append(parent_id)
            return list(self.children.get(parent_id, []))

        def create_folder(self, parent_id, name):
            self.next_id += 1
            folder_id = f"folder-{self.next_id}"
            self.children[folder_id] = []
            self.children[parent_id].append({
                "id": folder_id, "name": name, "mimeType": uploader.DRIVE_FOLDER_MIME,
            })
            return folder_id

        def upload_file(self, parent_id, path, mime_type):
            assert mime_type == "application/zip"
            self.next_id += 1
            file_id = f"file-{self.next_id}"
            self.data[file_id] = Path(path).read_bytes()
            self.children[parent_id].append({
                "id": file_id, "name": Path(path).name, "mimeType": mime_type,
            })
            return file_id

        def download_file(self, file_id):
            return self.data[file_id]

    client = FakeDrive()
    monkeypatch.setenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", "parent")
    monkeypatch.setattr(uploader, "DriveClient", FakeDrive)

    run_dir = make_run(tmp_path)
    archive = tmp_path / "bundle.zip"
    uploader.create_derived_bundle(run_dir, archive)

    result = uploader.upload_and_verify(archive, folder_name="know-place-test-run")

    assert result["status"] == "PASS"
    assert result["action"] == "UPLOADED"
    assert result["remote_bytes_verified"] is True
    assert result["bundle_sha256_local"] == result["bundle_sha256_downloaded_from_drive"]
    assert result["raw_h5_included"] is False


def test_drive_upload_fails_closed_for_wrong_storage_identity(tmp_path, monkeypatch):
    class WrongIdentityDrive:
        @classmethod
        def from_environment(cls):
            return cls()

        def refresh_access_token(self):
            return 200

        def about_email(self):
            return 200, "unintended-user@example.com"

    monkeypatch.setattr(uploader, "DriveClient", WrongIdentityDrive)
    with pytest.raises(uploader.BundleUploadError, match="DRIVE_STORAGE_ACCOUNT_IDENTITY_MISMATCH"):
        uploader.upload_and_verify(tmp_path / "unused.zip", folder_name="know-place-test-run")

@pytest.mark.parametrize(
    "refresh_secret, expected",
    [
        ("plain-refresh-token", "plain-refresh-token"),
        (json.dumps("quoted-refresh-token"), "quoted-refresh-token"),
        (json.dumps({"refresh_token": "object-refresh-token"}), "object-refresh-token"),
    ],
)
def test_drive_client_accepts_supported_refresh_token_secret_formats(
    monkeypatch, refresh_secret, expected
):
    monkeypatch.setenv(
        "GOOGLE_DRIVE_OAUTH_CLIENT_JSON",
        json.dumps({
            "installed": {
                "client_id": "test-client-id",
                "client_secret": "test-client-secret",
            }
        }),
    )
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", refresh_secret)

    client = DriveClient.from_environment()

    assert client.client_id == "test-client-id"
    assert client.client_secret == "test-client-secret"
    assert client.refresh_token == expected


def test_drive_client_rejects_malformed_oauth_client_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_OAUTH_CLIENT_JSON", "{not-json")
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "plain-refresh-token")

    with pytest.raises(DriveClientError, match="DRIVE_CONFIGURATION_INVALID"):
        DriveClient.from_environment()



def _drive_query(request):
    return parse_qs(urlparse(request.full_url).query)


def test_drive_get_file_enables_shared_drive_lookup(monkeypatch):
    client = DriveClient("client-id", "client-secret", "refresh-token")
    client.access_token = "access-token"
    captured = {}

    def fake_request(request, error_code, retries=0):
        captured["request"] = request
        return {"id": "parent", "mimeType": uploader.DRIVE_FOLDER_MIME, "driveId": "shared-drive"}

    monkeypatch.setattr(client, "_request_json", fake_request)

    result = client.get_file("parent")

    query = _drive_query(captured["request"])
    assert result["driveId"] == "shared-drive"
    assert query["supportsAllDrives"] == ["true"]
    assert query["fields"] == ["id,name,mimeType,parents,driveId"]


def test_drive_list_children_includes_shared_drives_and_all_pages(monkeypatch):
    client = DriveClient("client-id", "client-secret", "refresh-token")
    client.access_token = "access-token"
    responses = [
        {"files": [{"id": "first", "name": "one"}], "nextPageToken": "next-page"},
        {"files": [{"id": "second", "name": "two"}]},
    ]
    requests = []

    def fake_request(request, error_code, retries=0):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr(client, "_request_json", fake_request)

    files = client.list_children("shared-folder")

    assert [entry["id"] for entry in files] == ["first", "second"]
    assert len(requests) == 2
    first_query = _drive_query(requests[0])
    second_query = _drive_query(requests[1])
    for query in (first_query, second_query):
        assert query["supportsAllDrives"] == ["true"]
        assert query["includeItemsFromAllDrives"] == ["true"]
        assert query["corpora"] == ["user"]
        assert query["pageSize"] == ["1000"]
    assert second_query["pageToken"] == ["next-page"]


def test_drive_list_children_fails_closed_on_incomplete_search(monkeypatch):
    client = DriveClient("client-id", "client-secret", "refresh-token")
    client.access_token = "access-token"
    monkeypatch.setattr(
        client,
        "_request_json",
        lambda request, error_code, retries=0: {"files": [], "incompleteSearch": True},
    )

    with pytest.raises(DriveClientError, match="DRIVE_LIST_INCOMPLETE"):
        client.list_children("shared-folder")


def test_drive_download_file_enables_shared_drive_access(monkeypatch):
    client = DriveClient("client-id", "client-secret", "refresh-token")
    client.access_token = "access-token"
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b"verified-derived-bundle"

    def fake_urlopen(request, timeout=60):
        captured["request"] = request
        return FakeResponse()

    monkeypatch.setattr(drive_client_module, "urlopen", fake_urlopen)

    assert client.download_file("shared-drive-file") == b"verified-derived-bundle"
    assert _drive_query(captured["request"])["supportsAllDrives"] == ["true"]


def test_bundle_uploader_logs_safe_drive_http_status(tmp_path, monkeypatch, capsys):
    run_dir = make_run(tmp_path)

    def fail_upload(*args, **kwargs):
        raise DriveClientError("DRIVE_FILE_LOOKUP_FAILED", 404)

    monkeypatch.setattr(uploader, "upload_and_verify", fail_upload)
    monkeypatch.setattr(
        sys,
        "argv",
        ["upload_bundle_to_drive", "--run-root", str(tmp_path), "--folder-name", "known-place-test"],
    )

    assert uploader.main() == 2
    output = capsys.readouterr().out
    assert "ERROR=DRIVE_PARENT_FOLDER_NOT_FOUND_OR_NOT_ACCESSIBLE" in output
    assert "ACTION=CHECK_GOOGLE_DRIVE_PARENT_FOLDER_ID_AND_GRANT_ACCESS_TO_EXPECTED_STORAGE_ACCOUNT" in output
    assert "DRIVE_HTTP_STATUS=404" in output



def test_drive_client_preserves_safe_google_api_error_reason(monkeypatch):
    client = DriveClient("client-id", "client-secret", "refresh-token")
    request = Request("https://www.googleapis.com/drive/v3/files/missing-folder")

    def fake_urlopen(*args, **kwargs):
        body = json.dumps({
            "error": {
                "code": 404,
                "message": "File not found: secret-resource-id",
                "errors": [{"reason": "notFound", "message": "File not found: secret-resource-id"}],
            }
        }).encode("utf-8")
        raise HTTPError(request.full_url, 404, "Not Found", hdrs={}, fp=io.BytesIO(body))

    monkeypatch.setattr(drive_client_module, "urlopen", fake_urlopen)

    with pytest.raises(DriveClientError) as captured:
        client._request_json(request, "DRIVE_FILE_LOOKUP_FAILED")

    assert captured.value.status == 404
    assert captured.value.api_reason == "notFound"
    assert "secret-resource-id" not in str(captured.value)



@pytest.mark.parametrize(
    "configured_value, expected",
    [
        ("folder_ID-123", "folder_ID-123"),
        ("https://drive.google.com/drive/folders/folder_ID-123?usp=sharing", "folder_ID-123"),
        ("https://drive.google.com/open?id=folder_ID-123", "folder_ID-123"),
    ],
)
def test_drive_parent_folder_id_accepts_raw_id_and_standard_drive_urls(configured_value, expected):
    assert uploader.normalize_drive_folder_id(configured_value) == expected


@pytest.mark.parametrize(
    "configured_value, expected_error",
    [
        ("", "DRIVE_PARENT_FOLDER_ID_REQUIRED"),
        ("https://attacker.example/folders/folder_ID-123", "DRIVE_PARENT_FOLDER_URL_HOST_INVALID"),
        ("https://drive.google.com/drive/my-drive", "DRIVE_PARENT_FOLDER_ID_FORMAT_INVALID"),
        ("folder/id", "DRIVE_PARENT_FOLDER_ID_FORMAT_INVALID"),
    ],
)
def test_drive_parent_folder_id_rejects_invalid_values(configured_value, expected_error):
    with pytest.raises(uploader.BundleUploadError, match=expected_error):
        uploader.normalize_drive_folder_id(configured_value)

