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
    _verify_and_stage_product_results,
)
from process_gcov_job import write_web_preview
from river_shift.raster_io import validate_gcov_series


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
    assert workflow.count('gdal_formats="$(gdalinfo --formats)"') == 8
    assert workflow.count("grep -Eiq '^[[:space:]]*HDF5[[:space:]]+-' <<< \"$gdal_formats\"") == 7


def test_retry_job_consumes_only_the_validated_cross_job_matrix():
    repository_root = Path(__file__).resolve().parents[3]
    workflow = (repository_root / ".github" / "workflows" / "river-shift-gcov-process.yml").read_text(encoding="utf-8")
    retry_dispatch = workflow.split("\n  retry_dispatch:\n", 1)[1].split("\n  retry:\n", 1)[0]
    retry_job = workflow.split("\n  retry:\n", 1)[1].split("\n  retry_prepare_2:\n", 1)[0]

    assert "validate_retry_matrix.py" in retry_dispatch
    assert "RIVERSHIFT_EXPECTED_RETRY_ATTEMPT: \"1\"" in retry_dispatch
    assert "needs: [retry_prepare, retry_dispatch]" in retry_job
    assert "needs.retry_prepare.result == 'success'" in retry_job
    assert "needs.retry_dispatch.result == 'success'" in retry_job
    assert "needs.retry_prepare.outputs.retry_count != '0'" in retry_job
    assert "matrix: ${{ fromJSON(needs.retry_prepare.outputs.retry_matrix) }}" in retry_job
    assert "needs.retry_dispatch.outputs.retry_count" not in retry_job
    assert "fromJSON(needs.retry_dispatch.outputs.retry_matrix)" not in retry_job
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
    assert captured["retry_failure_count"] == "1"


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
    assert "validate_retry_matrix.py" in workflow
    assert "RIVERSHIFT_EXPECTED_RETRY_ATTEMPT:" in workflow
    assert "retry_prepare_2:" in workflow and "retry_prepare_3:" in workflow
    assert "retry_dispatch_2:" in workflow and "retry_dispatch_3:" in workflow
    assert "retry_2:" in workflow and "retry_3:" in workflow
    assert "RIVERSHIFT_RETRY_DISPATCH_STATUSES:" in workflow
    assert "needs.retry_dispatch.result" in workflow
    assert "needs.retry_dispatch_2.result" in workflow
    assert "needs.retry_dispatch_3.result" in workflow



def test_assembly_rebases_exporter_sidecar_after_product_artifact_import(tmp_path, monkeypatch):
    granule = "NISAR_L2_PR_GCOV_024_069_A_015_4005_DHDH_A_20260630T232208_20260630T232243_P05023_N_F_J_001"
    source_sha = "a" * 64
    raster_bytes = b"verified AOI COG payload"
    raster_sha = hashlib.sha256(raster_bytes).hexdigest()
    exporter_path = f"/home/runner/work/_temp/product-runner/rasters/{granule}.tif"

    artifact_root = tmp_path / "product-artifacts"
    product_dir = artifact_root / granule
    product_dir.mkdir(parents=True)
    (product_dir / f"{granule}.tif").write_bytes(raster_bytes)
    metadata = {
        "schema_version": 1,
        "source_granule_name": granule,
        "source_granule_names": [granule],
        "source_granule_sha256": [source_sha],
        "source_product_sha256": source_sha,
        "output_cog": exporter_path,
        "output_cog_sha256": raster_sha,
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "covariance_term": "HHHH",
        "bandwidth_mode": "4005",
        "polarization_code": "DHDH",
        "processing_type": "PR",
        "flight_direction": "ASCENDING",
        "relative_orbit": "069",
        "frame": "015",
        "crid": "P05023",
        "orbit_accuracy": "N",
        "frame_coverage": "FULL",
        "observation_source": "A",
    }
    (product_dir / f"{granule}.metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    receipt = {
        "granule_name": granule,
        "product": "GCOV",
        "maturity": "PROVISIONAL",
        "source_host": "nisar.asf.earthdatacloud.nasa.gov",
        "size_bytes": 123456,
        "sha256": source_sha,
        "downloaded": True,
    }
    (product_dir / f"{granule}.download.json").write_text(json.dumps(receipt), encoding="utf-8")
    inventory = {
        "product_file": f"{granule}.h5",
        "available_diagonal_terms": [{"frequency": "frequencyA", "term": "HHHH"}],
        "gdal_version": "test",
        "available_valid_sample_masks": [],
    }
    (product_dir / f"{granule}.gcov_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")

    required_files = [
        f"{granule}.tif",
        f"{granule}.metadata.json",
        f"{granule}.download.json",
        f"{granule}.gcov_inventory.json",
    ]
    files = [
        {
            "name": filename,
            "sha256": hashlib.sha256((product_dir / filename).read_bytes()).hexdigest(),
        }
        for filename in required_files
    ]
    (product_dir / "worker-result.json").write_text(json.dumps({
        "schema_version": 1,
        "status": "PASS",
        "job_id": "job-provenance-rebase",
        "request_fingerprint": "f" * 64,
        "granule_name": granule,
        "acquisition_date": "2026-06-30",
        "source_sha256": source_sha,
        "files": files,
    }), encoding="utf-8")

    retry_root = tmp_path / "retry-product-artifacts"
    retry_root.mkdir()
    monkeypatch.setenv("RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR", str(retry_root))
    monkeypatch.setattr(batch_module, "_log_worker_stage", lambda *_args, **_kwargs: None)
    prepared = {
        "job_id": "job-provenance-rebase",
        "request_fingerprint": "f" * 64,
        "selected_product_names": [granule],
        "date_by_name": {granule: "2026-06-30"},
        "products_by_date": {"2026-06-30": [granule]},
        "request": {
            "maturity": "PROVISIONAL",
            "frequency": "frequencyA",
            "term": "HHHH",
        },
    }
    work_dir = tmp_path / "assembly"
    date_rasters, _ = _verify_and_stage_product_results(prepared, artifact_root, work_dir)
    staged_raster = date_rasters["2026-06-30"][0]
    staged_metadata = json.loads(staged_raster.with_suffix(".metadata.json").read_text(encoding="utf-8"))

    assert staged_metadata["exporter_output_cog"] == exporter_path
    assert staged_metadata["output_cog"] == str(staged_raster.resolve())
    assert staged_metadata["output_cog_sha256"] == raster_sha
    records, complete = validate_gcov_series(
        {"2026-06-30": str(staged_raster)},
        maturity="PROVISIONAL",
        frequency="frequencyA",
        term="HHHH",
    )
    assert complete is True
    assert len(records) == 1


def test_assembly_rejects_artifact_when_exporter_cog_checksum_does_not_match(tmp_path, monkeypatch):
    granule = "NISAR_L2_PR_GCOV_024_069_A_015_4005_DHDH_A_20260630T232208_20260630T232243_P05023_N_F_J_001"
    source_sha = "b" * 64
    artifact_root = tmp_path / "product-artifacts"
    product_dir = artifact_root / granule
    product_dir.mkdir(parents=True)
    raster_bytes = b"tampered COG payload"
    (product_dir / f"{granule}.tif").write_bytes(raster_bytes)
    raster_sha = hashlib.sha256(raster_bytes).hexdigest()
    metadata = {
        "source_granule_name": granule,
        "source_product_sha256": source_sha,
        "output_cog": "/ephemeral/product-runner/scene.tif",
        "output_cog_sha256": "c" * 64,
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "covariance_term": "HHHH",
        "bandwidth_mode": "4005",
        "polarization_code": "DHDH",
        "processing_type": "PR",
        "flight_direction": "ASCENDING",
        "relative_orbit": "069",
        "frame": "015",
        "crid": "P05023",
        "orbit_accuracy": "N",
        "frame_coverage": "FULL",
        "observation_source": "A",
    }
    (product_dir / f"{granule}.metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    receipt = {
        "granule_name": granule,
        "product": "GCOV",
        "maturity": "PROVISIONAL",
        "source_host": "nisar.asf.earthdatacloud.nasa.gov",
        "size_bytes": 123456,
        "sha256": source_sha,
        "downloaded": True,
    }
    (product_dir / f"{granule}.download.json").write_text(json.dumps(receipt), encoding="utf-8")
    inventory = {
        "product_file": f"{granule}.h5",
        "available_diagonal_terms": [{"frequency": "frequencyA", "term": "HHHH"}],
        "gdal_version": "test",
        "available_valid_sample_masks": [],
    }
    (product_dir / f"{granule}.gcov_inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    required_files = [
        f"{granule}.tif",
        f"{granule}.metadata.json",
        f"{granule}.download.json",
        f"{granule}.gcov_inventory.json",
    ]
    files = [
        {"name": filename, "sha256": hashlib.sha256((product_dir / filename).read_bytes()).hexdigest()}
        for filename in required_files
    ]
    (product_dir / "worker-result.json").write_text(json.dumps({
        "status": "PASS",
        "job_id": "job-bad-provenance",
        "request_fingerprint": "e" * 64,
        "granule_name": granule,
        "acquisition_date": "2026-06-30",
        "source_sha256": source_sha,
        "files": files,
    }), encoding="utf-8")
    retry_root = tmp_path / "retry-product-artifacts"
    retry_root.mkdir()
    monkeypatch.setenv("RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR", str(retry_root))
    monkeypatch.setattr(batch_module, "_log_worker_stage", lambda *_args, **_kwargs: None)
    prepared = {
        "job_id": "job-bad-provenance",
        "request_fingerprint": "e" * 64,
        "selected_product_names": [granule],
        "date_by_name": {granule: "2026-06-30"},
        "products_by_date": {"2026-06-30": [granule]},
        "request": {"maturity": "PROVISIONAL", "frequency": "frequencyA", "term": "HHHH"},
    }
    with pytest.raises(WorkerFailure, match="checksum or exporter path is invalid"):
        _verify_and_stage_product_results(prepared, artifact_root, tmp_path / "assembly")


@pytest.mark.parametrize("fail_drive_upload", [False, True])
def test_assembly_finalization_builds_manifest_before_private_drive_upload(
    tmp_path, monkeypatch, fail_drive_upload,
):
    job_id = "6668c93f-2188-408e-9f8d-f990acaf2035"
    fingerprint = "a" * 64
    runner_temp = tmp_path / "runner-temp"
    prepared_dir = tmp_path / "prepared"
    prepared_dir.mkdir()
    for filename in (
        "gcov-catalogue-manifest.json",
        "gcov-time-series-audit.json",
        "selected-observations.json",
    ):
        (prepared_dir / filename).write_text(json.dumps({"source": filename}), encoding="utf-8")

    dates = ["2026-06-30", "2026-07-12", "2026-07-24", "2026-08-17"]
    event_window = {
        "before": dates[0],
        "event_proximal_observation": dates[1],
        "post_one": dates[2],
        "post_two": dates[3],
    }
    granule = "NISAR_L2_PR_GCOV_024_069_A_015_4005_DHDH_A_20260630T232208_20260630T232243_P05023_N_F_J_001"
    prepared = {
        "job_id": job_id,
        "request_fingerprint": fingerprint,
        "selected_product_names": [granule],
        "batches": [[granule]],
        "dates": dates,
        "event_window": event_window,
        "selection": {"dates_selected": dates, "release_status": "PROVISIONAL"},
    }
    request = {
        "job_id": job_id,
        "fingerprint": fingerprint,
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "term": "HHHH",
        "threshold_method": "otsu",
        "threshold_db": None,
    }

    events = []

    class FakeCallbacks:
        def send(self, state, stage, **_kwargs):
            events.append(("callback", state, stage))

    def fake_verify_and_stage(_prepared, _products_dir, work_dir):
        raster_dir = work_dir / "source-rasters"
        raster_dir.mkdir(parents=True)
        date_rasters = {}
        for observed_date in dates:
            raster = raster_dir / f"{observed_date}.tif"
            raster.write_bytes(f"aligned source raster for {observed_date}".encode("utf-8"))
            date_rasters[observed_date] = [raster]
        provenance = work_dir / "source-granule-provenance.json"
        provenance.write_text(json.dumps({"granules": []}), encoding="utf-8")
        (work_dir / "raw").mkdir()
        return date_rasters, provenance

    def fake_run_step(stage, command, *, context=None):
        del stage, context
        script = Path(command[1]).name
        output_dir = Path(command[command.index("--out-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        if script == "run_water_timeseries.py":
            filename = "river_shift_timeseries.json"
            payload = {"quality": {"warnings": []}, "method": {"threshold_db": -12.0}}
        elif script in {"run_flood_analysis.py", "run_morphology_analysis.py"}:
            filename = "river_shift_result.json"
            payload = {"quality": {"status": "PASS"}, "metrics": {}}
            import numpy as np
            import rasterio
            from rasterio.transform import from_origin

            def write_test_mask(name, positive_cell):
                values = np.zeros((4, 4), dtype=np.uint8)
                values[positive_cell] = 1
                with rasterio.open(
                    output_dir / name,
                    "w",
                    driver="GTiff",
                    height=4,
                    width=4,
                    count=1,
                    dtype="uint8",
                    crs="EPSG:32646",
                    transform=from_origin(500000, 2500000, 10, 10),
                ) as target:
                    target.write(values, 1)

            if script == "run_flood_analysis.py":
                write_test_mask("newly_water_covered_mask.tif", (2, 2))
            else:
                write_test_mask("erosion_candidate_mask.tif", (0, 0))
                write_test_mask("deposition_candidate_mask.tif", (3, 3))
        else:
            raise AssertionError(f"Unexpected assembly processing script: {script}")
        (output_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def fake_create_web_previews(work_dir, *_args):
        preview = work_dir / "outputs" / "map" / "river_change_candidates_preview.geojson"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
        return [{
            "path": preview.relative_to(work_dir).as_posix(),
            "sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
        }]

    def fake_upload_validated_results(work_dir):
        events.append(("upload", "START"))
        manifest_path = work_dir / "result-manifest.json"
        assert manifest_path.is_file(), "Drive upload must never start before the manifest exists."
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = manifest["validated_outputs"]
        assert outputs, "The package must contain validated outputs before Drive publication."
        receipts = []
        for index, output in enumerate(outputs, start=1):
            path = work_dir / output["path"]
            assert path.is_file()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == output["sha256"]
            receipts.append({
                "path": output["path"],
                "bytes": path.stat().st_size,
                "drive_file_id": f"private-drive-file-{index}",
            })
        if fail_drive_upload:
            raise batch_module.DriveUploadError("simulated remote upload failure")
        manifest["storage_verification"] = {"receipts": receipts}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        events.append(("upload", "PASS"))
        return {
            "status": "PASS",
            "receipts": receipts,
            "retained_bytes": sum(receipt["bytes"] for receipt in receipts),
        }

    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("RIVERSHIFT_PREPARED_DIR", str(prepared_dir))
    monkeypatch.setenv("RIVERSHIFT_PRODUCT_ARTIFACTS_DIR", str(tmp_path / "product-artifacts"))
    monkeypatch.setenv("RIVERSHIFT_JOB_ID", job_id)
    monkeypatch.setattr(batch_module, "_ensure_credentials", lambda: None)
    monkeypatch.setattr(batch_module, "_verify_and_stage_product_results", fake_verify_and_stage)
    monkeypatch.setattr(batch_module, "_co_register", lambda path, _reference, *, is_reference: path)
    monkeypatch.setattr(batch_module, "require_worker_source_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch_module, "run_step", fake_run_step)
    monkeypatch.setattr(batch_module, "create_web_previews", fake_create_web_previews)
    monkeypatch.setattr(batch_module, "upload_validated_results", fake_upload_validated_results)

    def capture_stage(stage, status, **_details):
        events.append(("log", stage, status))

    monkeypatch.setattr(batch_module, "_log_worker_stage", capture_stage)

    if fail_drive_upload:
        with pytest.raises(WorkerFailure, match="Google Drive result publication failed") as error:
            batch_module._assemble_job(request, prepared, FakeCallbacks())
        assert error.value.code == "PRIVATE_STORAGE_PUBLICATION_FAILED"
        assert ("log", "private_result_publication", "FAIL") in events
        assert ("upload", "PASS") not in events
    else:
        summary, artifacts = batch_module._assemble_job(request, prepared, FakeCallbacks())
        assert summary["processing_status"] == "PASS"
        assert summary["release_status"] == "PROVISIONAL"
        assert artifacts
        assert all(item.get("drive_file_id") for item in artifacts)
        assert ("log", "private_result_publication", "PASS") in events
        assert ("upload", "PASS") in events

    package_pass = events.index(("log", "result_package_assembly", "PASS"))
    publication_callback = events.index(("callback", "running", "private_result_publication"))
    publication_start = events.index(("log", "private_result_publication", "START"))
    upload_start = events.index(("upload", "START"))
    assert package_pass < publication_callback < publication_start < upload_start
    assert ("callback", "running", "result_package_assembly") in events



def test_retry_wave_matrix_uses_wave_specific_attempt_and_batch_identity():
    first = _retry_matrix([{"granule_name": "NISAR_L2_PR_GCOV_025", "acquisition_date": "2026-07-12"}])
    second = _retry_matrix([{"granule_name": "NISAR_L2_PR_GCOV_025", "acquisition_date": "2026-07-12"}], retry_attempt=2)
    third = _retry_matrix([{"granule_name": "NISAR_L2_PR_GCOV_025", "acquisition_date": "2026-07-12"}], retry_attempt=3)

    assert first["include"][0]["retry_attempt"] == 1
    assert second["include"][0]["retry_attempt"] == 2
    assert third["include"][0]["retry_attempt"] == 3
    assert [first["include"][0]["batch_number"], second["include"][0]["batch_number"], third["include"][0]["batch_number"]] == [5, 6, 7]


def test_retry_wave_queues_only_products_still_unverified_after_previous_wave(tmp_path):
    recovered = "NISAR_L2_PR_GCOV_025"
    still_failed = "NISAR_L2_PR_GCOV_026"
    prepared = {
        "job_id": "job-multiwave",
        "request_fingerprint": "f" * 64,
        "selected_product_names": [recovered, still_failed],
        "date_by_name": {recovered: "2026-07-12", still_failed: "2026-07-24"},
    }
    first_dir = tmp_path / "first"
    retry_dir = tmp_path / "retry"
    for name, observed_date in ((recovered, "2026-07-12"), (still_failed, "2026-07-24")):
        product_dir = first_dir / name
        product_dir.mkdir(parents=True)
        (product_dir / "worker-result.json").write_text(json.dumps({
            "status": "FAIL",
            "job_id": "job-multiwave",
            "request_fingerprint": "f" * 64,
            "granule_name": name,
            "acquisition_date": observed_date,
            "error_code": "DOWNLOAD_FAILED",
            "files": [],
        }), encoding="utf-8")

    recovered_dir = retry_dir / "wave-1" / recovered
    recovered_dir.mkdir(parents=True)
    required = [
        f"{recovered}.tif",
        f"{recovered}.metadata.json",
        f"{recovered}.download.json",
        f"{recovered}.gcov_inventory.json",
    ]
    files = []
    for filename in required:
        payload = filename.encode("utf-8")
        (recovered_dir / filename).write_bytes(payload)
        files.append({"name": filename, "sha256": hashlib.sha256(payload).hexdigest()})
    (recovered_dir / "worker-result.json").write_text(json.dumps({
        "status": "PASS",
        "job_id": "job-multiwave",
        "request_fingerprint": "f" * 64,
        "granule_name": recovered,
        "acquisition_date": "2026-07-12",
        "retry_attempt": 1,
        "files": files,
    }), encoding="utf-8")

    failed_dir = retry_dir / "wave-1" / still_failed
    failed_dir.mkdir(parents=True)
    (failed_dir / "worker-result.json").write_text(json.dumps({
        "status": "FAIL",
        "job_id": "job-multiwave",
        "request_fingerprint": "f" * 64,
        "granule_name": still_failed,
        "acquisition_date": "2026-07-24",
        "retry_attempt": 1,
        "error_code": "EARTHDATA_NETWORK_UNREACHABLE",
        "files": [],
    }), encoding="utf-8")

    previous = batch_module._load_product_results(retry_dir)
    queued = _select_retry_rows(
        prepared,
        batch_module._load_product_results(first_dir),
        first_dir,
        previous_retry_results=previous,
        previous_retry_dir=retry_dir,
    )

    assert [row["granule_name"] for row in queued] == [still_failed]
    assert queued[0]["previous_retry_failure"] == "EARTHDATA_NETWORK_UNREACHABLE"
    assert queued[0]["previous_retry_attempt"] == 1
    wave_two = _retry_matrix(queued, retry_attempt=2)
    assert wave_two["include"][0]["retry_attempt"] == 2
