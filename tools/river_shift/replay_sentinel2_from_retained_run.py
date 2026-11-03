#!/usr/bin/env python3
"""Replay a retained RiverShift run's NISAR water mask and cross-check one date with Sentinel-2.

This optional replay consumes existing per-product COG artifacts from a completed
RiverShift GitHub Actions run. It does not redownload raw NISAR HDF5 products and
does not modify the primary live-processing workflow.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from river_shift.timeseries import run_water_timeseries_analysis
from validate_with_sentinel2 import CrosscheckError, run_crosscheck


class ReplayError(RuntimeError):
    """Raised when retained source artifacts cannot be safely replayed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_single_json(root: Path, filename: str) -> tuple[Path, dict[str, Any]]:
    paths = sorted(root.rglob(filename))
    if len(paths) != 1:
        raise ReplayError(
            f"Expected exactly one {filename} below {root}; found {len(paths)}."
        )
    try:
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"Could not read {filename}: {type(exc).__name__}.") from None
    if not isinstance(payload, dict):
        raise ReplayError(f"{filename} must contain a JSON object.")
    return paths[0], payload


def prepare_source_observations(
    products_dir: Path,
    prepared_dir: Path,
    *,
    expected_source_run_id: str,
) -> tuple[list[dict[str, str]], dict[str, Any], list[dict[str, Any]]]:
    """Verify retained per-product COG receipts and restore exact local sidecar paths."""
    _, prepared = _load_single_json(prepared_dir, "prepared.json")
    selected_names = prepared.get("selected_product_names")
    date_by_name = prepared.get("date_by_name")
    request = prepared.get("request")
    if not isinstance(selected_names, list) or not selected_names:
        raise ReplayError("The prepared manifest contains no selected product names.")
    if len(selected_names) != len(set(selected_names)):
        raise ReplayError("The prepared manifest repeats a selected product name.")
    if not isinstance(date_by_name, dict) or not isinstance(request, dict):
        raise ReplayError("The prepared manifest is missing date_by_name or request metadata.")
    if len(selected_names) != len(date_by_name):
        raise ReplayError("Selected product names and acquisition-date mapping are incomplete.")

    result_paths = sorted(products_dir.rglob("worker-result.json"))
    results_by_name: dict[str, tuple[Path, dict[str, Any]]] = {}
    for result_path in result_paths:
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = result.get("granule_name") if isinstance(result, dict) else None
        if isinstance(name, str):
            if name in results_by_name:
                raise ReplayError(f"More than one retained worker receipt exists for {name}.")
            results_by_name[name] = (result_path.parent, result)

    observations: list[dict[str, str]] = []
    receipts: list[dict[str, Any]] = []
    expected_signature: tuple[str, str, str, str, str, str, str] | None = None
    for name in selected_names:
        if not isinstance(name, str) or not name:
            raise ReplayError("The prepared manifest contains an invalid granule name.")
        observed_date = date_by_name.get(name)
        if not isinstance(observed_date, str):
            raise ReplayError(f"The prepared manifest has no acquisition date for {name}.")
        try:
            date.fromisoformat(observed_date)
        except ValueError:
            raise ReplayError(f"The acquisition date for {name} is invalid.") from None

        located = results_by_name.get(name)
        if located is None:
            raise ReplayError(f"No retained worker receipt was found for {name}.")
        product_dir, result = located
        if result.get("status") != "PASS":
            raise ReplayError(f"The retained product receipt for {name} is not PASS.")
        if str(result.get("workflow_run_id")) != str(expected_source_run_id):
            raise ReplayError(f"The product receipt for {name} is not from source run {expected_source_run_id}.")
        if result.get("granule_name") != name:
            raise ReplayError(f"The retained product identity does not match {name}.")

        files = result.get("files")
        if not isinstance(files, list):
            raise ReplayError(f"The worker receipt for {name} has no file inventory.")
        raster_receipt = next(
            (
                item for item in files
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and item["name"].endswith(".tif")
            ),
            None,
        )
        if raster_receipt is None:
            raise ReplayError(f"The worker receipt for {name} has no retained COG.")
        raster_path = product_dir / raster_receipt["name"]
        sidecar_path = raster_path.with_suffix(".metadata.json")
        if not raster_path.is_file() or not sidecar_path.is_file():
            raise ReplayError(f"The COG or metadata sidecar for {name} is missing.")
        raster_digest = sha256_file(raster_path)
        if raster_digest.lower() != str(raster_receipt.get("sha256", "")).lower():
            raise ReplayError(f"The COG checksum does not match the worker receipt for {name}.")
        if raster_digest.lower() != str(result.get("raster_sha256", "")).lower():
            raise ReplayError(f"The COG checksum does not match the worker result for {name}.")

        try:
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ReplayError(f"The COG metadata sidecar for {name} is invalid.") from None
        if not isinstance(metadata, dict):
            raise ReplayError(f"The COG metadata sidecar for {name} is not a JSON object.")
        if metadata.get("source_granule_name") != name:
            raise ReplayError(f"The COG sidecar source identity does not match {name}.")
        if str(metadata.get("output_cog_sha256", "")).lower() != raster_digest.lower():
            raise ReplayError(f"The COG sidecar checksum does not match the raster for {name}.")

        signature = (
            str(metadata.get("maturity", "")).upper(),
            str(metadata.get("frequency", "")),
            str(metadata.get("covariance_term", "")),
            str(metadata.get("bandwidth_mode", "")),
            str(metadata.get("polarization_code", "")),
            str(metadata.get("flight_direction", "")),
            str(metadata.get("relative_orbit", "")),
        )
        if expected_signature is None:
            expected_signature = signature
        elif signature != expected_signature:
            raise ReplayError("Retained COGs do not share one identical GCOV comparison signature.")

        if str(metadata.get("maturity", "")).upper() != str(request.get("maturity", "")).upper():
            raise ReplayError(f"COG maturity does not match the prepared request for {name}.")
        if metadata.get("frequency") != request.get("frequency"):
            raise ReplayError(f"COG frequency does not match the prepared request for {name}.")
        if metadata.get("covariance_term") != request.get("term"):
            raise ReplayError(f"COG covariance term does not match the prepared request for {name}.")

        # The provenance validator requires a sidecar to bind the exact local
        # raster path. Restore only that path; keep and re-check the original
        # COG SHA-256 unchanged.
        metadata["output_cog"] = str(raster_path.resolve())
        sidecar_path.write_text(
            json.dumps(metadata, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        observations.append({"date": observed_date, "path": str(raster_path.resolve())})
        receipts.append({
            "date": observed_date,
            "granule_name": name,
            "cog_sha256": raster_digest,
            "source_product_sha256": metadata.get("source_product_sha256"),
            "sidecar": sidecar_path.name,
        })

    observations.sort(key=lambda row: row["date"])
    if len(observations) < 2:
        raise ReplayError("At least two retained observations are required.")
    if len({row["date"] for row in observations}) != len(observations):
        raise ReplayError("Retained source artifacts contain duplicate acquisition dates.")
    if len(observations) != len(selected_names):
        raise ReplayError("Not all selected products were restored.")
    return observations, prepared, receipts


def run_replay(
    *,
    products_dir: Path,
    prepared_dir: Path,
    source_run_id: str,
    observation_date: date,
    output_dir: Path,
    max_day_offset: int = 3,
    max_cloud_cover: float = 40.0,
    mndwi_threshold: float = 0.0,
    minimum_common_support: float = 0.80,
) -> dict[str, Any]:
    if not re.fullmatch(r"\d{6,20}", str(source_run_id)):
        raise ReplayError("source_run_id must be a numeric GitHub Actions run ID.")
    observations, prepared, receipts = prepare_source_observations(
        products_dir,
        prepared_dir,
        expected_source_run_id=str(source_run_id),
    )
    selected_dates = [row["date"] for row in observations]
    if observation_date.isoformat() not in selected_dates:
        raise ReplayError(
            f"Requested observation date {observation_date.isoformat()} is not in the retained source run."
        )
    request = prepared["request"]
    output_dir.mkdir(parents=True, exist_ok=True)
    timeseries_dir = output_dir / "nisar-time-series"
    threshold_method = str(request.get("threshold_method", "otsu"))
    threshold_db = request.get("threshold_db")
    if threshold_method not in {"otsu", "manual"}:
        raise ReplayError(f"Unsupported threshold method in source run: {threshold_method}.")
    timeseries = run_water_timeseries_analysis(
        observations=observations,
        output_dir=str(timeseries_dir),
        units="linear",
        threshold_db=threshold_db,
        use_otsu=(threshold_method == "otsu"),
        maturity=str(request["maturity"]),
        frequency=str(request["frequency"]),
        polarization_term=str(request["term"]),
    )
    mask_path = timeseries_dir / f"water_{observation_date.isoformat()}_mask.tif"
    if not mask_path.is_file():
        raise ReplayError("The exact-date NISAR water mask was not created.")
    crosscheck_dir = output_dir / "sentinel2-cross-sensor"
    report = run_crosscheck(
        nisar_mask_path=mask_path,
        observation_date=observation_date,
        output_dir=crosscheck_dir,
        max_day_offset=max_day_offset,
        max_cloud_cover=max_cloud_cover,
        mndwi_threshold=mndwi_threshold,
        minimum_common_support=minimum_common_support,
    )

    replay_manifest = {
        "schema_version": 1,
        "analysis_type": "retained_nisar_run_sentinel2_cross_sensor_replay",
        "source_workflow_run_id": str(source_run_id),
        "source_job_id": prepared.get("job_id"),
        "request_fingerprint": prepared.get("request_fingerprint"),
        "requested_observation_date": observation_date.isoformat(),
        "actual_nisar_observation_dates": selected_dates,
        "nisar_time_series_threshold_db": timeseries["method"]["threshold_db"],
        "nisar_time_series_threshold_method": timeseries["method"]["threshold_method"],
        "nisar_time_series_report_sha256": sha256_file(timeseries_dir / "river_shift_timeseries.json"),
        "nisar_water_mask_sha256": sha256_file(mask_path),
        "source_products": receipts,
        "sentinel2_report": "sentinel2-cross-sensor/sentinel2_cross_sensor_agreement.json",
        "sentinel2_report_sha256": sha256_file(crosscheck_dir / "sentinel2_cross_sensor_agreement.json"),
        "sentinel2_status": report.get("status"),
        "sentinel2_metrics_available": isinstance(report.get("metrics"), dict),
        "quality": {
            "status": "PROVISIONAL_CROSS_SENSOR_AGREEMENT_ONLY",
            "not_ground_truth": True,
            "not_field_validation": True,
            "primary_nisar_run_reprocessed_from_retained_cogs": True,
            "raw_nisar_hdf5_redownloaded": False,
        },
    }
    manifest_path = output_dir / "cross_sensor_replay_manifest.json"
    manifest_path.write_text(
        json.dumps(replay_manifest, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return {
        "status": report.get("status"),
        "observation_date": observation_date.isoformat(),
        "selected_dates": selected_dates,
        "sentinel2_observation": report.get("observation"),
        "spatial_support": report.get("spatial_support"),
        "metrics": report.get("metrics"),
        "replay_manifest": str(manifest_path),
        "warnings": report.get("warnings", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-dir", required=True, type=Path)
    parser.add_argument("--prepared-dir", required=True, type=Path)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--observation-date", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-day-offset", type=int, default=3)
    parser.add_argument("--max-cloud-cover", type=float, default=40.0)
    parser.add_argument("--mndwi-threshold", type=float, default=0.0)
    parser.add_argument("--minimum-common-support", type=float, default=0.80)
    args = parser.parse_args()
    try:
        summary = run_replay(
            products_dir=args.products_dir,
            prepared_dir=args.prepared_dir,
            source_run_id=args.source_run_id,
            observation_date=date.fromisoformat(args.observation_date),
            output_dir=args.output_dir,
            max_day_offset=args.max_day_offset,
            max_cloud_cover=args.max_cloud_cover,
            mndwi_threshold=args.mndwi_threshold,
            minimum_common_support=args.minimum_common_support,
        )
        print("RIVERSHIFT_CROSS_SENSOR_STATUS=" + str(summary["status"]))
        print("RIVERSHIFT_CROSS_SENSOR_OBSERVATION_DATE=" + summary["observation_date"])
        print("RIVERSHIFT_CROSS_SENSOR_NISAR_DATES=" + ",".join(summary["selected_dates"]))
        obs = summary.get("sentinel2_observation") or {}
        print("RIVERSHIFT_SENTINEL2_ITEM_ID=" + str(obs.get("sentinel2_item_id") or "not-found"))
        print("RIVERSHIFT_SENTINEL2_DATE=" + str(obs.get("sentinel2_date") or "not-found"))
        print("RIVERSHIFT_SENTINEL2_CLOUD_COVER=" + str(obs.get("cloud_cover_percent")))
        support = summary.get("spatial_support") or {}
        print("RIVERSHIFT_CROSS_SENSOR_COMMON_SUPPORT=" + str(support.get("common_support_fraction")))
        metrics = summary.get("metrics")
        if isinstance(metrics, dict):
            for name in ("scl_water_class", "mndwi_water_class"):
                values = metrics.get(name) or {}
                print(f"RIVERSHIFT_SENTINEL2_{name.upper()}_F1=" + str(values.get("f1_score")))
                print(f"RIVERSHIFT_SENTINEL2_{name.upper()}_IOU=" + str(values.get("intersection_over_union")))
        else:
            print("RIVERSHIFT_SENTINEL2_METRICS=NOT_AVAILABLE")
        print("RIVERSHIFT_CROSS_SENSOR_REPLAY_MANIFEST=" + summary["replay_manifest"])
        for warning in summary.get("warnings", []):
            print("RIVERSHIFT_CROSS_SENSOR_WARNING=" + str(warning)[:300])
        return 0
    except (ReplayError, CrosscheckError, OSError, ValueError) as exc:
        detail = str(exc).strip() or type(exc).__name__
        print("RIVERSHIFT_CROSS_SENSOR_REPLAY_ERROR=" + detail[:300], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
