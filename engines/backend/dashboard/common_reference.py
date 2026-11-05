"""Strict common-datum diagnostic series from retained, AOI-clipped GUNW rasters.

This never reads or downloads raw HDF5 data. It uses the pinned science engine's
common-reference primitives and graph inversion. A series is explicitly
DIAGNOSTIC_ONLY because the common AOI median is an internally inferred datum,
not an independently surveyed stable-ground reference.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _json_number(value: Any) -> float | None:
    return _finite(value)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _safe_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def _empty_report(status: str, reason: str, *, aoi_wkt_sha256: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "sarguardian-common-reference-timeseries/1.0",
        "status": status,
        "series_are_independent_geophysical_validation": False,
        "aoi_wkt_sha256": aoi_wkt_sha256,
        "common_reference_method": "median of the all-pair valid AOI mask after excluding a 2 km buffer around the target",
        "common_reference_is_independently_validated_stable_ground": False,
        "interpretation": (
            "A common-datum diagnostic only. The reference is inferred from the same AOI stack, "
            "not independently confirmed stable ground. It is not a hazard alert or forecast."
        ),
        "reason": reason,
        "networks": [],
        "pairwise_measurements": [],
        "components": [],
        "warnings": [
            "Pairwise LOS values are relative to a data-derived common AOI median, not an external stable-ground monument.",
            "Formal network fit errors exclude systematic reference instability, atmospheric residuals, orbital ramps and LOS-to-ground-motion geometry.",
            "No interpolation between acquisitions or future forecast is produced.",
        ],
    }


def build_common_reference_report(
    products: list[dict[str, Any]],
    output_root: Path,
    science_root: Path,
    aoi_wkt: str,
    aoi_wkt_sha256: str | None,
    site_context: dict[str, Any] | None,
    *,
    min_target_pixels: int = 6,
    target_radius_px: int = 5,
    buffer_km: float = 2.0,
) -> dict[str, Any]:
    """Create a guarded common-reference diagnostic from retained GUNW rasters."""
    output_root = output_root.resolve()
    target = ((site_context or {}).get("measurement_target") or {})
    if target.get("status") != "IN_AOI_TARGET_CAPTURED":
        report = _empty_report(
            "BLOCKED_NO_VALID_IN_AOI_TARGET",
            "The exact request has no target point validated inside its AOI polygon.",
            aoi_wkt_sha256=aoi_wkt_sha256,
        )
        _write_report(output_root, report)
        return report

    target_lat, target_lon = _finite(target.get("latitude")), _finite(target.get("longitude"))
    if target_lat is None or target_lon is None:
        report = _empty_report(
            "BLOCKED_INVALID_TARGET_COORDINATES",
            "The in-AOI target coordinates are missing or non-finite.",
            aoi_wkt_sha256=aoi_wkt_sha256,
        )
        _write_report(output_root, report)
        return report

    src = (science_root.resolve() / "src")
    if not src.is_dir():
        report = _empty_report(
            "UNAVAILABLE_PINNED_SCIENCE_SOURCE",
            "The pinned science source directory is missing; common-reference processing was not attempted.",
            aoi_wkt_sha256=aoi_wkt_sha256,
        )
        _write_report(output_root, report)
        return report
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    # The reader's custom AOI is set before using any science module. The
    # explicit update is safe even if a module was imported earlier in this
    # aggregation process: AOIS is a shared dictionary.
    os.environ["SARGUARDIAN_AOI_WKT"] = aoi_wkt
    try:
        from aoi_wkt import parse_polygon_wkt
        import gunw_reader
        ring = parse_polygon_wkt(aoi_wkt)
        gunw_reader.AOIS["custom"] = ring
        gunw_reader.set_aoi("custom")
        import common_ref
        import timeseries
        import rasterio
        from pyproj import Transformer
        from rasterio.features import geometry_mask
        from rasterio.warp import transform_geom
        from rasterio.transform import rowcol
    except Exception as exc:
        report = _empty_report(
            "UNAVAILABLE_SCIENCE_IMPORT",
            f"Pinned common-reference dependencies could not be loaded: {type(exc).__name__}: {str(exc)[:220]}",
            aoi_wkt_sha256=aoi_wkt_sha256,
        )
        _write_report(output_root, report)
        return report

    report = _empty_report(
        "NO_ELIGIBLE_GUNW_NETWORK",
        "No GUNW network met the retained-raster, common-grid and target support contract.",
        aoi_wkt_sha256=aoi_wkt_sha256,
    )
    report["target"] = {"latitude": target_lat, "longitude": target_lon}
    report["target_radius_pixels"] = target_radius_px
    report["stable_area_buffer_km"] = buffer_km
    report["minimum_common_reference_pixels"] = int(getattr(common_ref, "MIN_COMMON", 200))

    # The network identity comes from the complete granule name, never the
    # dashboard's display label or just the two acquisition dates.
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    rejected: list[dict[str, Any]] = []
    for product in products:
        if str(product.get("product_type", "")).upper() != "GUNW":
            continue
        name = str(product.get("granule_name") or "")
        meta = timeseries.granule_metadata(name)
        if not meta or meta.get("product") != "GUNW":
            rejected.append({"product_id": product.get("id"), "status": "REJECTED_IDENTITY", "reason": "Pinned timeseries.py could not parse the exact NISAR GUNW identity."})
            continue
        reference = _parse_date(product.get("reference_date"))
        secondary = _parse_date(product.get("secondary_date"))
        if reference is None or secondary is None or secondary <= reference:
            rejected.append({"product_id": product.get("id"), "status": "REJECTED_DATES", "reason": "Invalid acquisition dates."})
            continue
        exports = product.get("exports") or []
        if len(exports) != 1:
            rejected.append({"product_id": product.get("id"), "status": "REJECTED_EXPORT_COUNT", "reason": "Expected exactly one exported GUNW raster per granule."})
            continue
        rel = str(exports[0].get("relative_path") or "")
        try:
            raster_path = _safe_child(output_root, rel)
        except (ValueError, OSError):
            rejected.append({"product_id": product.get("id"), "status": "REJECTED_EXPORT_PATH", "reason": "Export path is not safely contained in the dashboard artifact."})
            continue
        if not raster_path.is_file():
            rejected.append({"product_id": product.get("id"), "status": "REJECTED_EXPORT_MISSING", "reason": "Retained AOI-clipped raster was not found."})
            continue
        # Split processing levels rather than mixing PR and UR in one network.
        network_key = (
            meta.get("product"), meta.get("direction"), meta.get("path"), meta.get("frame"),
            meta.get("subswath"), meta.get("bandwidth"), meta.get("polarisation"),
            meta.get("crid"), meta.get("processing"),
        )
        grouped[network_key].append({
            "product": product, "meta": meta, "path": raster_path,
            "reference": reference, "secondary": secondary,
        })

    networks: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    components_out: list[dict[str, Any]] = []
    any_common_datum = False
    any_cumulative_series = False

    for network_key, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        network_label = f"{network_key[1]} path {network_key[2]} frame {network_key[3]} subswath {network_key[4]} pol {network_key[6]} CRID {network_key[7]} {network_key[8]}"
        rows = sorted(rows, key=lambda row: (row["reference"], row["secondary"], row["product"].get("id", "")))
        intervals: dict[tuple[date, date], int] = defaultdict(int)
        for row in rows:
            intervals[(row["reference"], row["secondary"])] += 1
        duplicates = [key for key, count in intervals.items() if count > 1]
        if duplicates:
            networks.append({
                "network": network_label, "status": "WITHHELD_AMBIGUOUS_DUPLICATE_INTERVALS",
                "pairs": len(rows), "duplicates": [[str(a), str(b)] for a, b in duplicates],
                "reason": "More than one granule represents an identical interval inside the same exact footprint/release/processing network; choose one source explicitly.",
            })
            continue
        arrays: list[np.ndarray] = []
        grids: list[dict[str, Any]] = []
        accepted_rows: list[dict[str, Any]] = []
        grid_problem = None
        for row in rows:
            try:
                with rasterio.open(row["path"]) as ds:
                    tags = ds.tags()
                    if ds.count < 2 or ds.crs is None or ds.crs.to_epsg() is None or not ds.crs.is_projected:
                        grid_problem = "Raster must contain displacement and coherence bands with an identifiable projected CRS."
                        break
                    if str(tags.get("aoi_mask_applied", "")).lower() != "true" or tags.get("aoi_name") != "custom":
                        grid_problem = "Export does not prove masking against this exact custom AOI."
                        break
                    if tags.get("grid_policy") != "common_aoi_lattice":
                        grid_problem = "At least one export is not on the reader's fixed common AOI lattice."
                        break
                    displacement = ds.read(1, masked=True).filled(np.nan).astype("float64")
                    coherence = ds.read(2, masked=True).filled(np.nan).astype("float64")
                    valid = np.isfinite(displacement) & np.isfinite(coherence) & (coherence >= 0.3)
                    displacement[~valid] = np.nan
                    transform = ds.transform
                    grid = {
                        "crs": ds.crs, "epsg": ds.crs.to_epsg(), "shape": (ds.height, ds.width),
                        "transform": transform, "res_x": abs(float(ds.res[0])), "res_y": abs(float(ds.res[1])),
                        "bands": ds.count, "raster": row["path"].name,
                    }
                    if grid["res_x"] <= 0 or grid["res_y"] <= 0 or abs(grid["res_x"] - grid["res_y"]) / max(grid["res_x"], grid["res_y"]) > 0.02:
                        grid_problem = "Common-reference metric buffer requires a near-square projected pixel grid."
                        break
                    arrays.append(displacement)
                    grids.append(grid)
                    accepted_rows.append(row)
            except Exception as exc:
                grid_problem = f"Raster read/validation failed: {type(exc).__name__}: {str(exc)[:160]}"
                break
        if grid_problem:
            networks.append({"network": network_label, "status": "WITHHELD_GRID_OR_MASK_CONTRACT", "pairs": len(rows), "reason": grid_problem})
            continue
        if len(accepted_rows) < 2:
            networks.append({"network": network_label, "status": "WITHHELD_TOO_FEW_PAIRS", "pairs": len(accepted_rows), "reason": "At least two compatible same-network GUNW pairs are needed for common-reference diagnostics."})
            continue
        first_grid = grids[0]
        if any(
            grid["crs"] != first_grid["crs"] or grid["shape"] != first_grid["shape"]
            or not np.allclose(tuple(grid["transform"]), tuple(first_grid["transform"]), rtol=0, atol=1e-9)
            for grid in grids[1:]
        ):
            networks.append({"network": network_label, "status": "WITHHELD_GRID_MISMATCH", "pairs": len(accepted_rows), "reason": "Every pair in a common-reference stack must have identical CRS, shape and affine transform."})
            continue

        target_transformer = Transformer.from_crs("EPSG:4326", first_grid["crs"], always_xy=True)
        target_x, target_y = target_transformer.transform(target_lon, target_lat)
        with rasterio.open(accepted_rows[0]["path"]) as ds:
            target_row, target_col = ds.index(target_x, target_y)
            if not (0 <= target_row < ds.height and 0 <= target_col < ds.width):
                networks.append({"network": network_label, "status": "WITHHELD_TARGET_OUTSIDE_GRID", "pairs": len(accepted_rows), "reason": "In-AOI target does not intersect the exported common grid."})
                continue
            polygon = transform_geom("EPSG:4326", ds.crs, {"type": "Polygon", "coordinates": [ring if ring[0] == ring[-1] else ring + [ring[0]]]})
            inside_aoi = geometry_mask([polygon], out_shape=(ds.height, ds.width), transform=ds.transform, all_touched=False, invert=True)
            resolution = (first_grid["res_x"] + first_grid["res_y"]) / 2
        if not inside_aoi[target_row, target_col]:
            networks.append({"network": network_label, "status": "WITHHELD_TARGET_OUTSIDE_MASK", "pairs": len(accepted_rows), "reason": "Target centre falls outside the exact polygon mask on the exported grid."})
            continue

        common = common_ref.common_mask(arrays) & inside_aoi
        buffer_pixels = int(round(buffer_km * 1000 / resolution))
        stable_candidates = common & ~common_ref.buffer_mask(common.shape, [(target_row, target_col)], buffer_pixels)
        stable_count = int(stable_candidates.sum())
        if stable_count < int(getattr(common_ref, "MIN_COMMON", 200)):
            networks.append({
                "network": network_label, "status": "WITHHELD_INSUFFICIENT_COMMON_REFERENCE_PIXELS",
                "pairs": len(accepted_rows), "common_valid_aoi_pixels": int(common.sum()),
                "common_pixels_outside_target_buffer": stable_count, "required_pixels": int(getattr(common_ref, "MIN_COMMON", 200)),
                "reason": "The pinned science engine refuses a common datum with fewer than 200 pixels valid in every pair outside the target buffer.",
            })
            continue
        try:
            referenced_arrays, datum_offsets = common_ref.rereference(arrays, stable_candidates)
        except ValueError as exc:
            networks.append({"network": network_label, "status": "WITHHELD_COMMON_REFERENCE_FAILED", "pairs": len(accepted_rows), "common_pixels_outside_target_buffer": stable_count, "reason": str(exc)[:240]})
            continue

        any_common_datum = True
        pair_objects = []
        network_pair_rows = []
        for row, meta, source_array, referenced, offset in zip(accepted_rows, [x["meta"] for x in accepted_rows], arrays, referenced_arrays, datum_offsets):
            window = common_ref.window(referenced, target_row, target_col, target_radius_px)
            valid_target = np.isfinite(window)
            n_target = int(valid_target.sum())
            target_value = float(np.median(window[valid_target])) if n_target >= min_target_pixels else None
            reference_value = _finite(offset)
            coherence_mean = None
            try:
                with rasterio.open(row["path"]) as ds:
                    q = ds.read(2, masked=True).filled(np.nan).astype("float64")
                    qwin = common_ref.window(q, target_row, target_col, target_radius_px)
                    qvalid = np.isfinite(qwin) & valid_target
                    if qvalid.any():
                        coherence_mean = float(np.mean(qwin[qvalid]))
            except Exception:
                pass
            metadata = meta
            pair = timeseries.Pair(
                path=metadata.get("path"), direction=metadata.get("direction"),
                ref=row["reference"], sec=row["secondary"],
                value=target_value, n_px=n_target, coherence=coherence_mean,
                source=str(row["product"].get("granule_name") or ""), metadata=metadata,
            )
            pair_objects.append(pair)
            network_pair_rows.append({
                "product_id": row["product"].get("id"),
                "granule_name": row["product"].get("granule_name"),
                "product_type": "GUNW", "processing": metadata.get("processing"),
                "crid": metadata.get("crid"), "network": network_label,
                "reference_date": row["reference"].isoformat(), "secondary_date": row["secondary"].isoformat(),
                "span_days": pair.span_days, "target_local_pixels": n_target,
                "target_mm_common_datum": target_value,
                "datum_offset_mm_removed": reference_value,
                "common_reference_pixels": stable_count,
                "common_valid_aoi_pixels": int(common.sum()),
                "reference_assumption": "median of all-pair-valid AOI pixels outside target buffer; independently surveyed stability not provided",
                "status": "MEASURED_COMMON_DATUM_PAIR" if target_value is not None else "WITHHELD_INSUFFICIENT_TARGET_PIXELS",
            })
        pair_rows.extend(network_pair_rows)
        usable_pairs = [pair for pair in pair_objects if pair.value is not None]
        comps = timeseries.connected_components(usable_pairs) if usable_pairs else []
        network_components = []
        for component_index, epochs in enumerate(comps, 1):
            comp_pairs = [pair for pair in usable_pairs if pair.ref in epochs and pair.sec in epochs]
            n_epochs = len(epochs)
            redundancy = len(comp_pairs) - max(0, n_epochs - 1)
            fit = timeseries.invert_component(comp_pairs, epochs)
            jackknife = timeseries.jackknife(network_label, component_index, comp_pairs, epochs)
            series_available = (
                n_epochs >= 3 and redundancy > 0 and int(fit.get("dof", 0)) > 0
                and isinstance(jackknife, dict) and jackknife.get("testable") is True
                and jackknife.get("robust") is True
            )
            series_rows = []
            if series_available:
                errors = list(fit.get("error_mm", []))
                cumulative = list(fit.get("cumulative_mm", []))
                for idx, epoch in enumerate(fit.get("epochs", [])):
                    fit_error = _json_number(errors[idx]) if idx < len(errors) else None
                    value = _json_number(cumulative[idx]) if idx < len(cumulative) else None
                    series_rows.append({
                        "epoch": epoch.isoformat(), "cumulative_los_mm": value,
                        "graph_fit_standard_error_mm": fit_error,
                        "graph_fit_ci95_low_mm": (value - 1.96 * fit_error) if value is not None and fit_error is not None else None,
                        "graph_fit_ci95_high_mm": (value + 1.96 * fit_error) if value is not None and fit_error is not None else None,
                    })
                any_cumulative_series = True
            comp_status = (
                "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED" if series_available
                else "WITHHELD_NO_REDUNDANT_ROBUST_NETWORK"
            )
            network_components.append({
                "component": component_index, "status": comp_status,
                "first_epoch": epochs[0].isoformat() if epochs else None,
                "last_epoch": epochs[-1].isoformat() if epochs else None,
                "epochs_count": n_epochs, "pairs_count": len(comp_pairs),
                "redundancy": redundancy, "degrees_of_freedom": fit.get("dof"),
                "residual_rms_mm": _json_number(fit.get("residual_rms_mm")),
                "velocity_mm_per_day": _json_number(fit.get("velocity_mm_per_day")),
                "velocity_fit_error_mm_per_day": _json_number(fit.get("velocity_err_mm_per_day")),
                "jackknife": jackknife,
                "series": series_rows,
            })
        network_status = "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED" if any(x["status"] == "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED" for x in network_components) else "COMMON_DATUM_PAIRWISE_ONLY"
        networks.append({
            "network": network_label, "status": network_status,
            "pairs": len(accepted_rows), "common_valid_aoi_pixels": int(common.sum()),
            "common_pixels_outside_target_buffer": stable_count, "target_window_radius_px": target_radius_px,
            "target_window_minimum_valid_pixels": min_target_pixels,
            "reference_offsets_mm": [
                {"reference_date": row["reference"].isoformat(), "secondary_date": row["secondary"].isoformat(), "offset_mm_removed": _json_number(offset)}
                for row, offset in zip(accepted_rows, datum_offsets)
            ],
            "assumption_warning": "The reference median is drawn from the same AOI's common valid pixels outside a 2 km target buffer. It is not an independently surveyed or externally certified stable-ground reference.",
            "components": network_components,
        })

    report["networks"] = networks
    report["pairwise_measurements"] = pair_rows
    report["components"] = [
        {"network": network["network"], **component}
        for network in networks for component in network.get("components", [])
    ]
    if any_cumulative_series:
        report["status"] = "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED"
        report["reason"] = "At least one common-grid GUNW network produced a redundant, jackknife-stable inversion from data-derived common reference values. It remains a diagnostic because stable-ground reference is not independently validated."
    elif any_common_datum:
        report["status"] = "COMMON_DATUM_PAIRWISE_ONLY"
        report["reason"] = "At least one network had enough common pixels for re-referencing, but no connected, redundant, jackknife-robust cumulative series met publication gates."
    elif networks:
        report["status"] = "CUMULATIVE_SERIES_WITHHELD"
        report["reason"] = "No network satisfied the fixed-grid, common-reference, stable-pixel-count, and target-window requirements. Pairwise metrics remain available."
    else:
        report["status"] = "NO_ELIGIBLE_GUNW_NETWORK"
        report["reason"] = "No GUNW products were available for common-reference diagnostics."
    report["rejected_products"] = rejected
    _write_report(output_root, report)
    return report


def _write_report(output_root: Path, report: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "common-reference-timeseries.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    pair_rows = report.get("pairwise_measurements") or []
    if pair_rows:
        with (output_root / "common-reference-pairs.csv").open("w", newline="", encoding="utf-8") as f:
            fields = list(pair_rows[0].keys())
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(pair_rows)
    series_rows = []
    for component in report.get("components") or []:
        for point in component.get("series") or []:
            series_rows.append({"network": component.get("network"), "component": component.get("component"), **point})
    if series_rows:
        with (output_root / "common-reference-series.csv").open("w", newline="", encoding="utf-8") as f:
            fields = list(series_rows[0].keys())
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(series_rows)
