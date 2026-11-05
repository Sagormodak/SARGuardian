from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.resume_streamed_run import merge_artifact_roots, plan_resume, validate_resume_compatibility


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _manifests():
    products = [
        {"id": "GUNW-001", "granule_name": "g1.h5", "product_type": "GUNW", "maturity": "PROVISIONAL"},
        {"id": "GOFF-033", "granule_name": "g2.h5", "product_type": "GOFF", "maturity": "PROVISIONAL"},
    ]
    common = {"run_profile": "full-source-baseline", "aoi": "source", "science_commit": "abc123",
              "retention_profile": "derived-only",
              "time_window": {"start_date": "2025-01-01", "end_date": "2026-12-31", "covers_full_baseline": True},
              "products": products}
    return dict(common, run_id="new"), dict(common, run_id="previous")


def _complete_checkpoint(granules: Path, cleanups: Path, pid: str, granule: str, family: str):
    folder_id = f"folder-{pid}"
    gdir = granules / f"sarguardian-granule-{pid}"
    _write(gdir / "product-processing.json", {
        "id": pid, "granule_name": granule, "product_type": family, "maturity": "PROVISIONAL",
        "aoi": "source", "science_commit": "abc123", "retention_profile": "derived-only",
        "derived_output_validation_status": "PASS", "drive_remote_verification": "PASS",
        "drive_remote_folder_id": folder_id, "source_file_sha256": "a" * 64,
        "source_file_bytes": 123, "retained_archive": None,
        "stats_csv": "derived/stats.csv", "export_files": ["derived/export/product.tif"]})
    _write(gdir / "derived-output-validation.json", {"status": "PASS"})
    _write(gdir / "drive-retention-receipt.json", {
        "remote_verification": "PASS", "remote_folder_id": folder_id,
        "files": [{"name": n} for n in ["source-inventory.json", "preflight-report.json",
            "derived-output-validation.json", "download-manifest.json", "stats.csv", "product.tif"]]})
    for name in ("source-inventory.json", "preflight-report.json", "download-manifest.json"):
        (gdir / name).write_text("{}", encoding="utf-8")
    (gdir / "derived").mkdir(parents=True, exist_ok=True)
    (gdir / "derived/stats.csv").write_text("row\n1\n", encoding="utf-8")
    (gdir / "derived/export").mkdir(parents=True, exist_ok=True)
    (gdir / "derived/export/product.tif").write_bytes(b"tiff")
    cdir = cleanups / f"sarguardian-cleanup-{pid}"
    _write(cdir / "local-cleanup-receipt.json", {
        "product_id": pid, "granule_name": granule, "aoi": "source", "science_commit": "abc123",
        "retention_profile": "derived-only", "remote_retention_verification": "PASS",
        "remote_retention_folder_id": folder_id, "runner_raw_hdf5_deleted": True})
    _write(cdir / "drive-cleanup-upload-receipt.json", {
        "remote_verification": "PASS", "files": [{"name": "local-cleanup-receipt.json"}]})


def test_resume_reuses_only_fully_verified_products(tmp_path):
    current, previous = _manifests()
    granules, cleanups = tmp_path / "granules", tmp_path / "cleanups"
    _complete_checkpoint(granules, cleanups, "GUNW-001", "g1.h5", "GUNW")
    failed = granules / "sarguardian-granule-GOFF-033"
    failed.mkdir(parents=True)
    _write(failed / "product-run-diagnostics.json", {"download": "failure"})
    plan = plan_resume(current, previous, granules, cleanups)
    assert plan["reused_product_ids"] == ["GUNW-001"]
    assert [p["id"] for p in plan["products_to_process"]] == ["GOFF-033"]
    assert plan["products_reused"] == 1
    assert plan["products_to_process_count"] == 1


def test_resume_rejects_different_baseline():
    current, previous = _manifests()
    previous["aoi"] = "different"
    with pytest.raises(ValueError, match="RESUME_MANIFEST_MISMATCH field=aoi"):
        validate_resume_compatibility(current, previous)


def test_resume_rejects_pilot_source_run():
    current, previous = _manifests()
    previous["run_profile"] = "validation-pilot"
    with pytest.raises(ValueError, match="RESUME_SOURCE_RUN_IS_NOT_FULL_BASELINE"):
        validate_resume_compatibility(current, previous)


def test_merge_preserves_good_checkpoint_when_current_only_has_diagnostics(tmp_path):
    previous, current, output = tmp_path / "previous", tmp_path / "current", tmp_path / "output"
    old = previous / "sarguardian-granule-GUNW-001"
    _write(old / "product-processing.json", {
        "status": "good", "derived_output_validation_status": "PASS",
        "drive_remote_verification": "PASS", "drive_remote_folder_id": "folder-GUNW-001",
        "source_file_sha256": "a" * 64, "source_file_bytes": 123,
    })
    _write(old / "derived-output-validation.json", {"status": "PASS"})
    _write(old / "drive-retention-receipt.json", {
        "remote_verification": "PASS", "remote_folder_id": "folder-GUNW-001",
    })
    new = current / "sarguardian-granule-GUNW-001"
    _write(new / "product-run-diagnostics.json", {"download": "failure"})
    result = merge_artifact_roots(previous, current, output, "granule")
    preserved = json.loads((output / "sarguardian-granule-GUNW-001/product-processing.json").read_text())
    assert preserved["status"] == "good"
    assert result["complete_kept_over_incomplete"] == 1


def test_merge_prefers_complete_new_artifact_over_old_checkpoint(tmp_path):
    previous, current, output = tmp_path / "previous", tmp_path / "current", tmp_path / "output"
    for root, status in ((previous, "old"), (current, "new")):
        folder = root / "sarguardian-granule-GUNW-001"
        _write(folder / "product-processing.json", {
            "status": status, "derived_output_validation_status": "PASS",
            "drive_remote_verification": "PASS", "drive_remote_folder_id": "folder-GUNW-001",
            "source_file_sha256": "b" * 64, "source_file_bytes": 456,
        })
        _write(folder / "derived-output-validation.json", {"status": "PASS"})
        _write(folder / "drive-retention-receipt.json", {
            "remote_verification": "PASS", "remote_folder_id": "folder-GUNW-001",
        })
    merge_artifact_roots(previous, current, output, "granule")
    assert json.loads((output / "sarguardian-granule-GUNW-001/product-processing.json").read_text())["status"] == "new"


def test_cleanup_merge_uses_cleanup_receipt_pair(tmp_path):
    previous, current, output = tmp_path / "previous", tmp_path / "current", tmp_path / "output"
    _write(previous / "sarguardian-cleanup-GUNW-001/local-cleanup-receipt.json", {"runner_raw_hdf5_deleted": True})
    _write(previous / "sarguardian-cleanup-GUNW-001/drive-cleanup-upload-receipt.json", {"remote_verification": "PASS"})
    result = merge_artifact_roots(previous, current, output, "cleanup")
    assert result["copied"] == 1
