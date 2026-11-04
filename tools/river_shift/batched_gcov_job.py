#!/usr/bin/env python3
"""Run RiverShift as bounded 15-runner product batches.

The prepare and assembly phases are single-runner orchestration. Every selected
GCOV granule is downloaded, inspected and AOI-exported on its own GitHub-hosted
runner. Batch barriers ensure batch N+1 does not begin until all jobs in batch N
have completed. Raw multi-GB HDF5 files are never uploaded as Actions artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Any

from process_gcov_job import (
    MAX_SELECTED_GRANULES,
    JobCallbacks,
    WorkerFailure,
    _build_manifest,
    _callback_artifacts,
    _co_register,
    _copy_result_files,
    _ensure_credentials,
    _log_worker_stage,
    _mosaic_date_rasters,
    _metric_crs,
    _read_input,
    _product_date,
    _configure_earthdata_credentials,
    build_source_granule_manifest,
    create_web_previews,
    require_worker_source_provenance,
    run_step,
    select_covering_granules,
    select_event_compatible_group,
    select_general_compatible_group,
    generalize_flood_result,
    generalize_morphology_result,
    sha256_file,
)
from drive_upload_adapter import DriveUploadError, upload_validated_results
from river_shift.overlap_audit import audit_candidate_mask_overlap


BATCH_SIZE = 15
MAX_BATCHES = (MAX_SELECTED_GRANULES + BATCH_SIZE - 1) // BATCH_SIZE
PREPARED_DIR = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared"))
PRODUCT_OUTPUT_DIR = Path(os.environ.get("RIVERSHIFT_PRODUCT_OUTPUT_DIR", "product-output"))
PRODUCT_ARTIFACTS_DIR = Path(os.environ.get("RIVERSHIFT_PRODUCT_ARTIFACTS_DIR", "product-artifacts"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise WorkerFailure("BATCH_ARTIFACT_INVALID", f"The {label} artifact is missing or invalid.") from None
    if not isinstance(value, dict):
        raise WorkerFailure("BATCH_ARTIFACT_INVALID", f"The {label} artifact has an unexpected data shape.")
    return value


def _write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    delimiter = "RIVERSHIFT_" + hashlib.sha256(
        f"{name}:{time.monotonic_ns()}".encode("utf-8")
    ).hexdigest()[:24]
    with Path(output_path).open("a", encoding="utf-8") as stream:
        stream.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def _write_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as stream:
        stream.write(markdown.rstrip() + "\n")


def _batch_matrix(rows: list[dict[str, Any]], batch_number: int, batch_count: int, total_products: int) -> dict[str, Any]:
    include = []
    for position, row in enumerate(rows, start=1):
        include.append({
            "granule_name": row["granule_name"],
            "acquisition_date": row["acquisition_date"],
            "batch_number": batch_number,
            "batch_count": batch_count,
            "product_index": ((batch_number - 1) * BATCH_SIZE) + position,
            "total_products": total_products,
        })
    return {"include": include}


def _write_batch_outputs(batches: list[list[dict[str, Any]]], sequence: int, total_products: int) -> None:
    batch_count = len(batches)
    for index in range(MAX_BATCHES):
        rows = batches[index] if index < batch_count else []
        matrix = _batch_matrix(rows, index + 1, batch_count, total_products)
        _write_output(f"batch_{index + 1}_matrix", json.dumps(matrix, separators=(",", ":")))
        _write_output(f"batch_{index + 1}_count", str(len(rows)))
    _write_output("batch_count", str(batch_count))
    _write_output("selected_count", str(total_products))
    _write_output("callback_sequence", str(sequence))


def _prepare_job(request: dict[str, Any], callbacks: JobCallbacks) -> None:
    started = time.monotonic()
    # Child scripts execute with cwd=tools/river_shift; make output paths absolute
    # so discovery writes into the root-level folder uploaded by Actions.
    output_dir = Path(os.environ.get("RIVERSHIFT_PREPARE_OUTPUT_DIR", "prepared-output")).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    catalogue_path = output_dir / "gcov-catalogue-manifest.json"
    audit_path = output_dir / "gcov-time-series-audit.json"
    selection_path = output_dir / "selected-observations.json"
    selected_catalogue_path = output_dir / "selected-catalogue.json"

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
        batch_size=BATCH_SIZE,
        maximum_selected_granules=MAX_SELECTED_GRANULES,
    )

    _log_worker_stage("preflight", "START", stage_detail="Earthdata credentials and private Drive destination")
    _ensure_credentials()
    _log_worker_stage("preflight", "PASS", drive_root="RiverShift", parent_variable="GOOGLE_DRIVE_PARENT_FOLDER_ID")

    callbacks.send("running", "catalogue_discovery")
    discovery_command = [
        sys.executable, "discover_gcov_products.py",
        "--aoi-wkt", request["aoi_wkt"],
        "--start-date", request["start_date"].isoformat(),
        "--end-date", request["end_date"].isoformat(),
        "--maturity", request["maturity"],
        "--frame-coverage", request["frame_coverage"],
        "--max-results", "2000",
        "--out", str(catalogue_path),
    ]
    if request["main_band_polarization"]:
        discovery_command.extend(["--main-band-polarization", request["main_band_polarization"]])
    if request["flight_direction"]:
        discovery_command.extend(["--flight-direction", request["flight_direction"]])
    run_step("catalogue discovery", discovery_command)
    manifest = _read_json(catalogue_path, "GCOV catalogue")
    submitted = set(request["granule_names"])
    catalogue_rows = [
        row for row in manifest.get("products", [])
        if isinstance(row, dict) and row.get("granule_name") in submitted
    ]
    returned = {row.get("granule_name") for row in catalogue_rows}
    if returned != submitted:
        missing = sorted(submitted - returned)
        _log_worker_stage(
            "exact_catalogue_match", "FAIL",
            submitted_count=len(submitted), returned_count=len(returned),
            missing_count=len(missing), missing_granules=missing[:10],
        )
        raise WorkerFailure(
            "CATALOGUE_CHANGED",
            f"NASA CMR no longer returns {len(missing)} exact granules from the accepted request.",
        )
    _log_worker_stage(
        "exact_catalogue_match", "PASS",
        submitted_count=len(submitted), returned_count=len(returned),
    )
    manifest["products"] = catalogue_rows
    manifest["product_count"] = len(catalogue_rows)
    manifest.setdefault("query", {})["maturity"] = request["maturity"]
    _write_json(catalogue_path, manifest)
    _write_json(selected_catalogue_path, {"products": catalogue_rows})

    callbacks.send("running", "acquisition_compatibility_audit")
    run_step("acquisition compatibility audit", [
        sys.executable, "audit_gcov_acquisitions.py",
        "--catalogue", str(catalogue_path),
        "--minimum-dates", "4",
        "--minimum-aoi-coverage-percent", "90",
        "--frequency", request["frequency"],
        "--term", request["term"],
        "--out", str(audit_path),
    ])
    audit = _read_json(audit_path, "acquisition compatibility audit")
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
    ordered_products: list[dict[str, Any]] = []
    date_by_name: dict[str, str] = {}
    for observed_date in dates:
        selected = select_covering_granules(
            request["aoi"],
            catalogue_rows,
            rows_by_date[observed_date]["granule_names"],
            metric_crs,
        )
        products_by_date[observed_date] = selected
        for product in selected:
            name = product["granule_name"]
            if name in date_by_name and date_by_name[name] != observed_date:
                raise WorkerFailure("DUPLICATE_GRANULE_ASSIGNMENT", "One GCOV granule was assigned to more than one acquisition date.")
            if name not in date_by_name:
                ordered_products.append(product)
                date_by_name[name] = observed_date

    selected_product_names = list(date_by_name)
    if not selected_product_names:
        raise WorkerFailure("NO_SELECTED_GRANULES", "The AOI coverage audit selected no exact NISAR granules.")
    if len(selected_product_names) > MAX_SELECTED_GRANULES:
        raise WorkerFailure(
            "REQUEST_TOO_LARGE",
            f"The science selection needs {len(selected_product_names)} GCOV granules; the current audited cap is {MAX_SELECTED_GRANULES}.",
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
        "granule_names": selected_product_names,
        "aoi_coverage_gate_percent": 90,
        "catalogue_audit_status": audit.get("status"),
        "raster_grid": "all dates reprojected with nearest-neighbour to the first selected observation grid",
        "release_status": "PROVISIONAL",
    }
    _write_json(selection_path, selection)

    batch_rows: list[dict[str, Any]] = []
    for index, product in enumerate(ordered_products, start=1):
        batch_rows.append({
            "granule_name": product["granule_name"],
            "acquisition_date": date_by_name[product["granule_name"]],
            "product_index": index,
        })
    batches = [
        batch_rows[offset:offset + BATCH_SIZE]
        for offset in range(0, len(batch_rows), BATCH_SIZE)
    ]
    if len(batches) > MAX_BATCHES:
        raise WorkerFailure("REQUEST_TOO_LARGE", f"The selected product set exceeds the {MAX_BATCHES}-batch safety ceiling.")

    prepared = {
        "schema_version": 1,
        "job_id": request["job_id"],
        "request_fingerprint": request["fingerprint"],
        "request": {
            "aoi_wkt": request["aoi_wkt"],
            "start_date": request["start_date"].isoformat(),
            "end_date": request["end_date"].isoformat(),
            "analysis_mode": request["analysis_mode"],
            "event_date": request["event_date"].isoformat() if request["event_date"] else None,
            "maturity": request["maturity"],
            "main_band_polarization": request["main_band_polarization"],
            "flight_direction": request["flight_direction"],
            "frame_coverage": request["frame_coverage"],
            "frequency": request["frequency"],
            "term": request["term"],
            "threshold_method": request["threshold_method"],
            "threshold_db": request["threshold_db"],
        },
        "dates": dates,
        "analysis_window": event_window,
        "selection": selection,
        "products_by_date": {
            observed_date: [row["granule_name"] for row in rows]
            for observed_date, rows in products_by_date.items()
        },
        "selected_product_names": selected_product_names,
        "date_by_name": date_by_name,
        "batches": batches,
    }
    _write_json(output_dir / "prepared.json", prepared)

    _log_worker_stage(
        "observation_selection", "PASS",
        selected_date_count=len(dates),
        selected_granule_count=len(selected_product_names),
        selected_dates=dates,
        granules_per_date={observed_date: len(rows) for observed_date, rows in products_by_date.items()},
    )
    _log_worker_stage(
        "batch_plan", "PASS",
        batch_size=BATCH_SIZE,
        batch_count=len(batches),
        batch_product_counts=[len(rows) for rows in batches],
        total_selected_products=len(selected_product_names),
        parallel_runners_per_batch=min(BATCH_SIZE, len(selected_product_names)),
        note="Each runner downloads and processes one exact granule; the next batch waits for this batch to finish.",
    )

    callbacks.send("running", "exact_product_download")
    callbacks.send("running", "hdf5_inspection_and_aoi_extraction")
    prepared["callback_sequence"] = callbacks.sequence
    _write_json(output_dir / "prepared.json", prepared)
    _write_batch_outputs(batches, callbacks.sequence, len(selected_product_names))
    _log_worker_stage(
        "preparation_complete", "PASS",
        prepared_files=5,
        callback_sequence=callbacks.sequence,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


def _product_context(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "granule_name": product["granule_name"],
        "acquisition_date": product["acquisition_date"],
        "batch_number": int(product["batch_number"]),
        "batch_count": int(product["batch_count"]),
        "product_index": int(product["product_index"]),
        "total_products": int(product["total_products"]),
    }


def _product_result_path(output_dir: Path) -> Path:
    return output_dir / "worker-result.json"


def _write_product_failure(
    output_dir: Path,
    *,
    granule_name: str,
    acquisition_date: str,
    batch_number: int,
    product_index: int,
    total_products: int,
    started: float,
    code: str,
    message: str,
    failed_stage: str,
) -> dict[str, Any]:
    result = {
        "schema_version": 1,
        "status": "FAIL",
        "job_id": os.environ.get("RIVERSHIFT_JOB_ID"),
        "request_fingerprint": os.environ.get("RIVERSHIFT_REQUEST_FINGERPRINT"),
        "granule_name": granule_name,
        "acquisition_date": acquisition_date,
        "batch_number": batch_number,
        "product_index": product_index,
        "total_products": total_products,
        "retry_attempt": int(os.environ.get("RIVERSHIFT_RETRY_ATTEMPT", "0") or 0),
        "attempt_number": int(os.environ.get("RIVERSHIFT_RETRY_ATTEMPT", "0") or 0) + 1,
        "error_code": code,
        "error_message": message[:500],
        "failed_stage": failed_stage,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "files": [],
    }
    _write_json(_product_result_path(output_dir), result)
    _log_worker_stage(
        "product_worker_completion", "FAIL",
        granule_name=granule_name,
        acquisition_date=acquisition_date,
        batch_number=batch_number,
        product_index=product_index,
        total_products=total_products,
        retry_attempt=result["retry_attempt"],
        attempt_number=result["attempt_number"],
        error_code=code,
        failed_stage=failed_stage,
        error_message=message[:500],
        elapsed_seconds=result["elapsed_seconds"],
    )
    return result


def _product_catalogue_path(prepared_dir: Path) -> Path:
    """Return an absolute catalogue path for child tools executed with cwd=TOOLS."""
    catalogue_path = (prepared_dir / "selected-catalogue.json").resolve()
    if not catalogue_path.is_file():
        raise WorkerFailure("BATCH_ARTIFACT_INVALID", "The selected catalogue artifact is missing from the prepared workspace.")
    return catalogue_path


def _run_product_worker() -> int:
    started = time.monotonic()
    granule_name = os.environ.get("RIVERSHIFT_GRANULE_NAME", "").strip()
    acquisition_date = os.environ.get("RIVERSHIFT_ACQUISITION_DATE", "").strip()
    batch_number = int(os.environ.get("RIVERSHIFT_BATCH_NUMBER", "0") or 0)
    batch_count = int(os.environ.get("RIVERSHIFT_BATCH_COUNT", "0") or 0)
    product_index = int(os.environ.get("RIVERSHIFT_PRODUCT_INDEX", "0") or 0)
    total_products = int(os.environ.get("RIVERSHIFT_TOTAL_PRODUCTS", "0") or 0)
    retry_attempt = int(os.environ.get("RIVERSHIFT_RETRY_ATTEMPT", "0") or 0)
    attempt_number = retry_attempt + 1
    if not granule_name or not acquisition_date:
        raise WorkerFailure("INVALID_REQUEST", "A matrix job requires an exact granule name and acquisition date.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{10,250}", granule_name):
        raise WorkerFailure("INVALID_REQUEST", "The matrix granule name contains unsupported characters.")

    output_root = Path(os.environ.get("RIVERSHIFT_PRODUCT_OUTPUT_DIR", "product-output"))
    output_dir = output_root / granule_name
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    context = {
        "granule_name": granule_name,
        "acquisition_date": acquisition_date,
        "batch_number": batch_number,
        "batch_count": batch_count,
        "product_index": product_index,
        "total_products": total_products,
        "retry_attempt": retry_attempt,
        "attempt_number": attempt_number,
    }
    wave_label = "delayed retry wave" if retry_attempt else f"batch {batch_number:02d}/{batch_count:02d}"
    print(
        f"::group::RiverShift {wave_label} · attempt {attempt_number}/4 · "
        f"product {product_index}/{total_products} · {acquisition_date} · {granule_name}",
        flush=True,
    )
    _log_worker_stage("product_worker_startup", "START", **context)
    current_stage = "prepared_manifest_validation"
    try:
        prepared_dir = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared")).resolve()
        prepared = _read_json(prepared_dir / "prepared.json", "prepared selection")
        if prepared.get("job_id") != os.environ.get("RIVERSHIFT_JOB_ID"):
            raise WorkerFailure("REQUEST_MISMATCH", "This product runner received a prepared artifact for a different job.")
        if prepared.get("request_fingerprint") != os.environ.get("RIVERSHIFT_REQUEST_FINGERPRINT"):
            raise WorkerFailure("REQUEST_MISMATCH", "This product runner received a stale or mismatched request fingerprint.")
        if granule_name not in prepared.get("selected_product_names", []):
            raise WorkerFailure("REQUEST_MISMATCH", "The requested granule is not part of the audited scientific selection.")
        if prepared.get("date_by_name", {}).get(granule_name) != acquisition_date:
            raise WorkerFailure("REQUEST_MISMATCH", "The granule acquisition date does not match the prepared observation date.")

        catalogue_path = _product_catalogue_path(prepared_dir)
        product_matches = [
            row for row in _read_json(catalogue_path, "selected catalogue").get("products", [])
            if row.get("granule_name") == granule_name
        ]
        if len(product_matches) != 1:
            raise WorkerFailure("CATALOGUE_CHANGED", "The prepared exact product does not occur exactly once in the selected catalogue.")
        product = product_matches[0]
        request = prepared["request"]
        current_stage = "earthdata_authentication"
        _log_worker_stage("earthdata_credentials", "START", **context)
        _configure_earthdata_credentials()
        _log_worker_stage("earthdata_credentials", "PASS", authentication_mode="bearer_token_or_netrc", **context)

        runner_root = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / (
            f"river-shift-product-{prepared['job_id']}-{granule_name}"
        )
        if runner_root.exists():
            shutil.rmtree(runner_root)
        raw_dir = runner_root / "raw"
        raster_dir = runner_root / "rasters"
        raw_dir.mkdir(parents=True)
        raster_dir.mkdir(parents=True)

        current_stage = "exact_product_download"
        _log_worker_stage("product_download", "START", **context)
        run_step(
            "exact-product download",
            [
                sys.executable, "download_gcov_product.py",
                "--catalogue", str(catalogue_path),
                "--granule-name", granule_name,
                "--out-dir", str(raw_dir),
            ],
            context={**context, "stage_index": "1/3"},
        )
        product_path = raw_dir / f"{granule_name}.h5"
        receipt_path = raw_dir / f"{granule_name}.download.json"
        if not product_path.is_file() or not receipt_path.is_file():
            raise WorkerFailure("DOWNLOAD_RECEIPT_MISSING", "The exact download step did not produce the HDF5 file and its checksum receipt.")
        receipt = _read_json(receipt_path, "download receipt")
        _log_worker_stage(
            "product_download", "PASS",
            downloaded_bytes=receipt.get("size_bytes"),
            source_sha256=receipt.get("sha256"),
            **context,
        )
        _log_worker_stage(
            "product_download_receipt", "PASS",
            downloaded_bytes=receipt.get("size_bytes"),
            source_sha256=receipt.get("sha256"),
            **context,
        )

        current_stage = "hdf5_inspection"
        _log_worker_stage("hdf5_inspection", "START", product_file=f"{granule_name}.h5", **context)
        inventory_path = raw_dir / f"{granule_name}.gcov_inventory.json"
        run_step(
            "NISAR HDF5 inspection",
            [
                sys.executable, "inspect_gcov_product.py",
                "--product", str(product_path),
                "--out", str(inventory_path),
            ],
            context={**context, "stage_index": "2/3"},
        )
        inventory = _read_json(inventory_path, "HDF5 inventory")
        _log_worker_stage("hdf5_inspection", "PASS", gdal_version=inventory.get("gdal_version"), **context)
        current_stage = "hdf5_layer_validation"
        _log_worker_stage("hdf5_layer_validation", "START", requested_frequency=request["frequency"], requested_term=request["term"], **context)
        available = {
            (row.get("frequency"), row.get("term"))
            for row in inventory.get("available_diagonal_terms", [])
            if isinstance(row, dict)
        }
        if (request["frequency"], request["term"]) not in available:
            raise WorkerFailure(
                "GCOV_LAYER_UNAVAILABLE",
                f"The selected HDF5 product does not contain {request['frequency']}/{request['term']}.",
            )
        _log_worker_stage(
            "hdf5_layer_validation", "PASS",
            gdal_version=inventory.get("gdal_version"),
            requested_frequency=request["frequency"],
            requested_term=request["term"],
            **context,
        )

        current_stage = "aoi_raster_extraction"
        _log_worker_stage("aoi_raster_extraction", "START", **context)
        raster_path = raster_dir / f"{granule_name}.tif"
        run_step(
            "AOI raster extraction",
            [
                sys.executable, "export_gcov_layer.py",
                "--product", str(product_path),
                "--frequency", request["frequency"],
                "--term", request["term"],
                "--maturity", request["maturity"],
                "--aoi-wkt", request["aoi_wkt"],
                "--out", str(raster_path),
            ],
            context={**context, "stage_index": "3/3"},
        )
        metadata_path = raster_path.with_suffix(".metadata.json")
        if not raster_path.is_file() or not metadata_path.is_file():
            raise WorkerFailure("AOI_EXTRACTION_OUTPUT_MISSING", "AOI extraction did not produce the COG and its provenance sidecar.")
        metadata = _read_json(metadata_path, "AOI COG metadata")
        if metadata.get("source_granule_name") != granule_name:
            raise WorkerFailure("SOURCE_PROVENANCE_INVALID", "The exported COG sidecar is not bound to the selected granule.")
        if metadata.get("source_product_sha256") != receipt.get("sha256"):
            raise WorkerFailure("SOURCE_PROVENANCE_INVALID", "The COG source checksum does not match the exact download receipt.")

        _log_worker_stage(
            "aoi_raster_extraction", "PASS",
            output_bytes=raster_path.stat().st_size,
            output_sha256=sha256_file(raster_path),
            source_sha256=receipt.get("sha256"),
            **context,
        )
        current_stage = "product_artifact_preparation"
        _log_worker_stage("product_artifact_preparation", "START", **context)
        product_path.unlink(missing_ok=True)
        runner_files = [
            raster_path,
            metadata_path,
            receipt_path,
            inventory_path,
        ]
        files = []
        for source in runner_files:
            destination = output_dir / source.name
            shutil.copy2(source, destination)
            files.append({
                "name": destination.name,
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
            })
        result = {
            "schema_version": 1,
            "status": "PASS",
            "job_id": prepared["job_id"],
            "request_fingerprint": prepared["request_fingerprint"],
            **context,
            "download_bytes": receipt["size_bytes"],
            "source_sha256": receipt["sha256"],
            "raster_bytes": raster_path.stat().st_size,
            "raster_sha256": sha256_file(raster_path),
            "gdal_version": inventory.get("gdal_version"),
            "files": files,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "runner": os.environ.get("RUNNER_NAME", "github-hosted-runner"),
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        }
        _write_json(_product_result_path(output_dir), result)
        _log_worker_stage(
            "product_artifact_preparation", "PASS",
            artifact_file_count=len(files),
            artifact_bytes=sum(item["bytes"] for item in files),
            **context,
        )
        _log_worker_stage("product_worker_completion", "PASS", **{
            **context,
            "download_bytes": result["download_bytes"],
            "raster_bytes": result["raster_bytes"],
            "elapsed_seconds": result["elapsed_seconds"],
            "source_sha256": result["source_sha256"],
            "raster_sha256": result["raster_sha256"],
        })
        print("::notice::RiverShift product download, HDF5 validation and AOI export passed.", flush=True)
        shutil.rmtree(runner_root, ignore_errors=True)
        return 0
    except WorkerFailure as exc:
        _write_product_failure(
            output_dir,
            granule_name=granule_name,
            acquisition_date=acquisition_date,
            batch_number=batch_number,
            product_index=product_index,
            total_products=total_products,
            started=started,
            code=exc.code,
            message=str(exc),
            failed_stage=current_stage,
        )
        for raw_file in Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).glob(
            f"river-shift-product-*/raw/{granule_name}.h5"
        ):
            raw_file.unlink(missing_ok=True)
        print(f"::error::RiverShift product failed: {exc.code} · {granule_name}", flush=True)
        return 1
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _write_product_failure(
            output_dir,
            granule_name=granule_name,
            acquisition_date=acquisition_date,
            batch_number=batch_number,
            product_index=product_index,
            total_products=total_products,
            started=started,
            code="UNEXPECTED_PRODUCT_ERROR",
            message=f"Unexpected {type(exc).__name__}: {str(exc)[:400]}",
            failed_stage=current_stage,
        )
        print(f"::error::Unexpected RiverShift product failure · {granule_name}", flush=True)
        return 1
    finally:
        print("::endgroup::", flush=True)


def _batch_rows(prepared: dict[str, Any], batch_number: int) -> list[dict[str, Any]]:
    batches = prepared.get("batches")
    if not isinstance(batches, list) or not 1 <= batch_number <= MAX_BATCHES:
        raise WorkerFailure("BATCH_PLAN_INVALID", "The requested batch number is outside the prepared batch plan.")
    if batch_number > len(batches):
        return []
    return batches[batch_number - 1]


def _load_product_results(results_dir: Path) -> dict[str, dict[str, Any]]:
    """Load product receipts from flat first-attempt or wave-scoped retry artifacts."""
    results: dict[str, dict[str, Any]] = {}
    if not results_dir.exists():
        return results
    for result_path in sorted(results_dir.rglob("worker-result.json")):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(result, dict) and isinstance(result.get("granule_name"), str):
            # A product enters a later retry wave only after the previous wave failed.
            # Sorting ensures the latest wave's receipt is authoritative.
            results[result["granule_name"]] = result
    return results


def _product_result_problem(
    prepared: dict[str, Any],
    row: dict[str, Any],
    result: dict[str, Any] | None,
    results_dir: Path,
) -> str | None:
    """Return why a product result is unusable; None means fully verified PASS."""
    name = row["granule_name"]
    if not isinstance(result, dict):
        return "WORKER_RESULT_MISSING"
    if (
        result.get("job_id") != prepared["job_id"]
        or result.get("request_fingerprint") != prepared["request_fingerprint"]
        or result.get("granule_name") != name
        or result.get("acquisition_date") != row["acquisition_date"]
    ):
        return "WORKER_RESULT_IDENTITY_INVALID"
    if result.get("status") != "PASS":
        return str(result.get("error_code") or "PRODUCT_WORKER_FAILED")

    required = {
        f"{name}.tif",
        f"{name}.metadata.json",
        f"{name}.download.json",
        f"{name}.gcov_inventory.json",
    }
    verified: set[str] = set()
    for item in result.get("files", []):
        if not isinstance(item, dict):
            continue
        filename = item.get("name")
        digest = item.get("sha256")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            continue
        retry_attempt = int(result.get("retry_attempt", 0) or 0)
        product_root = results_dir / f"wave-{retry_attempt}" if retry_attempt > 0 else results_dir
        source = product_root / name / filename
        try:
            if source.is_file() and sha256_file(source) == digest:
                verified.add(filename)
        except OSError:
            continue
    if not required.issubset(verified):
        return "PRODUCT_ARTIFACT_MISSING_OR_CHECKSUM_INVALID"
    return None


def _retry_matrix(rows: list[dict[str, Any]], *, retry_attempt: int = 1) -> dict[str, Any]:
    if not 1 <= retry_attempt <= 3:
        raise ValueError("RiverShift retry_attempt must be between 1 and 3.")
    total = len(rows)
    return {
        "include": [
            {
                "granule_name": row["granule_name"],
                "acquisition_date": row["acquisition_date"],
                "batch_number": MAX_BATCHES + retry_attempt,
                "batch_count": 1,
                "product_index": index,
                "total_products": total,
                "retry_attempt": retry_attempt,
            }
            for index, row in enumerate(rows, start=1)
        ]
    }


def _select_retry_rows(
    prepared: dict[str, Any],
    first_attempt_results: dict[str, dict[str, Any]],
    first_attempt_dir: Path,
    *,
    previous_retry_results: dict[str, dict[str, Any]] | None = None,
    previous_retry_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Queue only products without a verified PASS from any earlier attempt."""
    rows = []
    previous_retry_results = previous_retry_results or {}
    for name in prepared["selected_product_names"]:
        row = {"granule_name": name, "acquisition_date": prepared["date_by_name"][name]}
        first_problem = _product_result_problem(
            prepared, row, first_attempt_results.get(name), first_attempt_dir
        )
        if first_problem is None:
            continue

        previous_result = previous_retry_results.get(name)
        previous_problem = None
        if previous_result is not None and previous_retry_dir is not None:
            previous_problem = _product_result_problem(
                prepared, row, previous_result, previous_retry_dir
            )
            if previous_problem is None:
                continue

        row["first_attempt_failure"] = first_problem
        if previous_problem:
            row["previous_retry_failure"] = previous_problem
            row["previous_retry_attempt"] = int(previous_result.get("retry_attempt", 0) or 0)
        rows.append(row)
    return rows


def _report_batch() -> None:
    prepared_dir = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared"))
    prepared = _read_json(prepared_dir / "prepared.json", "prepared selection")
    batch_number = int(os.environ.get("RIVERSHIFT_BATCH_NUMBER", "0") or 0)
    rows = _batch_rows(prepared, batch_number)
    sequence = int(os.environ.get("RIVERSHIFT_CALLBACK_SEQUENCE", "0") or 0)
    if not rows:
        _log_worker_stage("batch_barrier", "SKIP", batch_number=batch_number, reason="no selected products in this batch")
        _write_output("callback_sequence", str(sequence))
        _write_output("batch_success_count", "0")
        _write_output("batch_failure_count", "0")
        return

    results_dir = Path(os.environ.get("RIVERSHIFT_BATCH_RESULTS_DIR", "batch-results"))
    results = _load_product_results(results_dir)
    passed = 0
    failed = 0
    failure_details: list[tuple[str, str]] = []
    for row in rows:
        name = row["granule_name"]
        result = results.get(name)
        if not result:
            failed += 1
            failure_details.append((name, "WORKER_RESULT_MISSING"))
            _log_worker_stage(
                "batch_product_reconciliation", "FAIL",
                batch_number=batch_number,
                granule_name=name,
                acquisition_date=row["acquisition_date"],
                reason="result artifact missing; runner may have failed before artifact upload",
            )
            continue
        valid_identity = (
            result.get("job_id") == prepared["job_id"]
            and result.get("request_fingerprint") == prepared["request_fingerprint"]
            and result.get("granule_name") == name
            and result.get("acquisition_date") == row["acquisition_date"]
        )
        if result.get("status") == "PASS" and valid_identity:
            passed += 1
            _log_worker_stage(
                "batch_product_reconciliation", "PASS",
                batch_number=batch_number,
                granule_name=name,
                acquisition_date=row["acquisition_date"],
                elapsed_seconds=result.get("elapsed_seconds"),
                download_bytes=result.get("download_bytes"),
                raster_bytes=result.get("raster_bytes"),
            )
        else:
            failed += 1
            failure_details.append((name, str(result.get("error_code") or "PRODUCT_RESULT_INVALID")))
            _log_worker_stage(
                "batch_product_reconciliation", "FAIL",
                batch_number=batch_number,
                granule_name=name,
                acquisition_date=row["acquisition_date"],
                failed_stage=result.get("failed_stage", "unknown_stage"),
                error_code=result.get("error_code", "PRODUCT_RESULT_INVALID"),
                error_message=result.get("error_message", "Product result identity or status validation failed."),
            )
    _log_worker_stage(
        "batch_barrier", "PASS" if failed == 0 else "WARN",
        batch_number=batch_number,
        expected=len(rows),
        passed=passed,
        failed=failed,
        next_batch_waits_for_this_barrier=True,
    )

    callbacks = JobCallbacks(
        prepared["job_id"],
        prepared["request_fingerprint"],
        os.environ["RIVERSHIFT_CALLBACK_URL"],
        initial_sequence=sequence,
    )
    callbacks.send(
        "running",
        f"batch_{batch_number:02d}_completed",
        result_summary={
            "batch_number": batch_number,
            "expected_product_count": len(rows),
            "verified_product_count": passed,
            "failed_or_unverifiable_product_count": failed,
            "retry_eligible_count": failed,
        },
    )
    _write_output("callback_sequence", str(callbacks.sequence))
    _write_output("batch_success_count", str(passed))
    _write_output("batch_failure_count", str(failed))
    if failed:
        print(
            f"::warning::Batch {batch_number} reconciliation found {failed}/{len(rows)} failed or unverifiable products; the failures remain eligible for the delayed retry wave.",
            flush=True,
        )
    detail_rows = "\n".join(
        f"| {name} | {reason} |" for name, reason in failure_details[:30]
    ) or "| — | No failed products |"
    _write_step_summary(
        f"## Batch {batch_number} reconciliation\n\n"
        f"- Expected: **{len(rows)}**\n"
        f"- Verified: **{passed}**\n"
        f"- Failed/unverifiable: **{failed}**\n\n"
        "| Product | Outcome |\n|---|---|\n" + detail_rows
    )


def _prepare_retry_wave() -> None:
    prepared_dir = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared"))
    prepared = _read_json(prepared_dir / "prepared.json", "prepared selection")
    first_dir = Path(os.environ.get("RIVERSHIFT_PRODUCT_ARTIFACTS_DIR", "product-artifacts"))
    retry_dir = Path(os.environ.get("RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR", "retry-product-artifacts"))
    retry_attempt = int(os.environ.get("RIVERSHIFT_RETRY_ATTEMPT", "1") or 1)
    first_results = _load_product_results(first_dir)
    previous_retry_results = _load_product_results(retry_dir)
    retry_rows = _select_retry_rows(
        prepared,
        first_results,
        first_dir,
        previous_retry_results=previous_retry_results,
        previous_retry_dir=retry_dir,
    )
    matrix = _retry_matrix(retry_rows, retry_attempt=retry_attempt)
    _write_json(Path("retry-plan") / f"retry-products-wave-{retry_attempt}.json", {
        "job_id": prepared["job_id"],
        "request_fingerprint": prepared["request_fingerprint"],
        "retry_attempt": retry_attempt,
        "products": retry_rows,
    })
    for row in retry_rows:
        _log_worker_stage(
            "delayed_retry_queue", "QUEUE",
            granule_name=row["granule_name"],
            acquisition_date=row["acquisition_date"],
            first_attempt_failure=row["first_attempt_failure"],
            previous_retry_failure=row.get("previous_retry_failure"),
            retry_attempt=retry_attempt,
            runner_refresh=True,
        )
    _log_worker_stage(
        "delayed_retry_plan", "PASS",
        first_attempt_product_count=len(prepared["selected_product_names"]),
        previously_attempted_retry_count=len(previous_retry_results),
        retry_queue_count=len(retry_rows),
        retry_attempt=retry_attempt,
        retry_max_parallel=15,
        retry_policy="up to three delayed retry waves; each wave uses a fresh GitHub-hosted runner",
    )
    retry_matrix_json = json.dumps(matrix, separators=(",", ":"))
    if len(matrix.get("include", [])) != len(retry_rows):
        raise WorkerFailure("RETRY_MATRIX_INVALID", "Retry matrix row count does not match the exact retry queue.")
    retry_names = [row.get("granule_name") for row in matrix["include"]]
    if len(retry_names) != len(set(retry_names)):
        raise WorkerFailure("RETRY_MATRIX_INVALID", "Retry matrix contains duplicate granule identities.")
    _log_worker_stage(
        "delayed_retry_matrix_output", "PASS",
        retry_attempt=retry_attempt,
        retry_queue_count=len(retry_rows),
        matrix_include_count=len(matrix["include"]),
        matrix_json_bytes=len(retry_matrix_json.encode("utf-8")),
        matrix_sha256=hashlib.sha256(retry_matrix_json.encode("utf-8")).hexdigest(),
    )
    _write_output("retry_matrix", retry_matrix_json)
    _write_output("retry_count", str(len(retry_rows)))
    _write_step_summary(
        f"## Delayed retry wave {retry_attempt}\n\n"
        f"- Previously attempted products: **{len(previous_retry_results)}**\n"
        f"- Products queued for this fresh runner wave: **{len(retry_rows)}**\n"
        "- Maximum automatic retries per product: **3**\n"
        "- Parallel retry runners: **15 maximum**"
    )



def _report_retry_wave() -> None:
    prepared_dir = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared")).resolve()
    prepared = _read_json(prepared_dir / "prepared.json", "prepared selection")
    first_dir = Path(os.environ.get("RIVERSHIFT_PRODUCT_ARTIFACTS_DIR", "product-artifacts"))
    retry_dir = Path(os.environ.get("RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR", "retry-product-artifacts"))
    first_results = _load_product_results(first_dir)
    retry_results = _load_product_results(retry_dir)
    original_retry_rows = _select_retry_rows(prepared, first_results, first_dir)

    raw_dispatch = os.environ.get("RIVERSHIFT_RETRY_DISPATCH_STATUSES", "").strip()
    if raw_dispatch:
        dispatch_statuses = [value.strip().lower() for value in raw_dispatch.split(",")]
    else:
        # Backward compatibility for standalone callers/tests using the original
        # one-wave status variable. The newer two optional waves default to the
        # no-queue/success path unless their explicit status is supplied.
        legacy_status = os.environ.get("RIVERSHIFT_RETRY_DISPATCH_STATUS", "success").strip().lower()
        dispatch_statuses = [legacy_status, "success", "success"]
    raw_prepare = os.environ.get("RIVERSHIFT_RETRY_PREPARE_STATUSES", "success,success,success")
    prepare_statuses = [value.strip().lower() for value in raw_prepare.split(",")]
    raw_counts = os.environ.get("RIVERSHIFT_RETRY_COUNTS", "1,0,0")
    retry_counts = [value.strip() for value in raw_counts.split(",")]

    # Wave 1 is required. Waves 2 and 3 may prepare successfully with an empty
    # queue; their dispatch validators still run and must pass.
    setup_failures = []
    for index in range(3):
        prepare_status = prepare_statuses[index] if index < len(prepare_statuses) else "missing"
        dispatch_status = dispatch_statuses[index] if index < len(dispatch_statuses) else "missing"
        try:
            queue_count = int(retry_counts[index]) if index < len(retry_counts) and retry_counts[index] else -1
        except ValueError:
            queue_count = -1
        if prepare_status != "success":
            setup_failures.append(f"wave {index + 1} preparation={prepare_status}")
        elif dispatch_status != "success":
            setup_failures.append(f"wave {index + 1} matrix validation={dispatch_status}")
        elif queue_count < 0:
            setup_failures.append(f"wave {index + 1} retry_count missing or invalid")

    passed = 0
    failed = 0
    failure_details: list[tuple[str, str]] = []
    if setup_failures:
        failed = max(1, len(original_retry_rows))
        failure_details.extend(("retry setup", value) for value in setup_failures)
        _log_worker_stage(
            "delayed_retry_setup", "FAIL",
            setup_failures=setup_failures,
            queued_retry_count=len(original_retry_rows),
            max_retry_waves=3,
        )

    if not setup_failures:
        for row in original_retry_rows:
            result = retry_results.get(row["granule_name"])
            problem = _product_result_problem(prepared, row, result, retry_dir)
            if problem is None:
                passed += 1
                _log_worker_stage(
                    "delayed_retry_reconciliation", "PASS",
                    granule_name=row["granule_name"],
                    acquisition_date=row["acquisition_date"],
                    retry_attempt=int(result.get("retry_attempt", 0) or 0),
                    runner_refresh=True,
                    source_sha256=result.get("source_sha256"),
                    raster_sha256=result.get("raster_sha256"),
                )
            else:
                failed += 1
                failure_details.append((row["granule_name"], problem))
                _log_worker_stage(
                    "delayed_retry_reconciliation", "FAIL",
                    granule_name=row["granule_name"],
                    acquisition_date=row["acquisition_date"],
                    first_attempt_failure=row["first_attempt_failure"],
                    last_retry_attempt=int((result or {}).get("retry_attempt", 0) or 0),
                    retry_failure=problem,
                    retry_error_message=(result or {}).get("error_message", "Retry result artifact missing or invalid."),
                )


    _log_worker_stage(
        "delayed_retry_barrier", "PASS" if failed == 0 else "FAIL",
        original_retry_queue=len(original_retry_rows),
        passed=passed,
        failed=failed,
        retry_dispatch_statuses=dispatch_statuses,
        retry_counts=retry_counts,
        max_retry_waves=3,
        fresh_runner_per_wave=True,
        further_automatic_retries=0,
    )
    sequence = int(os.environ.get("RIVERSHIFT_CALLBACK_SEQUENCE", "0") or 0)
    callbacks = JobCallbacks(
        prepared["job_id"],
        prepared["request_fingerprint"],
        os.environ["RIVERSHIFT_CALLBACK_URL"],
        initial_sequence=sequence,
    )

    error_code = None
    error_message = None
    callback_state = "running"
    callback_stage = "delayed_retry_waves_completed"
    if setup_failures:
        callback_state = "failed"
        callback_stage = "delayed_retry_setup_failed"
        error_code = "RETRY_MATRIX_HANDOFF_FAILED"
        error_message = "One or more retry matrix handoffs for fresh-runner waves could not be prepared: " + "; ".join(setup_failures)
    elif failed:
        callback_state = "failed"
        callback_stage = "delayed_retry_waves_exhausted"
        error_code = "PRODUCT_RETRY_FAILED"
        error_message = (
            f"{failed} delayed retry product(s) remained unverifiable after up to three fresh-runner retry waves."
        )

    callbacks.send(
        callback_state,
        callback_stage,
        result_summary={
            "retry_count": len(original_retry_rows),
            "retry_success_count": passed,
            "retry_failure_count": failed,
            "maximum_retry_waves": 3,
            "fresh_runner_per_wave": True,
            "retry_dispatch_statuses": dispatch_statuses,
        },
        error_code=error_code,
        error_message=error_message,
    )
    _write_output("callback_sequence", str(callbacks.sequence))
    _write_output("retry_success_count", str(passed))
    _write_output("retry_failure_count", str(failed))

    detail_rows = "\n".join(
        f"| {name} | {reason} |" for name, reason in failure_details[:30]
    ) or "| — | No retry required |"
    _write_step_summary(
        "## Fresh-runner retry outcome\n\n"
        f"- Maximum retry waves: **3**\n"
        f"- Original retry queue: **{len(original_retry_rows)}**\n"
        f"- Recovered: **{passed}**\n"
        f"- Still failed/unverifiable: **{failed}**\n"
        f"- Dispatch checks: **{', '.join(dispatch_statuses)}**\n\n"
        "| Product / stage | Final outcome |\n|---|---|\n" + detail_rows
    )
    if callback_state == "failed":
        print(f"::error::Fresh-runner retry processing failed: {error_code} · {error_message}", flush=True)
        raise WorkerFailure(error_code or "PRODUCT_RETRY_FAILED", error_message or "Fresh-runner retry waves failed.")


def _rebase_exporter_sidecar_for_assembly(
    metadata_path: Path,
    raster_path: Path,
    *,
    granule_name: str,
    expected_source_sha256: str,
) -> None:
    """Rebind a verified exporter sidecar to its artifact-imported COG path.

    Product jobs run on isolated GitHub-hosted runners. Their absolute output
    paths are not valid on the assembly runner after artifact download, so the
    sidecar path must be rebased only after the copied raster checksum and
    exact source-granule identity have been verified.
    """
    metadata = _read_json(metadata_path, "exporter COG metadata")
    original_output_path = metadata.get("output_cog")
    output_digest = metadata.get("output_cog_sha256")
    source_digest = metadata.get("source_product_sha256")
    actual_digest = sha256_file(raster_path)

    if (
        not isinstance(original_output_path, str)
        or not original_output_path.strip()
        or not isinstance(output_digest, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", output_digest)
        or actual_digest.lower() != output_digest.lower()
    ):
        raise WorkerFailure(
            "SOURCE_PROVENANCE_INVALID",
            f"The imported COG checksum or exporter path is invalid for {granule_name}.",
        )
    source_names = metadata.get("source_granule_names")
    source_hashes = metadata.get("source_granule_sha256")
    if (
        metadata.get("source_granule_name") != granule_name
        or source_names != [granule_name]
        or not isinstance(source_hashes, list)
        or len(source_hashes) != 1
        or not isinstance(source_hashes[0], str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", source_hashes[0])
        or not isinstance(source_digest, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", source_digest)
        or source_digest.lower() != expected_source_sha256.lower()
        or source_hashes[0].lower() != expected_source_sha256.lower()
    ):
        raise WorkerFailure(
            "SOURCE_PROVENANCE_INVALID",
            f"The imported COG source identity or checksum does not match the verified download receipt for {granule_name}.",
        )

    # Preserve the original product-runner path for audit traceability. The
    # canonical output_cog field always points at the raster currently being
    # validated, not at an ephemeral runner filesystem.
    metadata.setdefault("exporter_output_cog", original_output_path)
    metadata["output_cog"] = str(raster_path.resolve())
    metadata["output_cog_sha256"] = actual_digest
    _write_json(metadata_path, metadata)
    _log_worker_stage(
        "source_sidecar_rebind",
        "PASS",
        granule_name=granule_name,
        exporter_path_preserved=True,
        imported_raster_sha256=actual_digest,
    )


def _verify_and_stage_product_results(
    prepared: dict[str, Any],
    product_artifacts_dir: Path,
    work_dir: Path,
) -> tuple[dict[str, list[Path]], Path]:
    expected_names = prepared["selected_product_names"]
    expected = set(expected_names)
    first_results = _load_product_results(product_artifacts_dir)
    retry_dir = Path(os.environ.get("RIVERSHIFT_RETRY_PRODUCT_ARTIFACTS_DIR", "retry-product-artifacts"))
    retry_results = _load_product_results(retry_dir)
    results = dict(first_results)
    result_dirs = {name: product_artifacts_dir for name in first_results}
    # A delayed retry result supersedes the first-attempt result for that exact granule.
    for name, retry_result in retry_results.items():
        if name in expected:
            results[name] = retry_result
            retry_attempt = int(retry_result.get("retry_attempt", 0) or 0)
            result_dirs[name] = retry_dir / f"wave-{retry_attempt}" if retry_attempt > 0 else retry_dir
    missing = sorted(expected - set(results))
    failures = []
    product_rasters: dict[str, Path] = {}
    raw_dir = work_dir / "raw"
    raster_dir = work_dir / "rasters"
    raw_dir.mkdir(parents=True)
    raster_dir.mkdir(parents=True)

    for name in expected_names:
        result = results.get(name)
        if not result:
            failures.append(f"{name}: result artifact missing")
            _log_worker_stage("batch_reconciliation_product", "FAIL", granule_name=name, reason="missing_result_artifact")
            continue
        if (
            result.get("status") != "PASS"
            or result.get("job_id") != prepared["job_id"]
            or result.get("request_fingerprint") != prepared["request_fingerprint"]
            or result.get("granule_name") != name
            or result.get("acquisition_date") != prepared["date_by_name"].get(name)
        ):
            reason = str(result.get("error_code") or "PRODUCT_RESULT_INVALID")
            detail = str(result.get("error_message") or "Product result failed identity or status validation.")
            failures.append(f"{name}: {reason} ({detail[:160]})")
            _log_worker_stage(
                "batch_reconciliation_product", "FAIL",
                granule_name=name,
                acquisition_date=prepared["date_by_name"].get(name),
                error_code=reason,
                error_message=detail,
            )
            continue

        verified_files = {}
        for item in result.get("files", []):
            if not isinstance(item, dict):
                continue
            filename = item.get("name")
            expected_digest = item.get("sha256")
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not isinstance(expected_digest, str)
                or len(expected_digest) != 64
            ):
                continue
            source = result_dirs.get(name, product_artifacts_dir) / name / filename
            if not source.is_file() or sha256_file(source) != expected_digest:
                failures.append(f"{name}: {filename} is missing or its SHA-256 does not match.")
                verified_files = {}
                break
            verified_files[filename] = source
        required = {
            f"{name}.tif",
            f"{name}.metadata.json",
            f"{name}.download.json",
            f"{name}.gcov_inventory.json",
        }
        if not required.issubset(verified_files):
            if not any(detail.startswith(f"{name}:") for detail in failures):
                failures.append(f"{name}: required raster or provenance sidecar is missing.")
            continue

        raster_source = verified_files[f"{name}.tif"]
        raw_dir.joinpath(f"{name}.download.json").write_bytes(verified_files[f"{name}.download.json"].read_bytes())
        raw_dir.joinpath(f"{name}.gcov_inventory.json").write_bytes(verified_files[f"{name}.gcov_inventory.json"].read_bytes())
        raster_destination = raster_dir / f"{name}.tif"
        metadata_destination = raster_destination.with_suffix(".metadata.json")
        shutil.copy2(raster_source, raster_destination)
        shutil.copy2(verified_files[f"{name}.metadata.json"], metadata_destination)
        _rebase_exporter_sidecar_for_assembly(
            metadata_destination,
            raster_destination,
            granule_name=name,
            expected_source_sha256=str(result.get("source_sha256") or ""),
        )
        product_rasters[name] = raster_destination
        _log_worker_stage(
            "batch_reconciliation_product", "PASS",
            granule_name=name,
            acquisition_date=result.get("acquisition_date"),
            download_bytes=result.get("download_bytes"),
            raster_bytes=result.get("raster_bytes"),
            source_sha256=result.get("source_sha256"),
            raster_sha256=result.get("raster_sha256"),
        )

    if missing:
        failures.extend(f"{name}: result artifact missing" for name in missing if not any(item.startswith(f"{name}:") for item in failures))
    if failures:
        _log_worker_stage(
            "batch_reconciliation", "FAIL",
            expected_count=len(expected_names),
            verified_count=len(product_rasters),
            failure_count=len(failures),
            failures=failures[:15],
        )
        raise WorkerFailure(
            "PRODUCT_BATCH_FAILED",
            f"{len(failures)} selected product(s) failed or were not verifiable after all 15-product batches: " + "; ".join(failures[:4]),
        )

    provenance = build_source_granule_manifest(
        raw_dir,
        expected_names,
        maturity=prepared["request"]["maturity"],
        frequency=prepared["request"]["frequency"],
        term=prepared["request"]["term"],
    )
    provenance_path = work_dir / "source-granule-provenance.json"
    _write_json(provenance_path, provenance)
    _log_worker_stage("batch_reconciliation", "PASS", expected_count=len(expected_names), verified_count=len(product_rasters))
    return {
        observed_date: [product_rasters[name] for name in names]
        for observed_date, names in prepared["products_by_date"].items()
    }, provenance_path


def _assemble_job(
    request: dict[str, Any],
    prepared: dict[str, Any],
    callbacks: JobCallbacks,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.monotonic()
    # Prepared jobs created before the two-mode contract are Event-Based by default.
    request.setdefault("analysis_mode", "event_based")
    work_dir = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / f"river-shift-{request['job_id']}-assemble"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    prepared_dir = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared"))
    products_dir = Path(os.environ.get("RIVERSHIFT_PRODUCT_ARTIFACTS_DIR", "product-artifacts"))
    if prepared.get("job_id") != request["job_id"] or prepared.get("request_fingerprint") != request["fingerprint"]:
        raise WorkerFailure("REQUEST_MISMATCH", "The assembly runner received a prepared artifact for a different RiverShift request.")

    callbacks.send("running", "assembly_preflight")
    _log_worker_stage("assembly_private_storage_preflight", "START")
    _ensure_credentials()
    _log_worker_stage(
        "assembly_private_storage_preflight", "PASS",
        storage_root="RiverShift",
        parent_variable="GOOGLE_DRIVE_PARENT_FOLDER_ID",
    )

    _log_worker_stage(
        "product_batch_import", "START",
        expected_product_count=len(prepared.get("selected_product_names", [])),
        expected_batch_count=len(prepared.get("batches", [])),
    )
    date_product_rasters, provenance_path = _verify_and_stage_product_results(prepared, products_dir, work_dir)
    raster_dir = work_dir / "rasters"
    date_rasters: dict[str, Path] = {}
    for observed_date, exported in date_product_rasters.items():
        _log_worker_stage(
            "date_raster_assembly", "START",
            acquisition_date=observed_date,
            source_cog_count=len(exported),
        )
        if len(exported) == 1:
            date_rasters[observed_date] = exported[0]
            result_path = exported[0]
            method = "single_source_cog"
        else:
            destination = raster_dir / f"observation_{observed_date}.tif"
            date_rasters[observed_date] = _mosaic_date_rasters(exported, destination)
            result_path = destination
            method = "deterministic_gdal_vrt_mosaic"
            for intermediate in exported:
                intermediate.unlink(missing_ok=True)
                intermediate.with_suffix(".metadata.json").unlink(missing_ok=True)
        _log_worker_stage(
            "date_raster_assembly", "PASS",
            acquisition_date=observed_date,
            source_cog_count=len(exported),
            assembly_method=method,
            output_bytes=result_path.stat().st_size,
            output_sha256=sha256_file(result_path),
        )
    _log_worker_stage(
        "product_batch_import", "PASS",
        verified_product_count=sum(len(rows) for rows in date_product_rasters.values()),
        assembled_date_count=len(date_rasters),
        source_provenance_manifest=provenance_path.name,
        source_provenance_sha256=sha256_file(provenance_path),
    )
    dates = prepared["dates"]
    analysis_window = prepared.get("analysis_window") or prepared.get("event_window")
    if not isinstance(analysis_window, dict):
        raise WorkerFailure("PREPARED_JOB_INVALID", "The prepared job is missing its immutable comparison window.")
    selection = prepared["selection"]
    source_granule_manifest_path = provenance_path
    reference_date = dates[0]
    reference_path = date_rasters[reference_date]
    aligned_observations: dict[str, Path] = {}
    for observed_date, path in date_rasters.items():
        _log_worker_stage(
            "observation_grid_alignment", "START",
            acquisition_date=observed_date,
            reference_date=reference_date,
            is_reference=(observed_date == reference_date),
            source_file=path.name,
        )
        aligned = _co_register(
            path, reference_path, is_reference=(observed_date == reference_date)
        )
        aligned_observations[observed_date] = aligned
        _log_worker_stage(
            "observation_grid_alignment", "PASS",
            acquisition_date=observed_date,
            reference_date=reference_date,
            aligned_file=aligned.name,
            output_bytes=aligned.stat().st_size,
            output_sha256=sha256_file(aligned),
        )
    _log_worker_stage("source_provenance_validation", "START", observation_count=len(aligned_observations))
    require_worker_source_provenance(
        aligned_observations,
        maturity=request["maturity"],
        frequency=request["frequency"],
        term=request["term"],
    )
    _log_worker_stage("source_provenance_validation", "PASS", observation_count=len(aligned_observations))

    callbacks.send("running", "water_time_series_and_change_analysis")
    threshold_args = ["--otsu"] if request["threshold_method"] == "otsu" else ["--threshold-db", str(request["threshold_db"])]
    time_dir = work_dir / "analysis" / "time-series"
    time_command = [sys.executable, "run_water_timeseries.py"]
    for observed_date in dates:
        time_command.extend(["--observation", f"{observed_date}={aligned_observations[observed_date]}"])
    time_command.extend(threshold_args + [
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"],
        "--out-dir", str(time_dir),
    ])
    run_step("observed-date time-series analysis", time_command, context={"observation_count": len(dates)})

    window_paths = {key: aligned_observations[value] for key, value in analysis_window.items()}
    flood_dir = work_dir / "analysis" / "flood"
    run_step("date-window water change screening", [
        sys.executable, "run_flood_analysis.py",
        "--before", str(window_paths["before"]),
        "--during", str(window_paths["event_proximal_observation"]),
        "--after", str(window_paths["post_one"]),
        "--before-date", analysis_window["before"],
        "--during-date", analysis_window["event_proximal_observation"],
        "--after-date", analysis_window["post_one"],
        *threshold_args,
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"],
        "--out-dir", str(flood_dir),
    ], context={"analysis_mode": request["analysis_mode"], "comparison_window": selection.get("comparison_window")})
    if request["analysis_mode"] == "general_scan":
        generalize_flood_result(flood_dir / "river_shift_result.json", selection)
    morphology_dir = work_dir / "analysis" / "morphology"
    run_step("persistent morphology screening", [
        sys.executable, "run_morphology_analysis.py",
        "--before", str(window_paths["before"]),
        "--post-one", str(window_paths["post_one"]),
        "--post-two", str(window_paths["post_two"]),
        "--before-date", analysis_window["before"],
        "--post-one-date", analysis_window["post_one"],
        "--post-two-date", analysis_window["post_two"],
        *threshold_args,
        "--input-units", "linear", "--maturity", request["maturity"],
        "--frequency", request["frequency"], "--term", request["term"],
        "--out-dir", str(morphology_dir),
    ], context={"analysis_mode": request["analysis_mode"], "comparison_window": selection.get("comparison_window")})
    if request["analysis_mode"] == "general_scan":
        generalize_morphology_result(morphology_dir / "river_shift_result.json", selection)

    callbacks.send("running", "result_package_assembly")
    _log_worker_stage("result_package_assembly", "START")
    output_root = work_dir / "outputs"
    inventory = []
    for label, directory in (("time-series", time_dir), ("flood", flood_dir), ("morphology", morphology_dir)):
        inventory.extend(_copy_result_files([(label, directory)], output_root))

    qa_dir = output_root / "qa"
    overlap_audit_path = qa_dir / "candidate_overlap_audit.json"
    try:
        candidate_overlap_audit = audit_candidate_mask_overlap(
            {
                "erosion": morphology_dir / "erosion_candidate_mask.tif",
                "deposition": morphology_dir / "deposition_candidate_mask.tif",
                "new_water": flood_dir / "newly_water_covered_mask.tif",
            },
            overlap_audit_path,
            comparison_window=selection.get("comparison_window") or analysis_window,
        )
    except (OSError, ValueError) as exc:
        detail = str(exc).strip() or type(exc).__name__
        _log_worker_stage("candidate_overlap_audit", "FAIL", error=detail[:240])
        raise WorkerFailure(
            "CANDIDATE_OVERLAP_AUDIT_FAILED",
            f"Full-resolution candidate-mask overlap QA failed: {detail[:240]}",
        ) from None
    inventory.append({
        "path": overlap_audit_path.relative_to(work_dir).as_posix(),
        "sha256": sha256_file(overlap_audit_path),
    })
    _log_worker_stage(
        "candidate_overlap_audit", "PASS",
        audit_status=candidate_overlap_audit["status"],
        pairwise=candidate_overlap_audit["pairwise"],
        triple_overlap_pixels=candidate_overlap_audit["triple_overlap_pixels_on_common_support"],
        output_sha256=sha256_file(overlap_audit_path),
    )

    provenance_dir = output_root / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in (
        ("gcov-catalogue-manifest.json", "catalogue-manifest.json"),
        ("gcov-time-series-audit.json", "acquisition-compatibility-audit.json"),
        ("selected-observations.json", "selected-observations.json"),
    ):
        source = prepared_dir / source_name
        target = provenance_dir / target_name
        shutil.copy2(source, target)
        inventory.append({"path": target.relative_to(work_dir).as_posix(), "sha256": sha256_file(target)})
    target_provenance = provenance_dir / "source-granule-provenance.json"
    shutil.copy2(source_granule_manifest_path, target_provenance)
    inventory.append({"path": target_provenance.relative_to(work_dir).as_posix(), "sha256": sha256_file(target_provenance)})

    granule_receipts_dir = provenance_dir / "granules"
    granule_receipts_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = work_dir / "raw"
    for granule in json.loads(source_granule_manifest_path.read_text(encoding="utf-8"))["granules"]:
        for key in ("download_receipt", "hdf5_inventory"):
            source = raw_dir / granule[key]
            target = granule_receipts_dir / source.name
            shutil.copy2(source, target)
            inventory.append({"path": target.relative_to(work_dir).as_posix(), "sha256": sha256_file(target)})

    time_report_path = output_root / "time-series" / "river_shift_timeseries_preview.json"
    time_report = _read_json(time_dir / "river_shift_timeseries.json", "time-series result")
    time_report["selection"] = selection
    time_report["quality"]["warnings"].append(
        "Web playback uses display-only simplified GeoJSON. Small patches may be omitted; use full-resolution private GeoJSON for detailed GIS review."
    )
    _write_json(time_report_path, time_report)
    preview_layers = create_web_previews(
        work_dir, time_dir, flood_dir, morphology_dir, reference_path, time_report_path,
    )
    inventory.extend(preview_layers)
    inventory.append({"path": time_report_path.relative_to(work_dir).as_posix(), "sha256": sha256_file(time_report_path)})

    report_digest = sha256_file(time_report_path)
    report_payload = _read_json(time_report_path, "time-series preview report")
    flood_result = _read_json(flood_dir / "river_shift_result.json", "flood result")
    morphology_result = _read_json(morphology_dir / "river_shift_result.json", "morphology result")
    summary = {
        "schema_version": 1,
        "processing_status": "PASS",
        "release_status": "PROVISIONAL",
        "independent_validation_status": "PENDING",
        "analysis_mode": request["analysis_mode"],
        "event_date_status": "NOT_APPLICABLE" if request["analysis_mode"] == "general_scan" else "USER_SUPPLIED_NOT_INDEPENDENTLY_CONFIRMED",
        "morphology_status": morphology_result["quality"]["status"],
        "flood_status": flood_result["quality"]["status"],
        "observation_count": len(dates),
        "selected_dates": dates,
        "comparison_window": selection.get("comparison_window"),
        "event_window": analysis_window if request["analysis_mode"] == "event_based" else None,
        "selected_granule_count": len(prepared["selected_product_names"]),
        "batch_size": BATCH_SIZE,
        "batch_count": len(prepared["batches"]),
        "threshold_method": request["threshold_method"],
        "threshold_db": report_payload["method"].get("threshold_db"),
        "time_series_report_sha256": report_digest,
        "map_preview": "outputs/map/river_change_candidates_preview.geojson",
        "candidate_overlap_audit": {
            "path": "outputs/qa/candidate_overlap_audit.json",
            "status": candidate_overlap_audit["status"],
            "pairwise": candidate_overlap_audit["pairwise"],
            "report_sha256": sha256_file(overlap_audit_path),
        },
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
        "result_package_assembly", "PASS",
        validated_output_count=len(inventory),
        manifest_sha256=sha256_file(manifest_path),
    )

    callbacks.send("running", "private_result_publication")
    _log_worker_stage(
        "private_result_publication", "START",
        output_count=len(inventory),
        storage_provider="Google Drive",
        folder="RiverShift",
    )
    try:
        storage = upload_validated_results(work_dir)
    except DriveUploadError as exc:
        _log_worker_stage("private_result_publication", "FAIL", error=str(exc))
        raise WorkerFailure(
            "PRIVATE_STORAGE_PUBLICATION_FAILED",
            "Google Drive result publication failed; inspect the per-file Drive stage logs.",
        ) from None
    if storage.get("status") != "PASS":
        raise WorkerFailure("PRIVATE_STORAGE_UNVERIFIED", "Google Drive did not return a successful remote checksum verification.")
    _log_worker_stage(
        "private_result_publication", "PASS",
        storage_status=storage.get("status"),
        receipt_count=len(storage.get("receipts", [])),
        retained_bytes=storage.get("retained_bytes"),
    )
    manifest_payload = _read_json(manifest_path, "result manifest")
    artifacts = _callback_artifacts(manifest_payload)
    _log_worker_stage("assembly_completion", "PASS", elapsed_seconds=round(time.monotonic() - started, 3))
    return summary, artifacts


def main() -> int:
    phase = os.environ.get("RIVERSHIFT_WORKER_PHASE", "prepare").strip().lower()
    callbacks: JobCallbacks | None = None
    started = time.monotonic()
    try:
        if phase == "product":
            return _run_product_worker()

        if phase == "prepare":
            _log_worker_stage("worker_startup", "START", phase=phase)
            request = _read_input()
            callbacks = JobCallbacks(request["job_id"], request["fingerprint"], os.environ["RIVERSHIFT_CALLBACK_URL"])
            callbacks.send("running", "worker_started")
            _prepare_job(request, callbacks)
            _log_worker_stage("worker_completion", "PASS", phase=phase, callback_sequence=callbacks.sequence, elapsed_seconds=round(time.monotonic() - started, 3))
            return 0

        if phase == "report-batch":
            _log_worker_stage("worker_startup", "START", phase=phase)
            _report_batch()
            _log_worker_stage("worker_completion", "PASS", phase=phase)
            return 0

        if phase == "prepare-retry":
            _log_worker_stage("worker_startup", "START", phase=phase)
            _prepare_retry_wave()
            _log_worker_stage("worker_completion", "PASS", phase=phase)
            return 0

        if phase == "report-retry":
            _log_worker_stage("worker_startup", "START", phase=phase)
            _report_retry_wave()
            _log_worker_stage("worker_completion", "PASS", phase=phase)
            return 0

        if phase == "assemble":
            _log_worker_stage("worker_startup", "START", phase=phase)
            request = _read_input()
            prepared_dir = Path(os.environ.get("RIVERSHIFT_PREPARED_DIR", "prepared"))
            prepared = _read_json(prepared_dir / "prepared.json", "prepared selection")
            sequence = int(os.environ.get("RIVERSHIFT_CALLBACK_SEQUENCE", "0") or 0)
            callbacks = JobCallbacks(
                request["job_id"],
                request["fingerprint"],
                os.environ["RIVERSHIFT_CALLBACK_URL"],
                initial_sequence=sequence,
            )
            summary, artifacts = _assemble_job(request, prepared, callbacks)
            callbacks.send("succeeded", "completed", result_summary=summary, artifact_manifest=artifacts)
            print("RIVERSHIFT_PROCESSING_STATUS=PASS", flush=True)
            print("RIVERSHIFT_RELEASE_STATUS=PROVISIONAL", flush=True)
            print(f"RIVERSHIFT_ARTIFACT_COUNT={len(artifacts)}", flush=True)
            _log_worker_stage("worker_completion", "PASS", phase=phase, artifact_count=len(artifacts), elapsed_seconds=round(time.monotonic() - started, 3))
            return 0

        raise WorkerFailure("INVALID_WORKER_PHASE", f"Unknown RiverShift worker phase: {phase}.")
    except WorkerFailure as exc:
        message = str(exc)[:500]
        print(f"RIVERSHIFT_PROCESSING_STATUS=FAIL code={exc.code} message={message}", file=sys.stderr, flush=True)
        _log_worker_stage("worker_completion", "FAIL", phase=phase, error_code=exc.code, elapsed_seconds=round(time.monotonic() - started, 3))
        if callbacks:
            try:
                callbacks.send("failed", callbacks.stage, error_code=exc.code, error_message=message)
            except WorkerFailure:
                print("RIVERSHIFT_CALLBACK_STATUS=FAIL", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        message = f"Unexpected {type(exc).__name__}: {str(exc)[:350]}"
        print(f"RIVERSHIFT_PROCESSING_STATUS=FAIL type={type(exc).__name__}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        _log_worker_stage("worker_completion", "FAIL", phase=phase, error_code="UNEXPECTED_WORKER_ERROR", error_type=type(exc).__name__, elapsed_seconds=round(time.monotonic() - started, 3))
        if callbacks:
            try:
                callbacks.send("failed", callbacks.stage, error_code="UNEXPECTED_WORKER_ERROR", error_message=message)
            except WorkerFailure:
                print("RIVERSHIFT_CALLBACK_STATUS=FAIL", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
