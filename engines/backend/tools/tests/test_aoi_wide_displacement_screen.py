from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import Affine

from tools.aoi_wide_displacement_screen import (
    _box_sum,
    _pair_offset_threshold_m,
    run_aoi_wide_screen,
)


def _write_goff(
    root: Path,
    product_id: str,
    reference: str,
    secondary: str,
    *,
    seed: int = 1,
    add_patch: bool = True,
    low_quality_patch: bool = False,
    patch_sign: float = 1.0,
    crid: str = "P05023",
    bandwidth: str = "4000",
    transform: Affine | None = None,
) -> dict:
    width, height = 120, 100
    transform = transform or Affine(80.0, 0.0, 500000.0, 0.0, -80.0, 3100000.0)
    rng = np.random.default_rng(seed)
    range_mm = rng.normal(0.0, 4.0, (height, width)).astype(np.float32)
    azimuth_mm = rng.normal(0.0, 4.0, (height, width)).astype(np.float32)
    corr = np.full((height, width), 0.9, dtype=np.float32)
    if add_patch:
        range_mm[45:66, 50:71] += 1000.0 * patch_sign
        azimuth_mm[45:66, 50:71] += 250.0 * patch_sign
    if low_quality_patch:
        corr[45:66, 50:71] = 0.1
    name = (
        f"NISAR_L2_PR_GOFF_023_098_A_016_024_{bandwidth}_SH_"
        f"{reference}T233921_{reference}T233956_"
        f"{secondary}T233920_{secondary}T233955_{crid}_N_F_J_001.h5"
    )
    out_dir = root / "product-data" / product_id
    out_dir.mkdir(parents=True, exist_ok=True)
    raster_rel = f"product-data/{product_id}/GOFF_{reference}_{secondary}_PR_HH-layer2.tif"
    raster_path = root / raster_rel
    with rasterio.open(
        raster_path, "w", driver="GTiff", width=width, height=height, count=3,
        dtype="float32", crs="EPSG:32645", transform=transform, nodata=np.nan,
    ) as ds:
        ds.write(range_mm, 1)
        ds.write(azimuth_mm, 2)
        ds.write(corr, 3)
        ds.set_band_description(1, "slant-range offset (mm)")
        ds.set_band_description(2, "along-track offset (mm)")
        ds.set_band_description(3, "correlation")
        ds.update_tags(
            aoi_mask_applied="true", grid_policy="common_aoi_lattice",
            correlation_min="0.3", crid=crid, source=name,
            reference=reference, secondary=secondary, export_status="WRITTEN",
        )
    valid = int(np.isfinite(range_mm).sum())
    return {
        "id": product_id, "product_type": "GOFF", "granule_name": name,
        "reference_date": f"{reference[:4]}-{reference[4:6]}-{reference[6:8]}",
        "secondary_date": f"{secondary[:4]}-{secondary[4:6]}-{secondary[6:8]}",
        "valid_pixels": valid, "crid": crid,
        "exports": [{"relative_path": raster_rel}],
    }


def _aoi_wkt() -> str:
    transform = Affine(80.0, 0.0, 500000.0, 0.0, -80.0, 3100000.0)
    coordinates = [
        (transform.c + 10 * 80, transform.f - 5 * 80),
        (transform.c + 110 * 80, transform.f - 5 * 80),
        (transform.c + 110 * 80, transform.f - 95 * 80),
        (transform.c + 10 * 80, transform.f - 95 * 80),
        (transform.c + 10 * 80, transform.f - 5 * 80),
    ]
    project = Transformer.from_crs("EPSG:32645", "EPSG:4326", always_xy=True)
    coords_wgs = [project.transform(x, y) for x, y in coordinates]
    return "POLYGON ((" + ", ".join(f"{lon:.9f} {lat:.9f}" for lon, lat in coords_wgs) + "))"


def test_box_sum_preserves_shape_and_edge_windows() -> None:
    values = np.arange(35, dtype=np.float32).reshape(5, 7)
    result = _box_sum(values, 3)
    padded = np.pad(values.astype(float), 1)
    expected = np.zeros_like(values, dtype=float)
    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            expected[row, col] = padded[row:row + 3, col:col + 3].sum()
    assert result.shape == values.shape
    np.testing.assert_allclose(result, expected, rtol=0, atol=1e-5)


def test_target_free_aoi_screen_finds_a_persistent_coherent_patch(tmp_path: Path) -> None:
    rows = [
        _write_goff(tmp_path, "GOFF-001", "20260620", "20260702", seed=1),
        _write_goff(tmp_path, "GOFF-003", "20260702", "20260714", seed=2),
    ]
    result = run_aoi_wide_screen(
        rows, tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
        local_window_px=41, direction_window_px=5, minimum_offset_anomaly_m=0.25,
        minimum_robust_z=4.0, minimum_directional_coherence=0.75,
        minimum_pairs=2, minimum_component_pixels=10,
    )
    assert result["purpose"] == "FIND_DISPLACEMENTS_AOI_WIDE"
    assert result["target_required"] is False
    assert result["target_coordinates_used"] is False
    assert result["status"] == "COMPLETED_EXPLORATORY_RANKING"
    assert result["candidate_count"] >= 1
    assert result["series"][0]["candidate_components"] >= 1
    geojson_path = tmp_path / result["candidates_geojson"]
    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    assert len(geojson["features"]) >= 1
    assert all(feature["properties"]["crid"] == "P05023" for feature in geojson["features"])
    with rasterio.open(tmp_path / result["series"][0]["candidate_mask_raster"]) as ds:
        assert ds.read(1)[55, 60] == 1
        assert ds.crs.to_epsg() == 32645


def test_low_correlation_patch_is_rejected_and_not_called_zero_motion(tmp_path: Path) -> None:
    rows = [
        _write_goff(tmp_path, "GOFF-001", "20260620", "20260702", seed=1, low_quality_patch=True),
        _write_goff(tmp_path, "GOFF-003", "20260702", "20260714", seed=2, low_quality_patch=True),
    ]
    result = run_aoi_wide_screen(
        rows, tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
    )
    assert result["candidate_count"] == 0
    assert result["target_required"] is False
    assert any("zero candidate count does not prove zero displacement" in warning.lower()
               for warning in result["warnings"])


def test_single_pair_does_not_claim_temporal_persistence(tmp_path: Path) -> None:
    row = _write_goff(tmp_path, "GOFF-001", "20260620", "20260702")
    result = run_aoi_wide_screen(
        [row], tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
    )
    assert result["status"] == "INSUFFICIENT_TEMPORAL_SUPPORT"
    assert result["candidate_count"] == 0
    assert result["series"][0]["status"] == "INSUFFICIENT_TEMPORAL_SUPPORT"


def test_duplicate_dates_do_not_count_as_two_temporal_pairs(tmp_path: Path) -> None:
    rows = [
        _write_goff(tmp_path, "GOFF-001", "20260620", "20260702", seed=1),
        _write_goff(tmp_path, "GOFF-002", "20260620", "20260702", seed=2),
    ]
    result = run_aoi_wide_screen(
        rows, tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
    )
    assert result["status"] == "INSUFFICIENT_TEMPORAL_SUPPORT"
    assert len(result["duplicate_intervals_excluded"]) == 1
    assert result["series"][0]["pair_count"] == 1


def test_different_crids_are_kept_in_separate_series(tmp_path: Path) -> None:
    rows = [
        _write_goff(tmp_path, "GOFF-001", "20260620", "20260702", crid="P05023"),
        _write_goff(tmp_path, "GOFF-003", "20260702", "20260714", crid="X05026"),
    ]
    result = run_aoi_wide_screen(
        rows, tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
    )
    assert len(result["series"]) == 2
    assert {series["crid"] for series in result["series"]} == {"P05023", "X05026"}
    assert result["candidate_count"] == 0



def test_opposing_pairwise_directions_do_not_pass_persistence_gate(tmp_path: Path) -> None:
    rows = [
        _write_goff(tmp_path, "GOFF-001", "20260620", "20260702", seed=1, patch_sign=1.0),
        _write_goff(tmp_path, "GOFF-003", "20260702", "20260714", seed=2, patch_sign=-1.0),
    ]
    result = run_aoi_wide_screen(
        rows, tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
        local_window_px=41, direction_window_px=5, minimum_offset_anomaly_m=0.25,
        minimum_robust_z=4.0, minimum_directional_coherence=0.75,
        minimum_cross_pair_directional_coherence=0.75,
        minimum_pairs=2, minimum_component_pixels=10,
    )
    assert result["status"] == "COMPLETED_EXPLORATORY_RANKING"
    assert result["candidate_count"] == 0
    series = result["series"][0]
    assert series["persistent_pixels_before_direction_gate"] > 0
    assert series["persistent_pixels_after_direction_gate"] == 0



def test_different_bandwidths_have_distinct_output_series_ids(tmp_path: Path) -> None:
    rows = [
        _write_goff(tmp_path, "GOFF-001", "20260620", "20260702", bandwidth="4000"),
        _write_goff(tmp_path, "GOFF-003", "20260702", "20260714", bandwidth="2000"),
    ]
    result = run_aoi_wide_screen(
        rows, tmp_path, tmp_path / "aoi-wide-displacement-screen", _aoi_wkt(),
    )
    assert len(result["series"]) == 2
    assert len({series["series_id"] for series in result["series"]}) == 2


def test_pair_threshold_uses_reader_floor_and_elapsed_days() -> None:
    identity = {
        "reference_date": "2026-06-20",
        "secondary_date": "2026-07-02",
    }
    threshold, floor = _pair_offset_threshold_m(
        {"stats": {"detect_floor_mm_day": 40.0}}, identity, 0.25,
    )
    assert floor == 40.0
    assert threshold == 0.48

    fallback_threshold, fallback_floor = _pair_offset_threshold_m(
        {"stats": {}}, identity, 0.25,
    )
    assert fallback_threshold == 0.25
    assert fallback_floor is None
