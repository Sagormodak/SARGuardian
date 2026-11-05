from __future__ import annotations

import csv
from argparse import Namespace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin

from tools.verify_derived_product_outputs import validate


def _write_csv(path: Path, fields: list[str], row: dict[str, object]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def _args(root: Path, family: str, granule: str) -> Namespace:
    return Namespace(
        product_id=f"{family}-001",
        product_type=family,
        granule_name=granule,
        baseline_csv=root / "baseline.csv",
        stats_csv=root / "actual.csv",
        export_dir=root / "exports",
    )


def test_gunw_derived_product_validation_passes(tmp_path: Path) -> None:
    family = "GUNW"
    granule = "NISAR_L2_PR_GUNW_fixture_20250101.h5"
    export_name = "GUNW_20250101_20250113_PR.tif"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    fields = ["file", "maturity", "median", "export_file", "export_rows", "export_cols", "export_mb"]
    row = {
        "file": granule, "maturity": "BETA", "median": "-1.25",
        "export_file": export_name, "export_rows": "4", "export_cols": "5", "export_mb": "0.001",
    }
    _write_csv(tmp_path / "baseline.csv", fields, row)
    _write_csv(tmp_path / "actual.csv", fields, row)
    path = export_dir / export_name
    with rasterio.open(
        path, "w", driver="GTiff", width=5, height=4, count=2, dtype="float32",
        crs="EPSG:32645", transform=from_origin(300000, 3200000, 80, 80), nodata=np.nan,
    ) as dst:
        dst.write(np.ones((4, 5), dtype=np.float32), 1)
        dst.write(np.full((4, 5), 0.8, dtype=np.float32), 2)
        dst.update_tags(source=granule)
    result = validate(_args(tmp_path, family, granule))
    assert result["status"] == "PASS"
    assert result["stats_schema_and_row_match"] is True
    assert result["export_validation"] == "PASS"
    assert result["exports"][0]["count"] == 2


def test_goff_requires_layer2_and_three_bands(tmp_path: Path) -> None:
    family = "GOFF"
    granule = "NISAR_L2_PR_GOFF_fixture_20250101.h5"
    export_name = "GOFF_20250101_20250113_PR_HH-layer2.tif"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    fields = ["file", "layer", "maturity", "range_median_mm", "export_file", "export_mb"]
    row = {"file": granule, "layer": "HH/layer2", "maturity": "BETA",
           "range_median_mm": "2.5", "export_file": export_name, "export_mb": "0.001"}
    _write_csv(tmp_path / "baseline.csv", fields, row)
    _write_csv(tmp_path / "actual.csv", fields, row)
    path = export_dir / export_name
    with rasterio.open(
        path, "w", driver="GTiff", width=5, height=4, count=3, dtype="float32",
        crs="EPSG:32645", transform=from_origin(300000, 3200000, 80, 80), nodata=np.nan,
    ) as dst:
        for band in range(1, 4):
            dst.write(np.full((4, 5), band, dtype=np.float32), band)
        dst.update_tags(source=granule, layer="HH/layer2")
    result = validate(_args(tmp_path, family, granule))
    assert result["status"] == "PASS"
    assert result["exports"][0]["count"] == 3


def test_validation_fails_when_stats_differ_from_baseline(tmp_path: Path) -> None:
    family = "GUNW"
    granule = "NISAR_L2_PR_GUNW_fixture_20250101.h5"
    export_name = "GUNW_20250101_20250113_PR.tif"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    fields = ["file", "maturity", "median", "export_file", "export_rows", "export_cols", "export_mb"]
    baseline = {"file": granule, "maturity": "BETA", "median": "1.0",
                "export_file": export_name, "export_rows": "4", "export_cols": "5", "export_mb": "0.001"}
    actual = dict(baseline, median="999")
    _write_csv(tmp_path / "baseline.csv", fields, baseline)
    _write_csv(tmp_path / "actual.csv", fields, actual)
    with rasterio.open(
        export_dir / export_name, "w", driver="GTiff", width=5, height=4, count=2,
        dtype="float32", crs="EPSG:32645",
        transform=from_origin(300000, 3200000, 80, 80), nodata=np.nan,
    ) as dst:
        dst.write(np.ones((4, 5), dtype=np.float32), 1)
        dst.write(np.ones((4, 5), dtype=np.float32), 2)
        dst.update_tags(source=granule)
    result = validate(_args(tmp_path, family, granule))
    assert result["status"] == "FAIL"
    assert any(error["problem"] == "source_baseline_row_mismatch" for error in result["errors"])
