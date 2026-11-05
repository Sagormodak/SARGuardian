"""Read-only audit of retained SARGuardian Drive archives and logical duplicates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    from tools.drive_resumable_upload import API, Drive, DriveError, FOLDER_MIME
except ModuleNotFoundError:
    from drive_resumable_upload import API, Drive, DriveError, FOLDER_MIME

ARCHIVE_RE = re.compile(r"^NISAR_L2_.*\.science\.h5$")
RETENTION_RE = re.compile(r"^NISAR_L2_.*\.retention-manifest\.json$")


class AuditError(RuntimeError):
    """Raised when a read-only Drive audit cannot safely continue."""


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def logical_archive_signature(manifest: dict[str, Any]) -> str:
    """Fingerprint retained HDF5 content/schema while ignoring container bytes.

    The source SHA-256 anchors the exact input file. The remaining fingerprint
    includes each retained dataset's logical digest, shape, dtype, attributes,
    creation properties and the source group/link metadata. It deliberately
    excludes the output HDF5 container SHA-256, which may differ between
    logically equivalent lossless archives.
    """
    source = manifest.get("source") or {}
    policy = manifest.get("policy") or {}
    stats = manifest.get("statistics") or {}

    datasets = [{
        "path": row.get("path"),
        "shape": row.get("shape"),
        "ndim": row.get("ndim"),
        "dtype": row.get("dtype"),
        "attrs_sha256": row.get("attrs_sha256"),
        "logical_data_sha256": row.get("logical_data_sha256"),
        "dimension_links": row.get("dimension_links") or [],
        "retention_status": row.get("retention_status"),
        "reason": row.get("reason"),
        "archive_dtype": row.get("archive_dtype"),
        "archive_shape": row.get("archive_shape"),
        "dataset_creation_properties": row.get("dataset_creation_properties") or {},
    } for row in (manifest.get("retained_datasets") or [])]
    datasets.sort(key=lambda row: str(row.get("path") or ""))

    groups = [{
        "path": row.get("path"),
        "attrs_sha256": row.get("attrs_sha256"),
    } for row in (manifest.get("source_group_attributes") or [])]
    groups.sort(key=lambda row: str(row.get("path") or ""))

    skipped_attrs = [{
        "object_path": row.get("object_path"),
        "attribute": row.get("attribute"),
        "reason": row.get("reason"),
    } for row in (manifest.get("skipped_hdf5_reference_attributes") or [])]
    skipped_attrs.sort(key=lambda row: (
        str(row.get("object_path") or ""),
        str(row.get("attribute") or ""),
        str(row.get("reason") or ""),
    ))

    stable = {
        "source_sha256": source.get("sha256"),
        "source_hdf5_root_attrs_sha256": source.get("hdf5_root_attrs_sha256"),
        "retention_profile": policy.get("retention_profile"),
        "product_type": policy.get("product_type"),
        "source_dataset_count": stats.get("source_dataset_count"),
        "retained_dataset_count": stats.get("retained_dataset_count"),
        "excluded_large_dataset_count": stats.get("excluded_large_dataset_count"),
        "derived_dataset_count": stats.get("derived_dataset_count"),
        "source_group_attributes": groups,
        "noncanonical_links": sorted(
            manifest.get("noncanonical_links") or [],
            key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False, default=str),
        ),
        "retained_datasets": datasets,
        "excluded_datasets": sorted(
            [{
                "path": row.get("path"),
                "shape": row.get("shape"),
                "dtype": row.get("dtype"),
                "reason": row.get("reason"),
                "logical_data_sha256": row.get("logical_data_sha256"),
            } for row in (manifest.get("excluded_datasets") or [])],
            key=lambda row: str(row.get("path") or ""),
        ),
        "derived_datasets": sorted(
            [{
                "path": row.get("path"),
                "shape": row.get("shape"),
                "dtype": row.get("dtype"),
                "logical_data_sha256": row.get("logical_data_sha256"),
                "attrs_sha256": row.get("attrs_sha256"),
            } for row in (manifest.get("derived_datasets") or [])],
            key=lambda row: str(row.get("path") or ""),
        ),
        "skipped_hdf5_reference_attributes": skipped_attrs,
    }
    return canonical_json_hash(stable)


def validate_full_lossless_manifest(
    manifest: dict[str, Any], product_type: str, granule_name: str
) -> list[str]:
    errors: list[str] = []
    policy = manifest.get("policy") or {}
    source = manifest.get("source") or {}
    archive = manifest.get("archive") or {}
    stats = manifest.get("statistics") or {}
    verification = manifest.get("verification") or {}
    source_name = Path(str(source.get("filename") or "")).name
    source_granule = source_name[:-3] if source_name.lower().endswith(".h5") else source_name

    if manifest.get("schema_version") != "sarguardian-science-archive/1.2":
        errors.append("unsupported_retention_manifest_schema")
    if policy.get("retention_profile") != "full-lossless":
        errors.append("archive_not_full_lossless")
    if policy.get("product_type") != product_type:
        errors.append("retention_manifest_product_type_mismatch")
    if source_granule != granule_name:
        errors.append("retention_manifest_granule_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256") or "")):
        errors.append("invalid_source_sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", str(archive.get("sha256") or "")):
        errors.append("invalid_archive_sha256")

    source_count = stats.get("source_dataset_count")
    retained_count = stats.get("retained_dataset_count")
    if not isinstance(source_count, int) or source_count <= 0 or retained_count != source_count:
        errors.append("source_retained_dataset_count_mismatch")
    if stats.get("excluded_large_dataset_count") != 0 or manifest.get("excluded_datasets"):
        errors.append("full_lossless_archive_has_exclusions")
    if len(manifest.get("retained_datasets") or []) != retained_count:
        errors.append("retained_dataset_inventory_count_mismatch")
    if any(row.get("retention_status") != "retained" for row in (manifest.get("retained_datasets") or [])):
        errors.append("retained_inventory_contains_nonretained_dataset")
    for field in ("local_archive_verification", "retained_data_logical_checksums", "dimension_scale_verification"):
        if verification.get(field) != "PASS":
            errors.append(f"archive_verification_not_pass:{field}")
    if stats.get("archive_bytes") != archive.get("bytes"):
        errors.append("archive_manifest_size_mismatch")
    if stats.get("source_bytes") != source.get("bytes"):
        errors.append("source_manifest_size_mismatch")
    return errors


def list_children(drive: Any, parent_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "q": f"'{drive._q(parent_id)}' in parents and trashed = false",
            "spaces": "drive",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "fields": (
                "nextPageToken,files(id,name,mimeType,size,md5Checksum,parents,description,"
                "createdTime,modifiedTime,shortcutDetails)"
            ),
        }
        if page_token:
            params["pageToken"] = page_token
        data = drive.request("GET", f"{API}/files", params=params).json()
        rows.extend(row for row in data.get("files", []) if isinstance(row, dict))
        page_token = data.get("nextPageToken")
        if not page_token:
            return rows


def folders_named(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get("name") == name and row.get("mimeType") == FOLDER_MIME
    ]


def read_remote_json(drive: Any, file_id: str) -> dict[str, Any]:
    response = drive.request(
        "GET",
        f"{API}/files/{quote(file_id, safe='')}",
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=(20, 90),
    )
    try:
        data = json.loads(response.content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise AuditError("REMOTE_JSON_FILE_INVALID") from exc
    finally:
        response.close()
    if not isinstance(data, dict):
        raise AuditError("REMOTE_JSON_ROOT_NOT_OBJECT")
    return data


def inspect_run_folder(
    drive: Any,
    files: list[dict[str, Any]],
    *,
    run_folder_id: str,
    run_folder_name: str,
    run_created_time: str,
    product_type: str,
    maturity: str,
    granule_name: str,
) -> dict[str, Any] | None:
    archives = [row for row in files if ARCHIVE_RE.fullmatch(str(row.get("name") or ""))]
    if not archives:
        return None
    base_record = {
        "product_type": product_type,
        "maturity": maturity,
        "granule_name": granule_name,
        "run_folder": run_folder_name,
        "run_created_time": run_created_time,
        "archive_name": archives[0].get("name"),
        "archive_bytes": int(archives[0].get("size") or 0),
    }
    if len(archives) != 1:
        return {**base_record, "status": "UNVERIFIED", "errors": ["archive_file_count_not_one"]}

    archive_file = archives[0]
    retention_files = [row for row in files if RETENTION_RE.fullmatch(str(row.get("name") or ""))]
    processing_files = [row for row in files if row.get("name") == "product-processing.json"]
    receipt_files = [row for row in files if row.get("name") == "drive-retention-receipt.json"]
    if len(retention_files) != 1 or len(processing_files) != 1 or len(receipt_files) != 1:
        return {**base_record, "status": "UNVERIFIED", "errors": ["required_provenance_file_missing_or_duplicated"]}

    errors: list[str] = []
    try:
        retention = read_remote_json(drive, str(retention_files[0]["id"]))
        processing = read_remote_json(drive, str(processing_files[0]["id"]))
        receipt = read_remote_json(drive, str(receipt_files[0]["id"]))
    except Exception as exc:
        return {**base_record, "status": "UNVERIFIED", "errors": [f"provenance_read_failed:{type(exc).__name__}"]}

    errors.extend(validate_full_lossless_manifest(retention, product_type, granule_name))
    source = retention.get("source") or {}
    archived = retention.get("archive") or {}

    checks = {
        "processing_product_type_mismatch": processing.get("product_type") == product_type,
        "processing_maturity_mismatch": processing.get("maturity") == maturity,
        "processing_granule_mismatch": processing.get("granule_name") == granule_name + ".h5",
        "processing_profile_mismatch": processing.get("retention_profile") == "full-lossless",
        "processing_source_sha256_mismatch": processing.get("source_file_sha256") == source.get("sha256"),
        "processing_archive_sha256_mismatch": processing.get("retained_archive_sha256") == archived.get("sha256"),
        "processing_drive_verification_not_pass": processing.get("drive_remote_verification") == "PASS",
        "processing_remote_folder_mismatch": processing.get("drive_remote_folder_id") == run_folder_id,
        "drive_receipt_verification_not_pass": receipt.get("remote_verification") == "PASS",
        "drive_receipt_folder_mismatch": receipt.get("remote_folder_id") == run_folder_id,
    }
    errors.extend(name for name, passed in checks.items() if not passed)

    receipt_archives = [row for row in receipt.get("files", []) if row.get("name") == archive_file.get("name")]
    receipt_archive = receipt_archives[0] if len(receipt_archives) == 1 else {}
    try:
        remote_size = int(archive_file.get("size", -1))
        receipt_size = int(receipt_archive.get("bytes", -1))
    except (TypeError, ValueError):
        remote_size, receipt_size = -1, -1
        errors.append("remote_archive_size_unparseable")
    if len(receipt_archives) != 1:
        errors.append("drive_receipt_archive_entry_count_not_one")
    if remote_size <= 0 or remote_size != archived.get("bytes") or receipt_size != remote_size:
        errors.append("remote_archive_size_mismatch")
    remote_md5 = str(archive_file.get("md5Checksum") or "").lower()
    receipt_md5 = str(receipt_archive.get("md5") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", remote_md5) or remote_md5 != receipt_md5:
        errors.append("remote_archive_md5_mismatch")
    if receipt_archive.get("sha256") != archived.get("sha256"):
        errors.append("drive_receipt_archive_sha256_mismatch")
    description_match = re.search(r"sha256=([0-9a-f]{64})", str(archive_file.get("description") or ""))
    if description_match and description_match.group(1) != archived.get("sha256"):
        errors.append("remote_archive_description_sha256_mismatch")

    record = {
        **base_record,
        "status": "VERIFIED_FULL_LOSSLESS" if not errors else "UNVERIFIED",
        "errors": errors,
        "archive_bytes": remote_size,
        "archive_sha256": archived.get("sha256"),
        "archive_md5": remote_md5,
        "source_sha256": source.get("sha256"),
        "source_bytes": source.get("bytes"),
        "source_dataset_count": (retention.get("statistics") or {}).get("source_dataset_count"),
        "retained_dataset_count": (retention.get("statistics") or {}).get("retained_dataset_count"),
        "excluded_dataset_count": (retention.get("statistics") or {}).get("excluded_large_dataset_count"),
        "logical_signature": logical_archive_signature(retention),
    }
    return record


def build_report_from_records(
    records: list[dict[str, Any]],
    inventory_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inventory_issues = inventory_issues or []
    verified = [row for row in records if row.get("status") == "VERIFIED_FULL_LOSSLESS"]
    unverified = [row for row in records if row.get("status") != "VERIFIED_FULL_LOSSLESS"]
    by_source: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in verified:
        key = (
            str(row.get("product_type")), str(row.get("maturity")),
            str(row.get("granule_name")), str(row.get("source_sha256")),
        )
        by_source[key].append(row)

    duplicate_groups: list[dict[str, Any]] = []
    inconsistent_groups: list[dict[str, Any]] = []
    candidate_reclaimable_bytes = 0
    unique_sources = set()
    for key, copies in sorted(by_source.items()):
        product_type, maturity, granule_name, source_sha = key
        signatures = {str(row.get("logical_signature")) for row in copies}
        unique_sources.add(key)
        if len(signatures) > 1:
            inconsistent_groups.append({
                "product_type": product_type,
                "maturity": maturity,
                "granule_name": granule_name,
                "source_sha256": source_sha,
                "copy_count": len(copies),
                "issue": "same_source_hash_but_logical_signature_differs",
                "runs": [{
                    "run_folder": row.get("run_folder"),
                    "archive_sha256": row.get("archive_sha256"),
                    "archive_bytes": row.get("archive_bytes"),
                    "logical_signature": row.get("logical_signature"),
                } for row in copies],
            })
            continue
        if len(copies) > 1:
            ordered = sorted(copies, key=lambda row: (
                str(row.get("run_created_time") or ""),
                str(row.get("run_folder") or ""),
            ))
            keeper, redundant = ordered[0], ordered[1:]
            reclaimable = sum(int(row.get("archive_bytes") or 0) for row in redundant)
            candidate_reclaimable_bytes += reclaimable
            duplicate_groups.append({
                "product_type": product_type,
                "maturity": maturity,
                "granule_name": granule_name,
                "source_sha256": source_sha,
                "logical_signature": next(iter(signatures)),
                "copy_count": len(copies),
                "archive_bytes_per_copy": sorted(int(row.get("archive_bytes") or 0) for row in copies),
                "recommended_keep_run_folder": keeper.get("run_folder"),
                "candidate_duplicate_run_folders": [row.get("run_folder") for row in redundant],
                "candidate_reclaimable_bytes": reclaimable,
                "archive_sha256_values_differ": len({row.get("archive_sha256") for row in copies}) > 1,
                "deletion_performed": False,
            })

    verified_bytes = sum(int(row.get("archive_bytes") or 0) for row in verified)
    unverified_bytes = sum(int(row.get("archive_bytes") or 0) for row in unverified)
    status = "PASS" if not unverified and not inconsistent_groups and not inventory_issues else "REVIEW_REQUIRED"
    return {
        "schema_version": "sarguardian-drive-archive-audit/1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "audit_mode": "read-only",
        "deletion_performed": False,
        "configured_root": "SARGuardian-DataArchive",
        "status": status,
        "summary": {
            "archive_copies_found": len(records),
            "verified_full_lossless_copies": len(verified),
            "unverified_copies": len(unverified),
            "unique_verified_source_products": len(unique_sources),
            "logically_duplicate_groups": len(duplicate_groups),
            "candidate_duplicate_copies": sum(max(0, group["copy_count"] - 1) for group in duplicate_groups),
            "candidate_reclaimable_bytes": candidate_reclaimable_bytes,
            "candidate_reclaimable_gb_decimal": round(candidate_reclaimable_bytes / 1_000_000_000, 3),
            "verified_archive_bytes": verified_bytes,
            "unverified_archive_bytes": unverified_bytes,
            "inconsistent_same_source_groups": len(inconsistent_groups),
            "inventory_issues": len(inventory_issues),
        },
        "logically_duplicate_groups": duplicate_groups,
        "inconsistent_same_source_groups": inconsistent_groups,
        "unverified_archives": [{
            "product_type": row.get("product_type"),
            "maturity": row.get("maturity"),
            "granule_name": row.get("granule_name"),
            "run_folder": row.get("run_folder"),
            "archive_name": row.get("archive_name"),
            "archive_bytes": row.get("archive_bytes"),
            "errors": row.get("errors"),
        } for row in unverified],
        "inventory_issues": inventory_issues,
        "all_archive_records": [{
            field: row.get(field) for field in (
                "product_type", "maturity", "granule_name", "run_folder", "run_created_time",
                "status", "archive_name", "archive_bytes", "archive_sha256", "source_sha256",
                "source_bytes", "source_dataset_count", "retained_dataset_count", "excluded_dataset_count",
            )
        } for row in records],
        "safety_note": (
            "No Drive files were deleted or modified. Candidate reclaimable bytes count only extra "
            "copies whose source SHA-256 and full-lossless logical dataset/attribute signature match "
            "and whose individual Drive size/MD5 receipt validates. Review before any deletion."
        ),
    }


def audit_drive(drive: Any, configured_parent_id: str) -> dict[str, Any]:
    parent_children = list_children(drive, configured_parent_id)
    archive_roots = folders_named(parent_children, "SARGuardian-DataArchive")
    if len(archive_roots) != 1:
        raise AuditError("SAR_GUARDIAN_ARCHIVE_ROOT_MISSING_OR_DUPLICATED")
    root = archive_roots[0]

    records: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    root_children = list_children(drive, str(root["id"]))
    for product_type in ("GUNW", "GOFF"):
        type_folders = folders_named(root_children, product_type)
        if len(type_folders) > 1:
            issues.append({"product_type": product_type, "issue": "duplicate_product_type_folder"})
            continue
        if not type_folders:
            continue
        type_children = list_children(drive, str(type_folders[0]["id"]))
        for maturity in ("BETA", "PROVISIONAL"):
            maturity_folders = folders_named(type_children, maturity)
            if len(maturity_folders) > 1:
                issues.append({"product_type": product_type, "maturity": maturity, "issue": "duplicate_maturity_folder"})
                continue
            if not maturity_folders:
                continue
            for granule in list_children(drive, str(maturity_folders[0]["id"])):
                if granule.get("mimeType") != FOLDER_MIME or not str(granule.get("name") or "").startswith("NISAR_L2_"):
                    continue
                granule_name = str(granule["name"])
                runs_folders = folders_named(list_children(drive, str(granule["id"])), "Runs")
                if len(runs_folders) > 1:
                    issues.append({
                        "product_type": product_type, "maturity": maturity,
                        "granule_name": granule_name, "issue": "duplicate_runs_folder",
                    })
                    continue
                if not runs_folders:
                    continue
                for run_folder in list_children(drive, str(runs_folders[0]["id"])):
                    if run_folder.get("mimeType") != FOLDER_MIME:
                        continue
                    files = list_children(drive, str(run_folder["id"]))
                    record = inspect_run_folder(
                        drive, files,
                        run_folder_id=str(run_folder["id"]),
                        run_folder_name=str(run_folder.get("name") or "unknown-run"),
                        run_created_time=str(run_folder.get("createdTime") or ""),
                        product_type=product_type, maturity=maturity, granule_name=granule_name,
                    )
                    if record is not None:
                        records.append(record)
    return build_report_from_records(records, issues)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="local output path for JSON report")
    args = parser.parse_args()
    try:
        parent_id = os.environ.get("GOOGLE_DRIVE_PARENT_FOLDER_ID", "").strip()
        if not parent_id:
            raise AuditError("MISSING_ENV_GOOGLE_DRIVE_PARENT_FOLDER_ID")
        report = audit_drive(Drive(), parent_id)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (AuditError, DriveError, OSError, ValueError) as exc:
        print(f"ERROR=DRIVE_ARCHIVE_AUDIT_FAILED TYPE={type(exc).__name__} DETAIL={str(exc)[:180]}", file=sys.stderr)
        return 2

    summary = report["summary"]
    print(f"DRIVE_ARCHIVE_AUDIT_STATUS={report['status']}")
    print(f"ARCHIVE_COPIES_FOUND={summary['archive_copies_found']}")
    print(f"VERIFIED_FULL_LOSSLESS_COPIES={summary['verified_full_lossless_copies']}")
    print(f"UNIQUE_VERIFIED_SOURCE_PRODUCTS={summary['unique_verified_source_products']}")
    print(f"LOGICALLY_DUPLICATE_GROUPS={summary['logically_duplicate_groups']}")
    print(f"CANDIDATE_DUPLICATE_COPIES={summary['candidate_duplicate_copies']}")
    print(f"CANDIDATE_RECLAIMABLE_BYTES={summary['candidate_reclaimable_bytes']}")
    print("FILES_DELETED=0")
    print(f"REPORT_PATH={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
