from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import plan_aoi_retries as planner


def _inputs(tmp_path: Path, step_outcomes: dict[str, str], validation_status: str | None = None):
    product = {
        "id": "GOFF-001",
        "granule_name": "NISAR_L2_PR_GOFF_TEST_PRODUCT",
        "product_type": "GOFF",
        "maturity": "PROVISIONAL",
        "expected_source_bytes": 100,
    }
    manifest = {
        "run_id": "test-run",
        "aoi_wkt_sha256": "test-hash",
        "aoi_name": "custom",
        "science_commit": "science-sha",
        "orchestration_sha": "orchestration-sha",
        "orchestration_branch": "feat/e2e-aoi-wkt-date-dashboard",
        "retention_profile": "derived-only",
        "products": [product],
    }
    product_root = tmp_path / "products"
    cleanup_root = tmp_path / "cleanups"
    artifact = product_root / "sarguardian-granule-GOFF-001"
    artifact.mkdir(parents=True)
    diagnostics = {"product_id": "GOFF-001", "step_outcomes": step_outcomes}
    (artifact / "product-run-diagnostics.json").write_text(json.dumps(diagnostics), encoding="utf-8")
    if validation_status is not None:
        (artifact / "derived-output-validation.json").write_text(
            json.dumps({"status": validation_status}), encoding="utf-8"
        )
    return manifest, product_root, cleanup_root


def test_reader_failure_after_successful_download_and_aoi_preflight_is_terminal_not_retried(tmp_path):
    manifest, product_root, cleanup_root = _inputs(
        tmp_path,
        {"download": "success", "aoi_preflight": "success", "reader": "failure"},
    )

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["retry_count"] == 0
    assert result["terminal_failure_count"] == 1
    decision = result["decisions"][0]
    assert decision["status"] == "TERMINAL_FAILURE"
    assert decision["terminal_reason"] == (
        "NON_RETRYABLE_READER_FAILURE_AFTER_SUCCESSFUL_DOWNLOAD_AND_AOI_PREFLIGHT"
    )


def test_download_failure_remains_eligible_for_retry(tmp_path):
    manifest, product_root, cleanup_root = _inputs(
        tmp_path,
        {"download": "failure", "aoi_preflight": "skipped", "reader": "skipped"},
    )

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["retry_count"] == 1
    assert result["terminal_failure_count"] == 0
    assert result["decisions"][0]["status"] == "RETRY"


def test_structural_validation_failure_after_successful_reader_is_terminal(tmp_path):
    manifest, product_root, cleanup_root = _inputs(
        tmp_path,
        {"download": "success", "aoi_preflight": "success", "reader": "success"},
        validation_status="FAIL",
    )

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["retry_count"] == 0
    assert result["terminal_failure_count"] == 1
    assert result["decisions"][0]["status"] == "TERMINAL_FAILURE"
    assert result["decisions"][0]["terminal_reason"] == (
        "NON_RETRYABLE_STRUCTURAL_VALIDATION_FAILURE_AFTER_SUCCESSFUL_READER"
    )



def _write_valid_checkpoint(tmp_path: Path, *, branch_name: str = "main"):
    product = {
        "id": "GOFF-001",
        "granule_name": "NISAR_L2_PR_GOFF_TEST_PRODUCT",
        "product_type": "GOFF",
        "maturity": "PROVISIONAL",
        "expected_source_bytes": 100,
    }
    manifest = {
        "run_id": "green-run",
        "aoi_wkt_sha256": "aoi-hash",
        "aoi_name": "custom",
        "science_commit": "science-sha",
        "orchestration_sha": "orchestration-sha",
        "orchestration_branch": branch_name,
        "retention_profile": "derived-only",
        "products": [product],
    }
    product_root = tmp_path / "products"
    cleanup_root = tmp_path / "cleanups"
    artifact = product_root / "sarguardian-granule-GOFF-001"
    cleanup = cleanup_root / "sarguardian-cleanup-GOFF-001"
    artifact.mkdir(parents=True)
    cleanup.mkdir(parents=True)
    sha = "a" * 64
    (artifact / "product-processing.json").write_text(json.dumps({
        "id": "GOFF-001",
        "product_type": "GOFF",
        "granule_name": "NISAR_L2_PR_GOFF_TEST_PRODUCT",
        "aoi": "custom",
        "science_commit": "science-sha",
        "orchestration_sha": "orchestration-sha",
        "orchestration_branch": branch_name,
        "retention_profile": "derived-only",
        "derived_output_validation_status": "PASS",
        "drive_remote_verification": "PASS",
    }), encoding="utf-8")
    (artifact / "derived-output-validation.json").write_text(
        json.dumps({"status": "PASS"}), encoding="utf-8"
    )
    (artifact / "download-manifest.json").write_text(
        json.dumps({"source_sha256": sha}), encoding="utf-8"
    )
    (artifact / "drive-retention-receipt.json").write_text(
        json.dumps({"remote_verification": "PASS"}), encoding="utf-8"
    )
    (artifact / "product-run-diagnostics.json").write_text(json.dumps({
        "step_outcomes": {"download": "success", "aoi_preflight": "success", "reader": "success"}
    }), encoding="utf-8")
    (cleanup / "local-cleanup-receipt.json").write_text(
        json.dumps({"remote_retention_verification": "PASS", "source_file_sha256": sha}),
        encoding="utf-8",
    )
    (cleanup / "drive-cleanup-upload-receipt.json").write_text(
        json.dumps({"remote_verification": "PASS"}), encoding="utf-8"
    )
    return manifest, product_root, cleanup_root


def test_complete_green_product_receipts_do_not_enter_retry_matrix(tmp_path):
    manifest, product_root, cleanup_root = _write_valid_checkpoint(tmp_path, branch_name="main")

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["products_complete"] == 1
    assert result["retry_count"] == 0
    assert result["retry_matrix"] == []
    assert result["decisions"] == [{
        "product_id": "GOFF-001",
        "granule_name": "NISAR_L2_PR_GOFF_TEST_PRODUCT",
        "status": "PASS",
        "terminal_reason": None,
        "reasons": [],
    }]


def test_branch_provenance_mismatch_after_successful_download_is_not_redownloaded(tmp_path):
    manifest, product_root, cleanup_root = _write_valid_checkpoint(
        tmp_path, branch_name="feat/final-aoi-science-integration"
    )
    manifest["orchestration_branch"] = "main"

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["retry_count"] == 0
    assert result["terminal_failure_count"] == 1
    decision = result["decisions"][0]
    assert decision["status"] == "TERMINAL_FAILURE"
    assert "META_ORCHESTRATION_BRANCH_INVALID" in decision["reasons"]
    assert decision["terminal_reason"] == "NON_RETRYABLE_POST_DOWNLOAD_CHECKPOINT_FAILURE"


def test_missing_processing_receipt_after_successful_download_is_not_redownloaded(tmp_path):
    manifest, product_root, cleanup_root = _inputs(
        tmp_path,
        {"download": "success", "aoi_preflight": "success", "reader": "skipped"},
    )

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["retry_count"] == 0
    assert result["terminal_failure_count"] == 1
    assert result["decisions"][0]["status"] == "TERMINAL_FAILURE"
    assert result["decisions"][0]["terminal_reason"] == (
        "NON_RETRYABLE_POST_DOWNLOAD_CHECKPOINT_FAILURE"
    )



def test_mixed_baseline_retries_only_the_product_with_a_missing_checkpoint(tmp_path):
    manifest, product_root, cleanup_root = _write_valid_checkpoint(tmp_path, branch_name="main")
    failed_product = {
        "id": "GUNW-002",
        "granule_name": "NISAR_L2_PR_GUNW_FAILED_PRODUCT",
        "product_type": "GUNW",
        "maturity": "PROVISIONAL",
        "expected_source_bytes": 200,
    }
    manifest["products"].append(failed_product)

    result = planner.plan(manifest, product_root, cleanup_root)

    assert result["products_expected"] == 2
    assert result["products_complete"] == 1
    assert result["retry_count"] == 1
    assert [product["id"] for product in result["retry_matrix"]] == ["GUNW-002"]
    decisions = {row["product_id"]: row for row in result["decisions"]}
    assert decisions["GOFF-001"]["status"] == "PASS"
    assert decisions["GOFF-001"]["reasons"] == []
    assert decisions["GUNW-002"]["status"] == "RETRY"
    assert "PRODUCT_PROCESSING_RECEIPT_MISSING" in decisions["GUNW-002"]["reasons"]


def test_workflow_retries_failed_product_matrix_before_dashboard_assembly() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "sarguardian-aoi-wkt-dashboard.yml").read_text(encoding="utf-8")
    worker = (root / ".github" / "workflows" / "sarguardian-aoi-product-worker.yml").read_text(encoding="utf-8")

    assert workflow.count("max-parallel: 15") == 2
    assert "  retry-plan:\n" in workflow
    assert "  retry-products:\n" in workflow
    assert "execution_label: retry-1" in workflow
    assert "needs: [manifest, process-products, retry-plan, retry-products]" in workflow
    assert "needs: [report-running, manifest, process-products, retry-plan, retry-products, dashboard]" in workflow
    assert workflow.index("  retry-products:\n") < workflow.index("  dashboard:\n")
    assert "max_attempts=1" in worker
