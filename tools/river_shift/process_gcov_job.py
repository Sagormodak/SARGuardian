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
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import numpy as np
from affine import Affine
import rasterio
import requests
from pyproj import CRS, Transformer
from rasterio.features import shapes
from rasterio.warp import Resampling, reproject
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union


ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
MAX_SELECTED_DATES = 12
MAX_SELECTED_GRANULES = 48
MAX_GRANULES_PER_DATE = 4
MAX_WEB_PREVIEW_BYTES = 3_500_000

from drive_upload_adapter import (
    DriveClient,
    DriveUploadError,
    RIVERSHIFT_STORAGE_FOLDER_NAME,
    load_drive_config,
    upload_validated_results,
)  # noqa: E402
from river_shift.raster_io import RasterContractError, validate_gcov_series  # noqa: E402
from river_shift.overlap_audit import audit_scene_mosaic_overlap  # noqa: E402


class WorkerFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _log_worker_stage(stage: str, status: str, **details: Any) -> None:
    """Print structured diagnostics without exposing credentials, AOI WKT or callback secrets."""
    payload = {"stage": stage, "status": status, **details}
    print("RIVERSHIFT_WORKER_STAGE " + json.dumps(payload, sort_keys=True, default=str), flush=True)


def build_source_granule_manifest(
    raw_dir: Path,
    granule_names: list[str],
    *,
    maturity: str,
    frequency: str,
    term: str,
) -> dict[str, Any]:
    """Bind accepted granules to download receipts and native HDF5 layer inventories."""
    rows = []
    for name in sorted(set(granule_names)):
        receipt_path = raw_dir / f"{name}.download.json"
        inventory_path = raw_dir / f"{name}.gcov_inventory.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise WorkerFailure(
                "SOURCE_RECEIPT_MISSING",
                f"Download receipt or HDF5 inventory is missing for selected granule {name}.",
            ) from None
        if (
            not isinstance(receipt, dict)
            or receipt.get("granule_name") != name
            or receipt.get("product") != "GCOV"
            or receipt.get("maturity") != maturity
            or receipt.get("downloaded") is not True
            or not isinstance(receipt.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", receipt["sha256"])
            or not isinstance(receipt.get("size_bytes"), int)
            or receipt["size_bytes"] <= 0
            or not isinstance(inventory, dict)
            or Path(str(inventory.get("product_file", ""))).name != f"{name}.h5"
        ):
            raise WorkerFailure(
                "SOURCE_RECEIPT_INVALID",
                f"Download receipt or HDF5 inventory does not match selected granule {name}.",
            )
        inventory_terms = inventory.get("available_diagonal_terms")
        if not isinstance(inventory_terms, list):
            raise WorkerFailure(
                "SOURCE_RECEIPT_INVALID",
                f"HDF5 layer inventory for {name} is missing its diagonal-term list.",
            )
        available = {
            (row.get("frequency"), row.get("term"))
            for row in inventory_terms
            if isinstance(row, dict)
        }
        if (frequency, term) not in available:
            raise WorkerFailure(
                "GCOV_LAYER_UNAVAILABLE",
                f"Native HDF5 inventory for {name} does not contain {frequency}/{term}.",
            )
        rows.append({
            "granule_name": name,
            "maturity": maturity,
            "source_host": receipt.get("source_host"),
            "size_bytes": receipt["size_bytes"],
            "source_product_sha256": receipt["sha256"].lower(),
            "download_receipt": f"{name}.download.json",
            "download_receipt_sha256": sha256_file(receipt_path),
            "hdf5_inventory": f"{name}.gcov_inventory.json",
            "hdf5_inventory_sha256": sha256_file(inventory_path),
            "gdal_version": inventory.get("gdal_version"),
            "available_diagonal_terms": inventory.get("available_diagonal_terms"),
            "available_valid_sample_masks": inventory.get("available_valid_sample_masks"),
        })
    if not rows:
        raise WorkerFailure("SOURCE_RECEIPT_MISSING", "No source granule receipts were retained for the selected observations.")
    return {
        "schema_version": 1,
        "mission": "NISAR",
        "product": "GCOV",
        "maturity": maturity,
        "frequency": frequency,
        "covariance_term": term,
        "granules": rows,
    }


def require_worker_source_provenance(
    observation_paths: dict[str, Path],
    *,
    maturity: str,
    frequency: str,
    term: str,
) -> list[dict[str, Any]]:
    """Fail the live worker unless every aligned date is bound to GCOV source hashes."""
    try:
        records, complete = validate_gcov_series(
            {key: str(path) for key, path in observation_paths.items()},
            maturity=maturity,
            frequency=frequency,
            term=term,
        )
    except (RasterContractError, OSError, ValueError) as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise WorkerFailure(
            "SOURCE_PROVENANCE_INVALID",
            "At least one aligned NISAR observation failed its source, maturity, layer or raster checksum provenance contract. "
            f"Validation detail: {detail[:300]}",
        ) from None
    if not complete or len(records) != len(observation_paths):
        raise WorkerFailure(
            "SOURCE_PROVENANCE_MISSING",
            "Every live RiverShift observation must include a verified exporter sidecar with exact source granule SHA-256 values.",
        )
    return records


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
    if isinstance(value, str):
        compact = re.fullmatch(r"(\\d{8}T\\d{6})(?:\\.\\d+)?Z?", value.strip())
        if compact:
            try:
                return datetime.strptime(compact.group(1), "%Y%m%dT%H%M%S").date().isoformat()
            except ValueError:
                return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.date().isoformat()
        except ValueError:
            pass
    granule_name = product.get("granule_name")
    if isinstance(granule_name, str):
        parts = granule_name.removesuffix(".h5").split("_")
        if len(parts) == 18 and parts[0] == "NISAR" and parts[1] == "L2" and parts[3] == "GCOV":
            try:
                return datetime.strptime(parts[11], "%Y%m%dT%H%M%S").date().isoformat()
            except ValueError:
                return None
    return None


def select_date_window(
    date_rows: list[dict[str, Any]], event_date: date, maximum_dates: int = MAX_SELECTED_DATES,
) -> tuple[list[str], dict[str, str]]:
    """Select one pre-event date, the first eligible post-event date, and two later dates."""
    if maximum_dates < 4:
        raise WorkerFailure("INVALID_REQUEST", "The selected time-series maximum cannot be lower than four dates.")
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
    try:
        parsed_dates = [date.fromisoformat(value) for value in dates]
    except ValueError:
        raise WorkerFailure("INVALID_CATALOGUE_DATE", "A footprint-qualified acquisition date is not valid ISO YYYY-MM-DD.") from None
    if len(set(parsed_dates)) != len(parsed_dates):
        raise WorkerFailure("DUPLICATE_CATALOGUE_DATE", "The footprint audit contains duplicate acquisition dates.")

    # A date-only event record cannot order an acquisition on that same
    # calendar date. Keep it in the discrete series, but do not treat it as
    # either a confirmed pre-event or post-event observation.
    before_index = next(
        (index for index in range(len(parsed_dates) - 1, -1, -1) if parsed_dates[index] < event_date),
        None,
    )
    event_index = next((index for index, observed in enumerate(parsed_dates) if observed > event_date), None)
    if before_index is None or event_index is None or event_index + 2 >= len(dates):
        raise WorkerFailure(
            "EVENT_WINDOW_NOT_BRACKETED",
            "Need one qualifying acquisition strictly before the event date and three strictly after it (event-proximal plus two later observations).",
        )

    quartet = [
        dates[before_index],
        dates[event_index],
        dates[event_index + 1],
        dates[event_index + 2],
    ]
    anchors = set(quartet)
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
    return sorted(selected), {
        "before": quartet[0],
        "event_proximal_observation": quartet[1],
        "post_one": quartet[2],
        "post_two": quartet[3],
    }


def select_general_date_window(
    date_rows: list[dict[str, Any]], maximum_dates: int = MAX_SELECTED_DATES,
) -> tuple[list[str], dict[str, str]]:
    """Select a baseline and three later real acquisitions without an event date."""
    if maximum_dates < 4:
        raise WorkerFailure("INVALID_REQUEST", "The selected time-series maximum cannot be lower than four dates.")
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
            "General River Change Scan needs at least four comparable, footprint-qualified NISAR acquisition dates.",
        )
    try:
        parsed = [date.fromisoformat(value) for value in dates]
    except ValueError:
        raise WorkerFailure("INVALID_CATALOGUE_DATE", "A footprint-qualified acquisition date is not valid ISO YYYY-MM-DD.") from None
    if len(set(parsed)) != len(parsed):
        raise WorkerFailure("DUPLICATE_CATALOGUE_DATE", "The footprint audit contains duplicate acquisition dates.")
    anchors = [dates[0], dates[1], dates[-2], dates[-1]]
    selected = set(anchors)
    while len(selected) < min(maximum_dates, len(dates)):
        remaining = [value for value in dates if value not in selected]
        if not remaining:
            break
        selected.add(max(
            remaining,
            key=lambda value: (
                min(abs((date.fromisoformat(value) - date.fromisoformat(chosen)).days) for chosen in selected),
                value,
            ),
        ))
    return sorted(selected), {
        "before": anchors[0],
        "event_proximal_observation": anchors[1],
        "post_one": anchors[2],
        "post_two": anchors[3],
    }


def select_general_compatible_group(
    qualifying_groups: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """Pick the highest-ranked compatible orbit/frame group with four qualified dates."""
    for group in qualifying_groups:
        try:
            selected_dates, comparison_window = select_general_date_window(group.get("dates", []))
        except WorkerFailure as exc:
            if exc.code == "INSUFFICIENT_COMPARABLE_ACQUISITIONS":
                continue
            raise
        return group, selected_dates, comparison_window
    raise WorkerFailure(
        "INSUFFICIENT_COMPARABLE_ACQUISITIONS",
        "No single compatible NISAR orbit/frame group has four footprint-qualified dates in this window.",
    )


def generalize_morphology_result(result_path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    """Remove event-specific labels from a general date-window morphology result."""
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("analysis_type") != "river_morphology_screening":
        raise WorkerFailure("RESULT_CONTRACT_INVALID", "The general-scan morphology output did not produce its expected report.")
    inputs, method, quality = result.get("inputs"), result.get("method"), result.get("quality")
    if not isinstance(inputs, dict) or not isinstance(method, dict) or not isinstance(quality, dict):
        raise WorkerFailure("RESULT_CONTRACT_INVALID", "The general-scan morphology report is incomplete.")
    result["analysis_mode"] = "general_scan"
    result["selection"] = selection
    inputs["comparison_window"] = selection.get("comparison_window", {})
    inputs["comparison_basis"] = "date-window comparison; no event date supplied or inferred"
    if isinstance(inputs.get("dates"), dict):
        inputs["dates"] = {
            "baseline": inputs["dates"].get("before"),
            "comparison_one": inputs["dates"].get("post_one"),
            "comparison_two": inputs["dates"].get("post_two"),
        }
    method["classification"] = "persistent_two_later_observation_water_land_transition"
    method["later_observations_required"] = method.pop("post_observations_required", 2)
    quality["warnings"] = [
        "Land-to-water and water-to-land transitions are provisional candidate zones, not confirmed geomorphic causation.",
        "Persistence is evaluated against the two later actual acquisition dates in the selected date window; no event date was supplied or inferred.",
        "All area and boundary comparisons use only the intersection of valid positive-power pixels across the three observations.",
        "Boundary distance is a symmetric displacement proxy, not a signed transect-derived bank migration rate.",
        "For braided rivers, interpret outer active-channel belt and individual threads separately.",
        "Check bank protection, dredging, sand mining, embankments and seasonal channel stage before attributing change to a specific cause.",
        "Threshold sensitivity is a deterministic method-robustness check, not a statistical confidence interval or total error budget.",
    ]
    Path(result_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def generalize_flood_result(result_path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    """Relabel the three-date water comparison without implying a flood event."""
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("analysis_type") != "flood_inundation_screening":
        raise WorkerFailure("RESULT_CONTRACT_INVALID", "The general-scan water comparison did not produce its expected report.")
    metrics, inputs, quality = result.get("metrics"), result.get("inputs"), result.get("quality")
    if not isinstance(metrics, dict) or not isinstance(inputs, dict) or not isinstance(quality, dict):
        raise WorkerFailure("RESULT_CONTRACT_INVALID", "The general-scan water comparison report is incomplete.")
    metrics["comparison_one_water_area_km2"] = metrics.pop("event_proximal_water_area_km2", None)
    metrics["comparison_two_water_area_km2"] = metrics.pop("post_event_water_area_km2", None)
    result["analysis_type"] = "river_change_scan"
    result["analysis_mode"] = "general_scan"
    result["selection"] = selection
    inputs["comparison_window"] = selection.get("comparison_window", {})
    inputs["comparison_basis"] = "date-window comparison; no event date supplied or inferred"
    inputs.pop("event_proximal_observation", None)
    if isinstance(inputs.get("dates"), dict):
        inputs["dates"] = {
            "baseline": inputs["dates"].get("before"),
            "comparison_one": inputs["dates"].get("during"),
            "comparison_two": inputs["dates"].get("after"),
        }
    if isinstance(result.get("method"), dict):
        result["method"]["comparison_semantics"] = "observed-date water coverage comparison; not an event attribution"
    quality["warnings"] = [
        "This is a general date-window comparison. No event date was supplied, estimated or inferred.",
        "Newly water-covered area is a relative radar-screening candidate, not proof of flood inundation or flood causality.",
        "Only the intersection of valid positive-power pixels across the selected comparison observations is included.",
        "Use comparable orbit geometry, acquisition mode, frequency, polarization, maturity and hydrological conditions.",
        "Low-backscatter screening may miss inundated vegetation because double-bounce scattering can be bright.",
        "Validate the water mask against an independent reference before reporting accuracy or impact claims.",
        "Threshold sensitivity is a deterministic method-robustness check, not a statistical confidence interval or total error budget.",
    ]
    Path(result_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def select_event_compatible_group(
    qualifying_groups: list[dict[str, Any]], event_date: date,
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """Choose the highest-ranked compatible group that brackets the event date."""
    for group in qualifying_groups:
        try:
            selected_dates, event_window = select_date_window(group.get("dates", []), event_date)
        except WorkerFailure as exc:
            if exc.code in {"EVENT_WINDOW_NOT_BRACKETED", "INSUFFICIENT_COMPARABLE_ACQUISITIONS"}:
                continue
            raise
        return group, selected_dates, event_window
    raise WorkerFailure(
        "EVENT_WINDOW_NOT_BRACKETED",
        "No single compatible NISAR orbit/frame group has one qualifying acquisition before the event date and three strictly after it.",
    )


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
    def __init__(self, job_id: str, fingerprint: str, callback_base: str, *, initial_sequence: int = 0) -> None:
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
        if isinstance(initial_sequence, bool) or not isinstance(initial_sequence, int) or initial_sequence < 0:
            raise WorkerFailure("INVALID_REQUEST", "Callback sequence must be a non-negative integer.")
        self.sequence = initial_sequence
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
        _log_worker_stage("signed_api_callback", "START", state=state, callback_stage=stage, sequence=sequence)
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
        retryable_status_codes = {408, 425, 429, 500, 502, 503, 504, 522, 524}
        retry_delays = (1.0, 2.0, 4.0)
        max_attempts = len(retry_delays) + 1
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    self.endpoint,
                    data=body,
                    headers={"Content-Type": "application/json", "X-SARGuardian-Signature": f"sha256={signature}"},
                    timeout=(15, 45),
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                error_response = getattr(exc, "response", None)
                status_code = getattr(error_response, "status_code", None)
                transient_transport_error = isinstance(exc, (requests.ConnectionError, requests.Timeout))
                retryable = transient_transport_error or status_code in retryable_status_codes
                if retryable and attempt < max_attempts:
                    delay = retry_delays[attempt - 1]
                    _log_worker_stage(
                        "signed_api_callback",
                        "RETRY",
                        state=state,
                        callback_stage=stage,
                        sequence=sequence,
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        status_code=status_code,
                        error_type=type(exc).__name__,
                        retry_delay_seconds=delay,
                    )
                    time.sleep(delay)
                    continue
                _log_worker_stage(
                    "signed_api_callback",
                    "FAIL",
                    state=state,
                    callback_stage=stage,
                    sequence=sequence,
                    attempts=attempt,
                    status_code=status_code,
                    error_type=type(exc).__name__,
                    retryable=retryable,
                )
                raise WorkerFailure("CALLBACK_REJECTED", "SARGuardian did not accept a signed processing update.") from None
            self.sequence = sequence
            _log_worker_stage(
                "signed_api_callback", "PASS", state=state, callback_stage=stage,
                sequence=sequence, attempts=attempt,
            )
            return
        raise WorkerFailure("CALLBACK_REJECTED", "SARGuardian did not accept a signed processing update.")


def run_step(stage: str, command: list[str], *, context: dict[str, Any] | None = None) -> None:
    started = time.monotonic()
    executable = Path(command[0]).name if command else "unknown"
    script = Path(command[1]).name if len(command) > 1 else None
    safe_context = context or {}
    _log_worker_stage("processing_command", "START", processing_step=stage, executable=executable, script=script, **safe_context)
    try:
        subprocess.run(command, cwd=TOOLS, check=True)
    except subprocess.CalledProcessError as exc:
        _log_worker_stage(
            "processing_command",
            "FAIL",
            processing_step=stage,
            executable=executable,
            script=script,
            exit_code=exc.returncode,
            elapsed_seconds=round(time.monotonic() - started, 3),
            **safe_context,
        )
        raise WorkerFailure(
            "SCIENCE_STEP_FAILED",
            f"The {stage.replace('_', ' ')} step failed with exit code {exc.returncode}; inspect the processing run logs.",
        ) from None
    _log_worker_stage(
        "processing_command",
        "PASS",
        processing_step=stage,
        executable=executable,
        script=script,
        elapsed_seconds=round(time.monotonic() - started, 3),
        **safe_context,
    )


def _mosaic_date_rasters(paths: list[Path], destination: Path) -> Path:
    if len(paths) == 1:
        return paths[0]
    vrt = destination.with_suffix(".vrt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered_paths = sorted(paths, key=lambda path: path.name)
    command = ["gdalbuildvrt", "-overwrite", "-resolution", "highest", "-addalpha", str(vrt), *map(str, ordered_paths)]
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
    try:
        mosaic_overlap_audit = audit_scene_mosaic_overlap(ordered_paths, destination)
    except (OSError, ValueError, rasterio.errors.RasterioError) as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise WorkerFailure(
            "MOSAIC_OVERLAP_AUDIT_FAILED",
            f"Could not complete the same-date scene overlap QA: {detail[:240]}",
        ) from None
    _log_worker_stage(
        "date_mosaic_overlap_audit", "PASS",
        acquisition_mosaic=destination.name,
        scene_count=mosaic_overlap_audit.get("scene_count"),
        pair_count=len(mosaic_overlap_audit.get("pairwise", [])),
        pairwise=mosaic_overlap_audit.get("pairwise", []),
        status=mosaic_overlap_audit.get("status"),
    )

    metadata_rows = [
        json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        for path in ordered_paths
    ]
    source_metadata = dict(metadata_rows[0])
    source_names = [
        name
        for row in metadata_rows
        for name in row.get("source_granule_names", [row["source_granule_name"]])
    ]
    source_hashes = [
        digest
        for row in metadata_rows
        for digest in row.get("source_granule_sha256", [row["source_product_sha256"]])
    ]
    aggregate_source_sha256 = (
        source_hashes[0] if len(source_hashes) == 1
        else hashlib.sha256("\n".join(sorted(source_hashes)).encode("ascii")).hexdigest()
    )
    source_metadata.update({
        "source_granule_name": "+".join(source_names),
        "source_granule_names": source_names,
        "source_granule_sha256": source_hashes,
        "source_product_sha256": aggregate_source_sha256,
        "source_product_sha256_scope": "single_granule" if len(source_hashes) == 1 else "sha256_of_sorted_source_granule_sha256_values",
        "output_cog": str(destination.resolve()),
        "output_cog_sha256": sha256_file(destination),
        "mosaic_method": "GDAL VRT; first valid source pixel in deterministic granule-name order",
        "mosaic_overlap_audit": mosaic_overlap_audit,
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
    """Legacy GeoJSON preview helper retained for import/API compatibility; not used by live jobs."""
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
    # Display-only previews may be simplified and omit small patches. Keep the
    # largest AOI features first so a dense candidate layer cannot fail an
    # otherwise valid scientific analysis merely because of a web payload cap.
    metric_features.sort(key=lambda item: item[1].area, reverse=True)

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

    # Last-resort display budget: retain the largest simplified candidate
    # polygons and explicitly report how many small patches were omitted.
    # Full-resolution GeoJSON and metrics remain untouched and authoritative.
    tolerance = max(float(pixel_size_m) * 128.0, 128.0)
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
    original_count = len(features)
    while features:
        omitted = original_count - len(features)
        preview["features"] = features
        preview["river_shift_preview"]["simplification_tolerance_m"] = round(tolerance, 3)
        preview["river_shift_preview"]["features_omitted_for_size"] = omitted
        preview["river_shift_preview"]["warning"] = (
            "DISPLAY ONLY: boundaries were simplified and the smallest patches were omitted to fit the map payload. "
            "Use the full private GeoJSON for detailed GIS review. Scientific metrics use the full-resolution analysis."
        )
        encoded = json.dumps(preview, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) <= max_bytes:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(encoded)
            return preview
        # Remove a deterministic tail of the smallest remaining features.
        keep = max(1, int(len(features) * 0.75))
        if keep == len(features):
            keep -= 1
        features = features[:keep]

    # An oversized web-only payload must never invalidate the underlying
    # scientific outputs. An empty display layer is preferable to losing a
    # valid analysis; the full-resolution GeoJSON remains in the private bundle.
    preview["features"] = []
    preview["river_shift_preview"]["features_omitted_for_size"] = original_count
    preview["river_shift_preview"]["warning"] = (
        "DISPLAY ONLY: every map patch was omitted because the preview exceeded its safe size budget. "
        "The full-resolution private GeoJSON and all scientific metrics remain available and unchanged."
    )
    encoded = json.dumps(preview, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) <= max_bytes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encoded)
        return preview
    raise WorkerFailure(
        "PREVIEW_GENERATION_FAILED",
        "The empty display-only preview exceeded its serialization limit; the underlying scientific output is preserved.",
    )



def write_mask_web_preview(
    mask_path: Path,
    destination: Path,
    *,
    class_name: str,
    max_bytes: int = MAX_WEB_PREVIEW_BYTES,
    max_dimension: int = 1600,
) -> dict[str, Any]:
    """Build a compact display-only GeoJSON layer from a binary science mask.

    The full-resolution mask remains the scientific source of record. The map
    preview uses max aggregation so isolated positive mask cells survive
    downsampling, then polygonizes the reduced grid and dissolves it to one
    feature per class. No source GeoJSON polygon is reprojected or simplified.
    """
    if not isinstance(class_name, str) or not class_name.strip():
        raise WorkerFailure("PREVIEW_GENERATION_FAILED", "A display layer must have a non-empty class name.")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1024:
        raise WorkerFailure("PREVIEW_GENERATION_FAILED", "The display preview byte limit is invalid.")
    if isinstance(max_dimension, bool) or not isinstance(max_dimension, int) or max_dimension < 64:
        raise WorkerFailure("PREVIEW_GENERATION_FAILED", "The display preview dimension is invalid.")

    try:
        with rasterio.open(mask_path) as source:
            if source.count != 1 or source.width < 1 or source.height < 1:
                raise ValueError("mask must be a non-empty single-band raster")
            if source.crs is None:
                raise ValueError("mask raster has no CRS")
            source_crs = CRS.from_user_input(source.crs)
            if not source_crs.is_projected:
                raise ValueError("mask raster must use a projected CRS")
            source_width = int(source.width)
            source_height = int(source.height)
            source_transform = source.transform
            source_crs_value = source.crs
            source_nodata = source.nodata
            source_mask_sha256 = sha256_file(mask_path)
            # Independently inventory the exact source-positive pixels once.
            # Some GDAL builds can yield tiny non-zero average-warp values for
            # an all-zero raster; this prevents those numerical artefacts from
            # becoming false map candidates and verifies empty/non-empty state.
            source_candidate_pixels = 0
            for _, source_window in source.block_windows(1):
                source_block = source.read(1, window=source_window)
                source_candidate_pixels += int(np.count_nonzero(source_block == 1))

            dimensions = sorted({
                min(max_dimension, value)
                for value in (1600, 1200, 900, 700, 512, 384, 256)
            }, reverse=True)
            selected_payload: dict[str, Any] | None = None
            last_output_bytes = 0

            for target_dimension in dimensions:
                scale = max(
                    source_width / float(target_dimension),
                    source_height / float(target_dimension),
                    1.0,
                )
                preview_width = max(1, int(math.ceil(source_width / scale)))
                preview_height = max(1, int(math.ceil(source_height / scale)))
                preview_transform = source_transform * Affine.scale(
                    source_width / float(preview_width),
                    source_height / float(preview_height),
                )
                # Use GDAL's average warp into floating point. RasterIO's
                # out_shape average can sample away isolated positives; a
                # coarser same-CRS warp computes fractional occupancy for each
                # target cell, so any positive source pixel remains > 0.
                # Zero is a valid background class in these binary masks.
                # Use a separate destination NoData sentinel so GDAL does not
                # replace valid zeros with tiny positive floats during warp.
                sampled_values = np.full(
                    (preview_height, preview_width), -1.0, dtype=np.float32
                )
                reproject(
                    source=rasterio.band(source, 1),
                    destination=sampled_values,
                    src_transform=source_transform,
                    src_crs=source_crs_value,
                    src_nodata=source_nodata,
                    dst_transform=preview_transform,
                    dst_crs=source_crs_value,
                    dst_nodata=-1.0,
                    resampling=Resampling.average,
                    init_dest_nodata=True,
                )
                candidate = sampled_values > 0.0
                if source_candidate_pixels == 0:
                    candidate.fill(False)
                candidate_cells = int(np.count_nonzero(candidate))
                if source_candidate_pixels > 0 and candidate_cells == 0:
                    raise WorkerFailure(
                        "PREVIEW_GENERATION_FAILED",
                        f"The source mask {mask_path.name} contains {source_candidate_pixels} positive candidate pixels, but resampling produced an empty display layer.",
                    )
                pixel_x_m = math.hypot(preview_transform.a, preview_transform.d)
                pixel_y_m = math.hypot(preview_transform.b, preview_transform.e)
                display_pixel_size_m = max(pixel_x_m, pixel_y_m)

                if candidate_cells:
                    geometries = []
                    for geometry, value in shapes(
                        candidate.astype(np.uint8),
                        mask=candidate,
                        transform=preview_transform,
                        connectivity=8,
                    ):
                        if int(value) == 1:
                            geometries.append(shape(geometry))
                    if not geometries:
                        raise WorkerFailure(
                            "PREVIEW_GENERATION_FAILED",
                            f"The source mask {mask_path.name} contains display candidates but polygonization returned none.",
                        )
                    merged = unary_union(geometries)
                    if merged.is_empty or not merged.is_valid:
                        merged = merged.buffer(0)
                    if merged.is_empty:
                        raise WorkerFailure(
                            "PREVIEW_GENERATION_FAILED",
                            f"The downsampled mask geometry for {mask_path.name} is empty or invalid.",
                        )
                    tolerance = max(display_pixel_size_m * 0.25, 0.01)
                    simplified = merged.simplify(tolerance, preserve_topology=True)
                    if simplified.is_empty:
                        simplified = merged
                    to_wgs84 = Transformer.from_crs(
                        source_crs_value, "EPSG:4326", always_xy=True
                    ).transform
                    geographic = transform(to_wgs84, simplified)
                    features = [{
                        "type": "Feature",
                        "properties": {
                            "class": class_name,
                            "river_shift_layer": class_name,
                            "preview_geometry": "average_aggregated_mask_footprint",
                        },
                        "geometry": mapping(geographic),
                    }]
                else:
                    features = []

                payload = {
                    "type": "FeatureCollection",
                    "name": destination.stem,
                    "crs": {
                        "type": "name",
                        "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
                    },
                    "river_shift_preview": {
                        "status": "DISPLAY_ONLY",
                        "method": "average_occupancy_gt_zero_then_polygonize",
                        "source_mask": mask_path.name,
                        "source_mask_sha256": source_mask_sha256,
                        "source_width": source_width,
                        "source_height": source_height,
                        "source_nodata": source_nodata,
                        "preview_width": preview_width,
                        "preview_height": preview_height,
                        "preview_candidate_cells": candidate_cells,
                        "source_candidate_pixels": source_candidate_pixels,
                        "display_pixel_size_m": round(display_pixel_size_m, 3),
                        "feature_count": len(features),
                        "features_omitted_for_size": 0,
                        "warning": (
                            "DISPLAY ONLY: geometry is generated from a average-aggregated lower-resolution copy of the "
                            "binary NISAR-derived mask. It preserves detected candidate cells for visual context, "
                            "but is not a survey-grade boundary or displacement measurement. Full-resolution "
                            "private masks, GeoJSON and scientific metrics are unchanged."
                        ),
                    },
                    "features": features,
                }
                encoded = json.dumps(
                    payload, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
                last_output_bytes = len(encoded)
                if len(encoded) <= max_bytes:
                    selected_payload = payload
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(encoded)
                    break

            if selected_payload is None:
                raise WorkerFailure(
                    "PREVIEW_GENERATION_FAILED",
                    f"Could not preserve the {class_name} display layer within the {max_bytes}-byte preview budget; "
                    f"the last compact candidate was {last_output_bytes} bytes. Full-resolution science outputs remain intact.",
                )

            if source_candidate_pixels == 0:
                selected_payload["river_shift_preview"]["empty_reason"] = (
                    "The full-resolution source mask contains no candidate pixels for this class."
                )
                destination.write_text(
                    json.dumps(selected_payload, separators=(",", ":"), allow_nan=False),
                    encoding="utf-8",
                )
            return selected_payload
    except WorkerFailure:
        raise
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise WorkerFailure(
            "PREVIEW_GENERATION_FAILED",
            f"Could not build the raster-first display preview for {mask_path.name}: {detail[:240]}",
        ) from None


def create_web_previews(
    work_dir: Path,
    time_dir: Path,
    flood_dir: Path,
    morphology_dir: Path,
    reference_raster: Path,
    time_report_path: Path,
) -> list[dict[str, Any]]:
    """Create checksum-bound map previews without reprocessing full GeoJSON polygons."""
    map_dir = work_dir / "outputs" / "map"
    with rasterio.open(reference_raster) as reference:
        if reference.crs is None or not CRS.from_user_input(reference.crs).is_projected:
            raise WorkerFailure("RASTER_GRID_INVALID", "Map previews need a projected NISAR raster grid.")
    layers: list[dict[str, Any]] = []
    sources = [
        (
            morphology_dir / "erosion_candidate_mask.tif",
            map_dir / "erosion_candidates_preview.geojson",
            "erosion",
        ),
        (
            morphology_dir / "deposition_candidate_mask.tif",
            map_dir / "deposition_candidates_preview.geojson",
            "deposition",
        ),
        (
            flood_dir / "newly_water_covered_mask.tif",
            map_dir / "newly_water_covered_preview.geojson",
            "new_water",
        ),
    ]
    change_features: list[dict[str, Any]] = []
    per_class_budget = max(1024, (MAX_WEB_PREVIEW_BYTES - 16_384) // len(sources))
    for source_path, destination, layer_type in sources:
        if not source_path.is_file():
            raise WorkerFailure(
                "PREVIEW_GENERATION_FAILED",
                f"The full-resolution {layer_type} science mask is missing: {source_path.name}.",
            )
        _log_worker_stage(
            "web_map_preview", "START",
            layer_type=layer_type,
            source_file=source_path.name,
            output_file=destination.name,
            preview_method="average_occupancy_gt_zero_then_polygonize",
        )
        preview = write_mask_web_preview(
            source_path,
            destination,
            class_name=layer_type,
            max_bytes=per_class_budget,
        )
        digest = sha256_file(destination)
        layers.append({
            "path": destination.relative_to(work_dir).as_posix(),
            "sha256": digest,
        })
        for feature in preview["features"]:
            properties = dict(feature.get("properties") or {})
            properties["river_shift_layer"] = layer_type
            change_features.append({**feature, "properties": properties})
        _log_worker_stage(
            "web_map_preview", "PASS",
            layer_type=layer_type,
            feature_count=len(preview.get("features", [])),
            source_candidate_pixels=preview["river_shift_preview"]["source_candidate_pixels"],
            source_candidate_fraction=round(
                preview["river_shift_preview"]["source_candidate_pixels"]
                / max(1, preview["river_shift_preview"]["source_width"] * preview["river_shift_preview"]["source_height"]),
                6,
            ),
            preview_candidate_cells=preview["river_shift_preview"]["preview_candidate_cells"],
            preview_candidate_fraction=round(
                preview["river_shift_preview"]["preview_candidate_cells"]
                / max(1, preview["river_shift_preview"]["preview_width"] * preview["river_shift_preview"]["preview_height"]),
                6,
            ),
            preview_width=preview["river_shift_preview"]["preview_width"],
            preview_height=preview["river_shift_preview"]["preview_height"],
            features_omitted_for_size=0,
            output_bytes=destination.stat().st_size,
            output_sha256=digest,
        )

    combined_path = map_dir / "river_change_candidates_preview.geojson"
    combined = {
        "type": "FeatureCollection",
        "name": combined_path.stem,
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "river_shift_preview": {
            "status": "DISPLAY_ONLY",
            "method": "separate_average_aggregated_mask_footprints_per_class",
            "class_count": len({feature["properties"]["river_shift_layer"] for feature in change_features}),
            "feature_count": len(change_features),
            "features_omitted_for_size": 0,
            "warning": (
                "Red: persistent erosion candidate; green: persistent deposition candidate; blue: newly water-covered "
                "candidate. Each class is represented independently from its own average-aggregated binary mask. "
                "These are provisional display footprints, not signed bank-migration measurements."
            ),
        },
        "features": change_features,
    }
    encoded_combined = json.dumps(
        combined, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(encoded_combined) > MAX_WEB_PREVIEW_BYTES:
        raise WorkerFailure(
            "PREVIEW_GENERATION_FAILED",
            "The class-preserving combined map preview exceeds its safe byte limit; no change class was silently dropped.",
        )
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    combined_path.write_bytes(encoded_combined)
    combined_digest = sha256_file(combined_path)
    layers.append({
        "path": combined_path.relative_to(work_dir).as_posix(),
        "sha256": combined_digest,
    })
    _log_worker_stage(
        "combined_change_preview", "PASS",
        feature_count=len(change_features),
        class_count=combined["river_shift_preview"]["class_count"],
        features_omitted_for_size=0,
        output_bytes=len(encoded_combined),
        output_sha256=combined_digest,
    )

    report = json.loads(time_report_path.read_text(encoding="utf-8"))
    frames = report.get("time_series")
    if not isinstance(frames, list):
        raise WorkerFailure("PREVIEW_GENERATION_FAILED", "The observed-date time-series report has no frame list.")
    for frame in frames:
        observed_date = frame.get("date") if isinstance(frame, dict) else None
        if not isinstance(observed_date, str):
            raise WorkerFailure("PREVIEW_GENERATION_FAILED", "An observed-date time-series frame has an invalid date.")
        mask_name = Path(str(frame.get("water_mask", ""))).name
        if not mask_name or mask_name in {".", ".."}:
            raise WorkerFailure(
                "PREVIEW_GENERATION_FAILED",
                f"The {observed_date} observed-date frame is missing its source water mask reference.",
            )
        source_mask = time_dir / mask_name
        if not source_mask.is_file():
            raise WorkerFailure(
                "PREVIEW_GENERATION_FAILED",
                f"The {observed_date} observed-date source mask is missing: {mask_name}.",
            )
        preview_path = map_dir / f"water_{observed_date}_preview.geojson"
        _log_worker_stage(
            "time_series_frame_preview", "START",
            acquisition_date=observed_date,
            source_file=source_mask.name,
            preview_method="max_aggregated_binary_mask_then_polygonize",
        )
        frame_preview = write_mask_web_preview(
            source_mask,
            preview_path,
            class_name="open_water",
            max_bytes=MAX_WEB_PREVIEW_BYTES,
        )
        frame_digest = sha256_file(preview_path)
        layers.append({
            "path": preview_path.relative_to(work_dir).as_posix(),
            "sha256": frame_digest,
        })
        frame["water_geojson"] = preview_path.name
        frame["water_geojson_sha256"] = frame_digest
        frame["water_preview_feature_count"] = len(frame_preview["features"])
        frame["water_preview_source_candidate_pixels"] = frame_preview["river_shift_preview"]["source_candidate_pixels"]
        frame["water_preview_candidate_cells"] = frame_preview["river_shift_preview"]["preview_candidate_cells"]
        _log_worker_stage(
            "time_series_frame_preview", "PASS",
            acquisition_date=observed_date,
            feature_count=len(frame_preview["features"]),
            source_candidate_pixels=frame_preview["river_shift_preview"]["source_candidate_pixels"],
            source_candidate_fraction=round(
                frame_preview["river_shift_preview"]["source_candidate_pixels"]
                / max(1, frame_preview["river_shift_preview"]["source_width"] * frame_preview["river_shift_preview"]["source_height"]),
                6,
            ),
            preview_candidate_cells=frame_preview["river_shift_preview"]["preview_candidate_cells"],
            preview_candidate_fraction=round(
                frame_preview["river_shift_preview"]["preview_candidate_cells"]
                / max(1, frame_preview["river_shift_preview"]["preview_width"] * frame_preview["river_shift_preview"]["preview_height"]),
                6,
            ),
            preview_width=frame_preview["river_shift_preview"]["preview_width"],
            preview_height=frame_preview["river_shift_preview"]["preview_height"],
            output_bytes=preview_path.stat().st_size,
            output_sha256=frame_digest,
            empty_reason=frame_preview["river_shift_preview"].get("empty_reason"),
        )
    report.setdefault("quality", {}).setdefault("warnings", []).append(
        "The web playback displays one max-aggregated lower-resolution mask per actual NISAR acquisition date. "
        "It is display-only; full-resolution masks and metrics remain authoritative. No daily interpolation is performed."
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
    analysis_mode = os.environ.get("RIVERSHIFT_ANALYSIS_MODE", "event_based").strip().lower()
    if analysis_mode not in {"general_scan", "event_based"}:
        raise WorkerFailure("INVALID_REQUEST", "RiverShift analysis mode must be general_scan or event_based.")
    raw_event_date = os.environ.get("RIVERSHIFT_EVENT_DATE", "").strip()
    event_date = _date(raw_event_date, "event_date") if raw_event_date else None
    if end_date < start_date or (end_date - start_date).days > 366:
        raise WorkerFailure("INVALID_REQUEST", "The selected NISAR observation window is not valid.")
    if analysis_mode == "event_based":
        if event_date is None or not start_date <= event_date <= end_date:
            raise WorkerFailure("INVALID_REQUEST", "Event-Based Analysis requires a user-supplied event date inside the observation window.")
    elif event_date is not None:
        raise WorkerFailure("INVALID_REQUEST", "General River Change Scan must not receive an event date.")
    maturity = _required_env("RIVERSHIFT_MATURITY").upper()
    main_band_polarization = os.environ.get("RIVERSHIFT_MAIN_BAND_POLARIZATION", "").strip() or None
    flight_direction = os.environ.get("RIVERSHIFT_FLIGHT_DIRECTION", "").strip().upper() or None
    frame_coverage = os.environ.get("RIVERSHIFT_FRAME_COVERAGE", "ALL").strip().upper()
    if main_band_polarization not in {None, "HH", "HH+HV", "HH+HV+VH+VV", "VV", "VV+VH", "LH+LV", "RH+RV"}:
        raise WorkerFailure("INVALID_REQUEST", "The main-band polarization discovery filter is unsupported.")
    if flight_direction not in {None, "ASCENDING", "DESCENDING"} or frame_coverage not in {"ALL", "FULL", "PARTIAL"}:
        raise WorkerFailure("INVALID_REQUEST", "The orbit-direction or frame-coverage discovery filter is unsupported.")
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
        "start_date": start_date, "end_date": end_date, "analysis_mode": analysis_mode, "event_date": event_date,
        "maturity": maturity, "main_band_polarization": main_band_polarization,
        "flight_direction": flight_direction, "frame_coverage": frame_coverage,
        "frequency": frequency, "term": term,
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
    _log_worker_stage("earthdata_credentials", "START")
    try:
        _configure_earthdata_credentials()
    except WorkerFailure as exc:
        _log_worker_stage("earthdata_credentials", "FAIL", error_code=exc.code, error=str(exc))
        raise
    earthdata_mode = "bearer_token" if os.environ.get("EARTHDATA_TOKEN", "").strip() else "netrc"
    _log_worker_stage("earthdata_credentials", "PASS", authentication_mode=earthdata_mode)

    _log_worker_stage("drive_configuration", "START")
    try:
        config = load_drive_config()
    except DriveUploadError as exc:
        _log_worker_stage("drive_configuration", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_CONFIGURATION_INVALID",
            "Google Drive configuration could not be parsed; inspect the sanitized Drive stage log.",
        ) from None
    folder_source = "GOOGLE_DRIVE_PARENT_FOLDER_ID"
    raw_token = os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN", "").strip()
    try:
        parsed_token = json.loads(raw_token)
        token_format = "token_json" if isinstance(parsed_token, dict) else "json_string"
    except json.JSONDecodeError:
        token_format = "bare"
    _log_worker_stage(
        "drive_configuration",
        "PASS",
        refresh_token_format=token_format,
        parent_folder_variable=folder_source,
        oauth_client_json_present=bool(os.environ.get("GOOGLE_DRIVE_OAUTH_CLIENT_JSON", "").strip()),
    )

    _log_worker_stage("drive_oauth_refresh", "START")
    try:
        drive = DriveClient(config)
    except DriveUploadError as exc:
        _log_worker_stage("drive_oauth_refresh", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_AUTHENTICATION_FAILED",
            "Google Drive OAuth token refresh failed; inspect the sanitized Drive stage log.",
        ) from None
    _log_worker_stage("drive_oauth_refresh", "PASS")

    _log_worker_stage("drive_account_verification", "START")
    try:
        drive.verify_authenticated_account()
    except DriveUploadError as exc:
        _log_worker_stage("drive_account_verification", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_ACCOUNT_VERIFICATION_FAILED",
            "The authenticated Google Drive account did not pass the SARGuardian account check.",
        ) from None
    _log_worker_stage("drive_account_verification", "PASS")

    _log_worker_stage(
        "drive_parent_folder_access",
        "START",
        folder_variable=folder_source,
        verification_method="list_children_then_find_or_create",
    )
    try:
        storage_root_folder = drive.find_or_create_folder(
            RIVERSHIFT_STORAGE_FOLDER_NAME, config.parent_folder_id
        )
    except DriveUploadError as exc:
        _log_worker_stage("drive_parent_folder_access", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_PARENT_FOLDER_UNAVAILABLE",
            "Google Drive could not list or create the fixed RiverShift folder beneath GOOGLE_DRIVE_PARENT_FOLDER_ID; verify that the parent exists and allows folder creation.",
        ) from None
    _log_worker_stage(
        "drive_parent_folder_access",
        "PASS",
        folder_name=RIVERSHIFT_STORAGE_FOLDER_NAME,
    )

    _log_worker_stage("river_shift_storage_folder_privacy", "START")
    try:
        drive.require_private_folder(storage_root_folder)
    except DriveUploadError as exc:
        _log_worker_stage("river_shift_storage_folder_privacy", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_FOLDER_NOT_PRIVATE",
            "The fixed RiverShift folder does not satisfy the private-storage policy.",
        ) from None
    _log_worker_stage("river_shift_storage_folder_privacy", "PASS")


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
        "analysis_mode": selection.get("analysis_mode", "event_based"),
        "event_date_status": "NOT_APPLICABLE" if selection.get("analysis_mode") == "general_scan" else "USER_SUPPLIED_NOT_INDEPENDENTLY_CONFIRMED",
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
    _log_worker_stage(
        "job_request_summary",
        "PASS",
        job_id=request["job_id"],
        start_date=request["start_date"].isoformat(),
        end_date=request["end_date"].isoformat(),
        analysis_mode=request["analysis_mode"],
        event_date=request["event_date"].isoformat() if request["event_date"] else None,
        maturity=request["maturity"],
        frequency=request["frequency"],
        covariance_term=request["term"],
        requested_granule_count=len(request["granule_names"]),
    )
    _ensure_credentials()
    work_dir = Path(os.environ.get("RUNNER_TEMP", str(ROOT / ".river-shift-runner"))) / f"river-shift-{request['job_id']}"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    catalogue_path = work_dir / "gcov-catalogue-manifest.json"
    audit_path = work_dir / "gcov-time-series-audit.json"
    selection_path = work_dir / "selected-observations.json"

    callbacks.send("running", "catalogue_discovery")
    discovery_command = [
        sys.executable, "discover_gcov_products.py", "--aoi-wkt", request["aoi_wkt"],
        "--start-date", request["start_date"].isoformat(), "--end-date", request["end_date"].isoformat(),
        "--maturity", request["maturity"], "--frame-coverage", request["frame_coverage"],
        "--max-results", "2000", "--out", str(catalogue_path),
    ]
    if request["main_band_polarization"]:
        discovery_command.extend(["--main-band-polarization", request["main_band_polarization"]])
    if request["flight_direction"]:
        discovery_command.extend(["--flight-direction", request["flight_direction"]])
    run_step("catalogue discovery", discovery_command)
    manifest = json.loads(catalogue_path.read_text(encoding="utf-8"))
    submitted = set(request["granule_names"])
    catalogue_rows = [row for row in manifest.get("products", []) if row.get("granule_name") in submitted]
    returned = {row.get("granule_name") for row in catalogue_rows}
    if returned != submitted:
        missing = len(submitted - returned)
        _log_worker_stage("exact_catalogue_match", "FAIL", submitted_count=len(submitted), returned_count=len(returned), missing_count=missing)
        raise WorkerFailure("CATALOGUE_CHANGED", f"NASA CMR no longer returns {missing} of the exact granules from the accepted request.")
    _log_worker_stage("exact_catalogue_match", "PASS", submitted_count=len(submitted), returned_count=len(returned))
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
    if request["analysis_mode"] == "event_based":
        group, dates, event_window = select_event_compatible_group(qualifying, request["event_date"])
    else:
        group, dates, event_window = select_general_compatible_group(qualifying)
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
        "analysis_mode": request["analysis_mode"],
        "maturity": request["maturity"],
        "frequency": request["frequency"],
        "covariance_term": request["term"],
        "time_series_semantics": "actual NISAR acquisition dates; no daily interpolation",
        "dates_selected": dates,
        "comparison_window": {
            "baseline": event_window["before"],
            "comparison_one": event_window["event_proximal_observation"],
            "comparison_two": event_window["post_one"],
            "comparison_three": event_window["post_two"],
        } if request["analysis_mode"] == "general_scan" else None,
        "event_date": request["event_date"].isoformat() if request["event_date"] else None,
        "event_date_basis": "user supplied; no independent gauge feed is attached" if request["analysis_mode"] == "event_based" else None,
        "event_window": event_window if request["analysis_mode"] == "event_based" else None,
        "event_proximal_observation_offset_days": (
            (date.fromisoformat(event_window["event_proximal_observation"]) - request["event_date"]).days
            if request["analysis_mode"] == "event_based" else None
        ),
        "granule_names": sorted(set(selected_product_names)),
        "aoi_coverage_gate_percent": 90,
        "catalogue_audit_status": audit.get("status"),
        "raster_grid": "all dates reprojected with nearest-neighbour to the first selected observation grid",
        "release_status": "PROVISIONAL",
    }
    selection_path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    _log_worker_stage(
        "observation_selection",
        "PASS",
        selected_date_count=len(dates),
        selected_granule_count=len(set(selected_product_names)),
        selected_dates=dates,
        granules_per_date={observed_date: len(rows) for observed_date, rows in products_by_date.items()},
    )

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
                "--granule-name", name, "--out-dir", str(raw_dir), 
            ], context={"granule_name": name, "acquisition_date": observed_date})
            product_path = raw_dir / f"{name}.h5"
            inventory_path = raw_dir / f"{name}.gcov_inventory.json"
            run_step(
                "NISAR HDF5 inspection",
                [sys.executable, "inspect_gcov_product.py", "--product", str(product_path), "--out", str(inventory_path)],
                context={"granule_name": name, "acquisition_date": observed_date},
            )
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            available = {(item.get("frequency"), item.get("term")) for item in inventory.get("available_diagonal_terms", [])}
            if (request["frequency"], request["term"]) not in available:
                raise WorkerFailure("GCOV_LAYER_UNAVAILABLE", f"Requested {request['frequency']}/{request['term']} is absent from a selected HDF5 product.")
            raster_path = raster_dir / f"{name}.tif"
            run_step("AOI raster extraction", [
                sys.executable, "export_gcov_layer.py", "--product", str(product_path),
                "--frequency", request["frequency"], "--term", request["term"],
                "--maturity", request["maturity"], "--aoi-wkt", request["aoi_wkt"], "--out", str(raster_path),
            ], context={"granule_name": name, "acquisition_date": observed_date})
            exported.append(raster_path)
            # The exporter has already bound the HDF5 source checksum, download
            # receipt and native layer inventory into the COG sidecar. Retain
            # the small receipts, but release multi-GB raw HDF5 immediately.
            product_path.unlink(missing_ok=True)
        destination = raster_dir / f"observation_{observed_date}.tif"
        if len(exported) == 1:
            date_rasters[observed_date] = exported[0]
        else:
            date_rasters[observed_date] = _mosaic_date_rasters(exported, destination)
            for intermediate in exported:
                intermediate.unlink(missing_ok=True)
                intermediate.with_suffix(".metadata.json").unlink(missing_ok=True)

    source_granule_manifest = build_source_granule_manifest(
        raw_dir,
        selected_product_names,
        maturity=request["maturity"],
        frequency=request["frequency"],
        term=request["term"],
    )
    source_granule_manifest_path = work_dir / "source-granule-provenance.json"
    source_granule_manifest_path.write_text(
        json.dumps(source_granule_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    reference_date = dates[0]
    reference_path = date_rasters[reference_date]
    aligned_observations: dict[str, Path] = {}
    for observed_date, path in date_rasters.items():
        aligned_observations[observed_date] = _co_register(path, reference_path, is_reference=(observed_date == reference_date))

    require_worker_source_provenance(
        aligned_observations,
        maturity=request["maturity"],
        frequency=request["frequency"],
        term=request["term"],
    )
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
    run_step("date-window water change screening", [
        sys.executable, "run_flood_analysis.py", "--before", str(window_paths["before"]),
        "--during", str(window_paths["event_proximal_observation"]), "--after", str(window_paths["post_one"]),
        "--before-date", event_window["before"], "--during-date", event_window["event_proximal_observation"],
        "--after-date", event_window["post_one"], *threshold_args,
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"], "--out-dir", str(flood_dir),
    ])
    if request["analysis_mode"] == "general_scan":
        generalize_flood_result(flood_dir / "river_shift_result.json", selection)
    morphology_dir = work_dir / "analysis" / "morphology"
    run_step("persistent morphology screening", [
        sys.executable, "run_morphology_analysis.py", "--before", str(window_paths["before"]),
        "--post-one", str(window_paths["post_one"]), "--post-two", str(window_paths["post_two"]),
        "--before-date", event_window["before"], "--post-one-date", event_window["post_one"],
        "--post-two-date", event_window["post_two"], *threshold_args,
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"], "--out-dir", str(morphology_dir),
    ])
    if request["analysis_mode"] == "general_scan":
        generalize_morphology_result(morphology_dir / "river_shift_result.json", selection)

    callbacks.send("running", "private_result_publication")
    _log_worker_stage("result_package_assembly", "START")
    output_root = work_dir / "outputs"
    inventory = []
    for label, directory in (("time-series", time_dir), ("flood", flood_dir), ("morphology", morphology_dir)):
        inventory.extend(_copy_result_files([(label, directory)], output_root))
    provenance_dir = output_root / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    for source, target in ((catalogue_path, provenance_dir / "catalogue-manifest.json"),
                           (audit_path, provenance_dir / "acquisition-compatibility-audit.json"),
                           (selection_path, provenance_dir / "selected-observations.json"),
                           (source_granule_manifest_path, provenance_dir / "source-granule-provenance.json")):
        shutil.copy2(source, target)
        inventory.append({"path": target.relative_to(work_dir).as_posix(), "sha256": sha256_file(target)})
    granule_receipts_dir = provenance_dir / "granules"
    granule_receipts_dir.mkdir(parents=True, exist_ok=True)
    for granule in source_granule_manifest["granules"]:
        for key in ("download_receipt", "hdf5_inventory"):
            source = raw_dir / granule[key]
            target = granule_receipts_dir / source.name
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
        "analysis_mode": request["analysis_mode"],
        "event_date_status": "NOT_APPLICABLE" if request["analysis_mode"] == "general_scan" else "USER_SUPPLIED_NOT_INDEPENDENTLY_CONFIRMED",
        "morphology_status": json.loads((morphology_dir / "river_shift_result.json").read_text(encoding="utf-8"))["quality"]["status"],
        "flood_status": json.loads((flood_dir / "river_shift_result.json").read_text(encoding="utf-8"))["quality"]["status"],
        "observation_count": len(dates),
        "selected_dates": dates,
        "comparison_window": selection.get("comparison_window"),
        "event_window": event_window if request["analysis_mode"] == "event_based" else None,
        "threshold_method": request["threshold_method"],
        "threshold_db": report_payload["method"].get("threshold_db"),
        "time_series_report_sha256": report_digest,
        "map_preview": "outputs/map/river_change_candidates_preview.geojson",
        "warnings": [
            "NISAR observations occur on actual acquisition dates; no daily raster observations or interpolation were created.",
            "Riverbank erosion and deposition are provisional radar-derived candidates, not field-confirmed changes.",
            *(
                [
                    "This is a relative date-window comparison; no event date was supplied or inferred.",
                    "New water and persistent land/water transitions are provisional candidates, not confirmed flood or geomorphic causes.",
                ] if request["analysis_mode"] == "general_scan" else [
                    "The flood comparison uses the first qualifying NISAR acquisition strictly after the user-supplied event date; it is not a measured peak-stage observation.",
                    "The event date was supplied by the user and was not verified against an authoritative gauge feed.",
                ]
            ),
        ],
    }
    manifest_path = _build_manifest(work_dir, inventory, selection)
    _log_worker_stage(
        "result_package_assembly",
        "PASS",
        validated_output_count=len(inventory),
        manifest_sha256=sha256_file(manifest_path),
    )
    try:
        storage = upload_validated_results(work_dir)
    except DriveUploadError as exc:
        _log_worker_stage("private_result_publication", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_PUBLICATION_FAILED",
            "Google Drive result publication failed; inspect the per-file Drive stage logs.",
        ) from None
    _log_worker_stage(
        "private_result_publication",
        "PASS",
        storage_status=storage.get("status"),
        receipt_count=len(storage.get("receipts", [])),
        retained_bytes=storage.get("retained_bytes"),
    )
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if storage.get("status") != "PASS":
        raise WorkerFailure("PRIVATE_STORAGE_UNVERIFIED", "Google Drive did not return a successful remote checksum verification.")
    artifact_manifest = _callback_artifacts(manifest_payload)
    return summary, artifact_manifest


def main() -> int:
    callbacks: JobCallbacks | None = None
    started = time.monotonic()
    _log_worker_stage("worker_startup", "START", python_version=sys.version.split()[0])
    try:
        # Validate the callback contract before doing any expensive satellite IO.
        _log_worker_stage("request_validation", "START")
        request = _read_input()
        _log_worker_stage(
            "request_validation",
            "PASS",
            job_id=request["job_id"],
            requested_granule_count=len(request["granule_names"]),
        )
        callbacks = JobCallbacks(request["job_id"], request["fingerprint"], _required_env("RIVERSHIFT_CALLBACK_URL"))
        callbacks.send("running", "worker_started")
        summary, artifacts = run_job(request, callbacks)
        callbacks.send("succeeded", "completed", result_summary=summary, artifact_manifest=artifacts)
        print("RIVERSHIFT_PROCESSING_STATUS=PASS", flush=True)
        print("RIVERSHIFT_RELEASE_STATUS=PROVISIONAL", flush=True)
        print(f"RIVERSHIFT_ARTIFACT_COUNT={len(artifacts)}", flush=True)
        _log_worker_stage("worker_completion", "PASS", elapsed_seconds=round(time.monotonic() - started, 3), artifact_count=len(artifacts))
        return 0
    except WorkerFailure as exc:
        message = str(exc)[:500]
        print(f"RIVERSHIFT_PROCESSING_STATUS=FAIL code={exc.code} message={message}", file=sys.stderr, flush=True)
        _log_worker_stage("worker_completion", "FAIL", error_code=exc.code, elapsed_seconds=round(time.monotonic() - started, 3))
        if callbacks:
            try:
                callbacks.send("failed", callbacks.stage, error_code=exc.code, error_message=message)
            except WorkerFailure:
                print("RIVERSHIFT_CALLBACK_STATUS=FAIL", file=sys.stderr, flush=True)
        return 1
    except Exception:
        message = "An unexpected RiverShift worker error occurred; inspect the processing run logs."
        print(f"RIVERSHIFT_PROCESSING_STATUS=FAIL type={type(sys.exc_info()[1]).__name__} message={message}", file=sys.stderr, flush=True)
        _log_worker_stage("worker_completion", "FAIL", error_code="UNEXPECTED_WORKER_ERROR", error_type=type(sys.exc_info()[1]).__name__, elapsed_seconds=round(time.monotonic() - started, 3))
        traceback.print_exc(file=sys.stderr)
        if callbacks:
            try:
                callbacks.send("failed", callbacks.stage, error_code="UNEXPECTED_WORKER_ERROR", error_message=message)
            except WorkerFailure:
                print("RIVERSHIFT_CALLBACK_STATUS=FAIL", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
