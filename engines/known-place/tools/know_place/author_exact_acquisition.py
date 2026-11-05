"""Acquire the author's exact five GOFF products via NASA CMR metadata.

The catalog and authenticated preflight operations never download the HDF5 payload.
The download-and-analyze operation requires the explicit [run-know-place] marker,
records fresh SHA-256 hashes, and writes derived outputs separately from raw inputs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse

from .author_catalog import (
    CMR_COLLECTION_CONCEPT_ID,
    EXPECTED_COLLECTION,
    EXPECTED_MATURITY,
    load_author_granules,
    query_cmr_exact_author_product,
)
from .goff_io import GoffReadError, inspect_goff_grid, parse_granule_identity

CONSENT_MARKER = "[run-know-place]"
TARGET_EPSG = 32645
TARGET_POSTING_M = 80.0
EXPECTED_GRID_WIDTH = 4311
EXPECTED_GRID_HEIGHT = 4230
CROWN_GEOMETRY_HEIGHT_M = 5151.0
DEFAULT_CONTROL_DRAWS = 1000
DEFAULT_CONTROL_SEED = 260826
DEFAULT_COHERENCE_MINIMUM = 1
PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS = "BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED"
PINNED_AUTHOR_TERRAIN_ELEVATION_SHA256 = "d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1"
TRUSTED_ASF_HOSTS = (
    "asf.alaska.edu",
    ".asf.alaska.edu",
    ".asf.earthdatacloud.nasa.gov",
)


class AuthorExactAcquisitionError(RuntimeError):
    """Raised when exact-source acquisition or its provenance cannot be verified."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def analysis_result_is_complete(return_code: int, report: dict[str, Any]) -> bool:
    """Only a zero-exit run with all five scientific metric records counts as complete."""
    return (
        return_code == 0
        and report.get("structural_status") == "PASS"
        and report.get("status") == "SCIENTIFIC_METRICS_COMPUTED"
    )


def author_site_series_result_is_complete(return_code: int, report: dict[str, Any]) -> bool:
    """Require the 65 base checks and all 15 halo-aware P2 Table S4 checks."""
    comparison = report.get("author_site_series_table_comparison", {})
    p2 = report.get("author_p2_table_comparison", {})
    return (
        return_code == 0
        and report.get("structural_status") == "PASS"
        and report.get("status") == "SCIENTIFIC_METRICS_COMPUTED"
        and report.get("method_profile") == "ARCHIVED_AUTHOR_SITE_SERIES_COMPATIBLE"
        and report.get("source_products_processed") == 5
        and comparison.get("status") == "PASS_AT_ARCHIVE_ROUNDING"
        and comparison.get("checks_passed") == 65
        and comparison.get("checks_total") == 65
        and comparison.get("mismatch_count") == 0
        and p2.get("status") == "PASS_AT_ARCHIVE_ROUNDING"
        and p2.get("checks_passed") == 15
        and p2.get("checks_total") == 15
        and p2.get("mismatch_count") == 0
    )


def author_grid_identity_validation(grid: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Compare CMR's stem to the exact HDF5 filename returned by the GOFF parser."""
    identity = grid.identity
    expected_name = str(row["granule_name"])
    expected_filename = str(row.get("source_filename") or f"{expected_name}.h5")
    actual_filename = Path(identity.granule_name).name
    start, end = str(row["interval"]).split("/", maxsplit=1)
    checks = {
        "filename": {
            "expected": expected_filename,
            "actual": actual_filename,
            "passed": actual_filename == expected_filename,
        },
        "granule_stem": {
            "expected": expected_name,
            "actual": Path(actual_filename).stem,
            "passed": Path(actual_filename).stem == expected_name,
        },
        "release_id": {
            "expected": "P05023",
            "actual": identity.release_id,
            "passed": identity.release_id == "P05023",
        },
        "reference_start_date": {
            "expected": start,
            "actual": identity.reference_start.date().isoformat(),
            "passed": identity.reference_start.date().isoformat() == start,
        },
        "secondary_start_date": {
            "expected": end,
            "actual": identity.secondary_start.date().isoformat(),
            "passed": identity.secondary_start.date().isoformat() == end,
        },
        "epsg": {
            "expected": TARGET_EPSG,
            "actual": grid.epsg,
            "passed": grid.epsg == TARGET_EPSG,
        },
    }
    mismatches = [name for name, check in checks.items() if not check["passed"]]
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "expected_granule_name_without_extension": expected_name,
        "expected_source_filename_with_extension": expected_filename,
        "actual_identity_filename": actual_filename,
        "checks": checks,
        "mismatch_fields": mismatches,
    }


def source_receipt_counts(products: list[dict[str, Any]]) -> dict[str, int]:
    """Separate completed byte transfers/hashes from scientifically validated source grids."""
    hashed = [
        row for row in products
        if isinstance(row.get("source_bytes"), int)
        and row["source_bytes"] > 0
        and isinstance(row.get("source_sha256"), str)
        and len(row["source_sha256"]) == 64
        and all(char in "0123456789abcdefABCDEF" for char in row["source_sha256"])
    ]
    return {
        "source_downloads": len(hashed),
        "source_sha256_count": len(hashed),
        "source_products_grid_validated": sum(
            row.get("download_status") == "PASS" for row in products
        ),
    }


def _trusted_asf_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == TRUSTED_ASF_HOSTS[0]
        or host.endswith(TRUSTED_ASF_HOSTS[1])
        or host.endswith(TRUSTED_ASF_HOSTS[2])
    )


def require_consent_marker(value: str | None) -> None:
    if value != CONSENT_MARKER:
        raise AuthorExactAcquisitionError("EXPLICIT_RAW_DOWNLOAD_CONSENT_MARKER_REQUIRED")


def select_exact_hdf5_data_url(catalog_record: dict[str, Any], wanted_name: str) -> str:
    """Select a direct CMR HTTP data link for this exact product, never a browse/metadata URL."""
    metadata = catalog_record.get("cmr_metadata")
    if not isinstance(metadata, dict):
        raise AuthorExactAcquisitionError(f"CMR_METADATA_MISSING:{wanted_name}")
    if catalog_record.get("catalog_identity_status") != "EXACT_CMR_GRANULE_CONFIRMED":
        raise AuthorExactAcquisitionError(f"CMR_EXACT_IDENTITY_NOT_CONFIRMED:{wanted_name}")
    if catalog_record.get("release_id") != "P05023":
        raise AuthorExactAcquisitionError(f"AUTHOR_RELEASE_MISMATCH:{wanted_name}")
    if catalog_record.get("cmr_collection_concept_id") != CMR_COLLECTION_CONCEPT_ID:
        raise AuthorExactAcquisitionError(f"CMR_COLLECTION_MISMATCH:{wanted_name}")
    links = metadata.get("links", [])
    if not isinstance(links, list):
        raise AuthorExactAcquisitionError(f"CMR_LINKS_INVALID:{wanted_name}")
    candidates: list[str] = []
    expected_file = wanted_name + ".h5"
    expected_path = f"/NISAR/{EXPECTED_COLLECTION}/{wanted_name}/{expected_file}"
    for link in links:
        if not isinstance(link, dict) or link.get("inherited") is True:
            continue
        rel = str(link.get("rel") or "")
        title = str(link.get("title") or "")
        href = link.get("href")
        if "data#" not in rel or expected_file not in title:
            continue
        if not isinstance(href, str) or not _trusted_asf_url(href):
            continue
        parsed = urlparse(href)
        if parsed.path != expected_path:
            continue
        candidates.append(href)
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise AuthorExactAcquisitionError(
            f"EXACT_CMR_HDF5_HTTP_URL_NOT_UNIQUE:{wanted_name}:count={len(unique)}"
        )
    return unique[0]


def discover_exact_author_sources() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Query CMR for all five author IDs, pin the collection, URL and interval."""
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    targets = load_author_granules()
    for target in targets:
        wanted = target["granule_name"]
        try:
            row, receipt = query_cmr_exact_author_product(target)
            if row is None:
                raise AuthorExactAcquisitionError(
                    f"CMR_AUTHOR_PRODUCT_NOT_CONFIRMED:{receipt.get('status')}"
                )
            if row.get("granule_name") != wanted:
                raise AuthorExactAcquisitionError("CMR_RETURNED_DIFFERENT_GRANULE")
            identity = parse_granule_identity(wanted + ".h5")
            if identity.release_id != "P05023" or identity.track != "098" or identity.direction != "A":
                raise AuthorExactAcquisitionError("AUTHOR_GRANULE_IDENTITY_CONTRACT_MISMATCH")
            start, end = target["interval"].split("/", maxsplit=1)
            if (
                identity.reference_start.date().isoformat() != start
                or identity.secondary_start.date().isoformat() != end
            ):
                raise AuthorExactAcquisitionError("AUTHOR_INTERVAL_DOES_NOT_MATCH_FILENAME")
            url = select_exact_hdf5_data_url(row, wanted)
            row["exact_data_url"] = url
            row["source_filename"] = wanted + ".h5"
            row["cmr_query_receipt"] = receipt
            row["interval_days"] = int(target["days"])
            row["expected_release"] = "P05023"
            row["source_sha256"] = None
            row["source_bytes"] = None
            row["download_status"] = "NOT_DOWNLOADED"
            rows.append(row)
        except Exception as exc:
            errors.append({
                "granule_name": wanted,
                "interval": target["interval"],
                "error_type": type(exc).__name__,
                "error_code": str(exc).split(":", maxsplit=1)[0][:160],
            })
    manifest = {
        "schema_version": "know-place-author-exact-acquisition/1.0",
        "created_at_utc": _utc_now(),
        "repository_branch": os.environ.get("GITHUB_REF_NAME", "local"),
        "repository_commit": os.environ.get("GITHUB_SHA", "local"),
        "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
        "expected_collection_short_name": EXPECTED_COLLECTION,
        "expected_maturity": EXPECTED_MATURITY,
        "author_release_id": "P05023",
        "expected_intervals": [row["interval"] for row in targets],
        "author_product_count": len(targets),
        "exact_cmr_confirmed_count": len(rows),
        "blocking_count": len(errors),
        "status": "PASS" if len(rows) == 5 and not errors else "BLOCKED",
        "products": rows,
        "blocking_products": errors,
        "source_downloads": 0,
        "raw_source_byte_identity": "UNVERIFIED",
        "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
        "hazard_detection_status": "NOT_EVALUATED",
    }
    return rows, manifest


def _load_downloader(science_root: Path):
    """Load the existing hardened single-granule HTTPS/credential helpers."""
    downloader_path = Path(__file__).resolve().parents[1] / "download_nisar_product.py"
    spec = importlib.util.spec_from_file_location("sarguardian_know_place_downloader", downloader_path)
    if spec is None or spec.loader is None:
        raise AuthorExactAcquisitionError("HARDENED_DOWNLOADER_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    acquisition, acquisition_sha = module.load_source_acquisition(science_root, "source")
    session = module.build_authenticated_session_with_retry(acquisition)
    return module, acquisition_sha, session


def authenticated_preflight(
    rows: list[dict[str, Any]],
    *,
    science_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Check current authenticated URL availability and exact Content-Length using HEAD/range only."""
    downloader, acquisition_sha, session = _load_downloader(science_root)
    probe_rows: list[dict[str, Any]] = []
    total_bytes = 0
    blockers: list[dict[str, str]] = []
    for row in rows:
        name = row["granule_name"]
        try:
            remote_bytes = downloader.probe_url_content_length(session, row["exact_data_url"])
            if remote_bytes is None or int(remote_bytes) <= 0:
                raise AuthorExactAcquisitionError("REMOTE_CONTENT_LENGTH_UNAVAILABLE")
            record = {
                "granule_name": name,
                "interval": row["interval"],
                "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
                "cmr_granule_concept_id": row["cmr_metadata"].get("id"),
                "url_host": urlparse(row["exact_data_url"]).hostname,
                "remote_content_length_bytes": int(remote_bytes),
                "probe_status": "PASS",
                "source_payload_downloaded": False,
            }
            total_bytes += int(remote_bytes)
        except Exception as exc:
            record = {
                "granule_name": name,
                "interval": row["interval"],
                "probe_status": "FAIL",
                "source_payload_downloaded": False,
                "error_type": type(exc).__name__,
                "error_code": str(exc).split(":", maxsplit=1)[0][:160],
            }
            blockers.append({"granule_name": name, "error_code": record["error_code"]})
        probe_rows.append(record)
    report = {
        "schema_version": "know-place-author-exact-preflight/1.0",
        "checked_at_utc": _utc_now(),
        "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
        "science_acquisition_module_sha256": acquisition_sha,
        "probe_method": "Authenticated HEAD with bounded metadata-only fallback to HTTP Range bytes=0-0 where server disallows HEAD",
        "product_count": len(probe_rows),
        "passed_count": sum(row["probe_status"] == "PASS" for row in probe_rows),
        "blocking_count": len(blockers),
        "estimated_total_source_bytes": total_bytes,
        "products": probe_rows,
        "blocking_products": blockers,
        "raw_payload_downloads": 0,
        "status": "PASS" if len(probe_rows) == 5 and not blockers else "BLOCKED",
    }
    _write_json_atomic(output_path, report)
    return report


def _build_analysis_config(
    source_manifest: dict[str, Any],
    raw_dir: Path,
    run_root: Path,
    *,
    geometry_height_m: float = CROWN_GEOMETRY_HEIGHT_M,
    control_draws: int = DEFAULT_CONTROL_DRAWS,
    seed: int = DEFAULT_CONTROL_SEED,
    coherence_minimum_valid_cells: int = DEFAULT_COHERENCE_MINIMUM,
    source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Build the analyzer's strict five-pair input config from actual downloaded receipts."""
    benchmark_path = Path(__file__).resolve().parents[2] / "docs" / "know-place" / "reference" / "author_benchmark_v1.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    spatial = benchmark["spatial_definition"]
    target_rows = load_author_granules()
    target_by_name = {row["granule_name"]: row for row in target_rows}
    products = []
    for product in source_manifest.get("products", []):
        if product.get("download_status") != "PASS":
            raise AuthorExactAcquisitionError("ANALYSIS_CONFIG_REQUIRES_FIVE_HASHED_DOWNLOADS")
        wanted = product["granule_name"]
        expected = target_by_name.get(wanted)
        if expected is None:
            raise AuthorExactAcquisitionError("DOWNLOADED_GRANULE_NOT_IN_AUTHOR_BENCHMARK")
        if product.get("release_id") != "P05023":
            raise AuthorExactAcquisitionError("ANALYSIS_CONFIG_RELEASE_NOT_AUTHOR_EXACT")
        if not product.get("source_sha256") or not product.get("source_bytes"):
            raise AuthorExactAcquisitionError("ANALYSIS_CONFIG_SOURCE_RECEIPT_INCOMPLETE")
        products.append({
            "path": f"raw/{product['source_filename']}",
            "expected_granule_name": product["source_filename"],
            "catalog_maturity": "PROVISIONAL",
            "catalog_maturity_evidence": (
                "NASA CMR exact producer-granule ID in pinned collection "
                f"{CMR_COLLECTION_CONCEPT_ID}; payload SHA-256 recorded after HDF5 validation"
            ),
        })
    if len(products) != 5:
        raise AuthorExactAcquisitionError("ANALYSIS_CONFIG_REQUIRES_FIVE_AUTHOR_PRODUCTS")
    config = {
        "schema_version": "know-place-analysis-inputs/1.0",
        "reference_box_wkt": spatial["reference_box_wkt"],
        "crown_wkt": spatial["crown_wkt"],
        "crown_geometry_kind": "bounding-box-approximation",
        "crown_geometry_source": (
            "Published WGS84 rectangle transcribed in author benchmark; the raw source product series is author-exact, "
            "but an author-supplied editable vector geometry was not present in the raw-data archive."
        ),
        "geometry_height_m": float(geometry_height_m),
        "control_seed": int(seed),
        "control_draws": int(control_draws),
        "coherence_minimum_valid_cells": int(coherence_minimum_valid_cells),
        "coherence_neighbour_policy": (
            "Primary minimum 1 because the preprint does not publish a minimum neighbour count; "
            "sensitivity is reported for 1,5,10,15,20,25."
        ),
        "products": products,
    }
    config_path = run_root / "know-place-inputs.json"
    _write_json_atomic(config_path, config)
    provenance = {
        "schema_version": "know-place-author-exact-run-config-provenance/1.0",
        "created_at_utc": _utc_now(),
        "config_sha256": sha256_file(config_path),
        "author_benchmark_file": "docs/know-place/reference/author_benchmark_v1.json",
        "author_benchmark_sha256": sha256_file(benchmark_path),
        "source_manifest_sha256": source_manifest_sha256,
        "configuration": config,
        "scientific_scope": "Exploratory metrics from author-exact source granules. Not a validated hazard detector.",
        "paper_reproduction_status": PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS,
        "hazard_detection_status": "NOT_EVALUATED",
    }
    _write_json_atomic(run_root / "run-config-provenance.json", provenance)
    return config


def acquire_and_analyze(
    *,
    science_root: Path,
    run_root: Path,
    output_root: Path,
    terrain_root: Path | None,
    consent_marker: str | None,
    expected_geometry_height_m: float = CROWN_GEOMETRY_HEIGHT_M,
    control_draws: int = DEFAULT_CONTROL_DRAWS,
    seed: int = DEFAULT_CONTROL_SEED,
) -> dict[str, Any]:
    """Download exactly five author granules one time each, hash/validate, then analyze separately."""
    require_consent_marker(consent_marker)
    if terrain_root is None:
        raise AuthorExactAcquisitionError("PINNED_AUTHOR_TERRAIN_ROOT_REQUIRED")
    terrain_root = Path(terrain_root).expanduser().resolve()
    terrain_file = terrain_root / "elev_m.tif"
    if not terrain_file.is_file():
        raise AuthorExactAcquisitionError("PINNED_AUTHOR_TERRAIN_ELEVATION_MISSING")
    if sha256_file(terrain_file) != PINNED_AUTHOR_TERRAIN_ELEVATION_SHA256:
        raise AuthorExactAcquisitionError("PINNED_AUTHOR_TERRAIN_ELEVATION_SHA256_MISMATCH")
    run_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    raw_dir = run_root / "raw"
    raw_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(raw_dir, 0o700)

    rows, source_manifest = discover_exact_author_sources()
    source_manifest["source_downloads"] = 0
    manifest_path = run_root / "author-exact-source-manifest.json"
    _write_json_atomic(manifest_path, source_manifest)
    _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
    if source_manifest["status"] != "PASS" or len(rows) != 5:
        _write_json_atomic(output_root / "author-exact-analysis-status.json", {
            "schema_version": "know-place-author-exact-run-status/1.0",
            "status": "BLOCKED_CMR_EXACT_AUTHOR_CATALOG_GATE",
            "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
            "hazard_detection_status": "NOT_EVALUATED",
            "blocking_products": source_manifest.get("blocking_products", []),
            "created_at_utc": _utc_now(),
        })
        raise AuthorExactAcquisitionError("CMR_EXACT_AUTHOR_CATALOG_GATE_BLOCKED")

    preflight_path = run_root / "author-exact-preflight-manifest.json"
    try:
        probe = authenticated_preflight(rows, science_root=science_root, output_path=preflight_path)
    except Exception as exc:
        _write_json_atomic(output_root / "author-exact-analysis-status.json", {
            "schema_version": "know-place-author-exact-run-status/1.0",
            "status": "BLOCKED_REMOTE_PREFLIGHT_EXCEPTION",
            "failure_type": type(exc).__name__,
            "failure_code": str(exc).split(":", maxsplit=1)[0][:160],
            "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
            "hazard_detection_status": "NOT_EVALUATED",
            "created_at_utc": _utc_now(),
        })
        raise
    if preflight_path.is_file():
        shutil.copy2(preflight_path, output_root / "author-exact-preflight-manifest.json")
    if probe.get("status") != "PASS" or probe.get("passed_count") != 5:
        source_manifest["status"] = "BLOCKED_REMOTE_PREFLIGHT_FAILED"
        source_manifest["preflight"] = probe
        _write_json_atomic(manifest_path, source_manifest)
        _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
        _write_json_atomic(output_root / "author-exact-analysis-status.json", {
            "schema_version": "know-place-author-exact-run-status/1.0",
            "status": "BLOCKED_REMOTE_PREFLIGHT_FAILED",
            "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
            "hazard_detection_status": "NOT_EVALUATED",
            "created_at_utc": _utc_now(),
        })
        raise AuthorExactAcquisitionError("AUTHOR_EXACT_AUTHENTICATED_URL_PREFLIGHT_FAILED")

    required_bytes = int(probe["estimated_total_source_bytes"])
    free_bytes = shutil.disk_usage(run_root).free
    required_free = int(required_bytes * 1.5 + 2 * 1024 * 1024 * 1024)
    if free_bytes < required_free:
        source_manifest["status"] = "BLOCKED_INSUFFICIENT_DISK_SPACE"
        source_manifest["required_free_bytes"] = required_free
        source_manifest["runner_free_bytes_before_download"] = free_bytes
        _write_json_atomic(manifest_path, source_manifest)
        _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
        _write_json_atomic(output_root / "author-exact-analysis-status.json", {
            "schema_version": "know-place-author-exact-run-status/1.0",
            "status": "BLOCKED_INSUFFICIENT_DISK_SPACE",
            "required_free_bytes": required_free,
            "runner_free_bytes_before_download": free_bytes,
            "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
            "hazard_detection_status": "NOT_EVALUATED",
            "created_at_utc": _utc_now(),
        })
        raise AuthorExactAcquisitionError("INSUFFICIENT_DISK_SPACE_BEFORE_RAW_DOWNLOAD")

    downloader, acquisition_sha, session = _load_downloader(science_root)
    source_manifest.update({
        "status": "DOWNLOAD_IN_PROGRESS",
        "authorization_marker": CONSENT_MARKER,
        "science_acquisition_module_sha256": acquisition_sha,
        "drive_version_tag": os.environ.get("DRIVE_VERSION_TAG", ""),
        "product_execution_label": os.environ.get("PRODUCT_EXECUTION_LABEL", "initial"),
        "preflight": probe,
        "runner_free_bytes_before_download": free_bytes,
        "required_free_bytes_before_download": required_free,
        "source_downloads": 0,
        "products": [
            {
                "granule_name": row["granule_name"],
                "interval": row["interval"],
                "release_id": "P05023",
                "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
                "cmr_granule_concept_id": row["cmr_metadata"].get("id"),
                "source_filename": row["source_filename"],
                "download_url_host": urlparse(row["exact_data_url"]).hostname,
                "remote_content_length_bytes": next(
                    item["remote_content_length_bytes"]
                    for item in probe["products"] if item["granule_name"] == row["granule_name"]
                ),
                "download_status": "PENDING",
                "source_bytes": None,
                "source_sha256": None,
            }
            for row in rows
        ],
    })
    _write_json_atomic(manifest_path, source_manifest)
    _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)

    import numpy as np
    reference_x_coordinates: Any = None
    reference_y_coordinates: Any = None
    for row, product_receipt in zip(rows, source_manifest["products"], strict=True):
        target_path = raw_dir / row["source_filename"]
        if target_path.exists():
            raise AuthorExactAcquisitionError("REFUSING_TO_OVERWRITE_EXISTING_RAW_HDF5")
        expected_bytes = int(product_receipt["remote_content_length_bytes"])
        try:
            max_attempts = 1
            max_worker_phases = 2  # initial + one receipt-scoped retry phase, matching main.
            worker_phase = 1
            while worker_phase <= max_worker_phases:
                execution_label = "initial" if worker_phase == 1 else "retry-1"
                print(
                    f"PRODUCT_ID={product_receipt['cmr_granule_concept_id']} "
                    f"GRANULE_NAME={row['granule_name']} PRODUCT_TYPE=GOFF MATURITY=PROVISIONAL "
                    f"EXPECTED_SOURCE_BYTES={expected_bytes} RAW_DIR={raw_dir}",
                    flush=True,
                )
                download_completed = False
                for attempt in range(1, max_attempts + 1):
                    print(f"DOWNLOAD_ATTEMPT={attempt}/{max_attempts} execution_label={execution_label}", flush=True)
                    try:
                        downloaded = downloader.download_exact_product_with_timeout(
                            session, row["exact_data_url"], target_path, expected_bytes,
                        )
                        download_completed = True
                        break
                    except Exception as download_exc:
                        retryable = bool(downloader.is_retryable_remote_failure(download_exc))
                        product_receipt.setdefault("attempt_history", []).append({
                            "execution_label": execution_label,
                            "attempt_number_within_worker": attempt,
                            "failure_type": type(download_exc).__name__,
                            "failure_code": str(download_exc).split(":", maxsplit=1)[0][:160],
                            "download_failure_retryable": retryable,
                            "completed_at_utc": _utc_now(),
                        })
                        print("DOWNLOAD_FAILURE_RETRYABLE=" + ("yes" if retryable else "no"), flush=True)
                        if not retryable or worker_phase >= max_worker_phases:
                            raise
                if download_completed:
                    product_receipt["download_execution_label"] = execution_label
                    product_receipt["download_attempt_history"] = product_receipt.get("attempt_history", [])
                    break
                # This branch is reserved for a retryable remote error. Grid/identity
                # validation occurs only after the loop and never triggers a redownload.
                target_path.unlink(missing_ok=True)
                delay = min(15 * (2 ** (worker_phase - 1)), 120)
                print(
                    f"DOWNLOAD_RETRY_SCHEDULED product={row['granule_name']} "
                    f"next_execution_label=retry-1 sleep_seconds={delay}",
                    flush=True,
                )
                product_receipt["download_status"] = "PENDING_RETRY"
                source_manifest.update(source_receipt_counts(source_manifest["products"]))
                _write_json_atomic(manifest_path, source_manifest)
                _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
                time.sleep(delay)
                worker_phase += 1

            actual_bytes = target_path.stat().st_size
            if actual_bytes != expected_bytes or downloaded != expected_bytes:
                raise AuthorExactAcquisitionError("DOWNLOADED_SOURCE_BYTE_COUNT_MISMATCH")

            # Hash a complete byte-count-matched transfer before content/science checks.
            # This preserves evidence even if HDF5 or GOFF-grid validation subsequently fails.
            product_receipt.update({
                "download_status": "BYTES_VERIFIED_CONTENT_PENDING",
                "source_bytes": actual_bytes,
                "source_sha256": sha256_file(target_path),
                "hdf5_container_valid": None,
                "byte_count_validation": "PASS",
                "content_validation_status": "PENDING",
                "grid_validation_status": "NOT_RUN",
                "download_attempt_history": product_receipt.get("attempt_history", []),
            })
            source_manifest.update(source_receipt_counts(source_manifest["products"]))
            source_manifest["raw_source_byte_identity"] = "PARTIAL_SOURCE_BYTES_HASHED"
            _write_json_atomic(manifest_path, source_manifest)
            _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
            print(
                f"AUTHOR_SOURCE_BYTES_VERIFIED={row['granule_name']} "
                f"BYTES={actual_bytes} SHA256={product_receipt['source_sha256']}",
                flush=True,
            )

            import h5py
            if not h5py.is_hdf5(target_path):
                product_receipt["hdf5_container_valid"] = False
                product_receipt["content_validation_status"] = "FAIL_HDF5_CONTAINER"
                raise AuthorExactAcquisitionError("DOWNLOADED_SOURCE_IS_NOT_VALID_HDF5")
            product_receipt["hdf5_container_valid"] = True
            product_receipt["content_validation_status"] = "PASS"
            source_manifest.update(source_receipt_counts(source_manifest["products"]))
            _write_json_atomic(manifest_path, source_manifest)
            _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)

            grid = inspect_goff_grid(
                target_path, polarization="HH", layer=2,
                expected_track="098", expected_direction="A", expected_processing="PR",
            )
            identity_report = author_grid_identity_validation(grid, row)
            product_receipt["identity_validation"] = identity_report
            if identity_report["status"] != "PASS":
                product_receipt["grid_validation_status"] = "FAIL_IDENTITY"
                raise AuthorExactAcquisitionError("RAW_HDF5_IDENTITY_VALIDATION_FAILED")
            width = len(grid.x_coordinates_m)
            height = len(grid.y_coordinates_m)
            if width != EXPECTED_GRID_WIDTH or height != EXPECTED_GRID_HEIGHT:
                product_receipt["grid_validation_status"] = "FAIL_DIMENSIONS"
                product_receipt["actual_grid_shape"] = [height, width]
                raise AuthorExactAcquisitionError(
                    f"RAW_HDF5_GRID_DIMENSION_MISMATCH:expected={EXPECTED_GRID_WIDTH}x{EXPECTED_GRID_HEIGHT}:actual={width}x{height}"
                )
            x_posting = float(np.median(np.diff(grid.x_coordinates_m)))
            y_posting = float(np.median(np.diff(grid.y_coordinates_m)))
            if not all(abs(abs(value) - TARGET_POSTING_M) <= 1e-4 for value in (x_posting, y_posting)):
                product_receipt["grid_validation_status"] = "FAIL_POSTING"
                product_receipt["actual_grid_posting_m"] = [x_posting, y_posting]
                raise AuthorExactAcquisitionError("RAW_HDF5_POSTING_NOT_80M")
            if reference_x_coordinates is None:
                reference_x_coordinates = np.asarray(grid.x_coordinates_m).copy()
                reference_y_coordinates = np.asarray(grid.y_coordinates_m).copy()
            elif (
                not np.array_equal(reference_x_coordinates, np.asarray(grid.x_coordinates_m))
                or not np.array_equal(reference_y_coordinates, np.asarray(grid.y_coordinates_m))
            ):
                product_receipt["grid_validation_status"] = "FAIL_GRID_MISMATCH"
                raise AuthorExactAcquisitionError("RAW_HDF5_SOURCE_GRID_MISMATCH_ACROSS_AUTHOR_PRODUCTS")
            product_receipt.update({
                "download_status": "PASS",
                "grid_validation_status": "PASS",
                "grid_epsg": grid.epsg,
                "grid_width": width,
                "grid_height": height,
                "grid_x_min_m": float(np.min(grid.x_coordinates_m)),
                "grid_x_max_m": float(np.max(grid.x_coordinates_m)),
                "grid_y_min_m": float(np.min(grid.y_coordinates_m)),
                "grid_y_max_m": float(np.max(grid.y_coordinates_m)),
                "grid_x_posting_m": x_posting,
                "grid_y_posting_m": y_posting,
                "polarization": grid.polarization,
                "layer": grid.layer,
                "validated_at_utc": _utc_now(),
            })
            source_manifest.update(source_receipt_counts(source_manifest["products"]))
            source_manifest["raw_source_byte_identity"] = (
                "FIVE_EXACT_AUTHOR_SOURCE_HASHES_PINNED"
                if source_manifest["source_sha256_count"] == 5
                else "PARTIAL_SOURCE_BYTES_HASHED"
            )
            source_manifest["status"] = "DOWNLOAD_IN_PROGRESS"
            _write_json_atomic(manifest_path, source_manifest)
            _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
            print(
                f"AUTHOR_SOURCE_GRID_VALIDATED={row['granule_name']} "
                f"GRID={width}x{height} EPSG={grid.epsg} POSTING={x_posting:.6f},{y_posting:.6f}",
                flush=True,
            )
        except Exception as exc:
            counts = source_receipt_counts(source_manifest["products"])
            has_hash = bool(product_receipt.get("source_sha256"))
            if has_hash and product_receipt.get("content_validation_status") == "FAIL_HDF5_CONTAINER":
                product_receipt["download_status"] = "BYTES_VERIFIED_HDF5_INVALID"
            elif has_hash:
                product_receipt["download_status"] = "BYTES_VERIFIED_GRID_VALIDATION_FAILED"
            else:
                product_receipt["download_status"] = "FAIL"
            product_receipt["failure_type"] = type(exc).__name__
            product_receipt["failure_code"] = str(exc).split(":", maxsplit=1)[0][:160]
            source_manifest.update(counts)
            source_manifest["raw_source_byte_identity"] = (
                "SOURCE_BYTES_HASHED_BUT_CONTENT_OR_GRID_VALIDATION_FAILED"
                if has_hash
                else ("PARTIAL_SOURCE_BYTES_HASHED" if counts["source_downloads"] else "UNVERIFIED")
            )
            source_manifest["status"] = "FAILED_DURING_SOURCE_DOWNLOAD"
            _write_json_atomic(manifest_path, source_manifest)
            _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)
            _write_json_atomic(output_root / "author-exact-analysis-status.json", {
                "schema_version": "know-place-author-exact-run-status/1.0",
                "status": "FAILED_DURING_SOURCE_DOWNLOAD",
                "failure_type": type(exc).__name__,
                "failure_code": str(exc).split(":", maxsplit=1)[0][:160],
                "source_downloads_completed": counts["source_downloads"],
                "source_sha256_recorded": counts["source_sha256_count"],
                "source_products_grid_validated": counts["source_products_grid_validated"],
                "raw_source_byte_identity": source_manifest["raw_source_byte_identity"],
                "paper_reproduction_status": "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED",
                "hazard_detection_status": "NOT_EVALUATED",
                "created_at_utc": _utc_now(),
            })
            if target_path.is_file():
                target_path.unlink(missing_ok=True)
            raise

    source_manifest["status"] = "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED"
    source_manifest.update(source_receipt_counts(source_manifest["products"]))
    source_manifest["author_exact_source_sha256_count"] = source_manifest["source_sha256_count"]
    source_manifest["raw_source_byte_identity"] = "FIVE_EXACT_AUTHOR_SOURCE_HASHES_PINNED"
    source_manifest["paper_reproduction_status"] = PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS
    source_manifest["download_completed_at_utc"] = _utc_now()
    _write_json_atomic(manifest_path, source_manifest)
    _write_json_atomic(output_root / "author-exact-source-manifest.json", source_manifest)

    _build_analysis_config(
        source_manifest, raw_dir, run_root,
        geometry_height_m=expected_geometry_height_m,
        control_draws=control_draws, seed=seed,
        source_manifest_sha256=sha256_file(manifest_path),
    )
    # Only receipts/configuration are copied to derived output; raw HDF5 stays in run_root/raw.
    shutil.copy2(manifest_path, output_root / "author-exact-source-manifest.json")
    shutil.copy2(preflight_path, output_root / "author-exact-preflight-manifest.json")
    shutil.copy2(run_root / "know-place-inputs.json", output_root / "know-place-inputs.json")
    shutil.copy2(run_root / "run-config-provenance.json", output_root / "run-config-provenance.json")
    try:
        completed = subprocess.run(
            [
                sys.executable, "-m", "tools.know_place.analyze",
                "--config", str(run_root / "know-place-inputs.json"),
                "--out", str(output_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5 * 60 * 60,
        )
        (output_root / "analysis.stdout.log").write_text(completed.stdout or "", encoding="utf-8")
        (output_root / "analysis.stderr.log").write_text(completed.stderr or "", encoding="utf-8")
        report_path = output_root / "know-place-analysis-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {
            "status": "FAILED",
            "structural_status": "FAIL",
            "paper_reproduction_status": "BLOCKED_ANALYSIS_REPORT_MISSING",
            "hazard_detection_status": "NOT_EVALUATED",
        }
        report["author_exact_source_identity"] = {
            "status": "PASS_5_OF_5_EXACT_AUTHOR_P05023",
            "source_manifest_sha256": sha256_file(manifest_path),
            "source_hashes": {
                product["granule_name"]: product["source_sha256"]
                for product in source_manifest["products"]
            },
        }
        # Keep the analyzer's specific scientific blocker. Source-byte identity is
        # evidenced separately by the five validated SHA-256 pins above.
        report.setdefault("paper_reproduction_status", PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS)
        report["hazard_detection_status"] = "NOT_EVALUATED"
        _write_json_atomic(report_path, report)
        exploratory_analysis_success = analysis_result_is_complete(completed.returncode, report)

        # Run a separately labelled author-compatible site-series profile against the
        # same five verified raw HDF5 files. This must not re-download source data.
        author_report_path = output_root / "author-raw-site-series-report.json"
        author_stdout_path = output_root / "author-raw-site-series.stdout.log"
        author_stderr_path = output_root / "author-raw-site-series.stderr.log"
        author_exit_code: int | None
        try:
            author_completed = subprocess.run(
                [
                    sys.executable, "-m", "tools.know_place.author_raw_site_series",
                    "--config", str(run_root / "know-place-inputs.json"),
                    "--out", str(output_root),
                    "--terrain-root", str(terrain_root),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5 * 60 * 60,
            )
            author_exit_code = author_completed.returncode
            author_stdout_path.write_text(author_completed.stdout or "", encoding="utf-8")
            author_stderr_path.write_text(author_completed.stderr or "", encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            author_exit_code = None
            stdout_value = getattr(exc, "stdout", None) or ""
            stderr_value = getattr(exc, "stderr", None) or ""
            if isinstance(stdout_value, bytes):
                stdout_value = stdout_value.decode("utf-8", errors="replace")
            if isinstance(stderr_value, bytes):
                stderr_value = stderr_value.decode("utf-8", errors="replace")
            author_stdout_path.write_text(str(stdout_value), encoding="utf-8")
            author_stderr_path.write_text(str(stderr_value), encoding="utf-8")
            _write_json_atomic(author_report_path, {
                "schema_version": "know-place-author-raw-site-series/1.0",
                "status": "AUTHOR_SITE_SERIES_ANALYSIS_TIMEOUT",
                "structural_status": "FAIL",
                "method_profile": "ARCHIVED_AUTHOR_SITE_SERIES_COMPATIBLE",
                "source_products_processed": 0,
                "author_site_series_table_comparison": {
                    "status": "BLOCKED_TIMEOUT", "checks_passed": 0, "checks_total": 65,
                    "mismatch_count": None, "mismatches": [],
                },
                "paper_reproduction_status": PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS,
                "hazard_detection_status": "NOT_EVALUATED",
            })
        if not author_report_path.is_file():
            _write_json_atomic(author_report_path, {
                "schema_version": "know-place-author-raw-site-series/1.0",
                "status": "AUTHOR_SITE_SERIES_REPORT_MISSING",
                "structural_status": "FAIL",
                "method_profile": "ARCHIVED_AUTHOR_SITE_SERIES_COMPATIBLE",
                "source_products_processed": 0,
                "author_site_series_table_comparison": {
                    "status": "BLOCKED_REPORT_MISSING", "checks_passed": 0, "checks_total": 65,
                    "mismatch_count": None, "mismatches": [],
                },
                "paper_reproduction_status": PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS,
                "hazard_detection_status": "NOT_EVALUATED",
            })
        author_site_report = json.loads(author_report_path.read_text(encoding="utf-8"))
        author_site_success = author_site_series_result_is_complete(author_exit_code if author_exit_code is not None else -1, author_site_report)

        # Preserve both method paths in the main report. A numeric resemblance from
        # the exploratory path must not mask a mismatch in the author-compatible path.
        report["author_compatible_site_series"] = {
            "report_file": author_report_path.name,
            "status": author_site_report.get("status"),
            "structural_status": author_site_report.get("structural_status"),
            "method_profile": author_site_report.get("method_profile"),
            "archive_comparison": author_site_report.get("author_site_series_table_comparison"),
            "p2_archive_comparison": author_site_report.get("author_p2_table_comparison"),
            "exit_code": author_exit_code,
            "complete_and_archive_matched": author_site_success,
        }
        report["exploratory_analysis_complete"] = exploratory_analysis_success
        report["paper_reproduction_status"] = (
            "PARTIAL_AUTHOR_P1_P2_AND_POLYGON_METRICS_MATCH_FULL_FOOTPRINT_SCREEN_NOT_REPRODUCED"
            if author_site_success
            else PAPER_REPRODUCTION_STATUS_AFTER_AUTHOR_EXACT_INPUTS
        )
        report["hazard_detection_status"] = "NOT_EVALUATED"
        _write_json_atomic(report_path, report)

        analysis_success = exploratory_analysis_success and author_site_success
        status = {
            "schema_version": "know-place-author-exact-run-status/1.0",
            "status": (
                "OUTPUTS_WRITTEN" if report_path.is_file() and analysis_success
                else ("ANALYSIS_FAILED_REPORT_PRESERVED" if report_path.is_file() else "ANALYSIS_REPORT_MISSING")
            ),
            "analysis_exit_code": completed.returncode,
            "analysis_status": report.get("status"),
            "structural_status": report.get("structural_status"),
            "exploratory_analysis_complete": exploratory_analysis_success,
            "author_site_series_exit_code": author_exit_code,
            "author_site_series_status": author_site_report.get("status"),
            "author_site_series_table_comparison_status": author_site_report.get("author_site_series_table_comparison", {}).get("status"),
            "author_site_series_comparisons_passed": author_site_report.get("author_site_series_table_comparison", {}).get("checks_passed"),
            "author_site_series_comparisons_total": author_site_report.get("author_site_series_table_comparison", {}).get("checks_total"),
            "author_p2_table_comparison_status": author_site_report.get("author_p2_table_comparison", {}).get("status"),
            "author_p2_table_comparisons_passed": author_site_report.get("author_p2_table_comparison", {}).get("checks_passed"),
            "author_p2_table_comparisons_total": author_site_report.get("author_p2_table_comparison", {}).get("checks_total"),
            "author_site_series_complete_and_archive_matched": author_site_success,
            "analysis_metrics_complete": analysis_success,
            "paper_reproduction_status": report.get("paper_reproduction_status"),
            "hazard_detection_status": report.get("hazard_detection_status"),
            "source_manifest_sha256": sha256_file(manifest_path),
            "created_at_utc": _utc_now(),
        }
        _write_json_atomic(output_root / "author-exact-analysis-status.json", status)
        print(f"EXPLORATORY_ANALYSIS_EXIT_CODE={completed.returncode}")
        print(f"EXPLORATORY_ANALYSIS_STATUS={report.get('status')}")
        print(f"AUTHOR_SITE_SERIES_EXIT_CODE={author_exit_code}")
        print(f"AUTHOR_SITE_SERIES_STATUS={author_site_report.get('status')}")
        print("AUTHOR_SITE_SERIES_TABLE_PARITY=" + str(author_site_report.get("author_site_series_table_comparison", {}).get("status")))
        print(f"AUTHOR_SITE_SERIES_TABLE_CHECKS={author_site_report.get('author_site_series_table_comparison', {}).get('checks_passed')}/{author_site_report.get('author_site_series_table_comparison', {}).get('checks_total')}")
        print("AUTHOR_P2_TABLE_PARITY=" + str(author_site_report.get("author_p2_table_comparison", {}).get("status")))
        print(f"AUTHOR_P2_TABLE_CHECKS={author_site_report.get('author_p2_table_comparison', {}).get('checks_passed')}/{author_site_report.get('author_p2_table_comparison', {}).get('checks_total')}")
        print(f"PAPER_REPRODUCTION_STATUS={report.get('paper_reproduction_status')}")
        print("HAZARD_DETECTION_STATUS=NOT_EVALUATED")
        return status
    except subprocess.TimeoutExpired as exc:
        if getattr(exc, "stdout", None):
            payload = exc.stdout
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            (output_root / "analysis.stdout.log").write_text(str(payload), encoding="utf-8")
        if getattr(exc, "stderr", None):
            payload = exc.stderr
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            (output_root / "analysis.stderr.log").write_text(str(payload), encoding="utf-8")
        status = {
            "schema_version": "know-place-author-exact-run-status/1.0",
            "status": "ANALYSIS_TIMEOUT",
            "analysis_exit_code": None,
            "paper_reproduction_status": "BLOCKED_ANALYSIS_TIMEOUT",
            "hazard_detection_status": "NOT_EVALUATED",
            "source_manifest_sha256": sha256_file(manifest_path),
            "created_at_utc": _utc_now(),
        }
        _write_json_atomic(output_root / "author-exact-analysis-status.json", status)
        return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=("catalog", "preflight", "download-and-analyze"), required=True)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--science-root", type=Path)
    parser.add_argument("--terrain-root", type=Path)
    parser.add_argument("--consent-marker")
    parser.add_argument("--geometry-height-m", type=float, default=CROWN_GEOMETRY_HEIGHT_M)
    parser.add_argument("--control-draws", type=int, default=DEFAULT_CONTROL_DRAWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_CONTROL_SEED)
    args = parser.parse_args(argv)
    root = args.out_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.operation != "catalog" and args.science_root is None:
        parser.error("--science-root is required for preflight/download-and-analyze")
    try:
        if args.operation == "download-and-analyze":
            require_consent_marker(args.consent_marker)
            if args.terrain_root is None:
                raise AuthorExactAcquisitionError("PINNED_AUTHOR_TERRAIN_ROOT_REQUIRED")
            terrain_file = args.terrain_root.expanduser().resolve() / "elev_m.tif"
            if not terrain_file.is_file():
                raise AuthorExactAcquisitionError("PINNED_AUTHOR_TERRAIN_ELEVATION_MISSING")
            if sha256_file(terrain_file) != PINNED_AUTHOR_TERRAIN_ELEVATION_SHA256:
                raise AuthorExactAcquisitionError("PINNED_AUTHOR_TERRAIN_ELEVATION_SHA256_MISMATCH")
        rows, manifest = discover_exact_author_sources()
        if args.operation == "catalog":
            path = root / "author-exact-catalog-manifest.json"
            _write_json_atomic(path, manifest)
            print(f"AUTHOR_CMR_CATALOG_GATE={manifest['status']}")
            print(f"AUTHOR_EXACT_PRODUCTS_CONFIRMED={manifest['exact_cmr_confirmed_count']}/5")
            print("RAW_SOURCE_DOWNLOADS=0")
            print(f"MANIFEST={path}")
            return 0 if manifest["status"] == "PASS" else 2
        if args.operation == "preflight":
            path = root / "author-exact-preflight-manifest.json"
            report = authenticated_preflight(rows, science_root=args.science_root, output_path=path)
            print(f"AUTHOR_EXACT_PREFLIGHT={report['status']}")
            print(f"PRODUCTS_WITH_REMOTE_BYTES={report['passed_count']}/5")
            print("RAW_SOURCE_DOWNLOADS=0")
            return 0 if report["status"] == "PASS" else 2
        require_consent_marker(args.consent_marker)
        status = acquire_and_analyze(
            science_root=args.science_root,
            terrain_root=args.terrain_root,
            run_root=root / "source-run",
            output_root=root / "derived",
            consent_marker=args.consent_marker,
            expected_geometry_height_m=args.geometry_height_m,
            control_draws=args.control_draws,
            seed=args.seed,
        )
        return 0 if status["status"] == "OUTPUTS_WRITTEN" else 2
    except Exception as exc:
        print("AUTHOR_EXACT_ACQUISITION_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:{str(exc).split(':',maxsplit=1)[0][:160]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
