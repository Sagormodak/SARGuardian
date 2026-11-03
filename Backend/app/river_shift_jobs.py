from __future__ import annotations

import hashlib
import hmac
import json
import logging
import mimetypes
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request as UrlRequest, urlopen
from uuid import UUID, uuid4
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from .auth import get_current_user
from .config import get_settings
from .jobs import JobState
from .persistence import (
    PersistenceConfigurationError,
    PersistenceConflictError,
    PersistenceError,
    get_job_store,
)
from .river_shift import (
    FlightDirection, FrameCoverage, Polarization, RiverShiftCatalogRequest, search_gcov_catalogue,
)
from science_adapter.geometry import validate_wkt
from science_adapter.upload_to_drive import DriveUploadError, download_private_result_to_path

router = APIRouter(prefix="/api/river-shift", tags=["RiverShift"])
logger = logging.getLogger(__name__)
MAX_GITHUB_INPUT_BYTES = 60_000
MAX_CALLBACK_BYTES = 2_000_000
MAX_ARTIFACT_BYTES = 250 * 1024 * 1024
JOB_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")
SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_:-]{0,79}$")
SAFE_STAGE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class CreateRiverShiftJobRequest(BaseModel):
    aoi_wkt: str = Field(min_length=20, max_length=100_000)
    start_date: date
    end_date: date
    event_date: date
    maturity: Literal["BETA", "PROVISIONAL"] = "PROVISIONAL"
    main_band_polarization: Polarization | None = None
    flight_direction: FlightDirection | None = None
    frame_coverage: FrameCoverage = "ALL"
    frequency: Literal["frequencyA", "frequencyB"] = "frequencyA"
    covariance_term: Literal["HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"] = "HHHH"
    threshold_method: Literal["otsu", "manual"] = "otsu"
    threshold_db: float | None = None
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("aoi_wkt")
    @classmethod
    def validate_aoi(cls, value: str) -> str:
        try:
            return validate_wkt(value).wkt
        except ValueError as exc:
            raise ValueError(f"AOI_WKT_INVALID: {exc}") from None

    @model_validator(mode="after")
    def validate_window_and_threshold(self) -> "CreateRiverShiftJobRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        if (self.end_date - self.start_date).days > 366:
            raise ValueError("RiverShift observation window cannot exceed 366 days.")
        if self.end_date > date.today() or self.event_date > date.today():
            raise ValueError("Observation and event dates cannot be in the future.")
        if not self.start_date <= self.event_date <= self.end_date:
            raise ValueError("event_date must fall inside the observation window.")
        if self.threshold_method == "manual":
            if self.threshold_db is None or not -60 <= self.threshold_db <= 0:
                raise ValueError("Manual water threshold must be between -60 and 0 dB.")
        elif self.threshold_db is not None:
            raise ValueError("threshold_db must be omitted when using Otsu.")
        return self


class RiverShiftWorkerCallback(BaseModel):
    job_id: UUID
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["running", "succeeded", "failed"]
    sequence: int = Field(ge=1, le=1000)
    stage: str = Field(min_length=1, max_length=80)
    github_run_id: str = Field(min_length=1, max_length=32)
    github_run_url: str | None = Field(default=None, max_length=2048)
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=500)
    result_summary: dict[str, Any] | None = None
    artifact_manifest: list[dict[str, Any]] | None = None


class RiverShiftArtifactResponse(BaseModel):
    name: str
    path: str
    bytes: int
    sha256: str


class RiverShiftJobResponse(BaseModel):
    id: UUID
    state: JobState
    stage: str
    aoi_wkt: str
    start_date: date
    end_date: date
    event_date: date
    maturity: Literal["BETA", "PROVISIONAL"]
    frequency: Literal["frequencyA", "frequencyB"]
    covariance_term: str
    threshold_method: Literal["otsu", "manual"]
    threshold_db: float | None = None
    github_run_id: str | None = None
    github_run_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] | None = None
    artifact_manifest: list[RiverShiftArtifactResponse] | None = None
    created_at: datetime
    updated_at: datetime


def _owner_uid(user: dict[str, Any]) -> str:
    value = user.get("uid")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=401, detail="Authenticated Firebase identity is unavailable.")
    return value


def _store():
    try:
        return get_job_store()
    except PersistenceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _response(record: dict[str, Any]) -> RiverShiftJobResponse:
    artifacts = record.get("artifact_manifest")
    safe_artifacts = None
    if isinstance(artifacts, list):
        safe_artifacts = []
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            safe_artifacts.append({
                "name": item.get("name", ""),
                "path": item.get("path", ""),
                "bytes": item.get("bytes", 0),
                "sha256": item.get("sha256", ""),
            })
    return RiverShiftJobResponse.model_validate({**record, "artifact_manifest": safe_artifacts})


def request_fingerprint(request_snapshot: dict[str, Any], manifest_snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"request": request_snapshot, "manifest": manifest_snapshot},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _acquisition_date(value: Any, granule_name: Any = None) -> str | None:
    """Normalize CMR ISO and NISAR filename timestamps to one UTC calendar date."""
    candidates: list[str] = []
    if isinstance(value, str) and value.strip():
        candidates.append(value.strip())
    if isinstance(granule_name, str):
        parts = granule_name.removesuffix(".h5").split("_")
        if len(parts) == 18 and parts[0] == "NISAR" and parts[1] == "L2" and parts[3] == "GCOV":
            candidates.append(parts[11])

    for candidate in candidates:
        compact = re.fullmatch(r"(\d{8}T\d{6})(?:\.\d+)?Z?", candidate)
        if compact:
            try:
                return datetime.strptime(compact.group(1), "%Y%m%dT%H%M%S").date().isoformat()
            except ValueError:
                continue
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
                return date.fromisoformat(candidate).isoformat()
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def _discover_manifest(payload: CreateRiverShiftJobRequest) -> tuple[dict[str, Any], list[str]]:
    aoi = validate_wkt(payload.aoi_wkt)
    catalogue = search_gcov_catalogue(RiverShiftCatalogRequest(
        coordinates=[list(point) for point in aoi.coordinates],
        start_date=payload.start_date,
        end_date=payload.end_date,
        maturity=payload.maturity,
        main_band_polarization=payload.main_band_polarization,
        flight_direction=payload.flight_direction,
        frame_coverage=payload.frame_coverage,
        max_results=100,
    ))
    products = [item.model_dump(mode="json") for item in catalogue.products]
    names = sorted({str(item["granule_name"]) for item in products if item.get("granule_name")})
    date_values = {
        observed
        for item in products
        if (observed := _acquisition_date(item.get("start_time_utc"), item.get("granule_name"))) is not None
        and payload.start_date.isoformat() <= observed <= payload.end_date.isoformat()
    }
    dates = sorted(date_values)
    if len(dates) < 4:
        raise HTTPException(
            status_code=422,
            detail="NASA CMR returned fewer than four acquisition dates for this AOI/window. RiverShift processing needs at least four observations before footprint and layer compatibility checks.",
        )
    if not names or len(names) > 100:
        raise HTTPException(status_code=422, detail="The accepted GCOV catalogue selection is empty or exceeds the 100-granule worker limit.")
    manifest = {
        "schema_version": 1,
        "source": "NASA CMR UMM-G / ASF DAAC",
        "endpoint": catalogue.query.get("endpoint"),
        "collection_short_names": catalogue.query.get("collection_short_names"),
        "discovery_filters": {
            "main_band_polarization": payload.main_band_polarization,
            "flight_direction": payload.flight_direction,
            "frame_coverage": payload.frame_coverage,
        },
        "reported_cmr_hits": catalogue.query.get("reported_cmr_hits"),
        "product_count": len(products),
        "unique_dates": dates,
        "products": products,
        "catalogue_only": True,
        "warning": "CMR metadata only. No HDF5 product has been downloaded and AOI coverage, real dataset paths and valid pixels remain subject to worker inspection.",
    }
    return manifest, names


def _dispatch(settings: Any, job_id: UUID, request_snapshot: dict[str, Any], granule_names: list[str], fingerprint: str) -> None:
    if not settings.river_shift_actions_enabled:
        raise RuntimeError("RiverShift GitHub Actions dispatch is disabled on the Dynamic API.")
    endpoint = (
        f"{settings.github_api_url}/repos/{settings.river_shift_github_actions_repository}"
        f"/actions/workflows/{settings.river_shift_github_actions_workflow}/dispatches"
    )
    inputs = {
        "job_id": str(job_id),
        "aoi_wkt": request_snapshot["aoi_wkt"],
        "start_date": request_snapshot["start_date"],
        "end_date": request_snapshot["end_date"],
        "event_date": request_snapshot["event_date"],
        "maturity": request_snapshot["maturity"],
        "main_band_polarization": request_snapshot.get("main_band_polarization") or "",
        "flight_direction": request_snapshot.get("flight_direction") or "",
        "frame_coverage": request_snapshot.get("frame_coverage", "ALL"),
        "frequency": request_snapshot["frequency"],
        "covariance_term": request_snapshot["covariance_term"],
        "threshold_method": request_snapshot["threshold_method"],
        "threshold_db": "" if request_snapshot.get("threshold_db") is None else str(request_snapshot["threshold_db"]),
        "granule_names_json": json.dumps(granule_names, separators=(",", ":")),
        "request_fingerprint": fingerprint,
        "callback_url": settings.river_shift_public_api_url,
    }
    body = json.dumps({"ref": settings.river_shift_github_actions_ref, "inputs": inputs}, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_GITHUB_INPUT_BYTES:
        raise RuntimeError("RiverShift request exceeds the safe GitHub Actions input size; simplify the AOI or acquisition selection.")
    http_request = UrlRequest(endpoint, data=body, method="POST", headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.river_shift_github_actions_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(http_request, timeout=20) as response:
            if response.status != 204:
                raise RuntimeError("GitHub Actions did not accept the RiverShift workflow dispatch.")
    except HTTPError as exc:
        raise RuntimeError(f"GitHub Actions rejected RiverShift dispatch (HTTP {exc.code}).") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Could not reach GitHub Actions to dispatch RiverShift processing.") from None


def _mark_dispatch_failure(store: Any, job_id: UUID, message: str) -> bool:
    """Mark a failed submission terminal without overwriting a worker callback."""
    for expected_state in (JobState.DISPATCHING.value, JobState.QUEUED.value):
        try:
            store.update_river_shift_job(
                job_id,
                {
                    "state": JobState.FAILED.value,
                    "stage": "dispatch_failed",
                    "error_code": "RIVERSHIFT_DISPATCH_FAILED",
                    "error_message": message[:500],
                },
                expected_state=expected_state,
                expected_sequence=0,
            )
            return True
        except PersistenceConflictError:
            # The transition may have committed despite a transport error, or
            # a worker callback may already have advanced the state. Try the
            # other pre-worker state, then leave any later state untouched.
            continue
        except PersistenceError:
            logger.exception("RiverShift dispatch failure could not be persisted for job %s", job_id)
            return False
    logger.warning("RiverShift job %s changed state while dispatch failure was being recorded", job_id)
    return False


def callback_signature_is_valid(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _validate_success_artifacts(artifacts: list[dict[str, Any]] | None) -> None:
    if not isinstance(artifacts, list) or not artifacts:
        raise HTTPException(status_code=409, detail="RiverShift success requires privately retained result artifacts.")
    seen_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise HTTPException(status_code=409, detail="RiverShift artifact manifest is invalid.")
        name, path = item.get("name"), item.get("path")
        digest, size, file_id = item.get("sha256"), item.get("bytes"), item.get("drive_file_id")
        verification = item.get("remote_verification")
        if (
            not isinstance(name, str) or not name or len(name) > 255
            or not isinstance(path, str) or not path or path.startswith("/")
            or ".." in path.split("/") or "\\" in path or len(path) > 500
            or path in seen_paths
            or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_ARTIFACT_BYTES
            or not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id)
            or not isinstance(verification, dict) or verification.get("status") != "PASS"
        ):
            raise HTTPException(status_code=409, detail="RiverShift success contains an incomplete or unverified private artifact receipt.")
        seen_paths.add(path)


@router.post("/jobs", response_model=RiverShiftJobResponse)
def create_river_shift_job(payload: CreateRiverShiftJobRequest, user: dict = Depends(get_current_user)) -> RiverShiftJobResponse:
    settings = get_settings()
    if not settings.river_shift_actions_enabled:
        raise HTTPException(status_code=503, detail="RiverShift processing is not enabled on this API deployment yet.")
    owner_uid = _owner_uid(user)
    store = _store()
    request_snapshot = payload.model_dump(mode="json")
    try:
        existing = store.get_river_shift_job_by_idempotency(owner_uid, payload.idempotency_key)
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not check RiverShift request idempotency.") from None
    if existing:
        return _response(existing)

    try:
        active_jobs = store.list_active_river_shift_jobs(owner_uid)
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not check RiverShift account processing capacity.") from None
    if active_jobs:
        active = active_jobs[0]
        raise HTTPException(
            status_code=409,
            detail=(
                "This account already has an active RiverShift job "
                f"({str(active.get('id', 'unknown'))}). Wait for it to finish before starting another."
            ),
        )

    try:
        manifest, granule_names = _discover_manifest(payload)
    except HTTPException:
        raise
    except Exception:
        logger.exception("RiverShift NASA CMR preflight failed")
        raise HTTPException(status_code=502, detail="NASA CMR discovery failed. No RiverShift processing job was dispatched.") from None

    unique_dates = manifest.get("unique_dates") if isinstance(manifest, dict) else None
    valid_dates = sorted({
        value for value in unique_dates
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    }) if isinstance(unique_dates, list) else []
    if len(valid_dates) < 4:
        raise HTTPException(
            status_code=422,
            detail="RiverShift processing requires at least four distinct catalogue acquisition dates for the requested AOI and window.",
        )
    if not isinstance(granule_names, list) or not granule_names or len(granule_names) > 100:
        raise HTTPException(
            status_code=422,
            detail="The exact GCOV granule selection is empty or exceeds the 100-granule worker limit.",
        )

    fingerprint = request_fingerprint(request_snapshot, manifest)
    job_id = uuid4()
    record = {
        "id": str(job_id),
        "owner_uid": owner_uid,
        "idempotency_key": payload.idempotency_key,
        "state": JobState.QUEUED.value,
        "stage": "queued",
        "aoi_wkt": payload.aoi_wkt,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "event_date": payload.event_date.isoformat(),
        "maturity": payload.maturity,
        "frequency": payload.frequency,
        "covariance_term": payload.covariance_term,
        "threshold_method": payload.threshold_method,
        "threshold_db": payload.threshold_db,
        "request_snapshot": request_snapshot,
        "manifest_snapshot": manifest,
        "request_fingerprint": fingerprint,
        "callback_sequence": 0,
        "artifact_manifest": None,
        "result_summary": None,
    }
    try:
        created = store.create_river_shift_job(record)
    except PersistenceConflictError:
        raise HTTPException(
            status_code=409,
            detail="This account already has an active RiverShift job. Wait for it to finish before starting another.",
        ) from None
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not persist the RiverShift processing request.") from None
    if created.get("id") != str(job_id):
        return _response(created)

    try:
        created = store.update_river_shift_job(
            job_id,
            {"state": JobState.DISPATCHING.value, "stage": "workflow_dispatch"},
            expected_state=JobState.QUEUED.value,
            expected_sequence=0,
        )
        _dispatch(settings, job_id, request_snapshot, granule_names, fingerprint)
    except Exception as exc:
        logger.exception("RiverShift Actions dispatch failed for job %s", job_id)
        _mark_dispatch_failure(store, job_id, str(exc))
        raise HTTPException(status_code=503, detail=f"RiverShift Actions dispatch failed: {str(exc)[:300]}") from None
    return _response(created)


def _github_get_json(settings: Any, url: str) -> dict[str, Any] | None:
    http_request = UrlRequest(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.river_shift_github_actions_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(http_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _find_workflow_run(settings: Any, job_id: UUID) -> dict[str, Any] | None:
    workflow = quote(settings.river_shift_github_actions_workflow, safe="")
    url = (
        f"{settings.github_api_url}/repos/{settings.river_shift_github_actions_repository}"
        f"/actions/workflows/{workflow}/runs?event=workflow_dispatch&per_page=100"
    )
    payload = _github_get_json(settings, url)
    rows = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    expected_title = f"RiverShift {job_id}"
    for row in rows:
        if isinstance(row, dict) and row.get("display_title") == expected_title:
            return row
    return None


def _refresh_workflow_state(store: Any, record: dict[str, Any]) -> dict[str, Any]:
    state = str(record.get("state"))
    if state not in {JobState.DISPATCHING.value, JobState.RUNNING.value}:
        return record
    try:
        settings = get_settings()
        if not settings.river_shift_actions_enabled:
            return record
        run = None
        run_id = record.get("github_run_id")
        if isinstance(run_id, str) and run_id.isdigit():
            run = _github_get_json(
                settings,
                f"{settings.github_api_url}/repos/{settings.river_shift_github_actions_repository}/actions/runs/{run_id}",
            )
        if run is None:
            run = _find_workflow_run(settings, UUID(str(record["id"])))
        updates: dict[str, Any] = {}
        if run is None:
            if state == JobState.DISPATCHING.value:
                created_raw = record.get("created_at")
                try:
                    created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=UTC)
                except (TypeError, ValueError):
                    return record
                timeout = int(getattr(settings, "displacement_dispatch_timeout_seconds", 3600))
                age_seconds = (datetime.now(UTC) - created_at.astimezone(UTC)).total_seconds()
                if age_seconds > timeout:
                    updates = {
                        "state": JobState.FAILED.value,
                        "stage": "workflow_start_timeout",
                        "error_code": "RIVERSHIFT_WORKFLOW_START_TIMEOUT",
                        "error_message": "The RiverShift GitHub Actions workflow did not report a start before the configured timeout.",
                    }
            if not updates:
                return record
        else:
            run_number = run.get("id")
            run_url = run.get("html_url")
            status = run.get("status")
            conclusion = run.get("conclusion")
            if isinstance(run_number, (int, str)) and str(run_number).isdigit():
                updates["github_run_id"] = str(run_number)
            if isinstance(run_url, str) and run_url.startswith("https://github.com/"):
                updates["github_run_url"] = run_url
            if status == "completed":
                updates.update({
                    "state": JobState.FAILED.value,
                    "stage": "terminal_validation_failed",
                    "error_code": "WORKER_CALLBACK_MISSING" if conclusion == "success" else "GITHUB_ACTIONS_WORKER_FAILED",
                    "error_message": (
                        "GitHub Actions completed without a verified RiverShift result callback."
                        if conclusion == "success"
                        else "GitHub Actions reported a terminal RiverShift worker failure."
                    ),
                })
            if not updates:
                return record
        return store.update_river_shift_job(
            UUID(str(record["id"])),
            updates,
            expected_state=state,
            expected_sequence=int(record.get("callback_sequence") or 0),
        )
    except (PersistenceConflictError, PersistenceError):
        return record
    except Exception:
        # A transient GitHub API failure must not hide the last durable job state.
        return record


@router.get("/jobs", response_model=list[RiverShiftJobResponse])
def list_river_shift_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
) -> list[RiverShiftJobResponse]:
    store = _store()
    try:
        records = store.list_river_shift_jobs(_owner_uid(user), limit)
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not list RiverShift processing jobs.") from None
    return [_response(_refresh_workflow_state(store, record)) for record in records]


@router.get("/jobs/{job_id}", response_model=RiverShiftJobResponse)
def get_river_shift_job(job_id: UUID, user: dict = Depends(get_current_user)) -> RiverShiftJobResponse:
    try:
        record = _store().get_river_shift_job(_owner_uid(user), job_id)
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not read the RiverShift processing job.") from None
    if not record:
        raise HTTPException(status_code=404, detail="RiverShift job was not found for this account.")
    record = _refresh_workflow_state(_store(), record)
    return _response(record)


@router.get("/jobs/{job_id}/artifacts/{artifact_index}")
def download_river_shift_artifact(
    job_id: UUID,
    artifact_index: int,
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    if artifact_index < 0 or artifact_index > 200:
        raise HTTPException(status_code=404, detail="RiverShift artifact was not found.")
    try:
        record = _store().get_river_shift_job(_owner_uid(user), job_id)
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not read the RiverShift processing job.") from None
    if not record:
        raise HTTPException(status_code=404, detail="RiverShift job was not found for this account.")
    if record.get("state") != JobState.SUCCEEDED.value:
        raise HTTPException(status_code=409, detail="RiverShift results are available only after verified processing succeeds.")
    artifacts = record.get("artifact_manifest")
    if not isinstance(artifacts, list) or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="RiverShift artifact was not found.")
    artifact = artifacts[artifact_index]
    if not isinstance(artifact, dict) or not isinstance(artifact.get("drive_file_id"), str):
        raise HTTPException(status_code=409, detail="RiverShift artifact has no private storage receipt.")

    filename = str(artifact.get("name") or "river-shift-result.bin")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", filename):
        raise HTTPException(status_code=409, detail="RiverShift artifact filename is invalid.")
    expected_bytes = artifact.get("bytes")
    expected_sha256 = artifact.get("sha256")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or not 0 < expected_bytes <= MAX_ARTIFACT_BYTES
        or not isinstance(expected_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
    ):
        raise HTTPException(status_code=409, detail="RiverShift artifact receipt is incomplete.")

    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        with tempfile.NamedTemporaryFile(
            prefix="sarguardian-river-shift-",
            suffix=Path(filename).suffix or ".bin",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        receipt = download_private_result_to_path(
            artifact["drive_file_id"],
            temporary_path,
            max_bytes=expected_bytes,
        )
    except DriveUploadError:
        try:
            temporary_path.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise HTTPException(status_code=503, detail="Private RiverShift result storage is temporarily unavailable.") from None

    if receipt.get("bytes") != expected_bytes or receipt.get("sha256") != expected_sha256:
        temporary_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="Downloaded RiverShift artifact failed its stored size or SHA-256 check.")

    def stream_verified_file():
        try:
            with temporary_path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    yield chunk
        finally:
            temporary_path.unlink(missing_ok=True)

    return StreamingResponse(
        stream_verified_file(),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(expected_bytes),
            "Cache-Control": "private, no-store",
            "X-Content-SHA256": expected_sha256,
        },
    )


@router.post("/jobs/{job_id}/callback")
async def update_river_shift_job_from_worker(job_id: UUID, request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_CALLBACK_BYTES:
        raise HTTPException(status_code=413, detail="RiverShift worker callback is too large.")
    settings = get_settings()
    if not callback_signature_is_valid(settings.river_shift_callback_secret, body, request.headers.get("X-SARGuardian-Signature")):
        raise HTTPException(status_code=401, detail="Invalid RiverShift worker callback signature.")
    try:
        payload = RiverShiftWorkerCallback.model_validate_json(body)
    except Exception:
        raise HTTPException(status_code=422, detail="RiverShift worker callback payload is invalid.") from None
    if payload.job_id != job_id or not SAFE_STAGE.fullmatch(payload.stage):
        raise HTTPException(status_code=409, detail="RiverShift callback is not bound to the requested job or stage.")
    if payload.github_run_url and not payload.github_run_url.startswith("https://github.com/"):
        raise HTTPException(status_code=422, detail="RiverShift callback run URL is invalid.")
    if payload.error_code and not SAFE_ERROR_CODE.fullmatch(payload.error_code):
        raise HTTPException(status_code=422, detail="RiverShift callback error code is invalid.")

    store = _store()
    try:
        record = store.get_river_shift_job_unscoped(job_id)
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not read RiverShift callback job state.") from None
    if not record:
        raise HTTPException(status_code=404, detail="RiverShift callback job was not found.")
    if not hmac.compare_digest(str(record.get("request_fingerprint") or ""), payload.request_fingerprint):
        raise HTTPException(status_code=409, detail="RiverShift callback request fingerprint does not match the immutable accepted request.")

    current_sequence = int(record.get("callback_sequence") or 0)
    if payload.sequence <= current_sequence:
        return {"status": "accepted", "job_id": str(job_id), "job_status": record["state"], "idempotent": True}
    if payload.sequence != current_sequence + 1:
        raise HTTPException(status_code=409, detail="RiverShift callback sequence is out of order.")
    old_state = str(record.get("state"))
    if payload.state == "running" and old_state not in {JobState.DISPATCHING.value, JobState.RUNNING.value}:
        raise HTTPException(status_code=409, detail="RiverShift job cannot accept a running callback in its current state.")
    if payload.state in {"succeeded", "failed"} and old_state not in {JobState.DISPATCHING.value, JobState.RUNNING.value}:
        raise HTTPException(status_code=409, detail="RiverShift job cannot accept a terminal callback in its current state.")
    if record.get("github_run_id") and record["github_run_id"] != payload.github_run_id:
        raise HTTPException(status_code=409, detail="RiverShift callback belongs to a different GitHub Actions run.")

    updates: dict[str, Any] = {
        "state": payload.state,
        "stage": payload.stage,
        "github_run_id": payload.github_run_id,
        "github_run_url": payload.github_run_url,
        "callback_sequence": payload.sequence,
        "error_code": None,
        "error_message": None,
    }
    if payload.state == "succeeded":
        summary = payload.result_summary
        if (
            not isinstance(summary, dict)
            or summary.get("schema_version") != 1
            or summary.get("processing_status") != "PASS"
            or summary.get("release_status") != "PROVISIONAL"
            or summary.get("independent_validation_status") != "PENDING"
        ):
            raise HTTPException(status_code=409, detail="RiverShift success requires a provisional processing report with independent validation explicitly pending.")
        _validate_success_artifacts(payload.artifact_manifest)
        updates["result_summary"] = summary
        updates["artifact_manifest"] = payload.artifact_manifest
    elif payload.state == "failed":
        if payload.artifact_manifest is not None:
            raise HTTPException(status_code=409, detail="Failed RiverShift callbacks cannot publish a result artifact manifest.")
        updates["error_code"] = payload.error_code or "RIVERSHIFT_WORKER_FAILED"
        updates["error_message"] = (payload.error_message or "RiverShift processing failed.")[:500]
    try:
        updated = store.update_river_shift_job(
            job_id, updates, expected_state=old_state, expected_sequence=current_sequence,
        )
    except PersistenceConflictError:
        raise HTTPException(status_code=409, detail="RiverShift job changed concurrently; refresh its status.") from None
    except PersistenceError:
        raise HTTPException(status_code=503, detail="Could not persist the RiverShift worker callback.") from None
    return {"status": "accepted", "job_id": str(job_id), "job_status": updated["state"], "idempotent": False}
