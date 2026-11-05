from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "audit_drive_archives.py"
spec = importlib.util.spec_from_file_location("audit_drive_archives", TOOL)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def sample_manifest(archive_sha="a" * 64, data_sha="b" * 64, source_sha="c" * 64):
    row = {
        "path": "/science/data",
        "shape": [2, 2],
        "ndim": 2,
        "dtype": "float32",
        "attrs_sha256": "d" * 64,
        "logical_data_sha256": data_sha,
        "dimension_links": [{"axis": 0, "scale_path": "/science/yCoordinates"}],
        "retention_status": "retained",
        "reason": "full_lossless_source_dataset",
        "archive_dtype": "float32",
        "archive_shape": [2, 2],
        "dataset_creation_properties": {
            "maxshape": [2, 2], "chunks": [2, 2], "compression": "gzip",
            "compression_opts": 4, "shuffle": False, "fletcher32": False,
            "scaleoffset": None, "fillvalue": 0.0, "is_virtual": False, "external_storage": None,
        },
    }
    return {
        "schema_version": "sarguardian-science-archive/1.2",
        "policy": {"retention_profile": "full-lossless", "product_type": "GUNW"},
        "source": {
            "filename": "NISAR_L2_PR_GUNW_example.h5", "bytes": 1000,
            "sha256": source_sha, "hdf5_root_attrs_sha256": "e" * 64,
        },
        "archive": {"filename": "NISAR_L2_PR_GUNW_example.science.h5", "bytes": 950, "sha256": archive_sha},
        "statistics": {
            "source_dataset_count": 1, "retained_dataset_count": 1,
            "excluded_large_dataset_count": 0, "derived_dataset_count": 0,
            "source_bytes": 1000, "archive_bytes": 950,
        },
        "verification": {
            "local_archive_verification": "PASS",
            "retained_data_logical_checksums": "PASS",
            "derived_phase_verification": "PASS",
            "dimension_scale_verification": "PASS",
        },
        "source_group_attributes": [{"path": "/science", "attrs_sha256": "f" * 64}],
        "noncanonical_links": [],
        "retained_datasets": [row],
        "excluded_datasets": [],
        "derived_datasets": [],
        "skipped_hdf5_reference_attributes": [],
    }


def record(run, *, signature="sig-one", status="VERIFIED_FULL_LOSSLESS", size=950, source="c" * 64):
    return {
        "product_type": "GUNW", "maturity": "BETA",
        "granule_name": "NISAR_L2_PR_GUNW_example",
        "source_sha256": source, "logical_signature": signature,
        "status": status, "archive_bytes": size,
        "archive_sha256": (str(run) * 64)[:64], "run_folder": run,
        "run_created_time": f"2026-0{1 if run == 'run-1' else 2}-01T00:00:00Z",
    }


def test_logical_signature_ignores_archive_container_sha_but_uses_dataset_hashes():
    assert audit.logical_archive_signature(sample_manifest(archive_sha="a" * 64)) == audit.logical_archive_signature(
        sample_manifest(archive_sha="9" * 64)
    )


def test_logical_signature_changes_when_retained_dataset_digest_or_dimension_links_change():
    one = sample_manifest(data_sha="b" * 64)
    two = sample_manifest(data_sha="8" * 64)
    assert audit.logical_archive_signature(one) != audit.logical_archive_signature(two)
    two = sample_manifest(data_sha="b" * 64)
    two["retained_datasets"][0]["dimension_links"] = [{"axis": 0, "scale_path": "/wrong"}]
    assert audit.logical_archive_signature(one) != audit.logical_archive_signature(two)


def test_full_lossless_validator_accepts_complete_verified_manifest():
    errors = audit.validate_full_lossless_manifest(
        sample_manifest(), product_type="GUNW", granule_name="NISAR_L2_PR_GUNW_example"
    )
    assert errors == []


def test_full_lossless_validator_rejects_exclusions_or_failed_verification():
    manifest = sample_manifest()
    manifest["statistics"]["excluded_large_dataset_count"] = 1
    manifest["excluded_datasets"] = [{"path": "/science/excluded"}]
    manifest["verification"]["retained_data_logical_checksums"] = "FAIL"
    errors = audit.validate_full_lossless_manifest(
        manifest, product_type="GUNW", granule_name="NISAR_L2_PR_GUNW_example"
    )
    assert "full_lossless_archive_has_exclusions" in errors
    assert "archive_verification_not_pass:retained_data_logical_checksums" in errors


def test_only_verified_logically_equivalent_copies_count_as_reclaimable():
    records = [
        record("run-1"),
        record("run-2", signature="sig-one", size=950),
        {**record("run-3", status="UNVERIFIED"), "errors": ["receipt_missing"]},
    ]
    report = audit.build_report_from_records(records)
    summary = report["summary"]
    assert summary["archive_copies_found"] == 3
    assert summary["verified_full_lossless_copies"] == 2
    assert summary["unique_verified_source_products"] == 1
    assert summary["logically_duplicate_groups"] == 1
    assert summary["candidate_reclaimable_bytes"] == 950
    assert summary["unverified_copies"] == 1
    assert report["deletion_performed"] is False
    assert report["status"] == "REVIEW_REQUIRED"


def test_same_source_but_conflicting_logical_content_is_not_reclaimable():
    report = audit.build_report_from_records([
        record("run-1", signature="sig-one"),
        record("run-2", signature="different"),
    ])
    assert report["summary"]["candidate_reclaimable_bytes"] == 0
    assert report["summary"]["inconsistent_same_source_groups"] == 1
    assert report["status"] == "REVIEW_REQUIRED"


def test_different_source_hashes_are_not_duplicates():
    report = audit.build_report_from_records([
        record("run-1", source="c" * 64),
        record("run-2", source="d" * 64),
    ])
    assert report["summary"]["candidate_reclaimable_bytes"] == 0
    assert report["summary"]["unique_verified_source_products"] == 2
