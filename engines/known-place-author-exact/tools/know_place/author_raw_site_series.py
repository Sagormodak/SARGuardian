"""Author-compatible five-pair site-series metrics from verified raw GOFF inputs.

This runner is separate from analyze.py's exploratory fixed-height path.
P1/site-series fields use the archived crown-local height-axis-median geometry,
SNR/magnitude gate, conditional ring reference, north-up extent and
post-hoc polygon-null statistics. P2/local-mean reference is a distinct path:
it builds per-pixel projection coefficients from the pinned author DEM and
radarGrid geometry, computes the source-compatible local-mean residual
coherence on a context halo, then selects the WIDE pixel box and crown using
the archived spatial-selection order. The prepared DEM's height values are
used directly against the radarGrid HAE axis without a vertical transformation;
the mismatch is explicitly reported. This is not the full-footprint screen
and does not certify hazard-detection skill.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import rasterio
from affine import Affine
from rasterio.windows import Window

from .analyze import _load_and_validate_inputs, load_config
from .author_parity import (
    AuthorParityError,
    author_coherence_map,
    author_crown_geometry_median,
    author_crown_slice,
    author_inside_aoi_mask,
    author_local_mean_reference_statistics,
    author_north_up,
    author_polygon_null_statistics,
    author_project_offsets,
    author_quality_mask,
    author_reference_correct,
    author_site_series_statistics,
    author_wide_window_slices,
)
from .geometry import parse_polygon_wkt
from .goff_io import GoffReadError, read_geometry_cubes, read_raw_goff
from .footprint_geometry import AUTHOR_GEOMETRY_SHA256, build_per_pixel_coefficients
from .footprint_screen import project_per_pixel_offsets
from .paper_method import PAPER_INTERVALS

AUTHOR_CROWN_BOUNDS = (85.5245, 28.2847, 85.5400, 28.2970)
AUTHOR_WIDE_BOUNDS = (85.500, 28.265, 85.565, 28.318)
AUTHOR_CROWN_POINT = (85.52985, 28.29041)
AUTHOR_EXPECTED_EPSG = 32645
AUTHOR_POSTING_M = 80.0
AUTHOR_NULL_SEED = 20260907
AUTHOR_NULL_DRAWS = 1200
PAPER_BLOCKED = "BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED"
AUTHOR_TERRAIN_ELEVATION_SHA256 = "d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1"
AUTHOR_TERRAIN_SHAPE = (4230, 4311)
AUTHOR_TERRAIN_TRANSFORM = Affine(80.0, 0.0, 126720.0, 0.0, -80.0, 3347280.0)
AUTHOR_DEM_VERTICAL_REFERENCE = "EPSG:9518 WGS 84 + EGM2008 height, Copernicus GLO-90 prepared elevation"
AUTHOR_GEOMETRY_HEIGHT_REFERENCE = "NISAR radarGrid heightAboveEllipsoid (HAE)"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _bounds_from_wkt(wkt: str, label: str) -> tuple[float, float, float, float]:
    ring = parse_polygon_wkt(wkt)
    coordinates = ring[:-1]
    bounds = (
        min(point[0] for point in coordinates),
        min(point[1] for point in coordinates),
        max(point[0] for point in coordinates),
        max(point[1] for point in coordinates),
    )
    if not bounds[0] < bounds[2] or not bounds[1] < bounds[3]:
        raise GoffReadError(f"{label}_WKT_BOUNDS_INVALID")
    return bounds


def _assert_author_bounds(config: dict[str, Any]) -> None:
    """Fail closed if the run config silently changes the archived author rectangles."""
    checks = (
        ("CROWN", _bounds_from_wkt(str(config["crown_wkt"]), "CROWN"), AUTHOR_CROWN_BOUNDS),
        ("REFERENCE_BOX", _bounds_from_wkt(str(config["reference_box_wkt"]), "REFERENCE_BOX"), AUTHOR_WIDE_BOUNDS),
    )
    for label, actual, expected in checks:
        if any(abs(float(a) - float(e)) > 1e-9 for a, e in zip(actual, expected, strict=True)):
            raise GoffReadError(
                f"AUTHOR_PROFILE_{label}_BOUNDS_MISMATCH:actual={actual}:expected={expected}"
            )


def _rounding_match(actual: float | int, expected: float | int, decimals: int | None) -> bool:
    if decimals is None:
        return int(actual) == int(expected)
    return round(float(actual), decimals) == round(float(expected), decimals)


def compare_pair_to_archive(
    site: dict[str, Any],
    polygon_null: dict[str, Any],
    pair_index: int,
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    """Compare explicit, same-estimand metrics at the archive's published precision."""
    expected = benchmark["published_site_series"]
    specs: list[tuple[str, float | int, float | int, int | None]] = [
        ("displacement_valid_crown_pixels", site["displacement_valid_crown_cells"],
         expected["displacement_valid_crown_pixels"][pair_index], None),
        ("median_crown_displacement_m", site["crown_median_displacement_m"],
         expected["median_crown_displacement_m"][pair_index], 2),
        ("median_crown_rate_cm_per_day", site["crown_median_rate_cm_per_day"],
         expected["median_crown_rate_cm_per_day"][pair_index], 1),
        ("bulk_reference_crown_R", site["P1_R_crown"],
         expected["bulk_reference_crown_R"][pair_index], 3),
        ("bulk_reference_background_R", site["P1_R_background"],
         expected["bulk_reference_background_R"][pair_index], 3),
        ("polygon_null_R_valid_crown_pixels", polygon_null["crown_valid_R_cells"],
         expected["polygon_null_R_valid_crown_pixels"][pair_index], None),
        ("single_field_crown_R", polygon_null["crown_R"],
         expected["single_field_crown_R"][pair_index], 3),
        ("polygon_null_box_R", polygon_null["box_R"],
         expected["bulk_reference_background_R"][pair_index], 3),
        ("polygon_null_R_percentile", polygon_null["crown_percentile_strict_less_than"],
         expected["polygon_null_R_percentile"][pair_index], 1),
        ("polygon_null_samples_beating_box_mean_percent", polygon_null["fraction_controls_strictly_above_box"],
         expected["polygon_null_samples_beating_box_mean_percent"][pair_index], 1),
        ("polygon_null_R_5th_percentile", polygon_null["null_p5"],
         expected["polygon_null_R_5th_percentile"][pair_index], 3),
        ("polygon_null_R_95th_percentile", polygon_null["null_p95"],
         expected["polygon_null_R_95th_percentile"][pair_index], 3),
        ("polygon_null_accepted_draws", polygon_null["accepted_draws"],
         expected["polygon_null_accepted_draws"][pair_index], None),
    ]
    comparisons = []
    for metric, actual, target, decimals in specs:
        comparisons.append({
            "metric": metric,
            "actual": actual,
            "archive_target": target,
            "comparison_precision_decimals": decimals,
            "passed": _rounding_match(actual, target, decimals),
        })
    return {
        "status": "PASS_AT_ARCHIVE_ROUNDING" if all(row["passed"] for row in comparisons) else "MISMATCH",
        "checks_passed": sum(bool(row["passed"]) for row in comparisons),
        "checks_total": len(comparisons),
        "comparisons": comparisons,
    }




def compare_p2_pair_to_archive(
    p2: dict[str, Any], pair_index: int, benchmark: dict[str, Any]
) -> dict[str, Any]:
    """Compare P2/local-mean reference fields with Table S4's three P2 columns."""
    expected = benchmark["published_site_series"]
    specs = [
        ("P2_R_crown", p2["P2_R_crown"], expected["local_mean_reference_crown_R"][pair_index], 3),
        ("P2_R_bg", p2["P2_R_background"], expected["local_mean_reference_background_R"][pair_index], 3),
        (
            "P2_resolved",
            p2["P2_resolved"],
            bool(expected["local_mean_reference_crown_R"][pair_index]
                 > expected["local_mean_reference_background_R"][pair_index]),
            None,
        ),
    ]
    checks = []
    for metric, actual, target, decimals in specs:
        passed = (bool(actual) == bool(target)) if metric == "P2_resolved" else _rounding_match(actual, target, decimals)
        checks.append({
            "metric": metric,
            "actual": actual,
            "archive_target": target,
            "comparison_precision_decimals": decimals,
            "passed": bool(passed),
        })
    return {
        "status": "PASS_AT_ARCHIVE_ROUNDING" if all(row["passed"] for row in checks) else "MISMATCH",
        "checks_passed": sum(row["passed"] for row in checks),
        "checks_total": len(checks),
        "comparisons": checks,
    }

def process_author_pair_arrays(
    *,
    along_track_m: Any,
    slant_range_m: Any,
    snr: Any,
    x_coordinates_m: Any,
    y_coordinates_m: Any,
    epsg: int,
    geometry_cubes: Any,
    interval_days: int,
    polygon_null_rng: np.random.Generator,
) -> dict[str, Any]:
    """Compute archived author site-series metrics from one raw GOFF window."""
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    at = np.asarray(along_track_m, dtype=float)
    sr = np.asarray(slant_range_m, dtype=float)
    snr_array = np.asarray(snr, dtype=float)
    if at.ndim != 2 or sr.shape != at.shape or snr_array.shape != at.shape:
        raise GoffReadError("AUTHOR_RAW_PAIR_ARRAY_SHAPE_MISMATCH")
    if at.shape != (y.size, x.size):
        raise GoffReadError("AUTHOR_RAW_PAIR_COORDINATE_SHAPE_MISMATCH")
    if int(epsg) != AUTHOR_EXPECTED_EPSG:
        raise GoffReadError(f"AUTHOR_RAW_PAIR_EPSG_MISMATCH:{epsg}")
    geometry = author_crown_geometry_median(
        geometry_cubes, crown_lonlat=AUTHOR_CROWN_POINT, expected_epsg=AUTHOR_EXPECTED_EPSG
    )
    east, north = author_project_offsets(at, sr, geometry)
    valid = author_quality_mask(east, north, snr_array, minimum_snr=5.0, maximum_magnitude_m=10.0)
    inside = author_inside_aoi_mask(
        x, y, int(epsg), aoi_bounds_lonlat=AUTHOR_CROWN_BOUNDS
    )
    corrected_east, corrected_north, reference = author_reference_correct(
        east, north, valid, inside, minimum_ring_count_exclusive=200
    )
    extent, oriented = author_north_up(
        x, y, int(epsg), [corrected_east, corrected_north, valid, inside]
    )
    east_up, north_up = np.asarray(oriented[0], dtype=float), np.asarray(oriented[1], dtype=float)
    valid_up, inside_up = np.asarray(oriented[2], dtype=bool), np.asarray(oriented[3], dtype=bool)
    magnitude = np.hypot(east_up, north_up)
    magnitude[~(np.isfinite(east_up) & np.isfinite(north_up))] = np.nan
    coherence = author_coherence_map(east_up, north_up)
    crop = author_crown_slice(east_up.shape, extent, AUTHOR_CROWN_BOUNDS)
    crown_mask = np.zeros(east_up.shape, dtype=bool)
    crown_mask[crop] = True
    site = author_site_series_statistics(
        east_up, north_up, extent, interval_days, crown_bounds_lonlat=AUTHOR_CROWN_BOUNDS
    )
    polygon_null = author_polygon_null_statistics(
        east_up, north_up, extent, rng=polygon_null_rng,
        n_draw=AUTHOR_NULL_DRAWS, acceptance_fraction=0.60,
        crown_bounds_lonlat=AUTHOR_CROWN_BOUNDS,
    )
    return {
        "geometry": geometry,
        "quality": {
            "total_window_cells": int(valid.size),
            "author_valid_cells_after_snr_and_magnitude_gates": int(valid.sum()),
            "correlation_field_is_not_used_by_author_quality_gate": True,
            "minimum_snr": 5.0,
            "maximum_horizontal_magnitude_m": 10.0,
            "rejected_pixels_are_masked_not_clipped": True,
        },
        "reference_correction": reference,
        "extent_lonlat": list(extent),
        "site_series": site,
        "polygon_null": polygon_null,
        "arrays": {
            "east_m": east_up.astype(np.float32),
            "north_m": north_up.astype(np.float32),
            "horizontal_magnitude_m": magnitude.astype(np.float32),
            "directional_coherence_R": coherence.astype(np.float32),
            "valid_mask": valid_up.astype(np.uint8),
            "inside_aoi_mask": inside_up.astype(np.uint8),
            "crown_mask": crown_mask.astype(np.uint8),
        },
    }


def _read_author_p2_terrain_window(
    terrain_root: str | Path,
    row_slice: slice,
    col_slice: slice,
    raw_halo: Any,
) -> tuple[np.ndarray, Affine, dict[str, Any]]:
    """Read the exact pinned DEM tile aligned to a raw GOFF context window."""
    terrain_path = Path(terrain_root).expanduser().resolve() / "elev_m.tif"
    if not terrain_path.is_file():
        raise GoffReadError("AUTHOR_P2_PINNED_TERRAIN_ELEVATION_MISSING")
    digest = _sha256_file(terrain_path)
    if digest != AUTHOR_TERRAIN_ELEVATION_SHA256:
        raise GoffReadError("AUTHOR_P2_PINNED_TERRAIN_SHA256_MISMATCH")
    if row_slice.start is None or row_slice.stop is None or col_slice.start is None or col_slice.stop is None:
        raise GoffReadError("AUTHOR_P2_TERRAIN_WINDOW_BOUNDS_MISSING")
    row_start, row_stop = int(row_slice.start), int(row_slice.stop)
    col_start, col_stop = int(col_slice.start), int(col_slice.stop)
    if row_start < 0 or col_start < 0 or row_stop <= row_start or col_stop <= col_start:
        raise GoffReadError("AUTHOR_P2_TERRAIN_WINDOW_BOUNDS_INVALID")
    expected_window = {
        "row_start": row_start, "row_stop": row_stop,
        "column_start": col_start, "column_stop": col_stop,
    }
    if raw_halo.metadata.get("read_window", {}) != expected_window:
        raise GoffReadError("AUTHOR_P2_RAW_GOFF_WINDOW_IDENTITY_MISMATCH")
    window = Window(col_start, row_start, col_stop - col_start, row_stop - row_start)
    with rasterio.open(terrain_path) as src:
        epsg = src.crs.to_epsg() if src.crs else None
        if epsg != 32645:
            raise GoffReadError("AUTHOR_P2_TERRAIN_CRS_MISMATCH")
        if (src.height, src.width) != AUTHOR_TERRAIN_SHAPE:
            raise GoffReadError("AUTHOR_P2_TERRAIN_SHAPE_MISMATCH")
        if src.count != 1 or src.dtypes[0] != "float32":
            raise GoffReadError("AUTHOR_P2_TERRAIN_BAND_TYPE_MISMATCH")
        if src.nodata is None or float(src.nodata) != -9999.0:
            raise GoffReadError("AUTHOR_P2_TERRAIN_NODATA_MISMATCH")
        if not np.allclose(
            [src.transform.a, src.transform.b, src.transform.c,
             src.transform.d, src.transform.e, src.transform.f],
            [AUTHOR_TERRAIN_TRANSFORM.a, AUTHOR_TERRAIN_TRANSFORM.b, AUTHOR_TERRAIN_TRANSFORM.c,
             AUTHOR_TERRAIN_TRANSFORM.d, AUTHOR_TERRAIN_TRANSFORM.e, AUTHOR_TERRAIN_TRANSFORM.f],
            rtol=0.0, atol=1e-9,
        ):
            raise GoffReadError("AUTHOR_P2_TERRAIN_AFFINE_MISMATCH")
        tile_transform = src.window_transform(window)
        expected_tile_transform = Affine(
            80.0, 0.0, AUTHOR_TERRAIN_TRANSFORM.c + col_start * 80.0,
            0.0, -80.0, AUTHOR_TERRAIN_TRANSFORM.f - row_start * 80.0,
        )
        if not np.allclose(
            [tile_transform.a, tile_transform.b, tile_transform.c,
             tile_transform.d, tile_transform.e, tile_transform.f],
            [expected_tile_transform.a, expected_tile_transform.b, expected_tile_transform.c,
             expected_tile_transform.d, expected_tile_transform.e, expected_tile_transform.f],
            rtol=0.0, atol=1e-9,
        ):
            raise GoffReadError("AUTHOR_P2_TERRAIN_WINDOW_AFFINE_MISMATCH")
        dem = src.read(1, window=window, masked=False).astype(np.float32, copy=False)
    if dem.shape != raw_halo.along_track_m.shape:
        raise GoffReadError("AUTHOR_P2_TERRAIN_RAW_WINDOW_SHAPE_MISMATCH")
    expected_x = AUTHOR_TERRAIN_TRANSFORM.c + (
        np.arange(col_start, col_stop, dtype=np.float64) + 0.5
    ) * AUTHOR_TERRAIN_TRANSFORM.a
    expected_y = AUTHOR_TERRAIN_TRANSFORM.f + (
        np.arange(row_start, row_stop, dtype=np.float64) + 0.5
    ) * AUTHOR_TERRAIN_TRANSFORM.e
    if not np.allclose(raw_halo.x_coordinates_m, expected_x, rtol=0.0, atol=1e-4):
        raise GoffReadError("AUTHOR_P2_GOFF_X_DOES_NOT_MATCH_PINNED_TERRAIN")
    if not np.allclose(raw_halo.y_coordinates_m, expected_y, rtol=0.0, atol=1e-4):
        raise GoffReadError("AUTHOR_P2_GOFF_Y_DOES_NOT_MATCH_PINNED_TERRAIN")
    evidence = {
        "sha256": digest,
        "crs_epsg": 32645,
        "source_shape": list(AUTHOR_TERRAIN_SHAPE),
        "window": expected_window,
        "window_shape": list(dem.shape),
        "window_transform": {
            "a": tile_transform.a, "b": tile_transform.b, "c": tile_transform.c,
            "d": tile_transform.d, "e": tile_transform.e, "f": tile_transform.f,
        },
        "nodata": -9999.0,
        "raw_goff_pixel_centres_match_dem_window": True,
    }
    return dem, tile_transform, evidence


def project_author_p2_window(
    *,
    along_track_m: Any,
    slant_range_m: Any,
    snr: Any,
    geometry_cubes: Any,
    dem_elevation_m: Any,
    target_transform: Affine,
    epsg: int,
) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    """Build author per-pixel DEM geometry and project P2 offsets for one tile."""
    dem = np.asarray(dem_elevation_m, dtype=np.float32)
    at = np.asarray(along_track_m, dtype=np.float32)
    sr = np.asarray(slant_range_m, dtype=np.float32)
    snr_values = np.asarray(snr, dtype=np.float32)
    if dem.ndim != 2 or at.shape != dem.shape or sr.shape != dem.shape or snr_values.shape != dem.shape:
        raise GoffReadError("AUTHOR_P2_RAW_DEM_TILE_SHAPE_MISMATCH")
    geometry = build_per_pixel_coefficients(
        geometry_cubes.height_m,
        geometry_cubes.y_m,
        geometry_cubes.x_m,
        geometry_cubes.incidence_deg,
        geometry_cubes.los_x,
        geometry_cubes.los_y,
        geometry_cubes.along_track_x,
        geometry_cubes.along_track_y,
        dem,
        target_transform,
        dem_transform=target_transform,
        target_epsg=int(epsg),
        geometry_metadata_epsg=int(geometry_cubes.metadata_epsg),
        dem_epsg=int(epsg),
        dem_vertical_reference=AUTHOR_DEM_VERTICAL_REFERENCE,
        geometry_height_reference=AUTHOR_GEOMETRY_HEIGHT_REFERENCE,
        # Match archived source behavior exactly; datum mismatch remains
        # explicit in the report and no vertical correction is applied.
        allow_vertical_reference_mismatch=True,
        dem_nodata=-9999.0,
        block_rows=100,
    )
    if geometry.get("status") != "PER_PIXEL_GEOMETRY_COEFFICIENTS_COMPUTED":
        raise GoffReadError("AUTHOR_P2_PER_PIXEL_GEOMETRY_INCOMPLETE")
    coefficients = geometry["coefficients"]
    projection = project_per_pixel_offsets(
        at, sr, snr_values,
        coefficients["cE"], coefficients["cN"],
        coefficients["kE"], coefficients["kN"],
        minimum_snr=5.0, maximum_magnitude_m=10.0,
    )
    evidence = {
        "geometry_method": "author geometry.py RegularGridInterpolator using each target DEM pixel elevation",
        "author_geometry_source_sha256": AUTHOR_GEOMETRY_SHA256,
        "dem_vertical_reference": AUTHOR_DEM_VERTICAL_REFERENCE,
        "geometry_height_reference": AUTHOR_GEOMETRY_HEIGHT_REFERENCE,
        "vertical_transformation_applied": False,
        "vertical_reference_diagnostics": geometry.get("vertical_reference"),
        "coefficient_diagnostics": geometry.get("diagnostics"),
        "coefficient_cache_policy": "build from first exact pair and reuse across five same-grid pairs, matching author cached geometry",
        "projection_geometry_policy": projection.get("geometry_policy"),
        "quality_gate": "float32 dE/dN; SNR >= 5; horizontal magnitude <= 10 m; invalid pixels masked",
    }
    return projection, coefficients, evidence


def run_author_raw_site_series(config_path: str | Path, output_dir: str | Path, *, terrain_root: str | Path) -> dict[str, Any]:
    """Read exactly five validated raw author granules and write reproducible site-series evidence."""
    config, config_dir = load_config(config_path)
    _assert_author_bounds(config)
    terrain_root = Path(terrain_root).expanduser().resolve()
    if not (terrain_root / "elev_m.tif").is_file():
        raise GoffReadError("AUTHOR_P2_PINNED_TERRAIN_ELEVATION_MISSING")
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    products = _load_and_validate_inputs(config, config_dir)
    benchmark_path = Path(__file__).resolve().parents[2] / "docs" / "know-place" / "reference" / "author_benchmark_v1.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    rng = np.random.default_rng(AUTHOR_NULL_SEED)
    pair_reports: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    p2_coefficients: dict[str, np.ndarray] | None = None
    p2_geometry_evidence: dict[str, Any] | None = None
    p2_window_signature: dict[str, int] | None = None
    p2_x_coordinates: np.ndarray | None = None
    p2_y_coordinates: np.ndarray | None = None

    for pair_index, (item, interval) in enumerate(zip(products, PAPER_INTERVALS, strict=True)):
        start, end = interval
        if (item["reference_date"], item["secondary_date"]) != interval:
            raise GoffReadError("AUTHOR_PROFILE_PAIR_ORDER_MISMATCH")
        grid = item["grid"]
        row_slice, col_slice = author_wide_window_slices(
            grid.x_coordinates_m, grid.y_coordinates_m, grid.epsg,
            wide_bounds_lonlat=AUTHOR_WIDE_BOUNDS,
        )
        raw = read_raw_goff(
            item["path"], polarization="HH", layer=2,
            expected_track="098", expected_direction="A", expected_processing="PR",
            window_slices=(row_slice, col_slice), expected_grid=grid,
        )
        cubes = read_geometry_cubes(item["path"], expected_epsg=raw.epsg)
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        result = process_author_pair_arrays(
            along_track_m=raw.along_track_m,
            slant_range_m=raw.slant_range_m,
            snr=raw.snr,
            x_coordinates_m=raw.x_coordinates_m,
            y_coordinates_m=raw.y_coordinates_m,
            epsg=raw.epsg,
            geometry_cubes=cubes,
            interval_days=days,
            polygon_null_rng=rng,
        )

        # P2 uses author per-pixel DEM-derived geometry, not the P1
        # crown-point median-geometry approximation. The 22-pixel halo supports
        # the 41x41 local mean and 5x5 residual coherence around the box.
        halo_pixels = 41 // 2 + 2
        halo_rows = slice(
            max(0, int(row_slice.start) - halo_pixels),
            min(int(grid.grid_shape[0]), int(row_slice.stop) + halo_pixels),
        )
        halo_cols = slice(
            max(0, int(col_slice.start) - halo_pixels),
            min(int(grid.grid_shape[1]), int(col_slice.stop) + halo_pixels),
        )
        raw_halo = read_raw_goff(
            item["path"], polarization="HH", layer=2,
            expected_track="098", expected_direction="A", expected_processing="PR",
            window_slices=(halo_rows, halo_cols), expected_grid=grid,
        )
        current_window = raw_halo.metadata["read_window"]
        if p2_coefficients is None:
            dem, dem_transform, terrain_evidence = _read_author_p2_terrain_window(
                terrain_root, halo_rows, halo_cols, raw_halo
            )
            p2_projection, p2_coefficients, p2_geometry_evidence = project_author_p2_window(
                along_track_m=raw_halo.along_track_m,
                slant_range_m=raw_halo.slant_range_m,
                snr=raw_halo.snr,
                geometry_cubes=cubes,
                dem_elevation_m=dem,
                target_transform=dem_transform,
                epsg=raw_halo.epsg,
            )
            p2_geometry_evidence["terrain"] = terrain_evidence
            p2_window_signature = {key: int(value) for key, value in current_window.items()}
            p2_x_coordinates = raw_halo.x_coordinates_m.copy()
            p2_y_coordinates = raw_halo.y_coordinates_m.copy()
        else:
            if (
                current_window != p2_window_signature
                or p2_x_coordinates is None or p2_y_coordinates is None
                or not np.array_equal(raw_halo.x_coordinates_m, p2_x_coordinates)
                or not np.array_equal(raw_halo.y_coordinates_m, p2_y_coordinates)
                or any(np.asarray(value).shape != raw_halo.along_track_m.shape
                       for value in p2_coefficients.values())
            ):
                raise GoffReadError("AUTHOR_P2_REUSED_GEOMETRY_GRID_IDENTITY_MISMATCH")
            p2_projection = project_per_pixel_offsets(
                np.asarray(raw_halo.along_track_m, dtype=np.float32),
                np.asarray(raw_halo.slant_range_m, dtype=np.float32),
                np.asarray(raw_halo.snr, dtype=np.float32),
                p2_coefficients["cE"], p2_coefficients["cN"],
                p2_coefficients["kE"], p2_coefficients["kN"],
                minimum_snr=5.0, maximum_magnitude_m=10.0,
            )
        p2 = author_local_mean_reference_statistics(
            p2_projection["dE_m"], p2_projection["dN_m"],
            raw_halo.x_coordinates_m, raw_halo.y_coordinates_m, raw_halo.epsg,
            local_window=41,
            crown_bounds_lonlat=AUTHOR_CROWN_BOUNDS,
            box_bounds_lonlat=AUTHOR_WIDE_BOUNDS,
        )
        p2["projection_geometry"] = p2_geometry_evidence
        p2["projection_quality_gate_counts"] = p2_projection["quality_gate_counts"]
        p2_comparison = compare_p2_pair_to_archive(p2, pair_index, benchmark)
        comparison = compare_pair_to_archive(
            result["site_series"], result["polygon_null"], pair_index, benchmark
        )
        pair_key = f"{start.replace('-', '')}__{end.replace('-', '')}"
        array_path = out / f"{pair_key}_author_site_series_arrays.npz"
        np.savez_compressed(array_path, **result["arrays"])
        pair_report = {
            "pair": f"{start}->{end}",
            "interval_days": days,
            "granule_name": raw.identity.granule_name,
            "release_id": raw.identity.release_id,
            "source_sha256": raw.source_sha256,
            "source_bytes": int(grid.file_size_bytes),
            "source_grid": {
                "epsg": int(raw.epsg),
                "original_width": int(grid.grid_shape[1]),
                "original_height": int(grid.grid_shape[0]),
                "window_shape": list(raw.along_track_m.shape),
                "window_slices": raw.metadata["read_window"],
                "x_posting_m": float(np.median(np.diff(grid.x_coordinates_m))),
                "y_posting_m": float(np.median(np.diff(grid.y_coordinates_m))),
            },
            "geometry": {
                **result["geometry"],
                "height_policy": "nearest crown radarGrid XY cell; nan-median across the full valid height axis",
                "vertical_datum_correction_applied": False,
                "unit_evidence": cubes.unit_evidence,
            },
            "quality": result["quality"],
            "reference_correction": result["reference_correction"],
            "extent_lonlat": result["extent_lonlat"],
            "site_series": result["site_series"],
            "polygon_null": result["polygon_null"],
            "P2_local_mean_reference": p2,
            "P2_archive_table_comparison": p2_comparison,
            "archive_table_comparison": comparison,
            "diagnostic_npz": array_path.name,
            "diagnostic_arrays_sha256": _sha256_file(array_path),
        }
        pair_reports.append(pair_report)
        csv_rows.append({
            "pair": pair_report["pair"],
            "source_sha256": pair_report["source_sha256"],
            "valid_crown_displacement_pixels": result["site_series"]["displacement_valid_crown_cells"],
            "crown_median_displacement_m": result["site_series"]["crown_median_displacement_m"],
            "crown_median_rate_cm_per_day": result["site_series"]["crown_median_rate_cm_per_day"],
            "bulk_reference_crown_R": result["site_series"]["P1_R_crown"],
            "bulk_reference_background_R": result["site_series"]["P1_R_background"],
            "polygon_null_crown_R": result["polygon_null"]["crown_R"],
            "polygon_null_crown_percentile": result["polygon_null"]["crown_percentile_strict_less_than"],
            "archive_checks_passed": comparison["checks_passed"],
            "archive_checks_total": comparison["checks_total"],
            "archive_table_comparison_status": comparison["status"],
            "P2_R_crown": p2["P2_R_crown"],
            "P2_R_background": p2["P2_R_background"],
            "P2_resolved": p2["P2_resolved"],
            "P2_archive_checks_passed": p2_comparison["checks_passed"],
            "P2_archive_checks_total": p2_comparison["checks_total"],
            "P2_archive_comparison_status": p2_comparison["status"],
        })
        del cubes, raw

    comparison_count = sum(row["archive_table_comparison"]["checks_total"] for row in pair_reports)
    comparison_passed = sum(row["archive_table_comparison"]["checks_passed"] for row in pair_reports)
    mismatches = [
        {"pair": row["pair"], **check}
        for row in pair_reports
        for check in row["archive_table_comparison"]["comparisons"]
        if not check["passed"]
    ]
    site_table_match = (
        len(pair_reports) == 5
        and comparison_count == 65
        and comparison_passed == 65
        and not mismatches
    )
    p2_comparisons = [
        check
        for row in pair_reports
        for check in row["P2_archive_table_comparison"]["comparisons"]
    ]
    p2_passed = sum(bool(check["passed"]) for check in p2_comparisons)
    p2_total = len(p2_comparisons)
    p2_mismatches = [
        {"pair": row["pair"], **check}
        for row in pair_reports
        for check in row["P2_archive_table_comparison"]["comparisons"]
        if not check["passed"]
    ]
    p2_table_match = len(pair_reports) == 5 and p2_total == 15 and p2_passed == 15 and not p2_mismatches
    paper_status = (
        "PARTIAL_AUTHOR_P1_P2_AND_POLYGON_METRICS_MATCH_FULL_FOOTPRINT_SCREEN_NOT_REPRODUCED"
        if site_table_match and p2_table_match
        else "PARTIAL_AUTHOR_SITE_METRICS_MATCH_P2_UNVERIFIED_FULL_FOOTPRINT_SCREEN_NOT_REPRODUCED"
        if site_table_match
        else PAPER_BLOCKED
    )
    report = {
        "schema_version": "know-place-author-raw-site-series/1.0",
        "status": "SCIENTIFIC_METRICS_COMPUTED",
        "structural_status": "PASS" if len(pair_reports) == 5 else "FAIL",
        "method_profile": "ARCHIVED_AUTHOR_SITE_SERIES_COMPATIBLE",
        "method_source": "Zenodo 10.5281/zenodo.22730419: code/make_pot_figure.py, code/make_fig_timeseries.py, code/reconcile_scale.py, code/polygon_null.py",
        "source_products_expected": 5,
        "source_products_processed": len(pair_reports),
        "author_site_series_table_comparison": {
            "status": "PASS_AT_ARCHIVE_ROUNDING" if comparison_count == 65 and comparison_passed == 65 else "MISMATCH",
            "checks_passed": comparison_passed,
            "checks_total": comparison_count,
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "table_s4_metric_cells_directly_covered": 45 if len(pair_reports) == 5 else 9 * len(pair_reports),
            "support_checks_not_in_table_s4": comparison_count - (9 * len(pair_reports)),
            "checks_are_full_table_s4_parity": False,
        },
        "author_p2_table_comparison": {
            "status": "PASS_AT_ARCHIVE_ROUNDING" if p2_table_match else "MISMATCH",
            "checks_passed": p2_passed,
            "checks_total": p2_total,
            "mismatch_count": len(p2_mismatches),
            "mismatches": p2_mismatches,
            "required_halo_pixels_per_side": 22,
            "method": "per-pixel DEM-interpolated author geometry; float32 SNR/magnitude-gated dE/dN; 41x41 local mean; 5x5 residual coherence computed on the halo before cropping the R raster to box and crown",
        },
        "author_profile": {
            "wide_bounds_lonlat": list(AUTHOR_WIDE_BOUNDS),
            "crown_bounds_lonlat": list(AUTHOR_CROWN_BOUNDS),
            "crown_reference_point_lonlat": list(AUTHOR_CROWN_POINT),
            "geometry_estimator": "P1 site series: median of each geometry component along height at nearest radarGrid XY cell to crown reference point",
            "P2_geometry_estimator": "author geometry.py per-pixel DEM-interpolated coefficients; coefficient tile cached from first exact pair and reused across the five same-grid pairs",
            "quality_gate": "finite projected dE/dN and SNR >= 5 and horizontal magnitude <= 10 m; correlation is not a gate",
            "bulk_reference": "component medians of valid pixels outside crown; apply only if valid outside-crown count > 200",
            "site_R": "5x5 mean resultant length with reflected edges and strict finite support > 0.5; crown R is recomputed on the crown-cropped field",
            "polygon_null": "post-hoc archive analysis; shared default_rng(20260907), 1200 candidates per pair, strict percentile inequalities and at least 60% valid target-crown cells",
            "geometry_height_m_from_exploratory_config_ignored": config.get("geometry_height_m"),
            "vertical_datum_correction_applied": False,
        },
        "paper_reproduction_status": paper_status,
        "hazard_detection_status": "NOT_EVALUATED",
        "pair_reports": pair_reports,
        "limitations": [
            "A match to exported site-field summaries is not native source-grid pixelwise crown-mask parity.",
            "The exact author crown rectangle is bounds-defined; aggregate counts do not prove pixel-for-pixel crown-mask parity on the original source grid.",
            "The P2 calculation uses a 22-pixel halo to avoid artificial crop-edge reflection; its archive comparison is separately reported and does not expand the 65-check P1/polygon-null gate.",
            "The processed-field polygon null is an archive post-hoc analysis, not a published-paper metric.",
            "The footprint-wide candidate screen and its per-pair rasters are not computed by this site-series runner.",
            "No hazard-detection precision, recall, false-alarm rate, lead time or operational value is inferred.",
        ],
    }
    _write_json(out / "author-raw-site-series-report.json", report)
    if csv_rows:
        with (out / "author-raw-site-series.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
            writer.writeheader()
            writer.writerows(csv_rows)
    return report


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--terrain-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_author_raw_site_series(args.config, args.out, terrain_root=args.terrain_root)
    except (GoffReadError, AuthorParityError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({
            "status": "AUTHOR_SITE_SERIES_ANALYSIS_FAILED",
            "error_type": type(exc).__name__,
            "error_code": str(exc).split(":", maxsplit=1)[0][:160],
            "paper_reproduction_status": PAPER_BLOCKED,
            "hazard_detection_status": "NOT_EVALUATED",
        }, ensure_ascii=False))
        return 1
    print(f"AUTHOR_RAW_SITE_SERIES_STATUS={report['status']}")
    print(f"STRUCTURAL_STATUS={report['structural_status']}")
    print(f"ARCHIVE_TABLE_PARITY={report['author_site_series_table_comparison']['status']}")
    print(f"ARCHIVE_TABLE_COMPARISONS={report['author_site_series_table_comparison']['checks_passed']}/{report['author_site_series_table_comparison']['checks_total']}")
    print(f"P2_ARCHIVE_TABLE_PARITY={report['author_p2_table_comparison']['status']}")
    print(f"P2_ARCHIVE_TABLE_COMPARISONS={report['author_p2_table_comparison']['checks_passed']}/{report['author_p2_table_comparison']['checks_total']}")
    print("PAPER_REPRODUCTION_STATUS=" + report["paper_reproduction_status"])
    print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
    return 0 if (
        report["structural_status"] == "PASS"
        and report["author_site_series_table_comparison"].get("status") == "PASS_AT_ARCHIVE_ROUNDING"
        and report["author_site_series_table_comparison"].get("checks_passed") == 65
        and report["author_site_series_table_comparison"].get("checks_total") == 65
        and report["author_p2_table_comparison"].get("status") == "PASS_AT_ARCHIVE_ROUNDING"
        and report["author_p2_table_comparison"].get("checks_passed") == 15
        and report["author_p2_table_comparison"].get("checks_total") == 15
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
