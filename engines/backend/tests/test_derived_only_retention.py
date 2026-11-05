from __future__ import annotations

# Reuse the repository aggregation module's public policy-aware helpers.
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "aggregate_streamed_outputs.py"
spec = importlib.util.spec_from_file_location("aggregate_streamed_outputs_derived_only", TOOL)
assert spec and spec.loader
agg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agg)



def test_derived_only_storage_accounting_accepts_no_hdf5_archive(tmp_path):
    import json

    product_id = "GUNW-001"
    granule = (
        "NISAR_L2_PR_GUNW_006_048_D_074_007_2000_SH_"
        "20251125T125813_20251125T125848_20251207T125814_20251207T125849_X05010_N_F_J_001.h5"
    )
    artifact_root = tmp_path / "products"
    cleanup_root = tmp_path / "cleanup"
    product_dir = artifact_root / f"sarguardian-granule-{product_id}"
    cleanup_dir = cleanup_root / f"sarguardian-cleanup-{product_id}"
    product_dir.mkdir(parents=True)
    cleanup_dir.mkdir(parents=True)

    def receipt(path, files):
        path.write_text(json.dumps({
            "remote_verification": "PASS",
            "remote_folder_id": "drive-folder",
            "files": files,
        }), encoding="utf-8")

    receipt(product_dir / "drive-retention-receipt.json", [
        {"id": "inventory-id", "name": "source-inventory.json", "bytes": 5, "reused": False},
        {"id": "stats-id", "name": "gunw_stats_source.csv", "bytes": 25, "reused": False},
        {"id": "tiff-id", "name": "GUNW_fixture.tif", "bytes": 350, "reused": False},
        {"id": "validation-id", "name": "derived-output-validation.json", "bytes": 70, "reused": False},
    ])
    receipt(product_dir / "drive-metadata-upload-receipt.json", [
        {"id": "processing-id", "name": "product-processing.json", "bytes": 90, "reused": False},
        {"id": "receipt-id", "name": "drive-retention-receipt.json", "bytes": 500, "reused": False},
    ])
    receipt(cleanup_dir / "drive-cleanup-upload-receipt.json", [
        {"id": "cleanup-id", "name": "local-cleanup-receipt.json", "bytes": 20, "reused": False},
    ])
    manifest = {
        "retention_profile": "derived-only",
        "products": [{"id": product_id, "granule_name": granule}],
    }

    errors = []
    result = agg.summarize_retained_storage(manifest, artifact_root, cleanup_root, errors)

    assert result["status"] == "PASS"
    assert result["retention_profile"] == "derived-only"
    assert result["products_accounted"] == 1
    assert result["actual_remote_retained_bytes"] == 1060
    assert result["by_product"][0]["retained_archive"] is False
    assert result["by_product"][0]["retained_archive_bytes"] == 0
    assert result["by_product"][0]["ancillary_retained_bytes"] == 1060
    assert errors == []


def test_derived_only_cleanup_evidence_requires_no_remote_archive(tmp_path):
    import json

    artifact_root = tmp_path / "products"
    cleanup_root = tmp_path / "cleanup"
    product_id = "GOFF-001"
    granule = (
        "NISAR_L2_PR_GOFF_006_048_D_074_007_2000_SH_"
        "20251125T125813_20251125T125848_20251207T125814_20251207T125849_X05010_N_F_J_001.h5"
    )
    product_dir = artifact_root / f"sarguardian-granule-{product_id}"
    cleanup_dir = cleanup_root / f"sarguardian-cleanup-{product_id}"
    product_dir.mkdir(parents=True)
    cleanup_dir.mkdir(parents=True)

    meta = {
        "drive_remote_folder_id": "drive-folder",
        "source_file_sha256": "source-sha",
        "retained_archive": None,
        "retained_archive_sha256": None,
    }
    (product_dir / "product-processing.json").write_text(json.dumps(meta), encoding="utf-8")
    receipt = {
        "schema_version": "sarguardian-local-cleanup-receipt/1.1",
        "product_id": product_id,
        "product_type": "GOFF",
        "maturity": "BETA",
        "granule_name": granule,
        "aoi": "source",
        "science_commit": "science-sha",
        "source_file_sha256": "source-sha",
        "retention_profile": "derived-only",
        "retained_archive_name": None,
        "retained_archive_sha256": None,
        "remote_retention_verification": "PASS",
        "remote_retention_folder_id": "drive-folder",
        "runner_raw_hdf5_deleted": True,
        "runner_archive_deleted": True,
        "cleanup_scope": "temporary runner raw deleted after verified derived-only outputs; no HDF5 archive retained",
    }
    (cleanup_dir / "local-cleanup-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    drive_receipt = {
        "remote_verification": "PASS",
        "files": [{"name": "local-cleanup-receipt.json", "bytes": 100, "md5": "abc"}],
    }
    (cleanup_dir / "drive-cleanup-upload-receipt.json").write_text(json.dumps(drive_receipt), encoding="utf-8")
    manifest = {
        "science_commit": "science-sha",
        "retention_profile": "derived-only",
        "products": [{
            "id": product_id,
            "product_type": "GOFF",
            "maturity": "BETA",
            "granule_name": granule,
        }],
    }

    errors = []
    result = agg.validate_cleanup_evidence(manifest, artifact_root, cleanup_root, errors)
    assert result == {"status": "PASS", "expected": 1, "verified": 1}
    assert errors == []
