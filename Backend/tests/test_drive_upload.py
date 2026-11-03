from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from science_adapter import upload_to_drive as drive


class Response:
    def __init__(self, payload: dict):
        self.payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class DriveSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.next_id = 0
        self.files: dict[str, tuple[str, bytes]] = {}

    def post(self, _url, **_kwargs):
        return Response({"access_token": "access-token"})

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if method == "GET" and url.endswith("/files"):
            return Response({"files": []})
        if method == "GET" and url.endswith("/permissions"):
            return Response({"permissions": []})
        if method == "POST" and url == f"{drive.DRIVE_API}/files":
            self.next_id += 1
            return Response({"id": f"folder-{self.next_id}"})
        if method in {"POST", "PATCH"} and url.startswith(f"{drive.DRIVE_UPLOAD_API}/files"):
            self.next_id += 1
            identifier = f"file-{self.next_id}"
            upload = kwargs["files"]["file"]
            self.files[identifier] = (upload[0], upload[1].read())
            return Response({"id": identifier})
        if method == "GET" and "/files/file-" in url:
            identifier = url.rsplit("/", 1)[-1]
            name, content = self.files[identifier]
            return Response({"id": identifier, "name": name, "size": str(len(content)), "md5Checksum": hashlib.md5(content).hexdigest()})
        raise AssertionError(f"Unexpected Drive request: {method} {url}")


def write_validated_manifest(work_dir: Path) -> None:
    output = work_dir / "outputs" / "granule-one" / "screening.tif"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"validated-geotiff")
    (work_dir / "result-manifest.json").write_text(json.dumps({
        "status": "succeeded",
        "job_id": "123e4567-e89b-12d3-a456-426614174000",
        "validated_outputs": [{
            "path": "outputs/granule-one/screening.tif",
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }],
    }), encoding="utf-8")


def test_uploads_only_manifest_and_checksum_verified_outputs_to_a_private_job_folder(tmp_path: Path) -> None:
    write_validated_manifest(tmp_path)
    session = DriveSession()
    config = drive.DriveConfig("client", "secret", "https://oauth2.googleapis.com/token", "refresh", "13BIAepPGLlYYmscUlNPeMCdtepYshjT4")

    receipt = drive.upload_validated_results(tmp_path, config=config, session=session)

    assert receipt["status"] == "PASS"
    uploaded = [item for item in session.requests if item[1].startswith(f"{drive.DRIVE_UPLOAD_API}/files")]
    assert len(uploaded) >= 3  # manifest is refreshed after verified inventory is written
    assert not any("/permissions" in item[1] and item[0] == "POST" for item in session.requests)


def test_rejects_tampered_validated_outputs_before_google_drive_is_contacted(tmp_path: Path) -> None:
    write_validated_manifest(tmp_path)
    (tmp_path / "outputs" / "granule-one" / "screening.tif").write_bytes(b"tampered")

    with pytest.raises(drive.DriveUploadError, match="checksum"):
        drive.upload_validated_results(tmp_path, config=drive.DriveConfig("client", "secret", "https://oauth2.googleapis.com/token", "refresh", "13BIAepPGLlYYmscUlNPeMCdtepYshjT4"))


def test_accepts_installed_google_oauth_configuration() -> None:
    config = drive.load_drive_config({
        "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({"installed": {
            "client_id": "client",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}),
        "GOOGLE_DRIVE_REFRESH_TOKEN": "refresh",
        "GOOGLE_DRIVE_FOLDER_ID": "13BIAepPGLlYYmscUlNPeMCdtepYshjT4",
    })

    assert config.client_id == "client"
    assert config.client_secret == "secret"
    assert config.token_uri == "https://oauth2.googleapis.com/token"
    assert config.refresh_token == "refresh"
    assert config.parent_folder_id == "13BIAepPGLlYYmscUlNPeMCdtepYshjT4"



def test_accepts_parent_folder_environment_name_used_by_github_actions() -> None:
    config = drive.load_drive_config({
        "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({"web": {
            "client_id": "client",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}),
        "GOOGLE_DRIVE_REFRESH_TOKEN": "refresh",
        "GOOGLE_DRIVE_PARENT_FOLDER_ID": "13BIAepPGLlYYmscUlNPeMCdtepYshjT4",
    })

    assert config.parent_folder_id == "13BIAepPGLlYYmscUlNPeMCdtepYshjT4"


def test_prefers_parent_folder_id_when_both_drive_folder_names_are_present() -> None:
    config = drive.load_drive_config({
        "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({"web": {
            "client_id": "client",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}),
        "GOOGLE_DRIVE_REFRESH_TOKEN": "refresh",
        "GOOGLE_DRIVE_FOLDER_ID": "13BIAepPGLlYYmscUlNPeMCdtepYshjT4",
        "GOOGLE_DRIVE_PARENT_FOLDER_ID": "14BIAepPGLlYYmscUlNPeMCdtepYshjT4",
    })

    assert config.parent_folder_id == "14BIAepPGLlYYmscUlNPeMCdtepYshjT4"


def test_upload_configuration_still_requires_the_parent_folder_id() -> None:
    with pytest.raises(drive.DriveUploadError, match="GOOGLE_DRIVE_PARENT_FOLDER_ID"):
        drive.load_drive_config({
            "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({"web": {
                "client_id": "client",
                "client_secret": "secret",
                "token_uri": "https://oauth2.googleapis.com/token",
            }}),
            "GOOGLE_DRIVE_REFRESH_TOKEN": "refresh",
        })


def test_rejects_incomplete_or_untrusted_google_oauth_configuration() -> None:
    with pytest.raises(drive.DriveUploadError, match="incomplete"):
        drive.load_drive_config({
            "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({"installed": {}}),
            "GOOGLE_DRIVE_REFRESH_TOKEN": "refresh",
            "GOOGLE_DRIVE_FOLDER_ID": "13BIAepPGLlYYmscUlNPeMCdtepYshjT4",
        })
    with pytest.raises(drive.DriveUploadError, match="unsupported token endpoint"):
        drive.load_drive_config({
            "GOOGLE_DRIVE_OAUTH_CLIENT_JSON": json.dumps({"web": {
                "client_id": "client", "client_secret": "secret", "token_uri": "https://invalid.example/token",
            }}),
            "GOOGLE_DRIVE_REFRESH_TOKEN": "refresh",
            "GOOGLE_DRIVE_FOLDER_ID": "13BIAepPGLlYYmscUlNPeMCdtepYshjT4",
        })


class StreamingResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.was_closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        step = min(chunk_size, 7)
        for start in range(0, len(self.payload), step):
            yield self.payload[start:start + step]

    def close(self) -> None:
        self.was_closed = True


class StreamingDriveSession(DriveSession):
    def __init__(self, payload: bytes):
        super().__init__()
        self.response = StreamingResponse(payload)
        self.download_kwargs = None

    def get(self, _url, **kwargs):
        self.download_kwargs = kwargs
        return self.response


def test_streams_private_drive_file_to_disk_and_verifies_hash(tmp_path: Path) -> None:
    payload = b"large-private-result-bundle" * 1000
    session = StreamingDriveSession(payload)
    destination = tmp_path / "dashboard.zip"
    config = drive.DriveConfig("client", "secret", "https://oauth2.googleapis.com/token", "refresh", "13BIAepPGLlYYmscUlNPeMCdtepYshjT4")

    receipt = drive.DriveClient(config=config, session=session).download_file_to_path(
        "private-file-123456",
        destination,
        max_bytes=len(payload),
    )

    assert destination.read_bytes() == payload
    assert receipt == {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    assert session.download_kwargs["stream"] is True
    assert session.download_kwargs["timeout"] == 300
    assert session.response.was_closed is True


def test_streaming_private_drive_download_enforces_inventory_size_and_removes_partial_file(tmp_path: Path) -> None:
    payload = b"larger-than-inventory"
    session = StreamingDriveSession(payload)
    destination = tmp_path / "dashboard.zip"
    config = drive.DriveConfig("client", "secret", "https://oauth2.googleapis.com/token", "refresh", "13BIAepPGLlYYmscUlNPeMCdtepYshjT4")

    with pytest.raises(drive.DriveUploadError, match="verified size limit"):
        drive.DriveClient(config=config, session=session).download_file_to_path(
            "private-file-123456",
            destination,
            max_bytes=4,
        )

    assert not destination.exists()
    assert session.response.was_closed is True



def test_private_artifact_download_does_not_require_a_parent_folder_environment(
    monkeypatch, tmp_path: Path,
) -> None:
    payload = b"private-river-shift-preview" * 100
    monkeypatch.setenv("GOOGLE_DRIVE_OAUTH_CLIENT_JSON", json.dumps({"web": {
        "client_id": "client",
        "client_secret": "secret",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}))
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "refresh")
    monkeypatch.delenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)

    session = StreamingDriveSession(payload)
    destination = tmp_path / "private-preview.geojson"
    receipt = drive.download_private_result_to_path(
        "private-file-123456",
        destination,
        session=session,
        max_bytes=len(payload),
    )

    assert destination.read_bytes() == payload
    assert receipt == {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    assert session.response.was_closed is True
