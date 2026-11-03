from __future__ import annotations

import hashlib
import json
from pathlib import Path
import warnings

import pytest
from pyproj import Transformer
from shapely.geometry import box, mapping

import batched_gcov_job as batch_module
from batched_gcov_job import (
    BATCH_SIZE,
    MAX_BATCHES,
    WorkerFailure,
    _product_catalogue_path,
    _product_result_problem,
    _report_retry_wave,
    _retry_matrix,
    _run_product_worker,
    _select_retry_rows,
    _write_batch_outputs,
)
from process_gcov_job import write_web_preview


def _read_github_output(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    lines = iter(text.splitlines())
    for line in lines:
        if "<<" not in line:
            continue
        key, delimiter = line.split("<<", 1)
        payload = []
        for value in lines:
            if value == delimiter:
                break
            payload.append(value)
        values[key] = "\n".join(payload)
    return values


def test_batch_plan_is_sequential_barriers_of_at_most_15_products(tmp_path, monkeypatch):
    assert BATCH_SIZE == 15
    assert MAX_BATCHES == 4

    rows = [
        {"granule_name": f"NISAR_L2_PR_GCOV_{index:03d}_A_014_4005_DHDH_A_20260101T000000_20260101T000010_P05023_N_F_J_001",
         "acquisition_date": "2026-01-01"}
        for index in range(1, 34)
    ]
    batches = [rows[offset:offset + BATCH_SIZE] for offset in range(0, len(rows), BATCH_SIZE)]
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    _write_batch_outputs(batches, sequence=5, total_products=len(rows))
    result = _read_github_output(output)

    counts = [int(result[f"batch_{index}_count"]) for index in range(1, 5)]
    assert counts == [15, 15, 3, 0]
    assert int(result["batch_count"]) == 3
    assert int(result["selected_count"]) == 33
    assert int(result["callback_sequence"]) == 5

    for index, expected_count in enumerate(counts, start=1):
        matrix = json.loads(result[f"batch_{index}_matrix"])
        assert len(matrix["include"]) == expected_count
        assert all(row["batch_number"] == index for row in matrix["include"])
        assert all(row["batch_count"] == 3 for row in matrix["include"])
        assert all(row["total_products"] == 33 for row in matrix["include"])

    assert [row["product_index"] for row in json.loads(result["batch_1_matrix"])["include"]] == list(range(1, 16))
    assert [row["product_index"] for row in json.loads(result["batch_2_matrix"])["include"]] == list(range(16, 31))
    assert [row["product_index"] for row in json.loads(result["batch_3_matrix"])["include"]] == [31, 32, 33]


def test_preview_size_guard_keeps_largest_display_features_instead_of_failing(tmp_path):
    source = tmp_path / "dense-candidates.geojson"
    destination = tmp_path / "dense-candidates-preview.geojson"
    features = []
    # Build a dense but valid candidate layer whose full map payload exceeds
    # the web-display budget. The authoritative full GeoJSON remains untouched.
    for index in range(2400):
        column = index % 80
        row = index // 80
        west = 89.0 + column * 0.0015
        south = 24.0 + row * 0.0015
        geometry = box(west, south, west + 0.0008, south + 0.0008)
        features.append({
            "type": "Feature",
            "properties": {"candidate_id": f"candidate-{index:05d}", "evidence_note": "x" * 180},
            "geometry": mapping(geometry),
        })
    source.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    project = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True).transform
    unproject = Transformer.from_crs("EPSG:32645", "EPSG:4326", always_xy=True).transform
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*shapely.ops.transform.*", category=DeprecationWarning)
        preview = write_web_preview(
            source,
            destination,
            project,
            unproject,
            pixel_size_m=10.0,
            max_bytes=18_000,
        )

    encoded = destination.read_bytes()
    assert len(encoded) <= 18_000
    assert preview["river_shift_preview"]["status"] == "DISPLAY_ONLY"
    assert preview["river_shift_preview"]["features_omitted_for_size"] > 0
    assert 0 < len(preview["features"]) < len(features)
    assert len(json.loads(source.read_text(encoding="utf-8"))["features"]) == len(features)



def test_retry_matrix_is_one_delayed_wave_with_max_parallel_controlled_by_workflow():
    rows = [
        {"granule_name": f"granule-{index:02d}", "acquisition_date": "2026-01-01"}
        for index in range(1, 19)
    ]
    matrix = _retry_matrix(rows)
    assert len(matrix["include"]) == 18
    assert [row["product_index"] for row in matrix["include"]] == list(range(1, 19))
    assert all(row["retry_attempt"] == 1 for row in matrix["include"])
    assert all(row["batch_number"] == MAX_BATCHES + 1 for row in matrix["include"])
    assert all(row["batch_count"] == 1 for row in matrix["include"])


def test_failed_and_missing_products_are_queued_once_but_verified_passes_are_not(tmp_path):
    import hashlib

    prepared = {
        "job_id": "job-1",
        "request_fingerprint": "fingerprint-1",
        "selected_product_names": ["good-product-0001", "failed-product-0002", "missing-product-0003"],
        "date_by_name": {
            "good-product-0001": "2026-01-01",
            "failed-product-0002": "2026-01-02",
            "missing-product-0003": "2026-01-03",
        },
    }
    first_dir = tmp_path / "first"
    good_dir = first_dir / "good-product-0001"
    good_dir.mkdir(parents=True)
    required = [
        "good-product-0001.tif",
        "good-product-0001.metadata.json",
        "good-product-0001.download.json",
        "good-product-0001.gcov_inventory.json",
    ]
    good_files = []
    for filename in required:
        payload = filename.encode("utf-8")
        (good_dir / filename).write_bytes(payload)
        good_files.append({"name": filename, "sha256": hashlib.sha256(payload).hexdigest()})
    good = {
        "status": "PASS",
        "job_id": "job-1",
        "request_fingerprint": "fingerprint-1",
        "granule_name": "good-product-0001",
        "acquisition_date": "2026-01-01",
        "files": good_files,
    }
    failed = {
        "status": "FAIL",
        "job_id": "job-1",
        "request_fingerprint": "fingerprint-1",
        "granule_name": "failed-product-0002",
        "acquisition_date": "2026-01-02",
        "error_code": "DOWNLOAD_FAILED",
        "files": [],
    }
    results = {
        "good-product-0001": good,
        "failed-product-0002": failed,
    }

    queued = _select_retry_rows(prepared, results, first_dir)
    assert [row["granule_name"] for row in queued] == [
        "failed-product-0002",
        "missing-product-0003",
    ]
    assert _product_result_problem(
        prepared,
        {"granule_name": "good-product-0001", "acquisition_date": "2026-01-01"},
        good,
        first_dir,
    ) is None

def test_workflow_hdf5_checks_are_safe_with_pipefail():
    repository_root = Path(__file__).resolve().parents[3]
    workflow = (repository_root / ".github" / "workflows" / "river-shift-gcov-process.yml").read_text(encoding="utf-8")

    # All runner checks must capture gdalinfo output before grep. A grep -q
    # pipeline can terminate gdalinfo early and produce SIGPIPE (141) under
    # set -o pipefail even when GDAL has the HDF5 driver installed.
    assert "gdalinfo --formats | grep" not in workflow
    assert workflow.count('gdal_formats="$(gdalinfo --formats)"') == 6
    assert workflow.count("grep -Eiq '^[[:space:]]*HDF5[[:space:]]+-' <<< \"$gdal_formats\"") == 5


def test_retry_job_consumes_only_the_validated_cross_job_matrix():
    repository_root = Path(__file__).resolve().parents[3]
    workflow = (repository_root / ".github" / "workflows" / "river-shift-gcov-process.yml").read_text(encoding="utf-8")
    retry_dispatch = workflow.split("\n  retry_dispatch:\n", 1)[1].split("\n  retry:\n", 1)[0]
    retry_job = workflow.split("\n  retry:\n", 1)[1].split("\n  retry_status:\n", 1)[0]

    assert "RIVERSHIFT_RETRY_MATRIX_JSON:" in retry_dispatch
    assert "RIVERSHIFT_RETRY_COUNT:" in retry_dispatch
    assert "len(rows) != count" in retry_dispatch
    assert "needs.retry_dispatch.result == 'success'" in retry_job
    assert "needs.retry_dispatch.outputs.retry_count != '0'" in retry_job
    assert "matrix: ${{ fromJSON(needs.retry_dispatch.outputs.retry_matrix) }}" in retry_job
    assert "continue-on-error: true" not in retry_job

def test_product_catalogue_path_is_absolute_from_child_tools_working_directory(tmp_path, monkeypatch):
    tools_dir = tmp_path / "tools" / "river_shift"
    tools_dir.mkdir(parents=True)
    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir()
    catalogue = prepared_dir / "selected-catalogue.json"
    catalogue.write_text(json.dumps({"products": []}), encoding="utf-8")

    monkeypatch.chdir(tools_dir)
    resolved = _product_catalogue_path(prepared_dir)

    assert resolved.is_absolute()
    assert resolved == catalogue.resolve()
    assert resolved.is_file()


def test_product_worker_failure_receipt_returns_nonzero_and_uses_absolute_catalogue(tmp_path, monkeypatch):
    granule = "NISAR_L2_PR_GCOV_001"
    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir()
    fingerprint = "a" * 64
    (prepared_dir / "prepared.json").write_text(json.dumps({
        "job_id": "job-1",
        "request_fingerprint": fingerprint,
        "selected_product_names": [granule],
        "date_by_name": {granule: "2026-06-30"},
        "request": {
            "frequency": "frequencyA",
            "term": "HHHH",
            "maturity": "PROVISIONAL",
            "aoi_wkt": "POLYGON ((85 27, 85.01 27, 85.01 27.01, 85 27.01, 85 27))",
        },
    }), encoding="utf-8")
    (prepared_dir / "selected-catalogue.json").write_text(json.dumps({
        "products": [{"granule_name": granule}],
    }), encoding="utf-8")
    output_dir = tmp_path / "product-output"
    runner_temp = tmp_path / "runner-temp"

    environment = {
        "RIVERSHIFT_GRANULE_NAME": granule,
        "RIVERSHIFT_ACQUISITION_DATE": "2026-06-30",
        "RIVERSHIFT_BATCH_NUMBER": "1",
        "RIVERSHIFT_BATCH_COUNT": "1",
        "RIVERSHIFT_PRODUCT_INDEX": "1",
        "RIVERSHIFT_TOTAL_PRODUCTS": "1",
        "RIVERSHIFT_RETRY_ATTEMPT": "0",
        "RIVERSHIFT_PRODUCT_OUTPUT_DIR": str(output_dir),
        "RIVERSHIFT_PREPARED_DIR": str(prepared_dir),
        "RIVERSHIFT_JOB_ID": "job-1",
        "RIVERSHIFT_REQUEST_FINGERPRINT": fingerprint,
        "RUNNER_TEMP": str(runner_temp),
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(batch_module, "_configure_earthdata_credentials", lambda: None)
    monkeypatch.setattr(batch_module, "_log_worker_stage", lambda *_args, **_kwargs: None)

    seen_catalogue = {}

    def fail_download(stage, command, *, context=None):
        catalogue_arg = command[command.index("--catalogue") + 1]
        seen_catalogue["path"] = Path(catalogue_arg)
        raise WorkerFailure("SCIENCE_STEP_FAILED", "simulated child download failure")

    monkeypatch.setattr(batch_module, "run_step", fail_download)

    exit_code = _run_product_worker()

    assert seen_catalogue["path"].is_absolute()
    assert seen_catalogue["path"].is_file()
    assert exit_code == 1
    receipt = json.loads((output_dir / granule / "worker-result.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "FAIL"
    assert receipt["error_code"] == "SCIENCE_STEP_FAILED"


def test_retry_report_marks_failed_retry_as_terminal_and_returns_nonzero(tmp_path, monkeypatch):
    granule = "missing-product-0001"
    prepared_dir = tmp_path / "prepared"
    first_dir = tmp_path / "first-attempt"
    retry_dir = tmp_path / "retry-attempt"
    prepared_dir.mkdir()
    first_dir.mkdir()
    retry_dir.mkdir()
    (prepared_dir / "prepared.json").write_text(json.dumps({
        "job_id": "job-1",
        "request_fingerprint": "b" * 64,
        "selected_product_names": [granule],
        "date_by_name": {granule: "2026-07-12"},
    }), encoding="utf-8")
    for key, value in {
        "RIVERSHIFT_PREPARED_DIR": str(prepared_dir),
        "RIVERSHIFT_PRODUCT_ARTIFACTS_DIR": str(first_dir),
        "RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR": str(retry_dir),
        "RIVERSHIFT_CALLBACK_URL": "https://api.example.test",
        "RIVERSHIFT_CALLBACK_SEQUENCE": "6",
        "RIVERSHIFT_RETRY_DISPATCH_STATUS": "success",
    }.items():
        monkeypatch.setenv(key, value)

    captured = {}
    class FakeCallbacks:
        def __init__(self, job_id, fingerprint, callback_url, *, initial_sequence=0):
            self.sequence = initial_sequence
        def send(self, state, stage, *, result_summary=None, artifact_manifest=None, error_code=None, error_message=None):
            self.sequence += 1
            captured.update({"state": state, "stage": stage, "result_summary": result_summary, "error_code": error_code, "error_message": error_message})

    monkeypatch.setattr(batch_module, "JobCallbacks", FakeCallbacks)
    monkeypatch.setattr(batch_module, "_log_worker_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "_write_step_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "_write_output", lambda name, value: captured.__setitem__(name, value))

    with pytest.raises(WorkerFailure, match="delayed retry product"):
        _report_retry_wave()

    assert captured["state"] == "failed"
    assert captured["error_code"] == "PRODUCT_RETRY_FAILED"
    assert captured["result_summary"]["retry_failure_count"] == 1
    assert captured["callback_sequence"] == "7"


def test_retry_matrix_handoff_failure_posts_terminal_failure(tmp_path, monkeypatch):
    granule = "missing-product-0002"
    prepared_dir = tmp_path / "prepared"
    first_dir = tmp_path / "first"
    retry_dir = tmp_path / "retry"
    prepared_dir.mkdir()
    first_dir.mkdir()
    retry_dir.mkdir()
    (prepared_dir / "prepared.json").write_text(json.dumps({
        "job_id": "job-2",
        "request_fingerprint": "c" * 64,
        "selected_product_names": [granule],
        "date_by_name": {granule: "2026-08-01"},
    }), encoding="utf-8")
    for key, value in {
        "RIVERSHIFT_PREPARED_DIR": str(prepared_dir),
        "RIVERSHIFT_PRODUCT_ARTIFACTS_DIR": str(first_dir),
        "RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR": str(retry_dir),
        "RIVERSHIFT_CALLBACK_URL": "https://api.example.test",
        "RIVERSHIFT_CALLBACK_SEQUENCE": "4",
        "RIVERSHIFT_RETRY_DISPATCH_STATUS": "failure",
    }.items():
        monkeypatch.setenv(key, value)

    captured = {}
    class FakeCallbacks:
        def __init__(self, *_args, initial_sequence=0):
            self.sequence = initial_sequence
        def send(self, state, stage, **kwargs):
            self.sequence += 1
            captured.update({"state": state, "stage": stage, **kwargs})

    monkeypatch.setattr(batch_module, "JobCallbacks", FakeCallbacks)
    monkeypatch.setattr(batch_module, "_log_worker_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "_write_step_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "_write_output", lambda name, value: captured.__setitem__(name, value))

    with pytest.raises(WorkerFailure, match="retry matrix"):
        _report_retry_wave()

    assert captured["state"] == "failed"
    assert captured["error_code"] == "RETRY_MATRIX_HANDOFF_FAILED"
    assert captured["retry_failure_count"] == 1


def test_retry_report_with_no_retry_queue_stays_running(tmp_path, monkeypatch):
    granule = "verified-product-0001"
    prepared_dir = tmp_path / "prepared"
    first_dir = tmp_path / "first"
    retry_dir = tmp_path / "retry"
    prepared_dir.mkdir()
    (first_dir / granule).mkdir(parents=True)
    retry_dir.mkdir()
    required = [f"{granule}.tif", f"{granule}.metadata.json", f"{granule}.download.json", f"{granule}.gcov_inventory.json"]
    files = []
    for name in required:
        payload = name.encode("utf-8")
        (first_dir / granule / name).write_bytes(payload)
        files.append({"name": name, "sha256": hashlib.sha256(payload).hexdigest()})
    result = {
        "status": "PASS",
        "job_id": "job-3",
        "request_fingerprint": "d" * 64,
        "granule_name": granule,
        "acquisition_date": "2026-08-01",
        "files": files,
    }
    (first_dir / granule / "worker-result.json").write_text(json.dumps(result), encoding="utf-8")
    (prepared_dir / "prepared.json").write_text(json.dumps({
        "job_id": "job-3",
        "request_fingerprint": "d" * 64,
        "selected_product_names": [granule],
        "date_by_name": {granule: "2026-08-01"},
    }), encoding="utf-8")
    for key, value in {
        "RIVERSHIFT_PREPARED_DIR": str(prepared_dir),
        "RIVERSHIFT_PRODUCT_ARTIFACTS_DIR": str(first_dir),
        "RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR": str(retry_dir),
        "RIVERSHIFT_CALLBACK_URL": "https://api.example.test",
        "RIVERSHIFT_CALLBACK_SEQUENCE": "8",
        "RIVERSHIFT_RETRY_DISPATCH_STATUS": "success",
    }.items():
        monkeypatch.setenv(key, value)

    captured = {}
    class FakeCallbacks:
        def __init__(self, *_args, initial_sequence=0):
            self.sequence = initial_sequence
        def send(self, state, stage, *, result_summary=None, artifact_manifest=None, error_code=None, error_message=None):
            self.sequence += 1
            captured.update({"state": state, "stage": stage, "result_summary": result_summary})

    monkeypatch.setattr(batch_module, "JobCallbacks", FakeCallbacks)
    monkeypatch.setattr(batch_module, "_log_worker_stage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "_write_step_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "_write_output", lambda name, value: captured.__setitem__(name, value))

    _report_retry_wave()

    assert captured["state"] == "running"
    assert captured["result_summary"]["retry_count"] == 0
    assert captured["result_summary"]["retry_failure_count"] == 0


def test_workflow_does_not_mask_product_worker_failures_and_validates_retry_handoff():
    repository_root = Path(__file__).resolve().parents[3]
    workflow = (repository_root / ".github" / "workflows" / "river-shift-gcov-process.yml").read_text(encoding="utf-8")

    # Product-matrix failure must be visible; reconciliation jobs separately
    # preserve the ability to start later batches and the delayed retry wave.
    assert "continue-on-error: true\n    strategy:" not in workflow
    assert "retry_dispatch:" in workflow
    assert "RIVERSHIFT_RETRY_MATRIX_JSON:" in workflow
    assert "matrix_include_count=" in workflow
    assert "fromJSON(needs.retry_dispatch.outputs.retry_matrix)" in workflow
    expected_status_env = "RIVERSHIFT_RETRY_DISPATCH_STATUS: $" + "{{ needs.retry_dispatch.result }}"
    assert expected_status_env in workflow

