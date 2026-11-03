#!/usr/bin/env python3
"""Download one exact GCOV product listed in an ASF catalogue manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests


TRUSTED_ASF_HOSTS = {
    "nisar.asf.earthdatacloud.nasa.gov",
    "asf.alaska.edu",
    "datapool.asf.alaska.edu",
}
TRUSTED_EARTHDATA_AUTH_HOSTS = {"urs.earthdata.nasa.gov"}
HDF5_SIGNATURE = b"\\x89HDF\\r\\n\\x1a\\n"


def trusted_asf_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() in TRUSTED_ASF_HOSTS
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def trusted_redirect_chain(response: requests.Response) -> bool:
    """Allow only ASF product hosts and the official Earthdata Login host."""
    for hop in [*getattr(response, "history", []), response]:
        try:
            parsed = urlparse(str(hop.url))
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme != "https"
                or parsed.port not in (None, 443)
                or parsed.username is not None
                or parsed.password is not None
                or host not in TRUSTED_ASF_HOSTS | TRUSTED_EARTHDATA_AUTH_HOSTS
            ):
                return False
        except (TypeError, ValueError):
            return False
    return urlparse(str(response.url)).hostname in TRUSTED_ASF_HOSTS


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
        raise ValueError(f"Expected exactly one matching granule in the manifest; found {len(matches)}.")
    return matches[0]


def build_product_url(granule_name: str, maturity: str) -> str:
    """Build an official ASF HTTPS asset URL from an exact GCOV collection identity."""
    if maturity not in {"BETA", "PROVISIONAL"}:
        raise ValueError("A known BETA or PROVISIONAL maturity is required to construct an ASF URL.")
    name = granule_name.removesuffix(".h5")
    fields = name.split("_")
    if (
        len(fields) != 18
        or fields[0] != "NISAR"
        or fields[1] != "L2"
        or fields[2] not in {"PR", "UR", "OD"}
        or fields[3] != "GCOV"
        or fields[6] not in {"A", "D"}
        or fields[15] not in {"F", "P"}
        or not re.fullmatch(r"[0-9]{3}", fields[4])
        or not re.fullmatch(r"[0-9]{3}", fields[5])
        or not re.fullmatch(r"[0-9]{3}", fields[7])
    ):
        raise ValueError("Granule name does not match the official NISAR single-acquisition GCOV convention.")
    return (
        "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
        f"NISAR_L2_GCOV_{maturity}_V1/{name}/{name}.h5"
    )


def download_product(product: dict, output_dir: Path, timeout_seconds: int) -> dict:
    name = str(product.get("granule_name") or "")
    url = product.get("download_url")
    if not url and product.get("maturity") in {"BETA", "PROVISIONAL"}:
        url = build_product_url(name, str(product["maturity"]))
    if not isinstance(url, str) or not trusted_asf_url(url):
        raise ValueError("Catalogue record has no trusted HTTPS ASF product URL.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{10,250}", name):
        raise ValueError("Granule name contains unsupported characters.")
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / f"{name}.h5"
    partial_path = output_dir / f"{name}.h5.part"
    token = os.getenv("EARTHDATA_TOKEN", "").strip()

    session = requests.Session()
    session.trust_env = True  # Requests reads the user's protected .netrc when present.
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})

    try:
        with session.get(
            url,
            stream=True,
            allow_redirects=True,
            timeout=(30, timeout_seconds),
        ) as response:
            response.raise_for_status()
            if not trusted_redirect_chain(response):
                raise RuntimeError("ASF download redirected outside the trusted ASF/Earthdata hosts.")
            expected_header = response.headers.get("Content-Length")
            expected_bytes = int(expected_header) if expected_header and expected_header.isdigit() else None
            downloaded = 0
            digest = hashlib.sha256()
            with partial_path.open("wb") as target:
                for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                    if not chunk:
                        continue
                    target.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    print(f"DOWNLOAD_PROGRESS_BYTES={downloaded}", flush=True)

        if downloaded <= 0:
            raise RuntimeError("Downloaded file is empty.")
        if not is_hdf5_file(partial_path):
            raise RuntimeError("ASF response is not a valid HDF5 product; an HTML/login or error page may have been returned.")
        if expected_bytes is not None and downloaded != expected_bytes:
            raise RuntimeError(
                f"Downloaded byte count {downloaded} does not match HTTP Content-Length {expected_bytes}."
            )
        partial_path.replace(final_path)
    except requests.exceptions.HTTPError as exc:
        partial_path.unlink(missing_ok=True)
        status = getattr(exc.response, "status_code", None)
        if status in {401, 403}:
            raise RuntimeError(
                "Earthdata authentication was rejected. Configure EARTHDATA_TOKEN or a protected ~/.netrc entry."
            ) from None
        raise RuntimeError(f"ASF download failed with HTTP status {status or 'unknown'}.") from None
    except requests.exceptions.RequestException:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError("ASF download failed due to a network or timeout error.") from None
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    result = {
        "schema_version": 1,
        "granule_name": name,
        "product": "GCOV",
        "maturity": product.get("maturity", "UNKNOWN"),
        "source_host": urlparse(url).hostname,
        "file_path": str(final_path.resolve()),
        "size_bytes": final_path.stat().st_size,
        "sha256": sha256_file(final_path),
        "downloaded": True,
    }
    (output_dir / f"{name}.download.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--granule-name", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--read-timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        product = find_product(args.catalogue, args.granule_name)
        if product.get("maturity") == "UNKNOWN":
            raise ValueError("Product maturity is unknown. Verify maturity in ASF Vertex before downloading.")
        result = download_product(product, args.out_dir, args.read_timeout)
        print(f"GCOV_FILE={result['file_path']}")
        print(f"GCOV_SHA256={result['sha256']}")
        print(f"GCOV_BYTES={result['size_bytes']}")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
