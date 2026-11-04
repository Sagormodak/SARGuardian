from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "river-shift-gcov-process.yml"


def _job_block(workflow: str, job_name: str, next_job: str) -> str:
    start_marker = f"  {job_name}:"
    end_marker = f"  {next_job}:"
    start = workflow.find(start_marker)
    end = workflow.find(end_marker, start + len(start_marker))
    assert start >= 0, f"Missing RiverShift job: {job_name}"
    assert end > start, f"Missing next job after {job_name}"
    return workflow[start:end]


def test_delayed_retry_worker_is_not_suppressed_by_failed_first_attempt_ancestors():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    retry = _job_block(workflow, "retry", "retry_status")

    # GitHub adds implicit success() unless a status-check function is explicit.
    # A failed first-attempt matrix member must not suppress its own delayed retry.
    assert "if: >-\n      ${{ !cancelled()" in retry
    assert "needs.retry_prepare.result == 'success'" in retry
    assert "needs.retry_dispatch.result == 'success'" in retry
    assert "needs.retry_prepare.outputs.retry_count != '0'" in retry
    assert "matrix: ${{ fromJSON(needs.retry_prepare.outputs.retry_matrix) }}" in retry


def test_retry_reconciliation_runs_after_retry_worker_failure_or_skip():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    retry_status = _job_block(workflow, "retry_status", "assemble")
    assert "if: always() && needs.retry_prepare.result == 'success'" in retry_status
    assert "needs.retry_dispatch.result" in retry_status


def test_science_assembly_requires_successful_retry_reconciliation():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assemble = workflow[workflow.find("  assemble:"):]
    assert "if: always()" in assemble
    assert "needs.retry_status.result == 'success'" in assemble
