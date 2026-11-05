from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from dashboard.common_reference import build_common_reference_report


AOI_WKT = "POLYGON((84.90 26.90, 85.12 26.90, 85.12 27.12, 84.90 27.12, 84.90 26.90))"
TARGET = {"status": "IN_AOI_TARGET_CAPTURED", "latitude": 27.01, "longitude": 85.01}


def _fake_science_modules():
    timeseries = ModuleType("timeseries")

    def granule_metadata(name):
        return {
            "product": "GUNW", "cycle": 26, "path": 48, "direction": "D",
            "frame": 71, "subswath": 28, "bandwidth": 4000,
            "polarisation": "SH", "crid": "P05023", "processing": "PR",
        }

    class Pair:
        def __init__(self, *, path, direction, ref, sec, value=None, n_px=None,
                     coherence=None, source="", metadata=None):
            self.path, self.direction, self.ref, self.sec = path, direction, ref, sec
            self.value, self.n_px, self.coherence, self.source = value, n_px, coherence, source
            self.meta = metadata or {}
        def network_key(self):
            return ("D", 48, 71, 28, 4000, "SH", "P05023", "GUNW")
        def network_label(self, short=False):
            return "DESC path 048 frame 071 CRID P05023 GUNW"
        @property
        def span_days(self):
            return (self.sec - self.ref).days

    def connected_components(pairs):
        return [sorted({p.ref for p in pairs} | {p.sec for p in pairs})] if pairs else []

    def invert_component(pairs, epochs):
        return {
            "epochs": list(epochs),
            "dof": len(pairs) - len(epochs) + 1,
            "residual_rms_mm": 0.45,
            "velocity_mm_per_day": 0.08,
            "velocity_err_mm_per_day": 0.01,
            "cumulative_mm": np.asarray([0.0, 1.2, 2.0, 3.1]),
            "error_mm": np.asarray([0.0, 0.2, 0.25, 0.3]),
        }

    timeseries.granule_metadata = granule_metadata
    timeseries.Pair = Pair
    timeseries.connected_components = connected_components
    timeseries.invert_component = invert_component
    timeseries.jackknife = lambda _label, _idx, pairs, _epochs: (
        {"testable": True, "robust": True, "velocity_mm_per_day": 0.08,
         "jackknife_min": 0.06, "jackknife_max": 0.10} if len(pairs) >= 4 else None
    )

    aoi_wkt = ModuleType("aoi_wkt")
    def parse_polygon_wkt(_wkt):
        return [(84.90, 26.90), (85.12, 26.90), (85.12, 27.12), (84.90, 27.12), (84.90, 26.90)]
    aoi_wkt.parse_polygon_wkt = parse_polygon_wkt

    gunw_reader = ModuleType("gunw_reader")
    gunw_reader.AOIS = {}
    gunw_reader.set_aoi = lambda name: None

    common_ref = ModuleType("common_ref")
    common_ref.MIN_COMMON = 200
    common_ref.common_mask = lambda stack: np.logical_and.reduce([np.isfinite(a) for a in stack])
    def buffer_mask(shape, centres, radius_px):
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
        out = np.zeros(shape, dtype=bool)
        for row, col in centres:
            out |= (yy - row) ** 2 + (xx - col) ** 2 <= radius_px ** 2
        return out
    common_ref.buffer_mask = buffer_mask
    def rereference(stack, stable):
        count = int(stable.sum())
        if count < common_ref.MIN_COMMON:
            raise ValueError(f"only {count} common stable pixels; need {common_ref.MIN_COMMON}")
        offsets = [float(np.median(a[stable])) for a in stack]
        return [a - offset for a, offset in zip(stack, offsets)], offsets
    common_ref.rereference = rereference
    def window(a, row, col, radius):
        return a[max(0, row-radius):min(a.shape[0], row+radius+1),
                 max(0, col-radius):min(a.shape[1], col+radius+1)]
    common_ref.window = window

    return {
        "aoi_wkt": aoi_wkt,
        "timeseries": timeseries,
        "gunw_reader": gunw_reader,
        "common_ref": common_ref,
    }


def _write_raster(path: Path, value_offset: float) -> None:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    x, y = transformer.transform(TARGET["longitude"], TARGET["latitude"])
    transform = from_origin(x - 10_000, y + 10_000, 100, 100)
    rr, cc = np.mgrid[0:200, 0:200]
    los = (0.01 * rr + 0.02 * cc + value_offset).astype("float32")
    coherence = np.full((200, 200), 0.8, dtype="float32")
    with rasterio.open(path, "w", driver="GTiff", width=200, height=200, count=2,
                       dtype="float32", crs="EPSG:32645", transform=transform,
                       nodata=np.nan) as dst:
        dst.write(los, 1)
        dst.write(coherence, 2)
        dst.set_band_description(1, "LOS displacement (mm)")
        dst.set_band_description(2, "coherence")
        dst.update_tags(aoi_name="custom", aoi_mask_applied="true",
                        grid_policy="common_aoi_lattice", export_status="WRITTEN")


def test_missing_or_invalid_target_blocks_common_reference(tmp_path: Path) -> None:
    report = build_common_reference_report([], tmp_path, tmp_path, AOI_WKT, "a" * 64, {
        "measurement_target": {"status": "NOT_PROVIDED"}
    })
    assert report["status"] == "BLOCKED_NO_VALID_IN_AOI_TARGET"
    assert not report["components"]
    assert (tmp_path / "common-reference-timeseries.json").is_file()


def test_common_datum_diagnostic_requires_grid_and_network_gates(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    products = []
    # Five real-like intervals produce a connected, redundant four-epoch graph.
    intervals = [
        ("2026-08-01", "2026-08-13"),
        ("2026-08-13", "2026-08-25"),
        ("2026-08-25", "2026-09-06"),
        ("2026-08-01", "2026-08-25"),
        ("2026-08-13", "2026-09-06"),
    ]
    for idx, (reference, secondary) in enumerate(intervals, 1):
        folder = tmp_path / "product-data" / f"GUNW-{idx:03d}"
        folder.mkdir(parents=True)
        raster = folder / f"pair-{idx}.tif"
        _write_raster(raster, float(idx))
        granule = (
            f"NISAR_L2_PR_GUNW_026_048_D_071_028_4000_SH_"
            f"{reference.replace('-', '')}T000000_{reference.replace('-', '')}T000000_"
            f"{secondary.replace('-', '')}T000000_{secondary.replace('-', '')}T000000_P05023_N_F_J_001"
        )
        products.append({
            "id": f"GUNW-{idx:03d}", "product_type": "GUNW", "granule_name": granule,
            "reference_date": reference, "secondary_date": secondary,
            "exports": [{"relative_path": raster.relative_to(tmp_path).as_posix()}],
        })

    modules = _fake_science_modules()
    with patch.dict(sys.modules, modules):
        report = build_common_reference_report(products, tmp_path, tmp_path, AOI_WKT, "b" * 64, {
            "measurement_target": TARGET,
        })

    assert report["status"] == "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED"
    assert len(report["pairwise_measurements"]) == 5
    assert len(report["components"]) == 1
    component = report["components"][0]
    assert component["status"] == "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED"
    assert component["redundancy"] > 0
    assert component["jackknife"]["robust"] is True
    assert len(component["series"]) == 4
    assert report["common_reference_is_independently_validated_stable_ground"] is False
    saved = json.loads((tmp_path / "common-reference-timeseries.json").read_text(encoding="utf-8"))
    assert saved["status"] == report["status"]
    assert (tmp_path / "common-reference-pairs.csv").is_file()
    assert (tmp_path / "common-reference-series.csv").is_file()
