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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import requests


HDF5_SIGNATURE = bytes.fromhex("894844460d0a1a0a")
MATURITIES = {"BETA", "PROVISIONAL"}
RANGE_PART_BYTES = 256 * 1024 * 1024
RANGE_DOWNLOAD_WORKERS = 2
RANGE_MAX_ATTEMPTS = 3
DOWNLOAD_STREAM_CHUNK_BYTES = 8 * 1024 * 1024
EARTHDATA_LOGIN_MAX_ATTEMPTS = 3
TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504, 522, 524})


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


def _http_status_code(error: BaseException) -> int | None:
    """Extract an HTTP status from an exception or its chained causes."""
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        try:
            numeric_status = int(status)
        except (TypeError, ValueError):
            numeric_status = None
        if numeric_status is not None and 100 <= numeric_status <= 599:
            return numeric_status
        match = re.search(
            r"(?:Status code|HTTP(?: status)?)\\s*[:=]?\\s*(\\d{3})\\b",
            str(current),
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1))
        for nested in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


def _earthdata_http_auth_rejection(error: BaseException) -> int | None:
    """Return only explicit HTTP 401/403 authentication denials."""
    status = _http_status_code(error)
    return status if status in {401, 403} else None


def _reauthenticate_with_username_password(earthaccess) -> bool:
    """Replace an unverified bearer-token session with a fresh EDL password session.

    earthaccess 0.19.0 treats an environment token as locally authenticated before
    the first file request. Its module-level Auth cache must therefore be reset
    before a username/password fallback can actually run.
    """
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    username = os.environ.get("EARTHDATA_USERNAME", "").strip()
    password = os.environ.get("EARTHDATA_PASSWORD", "")
    if not token or not username or not password:
        return False

    old_auth = getattr(earthaccess, "_auth", None)
    old_store = getattr(earthaccess, "_store", None)
    try:
        os.environ.pop("EARTHDATA_TOKEN", None)
        if not hasattr(earthaccess, "Auth") or not hasattr(earthaccess, "_auth"):
            return False
        earthaccess._auth = earthaccess.Auth()
        earthaccess._store = None
        earthaccess.login(strategy="environment")
        return True
    except Exception:
        if old_auth is not None:
            earthaccess._auth = old_auth
        if hasattr(earthaccess, "_store"):
            earthaccess._store = old_store
        raise
    finally:
        os.environ["EARTHDATA_TOKEN"] = token


def _transient_network_error(error: BaseException) -> bool:
    """Identify retryable transport/HTTP failures, never credential denials."""
    if _http_status_code(error) in TRANSIENT_HTTP_STATUS_CODES:
        return True
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
            TimeoutError,
            ConnectionError,
        )):
            return True
        for nested in (getattr(current, "__cause__", None), getattr(current, "__context__", None)):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _safe_error_message(error: BaseException) -> str:
    """Keep useful transport diagnostics while ensuring credentials never enter logs."""
    message = str(error)
    for secret_name in ("EARTHDATA_TOKEN", "EARTHDATA_PASSWORD"):
        secret = os.environ.get(secret_name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:240]


def _login_with_bounded_retry(earthaccess, *, retry_wave: bool) -> str:
    """Retry transient EDL failures up to three times; fail fast on bad credentials."""
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    username = os.environ.get("EARTHDATA_USERNAME", "").strip()
    password = os.environ.get("EARTHDATA_PASSWORD", "")
    use_password_fallback = bool(retry_wave and token and username and password)
    auth_mode = "username_password_delayed_retry" if use_password_fallback else (
        "bearer_token" if token else "username_password"
    )

    for attempt in range(1, EARTHDATA_LOGIN_MAX_ATTEMPTS + 1):
        try:
            if use_password_fallback:
                print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                    "stage": "delayed_retry_password_authentication",
                    "status": "START",
                    "attempt_number": attempt,
                }), flush=True)
                if not _reauthenticate_with_username_password(earthaccess):
                    raise RuntimeError("username_password_retry_not_configured")
            else:
                earthaccess.login(strategy="environment")
            return auth_mode
        except Exception as exc:
            http_status = _http_status_code(exc)
            transient = _transient_network_error(exc)
            retrying = transient and attempt < EARTHDATA_LOGIN_MAX_ATTEMPTS
            retry_delay_seconds = min(2 ** attempt, 8) if retrying else 0
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "earthdata_login",
                "status": "RETRY" if retrying else "FAIL",
                "attempt_number": attempt,
                "max_attempts": EARTHDATA_LOGIN_MAX_ATTEMPTS,
                "retry_delay_seconds": retry_delay_seconds,
                "auth_mode": auth_mode,
                "error_type": type(exc).__name__,
                "http_status": http_status,
                "transient_network_error": transient,
                "error_message": _safe_error_message(exc),
            }), flush=True)
            if not retrying:
                raise
            time.sleep(retry_delay_seconds)
            # Clear a possibly half-initialized earthaccess module cache before
            # the next bounded login attempt. The configured environment remains
            # unchanged; this is transport recovery, not a credential retry.
            if hasattr(earthaccess, "Auth") and hasattr(earthaccess, "_auth"):
                try:
                    earthaccess._auth = earthaccess.Auth()
                    if hasattr(earthaccess, "_store"):
                        earthaccess._store = None
                except Exception:
                    pass
    raise RuntimeError("Earthdata login exhausted its bounded transient retry budget.")


def _authenticated_requests_session_factory(earthaccess):
    """Return earthaccess's redirect-safe EDL requests-session factory, if available."""
    getter = getattr(earthaccess, "get_requests_https_session", None)
    if not callable(getter):
        getter = getattr(earthaccess, "get_requests_session", None)
    return getter if callable(getter) else None


def _is_trusted_nisar_url(value: Any, expected_name: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and (host == "nisar.asf.earthdatacloud.nasa.gov" or host.endswith(".asf.earthdatacloud.nasa.gov"))
        and Path(parsed.path).name == f"{expected_name}.h5"
    )


def _parse_content_range(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", value.strip(), re.IGNORECASE)
    if not match:
        return None
    start, end, total = (int(item) for item in match.groups())
    if start < 0 or end < start or total <= end:
        return None
    return start, end, total


def _probe_http_range_support(earthaccess, url: str, expected_name: str) -> dict[str, Any] | None:
    """Probe one byte only. Return None when the ASF endpoint does not support Range."""
    if not _is_trusted_nisar_url(url, expected_name):
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "http_range_probe",
            "status": "SKIP",
            "reason": "no trusted exact-granule ASF URL in the selected manifest",
        }), flush=True)
        return None
    factory = _authenticated_requests_session_factory(earthaccess)
    if factory is None:
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "http_range_probe",
            "status": "SKIP",
            "reason": "earthaccess authenticated requests session is unavailable",
        }), flush=True)
        return None

    response = None
    session = None
    started = time.monotonic()
    try:
        session = factory()
        response = session.get(
            url,
            headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"},
            stream=True,
            allow_redirects=True,
            timeout=(20, 60),
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if status in {401, 403}:
            raise RuntimeError(f"Earthdata rejected the exact NISAR range probe with HTTP status: {status}")
        if status in {408, 425, 429} or status >= 500:
            raise RuntimeError(f"Transient ASF range-probe response: HTTP {status}.")
        if status != 206:
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "http_range_probe",
                "status": "FALLBACK",
                "http_status": status,
                "reason": "server did not return HTTP 206 Partial Content",
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }), flush=True)
            return None
        parsed = _parse_content_range(getattr(response, "headers", {}).get("Content-Range"))
        if parsed is None or parsed[0] != 0 or parsed[1] != 0:
            raise RuntimeError("The ASF range probe returned a malformed Content-Range header.")
        content_length = getattr(response, "headers", {}).get("Content-Length")
        if content_length not in (None, "", "1"):
            raise RuntimeError("The ASF range probe returned an unexpected Content-Length.")
        metadata = {
            "size_bytes": parsed[2],
            "etag": getattr(response, "headers", {}).get("ETag"),
            "last_modified": getattr(response, "headers", {}).get("Last-Modified"),
            "session_factory": factory,
        }
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "http_range_probe",
            "status": "PASS",
            "http_status": 206,
            "size_bytes": metadata["size_bytes"],
            "etag_present": bool(metadata["etag"]),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }), flush=True)
        return metadata
    except RuntimeError:
        raise
    except requests.exceptions.RequestException as exc:
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "http_range_probe",
            "status": "FALLBACK",
            "error_type": type(exc).__name__,
            "error_message": _safe_error_message(exc),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }), flush=True)
        return None
    finally:
        if response is not None and callable(getattr(response, "close", None)):
            response.close()
        if session is not None and callable(getattr(session, "close", None)):
            session.close()


def _download_one_http_range(
    *,
    session_factory,
    url: str,
    destination: Path,
    start: int,
    end: int,
    total_size: int,
    etag: str | None,
    granule_name: str,
) -> int:
    expected_bytes = end - start + 1
    for attempt in range(1, RANGE_MAX_ATTEMPTS + 1):
        response = None
        session = None
        try:
            headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
            if etag:
                headers["If-Range"] = etag
            session = session_factory()
            response = session.get(
                url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(20, 180),
            )
            status = int(getattr(response, "status_code", 0) or 0)
            if status in {401, 403}:
                raise RuntimeError(f"Earthdata rejected the NISAR range for {granule_name} with HTTP status: {status}")
            if status in {408, 425, 429} or status >= 500:
                raise requests.exceptions.HTTPError(
                    f"Transient HTTP {status} while downloading byte range {start}-{end}",
                    response=response,
                )
            if status != 206:
                raise RuntimeError(
                    f"ASF stopped honoring byte ranges for {granule_name}: expected HTTP 206, received {status}."
                )
            content_range = _parse_content_range(
                getattr(response, "headers", {}).get("Content-Range")
            )
            if content_range != (start, end, total_size):
                raise RuntimeError(
                    f"ASF returned an inconsistent Content-Range for {granule_name} bytes {start}-{end}."
                )
            response_etag = getattr(response, "headers", {}).get("ETag")
            if etag and response_etag and response_etag != etag:
                raise RuntimeError("ASF product ETag changed during ranged download; refusing to combine different object versions.")

            written = 0
            with destination.open("r+b") as stream:
                stream.seek(start)
                for chunk in response.iter_content(chunk_size=DOWNLOAD_STREAM_CHUNK_BYTES):
                    if not chunk:
                        continue
                    stream.write(chunk)
                    written += len(chunk)
            if written != expected_bytes:
                raise requests.exceptions.ChunkedEncodingError(
                    f"Range {start}-{end} yielded {written} bytes; expected {expected_bytes}."
                )
            return written
        except requests.exceptions.RequestException as exc:
            status = _earthdata_http_auth_rejection(exc)
            if status in {401, 403} or attempt >= RANGE_MAX_ATTEMPTS:
                raise RuntimeError(
                    f"HTTP range {start}-{end} for {granule_name} failed after {attempt} attempt(s): "
                    f"{type(exc).__name__}: {_safe_error_message(exc)}"
                ) from None
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "http_range_segment_retry",
                "status": "RETRY",
                "granule_name": granule_name,
                "range_start": start,
                "range_end": end,
                "attempt_number": attempt,
                "max_attempts": RANGE_MAX_ATTEMPTS,
                "error_type": type(exc).__name__,
            }), flush=True)
            time.sleep(min(2 ** attempt, 8))
        finally:
            if response is not None and callable(getattr(response, "close", None)):
                response.close()
            if session is not None and callable(getattr(session, "close", None)):
                session.close()
    raise RuntimeError(f"HTTP range {start}-{end} for {granule_name} exhausted its retry budget.")


def _download_via_http_ranges(
    *,
    earthaccess,
    url: str,
    destination: Path,
    granule_name: str,
    range_metadata: dict[str, Any],
) -> tuple[Path, int]:
    total_size = int(range_metadata["size_bytes"])
    if total_size <= 0:
        raise RuntimeError("The ASF range probe returned an invalid product size.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        stream.truncate(total_size)

    ranges = [
        (start, min(start + RANGE_PART_BYTES - 1, total_size - 1))
        for start in range(0, total_size, RANGE_PART_BYTES)
    ]
    worker_count = min(RANGE_DOWNLOAD_WORKERS, len(ranges))
    started = time.monotonic()
    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "http_range_download",
        "status": "START",
        "granule_name": granule_name,
        "size_bytes": total_size,
        "range_count": len(ranges),
        "parallel_connections": worker_count,
        "range_part_bytes": RANGE_PART_BYTES,
        "max_attempts_per_range": RANGE_MAX_ATTEMPTS,
    }), flush=True)

    downloaded = 0
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="rivershift-range") as executor:
        futures = [
            executor.submit(
                _download_one_http_range,
                session_factory=range_metadata["session_factory"],
                url=url,
                destination=destination,
                start=start,
                end=end,
                total_size=total_size,
                etag=range_metadata.get("etag"),
                granule_name=granule_name,
            )
            for start, end in ranges
        ]
        for future in as_completed(futures):
            downloaded += future.result()

    actual_size = destination.stat().st_size
    if downloaded != total_size or actual_size != total_size:
        raise RuntimeError(
            f"Ranged download size mismatch for {granule_name}: received {downloaded} of {total_size} bytes."
        )
    elapsed = max(time.monotonic() - started, 0.001)
    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "http_range_download",
        "status": "PASS",
        "granule_name": granule_name,
        "downloaded_bytes": downloaded,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_mib_per_second": round(downloaded / (1024 * 1024) / elapsed, 2),
        "retried_ranges": "see http_range_segment_retry events",
    }), flush=True)
    return destination, downloaded


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

    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    retry_wave = os.environ.get("RIVERSHIFT_RETRY_ATTEMPT", "0").strip() == "1"
    auth_mode = "username_password_delayed_retry" if retry_wave and token else (
        "bearer_token" if token else "username_password"
    )
    print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
        "stage": "earthdata_login",
        "status": "START",
        "auth_mode": auth_mode,
        "workflow_attempt_number": 2 if retry_wave else 1,
        "login_attempt_number": 1,
        "delayed_retry_wave": retry_wave,
        "max_transient_attempts": EARTHDATA_LOGIN_MAX_ATTEMPTS,
    }), flush=True)
    try:
        auth_mode = _login_with_bounded_retry(earthaccess, retry_wave=retry_wave)
    except Exception as exc:
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "earthdata_login",
            "status": "FAIL",
            "auth_mode": auth_mode,
            "error_type": type(exc).__name__,
            "http_status": _http_status_code(exc),
            "transient_network_error": _transient_network_error(exc),
            "error_message": _safe_error_message(exc),
        }), flush=True)
        raise RuntimeError(
            "Earthdata login failed after the bounded transient retry; inspect the error type and HTTP status above."
        ) from None
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
        download_started = time.monotonic()
        source_url = product.get("download_url")
        range_metadata = _probe_http_range_support(earthaccess, source_url, expected_name)
        download_method = "earthaccess.download"
        if range_metadata is not None:
            downloaded_path, downloaded_bytes = _download_via_http_ranges(
                earthaccess=earthaccess,
                url=source_url,
                destination=temporary_dir / f"{expected_name}.h5",
                granule_name=expected_name,
                range_metadata=range_metadata,
            )
            download_method = "earthaccess_authenticated_http_range"
        else:
            print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                "stage": "earthaccess_download",
                "status": "START",
                "threads": 1,
                "requested_granule_count": 1,
                "fallback_reason": "authenticated HTTP byte ranges unavailable",
            }), flush=True)
            try:
                downloaded_paths = earthaccess.download(
                    exact_matches,
                    local_path=str(temporary_dir),
                    threads=1,
                    show_progress=False,
                )
            except Exception as download_error:
                denied_status = _earthdata_http_auth_rejection(download_error)
                print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
                    "stage": "earthaccess_download",
                    "status": "FAIL",
                    "error_type": type(download_error).__name__,
                    "http_status": denied_status,
                    "attempt_number": 2 if retry_wave else 1,
                    "delayed_retry_wave": retry_wave,
                    "immediate_retry_performed": False,
                    "error_message": _safe_error_message(download_error),
                }), flush=True)
                if denied_status in {401, 403} and not retry_wave:
                    raise RuntimeError(
                        "Earthdata rejected this product download with HTTP "
                        f"{denied_status}; the product is queued for the single delayed retry wave after all first-attempt batches finish."
                    ) from None
                raise RuntimeError(
                    "The exact NISAR GCOV product download failed on this attempt; no immediate re-download was performed."
                ) from None

            paths = [Path(item).resolve() for item in (downloaded_paths or [])]
            if len(paths) != 1:
                raise RuntimeError(
                    f"earthaccess returned {len(paths)} files for one exact GCOV granule; refusing ambiguous output."
                )
            downloaded_path = paths[0]

        temp_root = temporary_dir.resolve()
        if temp_root not in downloaded_path.resolve().parents or not downloaded_path.is_file():
            raise RuntimeError("The exact download returned a missing or out-of-directory file.")
        if downloaded_path.stem != expected_name:
            raise RuntimeError("The downloaded NISAR filename does not match the exact requested granule.")
        downloaded_bytes = downloaded_path.stat().st_size
        if downloaded_bytes <= 0:
            raise RuntimeError("The downloaded NISAR HDF5 file is empty.")
        if range_metadata is not None and downloaded_bytes != int(range_metadata["size_bytes"]):
            raise RuntimeError(
                f"The HTTP range download is incomplete: {downloaded_bytes} of {range_metadata['size_bytes']} bytes."
            )
        if not is_hdf5_file(downloaded_path):
            raise RuntimeError(
                "The downloaded object does not contain the HDF5 signature; it may be an HTML/login or error response."
            )

        downloaded_path.replace(final_path)
        elapsed = max(time.monotonic() - download_started, 0.001)
        print("RIVERSHIFT_DOWNLOAD_STAGE " + json.dumps({
            "stage": "earthaccess_download",
            "status": "PASS",
            "download_method": download_method,
            "downloaded_bytes": downloaded_bytes,
            "elapsed_seconds": round(elapsed, 3),
            "throughput_mib_per_second": round(downloaded_bytes / (1024 * 1024) / elapsed, 2),
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
        "download_method": download_method,
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
