"""Verify processed site-field rasters from the CC BY 4.0 author ZIP.

Example:
    python -m tools.know_place.verify_author_fields archive.zip --output report.json

This validates the archive manifest and recomputes stored R from the exported
dE/dN bands. It does not reproduce raw GOFF inputs or the full-footprint screen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile, BadZipFile

import numpy as np
import rasterio
from rasterio.io import MemoryFile

from .author_parity import author_coherence_map, author_polygon_null_statistics, author_site_series_statistics


def _hash(data: bytes, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    digest.update(data)
    return digest.hexdigest()


def _hash_path(path: Path, algorithms: tuple[str, ...] = ("md5", "sha256")) -> dict[str, str]:
    digests = {algorithm: hashlib.new(algorithm) for algorithm in algorithms}
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            for digest in digests.values():
                digest.update(chunk)
    return {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}


def _check_field_payload(filename: str, payload: bytes) -> dict[str, Any]:
    with MemoryFile(payload) as mem:
        with mem.open() as src:
            if src.count != 3:
                raise ValueError(f"FIELD_BAND_COUNT_NOT_3:{filename}:{src.count}")
            if (src.width, src.height) != (80, 73):
                raise ValueError(f"FIELD_SHAPE_NOT_80x73:{filename}:{src.width}x{src.height}")
            if src.crs is None or src.crs.to_epsg() != 4326:
                raise ValueError(f"FIELD_CRS_NOT_EPSG4326:{filename}:{src.crs}")
            if src.descriptions[0] != "dE_m ground-referenced east displacement":
                raise ValueError(f"FIELD_BAND_1_DESCRIPTION_MISMATCH:{filename}")
            if src.descriptions[1] != "dN_m ground-referenced north displacement":
                raise ValueError(f"FIELD_BAND_2_DESCRIPTION_MISMATCH:{filename}")
            if src.descriptions[2] != "R directional coherence, 5x5 window":
                raise ValueError(f"FIELD_BAND_3_DESCRIPTION_MISMATCH:{filename}")
            east, north, reference_r = src.read([1, 2, 3]).astype(np.float64)
            nodata = src.nodata
            profile = {
                "width": src.width,
                "height": src.height,
                "crs": src.crs.to_string(),
                "bands": src.count,
                "dtypes": list(src.dtypes),
                "nodata": "NaN" if nodata is not None and np.isnan(nodata) else nodata,
                "bounds": [float(v) for v in src.bounds],
                "transform": [float(v) for v in src.transform],
            }

    calculated_r = author_coherence_map(east, north)
    finite_calc = np.isfinite(calculated_r)
    finite_ref = np.isfinite(reference_r)
    common = finite_calc & finite_ref
    if not common.any():
        raise ValueError(f"FIELD_NO_COMMON_FINITE_R:{filename}")
    difference = np.abs(calculated_r[common] - reference_r[common])
    result = {
        "filename": filename,
        "bytes": len(payload),
        "md5": _hash(payload, "md5"),
        "sha256": _hash(payload, "sha256"),
        "profile": profile,
        "finite_dE_dN_cells": int((np.isfinite(east) & np.isfinite(north)).sum()),
        "finite_reference_R_cells": int(finite_ref.sum()),
        "finite_recomputed_R_cells": int(finite_calc.sum()),
        "common_finite_R_cells": int(common.sum()),
        "finite_masks_equal": bool(np.array_equal(finite_calc, finite_ref)),
        "median_absolute_error": float(np.median(difference)),
        "p95_absolute_error": float(np.percentile(difference, 95)),
        "maximum_absolute_error": float(difference.max()),
        "errors_above_1e_6": int((difference > 1e-6).sum()),
        "R_band_match": bool(np.array_equal(finite_calc, finite_ref) and float(difference.max()) <= 1e-6),
    }
    return result


_AUTHOR_PAIR_SPECS = [
    ("20260620", "20260702", 12),
    ("20260702", "20260714", 12),
    ("20260714", "20260726", 12),
    ("20260726", "20260819", 24),
    ("20260819", "20260831", 12),
]


def _rounded_equal(actual: float, expected: float, decimals: int) -> bool:
    """Compare values at the number of decimal places stored in author tables."""
    return abs(round(float(actual), decimals) - float(expected)) <= 1e-12


def _author_table_parity(
    names: set[str],
    payloads: dict[str, bytes],
    read_member: Any,
    required: bool,
    n_draw: int = 1200,
) -> dict[str, Any]:
    """Compare five processed fields with corresponding archived author tables.

    This operates on the exported TIFFs only. It does not reproduce the raw
    GOFF source-grid crop, original HDF5 processing, or full-footprint screen.
    """
    required_tables = [
        "tables/nisar_pot_series.json",
        "tables/polygon_null.json",
        "tables/displacement_null.json",
        "tables/TableS4_site_series.json",
    ]
    present_tables = [path for path in required_tables if path in names]
    missing_tables = [path for path in required_tables if path not in names]
    if not required and missing_tables:
        return {
            "status": "NOT_APPLICABLE_FIELD_ONLY_FIXTURE",
            "required": False,
            "missing_tables": missing_tables,
            "scope": "Small test archives may validate TIFF integrity without carrying author statistics tables.",
        }
    if missing_tables:
        return {
            "status": "BLOCKED_REFERENCE_TABLES_MISSING",
            "required": True,
            "missing_tables": missing_tables,
            "present_tables": present_tables,
            "failed_checks": ["AUTHOR_REFERENCE_TABLES_MISSING"],
        }

    field_paths = [f"fields/offsets_{a}_{b}.tif" for a, b, _ in _AUTHOR_PAIR_SPECS]
    missing_fields = [path for path in field_paths if path not in payloads]
    if missing_fields:
        return {
            "status": "BLOCKED_EXPECTED_FIELD_MISSING",
            "required": True,
            "missing_fields": missing_fields,
            "present_tables": present_tables,
            "failed_checks": ["AUTHOR_EXPECTED_FIELD_MISSING"],
        }

    try:
        site_rows = json.loads(read_member("tables/nisar_pot_series.json"))
        polygon_rows = json.loads(read_member("tables/polygon_null.json"))
        displacement_rows = json.loads(read_member("tables/displacement_null.json"))
        table_s4 = json.loads(read_member("tables/TableS4_site_series.json"))
        s4_rows = table_s4["rows"]
    except (ValueError, KeyError, TypeError) as exc:
        return {
            "status": "BLOCKED_REFERENCE_TABLE_INVALID",
            "required": True,
            "present_tables": present_tables,
            "failed_checks": ["AUTHOR_REFERENCE_TABLE_INVALID"],
            "error": str(exc),
        }

    expected_pairs = [(a, b) for a, b, _ in _AUTHOR_PAIR_SPECS]
    table_sets = [
        ("nisar_pot_series", site_rows, lambda row: (row.get("a"), row.get("b"))),
        ("polygon_null", polygon_rows, lambda row: tuple(str(row.get("pair", "")).split("->", 1))),
        ("displacement_null", displacement_rows, lambda row: tuple(str(row.get("pair", "")).split("->", 1))),
        ("TableS4_site_series", s4_rows, lambda row: tuple(str(row.get("pair", "")).split("->", 1))),
    ]
    shape_failures = []
    for label, rows, pair_fn in table_sets:
        if not isinstance(rows, list) or len(rows) != 5 or [pair_fn(row) for row in rows] != expected_pairs:
            shape_failures.append(f"{label}:PAIR_ORDER_OR_ROW_COUNT_INVALID")
    if shape_failures:
        return {
            "status": "BLOCKED_REFERENCE_TABLE_PAIR_ORDER",
            "required": True,
            "present_tables": present_tables,
            "failed_checks": shape_failures,
        }

    rng = np.random.default_rng(20260907)
    pair_results: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, ((a, b, days), field_path) in enumerate(zip(_AUTHOR_PAIR_SPECS, field_paths)):
        with MemoryFile(payloads[field_path]) as mem:
            with mem.open() as src:
                east, north = src.read([1, 2]).astype(np.float64)
                extent = (
                    float(src.bounds.left),
                    float(src.bounds.right),
                    float(src.bounds.bottom),
                    float(src.bounds.top),
                )

        series_calc = author_site_series_statistics(east, north, extent, days)
        polygon_calc = author_polygon_null_statistics(east, north, extent, rng=rng, n_draw=n_draw)
        series_ref = site_rows[index]
        polygon_ref = polygon_rows[index]
        displacement_ref = displacement_rows[index]
        s4_ref = s4_rows[index]
        pair = f"{a}->{b}"

        series_checks = {
            "displacement_count_matches_n": int(series_calc["displacement_valid_crown_cells"]) == int(series_ref["n"]),
            "median_displacement_matches": abs(float(series_calc["crown_median_displacement_m"]) - float(series_ref["crown_median_m"])) <= 1e-6,
            "interval_rate_matches": abs(float(series_calc["crown_median_rate_cm_per_day"]) / 100.0 - float(series_ref["rate_m_per_day"])) <= 1e-8,
            "P1_crop_crown_R_matches": abs(float(series_calc["P1_R_crown"]) - float(series_ref["R_crown"])) <= 1e-6,
            "P1_scene_R_matches": abs(float(series_calc["P1_R_background"]) - float(series_ref["R_scene"])) <= 1e-6,
        }
        polygon_checks = {
            "R_valid_count_matches_n_px": int(polygon_calc["crown_valid_R_cells"]) == int(polygon_ref["n_px"]),
            "accepted_draw_count_matches": int(polygon_calc["accepted_draws"]) == int(polygon_ref["n_draw"]),
            "crown_R_matches_stored_precision": _rounded_equal(polygon_calc["crown_R"], polygon_ref["crown"], 3),
            "box_R_matches_stored_precision": _rounded_equal(polygon_calc["box_R"], polygon_ref["box"], 3),
            "crown_minus_box_matches_stored_precision": _rounded_equal(float(polygon_calc["crown_R"]) - float(polygon_calc["box_R"]), polygon_ref["adv"], 3),
            "strict_crown_percentile_matches_stored_precision": _rounded_equal(polygon_calc["crown_percentile_strict_less_than"], polygon_ref["crown_pctile"], 1),
            "strict_controls_above_box_matches_stored_precision": _rounded_equal(polygon_calc["fraction_controls_strictly_above_box"], polygon_ref["pct_beat_box"], 1),
            "null_p5_matches_stored_precision": _rounded_equal(polygon_calc["null_p5"], polygon_ref["null_p5"], 3),
            "null_p95_matches_stored_precision": _rounded_equal(polygon_calc["null_p95"], polygon_ref["null_p95"], 3),
        }
        s4_checks = {
            "TableS4_median_matches": _rounded_equal(series_calc["crown_median_displacement_m"], s4_ref["crown_disp_m"], 2),
            "TableS4_rate_matches": _rounded_equal(series_calc["crown_median_rate_cm_per_day"], s4_ref["crown_rate_cm_per_day"], 1),
            "TableS4_P1_crown_R_matches": _rounded_equal(series_calc["P1_R_crown"], s4_ref["P1_R_crown"], 3),
            "TableS4_P1_background_R_matches": _rounded_equal(series_calc["P1_R_background"], s4_ref["P1_R_bg"], 3),
            "TableS4_P1_resolution_rule_matches": (float(series_calc["P1_R_crown"]) > float(series_calc["P1_R_background"])) is bool(s4_ref["P1_resolved"]),
            "TableS4_polygon_null_crown_R_matches": _rounded_equal(polygon_calc["crown_R"], s4_ref["polynull_R_crown"], 3),
            "TableS4_polygon_null_box_R_matches": _rounded_equal(polygon_calc["box_R"], s4_ref["polynull_R_box"], 3),
            "TableS4_polygon_null_percentile_matches": _rounded_equal(polygon_calc["crown_percentile_strict_less_than"], s4_ref["polynull_crown_pctile"], 1),
            "TableS4_polygon_null_draw_count_matches": int(polygon_calc["accepted_draws"]) == int(s4_ref["polynull_n_draw"]),
            "TableS4_displacement_null_table_matches": (
                _rounded_equal(displacement_ref["crown"], s4_ref["dispnull_crown_m"], 2)
                and _rounded_equal(displacement_ref["null_med"], s4_ref["dispnull_null_med_m"], 2)
                and _rounded_equal(displacement_ref["pctile"], s4_ref["dispnull_pctile"], 1)
            ),
        }
        all_checks = {
            **{f"series.{key}": value for key, value in series_checks.items()},
            **{f"polygon_null.{key}": value for key, value in polygon_checks.items()},
            **{f"TableS4.{key}": value for key, value in s4_checks.items()},
        }
        failed = [key for key, passed in all_checks.items() if not passed]
        failures.extend(f"{pair}:{key}" for key in failed)
        pair_results.append({
            "pair": pair,
            "interval_days": days,
            "extent_source": "exported GeoTIFF bounds used as endpoint coordinates for the author crop function",
            "displacement_valid_crown_cells": int(series_calc["displacement_valid_crown_cells"]),
            "P1_crown_R_valid_cells": int(series_calc["P1_crown_R_valid_cells"]),
            "P1_background_R_valid_cells": int(series_calc["P1_background_R_valid_cells"]),
            "P1_crown_R": float(series_calc["P1_R_crown"]),
            "P1_background_R": float(series_calc["P1_R_background"]),
            "crown_median_displacement_m": float(series_calc["crown_median_displacement_m"]),
            "crown_median_rate_cm_per_day": float(series_calc["crown_median_rate_cm_per_day"]),
            "polygon_null_R_valid_crown_cells": int(polygon_calc["crown_valid_R_cells"]),
            "polygon_null_crown_R": float(polygon_calc["crown_R"]),
            "polygon_null_box_R": float(polygon_calc["box_R"]),
            "polygon_null_accepted_draws": int(polygon_calc["accepted_draws"]),
            "polygon_null_rejected_draws": int(polygon_calc["rejected_draws"]),
            "polygon_null_crown_percentile": float(polygon_calc["crown_percentile_strict_less_than"]),
            "polygon_null_fraction_controls_above_box_percent": float(polygon_calc["fraction_controls_strictly_above_box"]),
            "polygon_null_p5": float(polygon_calc["null_p5"]),
            "polygon_null_p95": float(polygon_calc["null_p95"]),
            "checks": all_checks,
            "failed_checks": failed,
            "status": "PASS" if not failed else "BLOCKED",
        })

    return {
        "status": "PASS_EXPORTED_FIELDS_MATCH_ARCHIVED_TABLES" if not failures else "BLOCKED_ARCHIVED_TABLE_PARITY",
        "required": True,
        "comparison_method": {
            "P1": "author coherence computed after crown crop; compared with nisar_pot_series and TableS4",
            "polygon_null": "author coherence computed over the full exported field then cropped; one shared numpy.default_rng(20260907) sequence across five pairs; compared with polygon_null.json and TableS4",
            "displacement_null": "No displacement-null generator replay is claimed; TableS4 is cross-checked against the archived displacement_null.json output only.",
            "tolerances": {
                "full_precision_series_values_absolute": 1e-6,
                "series_rate_m_per_day_absolute": 1e-8,
                "rounded_three_decimal_values": "rounded values must match the precision stored by the author tables",
                "rounded_one_decimal_values": "rounded values must match the precision stored by the author tables",
                "counts_and_accepted_draws": "exact integer equality",
            },
            "random_policy": f"One shared numpy.default_rng(20260907) sequence, {n_draw} candidate centres per pair (or all available finite-R centres if fewer), matching the archived polygon-null script.",
            "spatial_policy": "Crown crop uses author endpoint-linear searchsorted rules on exported GeoTIFF bounds. This does not prove pixelwise parity on the original GOFF source grid.",
        },
        "pair_results": pair_results,
        "failed_checks": failures,
        "interpretation": "Processed-field/table consistency only; not raw GOFF source replay, independent validation, full-footprint reproduction, or hazard-detection evidence.",
    }


def verify_author_archive(archive_path: str | Path, expected_field_count: int = 5) -> dict[str, Any]:
    archive = Path(archive_path).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"AUTHOR_ARCHIVE_NOT_FOUND:{archive}")
    if not isinstance(expected_field_count, int) or expected_field_count < 1:
        raise ValueError("EXPECTED_FIELD_COUNT_MUST_BE_POSITIVE")
    archive_hashes = _hash_path(archive)
    report: dict[str, Any] = {
        "schema_version": "know-place-author-field-verification/1.0",
        "archive": {
            "filename": archive.name,
            "bytes": archive.stat().st_size,
            "md5": archive_hashes["md5"],
            "sha256": archive_hashes["sha256"],
        },
        "manifest": {},
        "site_fields": [],
        "raw_goff_h5_in_archive": False,
        "full_footprint_per_pair_offset_rasters_in_archive": False,
        "status": "BLOCKED",
    }

    try:
        with ZipFile(archive) as zf:
            names = set(zf.namelist())
            broken = zf.testzip()
            if broken is not None:
                raise ValueError(f"ZIP_CRC_FAILURE:{broken}")
            if "MANIFEST.json" not in names:
                raise ValueError("ARCHIVE_MANIFEST_MISSING")
            manifest = json.loads(zf.read("MANIFEST.json"))
            listed = manifest.get("manifest")
            if not isinstance(listed, list):
                raise ValueError("ARCHIVE_MANIFEST_LIST_INVALID")
            payloads: dict[str, bytes] = {}
            missing: list[str] = []
            mismatches: list[dict[str, Any]] = []
            present = 0
            for entry in listed:
                path = str(entry.get("path", ""))
                if not path:
                    mismatches.append({"path": path, "reason": "EMPTY_PATH"})
                    continue
                if path not in names:
                    missing.append(path)
                    continue
                payload = zf.read(path)
                present += 1
                actual_size = len(payload)
                actual_md5 = _hash(payload, "md5")
                if actual_size != int(entry["bytes"]) or actual_md5 != str(entry["md5"]):
                    mismatches.append({
                        "path": path,
                        "expected_bytes": int(entry["bytes"]),
                        "actual_bytes": actual_size,
                        "expected_md5": str(entry["md5"]),
                        "actual_md5": actual_md5,
                    })
                if path.startswith("fields/offsets_") and path.endswith(".tif"):
                    payloads[path] = payload
            fields: list[dict[str, Any]] = []
            for path in sorted(payloads):
                fields.append(_check_field_payload(path, payloads[path]))
            listed_paths = {str(x.get("path", "")) for x in listed}
            unlisted = sorted(names - listed_paths)
            expected_external = [p for p in missing if p == "README.md" or p.startswith("extent_CC-BY-NC-4.0/")]
            unexpected_missing = sorted(set(missing) - set(expected_external))
            unexpected_unlisted = [p for p in unlisted if p != "MANIFEST.json"]
            report["manifest"] = {
                "declared_files": int(manifest.get("files", len(listed))),
                "zip_entry_count": len(names),
                "manifest_payloads_present": present,
                "manifest_paths_missing_from_zip": missing,
                "expected_separate_record_components_missing_from_zip": sorted(expected_external),
                "unexpected_missing_paths": unexpected_missing,
                "payload_size_or_md5_mismatches": mismatches,
                "zip_entries_not_listed_in_manifest": unlisted,
                "unexpected_unlisted_entries": unexpected_unlisted,
                "declared_bytes": int(manifest.get("total_bytes", 0)),
            }
            report["site_fields"] = fields
            report["author_table_parity"] = _author_table_parity(
                names=names,
                payloads=payloads,
                read_member=zf.read,
                required=(expected_field_count == 5),
            )
            report["raw_goff_h5_in_archive"] = any(name.lower().endswith((".h5", ".hdf5")) for name in names)
            report["full_footprint_per_pair_offset_rasters_in_archive"] = any(
                field["profile"]["width"] >= 4000 and field["profile"]["height"] >= 4000 for field in fields
            )
            all_payloads_verified = present > 0 and not unexpected_missing and not unexpected_unlisted and not mismatches
            fields_valid = len(fields) == expected_field_count and all(x["R_band_match"] for x in fields)
            table_status = report["author_table_parity"]["status"]
            tables_valid = table_status in {"PASS_EXPORTED_FIELDS_MATCH_ARCHIVED_TABLES", "NOT_APPLICABLE_FIELD_ONLY_FIXTURE"}
            report["status"] = (
                "PASS_PROCESSED_FIELD_R_VERIFIED"
                if all_payloads_verified and fields_valid and tables_valid
                else "BLOCKED"
            )
    except BadZipFile as exc:
        raise ValueError(f"INVALID_ZIP_ARCHIVE:{archive}") from exc

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Original Zenodo CC BY 4.0 data-and-code ZIP")
    parser.add_argument("--output", type=Path, help="Optional path for a JSON verification report")
    parser.add_argument("--expected-fields", type=int, default=5, help="Expected number of per-pair site-field TIFFs")
    args = parser.parse_args()
    report = verify_author_archive(args.archive, expected_field_count=args.expected_fields)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "PASS_PROCESSED_FIELD_R_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
