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


def test_every_retry_wave_uses_a_fresh_runner_and_validated_matrix():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "\\" + "$" + "{{" not in workflow
    specs = [
        ("retry_prepare", "retry_dispatch", "retry", "retry_prepare_2"),
        ("retry_prepare_2", "retry_dispatch_2", "retry_2", "retry_prepare_3"),
        ("retry_prepare_3", "retry_dispatch_3", "retry_3", "retry_status"),
    ]
    for prepare_name, dispatch_name, retry_name, next_name in specs:
        prepare = _job_block(workflow, prepare_name, dispatch_name)
        dispatch = _job_block(workflow, dispatch_name, retry_name)
        retry = _job_block(workflow, retry_name, next_name)
        assert "RIVERSHIFT_RETRY_ATTEMPT:" in prepare
        assert "RIVERSHIFT_EXPECTED_RETRY_ATTEMPT:" in dispatch
        assert "validate_retry_matrix.py" in dispatch
        assert "if: >-" in retry and "!cancelled()" in retry
        assert "max-parallel: 15" in retry
        assert "RIVERSHIFT_RETRY_ATTEMPT: " + "$" + "{{ matrix.retry_attempt }}" in retry
        assert "RIVERSHIFT_PRODUCT_OUTPUT_DIR: product-output/wave-" + "$" + "{{ matrix.retry_attempt }}" in retry
        assert "rivershift-retry-wave-" + "$" + "{{ matrix.retry_attempt }}" + "-product-" in retry


def test_later_waves_run_even_when_previous_worker_failed_but_validation_passed():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    wave_two = _job_block(workflow, "retry_prepare_2", "retry_dispatch_2")
    wave_three = _job_block(workflow, "retry_prepare_3", "retry_dispatch_3")
    assert "needs: [retry_prepare, retry_dispatch, retry]" in wave_two
    assert "needs.retry_prepare.result == 'success'" in wave_two
    assert "needs.retry_dispatch.result == 'success'" in wave_two
    assert "needs: [retry_prepare_2, retry_dispatch_2, retry_2]" in wave_three
    assert "needs.retry_prepare_2.result == 'success'" in wave_three
    assert "needs.retry_dispatch_2.result == 'success'" in wave_three


def test_retry_status_reconciles_every_wave_and_assembly_waits_for_it():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    retry_status = _job_block(workflow, "retry_status", "assemble")
    for name in ("retry_dispatch", "retry_dispatch_2", "retry_dispatch_3", "retry_prepare_2", "retry_prepare_3", "retry_2", "retry_3"):
        assert name in retry_status
    assert "RIVERSHIFT_RETRY_DISPATCH_STATUSES:" in retry_status
    assert "RIVERSHIFT_RETRY_PREPARE_STATUSES:" in retry_status
    assert "RIVERSHIFT_RETRY_COUNTS:" in retry_status
    assert "pattern: rivershift-retry-wave-*-product-*" in retry_status
    assert "if: always()" in retry_status
    assemble = workflow[workflow.find("  assemble:"):]
    assert "needs.retry_status.result == 'success'" in assemble


def test_initial_retry_worker_is_not_suppressed_by_failed_first_attempt_ancestors():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    retry = _job_block(workflow, "retry", "retry_prepare_2")
    assert "needs: [retry_prepare, retry_dispatch]" in retry
    assert "!cancelled()" in retry
    assert "needs.retry_prepare.result == 'success'" in retry
    assert "needs.retry_dispatch.result == 'success'" in retry
    assert "needs.retry_prepare.outputs.retry_count != '0'" in retry
    assert "matrix: " + "$" + "{{ fromJSON(needs.retry_prepare.outputs.retry_matrix) }}" in retry