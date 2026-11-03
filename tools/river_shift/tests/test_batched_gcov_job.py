from __future__ import annotations

import json
from pathlib import Path
import warnings

from pyproj import Transformer
from shapely.geometry import box, mapping

from batched_gcov_job import BATCH_SIZE, MAX_BATCHES, _write_batch_outputs
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
