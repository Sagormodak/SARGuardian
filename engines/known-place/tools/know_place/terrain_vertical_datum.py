"""Versioned EGM2008 orthometric-to-WGS84 ellipsoidal height sensitivity.

This is intentionally separate from the archived/source-reproduction path. It
requires the named PROJ EGM2008 grid operation and refuses ballpark/no-op
vertical transformations. It never downloads raw NISAR GOFF inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
from pyproj.datadir import append_data_dir
from pyproj.transformer import TransformerGroup
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.warp import reproject
from rasterio.windows import Window

TARGET_CRS = "EPSG:32645"
TARGET_WIDTH = 4311
TARGET_HEIGHT = 4230
TARGET_TRANSFORM = Affine(80.0, 0.0, 126720.0, 0.0, -80.0, 3347280.0)
SOURCE_VERTICAL_CRS = "EPSG:9518"  # WGS 84 + EGM2008 height
TARGET_3D_CRS = "EPSG:4979"  # WGS 84 ellipsoidal height
REQUIRED_GRID = "us_nga_egm08_25.tif"


class VerticalDatumSensitivityError(RuntimeError):
    """Raised when exact grid-based height conversion cannot be established."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json_has_grid(value: Any, filename: str) -> bool:
    needle = filename.lower()
    if isinstance(value, str):
        return needle in value.lower()
    if isinstance(value, dict):
        return any(_json_has_grid(k, filename) or _json_has_grid(v, filename) for k, v in value.items())
    if isinstance(value, (tuple, list)):
        return any(_json_has_grid(item, filename) for item in value)
    return False


def select_required_vertical_transformer(grid_path: str | Path):
    """Select only the named, real grid-based EGM2008 -> ellipsoid operation."""
    grid = Path(grid_path)
    if not grid.is_file() or grid.stat().st_size == 0:
        raise VerticalDatumSensitivityError("EGM2008_GRID_MISSING_OR_EMPTY")
    if grid.name != REQUIRED_GRID:
        raise VerticalDatumSensitivityError("UNEXPECTED_EGM2008_GRID_FILENAME")
    append_data_dir(str(grid.parent))
    source = CRS.from_epsg(9518)
    target = CRS.from_epsg(4979)
    group = TransformerGroup(source, target, always_xy=True)
    matches = []
    for transformer in group.transformers:
        try:
            definition = transformer.to_proj4() or ""
        except Exception:
            definition = ""
        try:
            json_definition = transformer.to_json_dict()
        except Exception:
            json_definition = {}
        description = str(transformer.description or "")
        has_grid = REQUIRED_GRID.lower() in definition.lower() or _json_has_grid(
            json_definition, REQUIRED_GRID
        ) or REQUIRED_GRID.lower() in description.lower()
        no_ballpark = "ballpark" not in description.lower() and "ballpark" not in definition.lower()
        has_grid_operation = "vgridshift" in definition.lower() or _json_has_grid(
            json_definition, REQUIRED_GRID
        )
        if has_grid and no_ballpark and has_grid_operation:
            matches.append(transformer)
    if not matches:
        raise VerticalDatumSensitivityError(
            "EGM2008_EXACT_GRID_OPERATION_UNAVAILABLE_NO_BALLPARK_FALLBACK"
        )
    # Prefer a declared numerical accuracy where available; a negative/unknown
    # accuracy is ranked after a stated non-negative accuracy.
    matches.sort(key=lambda item: (item.accuracy < 0, item.accuracy if item.accuracy >= 0 else math.inf))
    transformer = matches[0]
    return transformer, {
        "source_crs": source.to_string(),
        "target_crs": target.to_string(),
        "description": transformer.description,
        "definition": transformer.to_proj4(),
        "accuracy_m": transformer.accuracy,
        "group_best_available": bool(group.best_available),
        "selected_grid": REQUIRED_GRID,
        "grid_sha256": _sha256(grid),
        "grid_bytes": grid.stat().st_size,
        "ballpark_or_noop_used": False,
        "other_unavailable_operations": [
            {"name": op.name, "accuracy_m": op.accuracy}
            for op in group.unavailable_operations
        ],
    }


def calculate_height_offset_m(orthometric_m: np.ndarray, ellipsoidal_m: np.ndarray) -> np.ndarray:
    """Return the signed, operation-derived ellipsoidal-minus-orthometric delta."""
    orthometric = np.asarray(orthometric_m, dtype=np.float64)
    ellipsoidal = np.asarray(ellipsoidal_m, dtype=np.float64)
    if orthometric.shape != ellipsoidal.shape:
        raise VerticalDatumSensitivityError("HEIGHT_ARRAY_SHAPE_MISMATCH")
    valid_h = np.isfinite(orthometric)
    valid_e = np.isfinite(ellipsoidal)
    if not np.array_equal(valid_h, valid_e):
        raise VerticalDatumSensitivityError("HEIGHT_CONVERSION_VALID_MASK_CHANGED")
    delta = np.full(orthometric.shape, np.nan, dtype=np.float64)
    delta[valid_h] = ellipsoidal[valid_h] - orthometric[valid_h]
    if np.any(~np.isfinite(delta[valid_h])):
        raise VerticalDatumSensitivityError("HEIGHT_OFFSET_NONFINITE")
    return delta


def _write_float32_geotiff(path: Path, array: np.ndarray, crs: str) -> None:
    profile = {
        "driver": "GTiff",
        "width": TARGET_WIDTH,
        "height": TARGET_HEIGHT,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": TARGET_TRANSFORM,
        "nodata": float("nan"),
        "compress": "deflate",
        "predictor": 3,
        "zlevel": 6,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.asarray(array, dtype=np.float32), 1)
        dst.update_tags(
            VERTICAL_DATUM_SENSITIVITY="EXPERIMENTAL_SEPARATE_FROM_AUTHOR_REPRODUCTION",
            VERTICAL_TRANSFORMATION="EGM2008 height to WGS 84 ellipsoidal height",
            HEIGHT_OFFSET_SIGN="ellipsoidal_height_m_minus_orthometric_height_m",
        )


def _stats(array: np.ndarray) -> dict[str, Any]:
    values = np.asarray(array, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise VerticalDatumSensitivityError("NO_FINITE_HEIGHT_RESULTS")
    q = np.percentile(finite, [0, 1, 5, 50, 95, 99, 100])
    return {
        "valid_cells": int(finite.size),
        "min_m": float(q[0]),
        "p01_m": float(q[1]),
        "p05_m": float(q[2]),
        "median_m": float(q[3]),
        "p95_m": float(q[4]),
        "p99_m": float(q[5]),
        "max_m": float(q[6]),
        "mean_m": float(np.mean(finite)),
        "std_m": float(np.std(finite)),
    }


def build_public_glo90_sensitivity(
    source_root: str | Path,
    geoid_grid_path: str | Path,
    output_root: str | Path,
    *,
    row_chunk_size: int = 96,
) -> dict[str, Any]:
    """Recreate the archived author target grid, then transform heights separately."""
    source_root = Path(source_root)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    tile_paths = sorted(source_root.rglob("Copernicus_DSM_COG_30_N*_00_E*_00_DEM.tif"))
    if len(tile_paths) != 16:
        raise VerticalDatumSensitivityError(f"EXPECTED_16_SOURCE_TILES_FOUND_{len(tile_paths)}")
    source_manifest_paths = list(source_root.rglob("copernicus-glo90-source-manifest.json"))
    if len(source_manifest_paths) != 1:
        raise VerticalDatumSensitivityError("SOURCE_TILE_MANIFEST_NOT_UNIQUE")
    source_manifest = json.loads(source_manifest_paths[0].read_text(encoding="utf-8"))
    if source_manifest.get("tile_count") != 16:
        raise VerticalDatumSensitivityError("SOURCE_TILE_MANIFEST_COUNT_MISMATCH")
    manifest_tiles = {row.get("file"): row for row in source_manifest.get("tile_manifest", [])}
    for path in tile_paths:
        expected = manifest_tiles.get(path.name)
        if not expected:
            raise VerticalDatumSensitivityError(f"SOURCE_TILE_NOT_PINNED_IN_MANIFEST:{path.name}")
        if path.stat().st_size != expected.get("bytes") or _sha256(path) != expected.get("sha256"):
            raise VerticalDatumSensitivityError(f"SOURCE_TILE_HASH_MISMATCH:{path.name}")

    # Validate this is the expected public PROJ EGM2008 grid and obtain a real
    # grid-based vertical transformer before creating any transformed outputs.
    grid_path = Path(geoid_grid_path)
    with rasterio.open(grid_path) as grid_ds:
        if grid_ds.count != 1 or grid_ds.width != 8640 or grid_ds.height != 4321:
            raise VerticalDatumSensitivityError("EGM2008_GRID_PROFILE_UNEXPECTED")
        if not grid_ds.crs or not grid_ds.crs.is_geographic:
            raise VerticalDatumSensitivityError("EGM2008_GRID_CRS_UNEXPECTED")
        grid_profile = {
            "driver": grid_ds.driver,
            "width": grid_ds.width,
            "height": grid_ds.height,
            "count": grid_ds.count,
            "dtype": grid_ds.dtypes[0],
            "crs": grid_ds.crs.to_string(),
            "bounds": [float(x) for x in grid_ds.bounds],
            "transform": [float(x) for x in grid_ds.transform[:6]],
        }
    vertical_transformer, operation = select_required_vertical_transformer(grid_path)

    # Mosaicking and target-grid reprojection mirror the archived prep_terrain.py.
    with rasterio.Env(GDAL_NUM_THREADS="1"):
        with rasterio.open(tile_paths[0]) as first:
            src_crs = first.crs
        with rasterio.open(tile_paths[0]) as _:
            datasets = [rasterio.open(path) for path in tile_paths]
        try:
            mosaic, mosaic_transform = merge(datasets)
            mosaic = np.asarray(mosaic, dtype=np.float32)
            mosaic[mosaic < -1000.0] = np.nan
        finally:
            for ds in datasets:
                ds.close()

    public_dem_path = output_root / "elev_m_current_public_glo90.tif"
    profile = {
        "driver": "GTiff",
        "width": TARGET_WIDTH,
        "height": TARGET_HEIGHT,
        "count": 1,
        "dtype": "float32",
        "crs": TARGET_CRS,
        "transform": TARGET_TRANSFORM,
        "nodata": float("nan"),
        "compress": "deflate",
        "predictor": 3,
        "zlevel": 6,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "BIGTIFF": "IF_SAFER",
    }
    target_array = np.full((TARGET_HEIGHT, TARGET_WIDTH), np.nan, dtype=np.float32)
    reproject(
        source=mosaic[0],
        destination=target_array,
        src_transform=mosaic_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=TARGET_TRANSFORM,
        dst_crs=TARGET_CRS,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        init_dest_nodata=True,
        num_threads=1,
    )
    with rasterio.open(public_dem_path, "w", **profile) as dst:
        dst.write(target_array, 1)
        dst.update_tags(
            SOURCE="Current public Copernicus DEM GLO-90 AWS mirror",
            PREPARATION="Sorted 16-tile mosaic + float32 + values below -1000 set to NaN + bilinear reproject to archived target grid",
            VERTICAL_REFERENCE="EGM2008 orthometric height",
            ORIGINAL_AUTHOR_TILE_BYTES="NOT_VERIFIED",
        )

    hae_path = output_root / "elev_m_hae_experimental.tif"
    delta_path = output_root / "ellipsoid_minus_egm2008_m.tif"
    height_delta = np.full((TARGET_HEIGHT, TARGET_WIDTH), np.nan, dtype=np.float32)
    height_hae = np.full((TARGET_HEIGHT, TARGET_WIDTH), np.nan, dtype=np.float32)
    geographic_transformer = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)
    all_cols = np.arange(TARGET_WIDTH, dtype=np.float64)
    x_centres = TARGET_TRANSFORM.c + TARGET_TRANSFORM.a * (all_cols + 0.5)
    valid_input_total = 0
    valid_output_total = 0
    for row_start in range(0, TARGET_HEIGHT, row_chunk_size):
        row_stop = min(TARGET_HEIGHT, row_start + row_chunk_size)
        row_numbers = np.arange(row_start, row_stop, dtype=np.float64)
        y_centres = TARGET_TRANSFORM.f + TARGET_TRANSFORM.e * (row_numbers + 0.5)
        xx, yy = np.meshgrid(x_centres, y_centres)
        lon, lat = geographic_transformer.transform(xx, yy)
        orthometric = target_array[row_start:row_stop].astype(np.float64, copy=False)
        valid = np.isfinite(orthometric)
        valid_input_total += int(np.count_nonzero(valid))
        lon_flat = np.asarray(lon, dtype=np.float64)
        lat_flat = np.asarray(lat, dtype=np.float64)
        hae_lon, hae_lat, ellipsoidal = vertical_transformer.transform(
            lon_flat, lat_flat, orthometric, errcheck=False
        )
        hae = np.asarray(ellipsoidal, dtype=np.float64)
        # The vertical operation must not invalidate a source-valid cell or
        # silently return the same height as a no-op.
        if np.any(~np.isfinite(hae[valid])):
            raise VerticalDatumSensitivityError(f"NONFINITE_TRANSFORMED_HEIGHTS_ROWS_{row_start}_{row_stop}")
        if np.allclose(hae[valid], orthometric[valid], rtol=0.0, atol=1e-8):
            raise VerticalDatumSensitivityError(f"NOOP_VERTICAL_TRANSFORM_ROWS_{row_start}_{row_stop}")
        delta = calculate_height_offset_m(orthometric, hae)
        if np.any(np.abs(delta[valid]) > 200.0):
            raise VerticalDatumSensitivityError(f"VERTICAL_OFFSET_OUT_OF_PLAUSIBLE_RANGE_ROWS_{row_start}_{row_stop}")
        # Round the experimental ellipsoidal DEM to its saved Float32
        # representation first; derive the stored offset from those exact saved
        # heights so reading the two GeoTIFFs back preserves HAE - H.
        hae_float32 = np.where(valid, hae, np.nan).astype(np.float32)
        delta_float32 = calculate_height_offset_m(orthometric, hae_float32.astype(np.float64)).astype(np.float32)
        height_hae[row_start:row_stop] = hae_float32
        height_delta[row_start:row_stop] = delta_float32
        valid_output_total += int(np.count_nonzero(np.isfinite(hae[valid])))
    if valid_input_total != valid_output_total:
        raise VerticalDatumSensitivityError("HEIGHT_CONVERSION_VALID_CELL_COUNT_MISMATCH")
    _write_float32_geotiff(hae_path, height_hae, TARGET_CRS)
    _write_float32_geotiff(delta_path, height_delta, TARGET_CRS)

    report = {
        "schema_version": "know-place-vertical-datum-sensitivity/1.0",
        "status": "PASS_EXPLICIT_EGM2008_GRID_OPERATION_SEPARATE_VERSIONED_EXPERIMENT",
        "purpose": "Quantify an explicit EGM2008-to-WGS84-ellipsoidal height transformation sensitivity without modifying the author/source-reproduction path.",
        "created_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "source_tiles": {
            "count": len(tile_paths),
            "manifest_sha256": _sha256(source_manifest_paths[0]),
            "all_tile_hashes_rechecked": True,
            "tile_artifact_run_id": source_manifest.get("workflow_run_id", 40052506016),
            "tile_artifact_name": "know-place-copernicus-glo90-source-tiles-40052506016-1",
            "original_author_tile_bytes": "UNVERIFIED",
        },
        "public_dem_replay": {
            "path": public_dem_path.name,
            "crs": TARGET_CRS,
            "width": TARGET_WIDTH,
            "height": TARGET_HEIGHT,
            "transform": [float(x) for x in TARGET_TRANSFORM[:6]],
            "valid_cells": int(np.count_nonzero(np.isfinite(target_array))),
            "height_stats_m": _stats(target_array),
            "resampling": "bilinear",
            "source_vertical_reference": "EGM2008 height (EPSG:3855 in compound EPSG:9518)",
        },
        "geoid_grid": {
            "path": grid_path.name,
            "profile": grid_profile,
            "sha256": _sha256(grid_path),
            "bytes": grid_path.stat().st_size,
            "source_url": "https://cdn.proj.org/us_nga_egm08_25.tif",
            "grid_resolution_arc_minutes": 2.5,
            "operation": operation,
        },
        "conversion": {
            "source_crs": SOURCE_VERTICAL_CRS,
            "target_crs": TARGET_3D_CRS,
            "method": "PROJ EPSG transformation using the named us_nga_egm08_25.tif vgridshift operation",
            "operation": operation["description"],
            "ballpark_or_noop_used": False,
            "vertical_transform_applied": True,
            "valid_input_cells": valid_input_total,
            "valid_output_cells": valid_output_total,
            "signed_offset_definition": "ellipsoidal_height_m - EGM2008_orthometric_height_m",
            "signed_offset_stats_m": _stats(height_delta),
            "ellipsoidal_height_stats_m": _stats(height_hae),
        },
        "outputs": {
            "public_replayed_dem": public_dem_path.name,
            "experimental_ellipsoidal_height_dem": hae_path.name,
            "signed_height_offset": delta_path.name,
        },
        "limits": [
            "The current public AWS-mirror tiles are not proven byte-identical to the author's original source tiles; their mosaic/warp reproduces the archived prepared DEM separately.",
            "This transformation is a versioned sensitivity, not a change to the source-reproduction path.",
            "The raw GOFF geometry cube is not included, so this report does not quantify the resulting cE/cN/kE/kN coefficient differences.",
            "No footprint screen, hazard detector, early-warning decision or paper-reproduction claim is run by this workflow.",
            "The selected operation is explicitly grid-based; the workflow refuses ballpark/no-op conversion.",
        ],
        "raw_nisar_goff_downloaded": False,
        "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
        "hazard_detection_status": "NOT_EVALUATED",
    }
    report_path = output_root / "terrain_vertical_datum_sensitivity.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--geoid-grid", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--row-chunk-size", type=int, default=96)
    args = parser.parse_args(argv)
    if not 1 <= args.row_chunk_size <= 512:
        raise SystemExit("ERROR=ROW_CHUNK_SIZE_OUT_OF_RANGE")
    report = build_public_glo90_sensitivity(
        args.source_root, args.geoid_grid, args.out, row_chunk_size=args.row_chunk_size
    )
    print("VERTICAL_DATUM_SENSITIVITY_STATUS=" + report["status"])
    print("EGM2008_GRID_SHA256=" + report["geoid_grid"]["sha256"])
    print("VERTICAL_OPERATION=" + report["conversion"]["operation"])
    print("OFFSET_STATS_M=" + json.dumps(report["conversion"]["signed_offset_stats_m"], sort_keys=True))
    print("RAW_NISAR_GOFF_DOWNLOADS=0")
    print("PAPER_REPRODUCTION_STATUS=" + report["paper_reproduction_status"])
    print("HAZARD_DETECTION_STATUS=" + report["hazard_detection_status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
