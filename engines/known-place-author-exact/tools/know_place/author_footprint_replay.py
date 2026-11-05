"""Full-footprint, exact-author GOFF screen replay.

This module joins the verified raw GOFF reader, author-derived per-pixel geometry
kernel, footprint screen, persistence/component filter, terrain directional
attribution and archived output comparisons. It performs no downloads. The
caller must supply five source-hash-verified P05023 granules, the pinned author
archive, and the archive's exact prepared terrain rasters.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import zipfile
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.io import MemoryFile

from .analyze import _load_and_validate_inputs, load_config
from .footprint_geometry import build_per_pixel_coefficients
from .footprint_screen import (
    EXPECTED_INTERVALS,
    SCREEN_SCHEMA,
    aggregate_persistent_pairs,
    filter_persistent_components,
    project_per_pixel_offsets,
    residual_directional_coherence,
    screen_pair,
)
from .goff_io import GoffReadError, read_geometry_cubes, read_raw_goff

AUTHOR_ARCHIVE_SHA256 = "002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3"
EXPECTED_TERRAIN_SHA256 = {
    "elev_m.tif": "d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1",
    "slope_deg.tif": "e94d44a7f6e2078f59d7e6234ed075eaf1dda1683ca411a97bf749ab5cdfce7a",
    "downslope_az_deg.tif": "2fae2feabca24b56acc61d4fad1d408192245c3061278d1f4844d3b853c6314b",
}
EXPECTED_SOURCE_GRID_SHAPE = (4230, 4311)
EXPECTED_SOURCE_EPSG = 32645
EXPECTED_POSTING_M = 80.0
EXPECTED_TRANSFORM = Affine(80.0, 0.0, 126720.0, 0.0, -80.0, 3347280.0)
GEOMETRY_SOURCE_SHA256 = "0f056c46f2f5f9418dd1735b666edaa5c055514694fcd2c66490e09b6bb63004"
SCREEN_SOURCE_SHA256 = "60e4238b9a10510f52a4673939a9708bf513d8bae460ba797d2dd27a1357d7c9"
CANDIDATE_ATTRIBUTES_SOURCE_SHA256 = "dde30645bed46f7b44f6d0469c8224e1b8f630726fd9849f11471880edc6e196"
FIX_ZONAL_ATTRS_SOURCE_SHA256 = "3614d1f632e35dbcdecab8389f38e50674a087813cbefdaa2b8c027b0ebe18cb"
PARAMETERS_SOURCE_SHA256 = "85743e828c4d684046acf43bdb0bfbc8b8c194626aacad8fd58e154e925d8e76"
NODATA = -9999.0
P2_OR_SITE_PAPER_STATUS = "PARTIAL_AUTHOR_FOOTPRINT_SCREEN_NOT_REPRODUCED"
CANDIDATE_METRIC_COLUMNS = (
    "area_km2", "n_px", "n_epochs", "anom_m", "R", "score",
    "disp_az", "res_mag_m", "R_raw", "R_res", "mag_m",
    "elev_m", "slope_deg", "downslope_az", "range_az",
    "d_downslope", "d_range",
)


class FootprintReplayError(ValueError):
    """Full-footprint replay input fails a scientific or provenance contract."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_array(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    return hashlib.sha256(array.view(np.uint8)).hexdigest()


def _geometry_fingerprint(cubes: Any) -> dict[str, Any]:
    rows: dict[str, Any] = {
        "epsg": int(cubes.metadata_epsg),
        "group_path": str(cubes.group_path),
        "axes": {},
        "cubes": {},
    }
    for name in ("height_m", "y_m", "x_m"):
        arr = np.asarray(getattr(cubes, name))
        rows["axes"][name] = {
            "shape": list(arr.shape),
            "sha256": _hash_array(arr),
        }
    for name in ("incidence_deg", "los_x", "los_y", "along_track_x", "along_track_y"):
        arr = np.asarray(getattr(cubes, name))
        rows["cubes"][name] = {
            "shape": list(arr.shape),
            "sha256": _hash_array(arr),
        }
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    rows["fingerprint_sha256"] = hashlib.sha256(payload).hexdigest()
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FootprintReplayError("JSON_ROOT_NOT_OBJECT")
    return value


def _iso_date(compact_date: str) -> str:
    """Convert screen-kernel YYYYMMDD dates to manifest/config ISO dates."""
    if len(compact_date) != 8 or not compact_date.isdigit():
        raise FootprintReplayError("EXPECTED_INTERVAL_DATE_NOT_YYYYMMDD")
    return f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}"


def _manifest_interval(interval: tuple[str, str]) -> str:
    """Represent an expected pair in the acquisition manifest's ISO date format."""
    reference_date, secondary_date = interval
    return f"{_iso_date(reference_date)}/{_iso_date(secondary_date)}"


def _validate_source_manifest(path: Path) -> dict[str, dict[str, Any]]:
    manifest = _read_json(path)
    if manifest.get("status") != "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED":
        raise FootprintReplayError("AUTHOR_SOURCE_MANIFEST_NOT_PASS")
    if manifest.get("author_release_id") != "P05023":
        raise FootprintReplayError("AUTHOR_RELEASE_NOT_P05023")
    if manifest.get("source_downloads") != 5 or manifest.get("author_exact_source_sha256_count") != 5:
        raise FootprintReplayError("SOURCE_DOWNLOAD_OR_HASH_COUNT_NOT_FIVE")
    if manifest.get("source_products_grid_validated") != 5:
        raise FootprintReplayError("SOURCE_GRID_VALIDATION_COUNT_NOT_FIVE")
    expected_manifest_intervals = [_manifest_interval(interval) for interval in EXPECTED_INTERVALS]
    if manifest.get("expected_intervals") != expected_manifest_intervals:
        raise FootprintReplayError("SOURCE_MANIFEST_INTERVAL_ORDER_MISMATCH")
    products = manifest.get("products")
    if not isinstance(products, list) or len(products) != 5:
        raise FootprintReplayError("SOURCE_MANIFEST_PRODUCT_LIST_NOT_FIVE")
    indexed: dict[str, dict[str, Any]] = {}
    for row in products:
        if not isinstance(row, dict):
            raise FootprintReplayError("SOURCE_MANIFEST_PRODUCT_ROW_INVALID")
        interval = row.get("interval")
        if interval not in manifest["expected_intervals"] or interval in indexed:
            raise FootprintReplayError("SOURCE_MANIFEST_INTERVAL_DUPLICATE_OR_INVALID")
        if row.get("release_id") != "P05023" or row.get("download_status") != "PASS":
            raise FootprintReplayError(f"SOURCE_MANIFEST_PRODUCT_NOT_EXACT_P05023:{interval}")
        if row.get("grid_validation_status") != "PASS":
            raise FootprintReplayError(f"SOURCE_MANIFEST_GRID_NOT_VALIDATED:{interval}")
        if row.get("source_bytes", 0) <= 0 or len(str(row.get("source_sha256", ""))) != 64:
            raise FootprintReplayError(f"SOURCE_MANIFEST_HASH_OR_SIZE_MISSING:{interval}")
        if row.get("grid_epsg") != EXPECTED_SOURCE_EPSG:
            raise FootprintReplayError(f"SOURCE_MANIFEST_EPSG_MISMATCH:{interval}")
        if (row.get("grid_width"), row.get("grid_height")) != (4311, 4230):
            raise FootprintReplayError(f"SOURCE_MANIFEST_SHAPE_MISMATCH:{interval}")
        if abs(float(row.get("grid_x_posting_m", math.nan)) - EXPECTED_POSTING_M) > 1e-4:
            raise FootprintReplayError(f"SOURCE_MANIFEST_X_POSTING_MISMATCH:{interval}")
        if abs(abs(float(row.get("grid_y_posting_m", math.nan))) - EXPECTED_POSTING_M) > 1e-4:
            raise FootprintReplayError(f"SOURCE_MANIFEST_Y_POSTING_MISMATCH:{interval}")
        indexed[interval] = row
    if list(indexed) != manifest["expected_intervals"]:
        raise FootprintReplayError("SOURCE_MANIFEST_ORDER_IS_NOT_CANONICAL")
    return indexed


def _validate_author_archive(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FootprintReplayError("AUTHOR_ARCHIVE_NOT_FOUND")
    digest = sha256_file(path)
    if digest != AUTHOR_ARCHIVE_SHA256:
        raise FootprintReplayError("AUTHOR_ARCHIVE_SHA256_MISMATCH")
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            required = {
                "rasters/mean_anomaly_m.tif",
                "rasters/mean_coherence_R.tif",
                "rasters/n_epochs_flagged.tif",
                "inventory/candidates_attributed.csv",
                "tables/TableS6_screen_params.json",
                "tables/TableS7_all_validated_zones.csv",
                "code/candidate_attributes.py",
                "code/fix_zonal_attrs.py",
            }
            names = set(archive.namelist())
            if bad:
                raise FootprintReplayError(f"AUTHOR_ARCHIVE_MEMBER_CRC_FAILED:{bad}")
            if not required.issubset(names):
                raise FootprintReplayError("AUTHOR_ARCHIVE_GOLDEN_SCREEN_FILES_MISSING")
            return {
                "sha256": digest,
                "bytes": path.stat().st_size,
                "zip_crc": "PASS",
                "required_screen_assets_present": True,
                "terrain_elev_sha256_in_archive": _sha256_member(archive, "terrain/elev_m.tif"),
                "terrain_slope_sha256_in_archive": _sha256_member(archive, "terrain/slope_deg.tif"),
                "terrain_downslope_sha256_in_archive": _sha256_member(archive, "terrain/downslope_az_deg.tif"),
                "candidate_attributes_py_sha256": _sha256_member(archive, "code/candidate_attributes.py"),
                "fix_zonal_attrs_py_sha256": _sha256_member(archive, "code/fix_zonal_attrs.py"),
                "postprocess_score_formula": "n_epochs(zone max) * anom_m(zone mean rounded to 3 decimals) * R_res(zone mean over flagged observations)",
            }
    except zipfile.BadZipFile as exc:
        raise FootprintReplayError("AUTHOR_ARCHIVE_IS_NOT_A_VALID_ZIP") from exc


def _sha256_member(archive: zipfile.ZipFile, name: str) -> str:
    try:
        return hashlib.sha256(archive.read(name)).hexdigest()
    except KeyError as exc:
        raise FootprintReplayError(f"AUTHOR_ARCHIVE_MEMBER_MISSING:{name}") from exc


def _load_terrain(terrain_root: Path, *, verify_hashes: bool = True) -> tuple[dict[str, np.ndarray], dict[str, Any], Any]:
    if not terrain_root.is_dir():
        raise FootprintReplayError("TERRAIN_ROOT_NOT_FOUND")
    rasters: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] = {}
    reference_profile: dict[str, Any] | None = None
    reference_transform = None
    for name, expected_sha in EXPECTED_TERRAIN_SHA256.items():
        path = terrain_root / name
        if not path.is_file():
            raise FootprintReplayError(f"PINNED_TERRAIN_FILE_MISSING:{name}")
        digest = sha256_file(path)
        if verify_hashes and digest != expected_sha:
            raise FootprintReplayError(f"PINNED_TERRAIN_SHA256_MISMATCH:{name}")
        with rasterio.open(path) as src:
            epsg = src.crs.to_epsg() if src.crs else None
            if epsg != EXPECTED_SOURCE_EPSG:
                raise FootprintReplayError(f"TERRAIN_CRS_MISMATCH:{name}")
            if (src.height, src.width) != EXPECTED_SOURCE_GRID_SHAPE:
                raise FootprintReplayError(f"TERRAIN_SHAPE_MISMATCH:{name}")
            transform = src.transform
            if not np.allclose(
                [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
                [EXPECTED_TRANSFORM.a, EXPECTED_TRANSFORM.b, EXPECTED_TRANSFORM.c,
                 EXPECTED_TRANSFORM.d, EXPECTED_TRANSFORM.e, EXPECTED_TRANSFORM.f],
                rtol=0.0, atol=1e-9,
            ):
                raise FootprintReplayError(f"TERRAIN_AFFINE_MISMATCH:{name}")
            if src.count != 1 or src.dtypes[0] != "float32":
                raise FootprintReplayError(f"TERRAIN_BAND_TYPE_MISMATCH:{name}")
            arr = src.read(1).astype(np.float32, copy=False)
            if src.nodata is not None:
                arr = arr.copy()
                arr[arr == np.float32(src.nodata)] = np.nan
            if name == "elev_m.tif":
                reference_profile = src.profile.copy()
                reference_transform = transform
            elif reference_transform is None or transform != reference_transform:
                raise FootprintReplayError(f"TERRAIN_GRIDS_NOT_IDENTICAL:{name}")
            rasters[name] = arr
            metadata[name] = {
                "sha256": digest,
                "bytes": path.stat().st_size,
                "shape": [src.height, src.width],
                "crs": src.crs.to_string(),
                "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
                "nodata": src.nodata,
            }
    if reference_profile is None:
        raise FootprintReplayError("TERRAIN_ELEVATION_PROFILE_MISSING")
    return rasters, metadata, reference_profile


def _write_multiband_geotiff(path: Path, arrays: list[Any], profile: dict[str, Any], descriptions: tuple[str, ...]) -> None:
    if len(arrays) != len(descriptions):
        raise FootprintReplayError("OUTPUT_BAND_DESCRIPTION_COUNT_MISMATCH")
    output_profile = profile.copy()
    output_profile.update({
        "driver": "GTiff", "count": len(arrays), "dtype": "float32",
        "nodata": NODATA, "compress": "deflate", "predictor": 3,
        "tiled": True, "blockxsize": 256, "blockysize": 256,
        "BIGTIFF": "IF_SAFER",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **output_profile) as dst:
        for index, (array, description) in enumerate(zip(arrays, descriptions, strict=True), 1):
            values = np.asarray(array, dtype=np.float32)
            values = values.copy()
            values[~np.isfinite(values)] = np.float32(NODATA)
            dst.write(values, index)
            dst.set_band_description(index, description)


def _write_single_geotiff(path: Path, array: Any, profile: dict[str, Any], description: str) -> None:
    values = np.asarray(array, dtype=np.float32).copy()
    values[~np.isfinite(values)] = np.float32(NODATA)
    _write_multiband_geotiff(path, [values], profile, (description,))


def _compare_raster_arrays(actual: np.ndarray, expected: np.ndarray, *, tolerance: float) -> dict[str, Any]:
    a = np.asarray(actual, dtype=np.float32)
    b = np.asarray(expected, dtype=np.float32)
    if a.shape != b.shape:
        return {"status": "FAIL", "reason": "SHAPE_MISMATCH",
                "actual_shape": list(a.shape), "expected_shape": list(b.shape)}
    finite_a, finite_b = np.isfinite(a), np.isfinite(b)
    mismatch = int(np.count_nonzero(finite_a ^ finite_b))
    valid = finite_a & finite_b
    delta = np.abs(a[valid].astype(np.float64) - b[valid].astype(np.float64))
    maximum = float(delta.max()) if delta.size else None
    passed = mismatch == 0 and bool(delta.size) and bool(np.all(delta <= tolerance))
    return {
        "status": "PASS" if passed else "FAIL",
        "finite_mask_mismatch_count": mismatch,
        "finite_cells_compared": int(valid.sum()),
        "max_absolute_difference": maximum,
        "absolute_tolerance": tolerance,
    }


def compare_footprint_outputs_to_author_archive(
    output_root: Path, archive_path: Path, *, tolerance: float = 1e-5
) -> dict[str, Any]:
    """Compare the three generated full-footprint rasters to source archive golden outputs."""
    expected_sha = _validate_author_archive(archive_path)["sha256"]
    members = (
        ("n_epochs_flagged.tif", "rasters/n_epochs_flagged.tif", "flagged epochs", 0.0),
        ("mean_anomaly_m.tif", "rasters/mean_anomaly_m.tif", "mean magnitude anomaly", tolerance),
        ("mean_coherence_R.tif", "rasters/mean_coherence_R.tif", "mean residual coherence R", tolerance),
    )
    checks = []
    with zipfile.ZipFile(archive_path) as archive:
        for local_name, member_name, label, allowed_error in members:
            local_path = output_root / local_name
            if not local_path.is_file():
                raise FootprintReplayError(f"FOOTPRINT_OUTPUT_RASTER_MISSING:{local_name}")
            with rasterio.open(local_path) as actual:
                actual_values = actual.read(1, masked=True).filled(np.nan).astype(np.float32)
                actual_meta = {
                    "shape": [actual.height, actual.width],
                    "epsg": actual.crs.to_epsg() if actual.crs else None,
                    "transform": [actual.transform.a, actual.transform.b, actual.transform.c,
                                  actual.transform.d, actual.transform.e, actual.transform.f],
                }
            with MemoryFile(archive.read(member_name)) as memory:
                with memory.open() as expected:
                    expected_values = expected.read(1, masked=True).filled(np.nan).astype(np.float32)
                    expected_meta = {
                        "shape": [expected.height, expected.width],
                        "epsg": expected.crs.to_epsg() if expected.crs else None,
                        "transform": [expected.transform.a, expected.transform.b, expected.transform.c,
                                      expected.transform.d, expected.transform.e, expected.transform.f],
                    }
            metadata_match = (
                actual_meta["shape"] == expected_meta["shape"]
                and actual_meta["epsg"] == expected_meta["epsg"] == EXPECTED_SOURCE_EPSG
                and np.allclose(actual_meta["transform"], expected_meta["transform"], rtol=0.0, atol=1e-9)
            )
            value_check = _compare_raster_arrays(actual_values, expected_values, tolerance=allowed_error)
            checks.append({
                "raster": local_name, "archive_member": member_name, "label": label,
                "metadata_match": bool(metadata_match), "metadata_actual": actual_meta,
                "metadata_expected": expected_meta, "value_comparison": value_check,
                "status": "PASS" if metadata_match and value_check["status"] == "PASS" else "FAIL",
            })
    return {
        "status": "PASS" if all(row["status"] == "PASS" for row in checks) else "MISMATCH",
        "archive_sha256": expected_sha,
        "raster_count": len(checks),
        "rasters_passed": sum(row["status"] == "PASS" for row in checks),
        "comparisons": checks,
        "absolute_tolerance": tolerance,
        "notes": [
            "n_epochs_flagged must match exactly cell-by-cell; the two float rasters are compared at 1e-5 m / R.",
            "Aggregate raster parity does not by itself validate the full candidate attribute inventory or prospective hazard detection.",
        ],
    }


def _validated_quality_zone_count(comparison: dict[str, Any]) -> int:
    """Read the computed final-quality zone count from the Table S7 comparison schema."""
    value = comparison.get("computed_quality_zone_count")
    if not isinstance(value, int):
        raise FootprintReplayError("VALIDATED_QUALITY_ZONE_COUNT_MISSING")
    return value


def _angle_difference_degrees(a: float, b: float) -> float:
    return float(abs((float(a) - float(b) + 180.0) % 360.0 - 180.0))


def _candidate_table(
    labels: np.ndarray,
    epoch_count: np.ndarray,
    anomaly: np.ndarray,
    coherence: np.ndarray,
    terrain: dict[str, np.ndarray],
    coefficient: dict[str, Any],
    pair_raster_paths: list[Path],
    transform: Affine,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Summarize connected candidate zones using the archive's weighted-over-hit convention."""
    height, width = labels.shape
    flat_labels = labels.ravel()
    selected_flat = np.flatnonzero(flat_labels > 0)
    if selected_flat.size == 0:
        return [], {"component_count": 0, "directional_pass_count": 0}
    zone_ids = flat_labels[selected_flat].astype(np.int32)
    max_zone = int(zone_ids.max())
    rows_all, cols_all = np.divmod(selected_flat, width)
    counts = np.bincount(zone_ids, minlength=max_zone + 1).astype(np.int64)
    row_sum = np.bincount(zone_ids, weights=rows_all.astype(np.float64), minlength=max_zone + 1)
    col_sum = np.bincount(zone_ids, weights=cols_all.astype(np.float64), minlength=max_zone + 1)
    mean_rows = np.divide(row_sum, np.maximum(counts, 1))
    mean_cols = np.divide(col_sum, np.maximum(counts, 1))

    pixel_e = transform.c + (cols_all.astype(np.float64) + 0.5) * transform.a
    pixel_n = transform.f + (rows_all.astype(np.float64) + 0.5) * transform.e
    terrain_sums: dict[str, np.ndarray] = {}
    for name in ("elev_m.tif", "slope_deg.tif"):
        values = terrain[name].ravel()[selected_flat].astype(np.float64)
        good = np.isfinite(values)
        terrain_sums[name] = np.bincount(zone_ids[good], weights=values[good], minlength=max_zone + 1)
        terrain_sums[name + "_n"] = np.bincount(zone_ids[good], minlength=max_zone + 1).astype(np.float64)
    downslope = terrain["downslope_az_deg.tif"].ravel()[selected_flat].astype(np.float64)
    good_ds = np.isfinite(downslope)
    ds_rad = np.radians(downslope[good_ds])
    ds_c = np.bincount(zone_ids[good_ds], weights=np.cos(ds_rad), minlength=max_zone + 1)
    ds_s = np.bincount(zone_ids[good_ds], weights=np.sin(ds_rad), minlength=max_zone + 1)
    range_e = np.asarray(coefficient["kE"]).ravel()[selected_flat].astype(np.float64)
    range_n = np.asarray(coefficient["kN"]).ravel()[selected_flat].astype(np.float64)
    range_az = np.degrees(np.arctan2(range_e, range_n)) % 360.0
    rg_rad = np.radians(range_az)
    rg_c = np.bincount(zone_ids, weights=np.cos(rg_rad), minlength=max_zone + 1)
    rg_s = np.bincount(zone_ids, weights=np.sin(rg_rad), minlength=max_zone + 1)

    # The author code sums each selected cell's per-pair hit observations, then
    # divides by all finite hit observations in that zone; pairs are not equally
    # weighted after first averaging by epoch.
    obs_sums = {name: np.zeros(max_zone + 1, dtype=np.float64)
                for name in ("rE", "rN", "R_raw", "R_res", "mag")}
    obs_counts = {name: np.zeros(max_zone + 1, dtype=np.float64) for name in obs_sums}
    for raster_path in pair_raster_paths:
        with rasterio.open(raster_path) as src:
            hit = src.read(1) > 0.5
            selected = hit & (labels > 0)
            if not selected.any():
                continue
            zid = labels[selected].astype(np.int32)
            for name, band in (("rE", 5), ("rN", 6), ("R_raw", 7), ("R_res", 3), ("mag", 8)):
                vals = src.read(band)[selected].astype(np.float64)
                good = np.isfinite(vals) & (vals != NODATA)
                if not good.any():
                    continue
                obs_sums[name] += np.bincount(zid[good], weights=vals[good], minlength=max_zone + 1)
                obs_counts[name] += np.bincount(zid[good], minlength=max_zone + 1)

    to_lonlat = Transformer.from_crs("EPSG:32645", "EPSG:4326", always_xy=True)
    rows: list[dict[str, Any]] = []
    for zone_id in range(1, max_zone + 1):
        npx = int(counts[zone_id])
        if npx < 10:
            continue
        row_centre = int(min(max(math.floor(mean_rows[zone_id] + 0.5), 0), height - 1))
        col_centre = int(min(max(math.floor(mean_cols[zone_id] + 0.5), 0), width - 1))
        centre_x = transform.c + (mean_cols[zone_id] + 0.5) * transform.a
        centre_y = transform.f + (mean_rows[zone_id] + 0.5) * transform.e
        lon, lat = to_lonlat.transform(centre_x, centre_y)
        zone_mask = labels == zone_id
        zone_epochs = np.asarray(epoch_count[zone_mask], dtype=np.float64)
        n_epochs = int(np.max(np.nan_to_num(zone_epochs, nan=0.0))) if zone_epochs.size else 0
        zone_anomaly = np.asarray(anomaly[zone_mask], dtype=np.float64)
        zone_anomaly = zone_anomaly[np.isfinite(zone_anomaly)]
        anomaly_rounded = float(np.round(np.mean(zone_anomaly), 3)) if zone_anomaly.size else math.nan

        # R remains the centroid-sampled screen value from wide_screen.py. The
        # final attributed inventory is then post-processed by fix_zonal_attrs.py:
        # replace n_epochs/anom_m with zonal max/mean and rebuild score with R_res.
        R = float(np.nan_to_num(coherence[row_centre, col_centre]))
        R_rounded = round(R, 3)
        def observed(name: str) -> float:
            cnt = float(obs_counts[name][zone_id])
            return float(obs_sums[name][zone_id] / cnt) if cnt > 0 else math.nan
        mean_east, mean_north = observed("rE"), observed("rN")
        disp_az = float(np.degrees(np.arctan2(mean_east, mean_north)) % 360.0) if np.isfinite(mean_east + mean_north) else math.nan
        res_mag = float(np.hypot(mean_east, mean_north)) if np.isfinite(mean_east + mean_north) else math.nan
        elev_n, slope_n = terrain_sums["elev_m.tif_n"][zone_id], terrain_sums["slope_deg.tif_n"][zone_id]
        elev = terrain_sums["elev_m.tif"][zone_id] / elev_n if elev_n else math.nan
        slope = terrain_sums["slope_deg.tif"][zone_id] / slope_n if slope_n else math.nan
        down_az = float(np.degrees(np.arctan2(ds_s[zone_id], ds_c[zone_id])) % 360.0) if (ds_c[zone_id] != 0 or ds_s[zone_id] != 0) else math.nan
        gr_az = float(np.degrees(np.arctan2(rg_s[zone_id], rg_c[zone_id])) % 360.0) if (rg_c[zone_id] != 0 or rg_s[zone_id] != 0) else math.nan
        d_down = _angle_difference_degrees(disp_az, down_az) if np.isfinite(disp_az) and np.isfinite(down_az) else math.nan
        d_range = _angle_difference_degrees(disp_az, gr_az) if np.isfinite(disp_az) and np.isfinite(gr_az) else math.nan
        R_res = observed("R_res")
        # This is the deposited final score formula in fix_zonal_attrs.py, not
        # the provisional centroid score written by wide_screen.py.
        score = float(n_epochs * anomaly_rounded * R_res) if np.isfinite(anomaly_rounded + R_res) else math.nan
        valid_directional = bool(np.isfinite(d_down) and d_down < 45.0)
        quality_pass = bool(np.isfinite(R_res) and R_res >= 0.75 and valid_directional)
        rows.append({
            "component_id": zone_id,
            "lon": round(float(lon), 5), "lat": round(float(lat), 5),
            "area_km2": round(npx * transform.a * abs(transform.e) / 1e6, 4),
            "n_px": npx, "n_epochs": n_epochs,
            "anom_m": anomaly_rounded, "R": R_rounded, "score": score,
            "disp_az": disp_az, "res_mag_m": res_mag,
            "R_raw": observed("R_raw"), "R_res": R_res, "mag_m": observed("mag"),
            "elev_m": float(elev), "slope_deg": float(slope),
            "downslope_az": down_az, "range_az": gr_az,
            "d_downslope": d_down, "d_range": d_range,
            "valid_directional": valid_directional,
            "quality": quality_pass,
            "center_row": row_centre, "center_col": col_centre,
        })
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows, {
        "component_count": len(rows),
        "directional_pass_count": sum(bool(row["valid_directional"]) for row in rows),
        "quality_pass_count": sum(bool(row["quality"]) for row in rows),
        "minimum_component_pixels": 10,
        "directional_validation_max_misfit_deg_strict": 45.0,
        "centroid_policy": "mean of cell centres, equivalent to polygon centroid for union of equal-size grid cells",
        "attribute_weighting": "all finite hit-pixel observations pooled over pairs, matching source candidate_attributes.py",
        "final_zonal_postprocess": {
            "source_script": "code/fix_zonal_attrs.py",
            "source_script_sha256": FIX_ZONAL_ATTRS_SOURCE_SHA256,
            "n_epochs": "maximum n_epochs_flagged across pixels within the zone",
            "anom_m": "mean mean_anomaly_m across finite pixels in the zone, rounded to three decimals",
            "score": "n_epochs * anom_m * R_res",
            "quality": "R_res >= 0.75 and d_downslope < 45 degrees",
        },
    }


def compare_candidate_inventory(
    computed_rows: list[dict[str, Any]], archive_path: Path, *, numeric_tolerance: float = 1e-4
) -> dict[str, Any]:
    """Compare all 106 screen candidates and their source-archived final quality flag."""
    with zipfile.ZipFile(archive_path) as archive:
        text = archive.read("inventory/candidates_attributed.csv").decode("utf-8")
    expected_rows = list(csv.DictReader(text.splitlines()))
    by_key: dict[tuple[float, float], dict[str, Any]] = {}
    for row in computed_rows:
        key = (round(float(row["lon"]), 5), round(float(row["lat"]), 5))
        if key in by_key:
            raise FootprintReplayError("DUPLICATE_COMPUTED_CANDIDATE_CENTROID")
        by_key[key] = row
    mismatches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    matched_rows_in_archive_order: list[tuple[dict[str, Any], dict[str, Any]]] = []
    maximum_error: dict[str, float] = {name: 0.0 for name in CANDIDATE_METRIC_COLUMNS}
    expected_quality_pass = 0
    computed_quality_pass = sum(bool(row["quality"]) for row in computed_rows)
    archived_residual_score_match_count = 0
    score_formula_rows: list[dict[str, Any]] = []
    for expected in expected_rows:
        key = (round(float(expected["lon"]), 5), round(float(expected["lat"]), 5))
        actual = by_key.pop(key, None)
        if actual is None:
            missing.append({"lon": key[0], "lat": key[1]})
            continue
        matched_rows_in_archive_order.append((expected, actual))
        expected_score = float(expected["score"])
        postprocessed_score = float(actual["n_epochs"]) * float(actual["anom_m"]) * float(actual["R_res"])
        postprocess_score_matches = abs(expected_score - postprocessed_score) <= numeric_tolerance
        archived_residual_score_match_count += int(postprocess_score_matches)
        if not postprocess_score_matches:
            score_formula_rows.append({
                "lon": key[0], "lat": key[1], "archive_score": expected_score,
                "computed_final_score_n_epochs_times_zonal_anom_times_R_res": postprocessed_score,
                "postprocessed_formula_matches_archive": postprocess_score_matches,
            })
        for metric in CANDIDATE_METRIC_COLUMNS:
            if metric in {"n_px", "n_epochs"}:
                ok = int(float(actual[metric])) == int(float(expected[metric]))
                delta = abs(float(actual[metric]) - float(expected[metric]))
            else:
                ex, ac = float(expected[metric]), float(actual[metric])
                delta = abs(ex - ac)
                ok = np.isfinite(ex) and np.isfinite(ac) and delta <= numeric_tolerance
            maximum_error[metric] = max(maximum_error[metric], float(delta))
            if not ok:
                mismatches.append({
                    "lon": key[0], "lat": key[1], "metric": metric,
                    "expected": float(expected[metric]), "actual": float(actual[metric]),
                    "absolute_difference": float(delta),
                })
        quality_raw = str(expected.get("quality", "")).strip().casefold()
        if quality_raw not in {"true", "false"}:
            mismatches.append({
                "lon": key[0], "lat": key[1], "metric": "quality",
                "expected": expected.get("quality"), "actual": bool(actual["quality"]),
                "reason": "ARCHIVE_QUALITY_FLAG_INVALID",
            })
        else:
            expected_quality = quality_raw == "true"
            expected_quality_pass += int(expected_quality)
            if expected_quality != bool(actual["quality"]):
                mismatches.append({
                    "lon": key[0], "lat": key[1], "metric": "quality",
                    "expected": expected_quality, "actual": bool(actual["quality"]),
                    "reason": "DIRECTIONAL_QUALITY_FLAG_MISMATCH",
                })
    extra = [{"lon": key[0], "lat": key[1]} for key in sorted(by_key)]
    # fix_zonal_attrs.py sorts the final GPKG/CSV by the post-processed score.
    # Verify rank-order parity separately from per-row numeric parity. Score
    # differences no larger than the declared tolerance are treated as ties so
    # tiny float-rounding changes do not create a false rank inversion.
    expected_order_scores = [float(expected["score"]) for expected, _ in matched_rows_in_archive_order]
    computed_order_scores = [float(actual["score"]) for _, actual in matched_rows_in_archive_order]
    source_order_sorted = all(
        expected_order_scores[i] >= expected_order_scores[i + 1] - numeric_tolerance
        for i in range(max(0, len(expected_order_scores) - 1))
    )
    rank_inversions: list[dict[str, Any]] = []
    for i in range(len(matched_rows_in_archive_order)):
        expected_i, actual_i = matched_rows_in_archive_order[i]
        for j in range(i + 1, len(matched_rows_in_archive_order)):
            expected_j, actual_j = matched_rows_in_archive_order[j]
            expected_gap = float(expected_i["score"]) - float(expected_j["score"])
            if expected_gap > numeric_tolerance and float(actual_i["score"]) + numeric_tolerance < float(actual_j["score"]):
                rank_inversions.append({
                    "earlier_source_rank": i + 1, "later_source_rank": j + 1,
                    "earlier_centroid": [round(float(expected_i["lon"]), 5), round(float(expected_i["lat"]), 5)],
                    "later_centroid": [round(float(expected_j["lon"]), 5), round(float(expected_j["lat"]), 5)],
                    "expected_score_gap": expected_gap,
                    "computed_score_earlier": float(actual_i["score"]),
                    "computed_score_later": float(actual_j["score"]),
                })
    ranking_order = {
        "status": "PASS" if source_order_sorted and not rank_inversions and len(matched_rows_in_archive_order) == len(expected_rows) else "MISMATCH",
        "source_inventory_sorted_descending_by_final_score": source_order_sorted,
        "matched_rows_in_source_order": len(matched_rows_in_archive_order),
        "strict_score_order_pairs_checked": sum(
            1 for i in range(len(expected_order_scores)) for j in range(i + 1, len(expected_order_scores))
            if expected_order_scores[i] - expected_order_scores[j] > numeric_tolerance
        ),
        "rank_inversion_count": len(rank_inversions),
        "rank_inversions": rank_inversions[:25],
        "tie_tolerance": numeric_tolerance,
    }
    mismatch_count_by_metric: dict[str, int] = {}
    for row in mismatches:
        metric = str(row.get("metric", "UNSPECIFIED"))
        mismatch_count_by_metric[metric] = mismatch_count_by_metric.get(metric, 0) + 1
    passed = (
        not missing and not extra and not mismatches
        and ranking_order["status"] == "PASS"
        and len(expected_rows) == 106 and len(computed_rows) == 106
        and expected_quality_pass == 101 and computed_quality_pass == 101
    )
    return {
        "status": "PASS" if passed else "MISMATCH",
        "ranking_order_comparison": ranking_order,
        "expected_candidate_count": len(expected_rows),
        "computed_candidate_count": len(computed_rows),
        "matched_centroid_count": len(expected_rows) - len(missing),
        "expected_quality_pass_count": expected_quality_pass,
        "computed_quality_pass_count": computed_quality_pass,
        "missing_expected": missing,
        "extra_computed": extra,
        "mismatch_count": len(mismatches),
        "mismatch_count_by_metric": mismatch_count_by_metric,
        "mismatches": mismatches[:200],
        "max_absolute_error_by_metric": maximum_error,
        "numeric_tolerance": numeric_tolerance,
        "compared_columns": [*CANDIDATE_METRIC_COLUMNS, "quality"],
        "score_formula_audit": {
            "provisional_screen_formula": "centroid-sampled n_epochs * anom_m * R in code/wide_screen.py; intentionally provisional",
            "final_inventory_formula": "zone-max n_epochs * zone-mean anom_m (rounded to 3 decimals) * zone-mean R_res, as implemented by code/fix_zonal_attrs.py",
            "postprocess_script_sha256": FIX_ZONAL_ATTRS_SOURCE_SHA256,
            "archive_rows": len(expected_rows),
            "postprocessed_formula_matches": archived_residual_score_match_count,
            "status": (
                "PASS_POSTPROCESSED_AUTHOR_SCORE_CONVENTION"
                if archived_residual_score_match_count == len(expected_rows)
                else "POSTPROCESSED_SCORE_FORMULA_MISMATCH"
            ),
            "examples": score_formula_rows[:25],
        },
        "glacier_overlay_not_compared": True,
        "glacier_overlay_note": "The exact RGI 6.0 polygon assets are not part of this author archive; glacier class and nearest-glacier distance are not inferred by this comparison.",
    }


def compare_validated_zone_table(
    computed_rows: list[dict[str, Any]], archive_path: Path
) -> dict[str, Any]:
    """Compare the 101 final quality-passing candidates with Table S7 at displayed precision."""
    with zipfile.ZipFile(archive_path) as archive:
        text = archive.read("tables/TableS7_all_validated_zones.csv").decode("utf-8")
    expected_rows = list(csv.DictReader(text.splitlines()))
    computed = [row for row in computed_rows if bool(row["quality"])]
    by_key: dict[tuple[float, float], dict[str, Any]] = {}
    for row in computed:
        key = (round(float(row["lon"]), 5), round(float(row["lat"]), 5))
        if key in by_key:
            raise FootprintReplayError("DUPLICATE_VALIDATED_ZONE_CENTROID")
        by_key[key] = row

    precision = {
        "lon": 5, "lat": 5, "area_km2": 4, "n_epochs": None,
        "res_mag_m": 2, "disp_az": 1, "downslope_az": 1,
        "d_downslope": 1, "R_res": 3, "elev_m": 0, "slope_deg": 1,
    }
    mismatches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for expected in expected_rows:
        key = (round(float(expected["lon"]), 5), round(float(expected["lat"]), 5))
        actual = by_key.pop(key, None)
        if actual is None:
            missing.append({"lon": key[0], "lat": key[1]})
            continue
        for field, decimals in precision.items():
            target = float(expected[field])
            value = float(actual[field])
            ok = int(value) == int(target) if decimals is None else round(value, decimals) == round(target, decimals)
            if not ok:
                mismatches.append({
                    "lon": key[0], "lat": key[1], "metric": field,
                    "expected": target, "actual": value, "comparison_decimals": decimals,
                })
    extra = [{"lon": key[0], "lat": key[1]} for key in sorted(by_key)]
    passed = not missing and not extra and not mismatches and len(expected_rows) == 101 and len(computed) == 101
    return {
        "status": "PASS" if passed else "MISMATCH",
        "expected_zone_count": len(expected_rows),
        "computed_quality_zone_count": len(computed),
        "matched_centroid_count": len(expected_rows) - len(missing),
        "missing_expected": missing,
        "extra_computed": extra,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:200],
        "compared_columns": list(precision),
        "excluded_columns": ["glacier", "RGIId", "d_glac_m"],
        "excluded_columns_note": "These fields require the exact RGI 6.0 polygon source assets, which are not contained in the author archive; no glacier overlay is inferred.",
        "comparison_policy": "numeric values are compared at the displayed precision in Table S7",
    }

def run_author_footprint_replay(
    *,
    config_path: str | Path,
    source_manifest_path: str | Path,
    terrain_root: str | Path,
    author_archive_path: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Run all five exact author GOFF footprints and compare archive golden outputs."""
    config, config_dir = load_config(config_path)
    products = _load_and_validate_inputs(config, config_dir)
    manifest_rows = _validate_source_manifest(Path(source_manifest_path).resolve())
    archive_path = Path(author_archive_path).resolve()
    archive_meta = _validate_author_archive(archive_path)
    terrain, terrain_meta, profile = _load_terrain(Path(terrain_root).resolve())
    out = Path(output_root).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (int(profile["height"]), int(profile["width"])) != EXPECTED_SOURCE_GRID_SHAPE:
        raise FootprintReplayError("TARGET_PROFILE_SHAPE_INVALID")
    transform = profile["transform"]
    if transform != EXPECTED_TRANSFORM:
        raise FootprintReplayError("TARGET_PROFILE_AFFINE_INVALID")

    # Exact geocoded GOFF coordinates must be pixel-centre coordinates on the
    # archived terrain grid (raster affine describes the pixel edges).
    x_centres = transform.c + (np.arange(EXPECTED_SOURCE_GRID_SHAPE[1], dtype=np.float64) + 0.5) * transform.a
    y_centres = transform.f + (np.arange(EXPECTED_SOURCE_GRID_SHAPE[0], dtype=np.float64) + 0.5) * transform.e
    for item in products:
        grid = item["grid"]
        if grid.epsg != EXPECTED_SOURCE_EPSG or grid.grid_shape != EXPECTED_SOURCE_GRID_SHAPE:
            raise FootprintReplayError(f"SOURCE_GRID_IDENTITY_MISMATCH:{grid.identity.granule_name}")
        if not np.allclose(grid.x_coordinates_m, x_centres, rtol=0.0, atol=1e-4):
            raise FootprintReplayError(f"GOFF_X_CENTRES_NOT_ALIGNED_TO_TERRAIN:{grid.identity.granule_name}")
        if not np.allclose(grid.y_coordinates_m, y_centres, rtol=0.0, atol=1e-4):
            raise FootprintReplayError(f"GOFF_Y_CENTRES_NOT_ALIGNED_TO_TERRAIN:{grid.identity.granule_name}")

    pair_reports: list[dict[str, Any]] = []
    pair_result_inputs: list[dict[str, Any]] = []
    pair_raster_paths: list[Path] = []
    coefficient_result: dict[str, Any] | None = None
    reference_geometry_fingerprint: dict[str, Any] | None = None
    source_hashes: list[dict[str, Any]] = []
    for index, (item, interval) in enumerate(zip(products, EXPECTED_INTERVALS, strict=True)):
        interval_key = f"{interval[0]}__{interval[1]}"
        manifest_interval = _manifest_interval(interval)
        source_row = manifest_rows[manifest_interval]
        source_path = Path(item["path"]).resolve()
        if source_path.name != source_row.get("source_filename"):
            raise FootprintReplayError(f"SOURCE_FILENAME_DOES_NOT_MATCH_MANIFEST:{interval_key}")
        if item["reference_date"] != _iso_date(interval[0]) or item["secondary_date"] != _iso_date(interval[1]):
            raise FootprintReplayError(f"SOURCE_PAIR_ORDER_MISMATCH:{interval_key}")
        raw = read_raw_goff(
            source_path, polarization="HH", layer=2,
            expected_track="098", expected_direction="A", expected_processing="PR",
            expected_grid=item["grid"],
        )
        if raw.source_sha256 != source_row["source_sha256"] or len(Path(item["path"]).name) == 0:
            raise FootprintReplayError(f"SOURCE_SHA256_DOES_NOT_MATCH_MANIFEST:{interval_key}")
        if source_path.stat().st_size != int(source_row["source_bytes"]):
            raise FootprintReplayError(f"SOURCE_BYTE_COUNT_DOES_NOT_MATCH_MANIFEST:{interval_key}")
        cubes = read_geometry_cubes(source_path, expected_epsg=raw.epsg)
        fingerprint = _geometry_fingerprint(cubes)
        geometry_matches_first_pair = (
            reference_geometry_fingerprint is None
            or fingerprint["fingerprint_sha256"] == reference_geometry_fingerprint["fingerprint_sha256"]
        )
        if reference_geometry_fingerprint is None:
            reference_geometry_fingerprint = fingerprint
            # Match the archived geometry.py contract exactly: geometry.load()
            # constructs/caches coefficients from the first pair's radarGrid
            # and the prepared DEM, and every later pair reuses that cache.
            coefficient_result = build_per_pixel_coefficients(
                cubes.height_m, cubes.y_m, cubes.x_m,
                cubes.incidence_deg, cubes.los_x, cubes.los_y,
                cubes.along_track_x, cubes.along_track_y,
                terrain["elev_m.tif"], transform,
                dem_transform=transform,
                target_epsg=EXPECTED_SOURCE_EPSG,
                geometry_metadata_epsg=cubes.metadata_epsg,
                dem_epsg=EXPECTED_SOURCE_EPSG,
                dem_vertical_reference="EPSG:9518 WGS 84 + EGM2008 height, Copernicus GLO-90 prepared elevation",
                geometry_height_reference="NISAR radarGrid heightAboveEllipsoid (HAE)",
                # The archived source uses prepared GLO-90 values directly and
                # does not apply a vertical conversion. Preserve that behavior
                # as an explicit source-method override, never as datum-corrected truth.
                allow_vertical_reference_mismatch=True,
                dem_nodata=-9999.0,
                block_rows=300,
            )
            if coefficient_result.get("status") != "PER_PIXEL_GEOMETRY_COEFFICIENTS_COMPUTED":
                raise FootprintReplayError("PER_PIXEL_GEOMETRY_BUILDER_NOT_COMPLETE")
        # Do not fail merely because later pairs contain different geometry
        # metadata: the author's script explicitly reuses the first pair's
        # geometry cache for the entire five-pair screen. Record differences
        # as provenance diagnostics while using that first-pair cache.
        
        assert coefficient_result is not None
        coeffs = coefficient_result["coefficients"]
        projection = project_per_pixel_offsets(
            raw.along_track_m, raw.slant_range_m, raw.snr,
            coeffs["cE"], coeffs["cN"], coeffs["kE"], coeffs["kN"],
        )
        raw_R = residual_directional_coherence(projection["dE_m"], projection["dN_m"])
        screen = screen_pair(projection, interval=interval)
        pair_path = out / "pairs" / f"{interval[0]}__{interval[1]}_footprint_screen.tif"
        _write_multiband_geotiff(
            pair_path,
            [
                screen["hit_mask"].astype(np.float32),
                screen["hit_magnitude_anomaly_m"],
                screen["hit_residual_R"],
                screen["hit_z_score"],
                screen["hit_residual_east_m"],
                screen["hit_residual_north_m"],
                np.where(screen["hit_mask"], raw_R, np.nan).astype(np.float32),
                np.where(screen["hit_mask"], projection["magnitude_m"], np.nan).astype(np.float32),
            ],
            profile,
            (
                "hit_mask_0_or_1",
                "hit_magnitude_anomaly_m",
                "hit_residual_coherence_R",
                "hit_z_score",
                "hit_residual_east_m",
                "hit_residual_north_m",
                "hit_raw_field_coherence_R",
                "hit_absolute_magnitude_m",
            ),
        )
        pair_raster_paths.append(pair_path)
        pair_result_inputs.append({
            "schema_version": SCREEN_SCHEMA,
            "status": "CANDIDATE_MOVEMENT_SCREEN_COMPUTED",
            "interval": interval,
            "hit_mask": screen["hit_mask"],
            "hit_magnitude_anomaly_m": screen["hit_magnitude_anomaly_m"],
            "hit_residual_R": screen["hit_residual_R"],
        })
        bulk_east = float(np.nanmedian(projection["dE_m"]))
        bulk_north = float(np.nanmedian(projection["dN_m"]))
        pair_reports.append({
            "interval": f"{interval[0]}->{interval[1]}",
            "granule_name": raw.identity.granule_name,
            "release_id": raw.identity.release_id,
            "source_bytes": int(source_row["source_bytes"]),
            "source_sha256": raw.source_sha256,
            "source_grid": {
                "epsg": int(raw.epsg), "shape": list(raw.along_track_m.shape),
                "x_posting_m": float(np.median(np.diff(raw.x_coordinates_m))),
                "y_posting_m": float(np.median(np.diff(raw.y_coordinates_m))),
            },
            "geometry_fingerprint_sha256": fingerprint["fingerprint_sha256"],
            "geometry_fields_identical_to_first_pair": geometry_matches_first_pair,
            "projection_status": projection["status"],
            "quality_gate_counts": projection["quality_gate_counts"],
            "screen_status": screen["status"],
            "screen_counts": screen["counts"],
            "bulk_offset_median_m": [bulk_east, bulk_north],
            "pair_output": str(pair_path.relative_to(out)),
            "pair_output_sha256": sha256_file(pair_path),
        })
        source_hashes.append({
            "interval": f"{interval[0]}/{interval[1]}",
            "filename": source_path.name,
            "bytes": raw.source_bytes if hasattr(raw, "source_bytes") else int(source_row["source_bytes"]),
            "sha256": raw.source_sha256,
            "matches_manifest": True,
        })
        del raw, cubes, projection, raw_R, screen

    if len(pair_result_inputs) != 5:
        raise FootprintReplayError("EXACTLY_FIVE_FOOTPRINT_SCREEN_RESULTS_REQUIRED")
    persistence = aggregate_persistent_pairs(pair_result_inputs, minimum_epochs=2)
    components = filter_persistent_components(persistence["persistent_mask"], minimum_component_pixels=10)
    labels = components["component_labels"]
    _write_single_geotiff(out / "n_epochs_flagged.tif", persistence["n_epochs_flagged"], profile, "number of author intervals flagged (0-5)")
    _write_single_geotiff(out / "mean_anomaly_m.tif", persistence["mean_hit_magnitude_anomaly_m"], profile, "mean magnitude anomaly over hit epochs (m)")
    _write_single_geotiff(out / "mean_coherence_R.tif", persistence["mean_hit_residual_R"], profile, "mean residual directional coherence R over hit epochs")
    _write_single_geotiff(out / "candidate_component_labels.tif", labels.astype(np.float32), profile, "4-connected persistent components with at least 10 pixels")

    candidate_rows, candidate_summary = _candidate_table(
        labels, persistence["n_epochs_flagged"],
        persistence["mean_hit_magnitude_anomaly_m"], persistence["mean_hit_residual_R"],
        terrain, coeffs, pair_raster_paths, transform,
    )
    candidate_rows = sorted(candidate_rows, key=lambda row: row["score"], reverse=True)
    candidate_csv = out / "candidate_screen_zones.csv"
    candidate_fields = list(candidate_rows[0].keys()) if candidate_rows else [
        "component_id", "lon", "lat", "area_km2", "n_px", "n_epochs", "anom_m", "R",
        "score", "disp_az", "res_mag_m", "R_raw", "R_res", "mag_m", "elev_m",
        "slope_deg", "downslope_az", "range_az", "d_downslope", "d_range",
        "valid_directional", "quality", "center_row", "center_col",
    ]
    with candidate_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(candidate_rows)
    directional_rows = [row for row in candidate_rows if row["valid_directional"]]
    directional_csv = out / "candidate_directional_zones.csv"
    with directional_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(directional_rows)
    quality_rows = [row for row in candidate_rows if row["quality"]]
    quality_csv = out / "candidate_quality_zones.csv"
    with quality_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(quality_rows)

    raster_comparison = compare_footprint_outputs_to_author_archive(out, archive_path, tolerance=1e-5)
    inventory_comparison = compare_candidate_inventory(candidate_rows, archive_path)
    validated_zone_comparison = compare_validated_zone_table(candidate_rows, archive_path)
    coefficient_hashes = {
        name: _hash_array(values) for name, values in coefficient_result["coefficients"].items()
    }
    exact_screen_count_pass = (
        candidate_summary["component_count"] == 106
        and candidate_summary["quality_pass_count"] == 101
        and inventory_comparison.get("computed_quality_pass_count") == 101
        and persistence["counts"]["cells_persistent"] >= sum(
            row["n_px"] for row in candidate_rows
        )
    )
    footprint_status = (
        "PASS_AUTHOR_AGGREGATE_RASTERS_AND_CANDIDATE_INVENTORY"
        if raster_comparison["status"] == "PASS" and inventory_comparison["status"] == "PASS" and validated_zone_comparison["status"] == "PASS" and exact_screen_count_pass
        else "MISMATCH_AUTHOR_FOOTPRINT_PARITY"
    )
    report = {
        "schema_version": "know-place-author-footprint-replay/1.0",
        "status": "FOOTPRINT_SCREEN_COMPUTED",
        "structural_status": "PASS" if len(pair_reports) == 5 else "FAIL",
        "source_profile": "EXACT_AUTHOR_P05023_T098_ASC_HH_LAYER2",
        "source_products_expected": 5,
        "source_products_processed": len(pair_reports),
        "source_product_hash_validation": "PASS" if all(row["matches_manifest"] for row in source_hashes) else "FAIL",
        "source_products": source_hashes,
        "author_archive": archive_meta,
        "source_code_attribution": {
            "geometry_py_sha256": GEOMETRY_SOURCE_SHA256,
            "wide_screen_py_sha256": SCREEN_SOURCE_SHA256,
            "screen_parameters_json_sha256": PARAMETERS_SOURCE_SHA256,
            "license": "CC BY 4.0; the separate CC BY-NC 4.0 runout extent was not used",
        },
        "target_grid": {
            "shape": list(EXPECTED_SOURCE_GRID_SHAPE), "epsg": EXPECTED_SOURCE_EPSG,
            "transform": [transform.a, transform.b, transform.c, transform.d, transform.e, transform.f],
            "posting_m": EXPECTED_POSTING_M,
        },
        "terrain_assets": terrain_meta,
        "geometry": {
            "metadata_fingerprint_sha256": reference_geometry_fingerprint["fingerprint_sha256"],
            "source_method_geometry_cache_policy": "Use first pair's radarGrid geometry for all five pairs, matching code/geometry.py geometry.load() cache behavior.",
            "per_pair_geometry_fingerprints": [
                {"interval": row["interval"], "fingerprint_sha256": row["geometry_fingerprint_sha256"],
                 "identical_to_first_pair": row["geometry_fields_identical_to_first_pair"]}
                for row in pair_reports
            ],
            "coefficient_sha256": coefficient_hashes,
            "coefficient_status": coefficient_result["status"],
            "coefficient_diagnostics": coefficient_result["diagnostics"],
            "vertical_reference": coefficient_result["vertical_reference"],
            "all_five_pairs_geometry_identical": all(row["geometry_fields_identical_to_first_pair"] for row in pair_reports),
        },
        "pair_reports": pair_reports,
        "persistence": {
            **persistence["counts"],
            **components["counts"],
            "required_intervals": [f"{a}->{b}" for a, b in EXPECTED_INTERVALS],
            "minimum_epochs": 2,
            "minimum_component_pixels": 10,
        },
        "candidate_summary": candidate_summary,
        "candidate_csv": {
            "screen_zones": candidate_csv.name, "screen_zone_count": len(candidate_rows),
            "directional_zones": directional_csv.name,
            "directional_zone_count": len(directional_rows),
            "quality_zones": quality_csv.name,
            "quality_zone_count": len(quality_rows),
        },
        "author_aggregate_raster_comparison": raster_comparison,
        "author_inventory_comparison": inventory_comparison,
        "author_validated_zone_table_comparison": validated_zone_comparison,
        "footprint_screen_parity_status": footprint_status,
        "paper_reproduction_status": (
            "PARTIAL_AUTHOR_FOOTPRINT_SCREEN_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED"
            if footprint_status == "PASS_AUTHOR_AGGREGATE_RASTERS_AND_CANDIDATE_INVENTORY"
            else P2_OR_SITE_PAPER_STATUS
        ),
        "hazard_detection_status": "NOT_EVALUATED",
        "operational_warning_status": "NOT_IMPLEMENTED",
        "retention_note": "This runner does not delete raw sources or upload data. The enclosing workflow must verify derived-only Drive retention before deleting temporary HDF5.",
        "limitations": [
            "The archived displacement-null generator and draw-level values are not included in the supplied source archive; the three displacement-null Table S4 fields remain unverified.",
            "The candidate CSV comparison verifies numerical attributes of the author's 101 directional candidates; glacier/nearest-glacier attribution is not recomputed because the exact RGI 6.0 polygon inputs are not packaged in this archive.",
            "The published footprint screen identifies coherent moving surfaces, not landslide probability or failure prediction. Detection precision, recall, false alarms and lead time remain unevaluated.",
            "A source-method vertical-reference override reproduces the published code's direct use of the prepared DEM; it does not assert that DEM height is datum-corrected to the radarGrid height axis.",
        ],
    }
    report_path = out / "author-footprint-replay-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print("AUTHOR_FOOTPRINT_SCREEN_STATUS=" + footprint_status)
    print("FOOTPRINT_PAIR_COUNT=5")
    print("AUTHOR_AGGREGATE_RASTERS=" + raster_comparison["status"])
    print("AUTHOR_106_CANDIDATE_INVENTORY=" + inventory_comparison["status"])
    print("AUTHOR_101_VALIDATED_ZONE_TABLE=" + validated_zone_comparison["status"])
    print(f"CANDIDATE_ZONES_PRE_DIRECTION={len(candidate_rows)}")
    print(f"CANDIDATE_ZONES_DIRECTIONAL_PASS={len(directional_rows)}")
    print("AUTHOR_INVENTORY_COUNT=" + str(inventory_comparison["computed_candidate_count"]))
    print("AUTHOR_VALIDATED_ZONE_COUNT=" + str(_validated_quality_zone_count(validated_zone_comparison)))
    print("PAPER_REPRODUCTION_STATUS=" + report["paper_reproduction_status"])
    print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
    print("REPORT=" + str(report_path))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--source-manifest", required=True, type=Path)
    parser.add_argument("--terrain-root", required=True, type=Path)
    parser.add_argument("--author-archive", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_author_footprint_replay(
            config_path=args.config,
            source_manifest_path=args.source_manifest,
            terrain_root=args.terrain_root,
            author_archive_path=args.author_archive,
            output_root=args.out,
        )
    except (FootprintReplayError, GoffReadError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        failure = {
            "schema_version": "know-place-author-footprint-replay/1.0",
            "status": "FOOTPRINT_REPLAY_FAILED",
            "error_type": type(exc).__name__,
            "error_code": str(exc).split(":", 1)[0][:180],
            "paper_reproduction_status": P2_OR_SITE_PAPER_STATUS,
            "hazard_detection_status": "NOT_EVALUATED",
        }
        (args.out / "author-footprint-replay-report.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("AUTHOR_FOOTPRINT_SCREEN_STATUS=FAILED")
        print("ERROR=" + failure["error_code"])
        print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
        return 1
    # Output-comparison mismatches are preserved as a completed scientific
    # result so the enclosing workflow can package/upload the audit and verify
    # raw cleanup before its final gate reports the precise parity blocker.
    return 0 if report.get("status") == "FOOTPRINT_SCREEN_COMPUTED" and report.get("structural_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
