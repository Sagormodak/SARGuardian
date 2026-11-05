#!/usr/bin/env python3
"""Prepare shared Google Drive ancestors before AOI product workers run concurrently.

The product workers retain responsibility for one granule each: download, process,
verify outputs, upload with checksums, then delete local raw data only after verified
remote retention. This preflight creates only common Drive ancestors to avoid two
workers racing to create the same parent folders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from drive_resumable_upload import Drive, DriveError, granule_folder_names, required_env


def prepare_drive_folders(
    manifest: dict[str, Any],
    drive: Any,
    parent_id: str,
    version_tag: str,
) -> int:
    """Validate all selected product paths, then create shared ancestors serially."""
    if not isinstance(manifest, dict):
        raise ValueError("AOI_MANIFEST_INVALID")
    products = manifest.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("AOI_MANIFEST_HAS_NO_SELECTED_PRODUCTS")
    if not parent_id or not version_tag:
        raise ValueError("DRIVE_PARENT_AND_VERSION_TAG_REQUIRED")

    prepared: list[tuple[str, list[str]]] = []
    seen_products: set[tuple[str, str, str]] = set()
    seen_ids: set[str] = set()

    # Validate every product before making any remote mutation.
    for row in products:
        if not isinstance(row, dict):
            raise ValueError("AOI_MANIFEST_PRODUCT_INVALID")
        product_type = str(row.get("product_type") or "").strip().upper()
        maturity = str(row.get("maturity") or "").strip().upper()
        granule_name = str(row.get("granule_name") or "").strip()
        product_id = str(row.get("id") or "").strip()
        if not product_id or not granule_name or product_id in seen_ids:
            raise ValueError("AOI_MANIFEST_DUPLICATE_OR_INCOMPLETE_PRODUCT")
        identity = (product_type, maturity, granule_name)
        if identity in seen_products:
            raise ValueError("AOI_MANIFEST_DUPLICATE_OR_INCOMPLETE_PRODUCT")

        names = granule_folder_names(
            product_type, maturity, granule_name, version_tag=version_tag
        )
        if (
            not isinstance(names, list)
            or len(names) < 6
            or any(not isinstance(name, str) or not name for name in names)
            or names[-2:] != ["Runs", version_tag]
        ):
            raise ValueError("DRIVE_FOLDER_PATH_INVALID")

        # [archive, family, maturity] are shared. Granule/Runs/version are unique.
        shared_names = names[:-3]
        if len(shared_names) != 3:
            raise ValueError("DRIVE_SHARED_FOLDER_PREFIX_INVALID")
        seen_products.add(identity)
        seen_ids.add(product_id)
        prepared.append((product_id, shared_names))

    folder_ids: dict[tuple[str, str], str] = {}
    for product_id, names in prepared:
        parent = parent_id
        for name in names:
            key = (parent, name)
            folder_id = folder_ids.get(key)
            if folder_id is None:
                folder_id = drive.ensure_folder(parent, name)
                if not isinstance(folder_id, str) or not folder_id:
                    raise DriveError("DRIVE_FOLDER_PREPARATION_RETURNED_INVALID_ID")
                folder_ids[key] = folder_id
            parent = folder_id
        print(f"DRIVE_PRODUCT_SHARED_ANCESTORS_PREPARED id={product_id}")

    print(f"DRIVE_PRODUCTS_WITH_SHARED_ANCESTORS_PREPARED={len(prepared)}")
    print(f"DRIVE_UNIQUE_SHARED_FOLDER_EDGES={len(folder_ids)}")
    return len(prepared)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        drive = Drive()
        prepare_drive_folders(
            manifest,
            drive,
            required_env("GOOGLE_DRIVE_PARENT_FOLDER_ID"),
            required_env("DRIVE_VERSION_TAG"),
        )
    except (OSError, json.JSONDecodeError, ValueError, DriveError) as exc:
        print(
            f"ERROR=DRIVE_PRODUCT_FOLDER_PREFLIGHT_FAILED reason={str(exc)[:240]}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
