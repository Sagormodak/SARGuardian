#!/usr/bin/env python3
"""Build georeferenced display previews and a pair-aware interactive dashboard."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import colormaps
from PIL import Image
from rasterio.features import geometry_mask
from rasterio.transform import Affine, array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject

SCHEMA = "sarguardian-web-dashboard/1.0"
WEB_CRS = "EPSG:4326"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Required dashboard input missing: {path.name}")
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return result


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def _parse_pixel_stack_log(root: Path, diagnostics: dict[str, Any], key: str) -> dict[str, Any]:
    """Extract only support/cluster diagnostics; never publish fragile per-pixel rates."""
    entry = diagnostics.get(key) if isinstance(diagnostics.get(key), dict) else {}
    log_rel = str(entry.get("log") or "").strip()
    result: dict[str, Any] = {
        "status": str(entry.get("status") or "NOT_REPORTED"),
        "available": False,
        "pairs_examined": None,
        "chains": [],
        "log_status": "NOT_AVAILABLE",
    }
    if not log_rel:
        return result
    try:
        path = safe_path(root, (Path("science-diagnostics") / log_rel).as_posix())
        if not path.is_file():
            result["log_status"] = "LOG_FILE_MISSING"
            return result
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError, RuntimeError) as exc:
        result["log_status"] = type(exc).__name__
        return result

    total_match = re.search(r"(?m)^\[INFO\]\s+(\d+)\s+all pair\(s\)", text)
    marker_pairs = re.search(r"(?m)^PIXEL_STACK_PAIRS_EXAMINED=(\d+)\s*$", text)
    marker_networks = re.search(r"(?m)^PIXEL_STACK_EXACT_NETWORKS=(\d+)\s*$", text)
    marker_repeat = re.search(r"(?m)^PIXEL_STACK_NETWORKS_WITH_2_PLUS_PAIRS=(\d+)\s*$", text)
    marker_status = re.search(r"(?m)^PIXEL_STACK_STATUS=(\S+)\s*$", text)
    if total_match:
        result["pairs_examined"] = int(total_match.group(1))
    if marker_pairs:
        result["pairs_examined"] = int(marker_pairs.group(1))
    if marker_networks:
        result["exact_networks"] = int(marker_networks.group(1))
    if marker_repeat:
        result["networks_with_2_plus_pairs"] = int(marker_repeat.group(1))
    if marker_status:
        result["status"] = marker_status.group(1)
    header = re.compile(
        r"(?m)^\s*(?P<geometry>[AD]\d{3})\s+chain\s+(?P<chain>\d+)\s+"
        r"(?P<start>\d{4}-\d{2}-\d{2})\s+\.\.\s+"
        r"(?P<end>\d{4}-\d{2}-\d{2})\s+\((?P<pairs>\d+)\s+pairs,\s*(?P<days>\d+)\s+d\)\s*$"
    )
    matches = list(header.finditer(text))
    chains: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end():end]
        support = re.search(
            r"pixels with a complete series\s*:\s*([\d,]+)\s+of\s+([\d,]+)",
            block,
            flags=re.I,
        )
        complete = int(support.group(1).replace(",", "")) if support else None
        total = int(support.group(2).replace(",", "")) if support else None
        coverage = (100.0 * complete / total) if complete is not None and total else None
        cluster = re.search(r"largest connected cluster\s*:\s*([\d,]+)\s+px", block, flags=re.I)
        noise = re.search(
            r"clusters from noise ALONE\s*:\s*median\s+([\d,]+)\s+px,\s*95th pct\s+([\d,]+)\s+px,\s*max\s+([\d,]+)\s+px",
            block,
            flags=re.I,
        )
        verdict = re.search(r"VERDICT:\s*([A-Z ]+)", block)
        nothing_to_fit = bool(re.search(r"nothing to fit", block, flags=re.I))
        chains.append({
            "geometry": match.group("geometry"),
            "chain": int(match.group("chain")),
            "start_date": match.group("start"),
            "end_date": match.group("end"),
            "pair_count": int(match.group("pairs")),
            "duration_days": int(match.group("days")),
            "complete_pixels": complete,
            "total_pixels": total,
            "complete_support_pct": coverage,
            "largest_cluster_pixels": int(cluster.group(1).replace(",", "")) if cluster else None,
            "noise_cluster_median_pixels": int(noise.group(1).replace(",", "")) if noise else None,
            "noise_cluster_p95_pixels": int(noise.group(2).replace(",", "")) if noise else None,
            "noise_cluster_max_pixels": int(noise.group(3).replace(",", "")) if noise else None,
            "finding": (
                "NO_COMPLETE_SERIES" if nothing_to_fit or complete == 0 else
                "NOT_TESTABLE_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT"
                if verdict and "NOT TESTABLE" in verdict.group(1) else
                "NO_CLUSTER_ABOVE_NOISE_SCREEN" if verdict and "NO DETECTION" in verdict.group(1) else
                "REVIEW_REQUIRED"
            ),
        })
    result.update({
        "available": bool(chains),
        "log_status": (
            "PARSED" if chains else
            "PARSED_NO_COMPATIBLE_REPEATED_NETWORK"
            if result.get("status") == "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK" else
            "NO_CHAIN_BLOCKS_FOUND"
        ),
        "chains": chains,
    })
    return result


def build_pixel_stack_explanation(root: Path, diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Build a plain-language explanation of the older exploratory GUNW screen."""
    primary = _parse_pixel_stack_log(root, diagnostics, "pixel_stack")
    sensitivity = _parse_pixel_stack_log(root, diagnostics, "common_mode_sensitivity")
    same_support = False
    if primary["available"] and sensitivity["available"]:
        primary_counts = {
            chain["geometry"]: (chain["complete_pixels"], chain["total_pixels"])
            for chain in primary["chains"]
        }
        sensitivity_counts = {
            chain["geometry"]: (chain["complete_pixels"], chain["total_pixels"])
            for chain in sensitivity["chains"]
        }
        same_support = primary_counts == sensitivity_counts
    sensitivity_entry = diagnostics.get("common_mode_sensitivity")
    sensitivity_log_warning = False
    if isinstance(sensitivity_entry, dict):
        try:
            rel = str(sensitivity_entry.get("log") or "").strip()
            if rel:
                path = safe_path(root, (Path("science-diagnostics") / rel).as_posix())
                if path.is_file():
                    sensitivity_log_warning = "atmosphere will dominate" in path.read_text(
                        encoding="utf-8", errors="replace"
                    ).lower()
        except (OSError, ValueError, RuntimeError):
            pass
    chains = primary.get("chains", [])
    if primary.get("status") == "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK":
        pairs = primary.get("pairs_examined")
        networks = primary.get("exact_networks")
        repeat_networks = primary.get("networks_with_2_plus_pairs")
        pair_text = "the retained GUNW products" if pairs is None else f"{pairs} GUNW pair(s)"
        network_text = "an unknown number of separate networks" if networks is None else f"{networks} separate measurement networks"
        repeat_text = "an unreported number" if repeat_networks is None else str(repeat_networks)
        interpretation = (
            f"The target-free screen checked {pair_text}. They belong to {network_text}; "
            f"{repeat_text} network(s) contained two or more consecutive pair intervals with the same "
            "look, path, frame, subswath, bandwidth, polarization and processing CRID. "
            "A multi-date per-pixel LOS time series therefore could not be calculated without mixing "
            "different measurement networks. This is NOT TESTABLE, not NO DETECTION, and does not mean zero motion."
        )
        return {
            "schema_version": "sarguardian-gunw-pixel-stack-explainer/1.0",
            "status": primary.get("status"),
            "available": False,
            "pairs_examined": pairs,
            "exact_networks": networks,
            "networks_with_2_plus_pairs": repeat_networks,
            "chains": [],
            "common_mode_sensitivity": {
                "status": sensitivity.get("status", "NOT_REPORTED"),
                "available": sensitivity.get("available", False),
                "same_complete_pixel_support": False,
                "atmospheric_common_mode_warning": sensitivity_log_warning,
            },
            "interpretation": interpretation,
            "limitations": [
                "A multi-date GUNW series is only valid within a homogeneous network with the same look/path, frame, subswath, bandwidth, polarization and processing CRID.",
                "Pairwise GUNW LOS measurements are not cumulative displacement, vertical motion or full 3-D motion.",
                "This is NOT TESTABLE because a compatible repeated network is unavailable; it is not a NO DETECTION result.",
                "AOI-wide GOFF spatial anomalies remain a separate offset screen and are not ground displacement.",
            ],
        }
    not_testable = sum(
        chain.get("finding") == "NOT_TESTABLE_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT"
        for chain in chains
    )
    no_complete = sum(chain.get("finding") == "NO_COMPLETE_SERIES" for chain in chains)
    no_detection = sum(chain.get("finding") == "NO_CLUSTER_ABOVE_NOISE_SCREEN" for chain in chains)
    if not_testable:
        interpretation = (
            f"{not_testable} GUNW chain(s) had a few complete pixel time series, but not enough "
            "nearby valid pixels to estimate the spatial background-noise level. The noise-only "
            "cluster test was therefore withheld. "
            f"{no_complete} other chain(s) had no complete pixel series at all. "
            "This result is NOT TESTABLE, not a no-detection result, and is not evidence of zero ground motion."
        )
    elif chains:
        interpretation = (
            "This older exploratory per-pixel screen had extremely sparse complete time-series support. "
            f"{no_detection} chain(s) completed the noise comparison without a cluster above its noise-only screen; "
            f"{no_complete} chain(s) had no complete pixels to fit. This is not evidence of zero ground motion."
        )
    else:
        interpretation = (
            "The detailed per-pixel screen log was not available in this result bundle; "
            "no pixel-support conclusion is inferred."
        )
    return {
        "schema_version": "sarguardian-gunw-pixel-stack-explainer/1.0",
        "status": primary.get("status", "NOT_REPORTED"),
        "available": primary.get("available", False),
        "pairs_examined": primary.get("pairs_examined"),
        "chains": chains,
        "common_mode_sensitivity": {
            "status": sensitivity.get("status", "NOT_REPORTED"),
            "available": sensitivity.get("available", False),
            "same_complete_pixel_support": same_support,
            "atmospheric_common_mode_warning": sensitivity_log_warning,
        },
        "interpretation": interpretation,
        "limitations": [
            "This is an exploratory residual-based GUNW LOS screen, not independent geophysical validation.",
            "Complete time-series pixels are only a handful of cells and cannot represent the whole AOI.",
            "A spatial-noise null cannot be tested without enough nearby valid pixels; NOT TESTABLE is not NO DETECTION.",
            "Removing pairwise common mode can suppress real broad AOI-wide motion; retaining it can leave atmospheric/orbit bias.",
            "The separate strict AOI-relative time-series inversion has its own connected-network and common-pixel gates; the two screens are not interchangeable.",
            "No detection by this screen does not mean no movement.",
        ],
    }


def parse_wkt(value: str) -> list[list[float]]:
    match = re.fullmatch(r"\s*POLYGON\s*\(\(\s*(.*?)\s*\)\)\s*", value, flags=re.I)
    if not match:
        raise ValueError("Dashboard requires an already-validated single-ring WKT POLYGON")
    ring = []
    for token in match.group(1).split(","):
        xy = token.strip().split()
        if len(xy) != 2:
            raise ValueError("Malformed AOI WKT coordinate")
        x, y = float(xy[0]), float(xy[1])
        if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
            raise ValueError("AOI coordinate outside WGS84 limits")
        ring.append([x, y])
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("AOI WKT ring must be closed")
    return ring


def reproject_band(path: Path, band: int, aoi_geometry: dict[str, Any]) -> tuple[np.ndarray, tuple[float, float, float, float], dict[str, Any]]:
    with rasterio.open(path) as src:
        if src.crs is None or band < 1 or band > src.count:
            raise ValueError(f"Missing CRS or invalid band in {path.name}")
        source = src.read(band).astype("float32", copy=False)
        if src.nodata is not None:
            source = source.copy()
            source[source == src.nodata] = np.nan
        source[~np.isfinite(source)] = np.nan
        source_valid = int(np.isfinite(source).sum())
        transform, width, height = calculate_default_transform(
            src.crs, WEB_CRS, src.width, src.height, *src.bounds
        )
        if width < 1 or height < 1:
            raise ValueError(f"Invalid preview raster dimensions for {path.name}")
        # Keep presentation previews compact. Native GeoTIFF is never resampled or replaced.
        shrink = min(1.0, 1024.0 / width, 1024.0 / height)
        out_width = max(1, int(round(width * shrink)))
        out_height = max(1, int(round(height * shrink)))
        transform = transform @ Affine.scale(width / out_width, height / out_height)
        width, height = out_width, out_height
        if width * height > 1_100_000:
            raise ValueError(f"Preview raster exceeds the display-pixel cap for {path.name}")
        out = np.full((height, width), np.nan, dtype="float32")
        reproject(
            source=source, destination=out,
            src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
            dst_transform=transform, dst_crs=WEB_CRS, dst_nodata=np.nan,
            resampling=Resampling.nearest, init_dest_nodata=True,
        )
        # Clip the display preview to the exact AOI polygon; never expose the
        # rectangular raster window outside the requested polygon as data.
        inside_aoi = geometry_mask([aoi_geometry], out_shape=(height, width), transform=transform, invert=True, all_touched=False)
        out[~inside_aoi] = np.nan
        west, south, east, north = array_bounds(height, width, transform)
        if not all(math.isfinite(v) for v in (west, south, east, north)) or west >= east or south >= north:
            raise ValueError(f"Invalid WGS84 bounds for {path.name}")
        description = (src.descriptions[band - 1] if src.descriptions else None) or f"Band {band}"
        unit = (src.units[band - 1] if src.units else None) or ""
        if not unit:
            found = re.search(r"\(([^()]*)\)\s*$", description)
            unit = found.group(1).strip() if found else ("dimensionless" if "coherence" in description.lower() else "source units not declared")
        return out, (float(west), float(south), float(east), float(north)), {
            "description": description.strip(), "units": unit, "source_crs": src.crs.to_string(),
            "source_transform": [float(v) for v in src.transform[:6]],
            "source_width": src.width, "source_height": src.height, "source_valid_pixels": source_valid,
            "data_type": src.dtypes[band - 1], "source_nodata": float(src.nodata) if src.nodata is not None and math.isfinite(float(src.nodata)) else None,
            "preview_crs": WEB_CRS, "preview_transform": [float(v) for v in transform[:6]],
            "preview_width": width, "preview_height": height,
        }


def write_rgba(values: np.ndarray, lo: float, hi: float, kind: str, path: Path) -> tuple[int, float | None, float | None]:
    valid = np.isfinite(values)
    count = int(valid.sum())
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if count:
        normalized = np.clip((np.where(valid, values, lo) - lo) / (hi - lo), 0.0, 1.0)
        palette = "viridis" if kind == "coherence" else "RdBu_r"
        rgba[..., :3] = (colormaps[palette](normalized)[..., :3] * 255).astype(np.uint8)
        rgba[..., 3] = np.where(valid, 220, 0).astype(np.uint8)
        if kind == "binary_mask":
            # Red means retained global-MAD outlier for spatial review;
            # green means robust inlier. This is not displacement magnitude.
            rgba[valid & (values < 0.5), :3] = np.array([255, 110, 95], dtype=np.uint8)
            rgba[valid & (values >= 0.5), :3] = np.array([55, 190, 155], dtype=np.uint8)
        elif kind == "candidate_mask":
            selected = valid & (values > 0.5)
            rgba[..., 3] = np.where(selected, 220, 0).astype(np.uint8)
            rgba[selected, :3] = np.array([255, 110, 95], dtype=np.uint8)
        elif kind == "reference_mask":
            selected = valid & (values > 0.5)
            rgba[..., 3] = np.where(selected, 190, 0).astype(np.uint8)
            rgba[selected, :3] = np.array([55, 190, 155], dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", optimize=True)
    return count, (float(np.nanmin(values)) if count else None), (float(np.nanmax(values)) if count else None)


def write_viewer(path: Path) -> None:
    page = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SARGuardian · Interactive Science Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.css">
<style>
:root{color-scheme:dark;--bg:#07121c;--panel:#0e1e2a;--edge:#254050;--ink:#edf7fb;--muted:#a5bec8;--aqua:#66e2d3;--amber:#f7c76b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#123444,#07121c 55%);color:var(--ink);font:14px/1.45 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:22px}header{display:flex;gap:18px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;border-bottom:1px solid var(--edge);padding-bottom:16px}h1{font-size:clamp(25px,3vw,38px);line-height:1.05;letter-spacing:-.035em;margin:7px 0}.kicker{color:var(--aqua);font-size:10px;font-weight:800;letter-spacing:.17em;text-transform:uppercase}.muted{color:var(--muted)}button,select,input{font:inherit;color:inherit;background:#102a39;border:1px solid #396071;border-radius:7px;padding:8px}button{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--aqua);outline-offset:2px}.warn{margin:14px 0;padding:12px 14px;border:1px solid #8e6b35;background:#322816;color:#ffe7b6;border-radius:10px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}.card,.panel{background:linear-gradient(145deg,#112b39,#0c1a25);border:1px solid var(--edge);border-radius:12px;padding:13px;min-width:0}.label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}.big{font-size:26px;font-weight:750;margin-top:3px;overflow-wrap:anywhere}.layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(290px,.8fr);gap:12px}.maphead{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.mapbox{position:relative;height:min(65vh,640px);min-height:340px;border:1px solid var(--edge);border-radius:10px;overflow:hidden;background:#0a1720}.mapbox #map{position:absolute;inset:0}.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.timeline{margin-top:12px;display:grid;grid-template-columns:auto minmax(100px,1fr) auto;gap:9px;align-items:center}.timeline input{width:100%;padding:0;accent-color:var(--aqua)}.timeline small{font-variant-numeric:tabular-nums;color:var(--muted)}.metriclist{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}.metricitem{padding:10px;background:#091721;border:1px solid var(--edge);border-radius:8px;min-width:0}.metricitem strong{display:block;margin-top:4px;overflow-wrap:anywhere}.chart{width:100%;height:170px;display:block}.chart text{fill:var(--muted);font-size:10px}.product-list{display:grid;gap:6px;max-height:250px;overflow:auto}.product-row{width:100%;display:flex;justify-content:space-between;align-items:center;text-align:left;gap:9px;background:#091721}.product-row[aria-current=true]{border-color:var(--aqua);background:#153746}.product-row span{display:block}.product-row small{display:block;color:var(--muted)}details{margin-top:10px;border-top:1px solid var(--edge);padding-top:10px}summary{cursor:pointer}.foot{margin-top:15px;font-size:11px;color:var(--muted)}.legend{font-size:11px;color:var(--muted);margin:7px 0}.legendbar{height:8px;border-radius:4px;background:linear-gradient(90deg,#053061,#f7f7f7,#67001f);margin-top:5px}.hidden{display:none!important}.compare-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px}.compare-mapbox{height:300px;min-height:250px;border:1px solid var(--edge);border-radius:10px;overflow:hidden}.compare-mapbox>div{height:100%;width:100%}.compare-controls{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}.compare-controls label{display:grid;gap:5px;flex:1;min-width:160px}.compare-map-title{font-size:12px;overflow-wrap:anywhere;margin:8px 0}.scenario-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.scenario-grid label{display:grid;gap:5px}.scenario-result{padding:10px;border:1px solid var(--edge);border-radius:8px;margin-top:10px}.scenario-result strong{color:var(--aqua)}@media(max-width:850px){main{padding:12px}.layout{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.mapbox{height:48vh;min-height:300px}.compare-grid{grid-template-columns:1fr}.compare-mapbox{height:280px}.scenario-grid{grid-template-columns:1fr}}@media(max-width:450px){.cards{grid-template-columns:1fr 1fr}.big{font-size:21px}.timeline{grid-template-columns:1fr}.timeline input{grid-row:2}}
.quick-panel{margin:14px 0;padding:16px;background:linear-gradient(145deg,#102a38,#0b1923);border:1px solid var(--edge);border-radius:12px}.quick-panel h2{font-size:20px;margin:4px 0 12px}.story-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.story-card{padding:12px;background:#091721;border:1px solid var(--edge);border-radius:9px}.story-card strong{display:block;font-size:22px;margin-bottom:3px}.story-card span{display:block;color:var(--muted);font-size:12px}.plain-note{padding:11px 13px;margin:9px 0;background:#102331;border-left:3px solid var(--aqua);border-radius:6px;color:var(--ink);font-size:13px}.candidate-section{margin-top:16px;padding-top:12px;border-top:1px solid var(--edge)}.candidate-section h3{font-size:16px;margin:5px 0}.candidate-section details{margin-top:8px}@media(max-width:850px){.story-grid{grid-template-columns:1fr}}@media(max-width:450px){.quick-panel{padding:11px}.story-card strong{font-size:19px}}
:root{
  color-scheme:dark;
  --bg:#07141b;--surface:#0d2029;--surface-2:#112b36;--surface-3:#173642;
  --line:#294752;--line-soft:rgba(156,190,191,.16);
  --ink:#edf5f2;--muted:#9bb2b5;--teal:#83dfcc;--teal-deep:#286f69;
  --amber:#e9bb75;--coral:#e98c7c;--radius:18px;
  --shadow:0 22px 58px rgba(0,0,0,.24);
}
html{scroll-behavior:smooth}
body{
  min-width:320px;margin:0;color:var(--ink);
  background:
    radial-gradient(ellipse at 14% -8%,rgba(41,105,111,.25),transparent 36rem),
    radial-gradient(ellipse at 92% 8%,rgba(60,91,79,.14),transparent 34rem),
    var(--bg);
  font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  letter-spacing:.005em;
}
main{width:min(100% - 56px,1680px);max-width:1680px;margin:0 auto;padding:34px 0 48px}
button,select,input{font:inherit}
button,select{
  color:var(--ink);background:#102630;border:1px solid #385762;border-radius:10px;
  min-height:40px;padding:8px 12px;transition:border-color .18s,background .18s,transform .18s;
}
button{cursor:pointer}
button:hover,select:hover{border-color:var(--teal);background:#183742}
button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible,a:focus-visible{
  outline:2px solid var(--teal);outline-offset:3px
}
a{color:var(--teal)}
label{display:grid;gap:6px;color:#bdd0cf;font-size:12px;font-weight:650}
input[type=range]{accent-color:var(--teal);width:100%;min-width:100px}
.site-header{
  display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:end;
  border-bottom:1px solid var(--line);padding:0 0 24px;margin-bottom:18px
}
.brand-rail{grid-column:1/-1;display:flex;align-items:center;gap:11px;min-height:28px}
.brand-mark{width:22px;height:22px;border:1px solid var(--teal);border-radius:7px;position:relative;display:inline-block;transform:rotate(45deg)}
.brand-mark:before,.brand-mark:after{content:"";position:absolute;background:var(--teal);border-radius:2px}
.brand-mark:before{width:6px;height:6px;left:7px;top:7px}
.brand-mark:after{width:1px;height:13px;left:10px;top:4px;opacity:.6}
.brand-name{font-size:12px;letter-spacing:.16em;text-transform:uppercase;font-weight:850}
.brand-note{color:var(--muted);font-size:11px;margin-left:4px}
.dataset-tag{margin-left:auto;border:1px solid var(--line);padding:5px 9px;border-radius:999px;color:#b6cbca;font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.hero-copy{max-width:920px}
.hero-copy .kicker{margin-bottom:8px}
.site-header h1{font-size:clamp(32px,4.4vw,58px);line-height:1.02;letter-spacing:-.052em;margin:0 0 12px;max-width:900px}
.hero-subtitle{max-width:760px;margin:0;color:#aec2c2;font-size:clamp(14px,1.35vw,17px)}
.header-actions{display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-wrap:wrap}
#presentation{background:var(--teal);border-color:var(--teal);color:#06211f;font-weight:800;padding:10px 16px}
#presentation:hover{background:#a4ebd9}
.header-link{font-size:13px;text-decoration:none;padding:9px 10px;border:1px solid var(--line);border-radius:10px;color:#c6d7d5}
.view-switcher-wrap{
  display:grid;grid-template-columns:minmax(190px,.65fr) minmax(0,2.35fr);
  gap:12px 24px;align-items:center;padding:13px 0 17px;margin-bottom:14px;
  border-bottom:1px solid var(--line-soft)
}
.view-switcher-label strong{display:block;font-size:15px;margin-top:3px}
.view-switcher{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.view-option{
  display:flex;gap:11px;align-items:center;text-align:left;padding:11px 13px;
  min-height:68px;background:rgba(14,34,43,.72);border:1px solid var(--line);
  border-radius:12px;color:var(--ink)
}
.view-option .view-number{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
.view-option strong{display:block;font-size:13px;letter-spacing:.005em}
.view-option small{display:block;margin-top:2px;color:var(--muted);font-size:11px;font-weight:500}
.view-option[aria-selected=true]{border-color:var(--teal);background:linear-gradient(125deg,rgba(48,117,109,.3),rgba(17,44,54,.92));box-shadow:inset 0 0 0 1px rgba(131,223,204,.12)}
.view-option[aria-selected=true] .view-number{color:var(--teal)}
#modeCaption{grid-column:2;margin:0;color:var(--muted);font-size:12px}
.kicker{color:var(--teal);font-size:10px;font-weight:850;letter-spacing:.17em;text-transform:uppercase}
.muted{color:var(--muted)}
.warn{
  display:flex;gap:10px;align-items:flex-start;padding:13px 16px;margin:17px 0 14px;
  background:rgba(113,80,40,.14);border:1px solid rgba(233,187,117,.3);
  border-left:3px solid var(--amber);border-radius:11px;color:#e6d9c6;font-size:13px
}
.warn strong{color:#f5cc91;white-space:nowrap}
.quick-panel{
  margin:14px 0;padding:21px 23px;background:linear-gradient(120deg,rgba(19,49,60,.96),rgba(12,31,40,.96));
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)
}
.quick-panel h2{font-size:clamp(20px,2.4vw,27px);line-height:1.15;letter-spacing:-.025em;margin:5px 0 16px}
.story-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.story-card{
  padding:15px 16px;min-height:93px;background:rgba(5,20,27,.42);
  border:1px solid var(--line-soft);border-radius:13px
}
.story-card strong{display:block;font-size:clamp(22px,2vw,29px);font-weight:760;line-height:1.12;letter-spacing:-.035em;margin-bottom:5px;font-variant-numeric:tabular-nums}
.story-card span{display:block;color:var(--muted);font-size:12px;line-height:1.45}
.plain-note{padding:12px 15px;margin:11px 0 0;background:rgba(16,45,53,.82);border-left:3px solid var(--teal);border-radius:8px;color:#dcebe7;font-size:13px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:15px 0 18px}
.card{
  padding:15px 17px;min-height:106px;background:var(--surface);border:1px solid var(--line);
  border-radius:14px;box-shadow:0 8px 22px rgba(0,0,0,.12)
}
.card .label,.metricitem .label{color:var(--muted);font-size:11px;font-weight:650;letter-spacing:.035em}
.card .big{display:block;font-size:clamp(25px,2.2vw,34px);font-weight:780;line-height:1.1;margin:8px 0 4px;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.card small{color:var(--muted);font-size:11px}
.layout{display:grid;grid-template-columns:minmax(0,1.72fr) minmax(330px,.78fr);gap:15px;align-items:start}
.panel{
  min-width:0;background:linear-gradient(165deg,rgba(16,39,49,.98),rgba(10,27,35,.98));
  border:1px solid var(--line);border-radius:var(--radius);padding:17px;box-shadow:var(--shadow)
}
.maphead{display:grid;grid-template-columns:minmax(170px,.8fr) minmax(0,1.6fr);gap:14px;align-items:start;margin-bottom:13px}
.maphead strong{display:block;font-size:17px;margin-top:4px;line-height:1.25}
.controls{display:flex;gap:8px;align-items:end;flex-wrap:wrap}
.maphead .controls{display:grid;grid-template-columns:repeat(2,minmax(130px,1fr));gap:9px}
.maphead .controls label{min-width:0}
.maphead .controls select{width:100%;max-width:100%;font-size:12px}
.mapbox{height:clamp(430px,55vh,720px);position:relative;overflow:hidden;border:1px solid #355461;border-radius:14px;background:#081820}
#map{position:absolute;inset:0;width:100%;height:100%;min-height:0}
.maplibregl-ctrl-group{border:1px solid #6b848a!important;box-shadow:0 3px 12px rgba(0,0,0,.3)!important}
.maplibregl-ctrl-group button{background:#f4f6f3!important}
.maplibregl-ctrl-attrib{font-size:10px!important}
.legend{min-height:28px;margin:9px 0;color:#bfd0cd;font-size:11px}
.timeline{display:grid;grid-template-columns:auto minmax(90px,1fr) minmax(110px,auto);gap:12px;align-items:center;margin-top:7px;padding:12px;background:#091c24;border:1px solid var(--line-soft);border-radius:12px}
.timeline .controls{flex-wrap:nowrap}
.timeline button{min-width:43px;padding:7px 10px;font-weight:750}
.timeline input{width:100%;accent-color:var(--teal)}
.timeline small{color:#c3d6d3;font-size:11px;text-align:right;font-variant-numeric:tabular-nums}
#timelineNote{font-size:11px;margin:9px 2px 13px}
details{margin:10px 0;border:1px solid var(--line-soft);border-radius:11px;background:rgba(4,19,26,.28);overflow:hidden}
details>summary{cursor:pointer;padding:12px 14px;color:#d8e7e3;font-size:12px;font-weight:720;list-style-position:inside}
details>summary:hover{background:rgba(131,223,204,.06)}
details[open]>summary{border-bottom:1px solid var(--line-soft);color:var(--teal)}
details>*:not(summary){margin-left:13px;margin-right:13px}
details>p{line-height:1.5}
.compare-controls{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:13px}
.compare-controls select{width:100%}
.compare-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px}
.compare-map-title{font-size:14px;margin:3px 0 8px}
.compare-mapbox{height:260px;position:relative;overflow:hidden;border:1px solid var(--line);border-radius:10px;background:#081820}
.compare-mapbox>div{position:absolute;inset:0}
.scenario-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:13px}
.scenario-grid input{width:100%;padding:9px;background:#0b2029;border:1px solid #385762;border-radius:9px;color:var(--ink)}
.scenario-result{padding:10px 0}
.chart{display:block;width:100%;min-height:170px;height:auto;max-height:290px;margin:10px 0}
.evidence-panel h2{font-size:clamp(21px,2vw,26px);letter-spacing:-.025em;margin:5px 0 8px}
#productDescription{font-size:12px}
.metriclist{display:grid;gap:8px;margin:10px 0}
.metricitem{
  padding:11px 12px;background:rgba(6,22,29,.55);border:1px solid var(--line-soft);
  border-radius:10px;overflow-wrap:anywhere
}
.metricitem strong{display:block;font-size:15px;margin:4px 0 2px;font-weight:760}
.metricitem small{display:block;font-size:11px;color:var(--muted);line-height:1.45}
.metricitem .label{display:block}
.evidence-panel>label{margin:14px 0}
.evidence-panel select{width:100%;max-width:100%}
.product-list{display:grid;gap:6px;padding:10px 0}
.product-list>*{padding:9px 10px;background:rgba(7,24,31,.65);border:1px solid var(--line-soft);border-radius:8px}
.candidate-section{margin:17px 0 0;padding:16px 0 0;border-top:1px solid var(--line)}
.candidate-section h3{font-size:17px;line-height:1.25;letter-spacing:-.02em;margin:5px 0 7px}
.candidate-section>p{font-size:12px;line-height:1.5}
.candidate-section .metricitem{background:rgba(7,24,31,.7)}
.candidate-section details{margin:8px 0}
.foot{margin-top:20px;padding:15px 2px;border-top:1px solid var(--line);color:#8da6aa;font-size:11px;line-height:1.6}
.hidden{display:none!important}
body[data-dashboard-mode=public] .evidence-only,
body[data-dashboard-mode=public] .science-only{display:none!important}
body[data-dashboard-mode=evidence] .science-only{display:none!important}
body[data-dashboard-mode=science] .public-only{display:none!important}
body[data-dashboard-mode=public] .layout{grid-template-columns:minmax(0,1.25fr) minmax(340px,.95fr)}
body[data-dashboard-mode=public] .map-panel{padding:20px}
body[data-dashboard-mode=public] .mapbox{height:clamp(460px,62vh,760px)}
body[data-dashboard-mode=evidence] .layout{grid-template-columns:minmax(0,1.55fr) minmax(320px,.75fr)}
body[data-dashboard-mode=science] .layout{grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr)}
body[data-dashboard-mode=science] .mapbox{height:clamp(350px,42vh,540px)}
body.presentation-active main{width:min(100% - 36px,1800px);padding-top:18px}
body.presentation-active .site-header{padding-bottom:15px;margin-bottom:10px}
body.presentation-active .view-switcher-wrap{padding:9px 0 12px}
body.presentation-active .mapbox{height:min(66vh,760px)}
body.presentation-active[data-dashboard-mode=science] .mapbox{height:min(48vh,550px)}
body.presentation-active .quick-panel{padding:15px 18px;margin:10px 0}
body.presentation-active .story-card{min-height:76px;padding:10px 13px}
body.presentation-active .story-card strong{font-size:22px}
@media(max-width:1120px){
  main{width:min(100% - 36px,1680px)}
  .layout,body[data-dashboard-mode=public] .layout,body[data-dashboard-mode=evidence] .layout,body[data-dashboard-mode=science] .layout{grid-template-columns:minmax(0,1fr)}
  .evidence-panel{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}
  .evidence-panel>.kicker,.evidence-panel>h2,.evidence-panel>#productDescription,.evidence-panel>#productMetrics,.evidence-panel>label,.evidence-panel>.candidate-section,.evidence-panel>.science-only,.evidence-panel>.evidence-only{grid-column:1/-1}
  .maphead{grid-template-columns:1fr}
  .maphead .controls{grid-template-columns:repeat(3,minmax(120px,1fr))}
}
@media(max-width:760px){
  main{width:min(100% - 24px,1680px);padding-top:18px}
  .site-header{grid-template-columns:1fr;gap:14px}
  .brand-rail{grid-column:1}
  .site-header h1{font-size:clamp(31px,9vw,44px)}
  .header-actions{justify-content:flex-start}
  .view-switcher-wrap{grid-template-columns:1fr;gap:10px}
  .view-switcher{grid-template-columns:1fr;gap:6px}
  .view-option{min-height:54px;padding:8px 11px}
  #modeCaption{grid-column:1}
  .warn{display:block}
  .warn strong{display:block;margin-bottom:4px}
  .cards{grid-template-columns:repeat(2,minmax(0,1fr))}
  .card{min-height:92px;padding:12px}
  .quick-panel{padding:16px}
  .story-grid{grid-template-columns:1fr 1fr}
  .maphead .controls{grid-template-columns:repeat(2,minmax(0,1fr))}
  .mapbox{height:clamp(370px,58vh,620px)}
  .timeline{grid-template-columns:1fr;gap:9px}
  .timeline .controls{justify-content:space-between}
  .timeline small{text-align:left}
  .evidence-panel{display:block}
  .compare-controls,.compare-grid{grid-template-columns:1fr}
  .compare-mapbox{height:235px}
  .scenario-grid{grid-template-columns:1fr}
}
@media(max-width:430px){
  .dataset-tag{font-size:9px}
  .brand-note{display:none}
  .cards{gap:7px}
  .card .big{font-size:23px}
  .story-grid{grid-template-columns:1fr}
  .story-card{min-height:0}
  .maphead .controls{grid-template-columns:1fr 1fr}
  .panel{padding:12px}
  .mapbox{height:390px}
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{scroll-behavior:auto!important;transition:none!important;animation:none!important}
}


body[data-dashboard-mode=public] .advanced-controls{display:none!important}
body[data-dashboard-mode=evidence] .public-only,
body[data-dashboard-mode=science] .public-only{display:none!important}
.public-playback{margin:14px 0 16px;padding:18px 20px}
.public-playback-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap}
.public-playback h2{font-size:clamp(19px,2vw,24px);margin:4px 0 6px}
.public-family-switch{display:flex;gap:8px;flex-wrap:wrap}
.public-family-button{min-width:150px;text-align:left;padding:10px 13px;border:1px solid var(--line);border-radius:11px;background:rgba(5,20,27,.62)}
.public-family-button[aria-pressed=true]{border-color:var(--teal);background:rgba(39,101,96,.28);box-shadow:inset 0 0 0 1px rgba(131,223,204,.14)}
.public-family-button strong{display:block;font-size:15px}
.public-family-button small{display:block;color:var(--muted);font-size:11px;margin-top:3px}
.public-family-button:disabled{opacity:.45;cursor:not-allowed}
.public-playback-controls{display:grid;grid-template-columns:auto minmax(120px,1fr) auto;gap:10px;align-items:center;margin-top:14px}
.public-playback-actions{display:flex;gap:7px;align-items:center}
.public-playback-actions button{min-width:42px}
.public-playback-actions #publicPlay{min-width:110px;background:#1d5c55;border-color:#438a7c}
.public-pair-date{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;text-align:right}
#publicTimeline{width:100%;accent-color:var(--teal);padding:0}
.public-playback-note{font-size:12px;line-height:1.55;color:var(--muted);margin:10px 0 0}
.public-map-tools{display:flex;gap:10px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
.public-map-tools strong{font-size:12px}
.public-map-tools button{font-size:11px}
.public-map-legend{margin:9px 0 12px;padding:11px 13px;border:1px solid var(--line-soft);border-radius:10px;background:rgba(5,20,27,.5);font-size:12px;line-height:1.5}
.public-map-legend strong{display:block;margin-bottom:5px}
.public-ramp{height:10px;border-radius:8px;margin:7px 0;background:linear-gradient(90deg,#053061 0%,#f7f7f7 50%,#67001f 100%)}
.public-ramp-labels{display:flex;justify-content:space-between;gap:12px;color:var(--muted);font-size:10px}
.public-map-key{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;color:var(--muted);font-size:10px}
.public-map-key span{display:flex;align-items:center;gap:6px}
.public-key-swatch{width:11px;height:11px;border-radius:3px;display:inline-block}
.public-key-aoi{background:#66e2d3}
.public-key-candidate{background:#e9ad45}
.public-candidate-results{margin-top:16px;padding-top:14px;border-top:1px solid var(--line)}
.public-candidate-results-title{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
.public-candidate-results-title strong{font-size:15px}
.public-candidate-results-title span,.public-candidate-footnote{font-size:11px;line-height:1.5;color:var(--muted)}
.public-candidate-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.public-candidate-card{min-width:0;padding:12px;border:1px solid var(--line);border-radius:12px;background:rgba(5,19,26,.68);display:flex;flex-direction:column;gap:6px}
.public-candidate-head{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.public-candidate-head strong{display:block;font-size:12px;overflow-wrap:anywhere}
.public-candidate-track{font-size:10px;color:var(--muted);white-space:nowrap}
.public-candidate-location{font-size:13px;font-weight:650;letter-spacing:.01em}
.public-candidate-stats{display:flex;flex-wrap:wrap;gap:5px 10px;font-size:10px;color:var(--muted)}
.public-candidate-card>small{font-size:10px;line-height:1.4;color:var(--muted)}
.candidate-focus{align-self:flex-start;margin-top:3px;padding:7px 10px;border:1px solid var(--edge);border-radius:7px;background:rgba(102,226,211,.08);color:var(--text);font-size:11px;cursor:pointer}
.candidate-focus:hover{border-color:var(--accent);background:rgba(102,226,211,.16)}
.candidate-focus:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:760px){.public-candidate-list{grid-template-columns:minmax(0,1fr)}.evidence-panel{grid-template-columns:minmax(0,1fr)}}
.public-explainer-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 16px}
.public-explainer-card{min-width:0;padding:14px 15px;background:linear-gradient(145deg,rgba(17,48,59,.88),rgba(8,27,36,.92));border:1px solid var(--line);border-radius:13px}
.public-explainer-card .explainer-tag{display:inline-block;margin-bottom:7px;color:var(--teal);font-size:10px;font-weight:850;letter-spacing:.09em;text-transform:uppercase}
.public-explainer-card strong{display:block;margin-bottom:5px;font-size:14px;line-height:1.3}
.public-explainer-card p{margin:0;color:#b8cbca;font-size:12px;line-height:1.55}
.run-finding-number{font-variant-numeric:tabular-nums}
@media(max-width:760px){.public-explainer-grid{grid-template-columns:1fr}.public-playback-controls{grid-template-columns:1fr;gap:9px}.public-pair-date{text-align:left}.public-playback-actions{justify-content:flex-start}}
@media(max-width:430px){.public-family-switch{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.public-family-button{min-width:0;padding:9px}.public-playback-actions button{min-width:44px}}
</style></head><body><main>
<header class="site-header">
<div class="brand-rail"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">SARGuardian</span><span class="brand-note">Earth in sight · NISAR research results</span><span class="dataset-tag">AOI observation report</span></div>
<div class="hero-copy"><div class="kicker">Evidence before interpretation</div><h1>What did NISAR observe in this area?</h1><p class="hero-subtitle">See where the satellite found unusual patterns, what could be measured, and what still needs checking—without needing to know the target location first.</p></div>
<div class="header-actions"><button id="presentation" type="button" aria-pressed="false">Enter presentation</button><a class="header-link" href="../index.html">Processing report <span aria-hidden="true">↗</span></a></div>
</header>
<section class="view-switcher-wrap" aria-label="Choose dashboard audience view">
<div class="view-switcher-label"><div class="kicker">Choose your view</div><strong>One evidence set. Three levels of detail.</strong></div>
<div class="view-switcher" role="group" aria-label="Dashboard audience view">
<button type="button" class="view-option" data-sg-mode="public" aria-selected="true" aria-pressed="true"><span class="view-number">01</span><span><strong>Public Discovery</strong><small>What was observed in this area</small></span></button>
<button type="button" class="view-option" data-sg-mode="evidence" aria-selected="false" aria-pressed="false"><span class="view-number">02</span><span><strong>Explore the Evidence</strong><small>Maps, pairs and candidate patterns</small></span></button>
<button type="button" class="view-option" data-sg-mode="science" aria-selected="false" aria-pressed="false"><span class="view-number">03</span><span><strong>Scientific Evidence</strong><small>Measurements, gates and provenance</small></span></button>
</div>
<p id="modeCaption">A plain-language overview of the AOI, observation coverage and candidate evidence.</p>
</section>
<div class="warn"><strong>Important:</strong> a highlighted area is a place to investigate, not a confirmed landslide or glacier movement. The satellite records radar patterns; the results below explain which patterns were measured and which remain uncertain.</div>
<section class="quick-panel" aria-labelledby="runStoryTitle"><div class="kicker">Your area · at a glance</div><h2 id="runStoryTitle">What did the satellite data show?</h2><div id="runStory" class="story-grid"></div><p id="runWindowNote" class="muted"></p><p id="runPlainConclusion" class="plain-note" role="status"></p><p id="targetFreeNote" class="plain-note"></p></section>
<section class="public-explainer-grid public-only" aria-label="How to understand the results">
<article class="public-explainer-card"><span class="explainer-tag">GUNW · Measurement</span><strong>Distance change along the radar view</strong><p>Measures how the ground shifts toward or away from the satellite between two observation dates. It is not a full 3D movement measurement.</p></article>
<article class="public-explainer-card"><span class="explainer-tag">GOFF · Image pattern</span><strong>Places where radar images do not line up as expected</strong><p>An offset pattern can be a useful clue, but it is not by itself a measurement of ground movement.</p></article>
<article class="public-explainer-card"><span class="explainer-tag">Candidate · Review lead</span><strong>A place worth checking—not an alert</strong><p>Repeated patterns deserve attention, but need independent checks before anyone calls them real movement or a hazard.</p></article>
</section>
<section id="publicPlayback" class="panel public-only public-playback" aria-labelledby="publicPlaybackTitle">
<div class="public-playback-head">
  <div><div class="kicker">Satellite observations</div><h2 id="publicPlaybackTitle">Choose what to watch</h2><p class="muted" style="font-size:12px;margin:0">Play one satellite data type at a time. GUNW and GOFF always run in separate sequences.</p></div>
  <div class="public-family-switch" role="group" aria-label="Choose one satellite data family">
    <button type="button" id="publicFamilyGUNW" class="public-family-button" data-public-family="GUNW" aria-pressed="false"><strong>GUNW · LOS displacement</strong><small id="gunwPairCount">0 observation pairs</small></button>
    <button type="button" id="publicFamilyGOFF" class="public-family-button" data-public-family="GOFF" aria-pressed="true"><strong>GOFF · Image-offset clues</strong><small id="goffPairCount">0 observation pairs</small></button>
  </div>
</div>
<div class="public-playback-controls">
  <div class="public-playback-actions"><button type="button" id="publicPrevious" aria-label="Previous pair">◀</button><button type="button" id="publicPlay">Play GUNW</button><button type="button" id="publicNext" aria-label="Next pair">▶</button></div>
  <input id="publicTimeline" type="range" min="0" max="0" value="0" step="1" aria-label="Selected family observation timeline">
  <strong id="publicDateLabel" class="public-pair-date">—</strong>
</div>
<p id="publicPlaybackNote" class="public-playback-note" role="status">GUNW playback: only GUNW pairs, in acquisition-date order. The map shows the selected pair's line-of-sight measurement between two acquisition dates.</p>
</section>
<div class="cards public-only" id="summaryCards"></div>
<div class="layout" id="dashboardLayout"><section class="panel map-panel"><div class="maphead"><div><div class="kicker">Explore the selected area</div><strong id="mapTitle">Loading map layers…</strong></div><div class="controls advanced-controls"><label>Product family <select id="advancedFamilySelect" aria-label="Filter observations by product family"><option value="GUNW">GUNW only</option><option value="GOFF">GOFF only</option></select></label><label>Observed pair band <select id="bandSelect" aria-label="Select raster band"></select></label><label>Scientific layer <select id="derivedLayerSelect" aria-label="Select a derived scientific raster layer"><option value="">Observed pair playback</option></select></label><label>Candidate overlay <select id="candidateOverlaySelect" aria-label="Choose which candidate regions to show on the map"><option value="none">Hide candidate regions</option><option value="legacy">GOFF repeated-region screen</option><option value="extended-goff">GOFF offset-anomaly patterns</option><option value="extended-gunw">GUNW pairwise LOS anomalies</option><option value="extended">All extended anomaly records</option></select></label><label>Opacity <input id="opacity" type="range" min="0" max="100" value="80" aria-label="Raster opacity"></label><label>Speed <select id="speed"><option value="2500">0.5×</option><option value="1500" selected>1×</option><option value="750">2×</option></select></label></div><div class="public-map-tools public-only"><strong id="publicMapTitle">GUNW line-of-sight measurement map</strong><button type="button" id="publicCandidateToggle" aria-pressed="true">Hide review areas</button></div></div><div class="mapbox"><div id="map"></div><div id="mapFallback" class="hidden" style="padding:20px"><strong>Interactive map unavailable.</strong><p>The processing report and georeferenced assets remain in this bundle; the basemap/MapLibre library requires an internet connection.</p></div></div><div id="publicLegend" class="public-map-legend public-only" role="status"></div><div id="legend" class="legend advanced-controls"></div><div class="timeline advanced-controls"><div class="controls"><button id="previous" aria-label="Previous observation">◀</button><button id="play">Play</button><button id="next" aria-label="Next observation">▶</button></div><input id="timeline" type="range" min="0" max="0" value="0" step="1" aria-label="Observation pair timeline"><small id="dateLabel">—</small></div><p class="muted advanced-controls" id="timelineNote">Each point is a real acquisition pair. No synthetic intermediate observations are created.</p>
<details id="pairCompare" class="evidence-only"><summary>Side-by-side observed pair comparison</summary><p class="muted" style="font-size:11px">Compares two actual pairwise raster previews only when both source products have the same product family, track/look and exact source grid. This is not optical before/after imagery, not a computed difference, and not a cumulative trajectory.</p><div class="compare-controls"><label>Observed pair A<select id="compareA"></select></label><label>Observed pair B<select id="compareB"></select></label><label>Shared raster band<select id="compareBand"></select></label></div><p class="muted" id="compareStatus" role="status">Select two compatible observations to compare.</p><div class="compare-grid"><div><h3 id="compareTitleA" class="compare-map-title">Pair A</h3><div class="compare-mapbox"><div id="compareMapA"></div></div><p id="compareLegendA" class="legend"></p></div><div><h3 id="compareTitleB" class="compare-map-title">Pair B</h3><div class="compare-mapbox"><div id="compareMapB"></div></div><p id="compareLegendB" class="legend"></p></div></div></details>
<details id="scenarioSandbox" class="science-only"><summary>Hypothetical motion sensitivity sandbox (not a forecast)</summary><p class="muted" style="font-size:11px">Enter a hypothetical constant rate and duration to draw a scenario curve. It is generated by the calculator, not NISAR observations, not a landslide/glacier-collapse prediction, and must never be read as an alert. Any displayed noise floor comes only from a measured pair-local floor in this run.</p><div class="scenario-grid"><label>Hypothetical rate (mm/day)<input id="scenarioRate" type="number" min="-500" max="500" step="0.1" placeholder="Enter rate"></label><label>Duration (days)<input id="scenarioDays" type="number" min="1" max="90" step="1" placeholder="Enter duration"></label><div style="display:flex;align-items:end"><button id="simulateScenario" type="button">Simulate scenario</button></div></div><svg id="scenarioChart" class="chart" role="img" aria-label="Explicitly hypothetical cumulative displacement scenario" viewBox="0 0 560 180"></svg><div id="scenarioResult" class="scenario-result muted" role="status">No scenario generated.</div></details>
</section>
<aside class="panel evidence-panel">
<div class="kicker">Selected satellite observation</div><h2 id="publicProductTitle" class="public-only">Selected observation</h2><h2 id="productTitle" class="evidence-only">—</h2><p class="muted" id="productDescription">The selected observation pair and its measurement summary.</p><div class="metriclist" id="productMetrics"></div>
<details class="science-only"><summary>Technical measurements and source metadata</summary><div class="metriclist" id="productTechnicalMetrics"></div></details>
<label class="advanced-controls">Jump to an image pair <select id="productSelect"></select></label>
<details class="evidence-only"><summary>How much usable data each pair contains</summary><svg id="supportChart" class="chart" role="img" aria-label="Usable pixel support by acquisition pair"></svg><p class="muted" style="font-size:11px">Pixel counts are per product. One map cell may appear in several pairs, so these bars are not unique ground area or a movement trend.</p></details>
<details class="science-only"><summary>Pair measurements (technical view)</summary><label>Measurement <select id="measurementMetric" aria-label="Select one measurement and its units"></select></label><label>Satellite track <select id="measurementTrack" aria-label="Choose a satellite track"></select></label><svg id="measurementChart" class="chart" role="img" aria-label="Pairwise measurement statistics, not a cumulative time series"></svg><p class="muted" style="font-size:11px">GUNW LOS and GOFF offsets are different measurement families. Bars are separate acquisition pairs, not a connected cumulative trajectory. bars are not connected into a cumulative trend. detection floors are noise bounds, not observed motion.</p></details>
<details class="science-only"><summary>Why no cumulative network result was produced</summary><div class="kicker">GUNW common-reference diagnostic</div><label>Network <select id="cumulativeNetwork" aria-label="Select eligible common-reference network"></select></label><div id="cumulativeStatus" class="muted" role="status">Checking eligibility…</div><svg id="cumulativeChart" class="chart" role="img" aria-label="Cumulative LOS diagnostic using actual acquisition epochs"></svg><div class="kicker" style="margin-top:14px">GOFF common-reference diagnostic</div><label>Network / component <select id="goffCumulativeNetwork" aria-label="Select GOFF common-reference network and offset component"></select></label><div id="goffCumulativeStatus" class="muted" role="status">Checking eligibility…</div><svg id="goffCumulativeChart" class="chart" role="img" aria-label="Cumulative GOFF offset diagnostic using actual acquisition epochs"></svg><p class="muted" style="font-size:11px">A withheld chart means the observations did not meet the network and reference checks. It does not mean zero movement. Any shown series is an AOI-relative research diagnostic, not an independently surveyed stable-ground measurement.</p></details>
<section class="candidate-section"><div class="kicker">Find Displacements · whole-area scan</div><h3>Where did the screen find unusual SAR patterns?</h3><p class="muted" style="font-size:12px">The two screens below use different methods. Their counts are not added together, and neither is confirmation of ground movement.</p><div id="publicCandidateResults" class="public-only"></div><div id="aoiCandidateStatus" class="muted evidence-only" role="status"></div><div id="aoiCandidateList" class="metriclist evidence-only"></div><details class="evidence-only"><summary id="legacyCandidateSummary">Inspect GOFF repeated-region candidates</summary><div id="aoiLegacyCandidateList" class="metriclist"></div></details><details class="evidence-only"><summary id="extendedCandidateSummary">Inspect extended candidate records</summary><div id="aoiExtendedCandidateList" class="metriclist"></div></details></section>
<section class="candidate-section"><div class="kicker">GUNW · target-free LOS analysis</div><h3>Could a reliable multi-date LOS map be calculated?</h3><div id="pixelTimeseriesSummary" class="plain-note" role="status">Checking the available observations…</div><details class="science-only"><summary>Show the technical network checks</summary><div id="pixelTimeseriesStatus" class="muted" role="status"></div><div id="pixelTimeseriesNetworks" class="metriclist"></div></details><p class="muted" style="font-size:11px">This analysis does not need a target point. It is withheld when pairs do not make a connected, sufficiently overlapping and redundant time series. The background is an AOI-derived background, not independently surveyed stable ground.</p></section>
<section class="candidate-section evidence-only"><div class="kicker">GUNW · exploratory per-pixel screen</div><h3>How much complete pixel evidence was available?</h3><div id="pixelStackSummary" class="plain-note" role="status">Checking the saved GUNW screen log…</div><details class="science-only"><summary>Show support by track chain</summary><div id="pixelStackChains" class="metriclist"></div><p class="muted" style="font-size:11px">These counts refer to cells with a complete connected series across the pairs in that chain. They are not independent ground samples. Very sparse support cannot represent the whole AOI.</p></details></section>
<details class="science-only"><summary>Technical stage-by-stage processing status</summary><div id="scienceStages" class="metriclist"></div><p class="muted" style="font-size:11px">Technical module names and gates are preserved here for scientific audit.</p></details>
<details class="evidence-only"><summary>Browse all processed image pairs</summary><div class="product-list" id="productList"></div></details><details class="science-only"><summary>Run provenance and scientific limitations</summary><div id="provenance" class="muted" style="font-size:11px;overflow-wrap:anywhere"></div></details>
</aside></div>
<footer class="foot">Map data attribution: © OpenStreetMap contributors. Raster preview is reprojected from the validated clipped GeoTIFF; native raster and per-product records remain the scientific source assets. This is a research viewer, not a hazard-alert service.</footer>
</main><script src="./dashboard-data.js"></script><script type="module">
import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.mjs';
(function(){const $=id=>document.getElementById(id);const manifest=window.SARGUARDIAN_DASHBOARD;let M=null,selected=0,activeFamily='GUNW',playing=false,timer=null,activeLayer=null;const esc=s=>String(s==null?'—':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));if(!manifest){$('mapTitle').textContent='Manifest is missing';$('mapFallback').classList.remove('hidden');return}const obs=manifest.observations||[],layers=manifest.layers||[],aoi=manifest.aoi&&manifest.aoi.geometry,n=obs.length;
function familyIndices(family=activeFamily){return obs.map((p,i)=>({p,i})).filter(x=>x.p.product_type===family).sort((a,b)=>String(a.p.secondary_date||'').localeCompare(String(b.p.secondary_date||''))||a.i-b.i).map(x=>x.i);}
function familyPosition(){const indices=familyIndices(),position=indices.indexOf(selected);return position>=0?position:0;}
function hasRenderableFamily(family){return familyIndices(family).some(index=>layers.some(layer=>layer.observation_id===obs[index].id));}
function firstRenderableIndex(family){const indices=familyIndices(family);return indices.find(index=>layers.some(layer=>layer.observation_id===obs[index].id))??indices[0]??0;}
function syncFamilyControls(){
 const indices=familyIndices(),position=familyPosition(),count=indices.length,gunwCount=familyIndices('GUNW').length,goffCount=familyIndices('GOFF').length;
 const gunwButton=$('publicFamilyGUNW'),goffButton=$('publicFamilyGOFF');
 if(gunwButton){gunwButton.setAttribute('aria-pressed',String(activeFamily==='GUNW'));gunwButton.disabled=!gunwCount;}
 if(goffButton){goffButton.setAttribute('aria-pressed',String(activeFamily==='GOFF'));goffButton.disabled=!goffCount;}
 if($('gunwPairCount'))$('gunwPairCount').textContent=gunwCount+' observation pair(s)';
 if($('goffPairCount'))$('goffPairCount').textContent=goffCount+' observation pair(s)';
 if($('advancedFamilySelect'))$('advancedFamilySelect').value=activeFamily;
 if($('productSelect')){$('productSelect').innerHTML=indices.map((globalIndex,pos)=>{const p=obs[globalIndex];return '<option value="'+pos+'">'+esc(p.secondary_date)+' · '+esc(p.id)+'</option>';}).join('');$('productSelect').value=String(position);}
 ['timeline','publicTimeline'].forEach(id=>{const slider=$(id);if(slider){slider.max=String(Math.max(0,count-1));slider.value=String(position);slider.disabled=count<2;}});
 ['previous','next','publicPrevious','publicNext'].forEach(id=>{const button=$(id);if(button)button.disabled=count<2;});
 if($('publicPlay'))$('publicPlay').disabled=count<2;
 if($('play'))$('play').disabled=count<2;
}
if(hasRenderableFamily('GUNW'))activeFamily='GUNW';else if(hasRenderableFamily('GOFF'))activeFamily='GOFF';else if(familyIndices('GUNW').length)activeFamily='GUNW';else activeFamily='GOFF';
if(familyIndices().length)selected=firstRenderableIndex(activeFamily);
syncFamilyControls();
const site=(manifest.site_context||{}),place=site.place||{},target=site.measurement_target||{},aoiWideScreen=manifest.aoi_wide_displacement_screen||{},candidateReport=manifest.aoi_displacement_candidates||{};
const usableProducts=obs.filter(p=>Number(p.valid_pixels||0)>0).length,noPixelProducts=n-usableProducts,legacyCount=Number(aoiWideScreen.candidate_count||((aoiWideScreen.candidate_feature_collection||{}).features||[]).length||0),extendedFeatures=Array.isArray(candidateReport.features)?candidateReport.features:[],repeatedCount=extendedFeatures.filter(f=>(f.properties||{}).status==='REPEATED_SPATIAL_CANDIDATE').length,singleCount=extendedFeatures.filter(f=>(f.properties||{}).status==='SINGLE_PAIR_CANDIDATE_UNCONFIRMED').length;
const pixelTsReport=manifest.aoi_relative_pixel_timeseries||{};const losSeriesAvailable=pixelTsReport.status==='AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE';
const gunwCandidateFeatures=extendedFeatures.filter(f=>(f.properties||{}).product_type==='GUNW');
const goffCandidateFeatures=extendedFeatures.filter(f=>(f.properties||{}).product_type==='GOFF');
const gunwRepeatedFeatures=gunwCandidateFeatures.filter(f=>(f.properties||{}).status==='REPEATED_SPATIAL_CANDIDATE').length;
const gunwSingleFeatures=gunwCandidateFeatures.filter(f=>(f.properties||{}).status==='SINGLE_PAIR_CANDIDATE_UNCONFIRMED').length;
const story=[
 ['Observation pairs checked',n,obs.filter(p=>p.product_type==='GUNW').length+' GUNW displacement pairs · '+obs.filter(p=>p.product_type==='GOFF').length+' GOFF image-offset pairs'],
 ['GUNW pattern records',gunwCandidateFeatures.length,gunwRepeatedFeatures+' repeated across pair records · '+gunwSingleFeatures+' single-pair clues'],
 ['GOFF offset review regions',legacyCount,'Radar-image patterns flagged for review; not measured ground movement'],
 ['Can we measure change over time?',losSeriesAvailable?'Diagnostic available':'Not measurable',losSeriesAvailable?'Relative radar-view measurement; stable ground is not independently verified':'The GUNW observations did not meet the connected, overlapping and repeatable network checks']
];
$('runStory').innerHTML=story.map(x=>'<div class="story-card"><strong class="run-finding-number">'+esc(x[1])+'</strong><span><b>'+esc(x[0])+'</b><br>'+esc(x[2])+'</span></div>').join('');
const plainConclusion=$('runPlainConclusion');
if(plainConclusion){
 const findings=[];
 if(gunwCandidateFeatures.length)findings.push(gunwCandidateFeatures.length+' GUNW pattern record(s) for review');
 if(legacyCount)findings.push(legacyCount+' GOFF image-offset review region(s)');
 plainConclusion.textContent=findings.length
  ? 'The whole-area scan found '+findings.join(' and ')+'. These are results from separate screening methods; do not add the counts together or read them as confirmed landslides, glacier movement or hazard detections. '+(losSeriesAvailable?'A multi-date GUNW LOS diagnostic is available, but its background reference has not been independently verified.':'A reliable multi-date GUNW LOS rate could not be calculated from this observation network.')
  : 'No area crossed the configured candidate-screening thresholds in this run. That does not prove there was no movement; review the observation coverage and the limits of the available data.';
}
const tw=manifest.time_window||{};
$('runWindowNote').textContent='Satellite observation window: '+(tw.start_date||'—')+' to '+(tw.end_date||'—')+'. Playback shows real acquisition pairs only; no missing dates are filled in.';
$('targetFreeNote').textContent='The entire selected polygon was screened—no target point was needed. A highlighted area is a review lead, not a confirmed event or an automatic warning.';
const cards=[['Satellite pairs',n],['GUNW pairs',familyIndices('GUNW').length],['GOFF pairs',familyIndices('GOFF').length],['Pairs with usable pixels',usableProducts+' / '+n]];
$('summaryCards').innerHTML=cards.map(x=>'<div class="card"><div class="label">'+esc(x[0])+'</div><div class="big">'+esc(x[1])+'</div></div>').join('');
$('candidateOverlaySelect').value=publicDefaultCandidateMode(activeFamily);
$('candidateOverlaySelect').disabled=!legacyCount&&!extendedFeatures.length;
function addFallback(){ $('mapFallback').classList.remove('hidden'); }
function applyCandidateOverlay(){if(!M)return;const mode=$('candidateOverlaySelect')?$('candidateOverlaySelect').value:'none';const extendedVisible=mode==='extended'||mode==='extended-goff'||mode==='extended-gunw';['aoi-candidate-fill','aoi-candidate-outline'].forEach(function(id){if(M.getLayer(id)){M.setLayoutProperty(id,'visibility',extendedVisible?'visible':'none');const filter=mode==='extended-goff'?['==',['get','product_type'],'GOFF']:mode==='extended-gunw'?['==',['get','product_type'],'GUNW']:['all'];M.setFilter(id,filter);}});[['aoi-wide-candidate-fill','legacy'],['aoi-wide-candidate-outline','legacy']].forEach(function(item){if(M.getLayer(item[0]))M.setLayoutProperty(item[0],'visibility',mode===item[1]?'visible':'none');});}
if(maplibregl && typeof maplibregl.Map==='function'){try{M=new maplibregl.Map({container:'map',style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}},layers:[{id:'osm',type:'raster',source:'osm'}]},center:[0,0],zoom:2});M.addControl(new maplibregl.NavigationControl(),'top-right');M.on('load',function(){if(aoi){M.addSource('aoi',{type:'geojson',data:manifest.aoi});M.addLayer({id:'aoi-fill',type:'fill',source:'aoi',paint:{'fill-color':'#66e2d3','fill-opacity':0.09}});M.addLayer({id:'aoi-outline',type:'line',source:'aoi',paint:{'line-color':'#66e2d3','line-width':2,'line-dasharray':[2,1]}});const candidateReport=manifest.aoi_displacement_candidates||{};const candidateFeatures=Array.isArray(candidateReport.features)?candidateReport.features:[];if(candidateFeatures.length&&!M.getSource('aoi-candidate-regions')){M.addSource('aoi-candidate-regions',{type:'geojson',data:{type:'FeatureCollection',features:candidateFeatures}});M.addLayer({id:'aoi-candidate-fill',type:'fill',source:'aoi-candidate-regions',layout:{visibility:'none'},paint:{'fill-color':'#e9ad45','fill-opacity':0.22}});M.addLayer({id:'aoi-candidate-outline',type:'line',source:'aoi-candidate-regions',layout:{visibility:'none'},paint:{'line-color':'#e9ad45','line-width':2}});M.on('click','aoi-candidate-fill',function(e){const p=(e.features&&e.features[0]&&e.features[0].properties)||{};new maplibregl.Popup().setLngLat(e.lngLat).setHTML('<strong>'+esc(p.product_type==='GUNW'?'GUNW pairwise LOS anomaly':p.metric==='GOFF_SLANT_RANGE_OFFSET_MM'?'GOFF slant-range offset anomaly':'GOFF along-track offset anomaly')+'</strong><br>'+esc(p.status||'UNCONFIRMED')+'<br>Pair support: '+esc(p.support_pairs||0)+' (not a cumulative series)<br>Pixels: '+esc(p.pixel_count||0)+'<br>Exploratory score: '+esc(p.max_robust_score||0)+' (not probability)<br>Image-space anomaly only; not confirmed ground movement or hazard.').addTo(M);});}const legacyFC=aoiWideScreen.candidate_feature_collection||{type:'FeatureCollection',features:[]};if(Array.isArray(legacyFC.features)&&legacyFC.features.length&&!M.getSource('legacy-aoi-wide-candidates')){M.addSource('legacy-aoi-wide-candidates',{type:'geojson',data:legacyFC});M.addLayer({id:'aoi-wide-candidate-fill',type:'fill',source:'legacy-aoi-wide-candidates',layout:{visibility:'none'},filter:['==',['geometry-type'],'Polygon'],paint:{'fill-color':'#e9ad45','fill-opacity':0.16}});M.addLayer({id:'aoi-wide-candidate-outline',type:'line',source:'legacy-aoi-wide-candidates',layout:{visibility:'none'},filter:['==',['geometry-type'],'Polygon'],paint:{'line-color':'#e9ad45','line-width':2}});M.on('click','aoi-wide-candidate-fill',function(e){const p=(e.features&&e.features[0]&&e.features[0].properties)||{};new maplibregl.Popup().setLngLat(e.lngLat).setHTML('<strong>'+esc(p.candidate_id||'GOFF candidate')+'</strong><br>'+esc(p.direction||'')+' T'+esc(p.track||'—')+'<br>'+esc(p.area_km2_approx||'—')+' km²<br>'+esc(p.pairs_with_candidate||0)+' supporting pair(s)<br>GOFF offset anomaly only; not ground motion; not a hazard detection.').addTo(M);});}const coords=aoi.coordinates[0]||[];if(coords.length){let west=Infinity,south=Infinity,east=-Infinity,north=-Infinity;coords.forEach(c=>{west=Math.min(west,c[0]);south=Math.min(south,c[1]);east=Math.max(east,c[0]);north=Math.max(north,c[1]);});M.fitBounds([[west,south],[east,north]],{padding:55,maxZoom:14});}}if(place&&Number.isFinite(Number(place.longitude))&&Number.isFinite(Number(place.latitude))){M.addSource('selected-site',{type:'geojson',data:{type:'Feature',properties:{name:place.name||'Selected place'},geometry:{type:'Point',coordinates:[Number(place.longitude),Number(place.latitude)]}}});M.addLayer({id:'selected-site-marker',type:'circle',source:'selected-site',paint:{'circle-radius':8,'circle-color':'#f7c76b','circle-stroke-color':'#ffffff','circle-stroke-width':2}});}if(target.status==='IN_AOI_TARGET_CAPTURED'&&Number.isFinite(Number(target.longitude))&&Number.isFinite(Number(target.latitude))){M.addSource('selected-target',{type:'geojson',data:{type:'Feature',properties:{name:'Measurement target'},geometry:{type:'Point',coordinates:[Number(target.longitude),Number(target.latitude)]}}});M.addLayer({id:'selected-target-marker',type:'circle',source:'selected-target',paint:{'circle-radius':4,'circle-color':'#ff806e','circle-stroke-color':'#ffffff','circle-stroke-width':1.5}});}layers.forEach(function(l){const source='src-'+l.id;M.addSource(source,{type:'image',url:(window.SARGUARDIAN_LAYER_DATA||{})[l.id]||l.preview_asset,coordinates:l.corners});M.addLayer({id:'raster-'+l.id,type:'raster',source:source,layout:{visibility:'none'},paint:{'raster-opacity':Number($('opacity').value)/100,'raster-resampling':'nearest'}});});(manifest.derived_layers||[]).forEach(function(l){const source='src-derived-'+l.id;M.addSource(source,{type:'image',url:(window.SARGUARDIAN_DERIVED_LAYER_DATA||{})[l.id]||l.preview_asset,coordinates:l.corners});M.addLayer({id:'raster-derived-'+l.id,type:'raster',source:source,layout:{visibility:'none'},paint:{'raster-opacity':Number($('opacity').value)/100,'raster-resampling':'nearest'}});});applyCandidateOverlay();if(M.getLayer('aoi-candidate-fill'))M.moveLayer('aoi-candidate-fill');if(M.getLayer('aoi-candidate-outline'))M.moveLayer('aoi-candidate-outline');if(n)renderProduct();});}catch(e){addFallback();}}else addFallback();
function current(){return obs[selected]||null;}function obsLayers(p){return layers.filter(l=>l.observation_id===p.id);}function hideLayers(){if(!M)return;layers.forEach(l=>{const id='raster-'+l.id;if(M.getLayer(id))M.setLayoutProperty(id,'visibility','none');});(manifest.derived_layers||[]).forEach(l=>{const id='raster-derived-'+l.id;if(M.getLayer(id))M.setLayoutProperty(id,'visibility','none');});activeLayer=null;}
function renderLegend(l){if(!l){$('legend').textContent='No renderable raster overlay for this product.';return;}const d=l.display_scale||{};const ramp=l.kind==='coherence'?'linear-gradient(90deg,#440154,#21918c,#fde725)':'linear-gradient(90deg,#053061,#f7f7f7,#67001f)';const safeRamp=l.kind==='binary_mask'?'linear-gradient(90deg,#ff6e5f 0%,#37be9b 100%)':l.kind==='candidate_mask'?'linear-gradient(90deg,transparent 0%,#ff6e5f 100%)':l.kind==='reference_mask'?'linear-gradient(90deg,transparent 0%,#37be9b 100%)':ramp;$('legend').innerHTML='<strong>'+esc(l.description)+'</strong> · '+esc(l.units)+' · preview-valid pixels '+esc(l.valid_pixels)+'<br>Scale '+esc(d.min)+' to '+esc(d.max)+' '+esc(l.units)+' ('+esc(d.method)+')<div class="legendbar" style="background:'+safeRamp+'"></div>';}
function renderPublicLegend(l){
 const root=$('publicLegend');if(!root)return;
 if(!l){root.innerHTML='<strong>No raster measurement can be displayed for this pair.</strong><span>A blank map area does not mean zero movement; valid measurement data may be unavailable there.</span>';return;}
 const d=l.display_scale||{},minimum=Number(d.min),maximum=Number(d.max),units=l.units||'source units';
 const family=String((current()||{}).product_type||activeFamily);
  const measurement=family==='GUNW'?'GUNW · Pairwise line-of-sight (LOS) displacement':'GOFF · Slant-range radar-image pixel offset';
  const directionNote=family==='GUNW'?'Blue and red show negative and positive values under this product’s LOS sign convention. They do not, by themselves, tell you vertical, east–west, or 3-D movement.':'Blue and red show negative and positive pixel offsets along the slant-range image axis. This is image-coordinate information, not a direct compass direction or ground-motion direction.';
  const caution=family==='GUNW'?'This is a measurement between these two dates along the radar viewing direction—not a 3-D, vertical, east–west, or cumulative displacement.':'This is an offset between radar-image pixels, not a direct measurement of ground movement, landslide motion, or glacier motion.';
  root.innerHTML='<strong>What do the map colours mean?</strong><div>'+esc(measurement)+' · '+esc(units)+'</div><div class="public-ramp" aria-hidden="true"></div><div class="public-ramp-labels"><span>Blue: negative (−)</span><span>White: near zero</span><span>Red: positive (+)</span></div><div class="public-map-key"><span>Displayed range: '+(Number.isFinite(minimum)?minimum.toFixed(2):'—')+' to '+(Number.isFinite(maximum)?maximum.toFixed(2):'—')+' '+esc(units)+'</span><span><i class="public-key-swatch public-key-candidate"></i>Amber outline: area flagged for review</span><span><i class="public-key-swatch public-key-aoi"></i>Cyan outline: selected AOI</span></div><div style="margin-top:6px">'+esc(directionNote)+'</div><div style="margin-top:6px">'+esc(caution)+'</div><small class="muted"><strong>Colour is not a hazard score:</strong> red does not mean danger and blue does not mean safe. The displayed range belongs to this selected layer; another layer may use a different range. Transparent pixels mean no usable measurement or a masked pixel; they do not mean no change.</small>';
}
function publicDefaultCandidateMode(family=activeFamily){
 if(family==='GOFF')return legacyCount?'legacy':(extendedFeatures.some(f=>(f.properties||{}).product_type==='GOFF')?'extended-goff':'none');
 return extendedFeatures.some(f=>(f.properties||{}).product_type==='GUNW')?'extended-gunw':'none';
}
function updatePublicCandidateToggle(){
 const button=$('publicCandidateToggle'),select=$('candidateOverlaySelect');if(!button||!select)return;
 const visible=select.value!=='none';button.textContent=visible?'Hide review areas':'Show review areas';button.setAttribute('aria-pressed',String(visible));button.disabled=publicDefaultCandidateMode(activeFamily)==='none';
}
function syncPublicCandidateOverlay(){
 const select=$('candidateOverlaySelect');if(!select)return;
 select.value=publicDefaultCandidateMode(activeFamily);applyCandidateOverlay();updatePublicCandidateToggle();
 const title=$('publicMapTitle');if(title)title.textContent=activeFamily==='GUNW'?'GUNW · pairwise LOS measurement map':'GOFF · Radar image offset map';
}
function renderDerivedLayer(){
 const select=$('derivedLayerSelect'),id=select?select.value:'',derived=manifest.derived_layers||[];
 if(!id){if(n)renderProduct();return;}
 const layer=derived.find(item=>item.id===id);if(!layer||!M)return;
 hideLayers();const mapLayer='raster-derived-'+layer.id;
 if(M.getLayer(mapLayer)){M.setLayoutProperty(mapLayer,'visibility','visible');M.setPaintProperty(mapLayer,'raster-opacity',Number($('opacity').value)/100);activeLayer='derived-'+layer.id;}
 $('mapTitle').textContent='AOI-wide analysis · '+layer.description;
 renderLegend(layer);
}

function renderPixelStackDiagnostic(){
 const report=manifest.pixel_stack_diagnostic||{},summary=$('pixelStackSummary'),root=$('pixelStackChains');
 if(!summary||!root)return;
 if(report.status==='WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK'){
  summary.textContent=String(report.interpretation||'The GUNW pairs do not form a compatible repeated measurement network. This is NOT TESTABLE, not NO DETECTION.');
  root.innerHTML='<div class="metricitem"><div class="label">AOI-wide GUNW per-pixel time series</div><strong>No compatible multi-date GUNW network</strong><small style="display:block;margin-top:4px">'+esc(report.pairs_examined??'—')+' pairs · '+esc(report.exact_networks??'—')+' separate networks · '+esc(report.networks_with_2_plus_pairs??'—')+' networks with 2+ consecutive compatible pairs</small><small style="display:block;margin-top:4px">NOT TESTABLE, not NO DETECTION. Different subswaths or processing CRIDs must not be joined into one time series.</small></div>';
  return;
 }
 if(!report.available||!Array.isArray(report.chains)||!report.chains.length){
  summary.textContent='The detailed exploratory GUNW pixel-stack log was not retained in this bundle. No support or movement conclusion is inferred from this missing report.';
  root.innerHTML='<div class="metricitem"><strong>Pixel support not reported</strong><small>Missing diagnostics are not zero movement.</small></div>';
  return;
 }
 const chains=report.chains;
 const countable=chains.filter(c=>Number(c.complete_pixels)>0);
 const notTestable=countable.filter(c=>c.finding==='NOT_TESTABLE_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT').length;
 const noComplete=chains.filter(c=>c.finding==='NO_COMPLETE_SERIES').length;
 const noCluster=countable.filter(c=>c.finding==='NO_CLUSTER_ABOVE_NOISE_SCREEN').length;
 summary.textContent=String(report.interpretation||'The exploratory GUNW per-pixel screen has limited support.')+' It checked '+String(report.pairs_examined==null?'an unreported number of':report.pairs_examined)+' GUNW acquisition pairs across '+chains.length+' geometry chains. '+notTestable+' chain(s) could not estimate spatial background noise because too few nearby pixels were valid; '+noComplete+' chain(s) had no complete pixel series. The noise comparison was withheld where it could not be tested.';
 root.innerHTML=chains.map(c=>{
  const complete=Number(c.complete_pixels||0),total=Number(c.total_pixels||0),pct=Number(c.complete_support_pct||0);
  const support=total>0?complete.toLocaleString()+' / '+total.toLocaleString()+' complete pixels ('+pct.toFixed(4)+'%)':'Complete pixel support not reported';
  const verdict=c.finding==='NO_COMPLETE_SERIES'?'No complete series — nothing to fit':c.finding==='NOT_TESTABLE_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT'?'Not testable — too few nearby valid pixels to measure background noise':c.finding==='NO_CLUSTER_ABOVE_NOISE_SCREEN'?'No connected cluster passed this screen’s noise check':'Review required — see saved log';
  const noise=c.noise_cluster_p95_pixels==null?'': ' · noise-only 95th-percentile cluster '+Number(c.noise_cluster_p95_pixels).toLocaleString()+' px';
  return '<div class="metricitem"><div class="label">'+esc(c.geometry)+' · '+esc(c.pair_count)+' pairs · '+esc(c.duration_days)+' days</div><strong>'+esc(support)+'</strong><small style="display:block;margin-top:4px">'+esc(verdict)+' · largest cluster '+esc(c.largest_cluster_pixels==null?'not reported':Number(c.largest_cluster_pixels).toLocaleString()+' px')+esc(noise)+'</small></div>';
 }).join('');
 const sensitivity=report.common_mode_sensitivity||{};
 if(sensitivity.same_complete_pixel_support){
  summary.textContent+=' The common-mode-retained sensitivity pass had the same complete-pixel counts.';
 }
 if(sensitivity.atmospheric_common_mode_warning){
  summary.textContent+=' The retained-common-mode log warns that atmospheric/orbit effects can dominate; it is a sensitivity check, not a preferred truth.';
 }
}

function renderAOIPixelTimeseriesStatus(){
 const r=manifest.aoi_relative_pixel_timeseries||{},summary=$('pixelTimeseriesSummary'),status=$('pixelTimeseriesStatus'),root=$('pixelTimeseriesNetworks'),select=$('derivedLayerSelect');
 if(!status||!root||!select)return;
 const velocityLayers=(manifest.derived_layers||[]).filter(layer=>String(layer.analysis_role||'').toLowerCase().includes('velocity'));
 const networks=Array.isArray(r.networks)?r.networks:[];
 const withheld=String(r.status||'').includes('WITHHELD')||!velocityLayers.length;
 summary.textContent=withheld?'No reliable multi-date GUNW LOS map was produced in this run. The pairs did not provide enough connected, overlapping and repeatable observations on a compatible grid. This is a data-support limitation—not evidence that the ground did not move.':velocityLayers.length+' AOI-relative LOS layer(s) are available. They show relative radar motion only; the background reference has not been independently checked as stable ground.';
 status.textContent=String(r.status||'NOT_REPORTED')+' · '+String(r.reason||'No AOI-wide per-pixel report is available.');
 const old=select.value;select.innerHTML='<option value="">Observed pair playback</option>'+(manifest.derived_layers||[]).map(layer=>'<option value="'+esc(layer.id)+'">'+esc(layer.description)+' · '+esc(layer.network)+'</option>').join('');select.disabled=!(manifest.derived_layers||[]).length;if(old&&(manifest.derived_layers||[]).some(layer=>layer.id===old))select.value=old;
 if(!networks.length){root.innerHTML='<div class="metricitem"><strong>No eligible GUNW network assessed</strong><small>No multi-date velocity was inferred.</small></div>';return;}
 root.innerHTML=networks.map(network=>'<div class="metricitem"><div class="label">'+esc(network.network||'GUNW network')+'</div><strong>'+esc(network.status||'NOT_REPORTED')+'</strong><small style="display:block;margin-top:4px">'+esc(network.pair_count||0)+' pair(s) · '+esc(network.epoch_count||0)+' acquisition dates · redundancy '+esc(network.redundancy||0)+' · common pixels '+esc(network.common_valid_pixels||0)+'</small><small style="display:block;margin-top:4px">'+esc(network.reason||'See the processing report for gate details.')+'</small></div>').join('');
 if(velocityLayers.length)status.textContent+=' · '+velocityLayers.length+' velocity layer(s) available; diagnostic only, reference unvalidated.';
}

function renderProduct(){
 const p=current();if(!p){$('mapTitle').textContent='No observations available for this data family';renderPublicLegend(null);return;}syncFamilyControls();const derivedSelect=$('derivedLayerSelect');if(derivedSelect)derivedSelect.value='';
 const position=familyPosition(),pl=obsLayers(p);$('timeline').value=String(position);$('productSelect').value=String(position);$('publicTimeline').value=String(position);$('publicDateLabel').textContent=(p.reference_date||'—')+' → '+(p.secondary_date||'—');$('dateLabel').textContent=(p.reference_date||'—')+' → '+(p.secondary_date||'—');$('mapTitle').textContent=p.product_type==='GUNW'?'GUNW · Radar line-of-sight measurement':'GOFF · Radar image offset';$('publicProductTitle').textContent=p.product_type==='GUNW'?'Radar viewing-direction measurement':'Radar image offset';$('productTitle').textContent=p.id+' · '+p.product_type;$('productDescription').textContent=(p.reference_date||'—')+' → '+(p.secondary_date||'—')+' · selected observation pair';
 const priorBand=$('bandSelect').value;$('bandSelect').innerHTML=pl.map(l=>'<option value="'+esc(l.id)+'">Band '+esc(l.band)+': '+esc(l.description)+'</option>').join('');if(pl.some(l=>l.id===priorBand))$('bandSelect').value=priorBand;$('bandSelect').disabled=!pl.length;const layer=pl.find(l=>l.id===$('bandSelect').value)||pl[0]||null;hideLayers();if(layer&&M&&M.getLayer('raster-'+layer.id)){M.setLayoutProperty('raster-'+layer.id,'visibility','visible');M.setPaintProperty('raster-'+layer.id,'raster-opacity',Number($('opacity').value)/100);activeLayer=layer.id;}renderLegend(layer);renderPublicLegend(layer);
 $('publicPlaybackNote').textContent=(p.product_type==='GUNW'?'GUNW playback: only GUNW pairs are shown, in acquisition-date order. The map is the selected pair’s LOS displacement preview.':'GOFF playback: only GOFF pairs are shown, in acquisition-date order. The map is the selected pair’s slant-range offset preview; it is an image-space offset, not measured ground movement.');
 $('publicPlay').textContent=playing?'Pause':'Play '+activeFamily;
 const m=p.metrics||{},coverage=Number.isFinite(Number(p.aoi_coverage_pct))?Number(p.aoi_coverage_pct):null,coverageText=coverage===null?'Coverage not reported':coverage.toFixed(2)+'% of AOI pixels';
 const supportNote=p.support_level==='NO_USABLE_PIXELS'?'No valid raster pixels survived the product quality masks.':p.support_level==='VERY_LOW_COVERAGE'?'Very little of the AOI has usable pixels (<1%); do not interpret the median as an AOI-wide movement value.':p.support_level==='LOW_COVERAGE'?'Limited AOI pixel coverage (<10%); inspect the map and quality before interpreting the pair statistic.':'Coverage describes valid data support only; it does not prove geophysical accuracy.';
 const metricLabel=p.product_type==='GUNW'?'Radar viewing-direction reading':(p.product_type==='GOFF'?'Radar image offset reading':'Observation reading');let readerDisplay=m.reader_median==null?'Not reported':String(m.reader_median)+' '+(m.reader_median_units||'source units');
 if(p.support_level==='NO_USABLE_PIXELS')readerDisplay='No usable pixels — no median to interpret';else if(p.support_level==='VERY_LOW_COVERAGE')readerDisplay='Not interpreted — only '+(coverage===null?'very few pixels':coverage.toFixed(2)+'%')+' AOI coverage';
 const targetMeasured=m.target_measurement_status==='MEASURED',floorMeasured=m.target_local_floor_status==='MEASURED';
 const items=[['Usable pixels in this pair',(Number(p.valid_pixels||0)).toLocaleString()+' pixels'],['Share of selected area with usable data',coverageText],[metricLabel,readerDisplay],['What the coverage means',supportNote]];
 $('productMetrics').innerHTML=items.map(x=>'<div class="metricitem"><div class="label">'+esc(x[0])+'</div><strong>'+esc(x[1])+'</strong></div>').join('');
 const technicalItems=[['Reference acquisition',p.reference_date],['Secondary acquisition',p.secondary_date],['Track / look',p.track||'Not reported'],['Maturity',p.maturity],['Measurement-valid pixels',p.valid_pixels],['Screen-valid pixels',p.screen_valid_pixels==null?'Not reported':p.screen_valid_pixels],['Global-MAD outliers retained for review',p.screen_outlier_pixels==null?'Not applicable':p.screen_outlier_pixels],['Raw reader median',m.reader_median==null?'Not reported':String(m.reader_median)+' '+(m.reader_median_units||'source units')],['GOFF range offset median',m.goff_range_median_mm==null?'Not reported':m.goff_range_median_mm+' mm'],['GOFF along-track offset median',m.goff_azimuth_median_mm==null?'Not reported':m.goff_azimuth_median_mm+' mm'],['Mean coherence',m.mean_coherence==null?'Not reported':m.mean_coherence],['Mean correlation',m.mean_correlation==null?'Not reported':m.mean_correlation],['Target-local LOS / range',m.target_local_los_median_mm!=null?m.target_local_los_median_mm+' mm':m.target_local_range_median_mm!=null?m.target_local_range_median_mm+' mm':'Not measured'],['Target-local along-track',m.target_local_azimuth_median_mm==null?'Not measured':m.target_local_azimuth_median_mm+' mm'],['Target-local floor',m.target_local_floor_mm_day==null?'Not measured':m.target_local_floor_mm_day+' mm/day'],['Target floor confidence interval',m.target_local_floor_ci_lo_mm_day==null||m.target_local_floor_ci_hi_mm_day==null?'Not reported':m.target_local_floor_ci_lo_mm_day+'–'+m.target_local_floor_ci_hi_mm_day+' mm/day'],['Product CRID',p.crid],['Product workflow status',p.status],['Coverage category',p.support_level||'NOT_REPORTED']];
 $('productTechnicalMetrics').innerHTML=technicalItems.map(x=>'<div class="metricitem"><div class="label">'+esc(x[0])+'</div><strong>'+esc(x[1])+'</strong></div>').join('');
 $('provenance').innerHTML='<p>Run: '+esc(manifest.run.github_run_id)+'</p><p>AOI SHA-256: '+esc(manifest.run.aoi_wkt_sha256)+'</p><p>Science commit: '+esc(manifest.run.science_commit)+'</p><p>Orchestration commit: '+esc(manifest.run.orchestration_commit)+'</p><p>Source hash: '+esc(p.source_sha256)+'</p><p>'+esc(p.validation_scope||'Structural/provenance only; independent geophysical validation not performed.')+'</p><p>'+(p.warnings||[]).map(esc).join('<br>')+'</p>';
 renderList();
}
function renderPublicCandidateCards(family=activeFamily){
 const root=$('publicCandidateResults');if(!root)return;
 const legacy=manifest.aoi_wide_displacement_screen||{},legacyFeatures=((legacy.candidate_feature_collection||{}).features||[]);
 const features=Array.isArray(candidateReport.features)?candidateReport.features:[];
 let cards=[],heading='',description='',footnote='';
 if(family==='GOFF'){
  const seriesById=new Map((Array.isArray(legacy.series)?legacy.series:[]).map(item=>[item.series_id,item]));
  const ranked=legacyFeatures.slice().sort((a,b)=>{const x=a.properties||{},y=b.properties||{};return Number(y.pairs_with_candidate||0)-Number(x.pairs_with_candidate||0)||Number(y.mean_cross_pair_directional_coherence||0)-Number(x.mean_cross_pair_directional_coherence||0)||Number(y.area_km2_approx||0)-Number(x.area_km2_approx||0);});
  cards=ranked.slice(0,8).map((feature,index)=>{
   const p=feature.properties||{},series=seriesById.get(p.series_id)||{},pairs=Array.isArray(series.pairs)?series.pairs:[],first=pairs.length?pairs[0].reference_date:null,last=pairs.length?pairs[pairs.length-1].secondary_date:null,lon=Number(p.centroid_lon),lat=Number(p.centroid_lat),area=Number(p.area_km2_approx);
   return '<article class="public-candidate-card"><div class="public-candidate-head"><div><span class="label">GOFF review area '+String(index+1).padStart(2,'0')+'</span><strong>'+esc(p.direction||'Offset pattern')+' · '+esc(p.track||'track not reported')+'</strong></div><span class="public-candidate-track">Image offset</span></div><div class="public-candidate-location">'+(Number.isFinite(lat)&&Number.isFinite(lon)?lat.toFixed(5)+'° N, '+lon.toFixed(5)+'° E':'Location not reported')+'</div><div class="public-candidate-stats"><span>Approx. '+(Number.isFinite(area)?area.toFixed(2)+' km²':'area not reported')+'</span><span>'+esc(p.pixels_approx||'—')+' pixels</span><span>'+esc(p.pairs_with_candidate||0)+' supporting pair(s)</span></div><small>Compatible series: '+esc(first||'—')+' → '+esc(last||'—')+'</small><button type="button" class="candidate-focus" data-candidate-family="GOFF" data-candidate-lon="'+esc(Number.isFinite(lon)?lon:'')+'" data-candidate-lat="'+esc(Number.isFinite(lat)?lat:'')+'" data-candidate-name="'+esc(p.candidate_id||'GOFF review area')+'">Locate on map</button></article>';
  });
  heading='GOFF · Radar-image patterns to review';
  description='These are places where radar images show unusual offsets. They are clues for further checking—not direct measurements of ground movement.';
  footnote='The same place may appear more than once across tracks or records. Pair support shows how often a pattern appeared; it is not a probability, a movement distance or a hazard count.';
 }else{
  const ranked=features.filter(f=>(f.properties||{}).product_type==='GUNW').sort((a,b)=>{
   const x=a.properties||{},y=b.properties||{},xr=x.status==='REPEATED_SPATIAL_CANDIDATE'?1:0,yr=y.status==='REPEATED_SPATIAL_CANDIDATE'?1:0;
   return yr-xr||Number(y.support_pairs||0)-Number(x.support_pairs||0)||Number(y.pixel_count||0)-Number(x.pixel_count||0);
  });
  cards=ranked.slice(0,8).map((feature,index)=>{
   const p=feature.properties||{},geom=feature.geometry||{},coords=geom.type==='Polygon'?(geom.coordinates||[])[0]||[]:geom.type==='MultiPolygon'?((geom.coordinates||[])[0]||[])[0]||[]:[];
   let lon=Number(p.centroid_lon),lat=Number(p.centroid_lat);
   if(!Number.isFinite(lon)||!Number.isFinite(lat)){const points=coords.filter(point=>Array.isArray(point)&&Number.isFinite(Number(point[0]))&&Number.isFinite(Number(point[1])));if(points.length){lon=points.reduce((sum,point)=>sum+Number(point[0]),0)/points.length;lat=points.reduce((sum,point)=>sum+Number(point[1]),0)/points.length;}}
   const repeated=p.status==='REPEATED_SPATIAL_CANDIDATE',area=Number(p.approx_area_m2),pairRecords=Array.isArray(p.pair_intervals)?p.pair_intervals.length:Number(p.overlapping_pair_count||0);
   return '<article class="public-candidate-card"><div class="public-candidate-head"><div><span class="label">GUNW pattern record '+String(index+1).padStart(2,'0')+'</span><strong>'+(repeated?'Pattern repeated across observations':'Pattern seen in one pair')+'</strong></div><span class="public-candidate-track">'+(repeated?'Multiple records':'One record')+'</span></div><div class="public-candidate-location">Approx. map centre · '+(Number.isFinite(lat)&&Number.isFinite(lon)?lat.toFixed(5)+'° N, '+lon.toFixed(5)+'° E':'Location not reported')+'</div><div class="public-candidate-stats"><span>'+(Number.isFinite(area)?(area/1000000).toFixed(3)+' km²':'Area not reported')+'</span><span>'+esc(p.pixel_count||'—')+' pixels</span><span>'+esc(p.support_pairs||0)+' pair record(s) flagged</span></div><small>Pair records in screen: '+esc(pairRecords)+'</small><small>Pairwise LOS anomaly only; this run did not produce a connected multi-date GUNW time series.</small><button type="button" class="candidate-focus" data-candidate-family="GUNW" data-candidate-lon="'+esc(Number.isFinite(lon)?lon:'')+'" data-candidate-lat="'+esc(Number.isFinite(lat)?lat:'')+'" data-candidate-name="GUNW candidate area '+String(index+1)+'">Locate on map</button></article>';
  });
  heading='GUNW · Radar-view distance patterns to review';
  description='These areas show unusual differences in radar line-of-sight measurements relative to the surrounding AOI. A repeated pattern is a stronger reason to inspect the area, but it is not independently confirmed ground movement.';
  footnote='Several pattern records do not automatically form one connected measurement series. When the strict network test is NOT TESTABLE, no cumulative displacement or rate can be inferred. Missing measurement support does not mean zero movement.';
 }
 root.innerHTML='<div class="public-candidate-results-title"><strong>'+heading+'</strong><span>'+description+'</span></div><div class="public-candidate-list">'+(cards.join('')||'<p class="muted">No candidate areas were produced for this data family. This does not prove that the AOI had no movement; consider observation coverage and screening limits.</p>')+'</div><p class="public-candidate-footnote">'+footnote+'</p>';
 root.querySelectorAll('[data-candidate-lon][data-candidate-lat]').forEach(button=>button.addEventListener('click',()=>{
  const lon=Number(button.dataset.candidateLon),lat=Number(button.dataset.candidateLat),candidateFamily=button.dataset.candidateFamily||family;
  if(!M||!Number.isFinite(lon)||!Number.isFinite(lat)){root.setAttribute('data-status','Map unavailable or candidate coordinates not reported.');return;}
  const mode=candidateFamily==='GOFF'?(legacyCount?'legacy':'extended-goff'):'extended-gunw',selector=$('candidateOverlaySelect');
  if(selector){selector.value=mode;applyCandidateOverlay();updatePublicCandidateToggle();}
  M.flyTo({center:[lon,lat],zoom:11,duration:800});
  new maplibregl.Popup({offset:14}).setLngLat([lon,lat]).setHTML('<strong>'+esc(button.dataset.candidateName)+'</strong><br>'+(candidateFamily==='GUNW'?'GUNW pairwise LOS anomaly':'GOFF Radar-image offset pattern')+'<br>Review evidence only; not confirmed ground movement or a hazard.').addTo(M);
 }));
}
function simplifyCandidateOpenPath(points,tolerance){
 const keep=new Uint8Array(points.length);if(points.length<2)return points;keep[0]=1;keep[points.length-1]=1;
 const stack=[[0,points.length-1]],tol2=tolerance*tolerance;
 while(stack.length){const [start,end]=stack.pop();if(end<=start+1)continue;const a=points[start],b=points[end],dx=b[0]-a[0],dy=b[1]-a[1],length2=dx*dx+dy*dy;let best=-1,bestDistance=tol2;
  for(let i=start+1;i<end;i++){const p=points[i];let t=length2?((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2:0;t=Math.max(0,Math.min(1,t));const px=a[0]+t*dx,py=a[1]+t*dy,dist=(p[0]-px)**2+(p[1]-py)**2;if(dist>bestDistance){bestDistance=dist;best=i;}}
  if(best>=0){keep[best]=1;stack.push([start,best],[best,end]);}
 }
 return points.filter((_,index)=>keep[index]);
}
function simplifyCandidateClosedRing(closedRing,maxClosedVertices=500){
 const points=closedRing.slice(0,-1);if(points.length+1<=maxClosedVertices)return closedRing;
 if(points.length<4)return null;
 const origin=points[0];let pivot=1,pivotDistance=-1;
 for(let i=1;i<points.length;i++){const d=(points[i][0]-origin[0])**2+(points[i][1]-origin[1])**2;if(d>pivotDistance){pivotDistance=d;pivot=i;}}
 if(pivotDistance<=0)return null;
 const firstPath=points.slice(0,pivot+1),secondPath=[...points.slice(pivot),origin];
 let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
 for(const point of points){minX=Math.min(minX,point[0]);maxX=Math.max(maxX,point[0]);minY=Math.min(minY,point[1]);maxY=Math.max(maxY,point[1]);}
 const maxTolerance=Math.hypot(maxX-minX,maxY-minY);
 let lo=0,hi=Math.max(maxTolerance,1e-12),best=null;
 for(let iteration=0;iteration<28;iteration++){
  const tolerance=(lo+hi)/2;
  const a=simplifyCandidateOpenPath(firstPath,tolerance),b=simplifyCandidateOpenPath(secondPath,tolerance);
  const open=[...a.slice(0,-1),...b.slice(0,-1)];
  const closedVertexCount=open.length+1;
  if(closedVertexCount>maxClosedVertices){lo=tolerance;}
  else if(closedVertexCount>=4){best=[...open,open[0]];hi=tolerance;}
  else {hi=tolerance;}
 }
 return best;
}
function candidateFeatureMeasurementGeometry(feature){
 const geometry=feature&&feature.geometry;
 if(!geometry||geometry.type!=='Polygon'||!Array.isArray(geometry.coordinates)||geometry.coordinates.length!==1)return null;
 const source=geometry.coordinates[0];if(!Array.isArray(source)||source.length<4)return null;
 let ring=source.map(point=>Array.isArray(point)&&point.length>=2?[Number(point[0]),Number(point[1])]:[NaN,NaN]);
 if(ring.some(point=>!Number.isFinite(point[0])||!Number.isFinite(point[1])))return null;
 const first=ring[0],last=ring[ring.length-1];
 if(Math.abs(first[0]-last[0])>1e-10||Math.abs(first[1]-last[1])>1e-10)ring.push([...first]);
 const originalVertices=ring.length;let simplified=false;
 if(originalVertices>20000)return null;
 if(ring.length>500){ring=simplifyCandidateClosedRing(ring,500);if(!ring)return null;simplified=true;}
 if(ring.length<4||ring.length>500)return null;
 return {wkt:'POLYGON (('+ring.map(point=>point[0].toFixed(8)+' '+point[1].toFixed(8)).join(', ')+'))',simplified,originalVertices,vertices:ring.length};
}
function normalizeCandidatePairIntervals(values){
 if(!Array.isArray(values))return [];
 return values.slice(0,30).flatMap(value=>{
  if(value&&typeof value==='object'&&!Array.isArray(value)){
   const referenceDate=String(value.reference_date||value.referenceDate||'');
   const secondaryDate=String(value.secondary_date||value.secondaryDate||'');
   return referenceDate&&secondaryDate?[{reference_date:referenceDate,secondary_date:secondaryDate}]:[];
  }
  if(typeof value!=='string')return [];
  const pieces=value.split('/');
  if(pieces.length!==2)return [];
  return [{reference_date:pieces[0].slice(0,10),secondary_date:pieces[1].slice(0,10)}];
 });
}
function stableCandidateId(properties,geometryWkt){
 const source=[String(properties.network||''),String(properties.product_type||''),String(properties.metric||''),...(Array.isArray(properties.pair_intervals)?properties.pair_intervals.map(String):[]),geometryWkt].join('|');
 let hash=2166136261;
 for(let i=0;i<source.length;i++){hash^=source.charCodeAt(i);hash=Math.imul(hash,16777619);}
 return 'GOFF-CANDIDATE-'+(hash>>>0).toString(16).padStart(8,'0');
}
function transferGoffCandidate(feature){
 const p=feature&&feature.properties||{};
 if(p.product_type!=='GOFF'||!feature.geometry||feature.geometry.type!=='Polygon')return false;
 const geometry=candidateFeatureMeasurementGeometry(feature);
 if(!geometry){window.alert('This GOFF candidate boundary cannot be safely simplified into an editable polygon. Draw the measurement area manually in Known Place Analysis.');return false;}
 const transfer={
  schemaVersion:'sarguardian-known-place-candidate/1.0',
  measurementWkt:geometry.wkt,
  candidate:{
   candidateId:stableCandidateId(p,geometry.wkt),
   productType:'GOFF',metric:String(p.metric||'GOFF_OFFSET_ANOMALY').slice(0,120),
   evidenceClass:String(p.evidence_class||'GOFF_OFFSET_ANOMALY_NOT_GROUND_MOTION').slice(0,160),
   status:String(p.status||'UNCONFIRMED').slice(0,100),supportPairs:Number(p.support_pairs||0),
   pixelCount:Number(p.pixel_count||0),approximateAreaM2:Number(p.approx_area_m2||0),
   productIds:Array.isArray(p.product_ids)?p.product_ids.slice(0,30).map(String):[],
   pairIntervals:normalizeCandidatePairIntervals(p.pair_intervals),
   geometryOriginalVertices:geometry.originalVertices,geometrySuggestedVertices:geometry.vertices,
   geometrySimplified:geometry.simplified,
   interpretation:String(p.interpretation||'Offset anomaly candidate; not measured ground motion.').slice(0,500)
  }
 };
 try{window.sessionStorage.setItem('sarguardian.knownPlaceCandidate.v1',JSON.stringify(transfer));window.location.assign('/landslide/known-place-analysis?candidate=1');return true;}
 catch(error){window.alert('The candidate could not be handed to Known Place Analysis in this browser session. Please draw the measurement polygon manually.');return false;}
}
function renderAoiCandidateScreen(){
 const root=$('aoiCandidateList'),status=$('aoiCandidateStatus'),r=manifest.aoi_displacement_candidates||{},legacy=manifest.aoi_wide_displacement_screen||{};if(!root||!status)return;
 const features=Array.isArray(r.features)?r.features:[],legacyFeatures=((legacy.candidate_feature_collection||{}).features||[]),repeated=features.filter(f=>(f.properties||{}).status==='REPEATED_SPATIAL_CANDIDATE'),single=features.filter(f=>(f.properties||{}).status==='SINGLE_PAIR_CANDIDATE_UNCONFIRMED'),goffFeatures=features.filter(f=>(f.properties||{}).product_type==='GOFF'),gunwFeatures=features.filter(f=>(f.properties||{}).product_type==='GUNW'),countStatus=(rows,status)=>rows.filter(f=>(f.properties||{}).status===status).length,legacyCount=Number(legacy.candidate_count||legacyFeatures.length||0);
 const floorPolicy=r.candidate_local_floor_policy||{};
 const floorPolicyNote=' Candidate-local 3σ floor = 3 × (1.4826 × MAD) / pair span, using a '+String(floorPolicy.background_ring_pixels||5)+'-pixel background ring and at least '+String(floorPolicy.minimum_background_pixels||30)+' valid nearby pixels. Same acquisition interval counts once; nearby pixels are not proven stable ground and this is not a calibrated false-alarm probability.';
 status.textContent='Two separate screens ran. Choose which one to display on the map above. Neither screen confirms ground movement or a hazard.'+floorPolicyNote;
 root.innerHTML=[['GOFF repeated-region screen',legacyCount,'Separate GOFF-only review regions from a multi-pair screen. Regions can overlap between tracks; they are not confirmed movement or unique hazard sites.'],['Extended repeated feature records',repeated.length,'Same-pixel patterns repeated in more than one compatible pair within a metric/network group. Still only screening evidence.'],['Extended single-pair records',single.length,'Only one pair supports each record. Treat as an unconfirmed review lead.'],['GOFF offset-anomaly records',goffFeatures.length,countStatus(goffFeatures,'REPEATED_SPATIAL_CANDIDATE')+' repeated · '+countStatus(goffFeatures,'SINGLE_PAIR_CANDIDATE_UNCONFIRMED')+' single-pair. Range and along-track offsets are separate image-offset components, not ground displacement.'],['GUNW pairwise LOS anomaly records',gunwFeatures.length,countStatus(gunwFeatures,'REPEATED_SPATIAL_CANDIDATE')+' repeated · '+countStatus(gunwFeatures,'SINGLE_PAIR_CANDIDATE_UNCONFIRMED')+' single-pair. These are pairwise LOS spatial contrasts, not a cumulative time series.']].map(x=>'<div class="metricitem"><div class="label">'+esc(x[0])+'</div><strong>'+esc(x[1])+'</strong><small style="display:block;margin-top:4px">'+esc(x[2])+'</small></div>').join('')+'<div class="plain-note">There are '+esc(legacyCount)+' GOFF-only review regions and '+esc(features.length)+' extended feature records. The extended records include '+esc(goffFeatures.length)+' GOFF offsets and '+esc(gunwFeatures.length)+' pairwise GUNW LOS anomalies. These counts are not added together, are not unique locations, and do not mean '+esc(features.length)+' landslides or glacier-motion detections. A robust score is not a probability.</div>';
 renderPublicCandidateCards(activeFamily);
 $('legacyCandidateSummary').textContent='See up to 30 of '+legacyCount+' GOFF-only regions';$('extendedCandidateSummary').textContent='See up to 30 of '+features.length+' extended metric records';
 const legacyRoot=$('aoiLegacyCandidateList'),extendedRoot=$('aoiExtendedCandidateList');
 if(legacyRoot)legacyRoot.innerHTML=legacyFeatures.slice(0,30).map(f=>{const p=f.properties||{};return '<div class="metricitem"><div class="label">GOFF offset anomaly · '+esc(p.candidate_id||'Candidate')+'</div><strong>'+esc(p.direction||'')+' track '+esc(p.track||'—')+'</strong><small>Approx. area '+esc(p.area_km2_approx||'—')+' km² · supporting pairs '+esc(p.pairs_with_candidate||0)+'</small><small>Exploratory offset screen only; not ground displacement.</small></div>';}).join('')||'<p class="muted">No GOFF-only region records were produced.</p>';
  const extendedCandidates=[...repeated.slice(0,20),...single.slice(0,10)];
  if(extendedRoot)extendedRoot.innerHTML=extendedCandidates.map((f,index)=>{const p=f.properties||{};const metricLabel=p.metric==='GUNW_LOS_DISPLACEMENT_MM'?'GUNW pairwise LOS anomaly':p.metric==='GOFF_SLANT_RANGE_OFFSET_MM'?'GOFF slant-range offset anomaly':'GOFF along-track offset anomaly';const floors=Array.isArray(p.candidate_local_floor_by_pair)?p.candidate_local_floor_by_pair.filter(x=>x.status==='MEASURED_CANDIDATE_REGION_LOCAL_FLOOR'):[];const floorText=floors.length?floors.map(x=>x.reference_date+'→'+x.secondary_date+': '+Number(x.local_detection_floor_3sigma_mm_day).toFixed(2)+' mm/day').join(' · '):'Local floor withheld: insufficient nearby valid background pixels';const season=p.candidate_seasonality_inventory||{};const seasonText='Season coverage: '+Number(season.dry_season_pairs||0)+' dry · '+Number(season.monsoon_pairs||0)+' monsoon pair(s) — '+String(season.status||'NOT_REPORTED')+' (descriptive only)';const phase=p.candidate_phase_ceiling_review||{};const phaseText='GUNW λ/4 review: '+String(phase.status||'NOT_REPORTED')+' · '+(phase.threshold_mm==null?'—':Number(phase.threshold_mm).toFixed(1)+' mm');const measureButton=p.product_type==='GOFF'?(f.geometry&&f.geometry.type==='Polygon'&&Array.isArray(f.geometry.coordinates)&&f.geometry.coordinates.length===1?'<button type="button" class="candidate-focus candidate-measure" data-measure-candidate-index="'+index+'">Use as suggested measurement area</button>':'<small>GOFF candidate has multiple polygon components or interior rings. Draw the measurement polygon manually; unsupported geometry is not auto-converted.</small>'):'<small>GUNW LOS candidates require a separate LOS measurement workflow; not passed to GOFF analysis.</small>';return '<div class="metricitem"><div class="label">'+esc(metricLabel)+'</div><strong>'+esc(p.status||'UNCONFIRMED')+'</strong><small>Pair support '+esc(p.support_pairs||0)+' · pixel count '+esc(p.pixel_count||0)+' · approximate area '+esc(p.approx_area_m2||0)+' m² · exploratory score '+esc(p.max_robust_score||0)+' (not probability)</small><small>Candidate-local 3σ floor: '+esc(floorText)+'</small><small>'+esc(seasonText)+'</small><small>'+esc(phaseText)+'</small><small>Cross-geometry: '+esc(p.candidate_cross_geometry_status||'NOT_REPORTED')+'</small><small>'+esc(p.interpretation||'Candidate only; not validated movement.')+'</small>'+measureButton+'</div>';}).join('')||'<p class="muted">No extended feature records were produced.</p>';
  if(extendedRoot)extendedRoot.querySelectorAll('[data-measure-candidate-index]').forEach(button=>button.addEventListener('click',()=>{const feature=extendedCandidates[Number(button.dataset.measureCandidateIndex)];if(feature)transferGoffCandidate(feature);}));
}
function renderSciencePipeline(){const root=$('scienceStages'),r=manifest.science_pipeline||{};const modules=Array.isArray(r.modules)?r.modules:[];const networks=Array.isArray(r.networks)?r.networks:[];if(!modules.length){root.innerHTML='<div class="metricitem"><div class="label">Science pipeline</div><strong>Not reported</strong><small>Older result bundles may not contain stage-level eligibility.</small></div>';return;}root.innerHTML=modules.map(m=>'<div class="metricitem"><div class="label">'+esc(m.name)+'</div><strong>'+esc(m.status)+'</strong><small style="display:block;margin-top:4px">'+esc(m.reason||m.interpretation||m.limitation||m.produces||'See the structured pipeline report.')+'</small></div>').join('');if(networks.length){root.insertAdjacentHTML('beforeend','<div class="metricitem"><div class="label">Temporal network diagnostics</div><strong>'+networks.length+' network component(s)</strong><small style="display:block;margin-top:4px">'+networks.map(n=>esc(n.geometry)+': '+esc(n.n_pairs)+' pairs, '+esc(n.n_epochs)+' epochs, redundancy '+esc(n.redundancy)+' ('+esc(n.topology_status)+')').join('<br>')+'</small></div>');}const overall=document.createElement('div');overall.className='metricitem';overall.innerHTML='<div class="label">Stage assessment</div><strong>'+esc(r.overall_status||r.network_assessment_status||'PARTIAL')+'</strong><small style="display:block;margin-top:4px">'+esc((r.warnings||[]).join(' '))+'</small>';root.prepend(overall);}function renderList(){
 const indices=familyIndices();
 $('productList').innerHTML=indices.map((globalIndex,position)=>{
  const p=obs[globalIndex],coverage=Number.isFinite(Number(p.aoi_coverage_pct))?Number(p.aoi_coverage_pct).toFixed(2)+'% AOI':'coverage N/A';
  const quality=p.support_level==='NO_USABLE_PIXELS'?'NO DATA':p.support_level==='VERY_LOW_COVERAGE'?'VERY LOW SUPPORT':p.support_level==='LOW_COVERAGE'?'LIMITED SUPPORT':'pixels available';
  return '<button class="product-row" data-idx="'+position+'" aria-current="'+(globalIndex===selected?'true':'false')+'"><span><strong>'+esc(p.id)+' · '+esc(p.product_type)+'</strong><small>'+esc(p.reference_date)+' → '+esc(p.secondary_date)+' · '+esc(p.track||'track N/A')+' · '+esc(coverage)+'</small></span><span class="product-quality">'+esc(quality)+'</span></button>';
 }).join('');
 document.querySelectorAll('.product-row').forEach(b=>b.addEventListener('click',()=>{stop();select(Number(b.dataset.idx));}));
}
function renderChart(){const svg=$('supportChart'),w=480,h=170;svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.replaceChildren();const max=Math.max(1,...obs.map(p=>Number(p.valid_pixels)||0)),pad=25,bw=Math.max(4,(w-pad*2)/Math.max(1,obs.length)*.62),step=(w-pad*2)/Math.max(1,obs.length);obs.forEach((p,i)=>{const value=Math.max(0,Number(p.valid_pixels)||0),bar=Math.max(1,value/max*105),x=pad+i*step+(step-bw)/2;const r=document.createElementNS('http://www.w3.org/2000/svg','rect');r.setAttribute('x',x);r.setAttribute('y',125-bar);r.setAttribute('width',bw);r.setAttribute('height',bar);r.setAttribute('rx',2);r.setAttribute('fill',p.product_type==='GUNW'?'#66e2d3':'#f7c76b');const t=document.createElementNS('http://www.w3.org/2000/svg','title');t.textContent=p.id+': '+value+' valid pixels';r.append(t);svg.append(r);if(obs.length<=16){const tx=document.createElementNS('http://www.w3.org/2000/svg','text');tx.setAttribute('x',x+bw/2);tx.setAttribute('y',143);tx.setAttribute('text-anchor','middle');tx.textContent=p.id.replace('GUNW-','').replace('GOFF-','');svg.append(tx);}});const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x',pad);t.setAttribute('y',12);t.textContent='Valid pixels in each product (not unique across pairs)';svg.append(t);}
function metricValue(p,key){const m=p.metrics||{};if((p.support_level==='NO_USABLE_PIXELS'||p.support_level==='VERY_LOW_COVERAGE')&&['gunw_los_median','goff_range_median','goff_azimuth_median'].includes(key))return null;let value=null;if(key==='gunw_los_median'&&p.product_type==='GUNW'&&m.reader_median_units==='mm')value=m.reader_median;else if(key==='goff_range_median'&&p.product_type==='GOFF')value=m.goff_range_median_mm;else if(key==='goff_azimuth_median'&&p.product_type==='GOFF')value=m.goff_azimuth_median_mm;else if(key==='goff_detection_floor'&&p.product_type==='GOFF')value=m.goff_detect_floor_mm_day;else if(key==='gunw_target_los'&&p.product_type==='GUNW'&&m.target_measurement_status==='MEASURED')value=m.target_local_los_median_mm;else if(key==='goff_target_range'&&p.product_type==='GOFF'&&m.target_measurement_status==='MEASURED')value=m.target_local_range_median_mm;else if(key==='goff_target_azimuth'&&p.product_type==='GOFF'&&m.target_measurement_status==='MEASURED')value=m.target_local_azimuth_median_mm;else if(key==='target_local_floor'&&m.target_local_floor_status==='MEASURED')value=m.target_local_floor_mm_day;return value!==null&&value!==undefined&&Number.isFinite(Number(value))?Number(value):null}
function metricUncertainty(p,key){if(key!=='target_local_floor')return null;const m=p.metrics||{},lo=m.target_local_floor_ci_lo_mm_day,hi=m.target_local_floor_ci_hi_mm_day;if(lo===null||lo===undefined||hi===null||hi===undefined||!Number.isFinite(Number(lo))||!Number.isFinite(Number(hi))||Number(hi)<Number(lo))return null;return [Number(lo),Number(hi)];}
function metricSpecs(){return [
{id:'gunw_los_median',label:'GUNW LOS displacement median (mm)',units:'mm',note:'Pairwise LOS displacement; not cumulative or 3-D motion.'},
{id:'goff_range_median',label:'GOFF range-offset median (mm)',units:'mm',note:'Pairwise slant-range offset statistic; not interchangeable with GUNW phase displacement.'},
{id:'goff_azimuth_median',label:'GOFF along-track offset median (mm)',units:'mm',note:'Along-track offset component; does not by itself provide full ground-motion direction.'},
{id:'goff_detection_floor',label:'GOFF detection floor (mm/day)',units:'mm/day',note:'Reader-reported detectability bound/noise floor, not observed displacement or a velocity measurement.'},
{id:'gunw_target_los',label:'Target-local GUNW LOS median (mm)',units:'mm',note:'Target-window value in this GUNW pair’s own reference frame; not a shared-datum displacement series.'},
{id:'goff_target_range',label:'Target-local GOFF range median (mm)',units:'mm',note:'Target-window range offset in this GOFF pair’s own reference frame; do not equate to GUNW phase displacement.'},
{id:'goff_target_azimuth',label:'Target-local GOFF along-track median (mm)',units:'mm',note:'Target-window along-track offset; not a complete 3-D movement vector.'},
{id:'target_local_floor',label:'Target-local detection floor (mm/day)',units:'mm/day',note:'Pair-specific local noise/detectability bound, not observed motion or a forecast.'}
]}
function renderMeasurementChart(){const metricSelect=$('measurementMetric'),trackSelect=$('measurementTrack'),svg=$('measurementChart');const specs=metricSpecs().filter(s=>obs.some(p=>metricValue(p,s.id)!==null));const priorMetric=metricSelect.value;metricSelect.innerHTML=specs.map(s=>'<option value="'+esc(s.id)+'">'+esc(s.label)+'</option>').join('');metricSelect.disabled=!specs.length;if(specs.some(s=>s.id===priorMetric))metricSelect.value=priorMetric;svg.replaceChildren();if(!specs.length){svg.setAttribute('viewBox','0 0 420 70');svg.style.height='70px';const tx=document.createElementNS('http://www.w3.org/2000/svg','text');tx.setAttribute('x','10');tx.setAttribute('y','35');tx.textContent='No unit-labelled compatible metrics are available for this run.';svg.append(tx);trackSelect.innerHTML='';trackSelect.disabled=true;return;}const spec=specs.find(s=>s.id===metricSelect.value)||specs[0];const values=obs.map(p=>({p,value:metricValue(p,spec.id)})).filter(x=>x.value!==null);const tracks=[...new Set(values.map(x=>x.p.track||'track unavailable'))].sort();const priorTrack=trackSelect.value;trackSelect.innerHTML=tracks.map(t=>'<option value="'+esc(t)+'">'+esc(t)+'</option>').join('');if(tracks.includes(priorTrack))trackSelect.value=priorTrack;trackSelect.disabled=!tracks.length;const track=trackSelect.value||tracks[0],rows=values.filter(x=>(x.p.track||'track unavailable')===track);const rangeValues=rows.flatMap(x=>{const band=metricUncertainty(x.p,spec.id);return [x.value,...(band||[])];});const maxAbs=Math.max(1,...rangeValues.map(v=>Math.abs(v)));const positiveOnly=rows.every(x=>x.value>=0);const h=Math.max(100,rows.length*30+48),w=560,left=150,plot=370,zero=positiveOnly?left:left+plot/2;svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.style.height=h+'px';const makeText=(x,y,t,anchor='start')=>{const tx=document.createElementNS('http://www.w3.org/2000/svg','text');tx.setAttribute('x',x);tx.setAttribute('y',y);tx.setAttribute('text-anchor',anchor);tx.textContent=t;svg.append(tx);};const axis=document.createElementNS('http://www.w3.org/2000/svg','line');axis.setAttribute('x1',zero);axis.setAttribute('x2',zero);axis.setAttribute('y1',20);axis.setAttribute('y2',h-24);axis.setAttribute('stroke','#72909d');axis.setAttribute('stroke-dasharray','3 3');svg.append(axis);makeText(left,12,spec.label+' · '+track);makeText(left,h-5,positiveOnly?'0':(-maxAbs).toFixed(1),'start');makeText(zero,h-5,'0','middle');makeText(left+plot,h-5,maxAbs.toFixed(1),'end');rows.forEach((x,i)=>{const p=x.p,value=x.value,y=25+i*30,width=Math.abs(value)/maxAbs*(positiveOnly?plot-5:plot/2-4),barX=value<0?zero-width:zero;makeText(left-8,y+13,p.id+' · '+String(p.secondary_date||'').slice(5),'end');const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.setAttribute('x',barX);rect.setAttribute('y',y);rect.setAttribute('width',Math.max(1,width));rect.setAttribute('height',18);rect.setAttribute('rx',3);rect.setAttribute('fill',spec.id==='goff_detection_floor'?'#f7c76b':(value<0?'#66b9e8':'#f4a879'));const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=p.id+': '+value+' '+spec.units+' · '+p.reference_date+' → '+p.secondary_date;rect.append(title);svg.append(rect);const uncertainty=metricUncertainty(p,spec.id);if(uncertainty){const scale=positiveOnly?plot-5:plot/2-4;const mapX=v=>zero+(v/maxAbs)*scale;const xLo=mapX(uncertainty[0]),xHi=mapX(uncertainty[1]),midY=y+9;const whisker=document.createElementNS('http://www.w3.org/2000/svg','line');whisker.setAttribute('x1',xLo);whisker.setAttribute('x2',xHi);whisker.setAttribute('y1',midY);whisker.setAttribute('y2',midY);whisker.setAttribute('stroke','#ffffff');whisker.setAttribute('stroke-width','2');svg.append(whisker);[xLo,xHi].forEach(xp=>{const cap=document.createElementNS('http://www.w3.org/2000/svg','line');cap.setAttribute('x1',xp);cap.setAttribute('x2',xp);cap.setAttribute('y1',y+4);cap.setAttribute('y2',y+14);cap.setAttribute('stroke','#ffffff');cap.setAttribute('stroke-width','1.5');svg.append(cap);});}});const note=document.createElementNS('http://www.w3.org/2000/svg','text');note.setAttribute('x',left);note.setAttribute('y',h-24);note.textContent=spec.note;svg.append(note);}
// Comparison viewers are deliberately pairwise: same family, same track/look,
// same source grid and matching band semantics are required. No raster
// subtraction, cumulative trend, or cross-datum motion is synthesized here.
let compareMapAInstance=null,compareMapBInstance=null,compareMapALoaded=false,compareMapBLoaded=false;
let comparisonSyncing=false,compareOverlayA=null,compareOverlayB=null;
function compareLayerFor(p,band){return layers.find(l=>l.observation_id===p.id&&Number(l.band)===Number(band))||null;}
function nearlyEqual(a,b){return Number.isFinite(Number(a))&&Number.isFinite(Number(b))&&Math.abs(Number(a)-Number(b))<=1e-8;}
function sameNumbers(a,b){return Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>nearlyEqual(v,b[i]));}
function sameSourceGrid(a,b){return Boolean(a&&b&&a.source_crs&&a.source_crs===b.source_crs&&Number(a.source_width)===Number(b.source_width)&&Number(a.source_height)===Number(b.source_height)&&sameNumbers(a.source_transform,b.source_transform)&&sameNumbers(a.corners&&a.corners.flat(),b.corners&&b.corners.flat()));}
function compatiblePair(a,b){
 if(!a||!b||a.id===b.id||a.product_type!==b.product_type)return false;
 const at=String(a.track||''),bt=String(b.track||'');
 const al=String(a.look_direction||''),bl=String(b.look_direction||'');
 if(!at||!bt||at.startsWith('geometry-unclassified:')||bt.startsWith('geometry-unclassified:')||at!==bt||!al||!bl||al!==bl)return false;
 const aa=compareLayerFor(a,1),bb=compareLayerFor(b,1);
 return Boolean(aa&&bb&&aa.description===bb.description&&aa.units===bb.units&&sameSourceGrid(aa,bb));
}
function compareOptions(select,items,currentValue){select.innerHTML=items.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.secondary_date)+' · '+esc(p.id)+'</option>').join('');if(items.some(p=>p.id===currentValue))select.value=currentValue;}
function addComparisonBaseLayers(map,loadedFlag){
 if(!map||!map.isStyleLoaded())return;
 if(aoi&&!map.getSource('compare-aoi')){map.addSource('compare-aoi',{type:'geojson',data:manifest.aoi});map.addLayer({id:'compare-aoi-fill',type:'fill',source:'compare-aoi',paint:{'fill-color':'#66e2d3','fill-opacity':0.04}});map.addLayer({id:'compare-aoi-outline',type:'line',source:'compare-aoi',paint:{'line-color':'#66e2d3','line-width':2,'line-dasharray':[2,1]}});}
 if(place&&Number.isFinite(Number(place.longitude))&&Number.isFinite(Number(place.latitude))&&!map.getSource('compare-site')){map.addSource('compare-site',{type:'geojson',data:{type:'Feature',properties:{name:place.name||'Selected site'},geometry:{type:'Point',coordinates:[Number(place.longitude),Number(place.latitude)]}}});map.addLayer({id:'compare-site-marker',type:'circle',source:'compare-site',paint:{'circle-radius':6,'circle-color':'#f7c76b','circle-stroke-color':'#fff','circle-stroke-width':1.5}});}if(target.status==='IN_AOI_TARGET_CAPTURED'&&Number.isFinite(Number(target.longitude))&&Number.isFinite(Number(target.latitude))&&!map.getSource('compare-target')){map.addSource('compare-target',{type:'geojson',data:{type:'Feature',properties:{name:'Measurement target'},geometry:{type:'Point',coordinates:[Number(target.longitude),Number(target.latitude)]}}});map.addLayer({id:'compare-target-marker',type:'circle',source:'compare-target',paint:{'circle-radius':3.5,'circle-color':'#ff806e','circle-stroke-color':'#fff','circle-stroke-width':1.2}});}
}
function createComparisonMap(container,side){
 const map=new maplibregl.Map({container,style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}},layers:[{id:'osm',type:'raster',source:'osm'}]},center:[0,0],zoom:2});
 map.addControl(new maplibregl.NavigationControl(),'top-right');
 map.on('load',function(){addComparisonBaseLayers(map);if(aoi){const coords=aoi.coordinates[0]||[];if(coords.length){let west=Infinity,south=Infinity,east=-Infinity,north=-Infinity;coords.forEach(c=>{west=Math.min(west,c[0]);south=Math.min(south,c[1]);east=Math.max(east,c[0]);north=Math.max(north,c[1]);});map.fitBounds([[west,south],[east,north]],{padding:24,maxZoom:14});}}if(side==='A')compareMapALoaded=true;else compareMapBLoaded=true;renderPairComparison();});
 map.on('move',function(){if(comparisonSyncing)return;const other=side==='A'?compareMapBInstance:compareMapAInstance;if(!other||!other.loaded())return;comparisonSyncing=true;other.jumpTo({center:map.getCenter(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()});comparisonSyncing=false;});
 return map;
}
function setCompareOverlay(map,side,p,band){
 if(!map||!map.isStyleLoaded())return;
 const sourceId='compare-raster-'+side,layerId='compare-raster-layer-'+side;
 if(map.getLayer(layerId))map.removeLayer(layerId);if(map.getSource(sourceId))map.removeSource(sourceId);
 const layer=compareLayerFor(p,band);if(!layer)return;
 const url=(window.SARGUARDIAN_LAYER_DATA||{})[layer.id]||layer.preview_asset;
 map.addSource(sourceId,{type:'image',url,coordinates:layer.corners});
 map.addLayer({id:layerId,type:'raster',source:sourceId,paint:{'raster-opacity':0.88,'raster-resampling':'nearest'}});
}
function renderPairComparison(){
 const selectA=$('compareA'),selectB=$('compareB'),selectBand=$('compareBand');
 if(!selectA||!selectB||!selectBand)return;
 const observationA=obs.find(p=>p.id===selectA.value)||null;
 const priorB=selectB.value;
 const compatible=obs.filter(p=>compatiblePair(observationA,p));
 compareOptions(selectB,compatible,priorB);
 const observationB=obs.find(p=>p.id===selectB.value)||null;
 const compatibleNow=compatiblePair(observationA,observationB);
 const status=$('compareStatus');
 selectB.disabled=!compatible.length;
 if(!compatibleNow){
  status.textContent='Comparison withheld: no second observation with matching product family, known track/look geometry and exact source grid. No difference or movement claim is generated.';
  $('compareTitleA').textContent=observationA?'Pair A · '+observationA.id:'Pair A';
  $('compareTitleB').textContent='No compatible Pair B';
  $('compareLegendA').textContent='No valid pair comparison selected.';
  $('compareLegendB').textContent='A compatible source grid is required.';
  return;
 }
 const layerA=compareLayerFor(observationA,1),layerB=compareLayerFor(observationB,1);
 const commonBands=layers.filter(l=>l.observation_id===observationA.id).filter(l=>{
  const other=compareLayerFor(observationB,l.band);
  return other&&l.description===other.description&&l.units===other.units&&sameSourceGrid(l,other);
 });
 const previousBand=selectBand.value;
 selectBand.innerHTML=commonBands.map(l=>'<option value="'+esc(l.band)+'">Band '+esc(l.band)+': '+esc(l.description)+' ('+esc(l.units)+')</option>').join('');
 if(commonBands.some(l=>String(l.band)===previousBand))selectBand.value=previousBand;
 selectBand.disabled=!commonBands.length;
 const band=Number(selectBand.value||1),chosenA=compareLayerFor(observationA,band),chosenB=compareLayerFor(observationB,band);
 if(!chosenA||!chosenB||!sameSourceGrid(chosenA,chosenB)||chosenA.description!==chosenB.description||chosenA.units!==chosenB.units){
  status.textContent='Selected bands do not satisfy the common-grid and common-band contract. Comparison withheld.';
  return;
 }
 $('compareTitleA').textContent=(observationA.reference_date||'—')+' → '+(observationA.secondary_date||'—')+' · '+observationA.id;
 $('compareTitleB').textContent=(observationB.reference_date||'—')+' → '+(observationB.secondary_date||'—')+' · '+observationB.id;
 const warning='Separate pairwise raster · '+chosenA.description+' · '+chosenA.units+' · display scaling is for visualization only.';
 $('compareLegendA').textContent=warning;
 $('compareLegendB').textContent=warning;
 status.textContent='Compatible pairwise view only: same family ('+observationA.product_type+'), track '+observationA.track+', look '+observationA.look_direction+', source CRS/grid and band meaning match. The two values are not subtracted and may still use different per-pair references.';
 if(!compareMapAInstance&&maplibregl&&typeof maplibregl.Map==='function')compareMapAInstance=createComparisonMap('compareMapA','A');
 if(!compareMapBInstance&&maplibregl&&typeof maplibregl.Map==='function')compareMapBInstance=createComparisonMap('compareMapB','B');
 if(compareMapALoaded&&compareMapAInstance)setCompareOverlay(compareMapAInstance,'A',observationA,band);
 if(compareMapBLoaded&&compareMapBInstance)setCompareOverlay(compareMapBInstance,'B',observationB,band);
 if(compareMapAInstance)compareMapAInstance.resize();if(compareMapBInstance)compareMapBInstance.resize();
}
function renderHypotheticalScenario(){
 const svg=$('scenarioChart'),result=$('scenarioResult');if(!svg||!result)return;
 const rate=Number($('scenarioRate').value),days=Number($('scenarioDays').value);
 svg.replaceChildren();
 if($('scenarioRate').value.trim()===''||$('scenarioDays').value.trim()===''||!Number.isFinite(rate)||!Number.isFinite(days)||days<1||days>90||!Number.isInteger(days)||Math.abs(rate)>500){
  result.textContent='Enter a finite hypothetical rate between −500 and +500 mm/day and a duration of 1–90 whole days. No scenario is shown until both inputs are valid.';
  svg.setAttribute('viewBox','0 0 560 80');svg.style.height='80px';return;
 }
 const cumulative=rate*days,maxAbs=Math.max(1,Math.abs(cumulative));
 svg.setAttribute('viewBox','0 0 560 180');svg.style.height='180px';
 const line=(x1,y1,x2,y2,stroke,width,dash)=>{const e=document.createElementNS('http://www.w3.org/2000/svg','line');for(const [k,v] of Object.entries({x1,y1,x2,y2,stroke,'stroke-width':width,'stroke-dasharray':dash||''}))e.setAttribute(k,v);svg.append(e);};
 const textSvg=(x,y,value,anchor='start')=>{const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x',x);t.setAttribute('y',y);t.setAttribute('text-anchor',anchor);t.textContent=value;svg.append(t);};
 const zero=88,endY=zero-(cumulative/maxAbs)*55;
 line(38,zero,522,zero,'#72909d',1,'4 3');line(38,28,38,148,'#72909d',1,'');
 line(38,zero,522,endY,'#66e2d3',3,'');
 const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx','522');dot.setAttribute('cy',String(endY));dot.setAttribute('r','4');dot.setAttribute('fill','#66e2d3');svg.append(dot);
 textSvg(38,17,'HYPOTHETICAL RATE × DURATION · NOT OBSERVED');textSvg(38,164,'0 days');textSvg(522,164,String(days)+' days','end');
 textSvg(48,zero-7,'0 mm');textSvg(514,endY+(cumulative>=0?-8:16),cumulative.toFixed(1)+' mm','end');
 const pair=current(),metrics=pair&&pair.metrics||{},floor=(metrics.target_local_floor_status==='MEASURED'?Number(metrics.target_local_floor_mm_day):NaN);
 let message='Hypothetical only — not observed NISAR data, not a hazard alert, and not a forecast. Scenario displacement after '+days+' days: '+cumulative.toFixed(2)+' mm at '+rate.toFixed(2)+' mm/day.';
 if(Number.isFinite(floor)&&floor>0){
  const ratio=Math.abs(rate)/floor;
  message+=' Selected observed pair '+pair.id+' has a measured pair-local floor of '+floor.toFixed(2)+' mm/day; absolute scenario rate is '+ratio.toFixed(2)+'× that floor. This ratio is a simple sensitivity comparison, not a formal detection probability, inverse-velocity test or prediction.';
 } else {
  message+=' No measured target-local floor is available for the selected observed pair; no detection-threshold comparison is shown.';
 }
 result.textContent=message;
}
function initComparisonControls(){
 const a=$('compareA'),b=$('compareB'),band=$('compareBand'),details=$('pairCompare');
 compareOptions(a,obs,obs[0]&&obs[0].id);
 if(obs.length>1){const first=obs.find(p=>obs.some(q=>compatiblePair(p,q)));if(first)a.value=first.id;}
 renderPairComparison();
 a.addEventListener('change',renderPairComparison);b.addEventListener('change',renderPairComparison);band.addEventListener('change',renderPairComparison);
 details.addEventListener('toggle',()=>{if(details.open){renderPairComparison();if(compareMapAInstance)compareMapAInstance.resize();if(compareMapBInstance)compareMapBInstance.resize();}});
 $('simulateScenario').addEventListener('click',renderHypotheticalScenario);
}
function renderCommonReferenceChart(){
 const report=manifest.common_reference_timeseries||{},selectBox=$('cumulativeNetwork'),status=$('cumulativeStatus'),svg=$('cumulativeChart');
 if(!selectBox||!status||!svg)return;
 const components=(report.components||[]).filter(c=>c.status==='DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED'&&Array.isArray(c.series)&&c.series.length>=3);
 const oldValue=selectBox.value;
 selectBox.innerHTML=components.map((c,i)=>'<option value="'+i+'">'+esc(c.network)+' · component '+esc(c.component)+'</option>').join('');
 selectBox.disabled=!components.length;
 svg.replaceChildren();
 if(!components.length){
  const reason=report.reason||'No common-reference cumulative series met the minimum pixel, grid, redundancy and jackknife-stability gates.';
  status.textContent='Series withheld · '+String(report.status||'NOT_REPORTED')+' · '+reason;
  svg.setAttribute('viewBox','0 0 560 85');svg.style.height='85px';
  const textNode=document.createElementNS('http://www.w3.org/2000/svg','text');textNode.setAttribute('x','10');textNode.setAttribute('y','34');textNode.textContent='No publishable cumulative diagnostic series for this run.';svg.append(textNode);
  return;
 }
 if(oldValue!==''&&Number.isInteger(Number(oldValue))&&Number(oldValue)>=0&&Number(oldValue)<components.length)selectBox.value=oldValue;
 const component=components[Number(selectBox.value)||0],rows=component.series.filter(p=>p.cumulative_los_mm!==null&&p.cumulative_los_mm!==undefined&&Number.isFinite(Number(p.cumulative_los_mm)));
 if(rows.length<3){
  status.textContent='Series withheld: insufficient finite acquisition-epoch values.';
  return;
 }
 status.textContent='DIAGNOSTIC ONLY · '+component.network+' · '+rows.length+' actual epochs · '+component.pairs_count+' pairs · redundancy '+component.redundancy+' · common-reference pixels '+((report.networks||[]).find(n=>n.network===component.network)||{}).common_pixels_outside_target_buffer+'. The common datum is AOI-derived and reference stability is not independently validated.';
 const epochs=rows.map(p=>Date.parse(p.epoch+'T00:00:00Z')),values=rows.map(p=>Number(p.cumulative_los_mm));
 const uncertainty=rows.map(p=>({lo:p.graph_fit_ci95_low_mm,hi:p.graph_fit_ci95_high_mm})).filter(v=>v.lo!==null&&v.hi!==null&&Number.isFinite(Number(v.lo))&&Number.isFinite(Number(v.hi)));
 const yVals=[...values,...uncertainty.flatMap(v=>[Number(v.lo),Number(v.hi)])],minY=Math.min(0,...yVals),maxY=Math.max(0,...yVals),spanY=Math.max(1,maxY-minY);
 const minX=Math.min(...epochs),maxX=Math.max(...epochs),spanX=Math.max(1,maxX-minX);
 const W=600,H=230,left=66,right=18,top=30,bottom=45,plotW=W-left-right,plotH=H-top-bottom;
 const xMap=x=>left+(x-minX)/spanX*plotW;
 const yMap=y=>top+(maxY-y)/spanY*plotH;
 svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.style.height='230px';
 const addLine=(x1,y1,x2,y2,stroke,width,dash)=>{const e=document.createElementNS('http://www.w3.org/2000/svg','line');[['x1',x1],['y1',y1],['x2',x2],['y2',y2],['stroke',stroke],['stroke-width',width],['stroke-dasharray',dash||'']].forEach(([k,v])=>e.setAttribute(k,v));svg.append(e);};
 const addText=(x,y,txt,anchor='middle')=>{const e=document.createElementNS('http://www.w3.org/2000/svg','text');e.setAttribute('x',x);e.setAttribute('y',y);e.setAttribute('text-anchor',anchor);e.textContent=txt;svg.append(e);};
 for(let i=0;i<=4;i++){const value=minY+spanY*i/4,y=yMap(value);addLine(left,y,W-right,y,'#29414f',1,'3 4');addText(left-8,y+3,value.toFixed(1),'end');}
 addLine(left,top,left,H-bottom,'#72909d',1,'');addLine(left,H-bottom,W-right,H-bottom,'#72909d',1,'');
 addText(left,14,'Cumulative LOS · mm (relative to first connected epoch)','start');
 const pathNode=document.createElementNS('http://www.w3.org/2000/svg','path');pathNode.setAttribute('d',rows.map((p,i)=>(i?'L':'M')+xMap(epochs[i]).toFixed(2)+' '+yMap(values[i]).toFixed(2)).join(' '));pathNode.setAttribute('fill','none');pathNode.setAttribute('stroke','#66e2d3');pathNode.setAttribute('stroke-width','2.5');svg.append(pathNode);
 rows.forEach((p,i)=>{const x=xMap(epochs[i]),y=yMap(values[i]),lo=p.graph_fit_ci95_low_mm,hi=p.graph_fit_ci95_high_mm;
  if(lo!==null&&hi!==null&&Number.isFinite(Number(lo))&&Number.isFinite(Number(hi))){const y1=yMap(Number(hi)),y2=yMap(Number(lo));addLine(x,y1,x,y2,'#ffffff',1.4,'');addLine(x-4,y1,x+4,y1,'#ffffff',1.4,'');addLine(x-4,y2,x+4,y2,'#ffffff',1.4,'');}
  const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.setAttribute('r',4);dot.setAttribute('fill','#66e2d3');dot.setAttribute('stroke','#07121c');dot.setAttribute('stroke-width',1);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=p.epoch+': '+values[i].toFixed(2)+' mm cumulative LOS';dot.append(title);svg.append(dot);
 });
 addText(left,H-17,rows[0].epoch,'start');addText(W-right,H-17,rows[rows.length-1].epoch,'end');
 addText(W-right,14,'White bars: fit-only 95% interval','end');
}
function renderGoffCommonReferenceChart(){
 const report=manifest.goff_common_reference_timeseries||{},selectBox=$('goffCumulativeNetwork'),status=$('goffCumulativeStatus'),svg=$('goffCumulativeChart');
 if(!selectBox||!status||!svg)return;
 const components=(report.components||[]).filter(c=>c.status==='DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED'&&Array.isArray(c.series)&&c.series.length>=3);
 const oldValue=selectBox.value;
 selectBox.innerHTML=components.map((c,i)=>'<option value="'+i+'">'+esc(c.network)+' · '+esc(c.component)+'</option>').join('');
 selectBox.disabled=!components.length;svg.replaceChildren();
 if(!components.length){
  status.textContent='Series withheld · '+String(report.status||'NOT_REPORTED')+' · '+(report.reason||'No GOFF network passed the common-pixel, target-window and redundant graph gates.');
  svg.setAttribute('viewBox','0 0 560 85');svg.style.height='85px';
  const textNode=document.createElementNS('http://www.w3.org/2000/svg','text');textNode.setAttribute('x','10');textNode.setAttribute('y','34');textNode.textContent='No eligible GOFF common-reference diagnostic series for this run.';svg.append(textNode);return;
 }
 if(oldValue!==''&&Number.isInteger(Number(oldValue))&&Number(oldValue)>=0&&Number(oldValue)<components.length)selectBox.value=oldValue;
 const component=components[Number(selectBox.value)||0],rows=component.series.filter(p=>p.cumulative_offset_mm!==null&&p.cumulative_offset_mm!==undefined&&Number.isFinite(Number(p.cumulative_offset_mm)));
 if(rows.length<3){status.textContent='Series withheld: insufficient finite GOFF acquisition-epoch values.';return;}
 const componentLabel=component.component==='range_offset'?'slant-range offset component':'along-track azimuth offset component';
 status.textContent='DIAGNOSTIC ONLY · '+component.network+' · '+componentLabel+' · '+rows.length+' actual epochs · '+component.pairs_count+' pairs · redundancy '+component.redundancy+'. The common datum is AOI-derived and reference stability is not independently validated; these offsets are not a 3-D motion estimate.';
 const epochs=rows.map(p=>Date.parse(p.epoch+'T00:00:00Z')),values=rows.map(p=>Number(p.cumulative_offset_mm));
 const uncertainty=rows.map(p=>({lo:p.graph_fit_ci95_low_mm,hi:p.graph_fit_ci95_high_mm})).filter(v=>v.lo!==null&&v.hi!==null&&Number.isFinite(Number(v.lo))&&Number.isFinite(Number(v.hi)));
 const yVals=[...values,...uncertainty.flatMap(v=>[Number(v.lo),Number(v.hi)])],minY=Math.min(0,...yVals),maxY=Math.max(0,...yVals),spanY=Math.max(1,maxY-minY);
 const minX=Math.min(...epochs),maxX=Math.max(...epochs),spanX=Math.max(1,maxX-minX);
 const W=600,H=230,left=66,right=18,top=30,bottom=45,plotW=W-left-right,plotH=H-top-bottom;
 const xMap=x=>left+(x-minX)/spanX*plotW,yMap=y=>top+(maxY-y)/spanY*plotH;
 svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.style.height='230px';
 const addLine=(x1,y1,x2,y2,stroke,width,dash)=>{const e=document.createElementNS('http://www.w3.org/2000/svg','line');[['x1',x1],['y1',y1],['x2',x2],['y2',y2],['stroke',stroke],['stroke-width',width],['stroke-dasharray',dash||'']].forEach(([k,v])=>e.setAttribute(k,v));svg.append(e);};
 const addText=(x,y,text,anchor='middle')=>{const e=document.createElementNS('http://www.w3.org/2000/svg','text');e.setAttribute('x',x);e.setAttribute('y',y);e.setAttribute('text-anchor',anchor);e.textContent=text;svg.append(e);};
 for(let i=0;i<=4;i++){const value=minY+spanY*i/4,y=yMap(value);addLine(left,y,W-right,y,'#29414f',1,'3 4');addText(left-8,y+3,value.toFixed(1),'end');}
 addLine(left,top,left,H-bottom,'#72909d',1,'');addLine(left,H-bottom,W-right,H-bottom,'#72909d',1,'');
 addText(left,14,'Cumulative GOFF '+component.component.replace('_',' ')+' · mm (relative to first connected epoch)','start');
 const pathNode=document.createElementNS('http://www.w3.org/2000/svg','path');pathNode.setAttribute('d',rows.map((p,i)=>(i?'L':'M')+xMap(epochs[i]).toFixed(2)+' '+yMap(values[i]).toFixed(2)).join(' '));pathNode.setAttribute('fill','none');pathNode.setAttribute('stroke','#f7c76b');pathNode.setAttribute('stroke-width','2.5');svg.append(pathNode);
 rows.forEach((p,i)=>{const x=xMap(epochs[i]),y=yMap(values[i]),lo=p.graph_fit_ci95_low_mm,hi=p.graph_fit_ci95_high_mm;
  if(lo!==null&&hi!==null&&Number.isFinite(Number(lo))&&Number.isFinite(Number(hi))){const y1=yMap(Number(hi)),y2=yMap(Number(lo));addLine(x,y1,x,y2,'#ffffff',1.4,'');addLine(x-4,y1,x+4,y1,'#ffffff',1.4,'');addLine(x-4,y2,x+4,y2,'#ffffff',1.4,'');}
  const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.setAttribute('r',4);dot.setAttribute('fill','#f7c76b');dot.setAttribute('stroke','#07121c');dot.setAttribute('stroke-width',1);const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=p.epoch+': '+values[i].toFixed(2)+' mm cumulative '+component.component;dot.append(title);svg.append(dot);
 });
 addText(left,H-17,rows[0].epoch,'start');addText(W-right,H-17,rows[rows.length-1].epoch,'end');addText(W-right,14,'White bars: fit-only 95% interval','end');
}
function select(i){const indices=familyIndices();if(!indices.length)return;selected=indices[(i+indices.length)%indices.length];renderProduct();}
function stop(){playing=false;if(timer)clearInterval(timer);timer=null;$('play').textContent='Play';$('publicPlay').textContent='Play '+activeFamily;}
function play(){const count=familyIndices().length;if(count<2)return;if(playing){stop();return;}playing=true;$('play').textContent='Pause';$('publicPlay').textContent='Pause';timer=setInterval(()=>select((familyPosition()+1)%familyIndices().length),Number($('speed').value||1500));}
function setFamily(family){if(family!=='GUNW'&&family!=='GOFF')return;stop();if(!familyIndices(family).length)return;activeFamily=family;selected=firstRenderableIndex(family);syncFamilyControls();syncPublicCandidateOverlay();renderProduct();renderPublicCandidateCards(activeFamily);}
const sgModeButtons=Array.from(document.querySelectorAll('[data-sg-mode]'));
const sgModeDescriptions={public:'A plain-language overview of the AOI, observation coverage and candidate evidence.',evidence:'Explore the real acquisition pairs, map layers, playback and spatial candidate records.',science:'Inspect pair measurements, network eligibility, data support, stage diagnostics and run provenance.'};
function setSgDashboardMode(mode){
 if(!Object.prototype.hasOwnProperty.call(sgModeDescriptions,mode))return;
 document.body.dataset.dashboardMode=mode;
 sgModeButtons.forEach(button=>{const selected=button.dataset.sgMode===mode;button.setAttribute('aria-selected',String(selected));button.setAttribute('aria-pressed',String(selected));});
 const caption=$('modeCaption');if(caption)caption.textContent=sgModeDescriptions[mode];
}
sgModeButtons.forEach((button,index)=>{button.addEventListener('click',()=>setSgDashboardMode(button.dataset.sgMode));button.addEventListener('keydown',event=>{if(event.key!=='ArrowRight'&&event.key!=='ArrowLeft')return;event.preventDefault();const next=(index+(event.key==='ArrowRight'?1:-1)+sgModeButtons.length)%sgModeButtons.length;sgModeButtons[next].focus();setSgDashboardMode(sgModeButtons[next].dataset.sgMode);});});
setSgDashboardMode('public');
$('candidateOverlaySelect').addEventListener('change',()=>{applyCandidateOverlay();updatePublicCandidateToggle();});
$('publicCandidateToggle').addEventListener('click',()=>{const selector=$('candidateOverlaySelect');if(!selector)return;selector.value=selector.value==='none'?publicDefaultCandidateMode(activeFamily):'none';applyCandidateOverlay();updatePublicCandidateToggle();});
document.querySelectorAll('[data-public-family]').forEach(button=>button.addEventListener('click',()=>setFamily(button.dataset.publicFamily)));
$('advancedFamilySelect').addEventListener('change',event=>setFamily(event.target.value));
$('publicTimeline').addEventListener('input',event=>{stop();select(Number(event.target.value));});
$('publicPrevious').addEventListener('click',()=>{stop();select(familyPosition()-1);});
$('publicNext').addEventListener('click',()=>{stop();select(familyPosition()+1);});
$('publicPlay').addEventListener('click',play);
$('timeline').addEventListener('input',e=>{stop();select(Number(e.target.value));});
$('productSelect').addEventListener('change',e=>{stop();select(Number(e.target.value));});
$('previous').addEventListener('click',()=>{stop();select(familyPosition()-1);});
$('next').addEventListener('click',()=>{stop();select(familyPosition()+1);});
$('play').addEventListener('click',play);
$('speed').addEventListener('change',()=>{if(playing){stop();play();}});$('measurementTrack').addEventListener('change',renderMeasurementChart);$('measurementMetric').addEventListener('change',renderMeasurementChart);$('cumulativeNetwork').addEventListener('change',renderCommonReferenceChart);$('goffCumulativeNetwork').addEventListener('change',renderGoffCommonReferenceChart);$('bandSelect').addEventListener('change',renderProduct);$('derivedLayerSelect').addEventListener('change',renderDerivedLayer);$('opacity').addEventListener('input',()=>{if(M&&activeLayer&&M.getLayer('raster-'+activeLayer))M.setPaintProperty('raster-'+activeLayer,'raster-opacity',Number($('opacity').value)/100);});function syncSgPresentation(){const active=Boolean(document.fullscreenElement)||document.body.classList.contains('presentation-active');document.body.classList.toggle('presentation-active',active);$('presentation').textContent=active?'Exit presentation':'Enter presentation';$('presentation').setAttribute('aria-pressed',String(active));}
$('presentation').addEventListener('click',async()=>{const active=document.body.classList.contains('presentation-active')||Boolean(document.fullscreenElement);if(active){document.body.classList.remove('presentation-active');if(document.fullscreenElement){try{await document.exitFullscreen();}catch(e){}}syncSgPresentation();return;}document.body.classList.add('presentation-active');syncSgPresentation();try{if(document.documentElement.requestFullscreen)await document.documentElement.requestFullscreen();}catch(e){$('presentation').title='The browser blocked full screen; the presentation layout remains active.';}syncSgPresentation();});
document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)document.body.classList.remove('presentation-active');syncSgPresentation();});window.addEventListener('beforeunload',()=>{stop();if(compareMapAInstance)compareMapAInstance.remove();if(compareMapBInstance)compareMapBInstance.remove();});renderList();renderChart();renderMeasurementChart();renderCommonReferenceChart();renderGoffCommonReferenceChart();renderAoiCandidateScreen();renderAOIPixelTimeseriesStatus();renderPixelStackDiagnostic();renderSciencePipeline();initComparisonControls();if(n)renderProduct();else $('mapTitle').textContent='No observations available';syncPublicCandidateOverlay();renderPublicCandidateCards(activeFamily);})();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


def metric_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _add_derived_raster_layer(
    *,
    root: Path,
    webroot: Path,
    geometry: dict[str, Any],
    artifact: dict[str, Any],
    network: str,
    status: str,
    derived_layers: list[dict[str, Any]],
    derived_layer_errors: list[dict[str, str]],
) -> None:
    role = str(artifact.get("role") or "")
    relative = str(artifact.get("relative_path") or "")
    try:
        source_path = safe_path(root, relative)
        if not source_path.is_file() or source_path.suffix.lower() not in {".tif", ".tiff"}:
            raise ValueError("DERIVED_RASTER_MISSING")
        expected_hash = str(artifact.get("sha256") or "")
        if not re.fullmatch(r"[a-f0-9]{64}", expected_hash) or sha256(source_path) != expected_hash:
            raise ValueError("DERIVED_RASTER_SHA256_MISMATCH")
        values, bounds, meta = reproject_band(source_path, 1, geometry)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            raise ValueError("DERIVED_RASTER_HAS_NO_DISPLAYABLE_PIXELS")

        if "velocity" in role.lower() and "sigma" not in role.lower():
            limit = float(np.percentile(np.abs(finite), 98))
            if not math.isfinite(limit) or limit <= 0:
                limit = max(float(np.max(np.abs(finite))), 1.0)
            lo, hi, method, kind = -limit, limit, "symmetric_abs_98th_percentile", "continuous"
        elif "candidate mask" in role.lower():
            lo, hi, method, kind = 0.0, 1.0, "fixed_candidate_mask_0_to_1", "candidate_mask"
        elif "reference mask" in role.lower():
            lo, hi, method, kind = 0.0, 1.0, "fixed_reference_mask_0_to_1", "reference_mask"
        elif "mask" in role.lower():
            lo, hi, method, kind = 0.0, 1.0, "fixed_binary_mask_0_to_1", "coherence"
        else:
            lo, hi, method, kind = 0.0, float(np.percentile(finite, 98)), "positive_98th_percentile", "coherence"
            if not math.isfinite(hi) or hi <= 0:
                hi = max(float(np.max(finite)), 1.0)
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", network or "network").strip("-").lower()[:55]
        role_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", role).strip("-").lower()[:38]
        layer_id = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{role_slug}-{slug}").strip("-")[:110]
        preview_relative = f"layers/derived-{layer_id}.png"
        image_path = webroot / preview_relative
        count, value_min, value_max = write_rgba(values, lo, hi, kind, image_path)
        if count <= 0 or image_path.stat().st_size <= 0:
            raise ValueError("DERIVED_PREVIEW_HAS_NO_VALID_PIXELS")
        derived_layers.append({
            "id": layer_id, "observation_id": None, "product_type": "AOI_DERIVED",
            "description": role, "units": str(artifact.get("units") or meta.get("units") or "source units not declared"),
            "kind": kind, "analysis_role": role, "network": network or "AOI network", "status": status,
            "source_asset": relative, "source_sha256": expected_hash,
            "native_valid_pixels": int(artifact.get("valid_pixels") or 0),
            "preview_asset": preview_relative, "preview_sha256": sha256(image_path),
            "preview_bytes": image_path.stat().st_size, "source_crs": meta["source_crs"],
            "source_transform": meta["source_transform"], "source_width": meta["source_width"],
            "source_height": meta["source_height"], "preview_crs": WEB_CRS,
            "preview_transform": meta["preview_transform"], "preview_width": meta["preview_width"],
            "preview_height": meta["preview_height"], "bounds_wgs84": list(bounds),
            "corners": [[bounds[0], bounds[3]], [bounds[2], bounds[3]], [bounds[2], bounds[1]], [bounds[0], bounds[1]]],
            "valid_pixels": count, "value_min": value_min, "value_max": value_max,
            "display_scale": {"min": lo, "max": hi, "method": method, "clipping_percentile": 98},
            "reference_policy": "AOI-derived/relative as declared by source artifact; not independently validated stable ground",
            "movement_confirmed": False, "hazard_detected": False,
        })
    except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
        derived_layer_errors.append({
            "network": network, "role": role, "source_asset": relative,
            "reason": f"{type(exc).__name__}:{str(exc)[:180]}",
        })


def prepare_web_dashboard(root: Path) -> dict[str, Any]:
    root = root.resolve()
    summary_path = root / "aoi-run-summary.json"
    report_path = root / "aoi-processing-report.json"
    summary = read_json(summary_path)
    report = read_json(report_path, required=False)
    products = report.get("products")
    if not isinstance(products, list):
        products = [read_json(p) for p in sorted((root / "product-data").glob("*/product-record.json"))]
    if len(products) != int(summary.get("products_expected", len(products))):
        raise ValueError("Dashboard product count does not match processing summary")
    ring = parse_wkt(str(summary.get("aoi_wkt") or ""))
    geometry = {"type": "Polygon", "coordinates": [ring]}
    feature = {"type": "Feature", "properties": {"name": summary.get("aoi_name", "custom"), "aoi_wkt_sha256": summary.get("aoi_wkt_sha256")}, "geometry": geometry}
    bbox = [min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring)]

    pending = []
    groups: dict[tuple[str, str, str], list[np.ndarray]] = {}
    ordered = sorted(products, key=lambda p: (str(p.get("secondary_date") or "9999"), str(p.get("reference_date") or "9999"), str(p.get("id") or "")))
    for product in ordered:
        pid = str(product.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", pid):
            raise ValueError("Invalid product ID in processing report")
        exports = product.get("exports") or []
        if not exports:
            exports = [{"relative_path": next((p.relative_to(root).as_posix() for p in (root / "product-data" / pid).glob("*.tif")), "")}]
        band1_source_counts: list[int] = []
        for export_index, export in enumerate(exports):
            relative = str(export.get("relative_path") or "")
            if not relative:
                continue
            raster_path = safe_path(root, relative)
            if not raster_path.is_file() or raster_path.suffix.lower() not in {".tif", ".tiff"}:
                raise ValueError(f"Validated GeoTIFF not found: {pid}/{relative}")
            original_hash = sha256(raster_path)
            with rasterio.open(raster_path) as ds:
                band_count = ds.count
                source_tags_for_layers = ds.tags()
            for band in range(1, band_count + 1):
                values, bounds, meta = reproject_band(raster_path, band, geometry)
                overlaps = bounds[0] <= bbox[2] and bounds[2] >= bbox[0] and bounds[1] <= bbox[3] and bounds[3] >= bbox[1]
                if not overlaps:
                    raise ValueError(f"Preview does not intersect AOI: {pid}/{raster_path.name}")
                valid = values[np.isfinite(values)]
                if band == 1:
                    band1_source_counts.append(meta["source_valid_pixels"])
                if not valid.size:
                    continue
                track_value = (product.get("stats") or {}).get("track") or product.get("track")
                track = str(track_value) if track_value else "geometry-unclassified:" + pid
                description_lower = meta["description"].lower()
                kind = (
                    "coherence" if "coherence" in description_lower else
                    "binary_mask" if "robust inlier flag" in description_lower else
                    "continuous"
                )
                group_key = (str(product.get("product_type") or "UNKNOWN"), track, meta["description"])
                groups.setdefault(group_key, []).append(valid.astype("float32", copy=False))
                layer_id = f"{pid}-e{export_index+1}-band-{band}"
                pending.append({
                    "id": layer_id, "observation_id": pid, "product_type": product.get("product_type"),
                    "export_name": raster_path.name, "band": band, "description": meta["description"], "units": meta["units"],
                    "kind": kind, "source_sha256": original_hash, "source_asset": relative,
                    "source_crs": meta["source_crs"], "source_transform": meta["source_transform"],
                    "source_width": meta["source_width"], "source_height": meta["source_height"],
                    "source_valid_pixels": meta["source_valid_pixels"], "data_type": meta["data_type"],
                    "screen_valid_pixels": (
                        int(source_tags_for_layers["screen_valid_pixels"])
                        if band == 4 and source_tags_for_layers.get("screen_valid_pixels", "").isdigit() else None
                    ),
                    "robust_inlier_pixels": (
                        int(source_tags_for_layers["robust_inlier_pixels"])
                        if band == 4 and source_tags_for_layers.get("robust_inlier_pixels", "").isdigit() else None
                    ),
                    "screen_outlier_pixels": (
                        int(source_tags_for_layers["robust_outlier_pixels"])
                        if band == 4 and source_tags_for_layers.get("robust_outlier_pixels", "").isdigit() else None
                    ),
                    "preview_crs": WEB_CRS, "preview_transform": meta["preview_transform"],
                    "preview_width": meta["preview_width"], "preview_height": meta["preview_height"],
                    "bounds_wgs84": list(bounds),
                    "corners": [[bounds[0], bounds[3]], [bounds[2], bounds[3]], [bounds[2], bounds[1]], [bounds[0], bounds[1]]],
                    "valid_pixels": int(valid.size), "value_min": float(np.min(valid)), "value_max": float(np.max(valid)),
                    "values": values, "group_key": group_key,
                })
            if sha256(raster_path) != original_hash:
                raise RuntimeError(f"Source GeoTIFF unexpectedly changed: {raster_path.name}")
        if band1_source_counts:
            # Band 1 preserves the broad, quality-valid screening mask for GOFF;
            # the stricter measurement-valid count is recorded separately after
            # the global-MAD gate. Do not compare screen pixels to measurement pixels.
            expected_screen_raw = product.get("screen_valid_pixels")
            expected_raw = expected_screen_raw if expected_screen_raw is not None else product.get("valid_pixels")
            try:
                expected_screen = int(expected_raw)
            except (TypeError, ValueError):
                expected_screen = -1
            if expected_screen >= 0 and max(band1_source_counts) != expected_screen:
                raise ValueError(
                    f"Product screen-valid pixel summary mismatch for {pid}: "
                    f"record={expected_screen}, max_export={max(band1_source_counts)}"
                )

    webroot = root / "web-dashboard"
    # Publish all AOI-wide scientific derivatives as selectable map layers and
    # PNG quicklooks. Native GeoTIFFs remain authoritative.
    derived_layers: list[dict[str, Any]] = []
    derived_layer_errors: list[dict[str, str]] = []
    pixel_report = summary.get("aoi_relative_pixel_timeseries") or {}
    for network in pixel_report.get("networks", []) if isinstance(pixel_report.get("networks"), list) else []:
        if network.get("status") != "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_REFERENCE_UNVALIDATED":
            continue
        for artifact in network.get("artifacts", []) if isinstance(network.get("artifacts"), list) else []:
            _add_derived_raster_layer(
                root=root, webroot=webroot, geometry=geometry, artifact=artifact,
                network=str(network.get("network") or "GUNW network"),
                status=str(network.get("status") or "NOT_REPORTED"),
                derived_layers=derived_layers, derived_layer_errors=derived_layer_errors,
            )

    candidate_report = summary.get("aoi_displacement_candidates") or {}
    for artifact in candidate_report.get("raster_artifacts", []) if isinstance(candidate_report.get("raster_artifacts"), list) else []:
        _add_derived_raster_layer(
            root=root, webroot=webroot, geometry=geometry, artifact=artifact,
            network=str(artifact.get("network") or "AOI candidate screen"),
            status=str(candidate_report.get("status") or "NOT_REPORTED"),
            derived_layers=derived_layers, derived_layer_errors=derived_layer_errors,
        )
    public_layers = []
    for layer in pending:
        values = layer.pop("values")
        group_key = layer.pop("group_key")
        if layer["kind"] == "coherence":
            lo, hi, method = 0.0, 1.0, "fixed_coherence_0_to_1"
        elif layer["kind"] == "binary_mask":
            lo, hi, method = 0.0, 1.0, "discrete_flag_0_outlier_1_inlier"
            layer["units"] = "binary flag (1=inlier, 0=global-MAD outlier retained for review)"
        else:
            joined = np.concatenate(groups[group_key])
            limit = float(np.percentile(np.abs(joined[np.isfinite(joined)]), 98))
            if not math.isfinite(limit) or limit <= 0:
                limit = max(float(np.max(np.abs(joined[np.isfinite(joined)]))), 1.0)
            lo, hi, method = -limit, limit, "track_group_symmetric_98th_percentile"
        rel = f"layers/{layer['id']}.png"
        image_path = webroot / rel
        count, min_value, max_value = write_rgba(values, lo, hi, layer["kind"], image_path)
        if count != layer["valid_pixels"] or image_path.stat().st_size <= 0:
            raise ValueError(f"Preview integrity check failed: {layer['id']}")
        layer.update({"preview_asset": rel, "preview_sha256": sha256(image_path), "preview_bytes": image_path.stat().st_size,
                      "display_scale": {"min": lo, "max": hi, "method": method, "clipping_percentile": 98 if layer["kind"] == "continuous" else None},
                      "value_min": min_value, "value_max": max_value})
        public_layers.append(layer)

    observations = []
    for product in ordered:
        stats = product.get("stats") or {}
        floor = product.get("local_floor") if isinstance(product.get("local_floor"), dict) else {}
        floor_metrics = floor.get("metrics") if isinstance(floor.get("metrics"), dict) else {}
        target = product.get("target_measurement") if isinstance(product.get("target_measurement"), dict) else {}
        target_metrics = target.get("measurements") if isinstance(target.get("measurements"), dict) else {}
        target_status = str(target.get("status") or "NOT_REPORTED")
        floor_status = str(floor.get("status") or "NOT_REPORTED")
        product_layers = [layer for layer in public_layers if layer["observation_id"] == product.get("id")]
        band1 = next((layer for layer in product_layers if layer["band"] == 1), None)
        metric_name = str(product.get("metric_name") or "")
        metric_units = "source units not declared"
        if product.get("product_type") == "GUNW" and band1 and "los displacement" in band1["description"].lower() and "median" in metric_name.lower():
            metric_units = "mm"
        elif product.get("product_type") == "GOFF" and metric_name.lower() in {"range_median_mm", "median_range_mm", "azimuth_median_mm"}:
            metric_units = "mm"
        elif "mm_day" in metric_name.lower() or "floor" in metric_name.lower() or "velocity" in metric_name.lower():
            metric_units = "mm/day"
        valid_support_pixels = int(product.get("valid_pixels") or 0)
        aoi_support_pixels = metric_number(stats.get("aoi_px"))
        aoi_coverage_pct = metric_number(stats.get("aoi_pct"))
        if aoi_coverage_pct is None and aoi_support_pixels and aoi_support_pixels > 0:
            aoi_coverage_pct = 100.0 * valid_support_pixels / aoi_support_pixels
        if valid_support_pixels <= 0:
            support_level = "NO_USABLE_PIXELS"
        elif aoi_coverage_pct is not None and aoi_coverage_pct < 1.0:
            support_level = "VERY_LOW_COVERAGE"
        elif aoi_coverage_pct is not None and aoi_coverage_pct < 10.0:
            support_level = "LOW_COVERAGE"
        else:
            support_level = "PIXEL_SUPPORT_AVAILABLE"
        observations.append({
            "id": product.get("id"), "product_type": product.get("product_type"), "granule_name": product.get("granule_name"),
            "reference_date": product.get("reference_date"), "secondary_date": product.get("secondary_date"),
            "track": stats.get("track") or product.get("track"),
            "look_direction": product.get("look_direction") or stats.get("look_direction"),
            "maturity": product.get("maturity"), "crid": product.get("crid") or stats.get("crid"),
            "status": product.get("status"), "valid_pixels": product.get("valid_pixels"),
            "aoi_support_pixels": aoi_support_pixels, "aoi_coverage_pct": aoi_coverage_pct,
            "support_level": support_level,
            "screen_valid_pixels": product.get("screen_valid_pixels"),
            "screen_outlier_pixels": product.get("screen_outlier_pixels"),
            "grid_pixels_inside_aoi": product.get("grid_pixels_inside_aoi"), "source_sha256": product.get("source_sha256"),
            "warnings": product.get("warnings") or [], "validation_scope": product.get("validation_scope") or "structural_and_provenance_not_independent_geophysical_validation",
            "native_assets": [item.get("relative_path") for item in product.get("exports", []) if item.get("relative_path")],
            "quicklook": product.get("quicklook"), "layers": [layer["id"] for layer in product_layers],
            "metrics": {
                "reader_median": product.get("metric_value"),
                "reader_median_name": product.get("metric_name"),
                "reader_median_units": metric_units if product.get("metric_value") is not None else None,
                "goff_range_median_mm": metric_number(stats.get("range_median_mm")),
                "goff_azimuth_median_mm": metric_number(stats.get("azimuth_median_mm")),
                "goff_detect_floor_mm_day": metric_number(stats.get("detect_floor_mm_day")),
                "goff_range_velocity_mm_day": metric_number(stats.get("range_velocity_mm_day")),
                "mean_coherence": metric_number(stats.get("mean_coherence")),
                "mean_correlation": metric_number(stats.get("mean_correlation")),
                "target_measurement_status": target_status,
                "target_local_los_median_mm": metric_number(target_metrics.get("target_local_los_median_mm")) if target_status == "MEASURED" else None,
                "target_local_range_median_mm": metric_number(target_metrics.get("target_local_range_median_mm")) if target_status == "MEASURED" else None,
                "target_local_azimuth_median_mm": metric_number(target_metrics.get("target_local_azimuth_median_mm")) if target_status == "MEASURED" else None,
                "target_mean_coherence": metric_number(target_metrics.get("mean_coherence")) if target_status == "MEASURED" else None,
                "target_mean_correlation": metric_number(target_metrics.get("mean_correlation")) if target_status == "MEASURED" else None,
                "target_local_floor_status": floor_status,
                "target_local_floor_mm_day": metric_number(floor_metrics.get("local_floor_mm_day")) if floor_status == "MEASURED" else None,
                "target_local_floor_ci_lo_mm_day": metric_number(floor_metrics.get("local_floor_ci_lo_mm_day")) if floor_status == "MEASURED" else None,
                "target_local_floor_ci_hi_mm_day": metric_number(floor_metrics.get("local_floor_ci_hi_mm_day")) if floor_status == "MEASURED" else None,
            },
        })
    limitations = [
        "Structural/provenance PASS is not independent geophysical validation.",
        "Pairwise LOS displacement is not automatically cumulative, vertical, or 3-D ground motion.",
        "Playback shows actual acquisition pairs and does not interpolate missing observations or forecast movement.",
    ]
    diagnostics = summary.get("science_diagnostics") or {}
    pixel_stack_explanation = build_pixel_stack_explanation(root, diagnostics)
    stack = diagnostics.get("pixel_stack") or {}
    if stack:
        limitations.append(f"Pixel-stack status: {stack.get('status')}; inspect saved logs and diagnostics before interpreting a trend.")
    candidate = diagnostics.get("candidate_checks") or {}
    if str(candidate.get("status", "")).startswith("SKIPPED"):
        limitations.append("The legacy named-AOI candidate_check.py was skipped for this arbitrary WKT polygon; the separate target-free AOI spatial screen reports unconfirmed candidate regions and does not validate movement or hazard.")
    # Retain the pre-existing GOFF-only target-free AOI screen alongside the
    # newer cross-family candidate report. They use different methods and are
    # displayed as separate evidence layers; neither is promoted to movement.
    aoi_wide_screen = summary.get("aoi_wide_displacement_screen") or {}
    candidate_feature_collection = {"type": "FeatureCollection", "features": []}
    candidate_path_text = str(aoi_wide_screen.get("candidates_geojson") or "").strip()
    if candidate_path_text:
        try:
            candidate_path = safe_path(root, candidate_path_text)
            if candidate_path.is_file():
                candidate_feature_collection = read_json(candidate_path, required=False)
                if candidate_feature_collection.get("type") != "FeatureCollection":
                    raise ValueError("AOI-wide candidate GeoJSON is not a FeatureCollection")
                if not isinstance(candidate_feature_collection.get("features"), list):
                    raise ValueError("AOI-wide candidate GeoJSON has no features list")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            aoi_wide_screen = dict(aoi_wide_screen)
            aoi_wide_screen["candidate_geojson_load_error"] = type(exc).__name__ + ":" + str(exc)[:200]
            candidate_feature_collection = {"type": "FeatureCollection", "features": []}
    aoi_wide_screen_for_manifest = dict(aoi_wide_screen)
    aoi_wide_screen_for_manifest["candidate_feature_collection"] = candidate_feature_collection
    legacy_gunw_stack = aoi_wide_screen_for_manifest.get("gunw_per_pixel_stack") or {}
    strict_gunw_stack = dict(legacy_gunw_stack)
    strict_gunw_stack["legacy_reported_status"] = legacy_gunw_stack.get("status", "NOT_REPORTED")
    strict_gunw_stack["status"] = pixel_stack_explanation.get("status", strict_gunw_stack["legacy_reported_status"])
    strict_gunw_stack["interpretation"] = pixel_stack_explanation.get(
        "interpretation", strict_gunw_stack.get("interpretation", "No strict GUNW pixel-stack re-audit was reported.")
    )
    strict_gunw_stack["legacy_status_superseded"] = (
        strict_gunw_stack["legacy_reported_status"] != strict_gunw_stack["status"]
    )
    aoi_wide_screen_for_manifest["gunw_per_pixel_stack"] = strict_gunw_stack

    manifest = {
        "schema_version": SCHEMA, "run": {
            "github_run_id": summary.get("run_id"), "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "aoi_wkt_sha256": summary.get("aoi_wkt_sha256"), "science_commit": summary.get("science_commit"),
            "orchestration_commit": summary.get("orchestration_sha"), "workflow_commit": summary.get("dispatcher_workflow_sha"),
        },
        "validation": {"processing_status": summary.get("status", "UNKNOWN"), "visual_assets_status": "PASS" if (public_layers or derived_layers) else "NO_RENDERABLE_LAYERS",
                       "independent_geophysical_validation": "NOT_PERFORMED", "products_expected": summary.get("products_expected"),
                       "products_validated": summary.get("products_validated")},
        "aoi": feature, "aoi_bbox": bbox,
        "time_window": {"start_date": summary.get("date_start"), "end_date": summary.get("date_end"),
                        "date_basis": summary.get("date_basis"), "date_filter_mode": summary.get("date_filter_mode")},
        "observations": observations, "layers": public_layers, "derived_layers": derived_layers,
        "derived_layer_errors": derived_layer_errors,
        "aoi_relative_pixel_timeseries": pixel_report,
        "pixel_stack_diagnostic": pixel_stack_explanation,
        "science_limitations": limitations,
        "science_pipeline": summary.get("science_pipeline") or {},
        "site_context": summary.get("site_context") or {},
        "common_reference_timeseries": summary.get("common_reference_timeseries") or {},
        "goff_common_reference_timeseries": summary.get("goff_common_reference_timeseries") or {},
        "aoi_displacement_candidates": summary.get("aoi_displacement_candidates") or {},
        "aoi_wide_displacement_screen": aoi_wide_screen_for_manifest,
        "display_policy": "Find Displacements is target-free. Actual pair playback and AOI-wide derived layers are separate; GOFF offset anomalies are not ground velocity, GUNW velocity is relative LOS, and no extrapolation or hazard inference is added.",
         "target_free_analysis": True,
    }
    webroot.mkdir(parents=True, exist_ok=True)
    (webroot / "aoi.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}, indent=2) + "\n", encoding="utf-8")
    selected_place = (summary.get("site_context") or {}).get("place") or {}
    site_features = []
    try:
        site_lat, site_lon = float(selected_place.get("latitude")), float(selected_place.get("longitude"))
        if (math.isfinite(site_lat) and math.isfinite(site_lon)
                and -90 <= site_lat <= 90 and -180 <= site_lon <= 180):
            site_features.append({
                "type": "Feature",
                "properties": {
                    "name": str(selected_place.get("name") or "Selected place")[:200],
                    "inside_aoi": selected_place.get("inside_aoi"),
                    "role": "map-selected-place-context_not_hazard_evidence",
                },
                "geometry": {"type": "Point", "coordinates": [site_lon, site_lat]},
            })
    except (TypeError, ValueError, OverflowError):
        pass
    target_context = (summary.get("site_context") or {}).get("measurement_target") or {}
    if target_context.get("status") == "IN_AOI_TARGET_CAPTURED":
        try:
            target_lat = float(target_context.get("latitude"))
            target_lon = float(target_context.get("longitude"))
            if (math.isfinite(target_lat) and math.isfinite(target_lon)
                    and -90 <= target_lat <= 90 and -180 <= target_lon <= 180):
                site_features.append({
                    "type": "Feature",
                    "properties": {
                        "name": "Measurement target",
                        "inside_aoi": True,
                        "role": "in_aoi_pair_local_measurement_target_not_stable_reference",
                    },
                    "geometry": {"type": "Point", "coordinates": [target_lon, target_lat]},
                })
        except (TypeError, ValueError, OverflowError):
            pass
    (webroot / "site.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": site_features,
        "note": "Place context and measurement target are separate; neither marker is hazard evidence or a stable-ground reference.",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (webroot / "timeline.json").write_text(json.dumps({"schema_version": SCHEMA, "observations": [
        {key: obs.get(key) for key in ("id", "product_type", "reference_date", "secondary_date", "track", "look_direction", "maturity", "valid_pixels", "layers")} for obs in observations
    ], "policy": "pair-aware; no synthetic intermediate observations"}, indent=2) + "\n", encoding="utf-8")
    (webroot / "metrics.json").write_text(json.dumps({"schema_version": SCHEMA, "products": [
        {"id": obs["id"], "product_type": obs["product_type"], "track": obs["track"], "secondary_date": obs["secondary_date"],
         "valid_pixels": obs["valid_pixels"], "metrics": obs["metrics"]} for obs in observations
    ], "limitations": limitations}, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (webroot / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    image_data = {}
    for layer in public_layers:
        image = safe_path(webroot, layer["preview_asset"])
        image_data[layer["id"]] = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    derived_image_data = {}
    for layer in derived_layers:
        image = safe_path(webroot, layer["preview_asset"])
        derived_image_data[layer["id"]] = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    manifest_blob = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    manifest_blob = manifest_blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    (webroot / "dashboard-data.js").write_text(
        "window.SARGUARDIAN_DASHBOARD=" + manifest_blob + ";\nwindow.SARGUARDIAN_LAYER_DATA=" +
        json.dumps(image_data, separators=(",", ":"), allow_nan=False) + ";\nwindow.SARGUARDIAN_DERIVED_LAYER_DATA=" + json.dumps(derived_image_data, separators=(",", ":"), allow_nan=False) + ";\n", encoding="utf-8"
    )

    stac_root = webroot / "stac"
    stac_items = stac_root / "items"
    stac_items.mkdir(parents=True, exist_ok=True)
    item_links = []
    for obs in observations:
        product = next(p for p in products if p.get("id") == obs["id"])
        date = str(obs.get("secondary_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"Invalid secondary date for STAC item {obs['id']}")
        assets = {}
        exports = product.get("exports") or []
        if exports and exports[0].get("relative_path"):
            assets["native_raster"] = {"href": "../../../" + str(exports[0]["relative_path"]), "type": "image/tiff; application=geotiff", "roles": ["data"]}
        for idx, layer in enumerate(l for l in public_layers if l["observation_id"] == obs["id"]):
            assets["preview_band_" + str(layer["band"]) + "_" + str(idx + 1)] = {"href": "../../" + layer["preview_asset"], "type": "image/png", "roles": ["overview"]}
        if obs.get("quicklook"):
            assets["quicklook"] = {"href": "../../../" + str(obs["quicklook"]), "type": "image/png", "roles": ["overview"]}
        item = {
            "stac_version": "1.1.0", "type": "Feature", "id": str(obs["id"]), "geometry": geometry, "bbox": bbox,
            "properties": {"datetime": date + "T00:00:00Z", "start_datetime": str(obs.get("reference_date")) + "T00:00:00Z",
                           "end_datetime": date + "T00:00:00Z", "platform": "NISAR", "instruments": ["L-SAR"],
                           "sarguardian:product_type": obs.get("product_type"), "sarguardian:track": obs.get("track"),
                           "sarguardian:crid": obs.get("crid"), "sarguardian:maturity": obs.get("maturity"),
                           "sarguardian:source_sha256": obs.get("source_sha256"), "sarguardian:validation_scope": obs.get("validation_scope")},
            "links": [{"rel": "self", "href": str(obs["id"]) + ".json"}, {"rel": "parent", "href": "../collection.json"}, {"rel": "root", "href": "../catalog.json"}],
            "assets": assets,
        }
        (stac_items / (str(obs["id"]) + ".json")).write_text(json.dumps(item, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        item_links.append({"rel": "item", "href": "items/" + str(obs["id"]) + ".json", "type": "application/geo+json"})
    dates = [str(o.get("secondary_date")) for o in observations if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(o.get("secondary_date") or ""))]
    date_start = str(summary.get("date_start") or (min(dates) if dates else "2026-01-01"))
    date_end = str(summary.get("date_end") or (max(dates) if dates else "2026-12-31"))
    collection = {"stac_version": "1.1.0", "type": "Collection", "id": "sarguardian-" + str(summary.get("run_id", "run")),
                  "description": "AOI-clipped NISAR acquisition-pair exports; pairwise values are not automatically a common-reference time series.",
                  "license": "other",
                  "sarguardian:license_note": "Official NASA/NISAR data-use guidance is linked below for source context only. Verify the exact source product metadata and any non-NASA/third-party terms before redistribution; this package does not relicense source data or grant rights to third-party content.",
                  "providers": [
                      {"name": "NASA / ISRO NISAR mission", "roles": ["producer"], "url": "https://nisar-docs.asf.alaska.edu/"},
                      {"name": "Alaska Satellite Facility DAAC", "roles": ["host"], "url": "https://asf.alaska.edu/"},
                  ],
                  "extent": {"spatial": {"bbox": [bbox]}, "temporal": {"interval": [[date_start + "T00:00:00Z", date_end + "T23:59:59Z"]]}},
                  "links": [
                      {"rel": "self", "href": "collection.json"},
                      {"rel": "root", "href": "catalog.json"},
                      {"rel": "items", "href": "items/"},
                      {"rel": "license", "href": "https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy", "type": "text/html", "title": "NASA Earthdata data-use and citation guidance"},
                      {"rel": "license", "href": "https://nisar-docs.asf.alaska.edu/data-use-citation-guidance/", "type": "text/html", "title": "NISAR data-use and citation guidance"},
                  ] + item_links}
    (stac_root / "collection.json").write_text(json.dumps(collection, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    catalog = {"stac_version": "1.1.0", "type": "Catalog", "id": "sarguardian-" + str(summary.get("run_id", "run")),
               "description": "SARGuardian AOI-scoped NISAR products and derived previews.",
               "links": [{"rel": "self", "href": "catalog.json"}, {"rel": "child", "href": "collection.json", "type": "application/json"}]}
    (stac_root / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    write_viewer(webroot / "index.html")
    report_html = root / "index.html"
    if report_html.is_file():
        content = report_html.read_text(encoding="utf-8")
        if "web-dashboard/index.html" not in content:
            link = '<p class="interactive-dashboard-link"><a href="web-dashboard/index.html">Open interactive geospatial map &amp; observation timeline ↗</a></p>'
            content = re.sub(r"(<main(?:\s[^>]*)?>)", lambda m: m.group(1) + link, content, count=1, flags=re.I)
            report_html.write_text(content, encoding="utf-8")

    renderable_layer_count = len(public_layers) + len(derived_layers)
    receipt = {"schema_version": SCHEMA, "status": ("PASS" if renderable_layer_count and not derived_layer_errors else "PARTIAL"), "generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "manifest": "web-dashboard/manifest.json", "viewer": "web-dashboard/index.html",
               "viewer_data": "web-dashboard/dashboard-data.js", "aoi_geojson": "web-dashboard/aoi.geojson",
               "timeline": "web-dashboard/timeline.json", "metrics": "web-dashboard/metrics.json",
               "stac_catalog": "web-dashboard/stac/catalog.json", "observations": len(observations),
               "layers": len(public_layers), "derived_layers": len(derived_layers),
                "renderable_layers": renderable_layer_count,
               "aoi_relative_pixel_timeseries_status": pixel_report.get("status", "NOT_REPORTED"),
                "aoi_candidate_features": int((summary.get("aoi_displacement_candidates") or {}).get("candidate_features") or 0),
                "legacy_goff_candidate_features": int((summary.get("aoi_wide_displacement_screen") or {}).get("candidate_count") or 0),
               "derived_layer_errors": len(derived_layer_errors), "source_geotiffs_unchanged": True}
    (root / "web-dashboard-build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard-root", required=True, type=Path)
    result = prepare_web_dashboard(parser.parse_args().dashboard_root)
    print("WEB_DASHBOARD_STATUS=" + result["status"])
    print("WEB_DASHBOARD_OBSERVATIONS=" + str(result["observations"]))
    print("WEB_DASHBOARD_LAYERS=" + str(result["layers"]))
    print("WEB_DASHBOARD_VIEWER=" + result["viewer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
