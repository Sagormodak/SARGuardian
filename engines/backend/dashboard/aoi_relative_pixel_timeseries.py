"""Target-free AOI-wide per-pixel GUNW LOS temporal inversion.

The inversion is intentionally diagnostic and target-free. It requires one exact
network identity, a connected temporal graph with redundancy, common valid pixels,
and a broad AOI-derived background mask. Its zero is an AOI-derived reference,
not independently surveyed stable ground; a uniform AOI-wide motion component is
therefore not observable from this stage. No hazard decision is made here.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from scipy.ndimage import label

from dashboard.aoi_displacement_candidates import (
    _finite,
    _read_metric_rasters,
    _score_pair,
)


def _topology(rows: list[dict[str, Any]]) -> dict[str, Any]:
    edges = sorted({(row["reference_date"], row["secondary_date"]) for row in rows})
    epochs = sorted({epoch for edge in edges for epoch in edge})
    parent = {epoch: epoch for epoch in epochs}

    def find(epoch: str) -> str:
        while parent[epoch] != epoch:
            parent[epoch] = parent[parent[epoch]]
            epoch = parent[epoch]
        return epoch

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for ref_date, sec_date in edges:
        union(ref_date, sec_date)
    components = len({find(epoch) for epoch in epochs})
    redundancy = len(edges) - len(epochs) + components
    return {
        "edges": edges,
        "epochs": epochs,
        "epoch_count": len(epochs),
        "pair_count": len(edges),
        "connected_components": components,
        "redundancy": redundancy,
        "connected": bool(epochs) and components == 1,
    }


def _block_reference_medians(
    values: np.ndarray,
    reference_mask: np.ndarray,
    *,
    block_rows: int = 4,
    block_columns: int = 4,
    minimum_pixels_per_block: int = 8,
) -> list[dict[str, float | int]]:
    """Summarize reference support spatially; correlated pixels are not independent samples."""
    row_blocks = np.array_split(np.arange(reference_mask.shape[0]), block_rows)
    col_blocks = np.array_split(np.arange(reference_mask.shape[1]), block_columns)
    result: list[dict[str, float | int]] = []
    for row_index, row_ids in enumerate(row_blocks):
        if not row_ids.size:
            continue
        for column_index, column_ids in enumerate(col_blocks):
            if not column_ids.size:
                continue
            block_values = values[np.ix_(row_ids, column_ids)]
            block_mask = reference_mask[np.ix_(row_ids, column_ids)] & np.isfinite(block_values)
            count = int(np.count_nonzero(block_mask))
            if count < minimum_pixels_per_block:
                continue
            result.append({
                "block_row": int(row_index),
                "block_column": int(column_index),
                "pixels": count,
                "median_mm": float(np.median(block_values[block_mask])),
            })
    return result


def _network_key(item: dict[str, Any]) -> tuple[Any, ...]:
    meta = item["identity"]
    # Unlike target-free spatial screening, pixel inversion keeps sub-swath
    # identity strict. We will not blend independently processed phase rasters
    # across sub-swaths merely because they were written on a common lattice.
    return (
        meta["processing"], meta["path"], meta["frame"], meta["direction"],
        meta["subswath"], meta["bandwidth"], meta["polarisation"], meta["crid"],
        item["grid"],
    )


def _write_raster(path: Path, source: dict[str, Any], values: np.ndarray, valid: np.ndarray,
                  *, aoi_hash: str, metric: str, units: str, network: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    src_path = source["raster_path"]
    with rasterio.open(src_path) as src:
        profile = src.profile.copy()
        tags = src.tags()
    profile.update(count=1, dtype="float32", nodata=-9999.0, compress="deflate")
    out_values = np.full(values.shape, -9999.0, dtype="float32")
    out_values[valid & np.isfinite(values)] = values[valid & np.isfinite(values)].astype("float32")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(out_values, 1)
        dst.set_band_description(1, metric)
        dst.update_tags(
            **{
                "schema_version": "sarguardian-aoi-relative-pixel-timeseries/1.0",
                "aoi_wkt_sha256": aoi_hash,
                "metric": metric,
                "units": units,
                "network": network,
                "target_required": "false",
                "reference_policy": "AOI-derived common background; not independently validated stable ground",
                "movement_confirmed": "false",
                "hazard_detected": "false",
                "source": tags.get("source", ""),
            }
        )
    return {
        "role": metric,
        "relative_path": path.relative_to(Path(source["raster_path"]).parents[2]).as_posix(),
        "bytes": path.stat().st_size,
        "valid_pixels": int(np.count_nonzero(valid & np.isfinite(values))),
        "units": units,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _base_report(aoi_hash: str | None, status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "sarguardian-aoi-relative-pixel-timeseries/1.0",
        "status": status,
        "aoi_wkt_sha256": aoi_hash,
        "analysis_scope": "target-free per-pixel GUNW LOS temporal inversion",
        "target_required": False,
        "movement_confirmed": False,
        "hazard_detected": False,
        "reference_independently_validated": False,
        "reason": reason,
        "minimum_pairs": 3,
        "minimum_network_redundancy": 1,
        "minimum_common_valid_pixels": 200,
        "minimum_spatial_reference_blocks": 4,
        "networks": [],
        "warnings": [
            "The time series is relative to a spatially balanced AOI-derived background, not an independently surveyed stable-ground datum.",
            "Pairwise re-referencing suppresses spatially uniform AOI-wide motion and cannot prove absolute displacement.",
            "A minimum block count improves spatial distribution but cannot prove those blocks are geologically stable.",
            "Residual spatial ramps, atmosphere, phase-unwrapping errors, decorrelation and geocoding/systematic errors may remain.",
            "LOS velocity is not vertical displacement or 3-D ground motion.",
            "Fit sigma is residual-based OLS uncertainty only; it omits atmospheric, orbital, reference, phase-unwrapping and spatially correlated measurement errors.",
            "A valid velocity raster is a research diagnostic, not a landslide/glacier-collapse declaration or hazard alert.",
        ],
        "artifacts": [],
    }


def build_aoi_relative_pixel_timeseries_report(
    products: list[dict[str, Any]],
    output_root: Path,
    aoi_wkt_sha256: str | None,
    *,
    minimum_pairs: int = 3,
    minimum_redundancy: int = 1,
    minimum_common_valid_pixels: int = 200,
    minimum_reference_blocks: int = 4,
    minimum_pixels_per_reference_block: int = 8,
    coherence_threshold: float = 0.3,
    robust_candidate_z: float = 4.5,
    background_window_pixels: int = 11,
) -> dict[str, Any]:
    """Invert eligible connected redundant GUNW networks over the AOI, with no target point."""
    output_root = output_root.resolve()
    report = _base_report(
        aoi_wkt_sha256, "NOT_STARTED",
        "Target-free pixel inversion only runs on connected, redundant GUNW networks with sufficient common reference support.",
    )
    try:
        accepted, rejected = _read_metric_rasters(products, output_root)
    except Exception as exc:
        report.update({"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {str(exc)[:240]}", "rejected_products": []})
        _write_report(output_root, report)
        return report

    gunw = [item for item in accepted if item["product_type"] == "GUNW" and item["metric"] == "GUNW_LOS_DISPLACEMENT_MM"]
    # The reader applies finite/coherence quality checks and the common AOI-grid contract.
    for item in gunw:
        item["valid"] &= np.isfinite(item["values"])
    report["products_examined"] = len({item["product_id"] for item in gunw})
    report["rejected_products"] = [
        {"product_id": item.get("product_id"), "product_type": item.get("product_type"),
         "status": item.get("status"), "reason": item.get("reason")}
        for item in rejected if item.get("product_type") == "GUNW"
    ]
    if not gunw:
        report.update({
            "status": "NO_ELIGIBLE_GUNW_EXPORTS",
            "reason": "No retained GUNW export satisfied identity, AOI mask, common lattice, projected CRS and export-quality requirements.",
        })
        _write_report(output_root, report)
        return report

    scored = [
        _score_pair(item, threshold_z=robust_candidate_z,
                    background_window_pixels=background_window_pixels,
                    minimum_valid_pixels=minimum_common_valid_pixels)
        for item in gunw
    ]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in scored:
        groups[_network_key(item)].append(item)

    out_dir = output_root / "aoi-relative-pixel-timeseries"
    network_reports: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []
    for _, rows in sorted(groups.items(), key=lambda pair: str(pair[0])):
        rows = sorted(rows, key=lambda row: (row["reference_date"], row["secondary_date"], row["product_id"]))
        meta = rows[0]["identity"]
        label = (
            f"{meta['direction']} path {meta['path']} frame {meta['frame']} subswath {meta['subswath']} "
            f"bandwidth {meta['bandwidth']} pol {meta['polarisation']} CRID {meta['crid']}"
        )
        topology = _topology(rows)
        network = {
            "network": label,
            "status": "NOT_STARTED",
            "pair_count": topology["pair_count"],
            "epoch_count": topology["epoch_count"],
            "connected_components": topology["connected_components"],
            "redundancy": topology["redundancy"],
            "epochs": topology["epochs"],
            "common_valid_pixels": 0,
            "reference_pixels": 0,
            "artifacts": [],
            "movement_confirmed": False,
            "hazard_detected": False,
        }
        if len({(row["reference_date"], row["secondary_date"]) for row in rows}) != len(rows):
            network.update({
                "status": "WITHHELD_DUPLICATE_ACQUISITION_INTERVAL",
                "reason": "More than one raster represents the same interval in this exact network; duplicate edges cannot add temporal redundancy.",
            })
            network_reports.append(network)
            continue
        if topology["pair_count"] < minimum_pairs or topology["epoch_count"] < 3:
            network.update({
                "status": "WITHHELD_TOO_FEW_PAIRS",
                "reason": f"Need at least {minimum_pairs} unique GUNW pairs and 3 epochs.",
            })
            network_reports.append(network)
            continue
        if not topology["connected"]:
            network.update({
                "status": "WITHHELD_DISCONNECTED_NETWORK",
                "reason": "The graph contains disconnected acquisition blocks; no single cumulative series can link them.",
            })
            network_reports.append(network)
            continue
        if topology["redundancy"] < minimum_redundancy:
            network.update({
                "status": "WITHHELD_NO_TEMPORAL_REDUNDANCY",
                "reason": f"Network redundancy is {topology['redundancy']}; at least {minimum_redundancy} independent cycle(s) are required.",
            })
            network_reports.append(network)
            continue

        reference_dates = topology["epochs"]
        grid_shape = rows[0]["valid"].shape
        if any(item["valid"].shape != grid_shape or item["grid"] != rows[0]["grid"] for item in rows):
            network.update({
                "status": "WITHHELD_GRID_MISMATCH",
                "reason": "All GUNW pair rasters must match the same projected CRS, affine transform and fixed AOI lattice.",
            })
            network_reports.append(network)
            continue

        common_valid = np.ones(grid_shape, dtype=bool)
        candidate_union = np.zeros(grid_shape, dtype=bool)
        for item in rows:
            common_valid &= item["valid"] & np.isfinite(item["values"])
            candidate_union |= item["candidate_mask"]
        common_count = int(np.count_nonzero(common_valid))
        network["common_valid_pixels"] = common_count
        if common_count < minimum_common_valid_pixels:
            network.update({
                "status": "WITHHELD_INSUFFICIENT_COMMON_VALID_PIXELS",
                "reason": f"Only {common_count} pixels are finite/quality-valid in every selected pair; need {minimum_common_valid_pixels}.",
            })
            network_reports.append(network)
            continue

        stable = common_valid & ~candidate_union
        reference_count = int(np.count_nonzero(stable))
        network["reference_pixels"] = reference_count
        if reference_count < minimum_common_valid_pixels:
            network.update({
                "status": "WITHHELD_INSUFFICIENT_BACKGROUND_REFERENCE",
                "reason": f"Only {reference_count} common pixels remain after excluding per-pair spatial candidates; need {minimum_common_valid_pixels}.",
            })
            network_reports.append(network)
            continue

        block_reference_rows = [
            _block_reference_medians(
                item["values"], stable,
                minimum_pixels_per_block=minimum_pixels_per_reference_block,
            )
            for item in rows
        ]
        block_counts = [len(item) for item in block_reference_rows]
        minimum_blocks_observed = min(block_counts, default=0)
        network["minimum_spatial_reference_blocks_observed"] = minimum_blocks_observed
        network["reference_blocks_per_pair"] = block_counts
        if minimum_blocks_observed < minimum_reference_blocks:
            network.update({
                "status": "WITHHELD_POOR_REFERENCE_SPATIAL_DISTRIBUTION",
                "reason": (
                    f"The common background reference occupies only {minimum_blocks_observed} spatial blocks "
                    f"in at least one pair; need {minimum_reference_blocks}. A concentrated reference can be "
                    "biased by spatially correlated deformation or acquisition artefacts."
                ),
            })
            network_reports.append(network)
            continue

        global_pixel_offsets = [float(np.median(item["values"][stable])) for item in rows]
        # Balance the reference spatially by taking a median of supported block
        # medians. It reduces dominance by one dense corner, but it is still an
        # AOI-derived relative datum and does not establish geologic stability.
        offsets = [
            float(np.median([block["median_mm"] for block in blocks]))
            for blocks in block_reference_rows
        ]
        reference_offset_sensitivity = [
            abs(block_offset - pixel_offset)
            for block_offset, pixel_offset in zip(offsets, global_pixel_offsets)
        ]
        reference_block_dispersion = []
        for blocks in block_reference_rows:
            medians = np.asarray([block["median_mm"] for block in blocks], dtype="float64")
            centre = float(np.median(medians))
            reference_block_dispersion.append(
                float(1.4826 * np.median(np.abs(medians - centre)))
            )
        edge_values = np.stack([
            (item["values"] - offset).astype("float32", copy=False)
            for item, offset in zip(rows, offsets)
        ])
        epoch_index = {epoch: index for index, epoch in enumerate(reference_dates)}
        incidence = np.zeros((len(rows), len(reference_dates)), dtype="float64")
        for edge_index, item in enumerate(rows):
            incidence[edge_index, epoch_index[item["reference_date"]]] = -1.0
            incidence[edge_index, epoch_index[item["secondary_date"]]] = 1.0
        reduced = incidence[:, 1:]
        if int(np.linalg.matrix_rank(reduced)) != len(reference_dates) - 1:
            network.update({
                "status": "WITHHELD_RANK_DEFICIENT_NETWORK",
                "reason": "The connected network does not provide full-rank epoch differences.",
            })
            network_reports.append(network)
            continue

        pixel_indices = np.flatnonzero(common_valid)
        observations = edge_values.reshape(len(rows), -1)[:, pixel_indices].astype("float64")
        observed_pair_support = np.zeros(grid_shape, dtype="uint16")
        candidate_pair_support = np.zeros(grid_shape, dtype="uint16")
        for item in rows:
            observed_pair_support += item["valid"].astype("uint16")
            candidate_pair_support += item["candidate_mask"].astype("uint16")
        # Fix the earliest epoch to zero, and invert pairwise LOS differences with
        # least squares. The graph has redundant edges so residuals are measurable.
        inverse = np.linalg.pinv(reduced)
        relative_epochs_flat = np.vstack([
            np.zeros((1, pixel_indices.size), dtype="float64"),
            inverse @ observations,
        ])
        closure_residual = reduced @ relative_epochs_flat[1:] - observations
        closure_rmse = np.sqrt(np.mean(closure_residual ** 2, axis=0))
        day_values = np.array([
            (date.fromisoformat(epoch) - date.fromisoformat(reference_dates[0])).days
            for epoch in reference_dates
        ], dtype="float64")
        year_values = day_values / 365.25
        x = year_values - float(np.mean(year_values))
        sxx = float(np.sum(x ** 2))
        if sxx <= 0 or len(reference_dates) < 3:
            network.update({"status": "WITHHELD_INSUFFICIENT_EPOCH_SPAN", "reason": "At least 3 distinct dates are required for a velocity fit."})
            network_reports.append(network)
            continue
        epoch_mean = np.mean(relative_epochs_flat, axis=0)
        velocity_mm_year = np.sum(x[:, None] * (relative_epochs_flat - epoch_mean), axis=0) / sxx
        fitted = epoch_mean[None, :] + x[:, None] * velocity_mm_year[None, :]
        fit_residual = relative_epochs_flat - fitted
        dof = len(reference_dates) - 2
        sigma_rate = np.sqrt(np.sum(fit_residual ** 2, axis=0) / max(dof, 1) / sxx)
        closure_rmse_map = np.full(grid_shape, np.nan, dtype="float32")
        velocity_map = np.full(grid_shape, np.nan, dtype="float32")
        sigma_map = np.full(grid_shape, np.nan, dtype="float32")
        closure_rmse_map.flat[pixel_indices] = closure_rmse.astype("float32")
        velocity_map.flat[pixel_indices] = velocity_mm_year.astype("float32")
        sigma_map.flat[pixel_indices] = sigma_rate.astype("float32")

        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-").lower()
        velocity_artifact = _write_raster(
            out_dir / f"gunw-los-velocity-mm-year-{slug}.tif", rows[0], velocity_map, common_valid,
            aoi_hash=str(aoi_wkt_sha256 or ""), metric="AOI-relative GUNW LOS velocity", units="mm/year", network=label,
        )
        sigma_artifact = _write_raster(
            out_dir / f"gunw-los-velocity-fit-sigma-mm-year-{slug}.tif", rows[0], sigma_map, common_valid,
            aoi_hash=str(aoi_wkt_sha256 or ""), metric="GUNW LOS velocity fit sigma", units="mm/year", network=label,
        )
        closure_artifact = _write_raster(
            out_dir / f"gunw-los-closure-rmse-mm-{slug}.tif", rows[0], closure_rmse_map, common_valid,
            aoi_hash=str(aoi_wkt_sha256 or ""), metric="GUNW LOS inversion closure RMSE", units="mm", network=label,
        )
        artifacts = [velocity_artifact, sigma_artifact, closure_artifact]
        support_artifacts = [
            _write_raster(
                out_dir / f"gunw-los-candidate-mask-{slug}.tif", rows[0],
                candidate_union.astype("float32"), common_valid,
                aoi_hash=str(aoi_wkt_sha256 or ""), metric="GUNW LOS spatial candidate mask",
                units="binary candidate flag", network=label,
            ),
            _write_raster(
                out_dir / f"gunw-los-candidate-pair-count-{slug}.tif", rows[0],
                candidate_pair_support.astype("float32"), common_valid,
                aoi_hash=str(aoi_wkt_sha256 or ""), metric="GUNW candidate pair support count",
                units="pair count", network=label,
            ),
            _write_raster(
                out_dir / f"gunw-los-observed-pair-count-{slug}.tif", rows[0],
                observed_pair_support.astype("float32"), common_valid,
                aoi_hash=str(aoi_wkt_sha256 or ""), metric="GUNW valid observed pair count",
                units="pair count", network=label,
            ),
            _write_raster(
                out_dir / f"gunw-los-common-reference-mask-{slug}.tif", rows[0],
                stable.astype("float32"), common_valid,
                aoi_hash=str(aoi_wkt_sha256 or ""), metric="AOI-derived reference mask",
                units="binary reference-pixel flag", network=label,
            ),
        ]
        artifacts.extend(support_artifacts)
        all_artifacts.extend(artifacts)

        candidate_pixel_indices = np.flatnonzero(common_valid & candidate_union)
        epoch_statistics = []
        for i, epoch in enumerate(reference_dates):
            values = np.full(grid_shape, np.nan, dtype="float32")
            values.flat[pixel_indices] = relative_epochs_flat[i].astype("float32")
            epoch_artifact = _write_raster(
                out_dir / f"gunw-los-relative-{epoch}-{slug}.tif", rows[0], values, common_valid,
                aoi_hash=str(aoi_wkt_sha256 or ""), metric=f"AOI-relative GUNW LOS displacement at {epoch}",
                units="mm", network=label,
            )
            artifacts.append(epoch_artifact)
            all_artifacts.append(epoch_artifact)
            series_values = relative_epochs_flat[i]
            candidate_summary = None
            if candidate_pixel_indices.size:
                local_candidate_indices = np.searchsorted(pixel_indices, candidate_pixel_indices)
                candidate_values = series_values[local_candidate_indices]
                candidate_summary = {
                    "candidate_pixels": int(candidate_values.size),
                    "median_mm": float(np.median(candidate_values)),
                    "p05_mm": float(np.percentile(candidate_values, 5)),
                    "p95_mm": float(np.percentile(candidate_values, 95)),
                }
            epoch_statistics.append({
                "epoch": epoch,
                "aoi_common_valid_median_mm": float(np.median(series_values)),
                "aoi_common_valid_p05_mm": float(np.percentile(series_values, 5)),
                "aoi_common_valid_p95_mm": float(np.percentile(series_values, 95)),
                "candidate_pixel_summary": candidate_summary,
            })

        common_relative_velocity = velocity_mm_year
        network.update({
            "status": "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_REFERENCE_UNVALIDATED",
            "reason": "The graph was inverted on common valid pixels after subtracting a robust AOI-derived background per pair. This is relative LOS diagnostics; stable ground is not independently validated.",
            "reference_policy": "Spatially balanced median of common-valid 4x4 AOI blocks outside per-pair candidate masks; relative reference, not independently validated stable ground",
            "reference_medians_removed_mm": [round(value, 6) for value in offsets],
            "global_pixel_medians_removed_mm": [round(value, 6) for value in global_pixel_offsets],
            "block_reference_vs_global_median_difference_mm": [round(value, 6) for value in reference_offset_sensitivity],
            "reference_block_robust_dispersion_mm": [round(value, 6) for value in reference_block_dispersion],
            "minimum_reference_pixels": minimum_common_valid_pixels,
            "minimum_reference_blocks": minimum_reference_blocks,
            "minimum_pixels_per_reference_block": minimum_pixels_per_reference_block,
            "reference_spatial_support": "4x4 equal-grid blocks; at least 4 blocks with >=8 valid common background pixels per pair",
            "reference_independent_stability": False,
            "common_valid_pixels": common_count,
            "reference_pixels": reference_count,
            "candidate_pixels_in_complete_series": int(candidate_pixel_indices.size),
            "median_relative_velocity_mm_year": float(np.median(common_relative_velocity)),
            "robust_relative_velocity_scatter_mm_year": _finite(1.4826 * np.median(np.abs(common_relative_velocity - np.median(common_relative_velocity)))),
            "median_fit_sigma_mm_year": float(np.median(sigma_rate)),
            "median_network_closure_rmse_mm": float(np.median(closure_rmse)),
            "epoch_statistics": epoch_statistics,
            "artifacts": artifacts,
            "movement_confirmed": False,
            "hazard_detected": False,
        })
        network_reports.append(network)

    successful = [item for item in network_reports if item["status"] == "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_REFERENCE_UNVALIDATED"]
    report.update({
        "status": "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE" if successful else "WITHHELD_SCIENCE_GATES",
        "reason": (
            f"{len(successful)} compatible GUNW network(s) produced target-free AOI-relative pixelwise LOS time-series diagnostics; see each network's gates and limitations."
            if successful else
            "No GUNW network passed the connected/redundant graph, common valid-pixel and reference-support gates. Spatial candidate screening remains available independently."
        ),
        "networks": network_reports,
        "artifacts": all_artifacts,
        "networks_calculated": len(successful),
        "movement_confirmed": False,
        "hazard_detected": False,
        "reference_independently_validated": False,
    })
    _write_report(output_root, report)
    return report


def _write_report(output_root: Path, report: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "aoi-relative-pixel-timeseries.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
