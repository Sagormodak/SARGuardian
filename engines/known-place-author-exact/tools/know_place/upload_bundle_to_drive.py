"""Create and verify a derived-only Know Place result bundle in central Google Drive.

Raw HDF5 inputs and credentials are never placed inside the bundle. Drive upload
is intentionally separate from analysis status, so a storage failure cannot be
misreported as a science-processing failure or vice versa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile
from typing import Any

from app.storage.drive_client import DRIVE_FOLDER_MIME, DriveClient, DriveClientError

EXPECTED_ACCOUNT = "sarguardian.org@gmail.com"


class BundleUploadError(RuntimeError):
    """Safe bundle or Drive receipt failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def locate_one_run(run_root: Path) -> Path:
    root = run_root.expanduser().resolve()
    candidates = sorted(
        directory for directory in root.iterdir()
        if directory.is_dir() and (directory / "manifest.json").is_file()
        and (directory / "result.json").is_file()
    )
    if len(candidates) != 1:
        raise BundleUploadError("EXPECTED_EXACTLY_ONE_COMPLETED_RUN_DIRECTORY")
    return candidates[0]


def create_derived_bundle(run_dir: Path, archive_path: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    files = sorted(path for path in run_dir.rglob("*") if path.is_file())
    if not files:
        raise BundleUploadError("RUN_OUTPUT_DIRECTORY_EMPTY")
    forbidden = [
        str(path.relative_to(run_dir))
        for path in files
        if path.suffix.lower() in {".h5", ".hdf5"}
    ]
    if forbidden:
        raise BundleUploadError("RAW_HDF5_MUST_NOT_BE_INCLUDED_IN_DERIVED_BUNDLE")
    if not (run_dir / "result.json").is_file() or not (run_dir / "manifest.json").is_file():
        raise BundleUploadError("RESULT_OR_MANIFEST_MISSING")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, arcname=str(path.relative_to(run_dir)).replace("\\", "/"))
    return {
        "archive_path": str(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "bundled_file_count": len(files),
        "raw_h5_included": False,
    }


def upload_and_verify(archive_path: Path, *, folder_name: str) -> dict[str, Any]:
    client = DriveClient.from_environment()
    client.refresh_access_token()
    _, email = client.about_email()
    if not isinstance(email, str) or email.lower() != EXPECTED_ACCOUNT.lower():
        raise BundleUploadError("DRIVE_STORAGE_ACCOUNT_IDENTITY_MISMATCH")

    parent_id = os.environ.get("GOOGLE_DRIVE_PARENT_FOLDER_ID", "").strip()
    if not parent_id:
        raise BundleUploadError("DRIVE_PARENT_FOLDER_ID_REQUIRED")
    parent = client.get_file(parent_id)
    if parent.get("mimeType") != DRIVE_FOLDER_MIME:
        raise BundleUploadError("DRIVE_PARENT_FOLDER_IS_NOT_A_FOLDER")

    matches = [entry for entry in client.list_children(parent_id) if entry.get("name") == folder_name]
    if any(entry.get("mimeType") != DRIVE_FOLDER_MIME for entry in matches):
        raise BundleUploadError("DRIVE_BUNDLE_ENTRY_NAME_CONFLICT")
    if len(matches) > 1:
        raise BundleUploadError("DRIVE_DUPLICATE_BUNDLE_FOLDERS")
    folder_id = matches[0]["id"] if matches else client.create_folder(parent_id, folder_name)

    existing = [entry for entry in client.list_children(folder_id) if entry.get("name") == archive_path.name]
    if len(existing) > 1:
        raise BundleUploadError("DRIVE_DUPLICATE_BUNDLE_FILES")
    expected_sha = sha256_file(archive_path)
    if existing:
        file_id = existing[0].get("id")
        if not isinstance(file_id, str):
            raise BundleUploadError("DRIVE_EXISTING_BUNDLE_ID_MISSING")
        downloaded = client.download_file(file_id)
        actual_sha = hashlib.sha256(downloaded).hexdigest()
        if actual_sha != expected_sha:
            raise BundleUploadError("DRIVE_EXISTING_BUNDLE_CHECKSUM_CONFLICT")
        action = "REUSED_AND_VERIFIED"
    else:
        file_id = client.upload_file(folder_id, archive_path, "application/zip")
        action = "UPLOADED"
        # Verify remote bytes, not just the metadata returned by the upload API.
        downloaded = client.download_file(file_id)
        actual_sha = hashlib.sha256(downloaded).hexdigest()
        if actual_sha != expected_sha:
            raise BundleUploadError("DRIVE_UPLOADED_BUNDLE_CHECKSUM_MISMATCH")

    children = client.list_children(folder_id)
    matching = [
        entry for entry in children
        if entry.get("name") == archive_path.name and entry.get("id") == file_id
    ]
    if len(matching) != 1:
        raise BundleUploadError("DRIVE_BUNDLE_POST_UPLOAD_LIST_VERIFICATION_FAILED")

    return {
        "schema_version": "know-place-drive-upload-receipt/1.0",
        "status": "PASS",
        "action": action,
        "account_email": email,
        "parent_folder_id": parent_id,
        "bundle_folder_id": folder_id,
        "bundle_file_id": file_id,
        "bundle_file_name": archive_path.name,
        "bundle_bytes": archive_path.stat().st_size,
        "bundle_sha256_local": expected_sha,
        "bundle_sha256_downloaded_from_drive": actual_sha,
        "remote_bytes_verified": expected_sha == actual_sha,
        "raw_h5_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a derived-only Know Place bundle to central Google Drive.")
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--folder-name", required=True)
    args = parser.parse_args()
    if not args.folder_name or any(char in args.folder_name for char in "/\\"):
        raise SystemExit("ERROR=DRIVE_FOLDER_NAME_INVALID")

    try:
        run_dir = locate_one_run(args.run_root)
        archive = args.run_root.expanduser().resolve() / f"{args.folder_name}.zip"
        bundle = create_derived_bundle(run_dir, archive)
        receipt = upload_and_verify(archive, folder_name=args.folder_name)
        receipt.update({
            "run_directory_name": run_dir.name,
            "source_manifest_sha256": sha256_file(run_dir / "manifest.json"),
            "bundle": bundle,
        })
        receipt_path = args.run_root.expanduser().resolve() / f"{args.folder_name}.drive-upload-receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, DriveClientError, BundleUploadError) as exc:
        print(f"DRIVE_BUNDLE_UPLOAD_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:{str(exc).split(':', 1)[0][:120]}")
        return 2

    print("DRIVE_BUNDLE_UPLOAD_STATUS=PASS")
    print(f"BUNDLE_SHA256={receipt['bundle_sha256_local']}")
    print(f"REMOTE_BYTES_VERIFIED={str(receipt['remote_bytes_verified']).lower()}")
    print(f"RECEIPT={receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
