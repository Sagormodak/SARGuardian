from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
from pyproj import Transformer

from tools.know_place.analyze import analyze_config
from tools.know_place.geometry import parse_polygon_wkt


BOX_WKT = (
    "POLYGON ((85.500000 28.265000, 85.565000 28.265000, "
    "85.565000 28.318000, 85.500000 28.318000, 85.500000 28.265000))"
)
CROWN_WKT = (
    "POLYGON ((85.525000 28.285000, 85.540000 28.285000, "
    "85.540000 28.297000, 85.525000 28.297000, 85.525000 28.285000))"
)
PAIRS = (
    ("2026-06-20", "2026-07-02"),
    ("2026-07-02", "2026-07-14"),
    ("2026-07-14", "2026-07-26"),
    ("2026-07-26", "2026-08-19"),
    ("2026-08-19", "2026-08-31"),
)
BASE = "/science/LSAR/GOFF"


def _date_stamp(value: str, *, second: int = 0) -> str:
    return value.replace("-", "") + f"T0000{second:02d}00"


def _write_goff(path: Path, *, x: np.ndarray, y: np.ndarray, east_motion: float):
    xx, yy = np.meshgrid(x, y)
    raw_at = np.zeros(xx.shape, dtype=np.float32)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    crown_ring = parse_polygon_wkt(CROWN_WKT)
    px, py = transformer.transform(
        [p[0] for p in crown_ring], [p[1] for p in crown_ring]
    )
    inside = np.zeros(xx.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(zip(px[:-1], py[:-1]), zip(px[1:], py[1:])):
        crosses = (y1 > yy) != (y2 > yy)
        if y2 != y1:
            inside ^= crosses & (xx < (x2 - x1) * (yy - y1) / (y2 - y1) + x1)
    raw_at[inside] = east_motion
    # One valid-in-box, outside-crown gross blunder verifies reject-not-clip.
    box_ring = parse_polygon_wkt(BOX_WKT)
    bx, by = transformer.transform(
        [p[0] for p in box_ring], [p[1] for p in box_ring]
    )
    inside_box = np.zeros(xx.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(zip(bx[:-1], by[:-1]), zip(bx[1:], by[1:])):
        crosses = (y1 > yy) != (y2 > yy)
        if y2 != y1:
            inside_box ^= crosses & (xx < (x2 - x1) * (yy - y1) / (y2 - y1) + x1)
    outside_crown = np.argwhere(inside_box & ~inside)
    assert outside_crown.size, "synthetic reference box must have background cells"
    bad_row, bad_col = outside_crown[0]
    raw_at[bad_row, bad_col] = 20.0
    shape = raw_at.shape
    layer_path = f"{BASE}/grids/frequencyA/pixelOffsets/HH/layer2"
    with h5py.File(path, "w") as handle:
        layer = handle.create_group(layer_path)
        for name, values, units in (
            ("alongTrackOffset", raw_at, "m"),
            ("slantRangeOffset", np.zeros(shape, dtype=np.float32), "m"),
            ("snr", np.full(shape, 6.0, dtype=np.float32), "1"),
            ("correlationSurfacePeak", np.full(shape, 0.8, dtype=np.float32), "1"),
        ):
            dataset = layer.create_dataset(name, data=values)
            dataset.attrs["units"] = units
            dataset.attrs["grid_mapping"] = "projection"
        layer.create_dataset("xCoordinates", data=x).attrs["units"] = "m"
        layer.create_dataset("yCoordinates", data=y).attrs["units"] = "m"
        projection = layer.create_dataset("projection", data=np.int32(32645))
        projection.attrs["epsg_code"] = 32645

        metadata = handle.create_group(f"{BASE}/metadata/radarGrid")
        metadata.create_dataset("xCoordinates", data=x)
        metadata.create_dataset("yCoordinates", data=y)
        metadata.create_dataset("heightAboveEllipsoid", data=np.array([4000.0, 6000.0]))
        cubes = {
            "incidenceAngle": (39.1, "degrees"),
            "losUnitVectorX": (0.2, "1"),
            "losUnitVectorY": (-0.3, "1"),
            "alongTrackUnitVectorX": (0.6, "1"),
            "alongTrackUnitVectorY": (0.8, "1"),
        }
        for name, (value, units) in cubes.items():
            cube = metadata.create_dataset(
                name, data=np.full((2, len(y), len(x)), value, dtype=np.float32)
            )
            cube.attrs["units"] = units
        geometry_projection = metadata.create_dataset("projection", data=np.int32(32645))
        geometry_projection.attrs["epsg_code"] = 32645


def _granule_name(start: str, end: str) -> str:
    return (
        "NISAR_L2_PR_GOFF_014_098_A_016_023_4000_SH_"
        f"{_date_stamp(start, second=0)}_{_date_stamp(start, second=30)}_"
        f"{_date_stamp(end, second=0)}_{_date_stamp(end, second=30)}_"
        "P05023_N_F_J_001.h5"
    )


def test_synthetic_five_pair_pipeline_writes_auditable_report_and_keeps_parity_blocked(tmp_path):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    box_ring = parse_polygon_wkt(BOX_WKT)
    box_x, box_y = transformer.transform(
        [p[0] for p in box_ring], [p[1] for p in box_ring]
    )
    x0 = np.floor(min(box_x) / 80.0) * 80.0 - 800.0
    x1 = np.ceil(max(box_x) / 80.0) * 80.0 + 800.0
    y0 = np.floor(min(box_y) / 80.0) * 80.0 - 800.0
    y1 = np.ceil(max(box_y) / 80.0) * 80.0 + 800.0
    x = np.arange(x0, x1 + 0.1, 80.0, dtype=np.float64)
    y = np.arange(y0, y1 + 0.1, 80.0, dtype=np.float64)

    manifest_products = []
    for start, end in PAIRS:
        path = tmp_path / _granule_name(start, end)
        _write_goff(path, x=x, y=y, east_motion=0.5)
        manifest_products.append({
            "path": path.name,
            "expected_granule_name": path.name,
            "catalog_maturity": "PROVISIONAL",
            "catalog_maturity_evidence": "synthetic fixture; not real ASF evidence",
        })
    config_path = tmp_path / "know-place-inputs.json"
    config_path.write_text(json.dumps({
        "schema_version": "know-place-analysis-inputs/1.0",
        "reference_box_wkt": BOX_WKT,
        "crown_wkt": CROWN_WKT,
        "crown_geometry_kind": "bounding-box-approximation",
        "crown_geometry_source": "synthetic test rectangle, not author-supplied geometry",
        "geometry_height_m": 5151.0,
        "control_seed": 260826,
        "control_draws": 20,
        "coherence_minimum_valid_cells": 1,
        "products": manifest_products,
    }, indent=2), encoding="utf-8")

    result = analyze_config(config_path, tmp_path / "out")
    report_path = tmp_path / "out" / "know-place-analysis-report.json"
    csv_path = tmp_path / "out" / "know-place-analysis-pairs.csv"
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert result["structural_status"] == "PASS"
    assert result["status"] == "SCIENTIFIC_METRICS_COMPUTED"
    assert saved["runtime_environment"]["packages"]["numpy"]
    assert saved["runtime_environment"]["packages"]["h5py"]
    assert saved["runtime_environment"]["packages"]["scipy"]
    assert result["paper_reproduction_status"] == "BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED"
    assert result["hazard_detection_status"] == "NOT_EVALUATED"
    assert len(saved["products"]) == 5
    for pair in saved["products"]:
        assert pair["status"] == "METRICS_COMPUTED"
        sensitivity = pair["directional_coherence_sensitivity"]
        assert sensitivity["primary_minimum_valid_neighbours"] == 1
        assert set(sensitivity["thresholds"]) == {"1", "5", "10", "15", "20", "25"}
        assert sensitivity["thresholds"]["1"]["crown_valid_centres"] >= sensitivity["thresholds"]["25"]["crown_valid_centres"]
        stats = pair["crown_statistics"]
        # ATU is (0.6, 0.8), SR is zero, so a 0.5 m AT shift yields 0.5 m
        # horizontal magnitude by construction; this is only a synthetic check.
        assert abs(stats["crown_median_horizontal_magnitude_m"] - 0.5) < 1e-6
        assert len(pair["source_sha256"]) == 64
        assert pair["quality_gate_counts"]["rejected_magnitude"] >= 1
        assert pair["diagnostic_arrays_file"].endswith(".npz")
        assert len(pair["exploratory_control_comparison"]["spatial_control_sample_sha256"]) == 64
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "crown_median_horizontal_magnitude_m" in csv_text
    assert "2026-07-26,2026-08-19" in csv_text


def test_cli_emits_path_free_failure_report_when_input_manifest_is_missing(tmp_path, capsys):
    from tools.know_place.analyze import main

    missing_config = tmp_path / "private" / "missing-inputs.json"
    output = tmp_path / "results"
    rc = main(["--config", str(missing_config), "--out", str(output)])
    assert rc == 2
    report_path = output / "know-place-analysis-report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "FAILED"
    assert report["structural_status"] == "FAIL"
    assert report["paper_reproduction_status"] == "BLOCKED_ANALYSIS_FAILED"
    assert report["hazard_detection_status"] == "NOT_EVALUATED"
    assert report["runtime_environment"]["python_version"]
    assert str(tmp_path) not in json.dumps(report)
    assert "KNOW_PLACE_ANALYSIS_STATUS=FAIL" in capsys.readouterr().out



def test_coherence_sensitivity_records_magnitude_window_and_valid_centre_counts():
    from tools.know_place.analyze import _coherence_sensitivity

    h = w = 15
    east = np.ones((h, w), dtype=float)
    north = np.zeros((h, w), dtype=float)
    valid = np.ones((h, w), dtype=bool)
    box = np.ones((h, w), dtype=bool)
    crown = np.zeros((h, w), dtype=bool)
    crown[5:10, 5:10] = True
    magnitude = np.ones((h, w), dtype=float)
    result = _coherence_sensitivity(
        east, north, valid, valid, box, crown, magnitude,
        include_published_magnitude_window=True,
    )
    thresholds = result["thresholds"]
    assert result["primary_minimum_valid_neighbours"] == 1
    assert set(thresholds) == {"1", "5", "10", "15", "20", "25"}
    assert thresholds["1"]["crown_valid_centres"] == 25
    assert thresholds["25"]["crown_valid_centres"] == 25
    assert thresholds["1"]["crown_median_R"] == 1.0
    assert thresholds["1"]["target_pair_0_17_to_2_75_m_sensitivity"]["crown_median_R"] == 1.0
    assert "not the paper's matched-control sample" in thresholds["1"]["target_pair_0_17_to_2_75_m_sensitivity"]["note"]
