from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "aggregate_streamed_outputs.py"
spec = importlib.util.spec_from_file_location("aggregate_streamed_outputs", TOOL)
assert spec and spec.loader
agg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agg)


def test_stat_rows_key_by_product_and_layer():
    fields = ["file", "layer", "median", "maturity"]
    rows = [
        {"file": "A.h5", "layer": "HH/layer1", "median": "1", "maturity": "BETA"},
        {"file": "A.h5", "layer": "HH/layer2", "median": "2", "maturity": "BETA"},
        {"file": "B.h5", "layer": "HH/layer2", "median": "3", "maturity": "BETA"},
    ]
    assert len({agg.row_key(r, fields) for r in rows}) == 3


def test_candidate_floor_rows_do_not_collapse_to_same_file_key():
    fields = ["target_id", "file", "window_px", "local_floor_mm_day"]
    rows = [
        {"target_id": "1", "file": "A.h5", "window_px": "6", "local_floor_mm_day": "1.2"},
        {"target_id": "4", "file": "A.h5", "window_px": "6", "local_floor_mm_day": "2.4"},
        {"target_id": "4", "file": "A.h5", "window_px": "12", "local_floor_mm_day": "2.1"},
    ]
    assert len({agg.row_key(r, fields) for r in rows}) == 3


def test_common_reference_rows_key_by_target_pair_and_window():
    fields = ["target_id", "pair", "window_px", "datum_error_mm"]
    a = {"target_id": "4", "pair": "20260702_20260714", "window_px": "6", "datum_error_mm": "1.2"}
    b = {"target_id": "4", "pair": "20260714_20260726", "window_px": "6", "datum_error_mm": "-0.3"}
    assert agg.row_key(a, fields) != agg.row_key(b, fields)


def test_timeseries_rows_key_by_geometry_component_epoch():
    fields = ["geometry", "component", "epoch", "cumulative_mm"]
    a = {"geometry": "ASC", "component": "range", "epoch": "2026-07-01", "cumulative_mm": "1"}
    b = {"geometry": "ASC", "component": "range", "epoch": "2026-07-13", "cumulative_mm": "2"}
    assert agg.row_key(a, fields) != agg.row_key(b, fields)


def test_numeric_comparison_has_explicit_small_tolerance():
    assert agg.value_equal("10.00000", "10.00001", "median")
    assert not agg.value_equal("10.0", "10.1", "median")
    assert agg.value_equal("file.tif", "file.tif", "export_file")


def test_detectability_rows_use_experiment_parameters_and_tolerate_float_serialization_noise():
    fields = [
        "precursor_days", "revisit_days", "noise_mm", "creep_mm", "gate",
        "gate_mm_day", "detection_rate", "abs_pred_error_median",
    ]
    baseline = [{
        "precursor_days": "10.0", "revisit_days": "1", "noise_mm": "5.0",
        "creep_mm": "300.0", "gate": "noise", "gate_mm_day": "21.213",
        "detection_rate": "0.9775", "abs_pred_error_median": "0.7015650034458467",
    }]
    actual = [{
        "precursor_days": "10.0", "revisit_days": "1", "noise_mm": "5.0",
        "creep_mm": "300.0", "gate": "noise", "gate_mm_day": "21.213",
        "detection_rate": "0.9775", "abs_pred_error_median": "0.7015650034458449",
    }]
    assert agg.row_key(baseline[0], fields) == agg.row_key(actual[0], fields)
    errors = []
    result = agg.compare_rows(baseline, actual, fields, label="detectability", errors=errors)
    assert result["status"] == "PASS"
    assert result["row_keys_missing"] == 0
    assert result["row_keys_extra"] == 0
    assert result["field_mismatches"] == 0
    assert errors == []


def test_compare_rows_detects_missing_extra_and_value_differences():
    fields = ["file", "median"]
    baseline = [{"file": "A.h5", "median": "1.0"}, {"file": "B.h5", "median": "2.0"}]
    actual = [{"file": "A.h5", "median": "1.1"}, {"file": "C.h5", "median": "3.0"}]
    errors = []
    result = agg.compare_rows(baseline, actual, fields, label="test", errors=errors)
    assert result["status"] == "FAIL"
    assert result["row_keys_missing"] == 1
    assert result["row_keys_extra"] == 1
    assert result["field_mismatches"] == 1
    assert errors


def test_cleanup_evidence_requires_verified_remote_retention_and_deleted_runner_copies(tmp_path):
    import json

    artifact_root = tmp_path / "product-artifacts"
    cleanup_root = tmp_path / "cleanup-artifacts"
    product_id = "GUNW-001"
    granule = (
        "NISAR_L2_PR_GUNW_006_048_D_074_007_2000_SH_"
        "20251125T125813_20251125T125848_20251207T125814_20251207T125849_X05010_N_F_J_001.h5"
    )
    product_dir = artifact_root / f"sarguardian-granule-{product_id}"
    cleanup_dir = cleanup_root / f"sarguardian-cleanup-{product_id}"
    product_dir.mkdir(parents=True)
    cleanup_dir.mkdir(parents=True)
    meta = {
        "drive_remote_folder_id": "drive-folder-123",
        "source_file_sha256": "source-sha",
        "retained_archive": f"archive/{granule[:-3]}.science.h5",
        "retained_archive_sha256": "archive-sha",
    }
    (product_dir / "product-processing.json").write_text(json.dumps(meta), encoding="utf-8")
    receipt = {
        "schema_version": "sarguardian-local-cleanup-receipt/1.0",
        "product_id": product_id,
        "product_type": "GUNW",
        "maturity": "BETA",
        "granule_name": granule,
        "aoi": "source",
        "science_commit": "science-sha",
        "source_file_sha256": "source-sha",
        "retained_archive_name": f"{granule[:-3]}.science.h5",
        "retained_archive_sha256": "archive-sha",
        "remote_retention_verification": "PASS",
        "remote_retention_folder_id": "drive-folder-123",
        "runner_raw_hdf5_deleted": True,
        "runner_archive_deleted": True,
        "cleanup_scope": "temporary GitHub Actions runner only; remote full-lossless Drive archive remains retained",
    }
    (cleanup_dir / "local-cleanup-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    drive_receipt = {
        "remote_verification": "PASS",
        "files": [{"name": "local-cleanup-receipt.json", "bytes": 100, "md5": "abc"}],
    }
    (cleanup_dir / "drive-cleanup-upload-receipt.json").write_text(json.dumps(drive_receipt), encoding="utf-8")
    manifest = {
        "science_commit": "science-sha",
        "products": [{
            "id": product_id,
            "product_type": "GUNW",
            "maturity": "BETA",
            "granule_name": granule,
        }],
    }
    errors = []
    result = agg.validate_cleanup_evidence(manifest, artifact_root, cleanup_root, errors)
    assert result == {"status": "PASS", "expected": 1, "verified": 1}
    assert errors == []


def test_cleanup_evidence_fails_if_runner_archive_not_deleted(tmp_path):
    import json

    artifact_root = tmp_path / "product-artifacts"
    cleanup_root = tmp_path / "cleanup-artifacts"
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
        "drive_remote_folder_id": "drive-folder-456",
        "source_file_sha256": "source-sha",
        "retained_archive": f"archive/{granule[:-3]}.science.h5",
        "retained_archive_sha256": "archive-sha",
    }
    (product_dir / "product-processing.json").write_text(json.dumps(meta), encoding="utf-8")
    receipt = {
        "schema_version": "sarguardian-local-cleanup-receipt/1.0",
        "product_id": product_id,
        "product_type": "GOFF",
        "maturity": "BETA",
        "granule_name": granule,
        "aoi": "source",
        "science_commit": "science-sha",
        "source_file_sha256": "source-sha",
        "retained_archive_name": f"{granule[:-3]}.science.h5",
        "retained_archive_sha256": "archive-sha",
        "remote_retention_verification": "PASS",
        "remote_retention_folder_id": "drive-folder-456",
        "runner_raw_hdf5_deleted": True,
        "runner_archive_deleted": False,
        "cleanup_scope": "temporary GitHub Actions runner only; remote full-lossless Drive archive remains retained",
    }
    (cleanup_dir / "local-cleanup-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    drive_receipt = {
        "remote_verification": "PASS",
        "files": [{"name": "local-cleanup-receipt.json", "bytes": 100, "md5": "abc"}],
    }
    (cleanup_dir / "drive-cleanup-upload-receipt.json").write_text(json.dumps(drive_receipt), encoding="utf-8")
    manifest = {
        "science_commit": "science-sha",
        "products": [{
            "id": product_id,
            "product_type": "GOFF",
            "maturity": "BETA",
            "granule_name": granule,
        }],
    }
    errors = []
    result = agg.validate_cleanup_evidence(manifest, artifact_root, cleanup_root, errors)
    assert result == {"status": "FAIL", "expected": 1, "verified": 0}
    assert errors[0]["problem"] == "cleanup_evidence_mismatch"



def test_retention_storage_accounting_sums_actual_unique_drive_file_sizes(tmp_path):
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
        {"id": "archive-id", "name": f"{granule[:-3]}.science.h5", "bytes": 100, "reused": False},
        {"id": "inventory-id", "name": "source-inventory.json", "bytes": 5, "reused": False},
    ])
    receipt(product_dir / "drive-metadata-upload-receipt.json", [
        {"id": "processing-id", "name": "product-processing.json", "bytes": 10, "reused": False},
        {"id": "receipt-id", "name": "drive-retention-receipt.json", "bytes": 50, "reused": False},
    ])
    receipt(cleanup_dir / "drive-cleanup-upload-receipt.json", [
        {"id": "cleanup-id", "name": "local-cleanup-receipt.json", "bytes": 15, "reused": False},
    ])
    manifest = {
        "products": [{"id": product_id, "granule_name": granule}],
    }

    errors = []
    result = agg.summarize_retained_storage(manifest, artifact_root, cleanup_root, errors)

    assert result["status"] == "PASS"
    assert result["products_expected"] == result["products_accounted"] == 1
    assert result["unique_remote_file_count"] == 5
    assert result["actual_remote_retained_bytes"] == 180
    assert result["actual_remote_retained_gib"] == round(180 / (1024 ** 3), 6)
    assert result["net_new_remote_bytes_in_run"] == 180
    assert result["by_product"][0]["retained_archive_bytes"] == 100
    assert result["by_product"][0]["ancillary_retained_bytes"] == 80
    assert result["run_level_bundle_included"] is False
    assert "not raw source-size estimates" in result["accounting_basis"]
    assert errors == []


def test_retention_storage_accounting_fails_if_any_drive_receipt_is_missing(tmp_path):
    import json

    product_id = "GOFF-001"
    granule = (
        "NISAR_L2_PR_GOFF_006_048_D_074_007_2000_SH_"
        "20251125T125813_20251125T125848_20251207T125814_20251207T125849_X05010_N_F_J_001.h5"
    )
    artifact_root = tmp_path / "products"
    cleanup_root = tmp_path / "cleanup"
    product_dir = artifact_root / f"sarguardian-granule-{product_id}"
    cleanup_dir = cleanup_root / f"sarguardian-cleanup-{product_id}"
    product_dir.mkdir(parents=True)
    cleanup_dir.mkdir(parents=True)
    (product_dir / "drive-retention-receipt.json").write_text(json.dumps({
        "remote_verification": "PASS",
        "remote_folder_id": "drive-folder",
        "files": [{"id": "archive-id", "name": f"{granule[:-3]}.science.h5", "bytes": 100, "reused": False}],
    }), encoding="utf-8")
    manifest = {"products": [{"id": product_id, "granule_name": granule}]}

    errors = []
    result = agg.summarize_retained_storage(manifest, artifact_root, cleanup_root, errors)

    assert result["status"] == "FAIL"
    assert result["products_accounted"] == 0
    assert result["actual_remote_retained_bytes"] == 0
    assert len(errors) == 2
    assert {error["receipt"] for error in errors} == {
        "drive-metadata-upload-receipt.json",
        "drive-cleanup-upload-receipt.json",
    }


def test_read_product_diagnostic_context_surfaces_download_failure(tmp_path):
    import json

    artifact_dir = tmp_path / "sarguardian-granule-GUNW-006"
    artifact_dir.mkdir()
    (artifact_dir / "product-run-diagnostics.json").write_text(
        json.dumps({
            "step_outcomes": {"download": "failure", "drive": "skipped"},
            "download_error_code": "ERROR=DIRECT_HTTPS_PRODUCT_PROBE_FAILED TYPE=ConnectionError",
            "download_diagnostics": [
                "ERROR=DIRECT_HTTPS_PRODUCT_PROBE_FAILED TYPE=ConnectionError",
                "DIRECT_PRODUCT_DIAGNOSTIC=status=unknown detail=temporary endpoint outage",
            ],
            "download_manifest_created": False,
            "drive_receipt_created": False,
            "raw_hdf5_present_at_diagnostic_time": False,
        }),
        encoding="utf-8",
    )

    result = agg.read_product_diagnostic_context(artifact_dir)

    assert result["diagnostics_artifact_present"] is True
    assert result["diagnostic_step_outcomes"]["download"] == "failure"
    assert result["download_error_code"].startswith("ERROR=DIRECT_HTTPS_PRODUCT_PROBE_FAILED")
    assert len(result["download_diagnostics"]) == 2
    assert result["download_manifest_created"] is False


def test_read_product_diagnostic_context_handles_missing_or_invalid_json(tmp_path):
    import json

    artifact_dir = tmp_path / "sarguardian-granule-GOFF-033"
    artifact_dir.mkdir()
    assert agg.read_product_diagnostic_context(artifact_dir) == {
        "diagnostics_artifact_present": False
    }

    path = artifact_dir / "product-run-diagnostics.json"
    path.write_text("{not-json", encoding="utf-8")
    result = agg.read_product_diagnostic_context(artifact_dir)
    assert result["diagnostics_artifact_present"] is True
    assert "diagnostics_parse_error" in result




def test_candidate4_common_reference_stack_keeps_all_16_pr_and_two_ur_edges():
    rows = [
        {"file": f"NISAR_L2_PR_GOFF_006_098_A_016_{i:03d}_4000_SH_20251128T233919_20251128T233954_20251210T233920_20251210T233955_X05010_N_F_J_001.h5",
         "layer": "HH/layer2"}
        for i in range(16)
    ]
    # These are distinct PR/UR files for the same late acquisition edges. They
    # must both be in the common-mask stack and the least-squares inversion.
    rows.extend([
        {"file": "NISAR_L2_UR_GOFF_028_048_D_074_029_2000_SH_20260816T125812_20260816T125846_20260828T125812_20260828T125846_P05023_F_F_J_001.h5",
         "layer": "HH/layer2"},
        {"file": "NISAR_L2_UR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_F_F_J_001.h5",
         "layer": "HH/layer2"},
    ])

    selected = agg.select_candidate4_common_reference_rows(rows)

    assert len(selected) == 18
    assert sum("_PR_GOFF_" in row["file"] for row in selected) == 16
    assert sum("_UR_GOFF_" in row["file"] for row in selected) == 2
    assert {row["file"] for row in selected} == {row["file"] for row in rows}


def test_candidate4_common_reference_stack_fails_closed_when_ur_edges_are_missing():
    rows = [
        {"file": f"NISAR_L2_PR_GOFF_006_098_A_016_{i:03d}_4000_SH_20251128T233919_20251128T233954_20251210T233920_20251210T233955_X05010_N_F_J_001.h5",
         "layer": "HH/layer2"}
        for i in range(16)
    ]
    rows.append({
        "file": "NISAR_L2_UR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_F_F_J_001.h5",
        "layer": "HH/layer2",
    })

    try:
        agg.select_candidate4_common_reference_rows(rows)
    except ValueError as exc:
        assert "Expected all 18 candidate-4 GOFF layer2 source products" in str(exc)
        assert "PR=16 UR=1" in str(exc)
    else:
        raise AssertionError("The candidate-4 stack must fail closed when one UR product is missing")

def test_resumed_checkpoint_bytes_are_not_counted_as_new_in_current_run(tmp_path):
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

    # These historical receipts said the files were new in the original run.
    # The current manifest resumes the whole checkpoint, so they are not new
    # bytes for this execution even though the original receipt flag is False.
    receipt(product_dir / "drive-retention-receipt.json", [
        {"id": "archive-id", "name": f"{granule[:-3]}.science.h5", "bytes": 100, "reused": False},
        {"id": "inventory-id", "name": "source-inventory.json", "bytes": 5, "reused": False},
    ])
    receipt(product_dir / "drive-metadata-upload-receipt.json", [
        {"id": "processing-id", "name": "product-processing.json", "bytes": 10, "reused": False},
        {"id": "receipt-id", "name": "drive-retention-receipt.json", "bytes": 50, "reused": False},
    ])
    receipt(cleanup_dir / "drive-cleanup-upload-receipt.json", [
        {"id": "cleanup-id", "name": "local-cleanup-receipt.json", "bytes": 15, "reused": False},
    ])
    manifest = {
        "retention_profile": "full-lossless",
        "products": [{"id": product_id, "granule_name": granule}],
        "resume": {"enabled": True, "reused_product_ids": [product_id]},
    }

    errors = []
    result = agg.summarize_retained_storage(manifest, artifact_root, cleanup_root, errors)

    assert result["status"] == "PASS"
    assert result["actual_remote_retained_bytes"] == 180
    assert result["net_new_remote_bytes_in_run"] == 0
    assert result["products_reused_from_checkpoint"] == 1
    assert result["new_bytes_excludes_reused_checkpoints"] is True
    assert errors == []


