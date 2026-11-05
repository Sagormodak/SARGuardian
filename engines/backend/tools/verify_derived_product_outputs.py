#!/usr/bin/env python3
"""Validate one raw-derived SARGuardian product against its committed CSV baseline.

This must run before temporary raw-HDF5 cleanup. It validates the original
single-product reader output and its AOI GeoTIFFs without creating an HDF5 copy.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

REL_TOL = 1e-5
ABS_TOL = 1e-3


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {path}")
        return list(reader.fieldnames), list(reader)


def value_equal(expected: str, actual: str, field: str) -> bool:
    left = (expected or "").strip()
    right = (actual or "").strip()
    if left == right:
        return True
    if field == "export_mb":
        try:
            return math.isclose(float(left), float(right), rel_tol=0.02, abs_tol=0.05)
        except (TypeError, ValueError):
            return False
    if left.lower() in {"nan", "inf", "-inf"} or right.lower() in {"nan", "inf", "-inf"}:
        return left.lower() == right.lower()
    try:
        return math.isclose(float(left), float(right), rel_tol=REL_TOL, abs_tol=ABS_TOL)
    except (TypeError, ValueError):
        return False


def validate_rasters(
    family: str,
    granule: str,
    row: dict[str, str],
    export_dir: Path,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        import numpy as np
        import rasterio
    except ImportError as exc:
        errors.append({"problem": "rasterio_or_numpy_missing", "detail": str(exc)})
        return []

    name = Path((row.get("export_file") or "").strip()).name
    if not name or name in {".", ".."}:
        errors.append({"problem": "baseline_export_filename_missing", "granule": granule})
        return []
    raster_path = (export_dir / name).resolve()
    try:
        raster_path.relative_to(export_dir.resolve())
    except ValueError:
        errors.append({"problem": "export_path_escapes_directory", "path": name})
        return []
    if not raster_path.is_file() or raster_path.stat().st_size == 0:
        errors.append({"problem": "required_export_missing_or_empty", "path": name})
        return []

    record: dict[str, Any] = {"name": name, "bytes": raster_path.stat().st_size}
    try:
        with rasterio.open(raster_path) as ds:
            if ds.width <= 0 or ds.height <= 0 or ds.count <= 0:
                errors.append({"problem": "invalid_raster_dimensions_or_bands", "path": name,
                               "width": ds.width, "height": ds.height, "count": ds.count})
                return [record]
            if ds.crs is None:
                errors.append({"problem": "raster_crs_missing", "path": name})
            if family == "GUNW" and ds.count < 2:
                errors.append({"problem": "gunw_export_requires_displacement_and_coherence_bands",
                               "path": name, "count": ds.count})
            if family == "GOFF" and ds.count < 3:
                errors.append({"problem": "goff_export_requires_range_azimuth_correlation_bands",
                               "path": name, "count": ds.count})

            for key, actual in (("export_rows", ds.height), ("export_cols", ds.width)):
                text = (row.get(key) or "").strip()
                if text:
                    try:
                        expected = int(float(text))
                        if expected != actual:
                            errors.append({"problem": "raster_shape_differs_from_stats",
                                           "path": name, "field": key, "expected": expected,
                                           "actual": actual})
                    except ValueError:
                        errors.append({"problem": "invalid_raster_shape_in_stats",
                                       "path": name, "field": key, "value": text})

            tags = ds.tags()
            source_tag = tags.get("source", "")
            if source_tag and Path(source_tag).name != granule:
                errors.append({"problem": "raster_source_tag_mismatch", "path": name,
                               "expected": granule, "actual": source_tag})
            # The current scientific reader writes pair/units tags but does not
            # guarantee a source filename tag. If supplied, validate it; product
            # identity is independently bound by the exact stats CSV row.

            first = ds.read(1, masked=True)
            valid_first = int(np.count_nonzero(~np.ma.getmaskarray(first) & np.isfinite(first.filled(np.nan))))
            try:
                expected_valid = int(float((row.get("valid_px") or "").strip()))
            except (TypeError, ValueError):
                expected_valid = None
            if expected_valid is not None and valid_first != expected_valid:
                errors.append({"problem": "raster_valid_pixel_count_mismatch", "path": name,
                               "baseline_valid_px": expected_valid, "export_valid_pixels": valid_first})
            if valid_first == 0 and expected_valid == 0:
                record["science_valid_pixels"] = "NONE_AS_IN_BASELINE"
            elif valid_first == 0:
                errors.append({"problem": "raster_displacement_band_has_no_valid_pixels", "path": name,
                               "baseline_valid_px": expected_valid})
            if family == "GOFF" and ds.count >= 3:
                corr = ds.read(3, masked=True)
                valid_corr = int(np.count_nonzero(~np.ma.getmaskarray(corr) & np.isfinite(corr.filled(np.nan))))
                if valid_corr == 0 and expected_valid != 0:
                    errors.append({"problem": "goff_correlation_band_has_no_valid_pixels", "path": name,
                                   "baseline_valid_px": expected_valid})

            record.update({
                "width": ds.width,
                "height": ds.height,
                "count": ds.count,
                "dtype": list(ds.dtypes),
                "crs": ds.crs.to_string() if ds.crs else None,
                "crs_epsg": ds.crs.to_epsg() if ds.crs else None,
                "transform": list(ds.transform),
                "nodata": (float(ds.nodata) if ds.nodata is not None and math.isfinite(float(ds.nodata)) else (str(ds.nodata) if ds.nodata is not None else None)),
                "source_tag": source_tag,
                "valid_band1_pixels": valid_first,
            })
    except Exception as exc:
        errors.append({"problem": "raster_read_failed", "path": name,
                       "type": type(exc).__name__, "detail": str(exc)[:300]})
    return [record]


def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        baseline_fields, baseline_rows = read_csv(args.baseline_csv)
        actual_fields, actual_rows = read_csv(args.stats_csv)
        granule = Path(args.granule_name).name
        baseline_matches = [r for r in baseline_rows if Path((r.get("file") or "").strip()).name == granule]
        actual_matches = [r for r in actual_rows if Path((r.get("file") or "").strip()).name == granule]
        if args.product_type == "GOFF":
            baseline_matches = [r for r in baseline_matches if "layer2" in (r.get("layer") or "").lower()]
            actual_matches = [r for r in actual_matches if "layer2" in (r.get("layer") or "").lower()]
        if len(baseline_matches) != 1:
            errors.append({"problem": "expected_one_baseline_row", "granule": granule,
                           "product_type": args.product_type, "count": len(baseline_matches)})
        if len(actual_matches) != 1:
            errors.append({"problem": "expected_one_reader_row", "granule": granule,
                           "product_type": args.product_type, "count": len(actual_matches)})

        if set(baseline_fields) != set(actual_fields):
            errors.append({"problem": "stats_schema_mismatch",
                           "baseline_fields": baseline_fields, "actual_fields": actual_fields})
        if len(baseline_matches) == 1 and len(actual_matches) == 1:
            expected, actual = baseline_matches[0], actual_matches[0]
            mismatches = []
            for field in baseline_fields:
                if field not in actual:
                    mismatches.append({"field": field, "expected": expected.get(field), "actual": None})
                elif not value_equal(expected.get(field, ""), actual.get(field, ""), field):
                    mismatches.append({"field": field, "expected": expected.get(field),
                                       "actual": actual.get(field)})
            if mismatches:
                errors.append({"problem": "source_baseline_row_mismatch",
                               "granule": granule, "mismatches": mismatches[:100]})
            if args.product_type == "GOFF" and "layer2" not in (actual.get("layer") or "").lower():
                errors.append({"problem": "actual_goff_row_is_not_layer2",
                               "layer": actual.get("layer")})
            if "maturity" in expected and expected.get("maturity") != actual.get("maturity"):
                errors.append({"problem": "maturity_differs_from_baseline",
                               "expected": expected.get("maturity"), "actual": actual.get("maturity")})
            raster_records = validate_rasters(args.product_type, granule, expected, args.export_dir, errors)
        else:
            raster_records = []
    except Exception as exc:
        errors.append({"problem": "validation_execution_failed", "type": type(exc).__name__,
                       "detail": str(exc)[:400]})
        raster_records = []

    status = "PASS" if not errors else "FAIL"
    return {
        "schema_version": "sarguardian-derived-product-validation/1.0",
        "status": status,
        "product_id": args.product_id,
        "product_type": args.product_type,
        "granule_name": Path(args.granule_name).name,
        "aoi": "source",
        "baseline_csv": str(args.baseline_csv),
        "stats_csv": str(args.stats_csv),
        "export_dir": str(args.export_dir),
        "stats_schema_and_row_match": not any(e["problem"] in {"stats_schema_mismatch", "source_baseline_row_mismatch",
                                                                    "expected_one_baseline_row", "expected_one_reader_row"}
                                                  for e in errors),
        "export_validation": "PASS" if raster_records and not any(
            e["problem"].startswith(("required_export", "export_", "invalid_raster", "raster_", "gunw_export", "goff_export"))
            or e["problem"] in {"raster_shape_differs_from_stats", "raster_valid_pixel_count_mismatch",
                                "raster_displacement_band_has_no_valid_pixels", "goff_correlation_band_has_no_valid_pixels"}
            for e in errors) else "FAIL",
        "exports": raster_records,
        "warnings": warnings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--product-type", required=True, choices=("GUNW", "GOFF"))
    parser.add_argument("--granule-name", required=True)
    parser.add_argument("--baseline-csv", required=True, type=Path)
    parser.add_argument("--stats-csv", required=True, type=Path)
    parser.add_argument("--export-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = validate(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                        encoding="utf-8")
    print(f"DERIVED_PRODUCT_VALIDATION_STATUS={report['status']}")
    print(f"DERIVED_EXPORT_COUNT={len(report['exports'])}")
    print(f"VALIDATION_REPORT={args.out}")
    if report["status"] != "PASS":
        print("ERROR=DERIVED_PRODUCT_VALIDATION_FAILED")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
