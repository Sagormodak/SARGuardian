from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

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
            assert file_id == "parent"
            return {"id": "parent", "mimeType": uploader.DRIVE_FOLDER_MIME}

        def list_children(self, parent_id):
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

