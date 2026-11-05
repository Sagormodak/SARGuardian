"""Offline tests for verified raw-source cleanup after remote derived retention."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.know_place.author_exact_retention import cleanup_verified_raw_sources


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    run_root = tmp_path / "run"
    derived_root = run_root / "derived"
    raw_dir = run_root / "source-run" / "raw"
    raw_dir.mkdir(parents=True)
    derived_root.mkdir(parents=True)
    products = []
    for i in range(5):
        name = f"NISAR_L2_PR_GOFF_{23+i:03d}_098_A_fake_P05023_N_F_J_001"
        filename = name + ".h5"
        payload = (f"test-source-payload-{i}-" * 19).encode()
        path = raw_dir / filename
        path.write_bytes(payload)
        products.append({
            "granule_name": name,
            "source_filename": filename,
            "release_id": "P05023",
            "download_status": "PASS",
            "hdf5_container_valid": True,
            "content_validation_status": "PASS",
            "grid_validation_status": "PASS",
            "grid_epsg": 32645,
            "grid_width": 4311,
            "grid_height": 4230,
            "source_bytes": len(payload),
            "source_sha256": _sha(path),
        })
    manifest = {
        "status": "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED",
        "author_release_id": "P05023",
        "source_downloads": 5,
        "author_exact_source_sha256_count": 5,
        "source_products_grid_validated": 5,
        "products": products,
    }
    (derived_root / "author-exact-source-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    main_receipt = {
        "remote_verification": "PASS",
        "raw_product_uploaded": False,
        "raw_source_deleted": False,  # This receipt is generated before runner-local cleanup.
        "files": [{
            "name": "author-exact-derived-results.zip",
            "id": "drive-bundle-id",
            "bytes": 1234,
            "sha256": "a" * 64,
        }],
    }
    copy_receipt = {
        "remote_verification": "PASS",
        "raw_product_uploaded": False,
        "files": [{
            "name": "drive-upload-receipt.json",
            "id": "drive-receipt-copy-id",
            "bytes": 888,
            "sha256": "b" * 64,
        }],
    }
    (derived_root / "drive-upload-receipt.json").write_text(json.dumps(main_receipt), encoding="utf-8")
    (derived_root / "drive-receipt-upload.json").write_text(json.dumps(copy_receipt), encoding="utf-8")
    return run_root, derived_root, raw_dir, products


def test_cleanup_deletes_only_five_hash_verified_sources_after_remote_receipts_pass(tmp_path) -> None:
    run_root, derived_root, raw_dir, products = _fixture(tmp_path)
    result = cleanup_verified_raw_sources(
        run_root=run_root, derived_root=derived_root, run_id="123", run_attempt=1,
    )
    assert result["status"] == "PASS"
    assert result["source_manifest_verified"] is True
    assert result["source_files_hash_verified_before_delete"] == 5
    assert result["remote_derived_bundle_verification"] == "PASS"
    assert result["remote_upload_receipt_copy_verification"] == "PASS"
    assert result["drive_derived_bundle_file_id"] == "drive-bundle-id"
    assert result["raw_hdf5_files_before_delete"] == 5
    assert result["raw_hdf5_deleted_count"] == 5
    assert result["raw_hdf5_files_remaining_count"] == 0
    assert result["raw_hdf5_uploaded"] is False
    assert result["raw_hdf5_deleted_after_verified_drive_retention"] is True
    assert result["raw_cleanup_evidence_is_post_delete"] is True
    assert all(not (raw_dir / p["source_filename"]).exists() for p in products)
    assert not raw_dir.exists()
    saved = json.loads((derived_root / "author-exact-raw-cleanup-receipt.json").read_text())
    assert saved == result


def test_receipt_generated_before_cleanup_does_not_block_cleanup_when_drive_verified(tmp_path) -> None:
    run_root, derived_root, raw_dir, _ = _fixture(tmp_path)
    receipt_path = derived_root / "drive-upload-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["raw_source_deleted"] is False
    # The separate post-delete receipt, not the pre-delete upload receipt, records deletion truth.
    result = cleanup_verified_raw_sources(
        run_root=run_root, derived_root=derived_root, run_id="456", run_attempt=1,
    )
    assert result["status"] == "PASS"
    assert result["raw_hdf5_deleted_after_verified_drive_retention"] is True


def test_failed_drive_verification_blocks_deletion_and_records_failure_receipt(tmp_path) -> None:
    run_root, derived_root, raw_dir, products = _fixture(tmp_path)
    path = derived_root / "drive-upload-receipt.json"
    value = json.loads(path.read_text())
    value["remote_verification"] = "FAIL"
    path.write_text(json.dumps(value))
    result = cleanup_verified_raw_sources(
        run_root=run_root, derived_root=derived_root, run_id="789", run_attempt=1,
    )
    assert result["status"] == "BLOCKED_PRE_DELETE_VALIDATION"
    assert result["failure_code"] == "DRIVE_REMOTE_VERIFICATION_NOT_PASS"
    assert result["raw_hdf5_deleted_count"] == 0
    assert result["raw_hdf5_files_remaining_count"] == 5
    assert all((raw_dir / p["source_filename"]).exists() for p in products)


def test_hash_mismatch_blocks_all_deletion_before_any_file_is_removed(tmp_path) -> None:
    run_root, derived_root, raw_dir, products = _fixture(tmp_path)
    (raw_dir / products[2]["source_filename"]).write_bytes(b"modified after validation")
    result = cleanup_verified_raw_sources(
        run_root=run_root, derived_root=derived_root, run_id="321", run_attempt=1,
    )
    assert result["status"] == "BLOCKED_PRE_DELETE_VALIDATION"
    assert result["failure_code"].startswith("RAW_HDF5_BYTES_MISMATCH") or result["failure_code"].startswith("RAW_HDF5_SHA256_MISMATCH")
    assert result["raw_hdf5_deleted_count"] == 0
    assert result["raw_hdf5_files_remaining_count"] == 5
    assert len(list(raw_dir.glob("*.h5"))) == 5


def test_unexpected_extra_hdf5_blocks_deletion(tmp_path) -> None:
    run_root, derived_root, raw_dir, _ = _fixture(tmp_path)
    (raw_dir / "unexpected.h5").write_bytes(b"not in manifest")
    result = cleanup_verified_raw_sources(
        run_root=run_root, derived_root=derived_root, run_id="654", run_attempt=1,
    )
    assert result["status"] == "BLOCKED_PRE_DELETE_VALIDATION"
    assert result["failure_code"] == "RAW_HDF5_FILE_SET_NOT_EXACT_FIVE"
    assert result["raw_hdf5_deleted_count"] == 0
    assert result["raw_hdf5_files_remaining_count"] == 6


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(author_exact_source_sha256_count=4), "SOURCE_SHA256_COUNT_NOT_FIVE"),
    (lambda d: d.update(status="PARTIAL_DOWNLOAD"), "SOURCE_MANIFEST_STATUS_NOT_COMPLETE"),
])
def test_incomplete_source_manifest_blocks_deletion(tmp_path, mutate, code) -> None:
    run_root, derived_root, raw_dir, _ = _fixture(tmp_path)
    path = derived_root / "author-exact-source-manifest.json"
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value))
    result = cleanup_verified_raw_sources(
        run_root=run_root, derived_root=derived_root, run_id="987", run_attempt=1,
    )
    assert result["status"] == "BLOCKED_PRE_DELETE_VALIDATION"
    assert result["failure_code"] == code
    assert result["raw_hdf5_deleted_count"] == 0
    assert len(list(raw_dir.glob("*.h5"))) == 5
