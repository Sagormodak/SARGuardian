"""Publish checksum-verified results to private Google Drive storage.

The application authorizes downloads through its existing job-owner API.  This
module deliberately never creates a public Drive permission or stores raw NISAR
HDF5 in the derived-only output inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests


DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_TOKEN_URIS = frozenset({
    "https://oauth2.googleapis.com/token",
    "https://accounts.google.com/o/oauth2/token",
})
FOLDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
RESUMABLE_THRESHOLD_BYTES = 5 * 1024 * 1024
RESUMABLE_CHUNK_BYTES = 8 * 1024 * 1024
MAX_RETRY_ATTEMPTS = 5
RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
EXPECTED_DRIVE_ACCOUNT = "sarguardian.org@gmail.com"


def _log_drive_stage(stage: str, status: str, **details: Any) -> None:
    """Emit structured, secret-safe diagnostics for each Drive operation."""
    payload = {"stage": stage, "status": status, **details}
    print("RIVERSHIFT_DRIVE_STAGE " + json.dumps(payload, sort_keys=True, default=str), flush=True)


def _run_drive_stage(stage: str, operation: Any, **details: Any) -> Any:
    started = time.monotonic()
    _log_drive_stage(stage, "START", **details)
    try:
        result = operation()
    except Exception as exc:
        _log_drive_stage(
            stage,
            "FAIL",
            elapsed_seconds=round(time.monotonic() - started, 3),
            error_type=type(exc).__name__,
            error=str(exc),
            **details,
        )
        raise
    _log_drive_stage(
        stage,
        "PASS",
        elapsed_seconds=round(time.monotonic() - started, 3),
        **details,
    )
    return result


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 30.0)
        except (TypeError, ValueError, OverflowError):
            pass
    return min(0.5 * (2 ** max(0, attempt - 1)), 8.0)


class DriveUploadError(RuntimeError):
    """A safe, user-facing result-publication failure."""


@dataclass(frozen=True)
class DriveConfig:
    client_id: str
    client_secret: str
    token_uri: str
    refresh_token: str
    parent_folder_id: str


def _md5_file(path: Path) -> str:
    """Calculate Drive's integrity checksum without loading large rasters into memory."""
    digest = hashlib.md5()  # nosec: Google Drive exposes MD5 as its remote integrity field.
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_oauth_client(raw_client_json: str) -> tuple[str, str, str, str]:
    """Match the working uploader: installed, web, or root-level OAuth JSON."""
    try:
        document = json.loads(raw_client_json)
    except json.JSONDecodeError:
        raise DriveUploadError("Google Drive OAuth client JSON is invalid.") from None
    if not isinstance(document, dict):
        raise DriveUploadError("Google Drive OAuth client JSON is invalid.")
    client = document.get("installed") or document.get("web") or document
    if not isinstance(client, dict):
        raise DriveUploadError("Google Drive OAuth client JSON is invalid.")
    client_id = client.get("client_id")
    client_secret = client.get("client_secret")
    token_uri = client.get("token_uri") or "https://oauth2.googleapis.com/token"
    if not isinstance(client_id, str) or not client_id.strip():
        raise DriveUploadError("Google Drive OAuth client ID is missing.")
    if not isinstance(client_secret, str) or not client_secret.strip():
        raise DriveUploadError("Google Drive OAuth client secret is missing.")
    if not isinstance(token_uri, str) or token_uri not in GOOGLE_TOKEN_URIS:
        raise DriveUploadError("Google Drive OAuth client uses an unsupported token endpoint.")
    credential_format = "installed" if isinstance(document.get("installed"), dict) else (
        "web" if isinstance(document.get("web"), dict) else "root"
    )
    return client_id, client_secret, token_uri, credential_format


def _parse_refresh_token(raw_secret: str) -> tuple[str, str]:
    """Match the working uploader: bare refresh token or token.json input."""
    try:
        parsed = json.loads(raw_secret)
    except json.JSONDecodeError:
        token = raw_secret
        token_format = "bare"
    else:
        if isinstance(parsed, dict):
            token = parsed.get("refresh_token")
            token_format = "token_json"
        elif isinstance(parsed, str):
            token = parsed
            token_format = "json_string"
        else:
            token = None
            token_format = "unsupported"
    if not isinstance(token, str) or not token.strip():
        raise DriveUploadError("Google Drive refresh token is missing or has an unsupported format.")
    return token.strip(), token_format


def load_drive_config(environ: dict[str, str] | None = None) -> DriveConfig:
    values = environ if environ is not None else os.environ
    raw_client = values.get("GOOGLE_DRIVE_OAUTH_CLIENT_JSON", "").strip()
    raw_refresh_token = values.get("GOOGLE_DRIVE_REFRESH_TOKEN", "").strip()
    # Match the established uploader's canonical variable first. The workflow
    # continues to provide the alternate name as a backwards-compatible alias.
    parent_folder_id = (
        values.get("GOOGLE_DRIVE_PARENT_FOLDER_ID", "").strip()
        or values.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    )
    if not raw_client or not raw_refresh_token or not parent_folder_id:
        raise DriveUploadError("Google Drive result storage is not fully configured; check GOOGLE_DRIVE_OAUTH_CLIENT_JSON, GOOGLE_DRIVE_REFRESH_TOKEN and GOOGLE_DRIVE_PARENT_FOLDER_ID or GOOGLE_DRIVE_FOLDER_ID.")
    if not FOLDER_ID_PATTERN.fullmatch(parent_folder_id):
        raise DriveUploadError("Configured Google Drive folder identifier is invalid.")
    client_id, client_secret, token_uri, _client_format = _parse_oauth_client(raw_client)
    refresh_token, _token_format = _parse_refresh_token(raw_refresh_token)
    return DriveConfig(client_id, client_secret, token_uri, refresh_token, parent_folder_id)


class DriveClient:
    def __init__(self, config: DriveConfig, session: requests.Session | Any | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.access_token = self._refresh_access_token()

    def _refresh_access_token(self) -> str:
        payload: Any = None
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            _log_drive_stage("oauth_token_refresh_attempt", "START", attempt=attempt, max_attempts=MAX_RETRY_ATTEMPTS)
            try:
                response = self.session.post(
                    self.config.token_uri,
                    data={
                        "client_id": self.config.client_id,
                        "client_secret": self.config.client_secret,
                        "refresh_token": self.config.refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                _log_drive_stage("oauth_token_refresh_attempt", "PASS", attempt=attempt)
                break
            except requests.HTTPError as exc:
                failed_response = getattr(exc, "response", None)
                status = getattr(failed_response, "status_code", None)
                oauth_error = None
                if failed_response is not None:
                    try:
                        error_payload = failed_response.json()
                    except (ValueError, AttributeError):
                        error_payload = {}
                    if isinstance(error_payload, dict):
                        candidate = error_payload.get("error")
                        if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", candidate):
                            oauth_error = candidate
                if status in RETRYABLE_HTTP_STATUSES and attempt < MAX_RETRY_ATTEMPTS:
                    _log_drive_stage("oauth_token_refresh_attempt", "RETRY", attempt=attempt, http_status=status)
                    retry_after = getattr(failed_response, "headers", {}).get("Retry-After")
                    time.sleep(_retry_delay(attempt, retry_after))
                    continue
                detail = f"HTTP {status}" if status else "HTTP status unavailable"
                if oauth_error:
                    detail += f"; oauth_error={oauth_error}"
                _log_drive_stage("oauth_token_refresh_attempt", "FAIL", attempt=attempt, diagnostic=detail)
                raise DriveUploadError(f"Google Drive OAuth token refresh failed ({detail}).") from None
            except ValueError:
                _log_drive_stage("oauth_token_refresh_attempt", "FAIL", attempt=attempt, diagnostic="invalid_json")
                raise DriveUploadError("Google Drive OAuth token endpoint returned invalid JSON.") from None
            except requests.RequestException as exc:
                if attempt < MAX_RETRY_ATTEMPTS:
                    _log_drive_stage("oauth_token_refresh_attempt", "RETRY", attempt=attempt, error_type=type(exc).__name__)
                    time.sleep(_retry_delay(attempt))
                    continue
                _log_drive_stage("oauth_token_refresh_attempt", "FAIL", attempt=attempt, diagnostic="network_or_timeout")
                raise DriveUploadError("Google Drive OAuth token refresh failed (network or timeout).") from None
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise DriveUploadError("Google Drive did not return an access token.")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def verify_authenticated_account(self) -> None:
        payload = self._json(
            "GET",
            f"{DRIVE_API}/about",
            params={"fields": "user(emailAddress)"},
        )
        user = payload.get("user")
        email = user.get("emailAddress") if isinstance(user, dict) else None
        if not isinstance(email, str) or email.lower() != EXPECTED_DRIVE_ACCOUNT:
            raise DriveUploadError("Google Drive authenticated account does not match the configured SARGuardian storage account.")

    def verify_parent_folder(self, folder_id: str) -> None:
        payload = self._json(
            "GET",
            f"{DRIVE_API}/files/{quote(folder_id, safe='')}",
            params={"fields": "id,mimeType"},
        )
        if payload.get("id") != folder_id or payload.get("mimeType") != FOLDER_MIME_TYPE:
            raise DriveUploadError("Configured Google Drive parent identifier is not an accessible folder.")

    def _json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        # Shared Drive-compatible flags are harmless for My Drive and required
        # when the configured parent folder belongs to a Shared Drive.
        params = dict(kwargs.pop("params", {}) or {})
        normalized_url = url.split("?", 1)[0]
        if normalized_url.startswith(DRIVE_API + "/files"):
            params.setdefault("supportsAllDrives", "true")
            if method.upper() == "GET" and normalized_url == DRIVE_API + "/files":
                params.setdefault("includeItemsFromAllDrives", "true")
                params.setdefault("spaces", "drive")
        if params:
            kwargs["params"] = params
        try:
            response = self.session.request(method, url, headers=self._headers(), timeout=60, **kwargs)
            response.raise_for_status()
            payload = response.json() if response.content else {}
        except requests.HTTPError as exc:
            failed_response = getattr(exc, "response", None)
            status = getattr(failed_response, "status_code", None)
            reason = None
            if failed_response is not None:
                try:
                    error_payload = failed_response.json()
                except (ValueError, AttributeError):
                    error_payload = {}
                if isinstance(error_payload, dict):
                    error = error_payload.get("error")
                    rows = error.get("errors") if isinstance(error, dict) else None
                    if isinstance(rows, list):
                        for row in rows:
                            candidate = row.get("reason") if isinstance(row, dict) else None
                            if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", candidate):
                                reason = candidate
                                break
            details = []
            if status:
                details.append(f"HTTP {status}")
            if reason:
                details.append(f"reason={reason}")
            detail = f" ({'; '.join(details)})" if details else ""
            raise DriveUploadError(f"Google Drive result storage request failed{detail}.") from exc
        except (requests.RequestException, ValueError) as exc:
            raise DriveUploadError("Google Drive result storage request failed (network or invalid response).") from exc
        if not isinstance(payload, dict):
            raise DriveUploadError("Google Drive returned an invalid result-storage response.")
        return payload

    @staticmethod
    def _query_text(value: str) -> str:
        return value.replace("'", "\\'")

    def _find_named_file(self, name: str, parent_id: str, mime_type: str | None = None) -> str | None:
        clauses = ["trashed = false", f"'{self._query_text(parent_id)}' in parents", f"name = '{self._query_text(name)}'"]
        if mime_type:
            clauses.append(f"mimeType = '{self._query_text(mime_type)}'")
        payload = self._json(
            "GET",
            f"{DRIVE_API}/files",
            params={"q": " and ".join(clauses), "fields": "files(id)", "pageSize": 2},
        )
        files = payload.get("files")
        if not isinstance(files, list):
            raise DriveUploadError("Google Drive returned an invalid file-search response.")
        identifiers = [item.get("id") for item in files if isinstance(item, dict) and isinstance(item.get("id"), str)]
        if len(identifiers) > 1:
            raise DriveUploadError("Google Drive contains ambiguous prior result files for this job.")
        return identifiers[0] if identifiers else None

    def find_or_create_folder(self, name: str, parent_id: str) -> str:
        existing = self._find_named_file(name, parent_id, FOLDER_MIME_TYPE)
        if existing:
            return existing
        payload = self._json(
            "POST",
            f"{DRIVE_API}/files",
            json={"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]},
            params={"fields": "id"},
        )
        identifier = payload.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise DriveUploadError("Google Drive did not create a result folder.")
        return identifier

    def require_private_folder(self, folder_id: str) -> None:
        permissions = self._json("GET", f"{DRIVE_API}/files/{quote(folder_id, safe='')}/permissions",
                                 params={"fields": "permissions(type,role,allowFileDiscovery)"}).get("permissions")
        if not isinstance(permissions, list):
            raise DriveUploadError("Google Drive returned invalid folder permissions.")
        shared_types = {"anyone", "domain", "group"}
        if any(isinstance(item, dict) and item.get("type") in shared_types for item in permissions):
            raise DriveUploadError("Configured Google Drive result folder is shared beyond its owner; private result retention is blocked.")

    def upload_file(self, path: Path, parent_id: str) -> dict[str, Any]:
        expected_bytes = path.stat().st_size
        if expected_bytes <= 0:
            raise DriveUploadError("Cannot publish an empty RiverShift result artifact.")
        expected_md5 = _md5_file(path)
        existing = self._find_named_file(path.name, parent_id)

        # Scientific outputs are immutable within a job folder. A worker rerun
        # may reuse byte-identical artifacts, but it must never silently replace
        # a different raster/report under the same result path. The root manifest
        # is the only mutable file because it is refreshed with remote receipts.
        if existing and path.name != "result-manifest.json":
            remote = self._json(
                "GET",
                f"{DRIVE_API}/files/{quote(existing, safe='')}",
                params={"fields": "id,name,size,md5Checksum,mimeType"},
            )
            if (remote.get("id") == existing and remote.get("name") == path.name
                    and str(remote.get("size")) == str(expected_bytes)
                    and remote.get("md5Checksum") == expected_md5):
                return {
                    "drive_file_id": existing,
                    "name": path.name,
                    "bytes": expected_bytes,
                    "md5": expected_md5,
                    "remote_md5": remote["md5Checksum"],
                    "status": "PASS",
                    "reused": True,
                }
            raise DriveUploadError("A prior RiverShift artifact has different bytes; immutable overwrite is blocked.")

        method = "PATCH" if existing else "POST"
        url = f"{DRIVE_UPLOAD_API}/files/{quote(existing, safe='')}" if existing else f"{DRIVE_UPLOAD_API}/files"
        metadata: dict[str, Any] = {"name": path.name}
        if not existing:
            metadata["parents"] = [parent_id]
        if expected_bytes > RESUMABLE_THRESHOLD_BYTES:
            payload = self._upload_resumable(path, metadata, method, url)
        else:
            payload = self._upload_multipart(path, metadata, method, url)
        identifier = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise DriveUploadError("Google Drive did not confirm a result-file upload.")
        # A returned upload id is not retention evidence. Read authoritative
        # metadata and compare byte count plus MD5 before allowing cleanup.
        remote = self._json("GET", f"{DRIVE_API}/files/{quote(identifier, safe='')}",
                            params={"fields": "id,name,size,md5Checksum,mimeType"})
        if (remote.get("id") != identifier or remote.get("name") != path.name
                or str(remote.get("size")) != str(expected_bytes)
                or remote.get("md5Checksum") != expected_md5):
            raise DriveUploadError("Google Drive did not verify the uploaded result bytes.")
        return {"drive_file_id": identifier, "name": path.name, "bytes": expected_bytes,
                "md5": expected_md5, "remote_md5": remote["md5Checksum"], "status": "PASS",
                "reused": False}

    def _upload_multipart(self, path: Path, metadata: dict[str, Any], method: str, url: str) -> dict[str, Any]:
        try:
            with path.open("rb") as stream:
                response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id,name,size,md5Checksum,mimeType"},
                    files={
                        "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                        "file": (path.name, stream, "application/octet-stream"),
                    },
                    timeout=300,
                )
                response.raise_for_status()
                payload = response.json()
        except (OSError, requests.RequestException, ValueError) as exc:
            raise DriveUploadError("Could not upload a validated result file to Google Drive.") from exc
        if not isinstance(payload, dict):
            raise DriveUploadError("Google Drive did not return a valid upload response.")
        return payload

    def _query_resumable_status(self, upload_url: str, total: int) -> dict[str, Any]:
        """Resolve ambiguous chunk failures using Google's acknowledged byte offset."""
        headers = {"Content-Length": "0", "Content-Range": f"bytes */{total}"}
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            response = None
            try:
                response = self.session.put(upload_url, data=b"", headers=self._headers() | headers, timeout=60)
            except requests.RequestException as exc:
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise DriveUploadError("Google Drive resumable status check failed after network retries.") from exc
                time.sleep(_retry_delay(attempt))
                continue

            status = response.status_code
            if status in {200, 201}:
                try:
                    payload = response.json()
                except (ValueError, AttributeError) as exc:
                    raise DriveUploadError("Google Drive resumable status returned invalid final metadata.") from exc
                finally:
                    response.close()
                if not isinstance(payload, dict):
                    raise DriveUploadError("Google Drive resumable status returned invalid final metadata.")
                return {"complete": True, "offset": total, "payload": payload}

            if status == 308:
                value = response.headers.get("Range", "")
                response.close()
                if not value:
                    return {"complete": False, "offset": 0}
                match = re.fullmatch(r"bytes=0-(\d+)", value.strip())
                if not match:
                    raise DriveUploadError("Google Drive resumable status returned an invalid acknowledged byte range.")
                offset = int(match.group(1)) + 1
                if not 0 <= offset <= total:
                    raise DriveUploadError("Google Drive resumable status returned an out-of-range byte offset.")
                return {"complete": False, "offset": offset}

            retry_after = response.headers.get("Retry-After")
            response.close()
            if status in RETRYABLE_HTTP_STATUSES and attempt < MAX_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(attempt, retry_after))
                continue
            if status in {404, 410}:
                raise DriveUploadError("Google Drive resumable upload session expired.")
            raise DriveUploadError(f"Google Drive resumable status check failed (HTTP {status}).")
        raise DriveUploadError("Google Drive resumable status retries were exhausted.")

    def _upload_resumable(self, path: Path, metadata: dict[str, Any], method: str, url: str) -> dict[str, Any]:
        """Stream chunks and resume only from offsets confirmed by Google Drive."""
        total = path.stat().st_size
        if total <= 0:
            raise DriveUploadError("Cannot publish an empty RiverShift artifact.")
        try:
            response = self.session.request(
                method,
                url,
                headers=self._headers() | {
                    "X-Upload-Content-Type": "application/octet-stream",
                    "X-Upload-Content-Length": str(total),
                },
                params={"uploadType": "resumable", "supportsAllDrives": "true", "fields": "id,name,size,md5Checksum,mimeType"},
                json=metadata,
                timeout=60,
            )
            response.raise_for_status()
            upload_url = response.headers.get("Location")
        except (OSError, requests.RequestException, ValueError) as exc:
            raise DriveUploadError("Could not create a Google Drive resumable upload session.") from exc
        finally:
            if "response" in locals():
                response.close()

        parsed = urlsplit(upload_url or "")
        if parsed.scheme != "https" or parsed.hostname not in {"www.googleapis.com", "upload.googleapis.com"}:
            raise DriveUploadError("Google Drive returned an untrusted resumable upload URL.")

        offset = 0
        payload: dict[str, Any] | None = None
        with path.open("rb") as stream:
            while offset < total and payload is None:
                chunk_start = offset
                stream.seek(chunk_start)
                chunk = stream.read(min(RESUMABLE_CHUNK_BYTES, total - chunk_start))
                if not chunk:
                    raise DriveUploadError("Local RiverShift artifact changed during resumable upload.")
                chunk_end = chunk_start + len(chunk)
                chunk_headers = self._headers() | {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {chunk_start}-{chunk_end - 1}/{total}",
                }

                attempt = 1
                while True:
                    response = None
                    try:
                        response = self.session.put(
                            upload_url,
                            headers=chunk_headers,
                            data=chunk,
                            timeout=300,
                        )
                    except requests.RequestException:
                        if attempt >= MAX_RETRY_ATTEMPTS:
                            raise DriveUploadError("Google Drive artifact chunk upload failed after network retries.") from None
                        state = self._query_resumable_status(upload_url, total)
                        if state["complete"]:
                            payload = state["payload"]
                            offset = total
                            break
                        server_offset = state["offset"]
                        if server_offset < chunk_start:
                            raise DriveUploadError("Google Drive resumable upload offset moved backwards.")
                        if server_offset > chunk_end:
                            raise DriveUploadError("Google Drive acknowledged bytes beyond the submitted chunk.")
                        if server_offset > chunk_start:
                            offset = server_offset
                            break
                        time.sleep(_retry_delay(attempt))
                        attempt += 1
                        continue

                    status = response.status_code
                    if status in {200, 201}:
                        try:
                            candidate = response.json()
                        except (ValueError, AttributeError) as exc:
                            raise DriveUploadError("Google Drive returned invalid final upload metadata.") from exc
                        finally:
                            response.close()
                        if not isinstance(candidate, dict):
                            raise DriveUploadError("Google Drive returned invalid final upload metadata.")
                        payload = candidate
                        offset = total
                        break

                    if status == 308:
                        value = response.headers.get("Range", "")
                        response.close()
                        if not value:
                            server_offset = 0
                        else:
                            match = re.fullmatch(r"bytes=0-(\d+)", value.strip())
                            if not match:
                                raise DriveUploadError("Google Drive returned an invalid acknowledged byte range.")
                            server_offset = int(match.group(1)) + 1
                        if server_offset < chunk_start or server_offset > chunk_end:
                            raise DriveUploadError("Google Drive acknowledged an invalid resumable upload offset.")
                        if server_offset > chunk_start:
                            offset = server_offset
                            break
                        if attempt >= MAX_RETRY_ATTEMPTS:
                            raise DriveUploadError("Google Drive resumable upload made no progress.")
                        time.sleep(_retry_delay(attempt))
                        attempt += 1
                        continue

                    retry_after = response.headers.get("Retry-After")
                    response.close()
                    if status in RETRYABLE_HTTP_STATUSES:
                        if attempt >= MAX_RETRY_ATTEMPTS:
                            raise DriveUploadError(f"Google Drive chunk upload failed after retries (HTTP {status}).")
                        state = self._query_resumable_status(upload_url, total)
                        if state["complete"]:
                            payload = state["payload"]
                            offset = total
                            break
                        server_offset = state["offset"]
                        if server_offset < chunk_start or server_offset > chunk_end:
                            raise DriveUploadError("Google Drive resumable upload returned an invalid acknowledged offset.")
                        if server_offset > chunk_start:
                            offset = server_offset
                            break
                        time.sleep(_retry_delay(attempt, retry_after))
                        attempt += 1
                        continue

                    if status in {404, 410}:
                        raise DriveUploadError("Google Drive resumable upload session expired.")
                    raise DriveUploadError(f"Google Drive chunk upload failed (HTTP {status}).")

        if payload is None:
            state = self._query_resumable_status(upload_url, total)
            if not state["complete"]:
                raise DriveUploadError("Google Drive acknowledged all chunks but did not confirm final artifact metadata.")
            payload = state["payload"]
        return payload

    def download_file_to_path(self, file_id: str, destination: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
        """Stream a private Drive object to disk while calculating its SHA-256."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
            raise DriveUploadError("Result storage file identifier is invalid.")
        destination = Path(destination)
        response = None
        digest = hashlib.sha256()
        byte_count = 0
        try:
            response = self.session.get(
                f"{DRIVE_API}/files/{quote(file_id, safe='')}",
                headers=self._headers(),
                params={"alt": "media"},
                stream=True,
                timeout=300,
            )
            response.raise_for_status()
            with destination.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    byte_count += len(chunk)
                    if max_bytes is not None and byte_count > max_bytes:
                        raise DriveUploadError("Private result artifact exceeded its verified size limit.")
                    digest.update(chunk)
                    stream.write(chunk)
        except DriveUploadError:
            destination.unlink(missing_ok=True)
            raise
        except (OSError, requests.RequestException) as exc:
            destination.unlink(missing_ok=True)
            raise DriveUploadError("Could not retrieve the private result artifact.") from exc
        finally:
            if response is not None:
                response.close()
        return {"bytes": byte_count, "sha256": digest.hexdigest()}

    def download_file(self, file_id: str) -> tuple[dict[str, Any], bytes]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
            raise DriveUploadError("Result storage file identifier is invalid.")
        try:
            response = self.session.get(f"{DRIVE_API}/files/{quote(file_id, safe='')}", headers=self._headers(),
                                        params={"alt": "media"}, timeout=300)
            response.raise_for_status()
            data = response.content
        except requests.RequestException as exc:
            raise DriveUploadError("Could not retrieve the private result artifact.") from exc
        return {"bytes": len(data), "md5": hashlib.md5(data).hexdigest()}, data  # nosec: Drive integrity field


def _validated_result_files(work_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    manifest_path = work_dir / "result-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DriveUploadError("Validated result manifest is unavailable for Google Drive upload.") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "succeeded":
        raise DriveUploadError("Result manifest does not prove a successful scientific run.")
    outputs = manifest.get("validated_outputs")
    if not isinstance(outputs, list) or not outputs:
        raise DriveUploadError("Result manifest has no validated files to upload.")
    root = work_dir.resolve()
    files = [manifest_path]
    for output in outputs:
        if not isinstance(output, dict):
            raise DriveUploadError("Result manifest contains an invalid validated-file entry.")
        relative = output.get("path")
        digest = output.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise DriveUploadError("Result manifest contains an invalid validated-file entry.")
        candidate = (root / relative).resolve()
        if root not in candidate.parents or not candidate.is_file() or _sha256_file(candidate) != digest:
            raise DriveUploadError("A validated result file is missing or failed its checksum before Google Drive upload.")
        files.append(candidate)
    return manifest, files


def upload_validated_results(work_dir: Path, *, config: DriveConfig | None = None, session: Any | None = None) -> dict[str, Any]:
    manifest, files = _run_drive_stage(
        "result_manifest_validation",
        lambda: _validated_result_files(work_dir),
    )
    job_id = manifest.get("job_id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
        raise DriveUploadError("Result manifest has an invalid job identifier.")
    drive_config = _run_drive_stage(
        "credential_configuration",
        lambda: config or load_drive_config(),
    )
    client = _run_drive_stage(
        "oauth_token_refresh",
        lambda: DriveClient(drive_config, session=session),
    )
    _run_drive_stage("authenticated_account_verification", client.verify_authenticated_account)
    _run_drive_stage(
        "parent_folder_access_verification",
        lambda: client.verify_parent_folder(client.config.parent_folder_id),
    )
    _run_drive_stage(
        "parent_folder_privacy_verification",
        lambda: client.require_private_folder(client.config.parent_folder_id),
    )
    job_folder = _run_drive_stage(
        "job_folder_find_or_create",
        lambda: client.find_or_create_folder(job_id, client.config.parent_folder_id),
    )
    _run_drive_stage(
        "job_folder_privacy_verification",
        lambda: client.require_private_folder(job_folder),
    )
    outputs_folder = _run_drive_stage(
        "outputs_folder_find_or_create",
        lambda: client.find_or_create_folder("outputs", job_folder),
    )
    root = work_dir.resolve()
    receipts = []
    output_by_path = {str(item.get("path")): item for item in manifest.get("validated_outputs", []) if isinstance(item, dict)}
    _log_drive_stage("result_upload_plan", "PASS", file_count=len(files))
    for index, path in enumerate(files, start=1):
        parent = job_folder if path.name == "result-manifest.json" else outputs_folder
        if path.name != "result-manifest.json":
            relative_parent = path.relative_to(root / "outputs").parent
            for part in relative_parent.parts:
                parent = _run_drive_stage(
                    "output_subfolder_find_or_create",
                    lambda part=part, parent=parent: client.find_or_create_folder(part, parent),
                    folder_level=part,
                )
        relative = str(path.relative_to(root)).replace("\\", "/")
        receipt = _run_drive_stage(
            "result_file_upload_and_remote_checksum",
            lambda path=path, parent=parent: client.upload_file(path, parent),
            file_index=index,
            file_count=len(files),
            file_name=relative,
            file_bytes=path.stat().st_size,
        )
        receipt["path"] = relative
        receipts.append(receipt)
        if relative in output_by_path:
            output_by_path[relative]["drive_file_id"] = receipt["drive_file_id"]
            output_by_path[relative]["remote_verification"] = receipt
    manifest["storage_verification"] = {"status": "PASS", "storage": "google-drive-private",
                                        "job_folder_id": job_folder, "receipts": receipts,
                                        "retained_bytes": sum(item["bytes"] for item in receipts)}
    manifest_path = root / "result-manifest.json"
    _run_drive_stage(
        "local_result_manifest_refresh",
        lambda: manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"),
    )
    manifest_receipt = _run_drive_stage(
        "remote_result_manifest_first_verification",
        lambda: client.upload_file(manifest_path, job_folder),
    )
    manifest["storage_verification"]["manifest_receipt"] = manifest_receipt
    _run_drive_stage(
        "local_result_manifest_final_refresh",
        lambda: manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"),
    )
    _run_drive_stage(
        "remote_result_manifest_final_verification",
        lambda: client.upload_file(manifest_path, job_folder),
    )
    _log_drive_stage(
        "private_result_publication",
        "PASS",
        file_count=len(receipts) + 1,
        retained_bytes=sum(item["bytes"] for item in receipts) + manifest_path.stat().st_size,
    )
    return manifest["storage_verification"]


def download_private_result(file_id: str, *, config: DriveConfig | None = None, session: Any | None = None) -> tuple[dict[str, Any], bytes]:
    """Used only after API job-owner authorization; never exposed to browsers."""
    return DriveClient(config or load_drive_config(), session=session).download_file(file_id)

def download_private_result_to_path(
    file_id: str,
    destination: Path,
    *,
    config: DriveConfig | None = None,
    session: Any | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Download an owner-authorized private result without holding the ZIP in memory."""
    return DriveClient(config or load_drive_config(), session=session).download_file_to_path(
        file_id, destination, max_bytes=max_bytes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        receipt = upload_validated_results(args.work_dir.resolve())
    except DriveUploadError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1
    print("DRIVE_STORAGE_RECEIPT=" + json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
