#!/usr/bin/env python3
"""Store Sentinel-2 reference candidates privately and run the RiverShift validator.

The optical rasters are cross-sensor candidates, not ground truth. The existing
independent-reference runner remains the authority for the NISAR source manifest,
date offset, source checksums and common-support release gates.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from drive_upload_adapter import (
    DriveClient,
    DriveUploadError,
    RIVERSHIFT_STORAGE_FOLDER_NAME,
    load_drive_config,
)
from validate_independent_reference import validate as validate_independent_reference


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read required JSON {path.name}: {type(exc).__name__}.") from None
    if not isinstance(value, dict):
        raise ValueError(f"Required JSON {path.name} must contain an object.")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _folder_component(value: str, *, maximum: int = 64) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")
    if not normalized:
        raise ValueError("Could not build a safe Google Drive folder name from the Sentinel-2 datatake.")
    return normalized[:maximum]


def _upload_checked(client: DriveClient, path: Path, folder_id: str, stage: str) -> dict[str, Any]:
    print(f"RIVERSHIFT_REFERENCE_DRIVE_STAGE={stage}:START file={path.name}", flush=True)
    receipt = client.upload_file(path, folder_id)
    if receipt.get("status") != "PASS" or receipt.get("remote_md5") != receipt.get("md5"):
        raise DriveUploadError(f"Google Drive checksum verification did not pass for {path.name}.")
    print(
        "RIVERSHIFT_REFERENCE_DRIVE_STAGE="
        + f"{stage}:PASS file={path.name} bytes={receipt.get('bytes')} "
        + f"drive_file_id={receipt.get('drive_file_id')}",
        flush=True,
    )
    return receipt


def run_pipeline(
    *,
    crosscheck_dir: Path,
    prepared_dir: Path,
    api_base_url: str,
    output_dir: Path,
    maximum_date_offset_days: int = 3,
    minimum_common_support_fraction: float = 0.80,
    block_size_pixels: int = 64,
    bootstrap_replicates: int = 500,
) -> dict[str, Any]:
    report_path = crosscheck_dir / "sentinel2_cross_sensor_agreement.json"
    scl_path = crosscheck_dir / "reference-scl-water.tif"
    mndwi_path = crosscheck_dir / "reference-mndwi-water.tif"
    report = _read_json(report_path)
    prepared = _read_json(prepared_dir / "prepared.json")
    observation = report.get("observation") or {}
    artifacts = report.get("reference_artifacts") or {}
    source_job_id = str(prepared.get("job_id") or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", source_job_id):
        raise ValueError("The retained prepared manifest does not contain a valid source RiverShift job UUID.")
    if report.get("status") not in {"CROSS_SENSOR_AGREEMENT_SCREEN", "INSUFFICIENT_OPTICAL_SPATIAL_SUPPORT"}:
        raise ValueError(
            "No eligible Sentinel-2 acquisition was selected; no independent reference GeoTIFF can be published."
        )
    reference_date = str(observation.get("sentinel2_date") or "")
    date.fromisoformat(reference_date)
    item_ids = observation.get("sentinel2_item_ids") or []
    datatake_id = str(observation.get("sentinel2_datatake_id") or "")
    if not item_ids or not datatake_id:
        raise ValueError("Sentinel-2 item IDs and datatake ID are required for a traceable reference.")
    if not scl_path.is_file() or not mndwi_path.is_file():
        raise ValueError("The expected Sentinel-2 SCL and MNDWI GeoTIFF candidates are missing.")

    for key, path in (("scl_water", scl_path), ("mndwi_water", mndwi_path)):
        receipt = artifacts.get(key)
        if not isinstance(receipt, dict) or receipt.get("sha256") != _sha256(path):
            raise ValueError(f"Sentinel-2 reference GeoTIFF checksum does not match the replay report: {path.name}.")

    workflow_run_id = re.sub(r"[^0-9]", "", __import__("os").environ.get("GITHUB_RUN_ID", "")) or "local"
    workflow_attempt = re.sub(r"[^0-9]", "", __import__("os").environ.get("GITHUB_RUN_ATTEMPT", "")) or "1"
    datatake_key = hashlib.sha256(datatake_id.encode("utf-8")).hexdigest()[:10]
    dated_folder_name = f"{reference_date}-{datatake_key}"
    workflow_folder_name = f"run-{workflow_run_id}-attempt-{workflow_attempt}"

    drive = DriveClient(load_drive_config())
    drive.verify_authenticated_account()
    root_folder = drive.find_or_create_folder(RIVERSHIFT_STORAGE_FOLDER_NAME, drive.config.parent_folder_id)
    drive.require_private_folder(root_folder)
    job_folder = drive.find_or_create_folder(source_job_id, root_folder)
    drive.require_private_folder(job_folder)
    candidate_root = drive.find_or_create_folder("sentinel2-reference-candidates", job_folder)
    drive.require_private_folder(candidate_root)
    dated_folder = drive.find_or_create_folder(dated_folder_name, candidate_root)
    drive.require_private_folder(dated_folder)
    output_folder = drive.find_or_create_folder(workflow_folder_name, dated_folder)
    drive.require_private_folder(output_folder)

    upload_receipts: dict[str, dict[str, Any]] = {}
    for key, path in (("scl_water", scl_path), ("mndwi_water", mndwi_path)):
        upload_receipts[key] = _upload_checked(drive, path, output_folder, f"upload_{key}")
        artifacts[key]["drive_file_id"] = upload_receipts[key]["drive_file_id"]
        artifacts[key]["drive_upload"] = {
            "status": upload_receipts[key]["status"],
            "bytes": upload_receipts[key]["bytes"],
            "md5": upload_receipts[key]["md5"],
            "remote_md5": upload_receipts[key]["remote_md5"],
            "folder": "RiverShift/<job-id>/sentinel2-reference-candidates/<date-datatake>/run-<workflow-run>",
        }

    report["reference_artifacts"] = artifacts
    report["private_storage"] = {
        "status": "PASS",
        "provider": "Google Drive",
        "root_folder": RIVERSHIFT_STORAGE_FOLDER_NAME,
        "job_folder_id": job_folder,
        "candidate_folder_id": output_folder,
        "retention": "private owner-controlled Drive folder; no public permission created",
    }
    report["quality"] = {
        **(report.get("quality") or {}),
        "release_status": "PROVISIONAL",
        "interpretation": "CROSS_SENSOR_REFERENCE_CANDIDATES_ONLY_NOT_GROUND_TRUTH",
    }
    _write_json(report_path, report)
    report_upload = _upload_checked(drive, report_path, output_folder, "upload_sentinel2_report")

    source_description = (
        "Copernicus Sentinel-2 L2A via Microsoft Planetary Computer STAC; "
        f"platform={observation.get('platform')}; datatake={datatake_id}; "
        f"items={','.join(str(value) for value in item_ids)}"
    )
    validation_specs = [
        (
            "scl",
            upload_receipts["scl_water"]["drive_file_id"],
            str((artifacts.get("scl_water") or {}).get("classification_method") or ""),
        ),
        (
            "mndwi",
            upload_receipts["mndwi_water"]["drive_file_id"],
            str((artifacts.get("mndwi_water") or {}).get("classification_method") or ""),
        ),
    ]
    results: dict[str, dict[str, Any]] = {}
    validation_reports: dict[str, dict[str, Any]] = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, reference_file_id, method in validation_specs:
        result_path = output_dir / f"independent_reference_validation_{key}.json"
        work_dir = output_dir / f"work-{key}"
        args = argparse.Namespace(
            source_job_id=source_job_id,
            api_base_url=api_base_url,
            reference_drive_file_id=reference_file_id,
            reference_source=source_description,
            reference_date=reference_date,
            reference_method=method,
            maximum_date_offset_days=maximum_date_offset_days,
            minimum_common_support_fraction=minimum_common_support_fraction,
            block_size_pixels=block_size_pixels,
            bootstrap_replicates=bootstrap_replicates,
            random_seed=42,
            work_dir=work_dir,
            output=result_path,
        )
        print(f"RIVERSHIFT_SENTINEL2_INDEPENDENT_VALIDATION={key.upper()}:START", flush=True)
        try:
            result = validate_independent_reference(args)
            quality = result.get("quality") or {}
            results[key] = {
                "status": quality.get("status", "UNKNOWN"),
                "release_status": quality.get("release_status", "PROVISIONAL"),
                "reference_date": reference_date,
                "target_observation_date": (result.get("reference") or {}).get("target_observation_date"),
                "temporal_offset_days": (result.get("reference") or {}).get("temporal_offset_days"),
                "common_support_fraction": (result.get("reference") or {}).get("common_support_fraction"),
                "metrics": result.get("metrics"),
                "report_file": result_path.name,
                "report_sha256": _sha256(result_path),
                "independence_verified": False,
            }
            validation_reports[key] = _upload_checked(
                drive, result_path, output_folder, f"upload_validation_{key}"
            )
            print(f"RIVERSHIFT_SENTINEL2_INDEPENDENT_VALIDATION={key.upper()}:METRICS_COMPUTED_REVIEW_REQUIRED", flush=True)
        except Exception as exc:
            results[key] = {
                "status": "NO_SCORE_OR_VALIDATION_ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
                "reference_date": reference_date,
                "independence_verified": False,
            }
            print(
                f"RIVERSHIFT_SENTINEL2_INDEPENDENT_VALIDATION={key.upper()}:BLOCKED "
                f"error_type={type(exc).__name__} detail={str(exc)[:400]}",
                flush=True,
            )

    passed = all(
        row.get("status") == "VALIDATION_METRICS_COMPUTED_REVIEW_REQUIRED"
        for row in results.values()
    ) and len(results) == 2
    status_payload = {
        "schema_version": 1,
        "status": "METRICS_COMPUTED_REVIEW_REQUIRED" if passed else "BLOCKED_NO_SCORE_OR_REVIEW_FAILURE",
        "source_run_id": str(prepared.get("source_workflow_run_id") or "41803576163"),
        "source_job_id": source_job_id,
        "nisar_requested_observation_date": str(report.get("requested_observation_date") or ""),
        "sentinel2_observation_date": reference_date,
        "sentinel2_item_ids": item_ids,
        "drive_folder_id": output_folder,
        "reference_uploads": upload_receipts,
        "independent_validation": results,
        "validation_report_uploads": validation_reports,
        "cross_sensor_report_drive_upload": report_upload,
        "release_status": "PROVISIONAL",
        "independence_verified": False,
        "review_required": True,
        "notes": [
            "SCL and MNDWI are alternate Sentinel-2 labels from the same optical datatake, not two independent field references.",
            "The validator checks the retained RiverShift during_water_mask date, provenance checksum and 80% common-support gate.",
            "Passing numeric metrics does not independently certify Sentinel-2 labels, hydrological-stage equivalence, flood causality or geomorphic change.",
        ],
    }
    status_path = output_dir / "sentinel2_reference_validation_status.json"
    _write_json(status_path, status_payload)
    status_upload = _upload_checked(drive, status_path, output_folder, "upload_validation_status")
    status_payload["status_report_drive_upload"] = status_upload
    receipt_path = output_dir / "sentinel2_reference_drive_receipt.json"
    _write_json(receipt_path, status_payload)
    receipt_upload = _upload_checked(drive, receipt_path, output_folder, "upload_drive_receipt")

    print("RIVERSHIFT_SENTINEL2_REFERENCE_DRIVE_FOLDER_ID=" + output_folder, flush=True)
    print("RIVERSHIFT_SENTINEL2_REFERENCE_DATE=" + reference_date, flush=True)
    print("RIVERSHIFT_SENTINEL2_REFERENCE_UPLOAD=PASS", flush=True)
    print("RIVERSHIFT_SENTINEL2_INDEPENDENT_VALIDATION_STATUS=" + status_payload["status"], flush=True)
    print("RIVERSHIFT_SENTINEL2_RELEASE_STATUS=PROVISIONAL", flush=True)
    print("RIVERSHIFT_SENTINEL2_DRIVE_RECEIPT=" + str(receipt_path), flush=True)
    if not passed:
        raise ValueError(
            "Independent validation did not produce both review-required metric sets; "
            "inspect sentinel2_reference_validation_status.json. No PASS release is permitted."
        )
    return status_payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crosscheck-dir", required=True, type=Path)
    parser.add_argument("--prepared-dir", required=True, type=Path)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--maximum-date-offset-days", type=int, default=3)
    parser.add_argument("--minimum-common-support-fraction", type=float, default=0.80)
    parser.add_argument("--block-size-pixels", type=int, default=64)
    parser.add_argument("--bootstrap-replicates", type=int, default=500)
    args = parser.parse_args()
    try:
        run_pipeline(
            crosscheck_dir=args.crosscheck_dir,
            prepared_dir=args.prepared_dir,
            api_base_url=args.api_base_url,
            output_dir=args.output_dir,
            maximum_date_offset_days=args.maximum_date_offset_days,
            minimum_common_support_fraction=args.minimum_common_support_fraction,
            block_size_pixels=args.block_size_pixels,
            bootstrap_replicates=args.bootstrap_replicates,
        )
        return 0
    except (DriveUploadError, OSError, ValueError) as exc:
        print(f"RIVERSHIFT_SENTINEL2_REFERENCE_PIPELINE=FAIL error_type={type(exc).__name__} detail={str(exc)[:600]}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
