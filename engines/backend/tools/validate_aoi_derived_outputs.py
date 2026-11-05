#!/usr/bin/env python3
"""Validate AOI-specific reader exports without comparing against the fixed source-AOI baseline.

Structural validation is intentionally not described as geophysical validation:
it checks product identity, CSV structure, output rasters and provenance only.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

def canonical_granule_name(value: Any) -> str:
    """Normalize CSV product paths and manifest granule names to one identity."""
    name = Path(str(value or "").strip()).name
    return name[:-3] if name.lower().endswith(".h5") else name

def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV_HEADER_MISSING")
        return list(reader.fieldnames), list(reader)

def validate(args: argparse.Namespace) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    raster_records: list[dict[str, Any]] = []
    stats_fields: list[str] = []
    rows: list[dict[str, str]] = []
    try:
        stats_fields, rows = read_rows(args.stats_csv)
        granule = canonical_granule_name(args.granule_name)
        product_matches = [
            r for r in rows
            if canonical_granule_name(r.get("file")) == granule
        ]
        matched = product_matches
        if args.product_type == "GOFF":
            matched = [r for r in matched if "layer2" in (r.get("layer") or "").lower()]
        if len(matched) != 1:
            errors.append({"problem": "EXPECTED_ONE_READER_ROW_FOR_PRODUCT", "count": len(matched)})
        export_files = sorted(
            p for p in args.export_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}
        )
        if not export_files:
            errors.append({"problem": "NO_AOI_CLIPPED_GEOTIFF_EXPORTS"})
        try:
            import numpy as np
            import rasterio
            for path in export_files:
                rec: dict[str, Any] = {"name": path.relative_to(args.export_dir).as_posix(),
                                       "bytes": path.stat().st_size}
                try:
                    with rasterio.open(path) as ds:
                        if ds.width <= 0 or ds.height <= 0 or ds.count < 1:
                            errors.append({"problem": "INVALID_RASTER_DIMENSIONS", "name": rec["name"]})
                        if ds.crs is None:
                            errors.append({"problem": "RASTER_CRS_MISSING", "name": rec["name"]})
                        minimum_bands = 2 if args.product_type == "GUNW" else 3
                        if ds.count < minimum_bands:
                            errors.append({"problem": "RASTER_BAND_SCHEMA_INVALID",
                                           "name": rec["name"], "count": ds.count,
                                           "minimum": minimum_bands})
                        band1 = ds.read(1, masked=True)
                        valid = ~np.ma.getmaskarray(band1) & np.isfinite(band1.filled(np.nan))
                        screen_valid_count = int(np.count_nonzero(valid))
                        tags = ds.tags()

                        def nonnegative_tag(name: str, fallback: int) -> int:
                            try:
                                value = int(str(tags.get(name, "")).strip())
                                return value if value >= 0 else fallback
                            except (TypeError, ValueError, OverflowError):
                                return fallback

                        robust_inlier_count = nonnegative_tag("robust_inlier_pixels", screen_valid_count)
                        screen_outlier_count = nonnegative_tag("robust_outlier_pixels", 0)
                        flag_valid_count = flag_inlier_count = flag_outlier_count = None
                        if ds.count >= 4 and (
                            "robust inlier flag" in str(ds.descriptions[3] or "").lower()
                            if ds.descriptions else False
                        ):
                            flag = ds.read(4, masked=True).filled(np.nan).astype("float64", copy=False)
                            finite_flag = np.isfinite(flag)
                            flag_valid_count = int(finite_flag.sum())
                            flag_inlier_count = int((finite_flag & np.isclose(flag, 1.0)).sum())
                            flag_outlier_count = int((finite_flag & np.isclose(flag, 0.0)).sum())
                            unknown_flags = finite_flag & ~(np.isclose(flag, 0.0) | np.isclose(flag, 1.0))
                            if unknown_flags.any():
                                errors.append({"problem": "GOFF_OUTLIER_FLAG_HAS_UNKNOWN_VALUES",
                                               "name": rec["name"], "count": int(unknown_flags.sum())})
                            if flag_valid_count != screen_valid_count:
                                errors.append({"problem": "GOFF_FLAG_AND_SCREEN_MASK_COUNTS_DIFFER",
                                               "name": rec["name"], "screen_valid": screen_valid_count,
                                               "flag_valid": flag_valid_count})
                            if flag_inlier_count != robust_inlier_count:
                                errors.append({"problem": "GOFF_ROBUST_INLIER_TAG_MISMATCH",
                                               "name": rec["name"], "tag": robust_inlier_count,
                                               "flag": flag_inlier_count})
                            if flag_outlier_count != screen_outlier_count:
                                errors.append({"problem": "GOFF_SCREEN_OUTLIER_TAG_MISMATCH",
                                               "name": rec["name"], "tag": screen_outlier_count,
                                               "flag": flag_outlier_count})
                        if screen_valid_count != robust_inlier_count + screen_outlier_count:
                            errors.append({"problem": "GOFF_SCREEN_ATTRITION_DOES_NOT_RECONCILE",
                                           "name": rec["name"], "screen_valid": screen_valid_count,
                                           "robust_inliers": robust_inlier_count,
                                           "screen_outliers": screen_outlier_count})
                        variance_layers: dict[str, Any] = {}
                        if args.product_type == "GOFF":
                            for tag_name, description_fragment, nonnegative in (
                                ("range_variance_band", "slant-range offset variance", True),
                                ("along_track_variance_band", "along-track offset variance", True),
                                ("cross_offset_variance_band", "cross offset variance", False),
                            ):
                                raw_index = str(tags.get(tag_name) or "").strip()
                                if not raw_index or raw_index.lower() == "not_exported":
                                    continue
                                try:
                                    band_index = int(raw_index)
                                except (TypeError, ValueError, OverflowError):
                                    errors.append({"problem": "GOFF_VARIANCE_BAND_INDEX_INVALID",
                                                   "name": rec["name"], "tag": tag_name, "value": raw_index})
                                    continue
                                if band_index < 1 or band_index > ds.count:
                                    errors.append({"problem": "GOFF_VARIANCE_BAND_INDEX_OUT_OF_RANGE",
                                                   "name": rec["name"], "tag": tag_name, "index": band_index,
                                                   "band_count": ds.count})
                                    continue
                                description = str(ds.descriptions[band_index - 1] or "").lower()
                                if description_fragment not in description:
                                    errors.append({"problem": "GOFF_VARIANCE_BAND_DESCRIPTION_MISMATCH",
                                                   "name": rec["name"], "tag": tag_name,
                                                   "description": description})
                                    continue
                                values = ds.read(band_index, masked=True)
                                array = values.filled(np.nan).astype("float64", copy=False)
                                finite_values = np.isfinite(array) & valid
                                negative_count = int((finite_values & (array < 0)).sum())
                                if nonnegative and negative_count:
                                    errors.append({"problem": "GOFF_DIAGONAL_VARIANCE_HAS_NEGATIVE_VALUES",
                                                   "name": rec["name"], "tag": tag_name,
                                                   "count": negative_count})
                                variance_layers[tag_name] = {
                                    "band_index": band_index,
                                    "description": description,
                                    "finite_valid_pixels": int(finite_values.sum()),
                                    "coverage": float(finite_values.sum() / max(1, screen_valid_count)),
                                    "negative_values": negative_count,
                                }
                            if ("range_variance_band" in variance_layers) != ("along_track_variance_band" in variance_layers):
                                warnings.append(f"PARTIAL_GOFF_COMPONENT_VARIANCE_LAYERS:{path.name}")
                        rec.update({
                            "width": ds.width, "height": ds.height, "count": ds.count,
                            "crs": ds.crs.to_string() if ds.crs else None,
                            # Keep the old field as the broad, quality-valid
                            # screen support because band 1 is intentionally
                            # preserved before robust-MAD removal. The strict
                            # measurement count is a separate field.
                            "valid_band1_pixels": screen_valid_count,
                            "screen_valid_pixels": screen_valid_count,
                            "robust_inlier_pixels": robust_inlier_count,
                            "screen_outlier_pixels": screen_outlier_count,
                            "outlier_flag_valid_pixels": flag_valid_count,
                            "outlier_flag_inlier_pixels": flag_inlier_count,
                            "outlier_flag_rejected_pixels": flag_outlier_count,
                            "science_values_present": screen_valid_count > 0,
                            "goff_variance_layers": variance_layers,
                            "bounds": [float(ds.bounds.left), float(ds.bounds.bottom),
                                       float(ds.bounds.right), float(ds.bounds.top)],
                        })
                        if screen_valid_count == 0:
                            warnings.append(f"NO_VALID_SCREEN_PIXELS:{path.name}")
                except Exception as exc:
                    errors.append({"problem": "RASTER_READ_FAILED", "name": rec["name"],
                                   "type": type(exc).__name__, "detail": str(exc)[:220]})
                raster_records.append(rec)
        except ImportError as exc:
            errors.append({"problem": "RASTERIO_NUMPY_MISSING", "detail": str(exc)})
    except Exception as exc:
        errors.append({"problem": "VALIDATION_EXECUTION_FAILED", "type": type(exc).__name__,
                       "detail": str(exc)[:250]})
    status = "PASS" if not errors else "FAIL"
    report = {
        "schema_version": "sarguardian-aoi-derived-validation/1.0",
        "status": status,
        "validation_scope": "structural_and_provenance_not_independent_geophysical_validation",
        "product_id": args.product_id,
        "product_type": args.product_type,
        "granule_name": canonical_granule_name(args.granule_name),
        "aoi": args.aoi_name,
        "stats_csv": str(args.stats_csv),
        "stats_fields": stats_fields,
        "stats_rows": len(rows),
        "product_rows": sum(
            canonical_granule_name(r.get("file")) == canonical_granule_name(args.granule_name)
            for r in rows
        ),
        "exports": raster_records,
        "warnings": warnings,
        "errors": errors,
    }
    return report

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--product-id", required=True)
    p.add_argument("--product-type", required=True, choices=("GUNW", "GOFF"))
    p.add_argument("--granule-name", required=True)
    p.add_argument("--aoi-name", default="custom")
    p.add_argument("--stats-csv", required=True, type=Path)
    p.add_argument("--export-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    report = validate(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                        encoding="utf-8")
    print(f"AOI_DERIVED_VALIDATION_STATUS={report['status']}")
    print(f"AOI_DERIVED_EXPORT_COUNT={len(report['exports'])}")
    print(f"AOI_DERIVED_VALIDATION_REPORT={args.out}")
    if report["status"] != "PASS":
        print("ERROR=AOI_DERIVED_VALIDATION_FAILED")
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
