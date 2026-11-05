from __future__ import annotations

import argparse
from datetime import date
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import numpy as np
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.warp import reproject

from drive_upload_adapter import download_private_result_to_path
from river_shift.validation import save_validation_report, validate_binary_classification


MAX_SOURCE_ARTIFACT_BYTES = 250_000_000
MAX_REFERENCE_BYTES = 250_000_000
PREDICTION_PATH = "outputs/flood/during_water_mask.tif"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required workflow secret/environment value is missing: {name}")
    return value


def _safe_https_base(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Validation API base URL must be an HTTPS origin/base path without credentials.")
    return value.rstrip("/")


def _download_verified(item: dict, destination: Path) -> None:
    file_id = item.get("drive_file_id")
    size = item.get("bytes")
    expected_sha = item.get("sha256")
    if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
        raise ValueError("Source artifact has an invalid private Drive identifier.")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_SOURCE_ARTIFACT_BYTES:
        raise ValueError("Source artifact has an invalid or excessive declared size.")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
        raise ValueError("Source artifact has an invalid SHA-256 receipt.")
    receipt = download_private_result_to_path(file_id, destination, max_bytes=size)
    actual_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
    if receipt.get("bytes") != size or destination.stat().st_size != size or not hmac.compare_digest(actual_sha, expected_sha):
        destination.unlink(missing_ok=True)
        raise ValueError(f"Source artifact verification failed for {item.get('name', 'unknown')}.")
    print(f"RIVERSHIFT_VALIDATION_DOWNLOAD=PASS name={item.get('name')} bytes={size} sha256={actual_sha}", flush=True)


def _resolve_source_manifest(job_id: str, api_base_url: str) -> dict:
    secret = _required_env("RIVERSHIFT_CALLBACK_SECRET")
    body = json.dumps({"prediction_path": PREDICTION_PATH}, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    response = requests.post(
        f"{_safe_https_base(api_base_url)}/api/river-shift/jobs/{job_id}/validation-inputs",
        data=body,
        headers={"Content-Type": "application/json", "X-SARGuardian-Signature": signature},
        timeout=(10, 30),
    )
    if response.status_code != 200:
        raise ValueError(f"Could not resolve retained RiverShift source artifacts (HTTP {response.status_code}).")
    manifest = response.json()
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("engine") != "RiverShift"
        or manifest.get("job_id") != job_id
        or manifest.get("prediction", {}).get("path") != PREDICTION_PATH
        or manifest.get("result_report", {}).get("path") != "outputs/flood/river_shift_result.json"
    ):
        raise ValueError("Signed Dynamic API response did not match the RiverShift validation contract.")
    return manifest


def _align_reference_to_prediction(prediction: Path, reference: Path, aligned: Path) -> dict:
    """Align an independently labelled categorical raster to the NISAR grid with nearest neighbour."""
    with rasterio.open(prediction) as pred, rasterio.open(reference) as ref:
        if pred.crs is None or ref.crs is None:
            raise ValueError("Both NISAR prediction and independent reference must declare a CRS.")
        if pred.crs is None or not pred.crs.is_projected:
            raise ValueError("Validation requires a projected metre-based NISAR analysis grid.")
        if ref.count != 1:
            raise ValueError("Independent reference GeoTIFF must contain exactly one binary class band.")
        source_values = ref.read(1)
        source_valid = ref.read_masks(1) > 0
        if not source_valid.any():
            raise ValueError("Independent reference raster has no valid labelled pixels.")
        if not np.isin(source_values[source_valid], [0, 1]).all():
            raise ValueError("Independent reference must be binary: 0=non-water, 1=water; unlabelled pixels must be NoData.")

        source = np.where(source_valid, source_values, 255).astype(np.uint8, copy=False)
        destination = np.full((pred.height, pred.width), 255, dtype=np.uint8)
        reproject(
            source=source,
            destination=destination,
            src_transform=ref.transform,
            src_crs=ref.crs,
            src_nodata=255,
            dst_transform=pred.transform,
            dst_crs=pred.crs,
            dst_nodata=255,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
        profile = pred.profile.copy()
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        profile.update(
            driver="GTiff",
            count=1,
            dtype="uint8",
            nodata=255,
            compress="deflate",
            tiled=False,
        )
        aligned.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(aligned, "w", **profile) as output:
            output.write(destination, 1)

        return {
            "method": "nearest_neighbour_categorical_reprojection",
            "source_crs": ref.crs.to_string(),
            "target_crs": pred.crs.to_string(),
            "target_width": pred.width,
            "target_height": pred.height,
            "target_transform": list(pred.transform)[:6],
            "source_valid_pixels": int(source_valid.sum()),
            "aligned_valid_pixels": int(np.count_nonzero(destination != 255)),
        }


def _common_support_fraction(prediction: Path, reference: Path) -> float:
    with rasterio.open(prediction) as pred, rasterio.open(reference) as ref:
        if (
            pred.crs != ref.crs
            or pred.transform != ref.transform
            or pred.width != ref.width
            or pred.height != ref.height
        ):
            raise ValueError("Aligned reference and NISAR prediction do not share the exact target grid.")
        pred_valid = pred.read_masks(1) > 0
        ref_valid = ref.read_masks(1) > 0
        total = int(pred_valid.sum())
        common = int((pred_valid & ref_valid).sum())
    if total == 0:
        raise ValueError("NISAR prediction has no valid pixels.")
    return common / total


def validate(args: argparse.Namespace) -> dict:
    source_job_id = args.source_job_id.strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", source_job_id):
        raise ValueError("Source job ID must be a UUID.")
    reference_file_id = args.reference_drive_file_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", reference_file_id):
        raise ValueError("Reference Drive file ID is invalid.")
    reference_source = args.reference_source.strip()
    reference_method = args.reference_method.strip()
    if not reference_source or not reference_method:
        raise ValueError("Reference source and method are both required.")

    target_manifest = _resolve_source_manifest(source_job_id, args.api_base_url)
    prediction_item = target_manifest["prediction"]
    report_item = target_manifest["result_report"]
    if reference_file_id in {prediction_item["drive_file_id"], report_item["drive_file_id"]}:
        raise ValueError("The reference must be a separate file from the NISAR prediction and its report.")

    target_date = date.fromisoformat(target_manifest["prediction_observation_date"])
    reference_date = date.fromisoformat(args.reference_date)
    offset_days = abs((reference_date - target_date).days)
    if offset_days > args.maximum_date_offset_days:
        raise ValueError(
            f"Reference temporal offset is {offset_days} days; "
            f"the configured maximum is {args.maximum_date_offset_days} days."
        )

    root = Path(args.work_dir).resolve()
    flood_dir = root / "outputs" / "flood"
    reference_dir = root / "reference"
    flood_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = flood_dir / "during_water_mask.tif"
    report_path = flood_dir / "river_shift_result.json"
    reference_path = reference_dir / "reference_mask_source.tif"
    aligned_reference_path = reference_dir / "reference_mask_aligned_to_nisar.tif"

    _download_verified(prediction_item, prediction_path)
    _download_verified(report_item, report_path)
    ref_receipt = download_private_result_to_path(
        reference_file_id,
        reference_path,
        max_bytes=MAX_REFERENCE_BYTES,
    )
    if not reference_path.is_file() or reference_path.stat().st_size <= 0:
        raise ValueError("Reference GeoTIFF download was empty.")
    reference_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    if ref_receipt.get("bytes") != reference_path.stat().st_size:
        raise ValueError("Reference GeoTIFF download size receipt did not match.")
    print(f"RIVERSHIFT_REFERENCE_DOWNLOAD=PASS bytes={reference_path.stat().st_size} sha256={reference_sha}", flush=True)

    reference_alignment = _align_reference_to_prediction(prediction_path, reference_path, aligned_reference_path)
    print("RIVERSHIFT_REFERENCE_ALIGNMENT=PASS method=nearest_neighbour_categorical_reprojection", flush=True)
    support = _common_support_fraction(prediction_path, aligned_reference_path)
    print(f"RIVERSHIFT_COMMON_SUPPORT_FRACTION={support:.6f}", flush=True)
    if support < args.minimum_common_support_fraction:
        raise ValueError(
            f"INSUFFICIENT_REFERENCE_SUPPORT: observed={support:.6f}, "
            f"required={args.minimum_common_support_fraction:.6f}."
        )

    result = validate_binary_classification(
        str(prediction_path),
        str(aligned_reference_path),
        reference_source=reference_source,
        reference_date=reference_date.isoformat(),
        reference_method=reference_method,
        block_size_pixels=args.block_size_pixels,
        bootstrap_replicates=args.bootstrap_replicates,
        random_seed=args.random_seed,
    )
    if result.get("quality", {}).get("provenance_complete") is not True:
        raise ValueError("NISAR prediction checksum did not match its retained RiverShift source report.")
    result["source"]["river_shift_job_id"] = source_job_id
    result["source"]["github_run_id"] = target_manifest.get("github_run_id")
    result["reference"]["target_observation_date"] = target_date.isoformat()
    result["reference"]["temporal_offset_days"] = offset_days
    result["reference"]["common_support_fraction"] = support
    result["reference"]["reference_file_sha256"] = reference_sha
    result["reference"]["alignment"] = reference_alignment
    result["reference"]["independence_verified"] = False
    result["quality"]["status"] = "VALIDATION_METRICS_COMPUTED_REVIEW_REQUIRED"
    result["quality"]["release_status"] = "PROVISIONAL"
    result["quality"]["warnings"].append(
        "The declared reference still requires independent review for origin, positional accuracy, "
        "hydrological comparability and label quality. Metrics alone do not approve scientific release."
    )
    result["quality"]["warnings"].append(
        "This workflow validates water-class agreement only. It does not validate erosion/deposition "
        "causality, bankline displacement, sediment transport or river morphology."
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    save_validation_report(result, output)
    metrics = result["metrics"]
    cm = result["confusion_matrix"]
    print("RIVERSHIFT_INDEPENDENT_VALIDATION=METRICS_COMPUTED_REVIEW_REQUIRED")
    print("RIVERSHIFT_RELEASE_STATUS=PROVISIONAL")
    print(
        "RIVERSHIFT_CONFUSION_MATRIX="
        f"TP:{cm['true_positive']},TN:{cm['true_negative']},"
        f"FP:{cm['false_positive']},FN:{cm['false_negative']}"
    )
    for name in (
        "precision_user_accuracy",
        "recall_producer_accuracy",
        "f1_score",
        "intersection_over_union",
        "specificity",
        "cohen_kappa",
        "area_bias_percent",
    ):
        print(f"RIVERSHIFT_METRIC_{name.upper()}={metrics.get(name)}")
    print(f"RIVERSHIFT_VALIDATION_REPORT={output}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-job-id", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--reference-drive-file-id", required=True)
    parser.add_argument("--reference-source", required=True)
    parser.add_argument("--reference-date", required=True)
    parser.add_argument("--reference-method", required=True)
    parser.add_argument("--maximum-date-offset-days", type=int, default=3)
    parser.add_argument("--minimum-common-support-fraction", type=float, default=0.80)
    parser.add_argument("--block-size-pixels", type=int, default=64)
    parser.add_argument("--bootstrap-replicates", type=int, default=500)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--work-dir", type=Path, default=Path("validation-work"))
    parser.add_argument("--output", type=Path, default=Path("validation-work/outputs/validation/independent_reference_validation.json"))
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not 0 <= args.maximum_date_offset_days <= 30:
        parser.error("--maximum-date-offset-days must be between 0 and 30.")
    if not 0.5 <= args.minimum_common_support_fraction <= 1.0:
        parser.error("--minimum-common-support-fraction must be between 0.5 and 1.0.")
    if not 1 <= args.block_size_pixels <= 2048:
        parser.error("--block-size-pixels must be between 1 and 2048.")
    if not 100 <= args.bootstrap_replicates <= 10_000:
        parser.error("--bootstrap-replicates must be between 100 and 10000.")
    if not 0 <= args.random_seed <= 2**31 - 1:
        parser.error("--random-seed must be a non-negative 32-bit integer.")
    try:
        validate(args)
    except (OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
        print(f"RIVERSHIFT_INDEPENDENT_VALIDATION=FAIL reason={type(exc).__name__}: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
