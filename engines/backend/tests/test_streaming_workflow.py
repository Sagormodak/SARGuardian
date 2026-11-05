from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "sarguardian-streaming-batch.yml"
PRODUCT_WORKER = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "sarguardian-product-worker.yml"


def test_aggregate_job_checks_out_backend_before_science_repository():
    text = WORKFLOW.read_text(encoding="utf-8")
    aggregate = text.split("  aggregate:\n", 1)[1]
    backend = aggregate.index("- name: Checkout backend aggregation tools")
    science = aggregate.index("- name: Checkout pinned science baseline")
    assert backend < science
    assert "path: science-source" in aggregate[science:science + 400]


def test_streaming_workflow_is_manual_to_avoid_unexpected_live_storage_use():
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = text.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in triggers
    assert "\n  push:" not in triggers
    assert "inputs.run_profile || 'validation-pilot'" in text
    assert "SAFE default is a 2-product pilot" in text
    assert "does not execute the full 33-product end-to-end science suite" in text
    assert "RUN_PROFILE_SELECTED=$RUN_PROFILE" in text
    assert "max-parallel: 1" in text


def test_raw_deletion_is_only_after_verified_drive_upload():
    text = PRODUCT_WORKER.read_text(encoding="utf-8")
    marker = "- name: Delete local raw/archive only after successful remote retention"
    section = text.split(marker, 1)[1].split("\n      - name:", 1)[0]
    assert "if: success()" in section
    assert "DRIVE_OUTPUTS_NOT_REMOTELY_VERIFIED" in text
    assert "FULL_LOSSLESS_ARCHIVE_NOT_FOUND_IN_DRIVE_RECEIPT" in text
    assert "REFUSING_RAW_DELETION_WITHOUT_REMOTE_VERIFICATION" in section
    assert "REFUSING_RAW_DELETION_WITHOUT_DERIVED_BASELINE_VALIDATION" in section
    assert "REMOTE_REQUIRED_DERIVED_OUTPUT_MISSING" in section


def test_product_run_diagnostics_are_explicitly_pre_cleanup():
    text = PRODUCT_WORKER.read_text(encoding="utf-8")
    assert "- name: Write a compact diagnostic receipt even when a product fails" in text
    assert "product-run-diagnostics.json" in text
    assert '"schema_version": "sarguardian-product-run-diagnostic/1.0"' in text
    assert "raw_hdf5_present_at_diagnostic_time" in text
    assert "if-no-files-found: error" in text


def test_quota_uses_actual_processed_upload_files_not_raw_estimates():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = text.split("  manifest:", 1)[1].split("  process-one:", 1)[0]
    process = PRODUCT_WORKER.read_text(encoding="utf-8")
    assert "preflight_drive_quota.py" not in text
    assert "expected_source_bytes" in manifest  # disk/download estimate only
    assert "Create a full-lossless retained HDF5 copy" in process
    assert "Upload validated per-product outputs to Drive with checksum verification" in process
    assert "default: derived-only" in text
    assert "if: env.RETENTION_PROFILE == 'full-lossless'" in process
    assert "derived-output-validation.json" in process
    uploader = (WORKFLOW.parents[2] / "tools" / "drive_resumable_upload.py").read_text(encoding="utf-8")
    assert "CURATED_UPLOAD_ACTUAL_BYTES" in uploader
    assert "DRIVE_NEW_BYTES_REQUIRED_ACTUAL" in uploader
    assert "DRIVE_ACTUAL_OUTPUT_QUOTA_CHECK=PASS" in uploader
    assert "DRIVE_QUOTA_INSUFFICIENT" in uploader


def test_cleanup_receipt_is_uploaded_and_aggregator_requires_it():
    text = WORKFLOW.read_text(encoding="utf-8")
    product = PRODUCT_WORKER.read_text(encoding="utf-8")
    combined = text + "\n" + product
    assert "LOCAL_CLEANUP_RECEIPT_GATE_FAILED" in combined
    assert "LOCAL_CLEANUP_RECEIPT_NOT_REMOTELY_VERIFIED" in combined
    assert "local-cleanup-receipt.json" in combined
    assert "drive-cleanup-upload-receipt.json" in combined
    assert 'pattern: sarguardian-cleanup-*' in text
    assert '--cleanup-artifact-root "$root/cleanup-artifacts"' in text


def test_download_reuses_the_pinned_source_acquisition_code_in_both_workflows():
    root = Path(__file__).resolve().parents[1]
    downloader = (root / "tools" / "download_nisar_product.py").read_text(encoding="utf-8")
    stream = WORKFLOW.read_text(encoding="utf-8")
    live = (root / ".github" / "workflows" / "sarguardian-live-validation.yml").read_text(encoding="utf-8")
    assert "src" in downloader and "nisar_acquisition.py" in downloader
    assert "def direct_product_url(" in downloader
    assert "def probe_direct_product(" in downloader
    assert "acquisition.build_session()" in downloader
    assert "download_exact_product_with_timeout(" in downloader
    assert "timeout=(connect_timeout_seconds, read_timeout_seconds)" in downloader
    assert "query_by_year(" not in downloader
    assert "earthaccess" not in downloader.lower()
    assert "uses: ./.github/workflows/sarguardian-product-worker.yml" in stream
    for workflow in (PRODUCT_WORKER.read_text(encoding="utf-8"), live):
        assert "python tools/download_nisar_product.py" in workflow
        assert '--science-root "$PWD/science-source" --aoi "$AOI_NAME"' in workflow


def test_granule_drive_uploads_are_scoped_to_a_unique_run_folder():
    root = Path(__file__).resolve().parents[1]
    uploader = (root / "tools" / "drive_resumable_upload.py").read_text(encoding="utf-8")
    assert 'names.extend(["Runs", version_tag])' in uploader
    for filename in (
        "sarguardian-product-worker.yml",
        "sarguardian-live-validation.yml",
        "sarguardian-retention-pilot.yml",
    ):
        workflow = (root / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        assert "DRIVE_VERSION_TAG: ${{ github.run_id }}-${{ github.run_attempt }}" in workflow
        assert '--version-tag "$DRIVE_VERSION_TAG"' in workflow

def test_inline_json_receipts_do_not_append_literal_backslash_n():
    text = WORKFLOW.read_text(encoding="utf-8")
    # A doubled escape writes the two characters "\\n" after the JSON document,
    # which Python's json.loads rejects as "Extra data".
    assert r'json.dumps(metadata, indent=2) + "\\n"' not in text
    assert r'json.dumps(meta,indent=2)+"\\n"' not in text
    assert r'json.dumps(record,indent=2)+"\\n"' not in text

def test_failed_download_diagnostics_are_preserved_for_aggregation():
    text = PRODUCT_WORKER.read_text(encoding="utf-8")
    diagnostic = text.split(
        "- name: Write a compact diagnostic receipt even when a product fails", 1
    )[1].split("\n      - name:", 1)[0]
    assert "DOWNLOAD_LOG: ${{ runner.temp }}/sarguardian-download-${{ inputs.product_id }}.log" in diagnostic
    assert '"DIRECT_PRODUCT_DIAGNOSTIC="' in diagnostic
    assert '"download_diagnostics": download_diagnostics' in diagnostic
    assert '"download_error_code": download_error_code' in diagnostic
    aggregator = (WORKFLOW.parents[2] / "tools" / "aggregate_streamed_outputs.py").read_text(encoding="utf-8")
    assert "read_product_diagnostic_context(artifact_dir)" in aggregator
    assert '"download_error_code": record.get("download_error_code")' in aggregator

def test_full_baseline_preflights_urgent_response_products_before_matrix_jobs():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = text.split("  manifest:\n", 1)[1].split("\n  process-one:", 1)[0]
    preflight = manifest.index("- name: Fail fast when a selected urgent-response baseline product is unavailable")
    preserve = manifest.index("- name: Preserve run manifest for aggregation")
    assert preserve < preflight
    assert "if: inputs.run_profile == 'full-source-baseline'" in manifest[preflight - 250:preflight + 150]
    assert "--probe-only" in manifest[preflight:]
    assert "ERROR=UR_BASELINE_SOURCE_UNAVAILABLE" in manifest[preflight:]
    assert "full-baseline processing stopped before any product downloads" in manifest[preflight:]

def test_download_step_captures_both_stdout_and_stderr_for_diagnostics():
    text = PRODUCT_WORKER.read_text(encoding="utf-8")
    download = text.split(
        "- name: Download exactly one raw NISAR granule", 1
    )[1].split("\n      - name:", 1)[0]
    assert '--out-dir "$RAW_DIR" 2>&1 | tee "$attempt_log"' in download
    assert "max_attempts=1" in download
    assert "DOWNLOAD_FAILURE_RETRYABLE=yes" in download
    assert "timeout-minutes: 90" in download
    assert 'ERROR=DIRECT_HTTPS_PRODUCT_PROBE_FAILED' in (WORKFLOW.parents[2] / "tools" / "download_nisar_product.py").read_text(encoding="utf-8")



def test_download_step_uses_single_attempt_before_targeted_retry_stage():
    text = PRODUCT_WORKER.read_text(encoding="utf-8")
    download = text.split(
        "- name: Download exactly one raw NISAR granule", 1
    )[1].split("\n      - name:", 1)[0]
    assert "max_attempts=1" in download
    assert "DOWNLOAD_FAILURE_RETRYABLE=yes" in download
    assert "if (( attempt >= max_attempts )); then" in download
    assert 'echo "DOWNLOAD_ATTEMPT=$attempt/$max_attempts"' in download
    assert "DOWNLOAD_ATTEMPTS_EXHAUSTED" in download
    assert "timeout-minutes: 90" in download


def test_urgent_response_preflight_uses_one_attempt_and_stops_before_downloads():
    text = WORKFLOW.read_text(encoding="utf-8")
    preflight = text.split(
        "- name: Fail fast when a selected urgent-response baseline product is unavailable", 1
    )[1].split("\n\n  process-one:", 1)[0]
    assert "DOWNLOAD_FAILURE_RETRYABLE=" in preflight
    assert "max_attempts = 1" in preflight
    assert "for attempt in range(1, max_attempts + 1)" in preflight
    assert "if not retryable or attempt >= max_attempts:" in preflight
    assert "ERROR=UR_BASELINE_SOURCE_UNAVAILABLE" in preflight


def test_full_baseline_can_resume_only_verified_prior_product_checkpoints():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "resume_from_run_id:" in text
    assert "Resolve a compatible run for automatic resume" in text
    assert "python tools/resolve_resume_run.py" in text
    assert "blank auto-detects the latest compatible failed full run" in text
    assert "continue-on-error: true" in text
    assert "permissions:\n  contents: read\n  actions: read" in text
    assert "Download previous run manifest for safe resume" in text
    assert "Download previous per-product checkpoints for safe resume" in text
    assert "RESUME_PRODUCTS_REUSED=" in text
    assert 'manifest["products_to_process"] = matrix_products' in text
    assert "Download prior per-granule checkpoints for resume" in text
    assert "Assemble complete product checkpoints for aggregation" in text
    assert "python tools/resume_streamed_run.py merge" in text
    assert "retention-days: 14" in text


def test_optional_earthdata_user_token_is_passed_to_preflight_and_product_jobs():
    text = WORKFLOW.read_text(encoding="utf-8")
    product = PRODUCT_WORKER.read_text(encoding="utf-8")
    assert text.count("EARTHDATA_TOKEN: ${{ secrets.EARTHDATA_TOKEN }}") + product.count("EARTHDATA_TOKEN: ${{ secrets.EARTHDATA_TOKEN }}") == 2
    downloader = (WORKFLOW.parents[2] / "tools" / "download_nisar_product.py").read_text(encoding="utf-8")
    assert 'os.environ.get("EARTHDATA_TOKEN", "").strip()' in downloader
    assert "auth_with_token(token)" in downloader
    assert "EARTHDATA_AUTH_MODE=pre_generated_user_token" in downloader
    assert "EARTHDATA_AUTH_MODE=username_password_token_exchange" in downloader



def test_full_baseline_uses_complete_science_suite_from_the_pinned_source_checkout():
    root = Path(__file__).resolve().parents[1]
    aggregator = (root / "tools" / "aggregate_streamed_outputs.py").read_text(encoding="utf-8")
    suite = (root / "tools" / "run_pinned_science_suite.py").read_text(encoding="utf-8")
    assert "from tools.run_pinned_science_suite import run_suite" in aggregator
    assert 'PINNED_SCIENCE_COMMIT = "ab547ecc82bcc4d6ccef545a59852536c2beacc6"' in suite
    assert '"raw_hdf5_used_by_supplementary_suite": False' in suite
    assert "result1_detectability_noise_gates" in suite
    assert "result2_track_sensitivity_and_dem_stencil_sweep" in suite
    assert "result3_impoundment_" in suite
    assert "result6_sentinel2_candidate_map" in suite
    plan_test = (root / "tests" / "test_run_pinned_science_suite.py").read_text(encoding="utf-8")
    assert 'not any(".h5" in " ".join(entry["argv"]).lower() for entry in plan)' in plan_test


def test_artifact_only_reassembly_reuses_existing_product_runs_without_source_downloads():
    root = Path(__file__).resolve().parents[1]
    replay = (root / ".github" / "workflows" / "sarguardian-reassemble-existing.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in replay
    assert "default: '39510497044'" in replay
    assert "default: '39524783921'" in replay
    assert "permissions:\n  contents: read\n  actions: read" in replay
    assert "validate_resume_compatibility(product, base)" in replay
    assert "REASSEMBLY_MANIFEST_COMPATIBILITY=PASS PRODUCTS=" in replay
    assert "pattern: sarguardian-granule-*" in replay
    assert "pattern: sarguardian-cleanup-*" in replay
    assert "Merge verified checkpoints without re-downloading source data" in replay
    assert "python tools/resume_streamed_run.py merge" in replay
    assert "python tools/aggregate_streamed_outputs.py" in replay
    assert "retention-days: 14" in replay
    assert "EARTHDATA_TOKEN" not in replay
    assert "download_nisar_product.py" not in replay


def test_candidate4_common_reference_uses_exact_pinned_pr_ur_stack():
    root = Path(__file__).resolve().parents[1]
    aggregator = (root / "tools" / "aggregate_streamed_outputs.py").read_text(encoding="utf-8")
    assert "select_candidate4_common_reference_rows(stats)" in aggregator
    assert '"product_families": {"PR": 16, "UR": 2}' in aggregator
    assert "Expected all 18 candidate-4 GOFF layer2 source products" in aggregator


def test_auto_resume_id_is_passed_from_manifest_job_to_aggregate_job():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = text.split("  manifest:", 1)[1].split("  process-one:", 1)[0]
    aggregate = text.split("  aggregate:", 1)[1]
    assert "resume_run_id: ${{ steps.resume.outputs.run_id }}" in manifest
    assert "resume_mode: ${{ steps.resume.outputs.mode }}" in manifest
    assert "needs.manifest.outputs.resume_run_id != ''" in aggregate
    assert aggregate.count("run-id: ${{ needs.manifest.outputs.resume_run_id }}") == 2
    assert "steps.resume.outputs.run_id" not in aggregate

def test_optional_checkpoint_downloads_do_not_abort_resume_aggregation():
    text = WORKFLOW.read_text(encoding="utf-8")
    optional_steps = (
        "Download current-run per-granule artifacts",
        "Download current-run post-cleanup evidence",
        "Download prior per-granule checkpoints for resume",
        "Download prior post-cleanup evidence for resume",
    )
    for name in optional_steps:
        section = text.split(f"- name: {name}", 1)[1].split("\n      - name:", 1)[0]
        assert "continue-on-error: true" in section, name

def test_failed_products_are_retried_and_receipts_gate_reassembly():
    stream = WORKFLOW.read_text(encoding="utf-8")
    worker = PRODUCT_WORKER.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/sarguardian-product-worker.yml" in stream
    assert "retry-plan:" in stream
    assert "retry-products:" in stream
    assert "preassembly-verify:" in stream
    assert "python tools/product_retry_gate.py plan-retries" in stream
    assert "python tools/product_retry_gate.py verify" in stream
    assert "PRODUCTS_SELECTED_FOR_RETRY=" in (
        (Path(__file__).resolve().parents[1] / "tools" / "product_retry_gate.py").read_text(encoding="utf-8")
    )
    aggregate = stream.split("  aggregate:\n", 1)[1]
    assert "needs.preassembly-verify.result == 'success'" in aggregate
    assert "Assemble complete product checkpoints for aggregation" in aggregate
    assert "continue-on-error: true" in worker
    assert worker.count("overwrite: true") == 2
    assert "Download first-attempt evidence for retry identity checks" in worker
    assert "RETRY_SOURCE_IDENTITY=PASS_SOURCE_SHA256_MATCH" in worker
    assert "ERROR=RETRY_SOURCE_BYTES_CHANGED" in worker
    assert "retry_upload_flags+=(--existing-files-are-new)" in worker
    assert "metadata_retry_flags+=(--existing-files-are-new)" in worker
    assert "cleanup_retry_flags+=(--existing-files-are-new)" in worker
    assert worker.count("retry_upload_flags+=(--replace-existing-retry-sidecars)") == 1
    assert worker.count("metadata_retry_flags+=(--replace-existing-retry-sidecars)") == 1
    assert worker.count("cleanup_retry_flags+=(--replace-existing-retry-sidecars)") == 1
    assert "Preserve retry diagnostics without replacing a prior checkpoint" in worker
    assert "Preserve retry cleanup diagnostics without replacing a prior checkpoint" in worker
    assert "steps.drive.outcome != 'success'" in worker
    assert "steps.cleanup.outcome != 'success'" in worker
    ci = (WORKFLOW.parent / "sarguardian-retention-ci.yml").read_text(encoding="utf-8")
    assert ".github/workflows/sarguardian-product-worker.yml" in ci



def test_zero_product_resume_uses_a_successful_noop_worker_without_polluting_receipt_plan():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = text.split("  manifest:\n", 1)[1].split("  process-one:\n", 1)[0]
    retry_plan = text.split("  retry-plan:\n", 1)[1].split("  retry-products:\n", 1)[0]
    worker = PRODUCT_WORKER.read_text(encoding="utf-8")

    # The actual product list stays empty for receipt validation and retry planning.
    assert "matrix: ${{ steps.make.outputs.matrix }}" in manifest
    assert 'compact = json.dumps(matrix, separators=(",", ":"))' in manifest
    assert "worker_matrix = matrix or [" in manifest
    assert '"id": "__NO_PRODUCTS__"' in manifest
    assert 'gh.write("matrix=" + compact' in manifest
    assert 'gh.write("worker_matrix=" + compact_worker' in manifest
    assert "include: ${{ fromJSON(needs.manifest.outputs.worker_matrix) }}" in text
    assert "EXPECTED_PRODUCTS_JSON: ${{ needs.manifest.outputs.matrix }}" in retry_plan

    # The sentinel completes a successful no-op job and never starts the downloader.
    assert "no-product-work:" in worker
    assert "if: inputs.product_id == '__NO_PRODUCTS__'" in worker
    assert "if: inputs.product_id != '__NO_PRODUCTS__'" in worker
    assert "NO_PRODUCT_WORK_REQUIRED=true" in worker
    assert "ALL_SELECTED_PRODUCTS_REUSED=true" in worker
