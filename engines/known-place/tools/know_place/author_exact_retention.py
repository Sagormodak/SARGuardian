"""Verified, auditable cleanup of temporary exact-author GOFF source bytes.

The pre-cleanup Google Drive upload receipt is not evidence that runner-local raw
files were subsequently deleted. This module verifies the five raw files against
the source manifest, requires remote verification of the derived-only bundle and
its receipt, deletes only the five hash-pinned HDF5 files, then emits a separate
post-cleanup receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

EXPECTED_SOURCE_STATUS = "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED"
EXPECTED_SOURCE_COUNT = 5
EXPECTED_WIDTH = 4311
EXPECTED_HEIGHT = 4230
EXPECTED_EPSG = 32645
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RawCleanupError(RuntimeError):
    """Raised when safe, evidence-backed raw source cleanup cannot proceed."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RawCleanupError(f"JSON_ROOT_NOT_OBJECT:{path.name}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _verified_drive_bundle(receipt: dict[str, Any], *, expected_name: str) -> dict[str, Any]:
    if receipt.get("remote_verification") != "PASS":
        raise RawCleanupError("DRIVE_REMOTE_VERIFICATION_NOT_PASS")
    if receipt.get("raw_product_uploaded") is not False:
        raise RawCleanupError("RAW_HDF5_MUST_NOT_BE_UPLOADED")
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise RawCleanupError("DRIVE_RECEIPT_FILE_LIST_MISSING")
    matches = [
        row for row in files
        if isinstance(row, dict) and row.get("name") == expected_name
        and isinstance(row.get("id"), str) and row.get("id")
        and isinstance(row.get("sha256"), str) and SHA256_PATTERN.fullmatch(row["sha256"])
        and isinstance(row.get("bytes"), int) and row["bytes"] > 0
    ]
    if len(matches) != 1:
        raise RawCleanupError(f"DRIVE_EXPECTED_FILE_NOT_UNIQUELY_VERIFIED:{expected_name}")
    return matches[0]


def _verified_receipt_copy(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("remote_verification") != "PASS":
        raise RawCleanupError("DRIVE_RECEIPT_COPY_REMOTE_VERIFICATION_NOT_PASS")
    if receipt.get("raw_product_uploaded") is not False:
        raise RawCleanupError("RAW_HDF5_MUST_NOT_BE_UPLOADED")
    files = receipt.get("files")
    if not isinstance(files, list):
        raise RawCleanupError("DRIVE_RECEIPT_COPY_FILE_LIST_MISSING")
    matches = [
        row for row in files
        if isinstance(row, dict)
        and row.get("name") == "drive-upload-receipt.json"
        and isinstance(row.get("id"), str) and row.get("id")
        and isinstance(row.get("sha256"), str) and SHA256_PATTERN.fullmatch(row["sha256"])
        and isinstance(row.get("bytes"), int) and row["bytes"] > 0
    ]
    if len(matches) != 1:
        raise RawCleanupError("DRIVE_UPLOAD_RECEIPT_COPY_NOT_UNIQUELY_VERIFIED")
    return matches[0]


def _validate_source_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("status") != EXPECTED_SOURCE_STATUS:
        raise RawCleanupError("SOURCE_MANIFEST_STATUS_NOT_COMPLETE")
    if manifest.get("author_release_id") != "P05023":
        raise RawCleanupError("SOURCE_MANIFEST_RELEASE_NOT_AUTHOR_P05023")
    if manifest.get("source_downloads") != EXPECTED_SOURCE_COUNT:
        raise RawCleanupError("SOURCE_DOWNLOAD_COUNT_NOT_FIVE")
    if manifest.get("author_exact_source_sha256_count") != EXPECTED_SOURCE_COUNT:
        raise RawCleanupError("SOURCE_SHA256_COUNT_NOT_FIVE")
    if manifest.get("source_products_grid_validated") != EXPECTED_SOURCE_COUNT:
        raise RawCleanupError("SOURCE_GRID_VALIDATION_COUNT_NOT_FIVE")
    products = manifest.get("products")
    if not isinstance(products, list) or len(products) != EXPECTED_SOURCE_COUNT:
        raise RawCleanupError("SOURCE_PRODUCT_LIST_NOT_FIVE")

    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            raise RawCleanupError("SOURCE_PRODUCT_ROW_NOT_OBJECT")
        name = product.get("granule_name")
        filename = product.get("source_filename")
        source_hash = product.get("source_sha256")
        source_bytes = product.get("source_bytes")
        if not isinstance(name, str) or not name.endswith("_P05023_N_F_J_001") and not name.endswith("_P05023_F_F_J_001"):
            raise RawCleanupError("SOURCE_GRANULE_NAME_NOT_EXACT_P05023")
        if product.get("release_id") != "P05023":
            raise RawCleanupError("SOURCE_PRODUCT_RELEASE_NOT_P05023")
        if product.get("download_status") != "PASS":
            raise RawCleanupError("SOURCE_PRODUCT_DOWNLOAD_NOT_PASS")
        if product.get("hdf5_container_valid") is not True:
            raise RawCleanupError("SOURCE_PRODUCT_HDF5_VALIDATION_NOT_PASS")
        if product.get("content_validation_status") != "PASS":
            raise RawCleanupError("SOURCE_PRODUCT_CONTENT_VALIDATION_NOT_PASS")
        if product.get("grid_validation_status") != "PASS":
            raise RawCleanupError("SOURCE_PRODUCT_GRID_VALIDATION_NOT_PASS")
        if product.get("grid_epsg") != EXPECTED_EPSG:
            raise RawCleanupError("SOURCE_PRODUCT_EPSG_MISMATCH")
        if product.get("grid_width") != EXPECTED_WIDTH or product.get("grid_height") != EXPECTED_HEIGHT:
            raise RawCleanupError("SOURCE_PRODUCT_GRID_DIMENSION_MISMATCH")
        if not isinstance(filename, str) or filename != name + ".h5" or Path(filename).name != filename:
            raise RawCleanupError("SOURCE_FILENAME_NOT_EXACT_GRANULE_NAME")
        if filename in seen:
            raise RawCleanupError("DUPLICATE_SOURCE_FILENAME")
        seen.add(filename)
        if not isinstance(source_hash, str) or not SHA256_PATTERN.fullmatch(source_hash):
            raise RawCleanupError("SOURCE_SHA256_INVALID")
        if not isinstance(source_bytes, int) or source_bytes <= 0:
            raise RawCleanupError("SOURCE_BYTE_COUNT_INVALID")
        validated.append(product)
    return validated


def _remaining_hdf5_files(raw_dir: Path) -> list[str]:
    if not raw_dir.exists():
        return []
    return sorted(
        path.relative_to(raw_dir).as_posix()
        for path in raw_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".h5", ".hdf5"}
    )


def cleanup_verified_raw_sources(
    *,
    run_root: str | Path,
    derived_root: str | Path,
    run_id: str,
    run_attempt: str | int,
) -> dict[str, Any]:
    """Delete only five exact, hash-verified P05023 HDF5 files after Drive PASS."""
    run_root = Path(run_root).resolve()
    derived_root = Path(derived_root).resolve()
    source_manifest_path = derived_root / "author-exact-source-manifest.json"
    main_receipt_path = derived_root / "drive-upload-receipt.json"
    copy_receipt_path = derived_root / "drive-receipt-upload.json"
    raw_dir = (run_root / "source-run" / "raw").resolve()

    receipt: dict[str, Any] = {
        "schema_version": "know-place-author-exact-raw-cleanup/1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": str(run_id),
        "workflow_run_attempt": str(run_attempt),
        "status": "BLOCKED_PRE_DELETE_VALIDATION",
        "source_manifest_sha256": None,
        "source_manifest_verified": False,
        "remote_derived_bundle_verification": "NOT_CHECKED",
        "remote_upload_receipt_copy_verification": "NOT_CHECKED",
        "drive_derived_bundle_file_id": None,
        "drive_derived_bundle_name": None,
        "expected_source_count": EXPECTED_SOURCE_COUNT,
        "source_files_hash_verified_before_delete": 0,
        "raw_hdf5_files_before_delete": 0,
        "raw_hdf5_deleted_count": 0,
        "raw_hdf5_files_remaining_count": None,
        "raw_hdf5_remaining": [],
        "raw_hdf5_uploaded": False,
        "cleanup_policy": "DELETE_ONLY_AFTER_TWO_REMOTE_DRIVE_VERIFICATION_RECEIPTS_PASS",
        "deleted_sources": [],
    }
    deleted: list[dict[str, Any]] = []
    try:
        if not source_manifest_path.is_file():
            raise RawCleanupError("SOURCE_MANIFEST_MISSING")
        source_manifest = _read_json(source_manifest_path)
        receipt["source_manifest_sha256"] = sha256_file(source_manifest_path)
        products = _validate_source_manifest(source_manifest)
        receipt["source_manifest_verified"] = True

        main_receipt = _read_json(main_receipt_path)
        bundle_file = _verified_drive_bundle(
            main_receipt,
            expected_name="author-exact-derived-results.zip",
        )
        receipt_copy = _read_json(copy_receipt_path)
        receipt_copy_file = _verified_receipt_copy(receipt_copy)
        receipt["remote_derived_bundle_verification"] = "PASS"
        receipt["remote_upload_receipt_copy_verification"] = "PASS"
        receipt["drive_derived_bundle_file_id"] = bundle_file["id"]
        receipt["drive_derived_bundle_name"] = bundle_file["name"]
        receipt["drive_derived_bundle_bytes"] = bundle_file["bytes"]
        receipt["drive_derived_bundle_sha256"] = bundle_file["sha256"]
        receipt["drive_upload_receipt_copy_id"] = receipt_copy_file["id"]

        if not raw_dir.is_dir() or raw_dir.is_symlink():
            raise RawCleanupError("RAW_SOURCE_DIRECTORY_MISSING_OR_UNSAFE")
        products_by_filename = {product["source_filename"]: product for product in products}
        actual_hdf5_paths = [
            path for path in raw_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".h5", ".hdf5"}
        ]
        nested_hdf5 = [
            path.relative_to(raw_dir).as_posix()
            for path in raw_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".h5", ".hdf5"}
            and path.parent != raw_dir
        ]
        actual_names = {path.name for path in actual_hdf5_paths}
        if nested_hdf5:
            raise RawCleanupError("UNEXPECTED_NESTED_HDF5_FOUND")
        if len(actual_hdf5_paths) != EXPECTED_SOURCE_COUNT or actual_names != set(products_by_filename):
            raise RawCleanupError("RAW_HDF5_FILE_SET_NOT_EXACT_FIVE")

        receipt["raw_hdf5_files_before_delete"] = len(actual_hdf5_paths)
        verified_files: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(actual_hdf5_paths):
            product = products_by_filename[path.name]
            if path.is_symlink() or not path.resolve().is_relative_to(raw_dir):
                raise RawCleanupError("RAW_HDF5_PATH_UNSAFE")
            actual_bytes = path.stat().st_size
            if actual_bytes != product["source_bytes"]:
                raise RawCleanupError(f"RAW_HDF5_BYTES_MISMATCH:{path.name}")
            actual_hash = sha256_file(path)
            if actual_hash != product["source_sha256"]:
                raise RawCleanupError(f"RAW_HDF5_SHA256_MISMATCH:{path.name}")
            receipt["source_files_hash_verified_before_delete"] += 1
            verified_files.append((path, product))

        # Do not start deletion until all five raw files pass every source-manifest check.
        for path, product in verified_files:
            path.unlink()
            deleted.append({
                "source_filename": product["source_filename"],
                "source_bytes": product["source_bytes"],
                "source_sha256": product["source_sha256"],
                "deleted": not path.exists(),
            })
            if path.exists():
                raise RawCleanupError(f"RAW_HDF5_DELETE_NOT_CONFIRMED:{path.name}")

        remaining = _remaining_hdf5_files(raw_dir)
        receipt["raw_hdf5_deleted_count"] = sum(row["deleted"] for row in deleted)
        receipt["deleted_sources"] = deleted
        receipt["raw_hdf5_files_remaining_count"] = len(remaining)
        receipt["raw_hdf5_remaining"] = remaining
        if receipt["raw_hdf5_deleted_count"] != EXPECTED_SOURCE_COUNT or remaining:
            receipt["status"] = "FAILED_PARTIAL_DELETE"
            raise RawCleanupError("RAW_HDF5_POST_DELETE_CHECK_FAILED")
        try:
            raw_dir.rmdir()
            receipt["raw_directory_removed"] = True
        except OSError:
            receipt["raw_directory_removed"] = False
        receipt["status"] = "PASS"
        receipt["raw_hdf5_deleted_after_verified_drive_retention"] = True
        receipt["raw_cleanup_evidence_is_post_delete"] = True
    except Exception as exc:
        remaining = _remaining_hdf5_files(raw_dir)
        receipt["raw_hdf5_deleted_count"] = sum(row.get("deleted") is True for row in deleted)
        receipt["deleted_sources"] = deleted
        receipt["raw_hdf5_files_remaining_count"] = len(remaining)
        receipt["raw_hdf5_remaining"] = remaining
        receipt["status"] = "FAILED_PARTIAL_DELETE" if deleted else receipt["status"]
        receipt["failure_type"] = type(exc).__name__
        receipt["failure_code"] = str(exc).split(":", maxsplit=1)[0][:180]
        receipt["raw_hdf5_deleted_after_verified_drive_retention"] = False

    _write_json_atomic(derived_root / "author-exact-raw-cleanup-receipt.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--derived-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    args = parser.parse_args(argv)
    result = cleanup_verified_raw_sources(
        run_root=args.run_root,
        derived_root=args.derived_root,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )
    print(f"AUTHOR_EXACT_RAW_CLEANUP_STATUS={result.get('status')}")
    print(f"RAW_HDF5_DELETED_COUNT={result.get('raw_hdf5_deleted_count')}")
    print(f"RAW_HDF5_FILES_REMAINING={result.get('raw_hdf5_files_remaining_count')}")
    print(f"RAW_HDF5_UPLOADED={str(result.get('raw_hdf5_uploaded')).lower()}")
    if result.get("status") != "PASS":
        print(f"AUTHOR_EXACT_RAW_CLEANUP_FAILURE={result.get('failure_code', 'UNSPECIFIED')}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
