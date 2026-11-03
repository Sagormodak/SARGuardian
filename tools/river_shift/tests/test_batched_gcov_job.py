from __future__ import annotations

import json
from pathlib import Path
import warnings

from pyproj import Transformer
from shapely.geometry import box, mapping

from batched_gcov_job import (
    BATCH_SIZE,
    MAX_BATCHES,
    _product_result_problem,
    _retry_matrix,
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


def test_retry_job_is_not_gated_by_the_retry_count_output():
    repository_root = Path(__file__).resolve().parents[3]
    workflow = (repository_root / ".github" / "workflows" / "river-shift-gcov-process.yml").read_text(encoding="utf-8")
    retry_job = workflow.split("\n  retry:\n", 1)[1].split("\n  retry_status:\n", 1)[0]

    # The matrix itself is the authoritative queue. Do not suppress the retry
    # job based on a second scalar output that can diverge from that matrix.
    assert "if: needs.retry_prepare.result == 'success'" in retry_job
    assert "retry_count !=" not in retry_job
    assert "matrix: ${{ fromJSON(needs.retry_prepare.outputs.retry_matrix) }}" in retry_job

