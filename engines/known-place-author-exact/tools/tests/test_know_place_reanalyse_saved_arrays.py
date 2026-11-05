from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from tools.know_place.goff_io import GoffReadError
from tools.know_place.reanalyse_saved_arrays import reanalyse_saved_arrays

PAIRS = (
    ("2026-06-20", "2026-07-02", 12),
    ("2026-07-02", "2026-07-14", 12),
    ("2026-07-14", "2026-07-26", 12),
    ("2026-07-26", "2026-08-19", 24),
    ("2026-08-19", "2026-08-31", 12),
)


def _make_report_bundle(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    h = w = 15
    east = np.ones((h, w), dtype=np.float32)
    north = np.zeros((h, w), dtype=np.float32)
    mag = np.ones((h, w), dtype=np.float32)
    valid = np.ones((h, w), dtype=np.uint8)
    box = np.ones((h, w), dtype=np.uint8)
    crown = np.zeros((h, w), dtype=np.uint8)
    crown[5:10, 5:10] = 1
    x = np.arange(w, dtype=np.float64) * 80
    y = np.arange(h, dtype=np.float64) * 80

    rows = []
    for start, end, days in PAIRS:
        name = f"{start.replace('-', '')}__{end.replace('-', '')}_diagnostic_arrays.npz"
        path = root / name
        np.savez_compressed(
            path,
            east_m=east,
            north_m=north,
            horizontal_magnitude_m=mag,
            directional_coherence_R=np.full((h, w), 0.5, dtype=np.float32),
            valid_mask=valid,
            reference_box_mask=box,
            crown_mask=crown,
            x_coordinates_m=x,
            y_coordinates_m=y,
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({
            "pair": f"{start} -> {end}",
            "reference_date": start,
            "secondary_date": end,
            "interval_days": days,
            "status": "METRICS_COMPUTED",
            "granule_name": f"synthetic-{start}-{end}",
            "source_sha256": "a" * 64,
            "diagnostic_arrays_file": name,
            "diagnostic_arrays_sha256": digest,
            "coherence_policy": {"minimum_valid_direction_vectors_per_window": 25},
            "crown_statistics": {
                "crown_median_horizontal_magnitude_m": 1.0,
                "crown_mean_vector_magnitude_m": 1.0,
                "crown_mean_vector_azimuth_deg_clockwise_from_north": 90.0,
                "crown_median_directional_coherence_R": 0.5,
            },
        })
    report = {
        "schema_version": "know-place-analysis-report/1.0",
        "structural_status": "PASS",
        "paper_reproduction_status": "BLOCKED",
        "run_scope": {"control_seed": 260826, "control_draws": 40},
        "products": rows,
    }
    report_path = root / "know-place-analysis-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path


def test_reanalyse_saved_arrays_recomputes_r_and_keeps_paper_parity_blocked(tmp_path):
    source_report = _make_report_bundle(tmp_path / "saved")
    out = tmp_path / "out" / "reanalysis.json"
    result = reanalyse_saved_arrays(
        source_report, tmp_path / "saved", out, source_run_id=12345,
    )
    assert result["status"] == "REANALYSIS_ONLY_DIAGNOSTIC_ARRAYS"
    assert result["source_run_id"] == "12345"
    assert len(result["products"]) == 5
    for pair in result["products"]:
        assert pair["reanalysed_primary_R_minimum_valid_neighbours"] == 1
        assert pair["crown_statistics_R_min1"]["crown_median_directional_coherence_R"] == pytest.approx(1.0)
        assert set(pair["coherence_sensitivity"]["thresholds"]) == {"1", "5", "10", "15", "20", "25"}
        assert pair["unchanged_scalar_check"]["absolute_difference_magnitude_m"] == pytest.approx(0.0)
    assert result["paper_reproduction_status"].startswith("BLOCKED")
    assert result["hazard_detection_status"] == "NOT_EVALUATED"
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == result["status"]


def test_reanalyse_saved_arrays_fails_closed_when_npz_hash_changes(tmp_path):
    source_report = _make_report_bundle(tmp_path / "saved")
    original = json.loads(source_report.read_text(encoding="utf-8"))
    target = tmp_path / "saved" / original["products"][0]["diagnostic_arrays_file"]
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(GoffReadError, match="DIAGNOSTIC_ARRAYS_SHA256_MISMATCH"):
        reanalyse_saved_arrays(source_report, tmp_path / "saved", tmp_path / "out.json")
