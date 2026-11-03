#!/usr/bin/env python3
"""Run one owner-requested, AOI-specific NISAR GCOV RiverShift job.

The worker never substitutes a built-in AOI, invents daily observations, or
marks a result verified. It processes comparable NISAR acquisition dates only
and returns checksum-bound provisional layers through the signed job callback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import numpy as np
import rasterio
import requests
from pyproj import CRS, Transformer
from rasterio.warp import Resampling, reproject
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
MAX_SELECTED_DATES = 12
MAX_SELECTED_GRANULES = 24
MAX_GRANULES_PER_DATE = 4
MAX_WEB_PREVIEW_BYTES = 3_500_000

from drive_upload_adapter import DriveClient, DriveUploadError, load_drive_config, upload_validated_results  # noqa: E402


class WorkerFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise WorkerFailure("WORKER_CONFIGURATION_MISSING", f"Required worker setting {name} is missing.")
    return value


def _date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise WorkerFailure("INVALID_REQUEST", f"{field} must use YYYY-MM-DD format.") from None


def _metric_crs(aoi) -> CRS:
    centroid = aoi.centroid
    zone = int(math.floor((centroid.x + 180.0) / 6.0)) + 1
    zone = max(1, min(60, zone))
    return CRS.from_epsg((32600 if centroid.y >= 0 else 32700) + zone)


def _feature_geometry(product: dict[str, Any]):
    value = product.get("footprint")
    if isinstance(value, dict) and value.get("type") == "Feature":
        value = value.get("geometry")
    try:
        geometry = shape(value) if isinstance(value, dict) else None
    except Exception:
        return None
    return geometry if geometry is not None and geometry.is_valid and not geometry.is_empty else None


def _product_date(product: dict[str, Any]) -> str | None:
    value = product.get("acquisition_start_utc") or product.get("start_time_utc")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def select_date_window(
    date_rows: list[dict[str, Any]], event_date: date, maximum_dates: int = MAX_SELECTED_DATES,
) -> tuple[list[str], dict[str, str]]:
    """Choose a real observation near the event with one earlier and two later dates."""
    by_date = {
        str(row.get("acquisition_date")): row
        for row in date_rows
        if row.get("passes_coverage_gate") is True
        and isinstance(row.get("acquisition_date"), str)
        and row.get("granule_names")
    }
    dates = sorted(by_date)
    if len(dates) < 4:
        raise WorkerFailure(
            "INSUFFICIENT_COMPARABLE_ACQUISITIONS",
            "This AOI and date window need at least four comparable, footprint-qualified NISAR acquisition dates.",
        )
    candidates = []
    for index in range(1, len(dates) - 2):
        observed = date.fromisoformat(dates[index])
        candidates.append((abs((observed - event_date).days), observed < event_date, index))
    _, _, event_index = min(candidates)
    anchors = {dates[event_index - 1], dates[event_index], dates[event_index + 1], dates[event_index + 2]}
    selected = set(anchors)
    while len(selected) < min(maximum_dates, len(dates)):
        remaining = [value for value in dates if value not in selected]
        if not remaining:
            break
        next_date = max(
            remaining,
            key=lambda value: (
                min(abs((date.fromisoformat(value) - date.fromisoformat(chosen)).days) for chosen in selected),
                value,
            ),
        )
        selected.add(next_date)
    sequence = sorted(selected)
    quartet = dates[event_index - 1:event_index + 3]
    return sequence, {
        "before": quartet[0], "event_observation": quartet[1],
        "post_one": quartet[2], "post_two": quartet[3],
    }


def select_covering_granules(
    aoi,
    products: list[dict[str, Any]],
    granule_names: list[str],
    metric_crs: CRS,
    minimum_coverage_percent: float = 90.0,
) -> list[dict[str, Any]]:
    """Greedily select the fewest footprint scenes needed to cover this AOI."""
    project = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True).transform
    aoi_metric = transform(project, aoi)
    candidates = []
    for name in sorted(set(granule_names)):
        row = next((item for item in products if item.get("granule_name") == name), None)
        geometry = _feature_geometry(row or {})
        if row is None or geometry is None:
            continue
        metric_geometry = transform(project, geometry)
        overlap = metric_geometry.intersection(aoi_metric)
        if not overlap.is_empty and overlap.area > 0:
            candidates.append((row, overlap))
    chosen: list[dict[str, Any]] = []
    coverage = 0.0
    covered = None
    while candidates and coverage < minimum_coverage_percent:
        ranked = []
        for row, geometry in candidates:
            new_cover = geometry if covered is None else covered.union(geometry)
            gain = new_cover.area - (covered.area if covered is not None else 0.0)
            ranked.append((gain, str(row.get("granule_name", "")), row, geometry))
        gain, _, row, geometry = max(ranked, key=lambda item: (item[0], item[1]))
        candidates = [(other, footprint) for other, footprint in candidates if other is not row]
        if gain <= 0:
            break
        chosen.append(row)
        covered = geometry if covered is None else covered.union(geometry)
        coverage = covered.intersection(aoi_metric).area / aoi_metric.area * 100.0
        if len(chosen) >= MAX_GRANULES_PER_DATE and coverage < minimum_coverage_percent:
            break
    if coverage < minimum_coverage_percent:
        raise WorkerFailure(
            "AOI_RASTER_COVERAGE_INSUFFICIENT",
            f"Selected acquisition scenes cover {coverage:.1f}% of the AOI; at least {minimum_coverage_percent:.0f}% is required.",
        )
    return chosen


class JobCallbacks:
    def __init__(self, job_id: str, fingerprint: str, callback_base: str) -> None:
        self.job_id = str(UUID(job_id))
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise WorkerFailure("INVALID_REQUEST", "Request fingerprint is invalid.")
        self.fingerprint = fingerprint
        self.secret = _required_env("RIVERSHIFT_CALLBACK_SECRET")
        parsed = urlsplit(callback_base)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise WorkerFailure("WORKER_CONFIGURATION_INVALID", "Callback URL must be a public HTTPS API base URL.")
        base = callback_base.rstrip("/")
        self.endpoint = f"{base}/api/river-shift/jobs/{self.job_id}/callback"
        self.sequence = 0
        self.stage = "worker_startup"
        self.run_id = _required_env("GITHUB_RUN_ID")
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        repository = _required_env("GITHUB_REPOSITORY")
        self.run_url = f"{server}/{repository}/actions/runs/{self.run_id}"

    def send(
        self,
        state: str,
        stage: str,
        *,
        result_summary: dict[str, Any] | None = None,
        artifact_manifest: list[dict[str, Any]] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        sequence = self.sequence + 1
        self.stage = stage
        payload = {
            "job_id": self.job_id,
            "request_fingerprint": self.fingerprint,
            "state": state,
            "sequence": sequence,
            "stage": stage,
            "github_run_id": self.run_id,
            "github_run_url": self.run_url,
            "error_code": error_code,
            "error_message": error_message,
            "result_summary": result_summary,
            "artifact_manifest": artifact_manifest,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        try:
            response = requests.post(
                self.endpoint,
                data=body,
                headers={"Content-Type": "application/json", "X-SARGuardian-Signature": f"sha256={signature}"},
                timeout=(15, 45),
            )
            response.raise_for_status()
        except requests.RequestException:
            raise WorkerFailure("CALLBACK_REJECTED", "SARGuardian did not accept a signed processing update.") from None
        self.sequence = sequence


def run_step(stage: str, command: list[str]) -> None:
    try:
        subprocess.run(command, cwd=TOOLS, check=True)
    except subprocess.CalledProcessError as exc:
        raise WorkerFailure(
            "SCIENCE_STEP_FAILED",
            f"The {stage.replace('_', ' ')} step failed with exit code {exc.returncode}; inspect the processing run logs.",
        ) from None


def _mosaic_date_rasters(paths: list[Path], destination: Path) -> Path:
    if len(paths) == 1:
        return paths[0]
    vrt = destination.with_suffix(".vrt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["gdalbuildvrt", "-overwrite", "-resolution", "highest", "-addalpha", str(vrt), *map(str, paths)]
    try:
        subprocess.run(command, cwd=TOOLS, check=True)
        subprocess.run(
            ["gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=FLOATING_POINT", str(vrt), str(destination)],
            cwd=TOOLS, check=True,
        )
    except subprocess.CalledProcessError:
        raise WorkerFailure("RASTER_MOSAIC_FAILED", "Could not combine the selected same-date scene rasters safely.") from None
    finally:
        vrt.unlink(missing_ok=True)
    source_metadata = json.loads(paths[0].with_suffix(".metadata.json").read_text(encoding="utf-8"))
    source_names = [json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))["source_granule_name"] for path in paths]
    source_hashes = [json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))["source_product_sha256"] for path in paths]
    source_metadata.update({
        "source_granule_name": "+".join(source_names),
        "source_granule_names": source_names,
        "source_product_sha256": hashlib.sha256("\n".join(sorted(source_hashes)).encode("ascii")).hexdigest(),
        "output_cog": str(destination.resolve()),
        "output_cog_sha256": sha256_file(destination),
        "mosaic_method": "GDAL VRT; first valid source pixel in deterministic granule-name order",
    })
    destination.with_suffix(".metadata.json").write_text(json.dumps(source_metadata, indent=2), encoding="utf-8")
    return destination


def _co_register(path: Path, reference_path: Path, *, is_reference: bool) -> Path:
    if is_reference:
        return path
    destination = path.with_name(path.stem + "_aligned.tif")
    sidecar_path = path.with_suffix(".metadata.json")
    with rasterio.open(reference_path) as reference, rasterio.open(path) as source:
        if reference.crs is None or source.crs is None or not reference.crs.is_projected:
            raise WorkerFailure("RASTER_GRID_INVALID", "Selected GCOV scenes need a projected metric CRS.")
        profile = reference.profile.copy()
        profile.update(driver="GTiff", count=1, dtype="float32", nodata=np.nan, tiled=True, compress="DEFLATE")
        source_values = source.read(1).astype(np.float32)
        source_valid = (source.dataset_mask() > 0) & np.isfinite(source_values)
        if source.nodata is not None and not math.isnan(float(source.nodata)):
            source_valid &= source_values != source.nodata
        source_values[~source_valid] = np.nan
        aligned = np.full((reference.height, reference.width), np.nan, dtype=np.float32)
        aligned_valid = np.zeros((reference.height, reference.width), dtype=np.uint8)
        reproject(
            source=source_values, destination=aligned,
            src_transform=source.transform, src_crs=source.crs, src_nodata=np.nan,
            dst_transform=reference.transform, dst_crs=reference.crs, dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )
        reproject(
            source=source_valid.astype(np.uint8), destination=aligned_valid,
            src_transform=source.transform, src_crs=source.crs, src_nodata=0,
            dst_transform=reference.transform, dst_crs=reference.crs, dst_nodata=0,
            resampling=Resampling.nearest,
        )
        aligned_valid = (aligned_valid > 0) & np.isfinite(aligned)
        with rasterio.open(destination, "w", **profile) as target:
            target.write(aligned, 1)
            target.write_mask(aligned_valid.astype(np.uint8) * 255)
    metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    metadata.update({"output_cog": str(destination.resolve()), "output_cog_sha256": sha256_file(destination),
                     "co_registration": "nearest-neighbour to first selected observed-date grid"})
    destination.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return destination


def _to_metric_transformer(aoi, raster_crs: CRS):
    source = CRS.from_epsg(4326)
    if not raster_crs.is_projected:
        raise WorkerFailure("RASTER_GRID_INVALID", "The selected NISAR product uses a non-projected analysis grid.")
    return Transformer.from_crs(source, raster_crs, always_xy=True).transform


def write_web_preview(
    source_path: Path,
    destination: Path,
    project,
    unproject,
    pixel_size_m: float,
    *,
    max_bytes: int = MAX_WEB_PREVIEW_BYTES,
) -> dict[str, Any]:
    """Create a topology-preserving, explicitly non-measurement map preview."""
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        raw_features = payload.get("features")
        if payload.get("type") != "FeatureCollection" or not isinstance(raw_features, list):
            raise ValueError("not a GeoJSON FeatureCollection")
        metric_features = []
        for feature in raw_features:
            geometry = shape(feature.get("geometry"))
            metric = transform(project, geometry)
            metric_features.append((feature, metric))
    except Exception:
        raise WorkerFailure("PREVIEW_GENERATION_FAILED", f"Could not prepare a map preview for {source_path.name}.") from None

    pixel_area = max(float(pixel_size_m) ** 2, 1.0)
    minimum_area = 4.0 * pixel_area
    tolerance = max(float(pixel_size_m) * 0.5, 0.5)
    while tolerance <= max(float(pixel_size_m) * 64, 64):
        features = []
        for feature, metric in metric_features:
            if metric.area < minimum_area:
                continue
            simplified = metric.simplify(tolerance, preserve_topology=True)
            if simplified.is_empty:
                continue
            features.append({
                "type": "Feature",
                "properties": dict(feature.get("properties") or {}),
                "geometry": mapping(transform(unproject, simplified)),
            })
        preview = {
            "type": "FeatureCollection",
            "name": destination.stem,
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "river_shift_preview": {
                "status": "DISPLAY_ONLY",
                "simplification_tolerance_m": round(tolerance, 3),
                "minimum_polygon_area_m2": round(minimum_area, 3),
                "warning": "Small patches may be omitted and boundaries simplified; use the full private GeoJSON for detailed GIS review. Areas are calculated from the full-resolution analysis, not this preview.",
            },
            "features": features,
        }
        encoded = json.dumps(preview, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) <= max_bytes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(encoded)
            return preview
        tolerance *= 2.0
    raise WorkerFailure(
        "PREVIEW_TOO_LARGE",
        f"The selected AOI produces a web map preview larger than {max_bytes} bytes after safe simplification; narrow the AOI before processing.",
    )


def create_web_previews(
    work_dir: Path,
    time_dir: Path,
    flood_dir: Path,
    morphology_dir: Path,
    reference_raster: Path,
    time_report_path: Path,
) -> list[dict[str, Any]]:
    map_dir = work_dir / "outputs" / "map"
    with rasterio.open(reference_raster) as source:
        if source.crs is None or not source.crs.is_projected:
            raise WorkerFailure("RASTER_GRID_INVALID", "Map previews need a projected NISAR raster grid.")
        raster_crs = CRS.from_user_input(source.crs)
        pixel_size = max(abs(source.transform.a), abs(source.transform.e))
    project = Transformer.from_crs("EPSG:4326", raster_crs, always_xy=True).transform
    unproject = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True).transform
    layers: list[dict[str, Any]] = []
    sources = [
        (morphology_dir / "erosion_candidates.geojson", map_dir / "erosion_candidates_preview.geojson", "erosion"),
        (morphology_dir / "deposition_candidates.geojson", map_dir / "deposition_candidates_preview.geojson", "deposition"),
        (flood_dir / "newly_water_covered.geojson", map_dir / "newly_water_covered_preview.geojson", "new_water"),
    ]
    change_features = []
    for source_path, destination, layer_type in sources:
        preview = write_web_preview(source_path, destination, project, unproject, pixel_size, max_bytes=1_100_000)
        layers.append({"path": destination.relative_to(work_dir).as_posix(), "sha256": sha256_file(destination)})
        for feature in preview["features"]:
            properties = dict(feature.get("properties") or {})
            properties["river_shift_layer"] = layer_type
            change_features.append({**feature, "properties": properties})
    combined_path = map_dir / "river_change_candidates_preview.geojson"
    combined = {
        "type": "FeatureCollection",
        "name": combined_path.stem,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "river_shift_preview": {
            "status": "DISPLAY_ONLY",
            "warning": "Red: persistent erosion candidate; green: persistent deposition candidate; blue: newly water-covered candidate. Boundaries are simplified and small patches may be omitted.",
        },
        "features": change_features,
    }
    encoded_combined = json.dumps(combined, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded_combined) > MAX_WEB_PREVIEW_BYTES:
        raise WorkerFailure("PREVIEW_TOO_LARGE", "The combined AOI change map is too large for the web preview; narrow the AOI.")
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined_path.write_bytes(encoded_combined)
    layers.append({"path": combined_path.relative_to(work_dir).as_posix(), "sha256": sha256_file(combined_path)})

    report = json.loads(time_report_path.read_text(encoding="utf-8"))
    for frame in report.get("time_series", []):
        observed_date = frame.get("date")
        if not isinstance(observed_date, str):
            raise WorkerFailure("PREVIEW_GENERATION_FAILED", "An observed-date time-series frame has an invalid date.")
        source_path = time_dir / str(frame.get("water_geojson", ""))
        preview_path = map_dir / f"water_{observed_date}_preview.geojson"
        write_web_preview(source_path, preview_path, project, unproject, pixel_size)
        layers.append({"path": preview_path.relative_to(work_dir).as_posix(), "sha256": sha256_file(preview_path)})
        frame["water_geojson"] = preview_path.name
        frame["water_geojson_sha256"] = sha256_file(preview_path)
    report.setdefault("quality", {}).setdefault("warnings", []).append(
        "The web playback uses display-only simplified GeoJSON. Small patches may be omitted; no daily interpolation is performed."
    )
    time_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return layers


def _read_input() -> dict[str, Any]:
    job_id = _required_env("RIVERSHIFT_JOB_ID")
    try:
        UUID(job_id)
    except ValueError:
        raise WorkerFailure("INVALID_REQUEST", "RiverShift job ID is invalid.") from None
    fingerprint = _required_env("RIVERSHIFT_REQUEST_FINGERPRINT")
    aoi_wkt = _required_env("RIVERSHIFT_AOI_WKT")
    try:
        aoi = shapely_wkt.loads(aoi_wkt)
    except Exception:
        raise WorkerFailure("INVALID_REQUEST", "The requested AOI is not valid WGS84 polygon text.") from None
    if aoi.geom_type != "Polygon" or aoi.is_empty or not aoi.is_valid:
        raise WorkerFailure("INVALID_REQUEST", "The requested AOI must be one valid WGS84 polygon.")
    start_date = _date(_required_env("RIVERSHIFT_START_DATE"), "start_date")
    end_date = _date(_required_env("RIVERSHIFT_END_DATE"), "end_date")
    event_date = _date(_required_env("RIVERSHIFT_EVENT_DATE"), "event_date")
    if end_date < start_date or (end_date - start_date).days > 366 or not start_date <= event_date <= end_date:
        raise WorkerFailure("INVALID_REQUEST", "The event date and observation window are not a valid selected range.")
    maturity = _required_env("RIVERSHIFT_MATURITY").upper()
    frequency = _required_env("RIVERSHIFT_FREQUENCY")
    term = _required_env("RIVERSHIFT_COVARIANCE_TERM").upper()
    threshold_method = _required_env("RIVERSHIFT_THRESHOLD_METHOD").lower()
    if maturity not in {"PROVISIONAL", "BETA"} or frequency not in {"frequencyA", "frequencyB"}:
        raise WorkerFailure("INVALID_REQUEST", "Choose one supported NISAR maturity and frequency.")
    if term not in {"HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"}:
        raise WorkerFailure("INVALID_REQUEST", "The selected covariance term is not supported.")
    if threshold_method not in {"otsu", "manual"}:
        raise WorkerFailure("INVALID_REQUEST", "The common threshold method is not supported.")
    threshold_text = os.environ.get("RIVERSHIFT_THRESHOLD_DB", "").strip()
    threshold_db = None
    if threshold_method == "manual":
        try:
            threshold_db = float(threshold_text)
        except ValueError:
            raise WorkerFailure("INVALID_REQUEST", "Manual threshold mode needs one finite threshold in dB.") from None
        if not math.isfinite(threshold_db) or not -60 <= threshold_db <= 0:
            raise WorkerFailure("INVALID_REQUEST", "Manual threshold must be between -60 and 0 dB.")
    elif threshold_text:
        raise WorkerFailure("INVALID_REQUEST", "Otsu mode cannot include a manual threshold value.")
    try:
        granules = json.loads(_required_env("RIVERSHIFT_GRANULE_NAMES_JSON"))
    except json.JSONDecodeError:
        raise WorkerFailure("INVALID_REQUEST", "The selected exact granule list is invalid JSON.") from None
    if (not isinstance(granules, list) or not granules or len(granules) > 100
            or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{10,250}", name) for name in granules)):
        raise WorkerFailure("INVALID_REQUEST", "The exact NISAR granule list is invalid or exceeds the request limit.")
    return {
        "job_id": job_id, "fingerprint": fingerprint, "aoi_wkt": aoi_wkt, "aoi": aoi,
        "start_date": start_date, "end_date": end_date, "event_date": event_date,
        "maturity": maturity, "frequency": frequency, "term": term,
        "threshold_method": threshold_method, "threshold_db": threshold_db,
        "granule_names": sorted(set(granules)),
    }


def _configure_earthdata_credentials() -> None:
    """Use an Earthdata bearer token or create a private runner-local netrc."""
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if token:
        return
    username = os.environ.get("EARTHDATA_USERNAME", "").strip()
    password = os.environ.get("EARTHDATA_PASSWORD", "")
    if not username or not password:
        raise WorkerFailure(
            "EARTHDATA_CREDENTIALS_MISSING",
            "Configure EARTHDATA_TOKEN or both EARTHDATA_USERNAME and EARTHDATA_PASSWORD.",
        )
    if any(character in username + password for character in ("\n", "\r", "\0")):
        raise WorkerFailure("EARTHDATA_CREDENTIALS_INVALID", "Earthdata credentials contain unsupported control characters.")

    def netrc_value(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    home = Path(os.environ.get("HOME") or str(Path.home())).resolve()
    home.mkdir(parents=True, exist_ok=True)
    netrc_path = home / ".netrc"
    netrc_path.write_text(
        "machine urs.earthdata.nasa.gov login "
        + netrc_value(username)
        + " password "
        + netrc_value(password)
        + "\n",
        encoding="utf-8",
    )
    os.chmod(netrc_path, 0o600)

def _ensure_credentials() -> None:
    _configure_earthdata_credentials()
    try:
        drive = DriveClient(load_drive_config())
        drive.require_private_folder(drive.config.parent_folder_id)
    except DriveUploadError:
        raise WorkerFailure("PRIVATE_STORAGE_UNAVAILABLE", "Private Google Drive result storage is not ready.") from None


def _copy_result_files(source_dirs: list[tuple[str, Path]], output_root: Path) -> list[dict[str, str]]:
    output_root.mkdir(parents=True, exist_ok=True)
    inventory = []
    for label, source_dir in source_dirs:
        for path in sorted(source_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".json", ".geojson", ".tif"}:
                continue
            destination = output_root / label / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            inventory.append({"path": destination.relative_to(output_root.parent).as_posix(), "sha256": sha256_file(destination)})
    return inventory


def _build_manifest(work_dir: Path, outputs: list[dict[str, str]], selection: dict[str, Any]) -> Path:
    manifest_path = work_dir / "result-manifest.json"
    manifest = {
        "schema_version": 1,
        "status": "succeeded",
        "job_id": os.environ["RIVERSHIFT_JOB_ID"],
        "release_status": "PROVISIONAL",
        "independent_validation_status": "PENDING",
        "event_date_status": "USER_SUPPLIED_NOT_INDEPENDENTLY_CONFIRMED",
        "selection": selection,
        "validated_outputs": outputs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def _callback_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = manifest.get("validated_outputs") or []
    receipts = {row.get("path"): row for row in outputs if isinstance(row, dict)}
    artifacts = []
    for receipt in manifest.get("storage_verification", {}).get("receipts", []):
        path = receipt.get("path")
        output = receipts.get(path)
        if not output:
            continue
        artifacts.append({
            "path": path,
            "name": Path(path).name,
            "sha256": output["sha256"],
            "bytes": receipt.get("bytes"),
            "drive_file_id": receipt.get("drive_file_id"),
            "remote_verification": receipt,
        })
    if not artifacts:
        raise WorkerFailure("PRIVATE_STORAGE_UNVERIFIED", "No privately verified RiverShift output files were returned by Google Drive.")
    return artifacts


def run_job(request: dict[str, Any], callbacks: JobCallbacks) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _ensure_credentials()
    work_dir = Path(os.environ.get("RUNNER_TEMP", str(ROOT / ".river-shift-runner"))) / f"river-shift-{request['job_id']}"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    catalogue_path = work_dir / "gcov-catalogue-manifest.json"
    audit_path = work_dir / "gcov-time-series-audit.json"
    selection_path = work_dir / "selected-observations.json"

    callbacks.send("running", "catalogue_discovery")
    run_step("catalogue discovery", [
        sys.executable, "discover_gcov_products.py", "--aoi-wkt", request["aoi_wkt"],
        "--start-date", request["start_date"].isoformat(), "--end-date", request["end_date"].isoformat(),
        "--maturity", request["maturity"], "--frame-coverage", "ALL", "--max-results", "2000",
        "--out", str(catalogue_path),
    ])
    manifest = json.loads(catalogue_path.read_text(encoding="utf-8"))
    submitted = set(request["granule_names"])
    catalogue_rows = [row for row in manifest.get("products", []) if row.get("granule_name") in submitted]
    returned = {row.get("granule_name") for row in catalogue_rows}
    if returned != submitted:
        missing = len(submitted - returned)
        raise WorkerFailure("CATALOGUE_CHANGED", f"NASA CMR no longer returns {missing} of the exact granules from the accepted request.")
    manifest["products"] = catalogue_rows
    manifest["product_count"] = len(catalogue_rows)
    manifest["query"]["maturity"] = request["maturity"]
    catalogue_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    callbacks.send("running", "acquisition_compatibility_audit")
    run_step("acquisition compatibility audit", [
        sys.executable, "audit_gcov_acquisitions.py", "--catalogue", str(catalogue_path),
        "--minimum-dates", "4", "--minimum-aoi-coverage-percent", "90",
        "--frequency", request["frequency"], "--term", request["term"], "--out", str(audit_path),
    ])
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    qualifying = audit.get("qualifying_groups")
    if not isinstance(qualifying, list) or not qualifying:
        raise WorkerFailure(
            "NO_COMPARABLE_ACQUISITION_GROUP",
            "This AOI/date selection has no four-date NISAR group with matching maturity, orbit, mode, term and footprint coverage.",
        )
    group = qualifying[0]
    dates, event_window = select_date_window(group.get("dates", []), request["event_date"])
    rows_by_date = {row["acquisition_date"]: row for row in group["dates"]}
    metric_crs = _metric_crs(request["aoi"])
    products_by_date: dict[str, list[dict[str, Any]]] = {}
    selected_product_names = []
    for observed_date in dates:
        date_row = rows_by_date[observed_date]
        selected = select_covering_granules(
            request["aoi"], catalogue_rows, date_row["granule_names"], metric_crs,
        )
        products_by_date[observed_date] = selected
        selected_product_names.extend(row["granule_name"] for row in selected)
    if len(selected_product_names) > MAX_SELECTED_GRANULES:
        raise WorkerFailure(
            "REQUEST_TOO_LARGE",
            f"This selection needs {len(selected_product_names)} NISAR files; the current worker limit is {MAX_SELECTED_GRANULES}. Narrow the date range or AOI.",
        )
    selection = {
        "aoi_wkt": request["aoi_wkt"],
        "start_date": request["start_date"].isoformat(),
        "end_date": request["end_date"].isoformat(),
        "event_date": request["event_date"].isoformat(),
        "maturity": request["maturity"],
        "frequency": request["frequency"],
        "covariance_term": request["term"],
        "event_date_basis": "user supplied; no independent gauge feed is attached",
        "time_series_semantics": "actual NISAR acquisition dates; no daily interpolation",
        "dates_selected": dates,
        "event_window": event_window,
        "event_observation_offset_days": (date.fromisoformat(event_window["event_observation"]) - request["event_date"]).days,
        "granule_names": sorted(set(selected_product_names)),
        "aoi_coverage_gate_percent": 90,
        "catalogue_audit_status": audit.get("status"),
        "raster_grid": "all dates reprojected with nearest-neighbour to the first selected observation grid",
        "release_status": "PROVISIONAL",
    }
    selection_path.write_text(json.dumps(selection, indent=2), encoding="utf-8")

    callbacks.send("running", "exact_product_download")
    raw_dir = work_dir / "raw"
    raster_dir = work_dir / "rasters"
    raster_dir.mkdir(parents=True)
    catalogue_for_download = work_dir / "selected-catalogue.json"
    catalogue_for_download.write_text(json.dumps({"products": catalogue_rows}, indent=2), encoding="utf-8")
    date_rasters: dict[str, Path] = {}
    callbacks.send("running", "hdf5_inspection_and_aoi_extraction")
    for observed_date in dates:
        exported = []
        for product in products_by_date[observed_date]:
            name = product["granule_name"]
            run_step("exact-product download", [
                sys.executable, "download_gcov_product.py", "--catalogue", str(catalogue_for_download),
                "--granule-name", name, "--out-dir", str(raw_dir), "--read-timeout", "900",
            ])
            product_path = raw_dir / f"{name}.h5"
            inventory_path = raw_dir / f"{name}.gcov_inventory.json"
            run_step("NISAR HDF5 inspection", [sys.executable, "inspect_gcov_product.py", "--product", str(product_path), "--out", str(inventory_path)])
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            available = {(item.get("frequency"), item.get("term")) for item in inventory.get("available_diagonal_terms", [])}
            if (request["frequency"], request["term"]) not in available:
                raise WorkerFailure("GCOV_LAYER_UNAVAILABLE", f"Requested {request['frequency']}/{request['term']} is absent from a selected HDF5 product.")
            raster_path = raster_dir / f"{name}.tif"
            run_step("AOI raster extraction", [
                sys.executable, "export_gcov_layer.py", "--product", str(product_path),
                "--frequency", request["frequency"], "--term", request["term"],
                "--maturity", request["maturity"], "--aoi-wkt", request["aoi_wkt"], "--out", str(raster_path),
            ])
            exported.append(raster_path)
        destination = raster_dir / f"observation_{observed_date}.tif"
        if len(exported) == 1:
            date_rasters[observed_date] = exported[0]
        else:
            date_rasters[observed_date] = _mosaic_date_rasters(exported, destination)

    reference_date = dates[0]
    reference_path = date_rasters[reference_date]
    aligned_observations: dict[str, Path] = {}
    for observed_date, path in date_rasters.items():
        aligned_observations[observed_date] = _co_register(path, reference_path, is_reference=(observed_date == reference_date))

    callbacks.send("running", "water_time_series_and_change_analysis")
    threshold_args = ["--otsu"] if request["threshold_method"] == "otsu" else ["--threshold-db", str(request["threshold_db"])]
    time_dir = work_dir / "analysis" / "time-series"
    time_command = [sys.executable, "run_water_timeseries.py"]
    for observed_date in dates:
        time_command.extend(["--observation", f"{observed_date}={aligned_observations[observed_date]}"])
    time_command.extend(threshold_args + [
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"], "--out-dir", str(time_dir),
    ])
    run_step("observed-date time-series analysis", time_command)

    window_paths = {key: aligned_observations[value] for key, value in event_window.items()}
    flood_dir = work_dir / "analysis" / "flood"
    run_step("flood change screening", [
        sys.executable, "run_flood_analysis.py", "--before", str(window_paths["before"]),
        "--during", str(window_paths["event_observation"]), "--after", str(window_paths["post_one"]),
        "--before-date", event_window["before"], "--during-date", event_window["event_observation"],
        "--after-date", event_window["post_one"], *threshold_args,
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"], "--out-dir", str(flood_dir),
    ])
    morphology_dir = work_dir / "analysis" / "morphology"
    run_step("persistent morphology screening", [
        sys.executable, "run_morphology_analysis.py", "--before", str(window_paths["before"]),
        "--post-one", str(window_paths["post_one"]), "--post-two", str(window_paths["post_two"]),
        "--before-date", event_window["before"], "--post-one-date", event_window["post_one"],
        "--post-two-date", event_window["post_two"], *threshold_args,
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"], "--out-dir", str(morphology_dir),
    ])

    callbacks.send("running", "private_result_publication")
    output_root = work_dir / "outputs"
    inventory = []
    for label, directory in (("time-series", time_dir), ("flood", flood_dir), ("morphology", morphology_dir)):
        inventory.extend(_copy_result_files([(label, directory)], output_root))
    provenance_dir = output_root / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    for source, target in ((catalogue_path, provenance_dir / "catalogue-manifest.json"),
                           (audit_path, provenance_dir / "acquisition-compatibility-audit.json"),
                           (selection_path, provenance_dir / "selected-observations.json")):
        shutil.copy2(source, target)
        inventory.append({"path": target.relative_to(work_dir).as_posix(), "sha256": sha256_file(target)})

    time_report_path = output_root / "time-series" / "river_shift_timeseries_preview.json"
    time_report = json.loads((time_dir / "river_shift_timeseries.json").read_text(encoding="utf-8"))
    time_report["selection"] = selection
    time_report["quality"]["warnings"].append(
        "Any companion *_preview.geojson layers are simplified for web display; use the full GeoJSON result for detailed GIS review."
    )
    time_report_path.write_text(json.dumps(time_report, indent=2), encoding="utf-8")
    preview_layers = create_web_previews(
        work_dir, time_dir, flood_dir, morphology_dir, reference_path, time_report_path,
    )
    inventory.extend(preview_layers)
    inventory.append({"path": time_report_path.relative_to(work_dir).as_posix(), "sha256": sha256_file(time_report_path)})
    report_digest = sha256_file(time_report_path)
    report_payload = json.loads(time_report_path.read_text(encoding="utf-8"))
    summary = {
        "schema_version": 1,
        "processing_status": "PASS",
        "release_status": "PROVISIONAL",
        "independent_validation_status": "PENDING",
        "event_date_status": "USER_SUPPLIED_NOT_INDEPENDENTLY_CONFIRMED",
        "morphology_status": json.loads((morphology_dir / "river_shift_result.json").read_text(encoding="utf-8"))["quality"]["status"],
        "flood_status": json.loads((flood_dir / "river_shift_result.json").read_text(encoding="utf-8"))["quality"]["status"],
        "observation_count": len(dates),
        "selected_dates": dates,
        "event_window": event_window,
        "threshold_method": request["threshold_method"],
        "threshold_db": report_payload["method"].get("threshold_db"),
        "time_series_report_sha256": report_digest,
        "map_preview": "outputs/map/river_change_candidates_preview.geojson",
        "warnings": [
            "NISAR observations occur on actual acquisition dates; no daily raster observations or interpolation were created.",
            "Riverbank erosion and deposition are provisional radar-derived candidates, not field-confirmed changes.",
            "The event date was supplied by the user and was not verified against an authoritative gauge feed.",
        ],
    }
    manifest_path = _build_manifest(work_dir, inventory, selection)
    try:
        storage = upload_validated_results(work_dir)
    except DriveUploadError:
        raise WorkerFailure("PRIVATE_STORAGE_UNVERIFIED", "Private Google Drive storage did not verify every RiverShift result checksum.") from None
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if storage.get("status") != "PASS":
        raise WorkerFailure("PRIVATE_STORAGE_UNVERIFIED", "Google Drive did not return a successful remote checksum verification.")
    artifact_manifest = _callback_artifacts(manifest_payload)
    return summary, artifact_manifest


def main() -> int:
    callbacks: JobCallbacks | None = None
    try:
        # Validate the callback contract before doing any expensive satellite IO.
        request = _read_input()
        callbacks = JobCallbacks(request["job_id"], request["fingerprint"], _required_env("RIVERSHIFT_CALLBACK_URL"))
        callbacks.send("running", "worker_started")
        summary, artifacts = run_job(request, callbacks)
        callbacks.send("succeeded", "completed", result_summary=summary, artifact_manifest=artifacts)
        print("RIVERSHIFT_PROCESSING_STATUS=PASS", flush=True)
        print("RIVERSHIFT_RELEASE_STATUS=PROVISIONAL", flush=True)
        print(f"RIVERSHIFT_ARTIFACT_COUNT={len(artifacts)}", flush=True)
        return 0
    except WorkerFailure as exc:
        message = str(exc)[:500]
        print(f"RIVERSHIFT_PROCESSING_STATUS=FAIL code={exc.code} message={message}", file=sys.stderr, flush=True)
        if callbacks:
            try:
                callbacks.send("failed", callbacks.stage, error_code=exc.code, error_message=message)
            except WorkerFailure:
                print("RIVERSHIFT_CALLBACK_STATUS=FAIL", file=sys.stderr, flush=True)
        return 1
    except Exception:
        message = "An unexpected RiverShift worker error occurred; inspect the processing run logs."
        print(f"RIVERSHIFT_PROCESSING_STATUS=FAIL message={message}", file=sys.stderr, flush=True)
        if callbacks:
            try:
                callbacks.send("failed", callbacks.stage, error_code="UNEXPECTED_WORKER_ERROR", error_message=message)
            except WorkerFailure:
                print("RIVERSHIFT_CALLBACK_STATUS=FAIL", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
