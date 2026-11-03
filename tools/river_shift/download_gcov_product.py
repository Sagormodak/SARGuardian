#!/usr/bin/env python3
"""Download one exact NISAR L2 GCOV granule through NASA's earthaccess client."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


HDF5_SIGNATURE = bytes.fromhex("894844460d0a1a0a")
MATURITIES = {"BETA", "PROVISIONAL"}


def _load_earthaccess():
    """Lazy import keeps the module's pure validation helpers lightweight in tests."""
    import earthaccess

    return earthaccess


def _normal_granule_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip().split("?", 1)[0].split("#", 1)[0]).name.removesuffix(".h5")


def _earthaccess_granule_name(granule: Any) -> str | None:
    """Read the exact public granule identity from a CMR DataGranule result."""
    if not hasattr(granule, "get"):
        return None
    umm = granule.get("umm", {})
    if isinstance(umm, dict):
        return _normal_granule_name(umm.get("GranuleUR"))
    return None


def is_hdf5_file(path: Path) -> bool:
    """Recognize the HDF5 signature, including a permitted user block."""
    with path.open("rb") as stream:
        offset = 0
        while offset <= 1_048_576:
            stream.seek(offset)
            if stream.read(len(HDF5_SIGNATURE)) == HDF5_SIGNATURE:
                return True
            offset = 512 if offset == 0 else offset * 2
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_product(manifest_path: Path, granule_name: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        row for row in manifest.get("products", [])
        if row.get("granule_name") == granule_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one matching granule in the manifest; found {len(matches)}."
        )
    return matches[0]


def download_product(product: dict, output_dir: Path) -> dict:
    """Re-resolve and download exactly one accepted GCOV granule using earthaccess."""
    name = str(product.get("granule_name") or "")
    maturity = str(product.get("maturity") or "").upper()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{10,250}", name):
        raise ValueError("Granule name contains unsupported characters.")
    if maturity not in MATURITIES:
        raise ValueError("A known BETA or PROVISIONAL collection maturity is required.")

    expected_name = _normal_granule_name(name)
    collection = f"NISAR_L2_GCOV_{maturity}_V1"
    earthaccess = _load_earthaccess()

    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "earthdata_login",
        "status": "START",
        "auth_mode": "environment",
    }), flush=True)
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    has_password_credentials = bool(os.environ.get("EARTHDATA_USERNAME", "").strip()) and bool(
        os.environ.get("EARTHDATA_PASSWORD", "")
    )
    auth_mode = "bearer_token" if token else "username_password"
    try:
        earthaccess.login(strategy="environment")
    except Exception as first_error:
        # Match the working SARGuardian product downloader: a rejected/stale
        # pre-generated token must not prevent a valid EDL username/password
        # session from being tried once. Restore the original env afterwards.
        if not token or not has_password_credentials:
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "earthdata_login",
                "status": "FAIL",
                "auth_mode": auth_mode,
                "error_type": type(first_error).__name__,
            }), flush=True)
            raise RuntimeError(
                "Earthdata authentication failed; verify EARTHDATA_TOKEN or the Earthdata username/password secrets."
            ) from None
        try:
            os.environ.pop("EARTHDATA_TOKEN", None)
            earthaccess.login(strategy="environment")
            auth_mode = "username_password_fallback"
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "earthdata_login_fallback",
                "status": "PASS",
                "auth_mode": auth_mode,
            }), flush=True)
        except Exception as fallback_error:
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "earthdata_login_fallback",
                "status": "FAIL",
                "error_type": type(fallback_error).__name__,
            }), flush=True)
            raise RuntimeError(
                "Earthdata authentication failed with both the user token and username/password fallback."
            ) from None
        finally:
            os.environ["EARTHDATA_TOKEN"] = token
    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "earthdata_login",
        "status": "PASS",
        "auth_mode": auth_mode,
    }), flush=True)

    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "exact_cmr_granule_lookup",
        "status": "START",
        "collection": collection,
    }), flush=True)
    try:
        candidates = earthaccess.search_data(
            short_name=collection,
            granule_name=expected_name,
            downloadable=True,
            count=2,
        )
    except Exception as exc:
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "exact_cmr_granule_lookup",
            "status": "FAIL",
            "error_type": type(exc).__name__,
        }), flush=True)
        raise RuntimeError("NASA CMR exact-granule lookup failed.") from None

    exact_matches = [
        row for row in (candidates or [])
        if _earthaccess_granule_name(row) == expected_name
    ]
    if len(exact_matches) != 1:
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "exact_cmr_granule_lookup",
            "status": "FAIL",
            "exact_match_count": len(exact_matches),
        }), flush=True)
        raise RuntimeError(
            f"NASA CMR did not return exactly one {maturity} GCOV match for the accepted granule."
        )
    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "exact_cmr_granule_lookup",
        "status": "PASS",
        "exact_match_count": 1,
    }), flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"{expected_name}.h5"
    if final_path.exists():
        raise RuntimeError("The exact raw-product destination already exists; refusing to overwrite it.")

    temporary_dir = output_dir / f".{expected_name}.earthaccess-download"
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True, exist_ok=False)

    try:
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "earthaccess_download",
            "status": "START",
            "threads": 1,
            "requested_granule_count": 1,
        }), flush=True)
        try:
            downloaded_paths = earthaccess.download(
                exact_matches,
                local_path=str(temporary_dir),
                threads=1,
                show_progress=False,
            )
        except Exception as exc:
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "earthaccess_download",
                "status": "FAIL",
                "error_type": type(exc).__name__,
            }), flush=True)
            raise RuntimeError(
                "earthaccess could not download the exact NISAR GCOV granule; inspect the network/authentication diagnostics."
            ) from None

        paths = [Path(item).resolve() for item in (downloaded_paths or [])]
        if len(paths) != 1:
            raise RuntimeError(
                f"earthaccess returned {len(paths)} files for one exact GCOV granule; refusing ambiguous output."
            )

        downloaded_path = paths[0]
        temp_root = temporary_dir.resolve()
        if temp_root not in downloaded_path.parents or not downloaded_path.is_file():
            raise RuntimeError("earthaccess returned a missing or out-of-directory download path.")
        if downloaded_path.stem != expected_name:
            raise RuntimeError("earthaccess returned a filename that does not match the requested exact granule.")
        downloaded_bytes = downloaded_path.stat().st_size
        if downloaded_bytes <= 0:
            raise RuntimeError("The downloaded NISAR HDF5 file is empty.")
        if not is_hdf5_file(downloaded_path):
            raise RuntimeError(
                "The downloaded object does not contain the HDF5 signature; it may be an HTML/login or error response."
            )

        downloaded_path.replace(final_path)
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "earthaccess_download",
            "status": "PASS",
            "downloaded_bytes": downloaded_bytes,
        }), flush=True)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)

    source_url = product.get("download_url")
    source_host = urlparse(source_url).hostname if isinstance(source_url, str) else None
    result = {
        "schema_version": 1,
        "granule_name": expected_name,
        "product": "GCOV",
        "maturity": maturity,
        "collection_short_name": collection,
        "download_method": "earthaccess.download",
        "source_host": source_host,
        "file_path": str(final_path.resolve()),
        "size_bytes": final_path.stat().st_size,
        "sha256": sha256_file(final_path),
        "downloaded": True,
    }
    receipt_path = output_dir / f"{expected_name}.download.json"
    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--granule-name", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        product = find_product(args.catalogue, args.granule_name)
        if product.get("maturity") == "UNKNOWN":
            raise ValueError("Product maturity is unknown. Verify maturity in ASF Vertex before downloading.")
        result = download_product(product, args.out_dir)
        print(f"GCOV_FILE={result['file_path']}")
        print(f"GCOV_SHA256={result['sha256']}")
        print(f"GCOV_BYTES={result['size_bytes']}")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
