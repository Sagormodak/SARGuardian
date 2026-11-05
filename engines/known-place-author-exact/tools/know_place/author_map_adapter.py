"""Render the interactive AOI map from a retained exact-author measurement artifact.

This adapter is presentation-only. It reads no raw GOFF HDF5 and never runs a
new measurement. The map overlay is an approximate geographic preview; numeric
statistics and native-grid/source evidence remain authoritative.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile
from typing import Any

import numpy as np

from .interactive_map import write_interactive_map


class AuthorMapAdapterError(ValueError):
    """The retained exact-author bundle cannot safely produce a map."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorMapAdapterError(f"JSON_INPUT_INVALID:{path.name}") from exc
    if not isinstance(value, dict):
        raise AuthorMapAdapterError(f"JSON_ROOT_NOT_OBJECT:{path.name}")
    return value


def _parse_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise AuthorMapAdapterError(f"CSV_INPUT_MISSING:{path.name}") from exc
    if not rows:
        raise AuthorMapAdapterError(f"CSV_HAS_NO_ROWS:{path.name}")
    return rows


def _required_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AuthorMapAdapterError(f"SHA256_INVALID:{label}")
    return value


def _date_token(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AuthorMapAdapterError("DATE_INVALID")
    return value.replace("-", "")


def _finite_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AuthorMapAdapterError(f"NUMBER_INVALID:{label}") from exc
    if not math.isfinite(result):
        raise AuthorMapAdapterError(f"NUMBER_NONFINITE:{label}")
    return result


def _preview_from_npz(payload: bytes, pair_label: str) -> tuple[dict[str, Any], int, int]:
    try:
        with np.load(io.BytesIO(payload), allow_pickle=False) as data:
            needed = {
                "horizontal_magnitude_m", "valid_mask", "crown_mask",
                "x_coordinates_m", "y_coordinates_m",
            }
            if not needed.issubset(data.files):
                raise AuthorMapAdapterError(f"DIAGNOSTIC_ARRAY_MISSING:{pair_label}")
            magnitude = np.asarray(data["horizontal_magnitude_m"], dtype=np.float64)
            valid = np.asarray(data["valid_mask"], dtype=bool)
            crown = np.asarray(data["crown_mask"], dtype=bool)
            x = np.asarray(data["x_coordinates_m"], dtype=np.float64)
            y = np.asarray(data["y_coordinates_m"], dtype=np.float64)
    except (OSError, ValueError, KeyError) as exc:
        if isinstance(exc, AuthorMapAdapterError):
            raise
        raise AuthorMapAdapterError(f"DIAGNOSTIC_NPZ_INVALID:{pair_label}") from exc

    if magnitude.ndim != 2 or magnitude.shape != valid.shape or magnitude.shape != crown.shape:
        raise AuthorMapAdapterError(f"DIAGNOSTIC_ARRAY_SHAPE_MISMATCH:{pair_label}")
    height, width = magnitude.shape
    if not (0 < width <= 160 and 0 < height <= 160 and width * height <= 20_000):
        raise AuthorMapAdapterError(f"PREVIEW_DIMENSIONS_EXCEED_SAFE_LIMIT:{pair_label}")
    if x.ndim != 1 or y.ndim != 1 or len(x) != width or len(y) != height:
        raise AuthorMapAdapterError(f"DIAGNOSTIC_COORDINATE_SHAPE_MISMATCH:{pair_label}")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise AuthorMapAdapterError(f"DIAGNOSTIC_COORDINATES_NONFINITE:{pair_label}")
    dx = np.diff(x)
    dy = np.diff(y)
    if not dx.size or not dy.size or not np.allclose(dx, np.median(dx), rtol=1e-6, atol=1e-4):
        raise AuthorMapAdapterError(f"X_GRID_NOT_REGULAR:{pair_label}")
    if not np.allclose(dy, np.median(dy), rtol=1e-6, atol=1e-4):
        raise AuthorMapAdapterError(f"Y_GRID_NOT_REGULAR:{pair_label}")
    if np.median(dx) <= 0 or np.median(dy) >= 0:
        raise AuthorMapAdapterError(f"GRID_AXIS_ORIENTATION_UNEXPECTED:{pair_label}")

    valid_crown = int(np.count_nonzero(valid & crown))
    crown_cells = int(np.count_nonzero(crown))
    if crown_cells <= 0 or valid_crown <= 0:
        raise AuthorMapAdapterError(f"CROWN_PREVIEW_HAS_NO_VALID_SUPPORT:{pair_label}")

    values: list[list[float | None]] = []
    for row in range(height):
        line: list[float | None] = []
        for col in range(width):
            value = float(magnitude[row, col])
            # Only the selected crown/AOI support region is colour-filled; scene pixels outside the mask remain transparent.
            line.append(value if valid[row, col] and crown[row, col] and math.isfinite(value) else None)
        values.append(line)

    preview = {
        "values": values,
        # These are first-pixel-centre coordinates in native EPSG:32645.
        # interactive_map.py densifies/project bounds and labels the warp as approximate.
        "min_x_m": float(x[0]),
        "max_y_m": float(y[0]),
        "pixel_size_x_m": float(np.median(dx)),
        "pixel_size_y_m": float(abs(np.median(dy))),
        "support_mask_label": "Crown-mask only; outside-crown and invalid pixels are transparent.",
    }
    return preview, valid_crown, crown_cells


def build_author_map_report(artifact_root: str | Path, source_run_id: int) -> dict[str, Any]:
    """Build the existing interactive-map schema from a verified derived-only artifact."""
    root = Path(artifact_root).resolve()
    if not root.is_dir():
        raise AuthorMapAdapterError("ARTIFACT_ROOT_NOT_DIRECTORY")
    if source_run_id <= 0:
        raise AuthorMapAdapterError("SOURCE_RUN_ID_INVALID")
    if any(path.is_file() and path.suffix.lower() in {".h5", ".hdf5"} for path in root.rglob("*")):
        raise AuthorMapAdapterError("RAW_HDF5_FOUND_IN_ARTIFACT_ROOT")

    manifest = _read_json(root / "author-exact-source-manifest.json")
    analysis = _read_json(root / "know-place-analysis-report.json")
    csv_rows = _parse_csv(root / "know-place-analysis-pairs.csv")
    archive_path = root / "author-exact-derived-results.zip"
    if manifest.get("status") != "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED":
        raise AuthorMapAdapterError("SOURCE_MANIFEST_NOT_PASS")
    if manifest.get("author_release_id") != "P05023" or manifest.get("source_sha256_count") != 5:
        raise AuthorMapAdapterError("SOURCE_MANIFEST_NOT_EXACT_P05023")
    if analysis.get("status") != "SCIENTIFIC_METRICS_COMPUTED" or analysis.get("structural_status") != "PASS":
        raise AuthorMapAdapterError("ANALYSIS_REPORT_NOT_COMPLETE")
    if analysis.get("hazard_detection_status") != "NOT_EVALUATED":
        raise AuthorMapAdapterError("HAZARD_STATUS_MUST_REMAIN_NOT_EVALUATED")
    if not archive_path.is_file():
        raise AuthorMapAdapterError("DERIVED_RESULTS_ZIP_MISSING")

    products = manifest.get("products")
    if not isinstance(products, list) or len(products) != 5:
        raise AuthorMapAdapterError("SOURCE_MANIFEST_PRODUCT_COUNT_INVALID")
    by_stem: dict[str, dict[str, Any]] = {}
    for product in products:
        if not isinstance(product, dict) or product.get("release_id") != "P05023":
            raise AuthorMapAdapterError("NON_AUTHOR_RELEASE_IN_SOURCE_MANIFEST")
        if product.get("download_status") != "PASS" or product.get("grid_validation_status") != "PASS":
            raise AuthorMapAdapterError("SOURCE_PRODUCT_NOT_VERIFIED")
        digest = _required_sha(product.get("source_sha256"), str(product.get("granule_name")))
        if digest != str(product.get("source_sha256")):
            raise AuthorMapAdapterError("SOURCE_SHA256_MISMATCH")
        stem = str(product.get("granule_name", ""))
        if not stem or stem in by_stem:
            raise AuthorMapAdapterError("SOURCE_GRANULE_DUPLICATE_OR_EMPTY")
        by_stem[stem] = product

    scope = analysis.get("run_scope", {})
    crown_wkt = scope.get("crown_wkt") if isinstance(scope, dict) else None
    if not isinstance(crown_wkt, str) or not crown_wkt.upper().startswith("POLYGON"):
        raise AuthorMapAdapterError("CROWN_WKT_MISSING")
    if scope.get("crown_geometry_kind") != "bounding-box-approximation":
        raise AuthorMapAdapterError("CROWN_GEOMETRY_KIND_CHANGED")

    pair_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    dates: list[str] = []
    with zipfile.ZipFile(archive_path, "r") as archive:
        if archive.testzip() is not None:
            raise AuthorMapAdapterError("DERIVED_RESULTS_ZIP_CRC_FAILURE")
        names = set(archive.namelist())
        if any(Path(name).suffix.lower() in {".h5", ".hdf5"} for name in names):
            raise AuthorMapAdapterError("RAW_HDF5_FOUND_IN_DERIVED_ZIP")
        for row in csv_rows:
            reference = row.get("reference_date", "")
            secondary = row.get("secondary_date", "")
            reference_token, secondary_token = _date_token(reference), _date_token(secondary)
            pair_label = f"{reference}->{secondary}"
            if pair_label in seen:
                raise AuthorMapAdapterError("DUPLICATE_PAIR_ROW")
            seen.add(pair_label)
            dates.extend([reference, secondary])
            granule = str(row.get("granule_name", ""))
            stem = Path(granule).stem
            product = by_stem.get(stem)
            if product is None or product.get("release_id") != "P05023":
                raise AuthorMapAdapterError(f"CSV_SOURCE_NOT_IN_VERIFIED_MANIFEST:{pair_label}")
            source_sha = _required_sha(row.get("source_sha256"), pair_label)
            if source_sha != product.get("source_sha256"):
                raise AuthorMapAdapterError(f"CSV_SOURCE_SHA256_MISMATCH:{pair_label}")
            interval = str(product.get("interval", ""))
            if interval != f"{reference}/{secondary}":
                raise AuthorMapAdapterError(f"PAIR_DATE_SOURCE_INTERVAL_MISMATCH:{pair_label}")

            member = f"{reference_token}__{secondary_token}_diagnostic_arrays.npz"
            if member not in names:
                raise AuthorMapAdapterError(f"DIAGNOSTIC_NPZ_MEMBER_MISSING:{member}")
            preview, valid_crown, crown_cells = _preview_from_npz(archive.read(member), pair_label)
            try:
                csv_valid = int(row["crown_valid_pixels"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AuthorMapAdapterError(f"CSV_VALID_CROWN_COUNT_INVALID:{pair_label}") from exc
            if valid_crown != csv_valid:
                raise AuthorMapAdapterError(f"PREVIEW_VALID_CROWN_COUNT_MISMATCH:{pair_label}")

            days = max(1, (np.datetime64(secondary) - np.datetime64(reference)).astype(int).item())
            median = _finite_float(row["crown_median_horizontal_magnitude_m"], pair_label + ":median")
            rate_m_day = median / days
            pair_rows.append({
                "reference_date": reference,
                "secondary_date": secondary,
                "release_id": "P05023",
                "status": "METRICS_COMPUTED",
                "epsg": int(product.get("grid_epsg", 32645)),
                "valid_aoi_pixels": valid_crown,
                "aoi_total_grid_cells": crown_cells,
                "valid_aoi_fraction": valid_crown / crown_cells,
                "support_region_label": "Valid crown-mask pixels",
                "source_sha256": source_sha,
                "statistics": {
                    "crown_median_horizontal_magnitude_m": median,
                    "crown_median_magnitude_rate_m_per_day": rate_m_day,
                },
                "map_preview": preview,
            })

    if len(pair_rows) != 5 or len(by_stem) != 5 or seen != {
        "2026-06-20->2026-07-02", "2026-07-02->2026-07-14",
        "2026-07-14->2026-07-26", "2026-07-26->2026-08-19",
        "2026-08-19->2026-08-31",
    }:
        raise AuthorMapAdapterError("EXPECTED_FIVE_EXACT_PAIRS_NOT_PRESENT")

    return {
        "schema_version": "know-place-author-map-adapter/1.0",
        "status": "PASS",
        "source_run_id": source_run_id,
        "raw_hdf5_read_or_downloaded": False,
        "source_backend_commit": manifest.get("repository_commit"),
        "source_manifest_sha256": _sha256_bytes((root / "author-exact-source-manifest.json").read_bytes()),
        "analysis_report_sha256": _sha256_bytes((root / "know-place-analysis-report.json").read_bytes()),
        "derived_bundle_sha256": _sha256_bytes(archive_path.read_bytes()),
        "paper_reproduction_status": analysis.get("paper_reproduction_status"),
        "hazard_detection_status": "NOT_EVALUATED",
        "source_granules": 5,
        "map_pairs": len(pair_rows),
        "pairs": pair_rows,
        "aoi_geometry_note": "Author-script AOI rectangle: 85.5245–85.5400° E, 28.2847–28.2970° N; native-grid pixel-mask parity remains unverified.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--source-run-id", required=True, type=int)
    args = parser.parse_args()
    args.out_root.mkdir(parents=True, exist_ok=True)
    try:
        report = build_author_map_report(args.artifact_root, args.source_run_id)
        # The existing map renderer accepts a request/report container; preserve the exact dates and WKT.
        map_report = {
            "project": "Bhote Koshi exact-author measurement",
            "status": "SCIENTIFIC_METRICS_COMPUTED",
            "structural_status": "PASS",
            "paper_reproduction_status": report["paper_reproduction_status"],
            "hazard_detection_status": "NOT_EVALUATED",
            "request": {
                "aoi": {
                    "wkt": _read_json(args.artifact_root / "know-place-analysis-report.json")["run_scope"]["crown_wkt"],
                    "geometry_note": report["aoi_geometry_note"],
                },
                "date_range": {"start": "2026-06-20", "end": "2026-08-31"},
            },
            "pairs": report["pairs"],
        }
        html_path = write_interactive_map(map_report, args.out_root / "interactive-map.html")
        html_bytes = html_path.read_bytes()
        report.update({
            "status": "PASS",
            "interactive_map_file": html_path.name,
            "interactive_map_bytes": len(html_bytes),
            "interactive_map_sha256": _sha256_bytes(html_bytes),
            "map_preview_is_approximate": True,
            "raw_hdf5_read_or_downloaded": False,
        })
        (args.out_root / "author-map-provenance.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print("AUTHOR_EXACT_INTERACTIVE_MAP=PASS")
        print("SOURCE_RUN_ID=" + str(args.source_run_id))
        print("MAP_PAIRS=" + str(report["map_pairs"]))
        print("EXACT_AUTHOR_P05023_SOURCE_COUNT=5")
        print("RAW_HDF5_READ_OR_DOWNLOADED=false")
        print("PAPER_REPRODUCTION_STATUS=" + str(report["paper_reproduction_status"]))
        print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
        return 0
    except (AuthorMapAdapterError, OSError, ValueError, zipfile.BadZipFile) as exc:
        failure = {
            "schema_version": "know-place-author-map-adapter/1.0",
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc).split(":", 1)[0],
            "source_run_id": args.source_run_id,
            "raw_hdf5_read_or_downloaded": False,
            "hazard_detection_status": "NOT_EVALUATED",
        }
        (args.out_root / "author-map-provenance.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("AUTHOR_EXACT_INTERACTIVE_MAP=FAIL")
        print("ERROR=" + str(exc).split(":", 1)[0])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
