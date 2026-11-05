"""Authenticated dispatch/status adapter for the separate Known Place Analysis workflow.

The workflow run itself is the source of truth for this analysis; no second copy of raw
science data or extra database table is created here. Request IDs are random UUIDs and
are embedded in the Actions run title so the browser can poll only its own known run.
"""
from __future__ import annotations

from datetime import date
import hashlib
import hmac
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile
import json
import math
import os
import re
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import RuntimeSettings
from science_adapter.geometry import validate_wkt

# Generic two-polygon measurement runs in the scientific backend repository.
KNOWN_PLACE_REPOSITORY = os.getenv("KNOWN_PLACE_REPOSITORY", "moshiour0/SARGuardian-backend").strip()
KNOWN_PLACE_WORKFLOW = "know-place-aoi-dispatcher.yml"
KNOWN_PLACE_REF = os.getenv("KNOWN_PLACE_REF", "main").strip()
KNOWN_PLACE_WORKFLOW_PAGE = (
    f"https://github.com/{KNOWN_PLACE_REPOSITORY}/actions/workflows/{KNOWN_PLACE_WORKFLOW}"
)

# The fixed author-exact paper launcher remains separate from the generic AOI workflow,
# but its entry point lives in the backend repository covered by the server Actions token.
KNOWN_PLACE_PAPER_REPOSITORY = os.getenv("KNOWN_PLACE_PAPER_REPOSITORY", KNOWN_PLACE_REPOSITORY).strip()
KNOWN_PLACE_PAPER_WORKFLOW = "know-place-paper-reproduction-dispatcher.yml"
KNOWN_PLACE_PAPER_REF = os.getenv("KNOWN_PLACE_PAPER_REF", KNOWN_PLACE_REF).strip()
KNOWN_PLACE_PAPER_WORKFLOW_PAGE = (
    f"https://github.com/{KNOWN_PLACE_PAPER_REPOSITORY}/actions/workflows/{KNOWN_PLACE_PAPER_WORKFLOW}"
)
KNOWN_PLACE_MAX_DATE_WINDOW_DAYS = 90


class KnownPlaceRequestError(ValueError):
    """A malformed or scientifically unsupported Known Place request."""


class KnownPlaceWorkflowError(RuntimeError):
    """A safe GitHub Actions dispatch/status error; never includes credentials."""


class KnownPlacePaperReproductionRequest(BaseModel):
    """Fixed Bhote Koshi author-exact run; raw download is always explicit."""
    confirm_raw_downloads: bool = False

    @model_validator(mode="after")
    def require_explicit_author_replay_consent(self) -> "KnownPlacePaperReproductionRequest":
        if self.confirm_raw_downloads is not True:
            raise ValueError("EXPLICIT_AUTHOR_EXACT_RAW_DOWNLOAD_CONSENT_REQUIRED")
        return self


class KnownPlaceAnalysisRequest(BaseModel):
    # aoi_wkt is the measurement polygon; scope_aoi_wkt preserves the outer map AOI.
    aoi_wkt: str = Field(min_length=20, max_length=100_000)
    scope_aoi_wkt: str | None = Field(default=None, max_length=100_000)
    start_date: date
    end_date: date
    hazard_mode: Literal["landslide", "glacier_collapse", "ice_rock_avalanche", "mixed"] = "mixed"
    analysis_mode: Literal["exploratory", "retrospective_validation"] = "exploratory"
    polarization: Literal["HH", "HV", "VV", "VH"] = "HH"
    track: str = "ANY"
    direction: Literal["ANY", "A", "D"] = "ANY"
    coherence_neighbours: Literal["1", "5", "10", "15", "20", "25"] = "1"
    allowed_release_ids: str = Field(default="", max_length=200)
    reference_wkt: str | None = Field(default=None, max_length=100_000)
    candidate_context: dict[str, Any] | None = None
    geometry_height_m: float | None = Field(default=None, ge=-500, le=100_000)
    execute_downloads: bool = False
    confirm_raw_downloads: bool = False

    @field_validator("aoi_wkt")
    @classmethod
    def validate_aoi_wkt(cls, value: str) -> str:
        try:
            return validate_wkt(value).wkt
        except ValueError as exc:
            raise ValueError(f"AOI_WKT_INVALID: {exc}") from None

    @field_validator("scope_aoi_wkt")
    @classmethod
    def validate_scope_aoi_wkt(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_wkt(value).wkt
        except ValueError as exc:
            raise ValueError(f"SCOPE_AOI_WKT_INVALID: {exc}") from None

    @field_validator("reference_wkt")
    @classmethod
    def validate_reference_wkt(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_wkt(value).wkt
        except ValueError as exc:
            raise ValueError(f"REFERENCE_WKT_INVALID: {exc}") from None

    @field_validator("candidate_context")
    @classmethod
    def validate_candidate_context(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if value.get("source") != "FIND_DISPLACEMENTS" or value.get("product_type") != "GOFF":
            raise ValueError("CANDIDATE_CONTEXT_MUST_BE_A_GOFF_FIND_DISPLACEMENTS_RECORD")
        candidate_id = value.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip() or len(candidate_id) > 160:
            raise ValueError("CANDIDATE_CONTEXT_ID_INVALID")
        evidence = value.get("evidence_class")
        if not isinstance(evidence, str) or "GOFF" not in evidence or len(evidence) > 160:
            raise ValueError("CANDIDATE_CONTEXT_EVIDENCE_CLASS_INVALID")
        for field_name in ("metric", "status", "interpretation"):
            field_value = value.get(field_name, "")
            limit = 500 if field_name == "interpretation" else 120
            if not isinstance(field_value, str) or len(field_value) > limit:
                raise ValueError(f"CANDIDATE_CONTEXT_{field_name.upper()}_INVALID")
        for field_name in ("support_pairs", "pixel_count", "geometry_original_vertices", "geometry_suggested_vertices"):
            number = value.get(field_name)
            maximum = 100_000 if field_name == "geometry_original_vertices" else 500 if field_name == "geometry_suggested_vertices" else 10_000_000
            if isinstance(number, bool) or not isinstance(number, int) or number < 0 or number > maximum:
                raise ValueError(f"CANDIDATE_CONTEXT_{field_name.upper()}_INVALID")
        area = value.get("approx_area_m2", 0)
        if isinstance(area, bool) or not isinstance(area, (int, float)) or not math.isfinite(float(area)) or area < 0:
            raise ValueError("CANDIDATE_CONTEXT_AREA_INVALID")
        if not isinstance(value.get("geometry_simplified"), bool):
            raise ValueError("CANDIDATE_CONTEXT_SIMPLIFICATION_FLAG_INVALID")
        if not isinstance(value.get("geometry_edited"), bool):
            raise ValueError("CANDIDATE_CONTEXT_EDIT_FLAG_INVALID")
        product_ids = value.get("product_ids", [])
        if not isinstance(product_ids, list) or len(product_ids) > 30 or any(not isinstance(item, str) or len(item) > 512 for item in product_ids):
            raise ValueError("CANDIDATE_CONTEXT_PRODUCT_IDS_INVALID")
        intervals = value.get("pair_intervals", [])
        if not isinstance(intervals, list) or len(intervals) > 30 or any(not isinstance(item, dict) for item in intervals):
            raise ValueError("CANDIDATE_CONTEXT_PAIR_INTERVALS_INVALID")
        try:
            if len(json.dumps(value, separators=(",", ":"), allow_nan=False)) > 20_000:
                raise ValueError("CANDIDATE_CONTEXT_TOO_LARGE")
        except (TypeError, ValueError) as exc:
            if str(exc) == "CANDIDATE_CONTEXT_TOO_LARGE":
                raise
            raise ValueError("CANDIDATE_CONTEXT_NOT_JSON_SAFE") from None
        return value

    @field_validator("track")
    @classmethod
    def validate_track(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned == "ANY" or re.fullmatch(r"\d{3}", cleaned):
            return cleaned
        raise ValueError("TRACK_MUST_BE_ANY_OR_THREE_DIGITS")

    @field_validator("allowed_release_ids")
    @classmethod
    def validate_release_ids(cls, value: str) -> str:
        cleaned = ",".join(part.strip().upper() for part in value.split(",") if part.strip())
        if cleaned and not re.fullmatch(r"[A-Z0-9_-]+(?:,[A-Z0-9_-]+)*", cleaned):
            raise ValueError("ALLOWED_RELEASE_IDS_INVALID")
        return cleaned

    @field_validator("geometry_height_m")
    @classmethod
    def validate_height(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("GEOMETRY_HEIGHT_MUST_BE_FINITE")
        return value

    @model_validator(mode="after")
    def validate_time_and_download_consent(self) -> "KnownPlaceAnalysisRequest":
        if self.end_date < self.start_date:
            raise ValueError("END_DATE_BEFORE_START_DATE")
        if (self.end_date - self.start_date).days > KNOWN_PLACE_MAX_DATE_WINDOW_DAYS:
            raise ValueError(f"DATE_WINDOW_EXCEEDS_{KNOWN_PLACE_MAX_DATE_WINDOW_DAYS}_DAYS")
        if self.end_date > date.today():
            raise ValueError("END_DATE_CANNOT_BE_IN_THE_FUTURE")
        if self.execute_downloads and not self.confirm_raw_downloads:
            raise ValueError("EXPLICIT_RAW_DOWNLOAD_CONSENT_REQUIRED")
        return self


class KnownPlaceAnalysisSubmission(BaseModel):
    request_id: str
    status: Literal["dispatching", "queued", "in_progress", "completed"] = "dispatching"
    github_run_id: str | None = None
    github_run_url: str
    conclusion: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    execute_downloads: bool | None = None
    notice: str


def _github_request(
    settings: RuntimeSettings,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    token = settings.github_actions_token.strip()
    if not token:
        raise KnownPlaceWorkflowError("Known Place Analysis is not configured on this server.")
    data = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read()
            if not raw:
                return response.status, {}
            parsed = json.loads(raw.decode("utf-8"))
            return response.status, parsed if isinstance(parsed, dict) else {}
    except HTTPError as exc:
        # Do not echo the request body, authentication header, or arbitrary response.
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        message = payload.get("message") if isinstance(payload, dict) else None
        if exc.code == 401:
            raise KnownPlaceWorkflowError("GitHub rejected the server's Actions token. Replace the production GITHUB_ACTIONS_TOKEN with a valid token.") from None
        if exc.code == 403:
            parts = path.strip("/").split("/")
            target_repository = (
                f"{parts[1]}/{parts[2]}"
                if len(parts) >= 3 and parts[0] == "repos"
                else "the configured repository"
            )
            raise KnownPlaceWorkflowError(
                f"GitHub denied workflow dispatch to {target_repository}. "
                "Grant the server token Actions: read and write on that repository."
            ) from None
        if exc.code == 404:
            raise KnownPlaceWorkflowError("The Known Place Analysis workflow was not found on its configured branch.") from None
        detail = f" ({exc.code})"
        if isinstance(message, str) and message and len(message) < 180:
            detail += f": {message}"
        raise KnownPlaceWorkflowError("GitHub Actions rejected the Known Place request" + detail + ".") from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise KnownPlaceWorkflowError("Could not reach GitHub Actions to submit or check the Known Place job.") from None


def dispatch_known_place_analysis(
    settings: RuntimeSettings,
    payload: KnownPlaceAnalysisRequest,
) -> KnownPlaceAnalysisSubmission:
    if not settings.displacement_actions_enabled:
        raise KnownPlaceWorkflowError("Processing is disabled by server configuration.")
    request_id = str(uuid4())
    workflow_path = (
        f"/repos/{KNOWN_PLACE_REPOSITORY}/actions/workflows/{KNOWN_PLACE_WORKFLOW}/dispatches"
    )
    inputs = {
        "request_id": request_id,
        "aoi_wkt": payload.aoi_wkt,
        "scope_aoi_wkt": payload.scope_aoi_wkt or "",
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "hazard_mode": payload.hazard_mode,
        "analysis_mode": payload.analysis_mode,
        "polarization": payload.polarization,
        "track": payload.track,
        "direction": payload.direction,
        "coherence_neighbours": payload.coherence_neighbours,
        "allowed_release_ids": payload.allowed_release_ids,
        "reference_wkt": payload.reference_wkt or "",
        "candidate_context_json": json.dumps(payload.candidate_context, separators=(",", ":"), allow_nan=False) if payload.candidate_context is not None else "",
        "geometry_height_m": "" if payload.geometry_height_m is None else str(payload.geometry_height_m),
        "execute_downloads": payload.execute_downloads,
        # The UI's explicit checkbox is converted to the exact workflow marker here;
        # clients cannot supply or override a raw-download consent string directly.
        "consent_marker": "[run-know-place]" if payload.execute_downloads and payload.confirm_raw_downloads else "",
    }
    status, _ = _github_request(
        settings,
        "POST",
        workflow_path,
        {"ref": KNOWN_PLACE_REF, "inputs": inputs},
    )
    if status != 204:
        raise KnownPlaceWorkflowError("GitHub Actions did not accept the Known Place request.")
    return KnownPlaceAnalysisSubmission(
        request_id=request_id,
        status="dispatching",
        github_run_id=None,
        github_run_url=KNOWN_PLACE_WORKFLOW_PAGE,
        execute_downloads=payload.execute_downloads,
        notice=(
            "Raw GOFF downloads and derived outputs were requested; check the run status for credential preflight and selected product inventory."
            if payload.execute_downloads
            else "Catalog/series-plan dry run only. No raw NISAR products will be downloaded."
        ),
    )


def dispatch_known_place_paper_reproduction(
    settings: RuntimeSettings,
    payload: KnownPlacePaperReproductionRequest,
) -> KnownPlaceAnalysisSubmission:
    """Dispatch the fixed author-exact Bhote Koshi P05023 reproduction workflow."""
    if not settings.displacement_actions_enabled:
        raise KnownPlaceWorkflowError("Processing is disabled by server configuration.")
    if payload.confirm_raw_downloads is not True:
        raise KnownPlaceWorkflowError("Explicit author-exact raw-download consent is required.")
    request_id = str(uuid4())
    workflow_path = (
        f"/repos/{KNOWN_PLACE_PAPER_REPOSITORY}/actions/workflows/{KNOWN_PLACE_PAPER_WORKFLOW}/dispatches"
    )
    inputs = {
        "request_id": request_id,
        "consent_marker": "[run-know-place]",
        "geometry_height_m": "5151",
        "control_draws": "1000",
        "seed": "260826",
    }
    status, _ = _github_request(
        settings,
        "POST",
        workflow_path,
        {"ref": KNOWN_PLACE_PAPER_REF, "inputs": inputs},
    )
    if status != 204:
        raise KnownPlaceWorkflowError("GitHub Actions did not accept the author-exact paper reproduction request.")
    return KnownPlaceAnalysisSubmission(
        request_id=request_id,
        status="dispatching",
        github_run_id=None,
        github_run_url=KNOWN_PLACE_PAPER_WORKFLOW_PAGE,
        execute_downloads=True,
        notice=(
            "Author-exact Bhote Koshi P05023 replay requested. The workflow checks Earthdata and Drive credentials before any raw download; "
            "its final paper-reproduction status remains evidence-gated and may remain PARTIAL."
        ),
    )


def get_known_place_paper_reproduction_status(
    settings: RuntimeSettings,
    request_id: str,
) -> KnownPlaceAnalysisSubmission:
    try:
        normalized_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise KnownPlaceWorkflowError("Invalid Known Place paper-reproduction request ID.") from None
    query = urlencode({"branch": KNOWN_PLACE_PAPER_REF, "event": "workflow_dispatch", "per_page": "30"})
    path = (
        f"/repos/{KNOWN_PLACE_PAPER_REPOSITORY}/actions/workflows/{KNOWN_PLACE_PAPER_WORKFLOW}/runs?{query}"
    )
    _status, response = _github_request(settings, "GET", path)
    runs = response.get("workflow_runs")
    if not isinstance(runs, list):
        raise KnownPlaceWorkflowError("GitHub returned an invalid author-exact paper reproduction status response.")
    expected_title = f"Known Place Paper Reproduction {normalized_id}"
    for run in runs:
        if not isinstance(run, dict):
            continue
        if (
            run.get("display_title") != expected_title
            or run.get("path") != f".github/workflows/{KNOWN_PLACE_PAPER_WORKFLOW}"
            or run.get("head_branch") != KNOWN_PLACE_PAPER_REF
            or run.get("event") != "workflow_dispatch"
        ):
            continue
        raw_status = str(run.get("status") or "")
        state = "completed" if raw_status == "completed" else "in_progress" if raw_status == "in_progress" else "queued"
        return KnownPlaceAnalysisSubmission(
            request_id=normalized_id,
            status=state,
            github_run_id=str(run.get("id")) if run.get("id") is not None else None,
            github_run_url=str(run.get("html_url") or KNOWN_PLACE_PAPER_WORKFLOW_PAGE),
            conclusion=str(run.get("conclusion")) if run.get("conclusion") is not None else None,
            created_at=str(run.get("created_at")) if run.get("created_at") else None,
            updated_at=str(run.get("updated_at")) if run.get("updated_at") else None,
            execute_downloads=True,
            notice="Open the author-exact GitHub run for the P05023 source hashes, parity gates, derived bundle and Drive receipt.",
        )
    return KnownPlaceAnalysisSubmission(
        request_id=normalized_id,
        status="dispatching",
        github_run_id=None,
        github_run_url=KNOWN_PLACE_PAPER_WORKFLOW_PAGE,
        execute_downloads=True,
        notice="GitHub accepted the author-exact request. The workflow run is still being allocated; refresh status shortly.",
    )


def get_known_place_analysis_status(
    settings: RuntimeSettings,
    request_id: str,
) -> KnownPlaceAnalysisSubmission:
    try:
        normalized_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise KnownPlaceWorkflowError("Invalid Known Place request ID.") from None
    query = urlencode({"branch": KNOWN_PLACE_REF, "event": "workflow_dispatch", "per_page": "30"})
    path = (
        f"/repos/{KNOWN_PLACE_REPOSITORY}/actions/workflows/{KNOWN_PLACE_WORKFLOW}/runs?{query}"
    )
    _status, response = _github_request(settings, "GET", path)
    runs = response.get("workflow_runs")
    if not isinstance(runs, list):
        raise KnownPlaceWorkflowError("GitHub returned an invalid Known Place workflow status response.")
    expected_title = f"Known Place Analysis {normalized_id}"
    for run in runs:
        if not isinstance(run, dict):
            continue
        if (
            run.get("display_title") != expected_title
            or run.get("path") != f".github/workflows/{KNOWN_PLACE_WORKFLOW}"
            or run.get("head_branch") != KNOWN_PLACE_REF
            or run.get("event") != "workflow_dispatch"
        ):
            continue
        raw_status = str(run.get("status") or "")
        state = "completed" if raw_status == "completed" else "in_progress" if raw_status == "in_progress" else "queued"
        return KnownPlaceAnalysisSubmission(
            request_id=normalized_id,
            status=state,
            github_run_id=str(run.get("id")) if run.get("id") is not None else None,
            github_run_url=str(run.get("html_url") or KNOWN_PLACE_WORKFLOW_PAGE),
            conclusion=str(run.get("conclusion")) if run.get("conclusion") is not None else None,
            created_at=str(run.get("created_at")) if run.get("created_at") else None,
            updated_at=str(run.get("updated_at")) if run.get("updated_at") else None,
            execute_downloads=None,
            notice="Open the GitHub Actions run for the artifact, scientific gate report, and Drive receipt.",
        )
    return KnownPlaceAnalysisSubmission(
        request_id=normalized_id,
        status="dispatching",
        github_run_id=None,
        github_run_url=KNOWN_PLACE_WORKFLOW_PAGE,
        execute_downloads=None,
        notice="GitHub accepted the request. The workflow run is still being allocated; refresh status shortly.",
    )


# Result-bundle retrieval is deliberately scoped to the generic two-polygon workflow.
# The author-exact paper workflow remains a separate dispatch and result path.
MAX_KNOWN_PLACE_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_KNOWN_PLACE_ARTIFACT_UNCOMPRESSED_BYTES = 24 * 1024 * 1024
MAX_KNOWN_PLACE_ARTIFACT_FILES = 2_000
MAX_KNOWN_PLACE_RESULT_JSON_BYTES = 3 * 1024 * 1024
MAX_KNOWN_PLACE_HTML_BYTES = 1_500_000


def _normalize_known_place_request_id(request_id: str) -> str:
    try:
        return str(UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise KnownPlaceWorkflowError("Invalid Known Place request ID.") from None


def _find_generic_known_place_run(settings: RuntimeSettings, normalized_id: str) -> dict[str, Any]:
    query = urlencode({"branch": KNOWN_PLACE_REF, "event": "workflow_dispatch", "per_page": "100"})
    path = (
        f"/repos/{KNOWN_PLACE_REPOSITORY}/actions/workflows/{KNOWN_PLACE_WORKFLOW}/runs?{query}"
    )
    _status, response = _github_request(settings, "GET", path)
    runs = response.get("workflow_runs")
    if not isinstance(runs, list):
        raise KnownPlaceWorkflowError("GitHub returned an invalid Known Place result response.")
    expected_title = f"Known Place Analysis {normalized_id}"
    for run in runs:
        if not isinstance(run, dict):
            continue
        if (
            run.get("display_title") == expected_title
            and run.get("path") == f".github/workflows/{KNOWN_PLACE_WORKFLOW}"
            and run.get("head_branch") == KNOWN_PLACE_REF
            and run.get("event") == "workflow_dispatch"
        ):
            if run.get("status") != "completed":
                raise KnownPlaceWorkflowError("KNOWN_PLACE_RESULTS_NOT_READY: the science workflow is still running.")
            if run.get("conclusion") != "success":
                conclusion = str(run.get("conclusion") or "unknown").upper()
                raise KnownPlaceWorkflowError(
                    f"KNOWN_PLACE_RESULTS_UNAVAILABLE: the GitHub Actions run concluded with {conclusion}."
                )
            return run
    raise KnownPlaceWorkflowError("KNOWN_PLACE_RESULTS_NOT_FOUND: no matching generic Known Place run was found.")


def _download_known_place_artifact(settings: RuntimeSettings, artifact_id: int) -> bytes:
    token = settings.github_actions_token.strip()
    if not token:
        raise KnownPlaceWorkflowError("Known Place result retrieval is not configured on this server.")
    request = Request(
        f"https://api.github.com/repos/{KNOWN_PLACE_REPOSITORY}/actions/artifacts/{artifact_id}/zip",
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        class _DoNotForwardGithubToken(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, new_url):
                return None

        opener = build_opener(_DoNotForwardGithubToken)
        try:
            response = opener.open(request, timeout=35)
        except HTTPError as redirect:
            if redirect.code not in {301, 302, 303, 307, 308}:
                raise
            location = redirect.headers.get("Location", "")
            target = urlsplit(location)
            if target.scheme != "https" or not target.netloc or target.username or target.password:
                raise KnownPlaceWorkflowError("GitHub returned an unsafe artifact download redirect.") from None
            # GitHub's short-lived object-storage URL is followed without the
            # GitHub Authorization header. The signed URL never reaches the browser.
            response = urlopen(Request(location, headers={"Accept": "application/zip"}), timeout=35)
        with response:
            archive_bytes = response.read(MAX_KNOWN_PLACE_ARTIFACT_BYTES + 1)
        if len(archive_bytes) > MAX_KNOWN_PLACE_ARTIFACT_BYTES:
            raise KnownPlaceWorkflowError("The Known Place result archive exceeds the safe download limit.")
        if not archive_bytes:
            raise KnownPlaceWorkflowError("GitHub returned an empty Known Place result archive.")
        return archive_bytes
    except HTTPError as exc:
        if exc.code == 401:
            raise KnownPlaceWorkflowError("GitHub rejected the server's Actions token while retrieving the result.") from None
        if exc.code == 403:
            raise KnownPlaceWorkflowError("GitHub denied Actions artifact read access for Known Place results.") from None
        if exc.code == 404:
            raise KnownPlaceWorkflowError("The Known Place result artifact is unavailable or has expired.") from None
        raise KnownPlaceWorkflowError(f"Could not download the Known Place result artifact ({exc.code}).") from None
    except (URLError, TimeoutError):
        raise KnownPlaceWorkflowError("Could not reach GitHub to retrieve the Known Place result artifact.") from None


def _load_generic_known_place_artifact(
    settings: RuntimeSettings,
    request_id: str,
) -> tuple[str, dict[str, Any], bytes]:
    normalized_id = _normalize_known_place_request_id(request_id)
    run = _find_generic_known_place_run(settings, normalized_id)
    run_id = run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        raise KnownPlaceWorkflowError("GitHub returned an invalid Known Place run identity.")
    path = f"/repos/{KNOWN_PLACE_REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"
    _status, response = _github_request(settings, "GET", path)
    artifacts = response.get("artifacts")
    if not isinstance(artifacts, list):
        raise KnownPlaceWorkflowError("GitHub returned an invalid Known Place artifact inventory.")
    expected_prefix = f"know-place-aoi-{run_id}-"
    matches = [
        item for item in artifacts
        if isinstance(item, dict)
        and isinstance(item.get("id"), int)
        and isinstance(item.get("name"), str)
        and item["name"].startswith(expected_prefix)
        and item.get("expired") is not True
    ]
    if not matches:
        raise KnownPlaceWorkflowError("KNOWN_PLACE_RESULTS_UNAVAILABLE: no unexpired result artifact exists for this run.")
    matches.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    artifact = matches[0]
    expected_digest = artifact.get("digest")
    if not isinstance(expected_digest, str) or not expected_digest.startswith("sha256:"):
        raise KnownPlaceWorkflowError("GitHub did not provide a SHA-256 digest for the Known Place result artifact.")
    archive_bytes = _download_known_place_artifact(settings, artifact["id"])
    actual_digest = "sha256:" + hashlib.sha256(archive_bytes).hexdigest()
    if not hmac.compare_digest(actual_digest, expected_digest):
        raise KnownPlaceWorkflowError("The downloaded Known Place result artifact failed GitHub SHA-256 verification.")
    return normalized_id, run, archive_bytes


def _safe_known_place_archive(archive_bytes: bytes) -> tuple[ZipFile, BytesIO]:
    buffer = BytesIO(archive_bytes)
    try:
        archive = ZipFile(buffer, "r")
        infos = archive.infolist()
        if not infos or len(infos) > MAX_KNOWN_PLACE_ARTIFACT_FILES:
            archive.close()
            raise KnownPlaceWorkflowError("The Known Place result archive has an invalid file count.")
        total_size = 0
        for info in infos:
            name = info.filename
            item_path = PurePosixPath(name)
            if (
                name.startswith("/")
                or "\\" in name
                or "\x00" in name
                or ".." in item_path.parts
                or item_path.is_absolute()
            ):
                archive.close()
                raise KnownPlaceWorkflowError("The Known Place result archive contains an unsafe path.")
            total_size += info.file_size
            if total_size > MAX_KNOWN_PLACE_ARTIFACT_UNCOMPRESSED_BYTES:
                archive.close()
                raise KnownPlaceWorkflowError("The Known Place result archive expands beyond the safe size limit.")
        return archive, buffer
    except BadZipFile:
        raise KnownPlaceWorkflowError("GitHub returned an unreadable Known Place result archive.") from None


def _read_known_place_member(archive: ZipFile, suffix: str, max_bytes: int) -> bytes:
    matches = [
        info for info in archive.infolist()
        if not info.is_dir() and info.filename.endswith(suffix)
    ]
    if len(matches) != 1:
        raise KnownPlaceWorkflowError(f"The Known Place result archive must contain exactly one {suffix} file.")
    info = matches[0]
    if info.file_size > max_bytes:
        raise KnownPlaceWorkflowError(f"The Known Place {suffix} file exceeds the safe size limit.")
    try:
        return archive.read(info)
    except (BadZipFile, OSError, RuntimeError):
        raise KnownPlaceWorkflowError(f"The Known Place {suffix} file could not be read.") from None


def _known_place_map_preview(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Project only the bounded, georeferenced preview; the native GeoTIFF remains authoritative."""
    preview = raw.get("map_preview")
    if not isinstance(preview, dict):
        return None

    width = preview.get("width")
    height = preview.get("height")
    epsg = raw.get("epsg")
    if (
        isinstance(width, bool) or not isinstance(width, int) or not 1 <= width <= 72
        or isinstance(height, bool) or not isinstance(height, int) or not 1 <= height <= 72
        or isinstance(epsg, bool) or not isinstance(epsg, int)
        or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760)
    ):
        return None

    def finite_number(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None

    def matrix(name: str) -> list[list[float | None]] | None:
        rows = preview.get(name)
        if not isinstance(rows, list) or len(rows) != height:
            return None
        output: list[list[float | None]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != width:
                return None
            projected_row: list[float | None] = []
            for cell in row:
                if cell is None:
                    projected_row.append(None)
                    continue
                number = finite_number(cell)
                if number is None:
                    return None
                projected_row.append(number)
            output.append(projected_row)
        return output

    values = matrix("values")
    east = matrix("east_values_m")
    north = matrix("north_values_m")
    if values is None or east is None or north is None:
        return None

    def ring(name: str, *, required: bool) -> list[list[float]] | None:
        points = preview.get(name)
        if points is None and not required:
            return None
        if not isinstance(points, list) or not 4 <= len(points) <= 256:
            return None
        output: list[list[float]] = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                return None
            x = finite_number(point[0])
            y = finite_number(point[1])
            if x is None or y is None:
                return None
            output.append([x, y])
        return output

    aoi_ring = ring("aoi_ring_xy", required=True)
    reference_ring = ring("reference_ring_xy", required=False)
    if aoi_ring is None:
        return None
    if preview.get("reference_ring_xy") is not None and reference_ring is None:
        return None

    min_x = finite_number(preview.get("min_x_m"))
    max_y = finite_number(preview.get("max_y_m"))
    pixel_x = finite_number(preview.get("pixel_size_x_m"))
    pixel_y = finite_number(preview.get("pixel_size_y_m"))
    stride = preview.get("stride_cells")
    if (
        min_x is None or max_y is None
        or pixel_x is None or pixel_y is None or pixel_x <= 0 or pixel_y <= 0
        or isinstance(stride, bool) or not isinstance(stride, int) or not 1 <= stride <= 1000
    ):
        return None

    return {
        "width": width,
        "height": height,
        "epsg": epsg,
        "values": values,
        "east_values_m": east,
        "north_values_m": north,
        "min_x_m": min_x,
        "max_y_m": max_y,
        "pixel_size_x_m": pixel_x,
        "pixel_size_y_m": pixel_y,
        "stride_cells": stride,
        "aoi_ring_xy": aoi_ring,
        "reference_ring_xy": reference_ring,
    }


def _known_place_pair_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_pairs = result.get("pairs")
    dynamics = result.get("motion_dynamics")
    feature_pairs = dynamics.get("pairs") if isinstance(dynamics, dict) else None
    if not isinstance(raw_pairs, list) or not isinstance(feature_pairs, list):
        raise KnownPlaceWorkflowError("The Known Place result is missing its pairwise measurement contract.")

    by_chain_interval: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    by_interval: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for item in feature_pairs:
        if not isinstance(item, dict):
            continue
        interval = (item.get("reference_date"), item.get("secondary_date"))
        chain_key = (item.get("chain_id"), *interval)
        by_chain_interval[chain_key] = item
        by_interval.setdefault(interval, []).append(item)

    rows: list[dict[str, Any]] = []
    for raw in raw_pairs:
        if not isinstance(raw, dict):
            continue
        interval = (raw.get("reference_date"), raw.get("secondary_date"))
        raw_chain_id = raw.get("chain_id")
        feature = by_chain_interval.get((raw_chain_id, *interval), {}) if raw_chain_id else {}
        # Backward compatibility is deliberately limited to unambiguous intervals.
        if not feature and not raw_chain_id:
            candidates = by_interval.get(interval, [])
            if len(candidates) == 1:
                feature = candidates[0]
        chain_id = str(raw_chain_id or feature.get("chain_id") or "")
        chain_parts = chain_id.split("-")
        rows.append({
            "reference_date": raw.get("reference_date"),
            "secondary_date": raw.get("secondary_date"),
            "interval_days": raw.get("interval_days"),
            "chain_id": chain_id,
            "track": raw.get("track") or (chain_parts[0] if len(chain_parts) > 1 else None),
            "direction": raw.get("direction") or (chain_parts[1] if len(chain_parts) > 1 else None),
            "polarization": raw.get("polarization"),
            "release_id": raw.get("release_id"),
            "catalog_maturity": raw.get("catalog_maturity"),
            "status": raw.get("status") or feature.get("measurement_status"),
            "valid_aoi_pixels": feature.get("valid_aoi_pixels", raw.get("valid_aoi_pixels")),
            "aoi_total_grid_cells": raw.get("aoi_total_grid_cells"),
            "valid_aoi_fraction": feature.get("valid_aoi_fraction", raw.get("valid_aoi_fraction")),
            "high_magnitude_flagged_pixels": feature.get("high_magnitude_flagged_pixels", raw.get("high_magnitude_flagged_pixels")),
            "high_magnitude_flagged_fraction": feature.get("high_magnitude_flagged_fraction"),
            "high_magnitude_threshold_m": raw.get("high_magnitude_threshold"),
            "median_horizontal_displacement_rate_m_per_day": feature.get("median_horizontal_displacement_rate_m_per_day"),
            "mean_vector_magnitude_rate_m_per_day": feature.get("mean_vector_magnitude_rate_m_per_day"),
            "mean_vector_east_rate_m_per_day": feature.get("mean_vector_east_rate_m_per_day"),
            "mean_vector_north_rate_m_per_day": feature.get("mean_vector_north_rate_m_per_day"),
            "mean_vector_azimuth_deg_clockwise_from_north": feature.get("mean_vector_azimuth_deg_clockwise_from_north"),
            "median_directional_coherence_R": feature.get("median_directional_coherence_R"),
            "crosses_registered_instrument_gap": feature.get("crosses_registered_instrument_gap", False),
            "grid_lattice_compatible_with_previous": feature.get("grid_lattice_compatible_with_previous"),
            "vector_rate_change_eligible": feature.get("vector_rate_change_eligible", False),
            "vector_rate_change_magnitude_m_per_day": feature.get("vector_rate_change_magnitude_m_per_day"),
            "vector_rate_acceleration_m_per_day_squared": feature.get("vector_rate_acceleration_m_per_day_squared"),
            "rate_change_block_reason": feature.get("rate_change_block_reason"),
            "spatial_uncertainty_status": feature.get("spatial_uncertainty_status"),
            "risk_score": feature.get("risk_score"),
            "risk_score_status": feature.get("risk_score_status", "NOT_CALIBRATED"),
            "detection_status": feature.get("detection_status", result.get("hazard_detection_status", "NOT_EVALUATED")),
            "quality_gate_counts": raw.get("quality_gate_counts"),
            "interval_coverage_warning": raw.get("interval_coverage_warning"),
            "map_preview": _known_place_map_preview(raw),
        })
    return rows

def _known_place_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    plan = result.get("pairwise_series_plan")
    dynamics = result.get("motion_dynamics")
    request = result.get("request")
    if not isinstance(plan, dict) or not isinstance(dynamics, dict) or not isinstance(request, dict):
        raise KnownPlaceWorkflowError("The Known Place result is missing its versioned science summary.")
    raw_chains = plan.get("chains")
    chains: list[dict[str, Any]] = []
    if isinstance(raw_chains, list):
        for chain in raw_chains:
            if not isinstance(chain, dict):
                continue
            geometry = chain.get("geometry_key") if isinstance(chain.get("geometry_key"), dict) else {}
            processing = chain.get("processing_identity") if isinstance(chain.get("processing_identity"), dict) else {}
            chain_pairs = []
            for pair in chain.get("pairs", []) if isinstance(chain.get("pairs"), list) else []:
                if not isinstance(pair, dict):
                    continue
                gaps = pair.get("known_instrument_data_gaps")
                chain_pairs.append({
                    "reference_date": pair.get("reference_date"),
                    "secondary_date": pair.get("secondary_date"),
                    "interval_days": pair.get("interval_days"),
                    "relation_to_previous": pair.get("relation_to_previous"),
                    "crosses_registered_instrument_gap": bool(gaps),
                    "gap_count": len(gaps) if isinstance(gaps, list) else 0,
                    "interval_coverage_warning": pair.get("interval_coverage_warning"),
                })
            chains.append({
                "chain_id": chain.get("chain_id"),
                "track": geometry.get("track"),
                "direction": geometry.get("direction"),
                "polarization": geometry.get("polarization"),
                "release_id": processing.get("release_id"),
                "maturity": processing.get("maturity"),
                "pair_count": chain.get("pair_count"),
                "continuous_chain_eligible": chain.get("continuous_chain_eligible"),
                "cumulative_displacement_status": chain.get("cumulative_displacement_status"),
                "grid_lattice_compatible": chain.get("grid_lattice_compatible"),
                "pairs": chain_pairs,
            })
    source_evidence = result.get("download_evidence")
    source_rows = []
    if isinstance(source_evidence, list):
        for source in source_evidence:
            if not isinstance(source, dict):
                continue
            source_rows.append({
                "granule_name": source.get("granule_name"),
                "release_id": source.get("release_id"),
                "maturity": source.get("maturity"),
                "source_sha256": source.get("source_sha256"),
                "source_bytes": source.get("source_bytes"),
                "cache_status": source.get("cache_status"),
            })
    req_aoi = request.get("aoi") if isinstance(request.get("aoi"), dict) else {}
    req_scope = request.get("scope_aoi") if isinstance(request.get("scope_aoi"), dict) else {}
    req_reference = request.get("reference") if isinstance(request.get("reference"), dict) else {}
    date_range = request.get("date_range") if isinstance(request.get("date_range"), dict) else {}
    return {
        "schema_version": result.get("schema_version"),
        "engine_version": result.get("engine_version"),
        "created_at_utc": result.get("created_at_utc"),
        "status": result.get("status"),
        "structural_status": result.get("structural_status"),
        "measurement_status": result.get("measurement_status"),
        "paper_reproduction_status": result.get("paper_reproduction_status"),
        "hazard_detection_status": result.get("hazard_detection_status"),
        "pair_measurement_counts": result.get("pair_measurement_counts"),
        "grid_compatibility_status": result.get("grid_compatibility_status"),
        "grid_mismatch_pair_count": result.get("grid_mismatch_pair_count"),
        "motion_dynamics": {
            "status": dynamics.get("status"),
            "measured_feature_count": dynamics.get("measured_feature_count"),
            "unmeasured_feature_count": dynamics.get("unmeasured_feature_count"),
            "risk_score": dynamics.get("risk_score"),
            "hazard_detection_status": dynamics.get("hazard_detection_status"),
            "interpretation": dynamics.get("interpretation"),
            "limitations": dynamics.get("limitations"),
        },
        "pairwise_series_plan": {
            "status": plan.get("status"),
            "chain_count": plan.get("chain_count"),
            "continuous_chain_eligible": plan.get("continuous_chain_eligible"),
            "cumulative_displacement_status": plan.get("cumulative_displacement_status"),
            "pair_count": plan.get("pair_count"),
            "pairwise_metrics_are_not_cumulative": plan.get("pairwise_metrics_are_not_cumulative"),
            "warnings": plan.get("warnings") if isinstance(plan.get("warnings"), list) else [],
            "known_nisar_data_gaps_intersecting_requested_pairs": plan.get("known_nisar_data_gaps_intersecting_requested_pairs"),
            "chains": chains,
        },
        "pairs": _known_place_pair_rows(result),
        "request": {
            "measurement_wkt": req_aoi.get("wkt"),
            "outer_scope_wkt": req_scope.get("wkt"),
            "reference_wkt": req_reference.get("polygon_wkt"),
            "date_range": date_range,
            "hazard_mode": request.get("hazard_mode"),
            "analysis_mode": request.get("analysis_mode"),
            "source_adapters": result.get("source_adapters"),
            "polarization": request.get("polarization"),
            "product_selection": request.get("product_selection"),
            "geometry_policy": request.get("geometry_policy"),
            "quality_policy": request.get("quality_policy"),
            "coherence_policy": request.get("coherence_policy"),
            "reference_policy": result.get("reference_policy"),
            "reference_buffer_m": result.get("reference_buffer_m"),
        },
        "source_evidence": source_rows,
        "limitations": result.get("limitations") if isinstance(result.get("limitations"), list) else [],
        "output_files": result.get("output_files") if isinstance(result.get("output_files"), list) else [],
    }


def _parse_known_place_result_archive(
    archive_bytes: bytes,
    request_id: str,
    run: dict[str, Any],
) -> dict[str, Any]:
    archive, _buffer = _safe_known_place_archive(archive_bytes)
    try:
        result_bytes = _read_known_place_member(archive, "/result.json", MAX_KNOWN_PLACE_RESULT_JSON_BYTES)
        dashboard_bytes = _read_known_place_member(archive, "/visuals/dashboard.html", MAX_KNOWN_PLACE_HTML_BYTES)
        map_bytes = _read_known_place_member(archive, "/visuals/interactive-map.html", MAX_KNOWN_PLACE_HTML_BYTES)
        try:
            result = json.loads(result_bytes.decode("utf-8"))
            dashboard_html = dashboard_bytes.decode("utf-8")
            interactive_map_html = map_bytes.decode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KnownPlaceWorkflowError("The Known Place result bundle contains invalid UTF-8 or JSON.") from None
        if not isinstance(result, dict) or result.get("schema_version") != "know-place-aoi-result/1.0":
            raise KnownPlaceWorkflowError("The Known Place result does not match the supported science schema.")
        if not isinstance(dashboard_html, str) or "<html" not in dashboard_html[:500].lower():
            raise KnownPlaceWorkflowError("The generated Known Place report is not a valid HTML document.")
        if not isinstance(interactive_map_html, str) or "<html" not in interactive_map_html[:500].lower():
            raise KnownPlaceWorkflowError("The generated Known Place map is not a valid HTML document.")
        summary = _known_place_result_summary(result)
        receipt_bytes = None
        receipt_matches = [
            info for info in archive.infolist()
            if not info.is_dir() and info.filename.endswith(".drive-upload-receipt.json")
        ]
        if len(receipt_matches) == 1 and receipt_matches[0].file_size <= 128_000:
            receipt_bytes = archive.read(receipt_matches[0])
        storage: dict[str, Any] = {"status": "NOT_PRESENT", "remote_bytes_verified": False, "hash_verified": False}
        if receipt_bytes:
            try:
                receipt = json.loads(receipt_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                receipt = {}
            if isinstance(receipt, dict):
                local_hash = receipt.get("bundle_sha256_local")
                remote_hash = receipt.get("bundle_sha256_downloaded_from_drive")
                storage = {
                    "status": receipt.get("status"),
                    "action": receipt.get("action"),
                    "bundle_bytes": receipt.get("bundle_bytes"),
                    "remote_bytes_verified": receipt.get("remote_bytes_verified") is True,
                    "hash_verified": isinstance(local_hash, str) and local_hash == remote_hash,
                    "raw_h5_included": receipt.get("raw_h5_included"),
                    "bundled_file_count": (receipt.get("bundle") or {}).get("bundled_file_count")
                    if isinstance(receipt.get("bundle"), dict) else None,
                }
        return {
            "request_id": request_id,
            "run": {
                "id": run.get("id"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "html_url": run.get("html_url"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "head_sha": run.get("head_sha"),
            },
            "result": summary,
            "storage": storage,
            "dashboard_html": dashboard_html,
            "interactive_map_html": interactive_map_html,
        }
    finally:
        archive.close()


def get_known_place_analysis_results(settings: RuntimeSettings, request_id: str) -> dict[str, Any]:
    """Return authenticated, bounded view data from the completed generic Known Place artifact."""
    normalized_id, run, archive_bytes = _load_generic_known_place_artifact(settings, request_id)
    return _parse_known_place_result_archive(archive_bytes, normalized_id, run)


def download_known_place_analysis_bundle(settings: RuntimeSettings, request_id: str) -> tuple[str, bytes]:
    """Return the original Actions artifact ZIP after validating its request/run identity."""
    normalized_id, _run, archive_bytes = _load_generic_known_place_artifact(settings, request_id)
    # Validate the archive before making the original package available to the browser.
    archive, _buffer = _safe_known_place_archive(archive_bytes)
    archive.close()
    return f"SARGuardian-known-place-{normalized_id}.zip", archive_bytes
