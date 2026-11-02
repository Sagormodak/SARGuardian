"""Authenticated dispatch/status adapter for the separate Known Place Analysis workflow.

The workflow run itself is the source of truth for this analysis; no second copy of raw
science data or extra database table is created here. Request IDs are random UUIDs and
are embedded in the Actions run title so the browser can poll only its own known run.
"""
from __future__ import annotations

from datetime import date
import json
import math
import re
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import RuntimeSettings
from science_adapter.geometry import validate_wkt

# Generic two-polygon measurement runs in the scientific backend repository.
KNOWN_PLACE_REPOSITORY = "moshiour0/SARGuardian-backend"
KNOWN_PLACE_WORKFLOW = "know-place-aoi-dispatcher.yml"
KNOWN_PLACE_REF = "main"
KNOWN_PLACE_WORKFLOW_PAGE = (
    f"https://github.com/{KNOWN_PLACE_REPOSITORY}/actions/workflows/{KNOWN_PLACE_WORKFLOW}"
)

# The fixed author-exact paper launcher remains separate from the generic AOI workflow.
KNOWN_PLACE_PAPER_REPOSITORY = "moshiour0/SARGuardian_Dynamic"
KNOWN_PLACE_PAPER_WORKFLOW = "known-place-paper-reproduction.yml"
KNOWN_PLACE_PAPER_REF = "main"
KNOWN_PLACE_PAPER_WORKFLOW_PAGE = (
    f"https://github.com/{KNOWN_PLACE_PAPER_REPOSITORY}/actions/workflows/{KNOWN_PLACE_PAPER_WORKFLOW}"
)
# Immutable backend commit containing the author-exact workflow and science code.
KNOWN_PLACE_AUTHOR_BACKEND_REF = "d847b0461a2fec1bdf2abcce0a6b1d2f9dddabc9"
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
        if exc.code in (401, 403):
            raise KnownPlaceWorkflowError("GitHub Actions dispatch is not authorized; check the server's workflow token permissions.") from None
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
        "backend_code_ref": KNOWN_PLACE_AUTHOR_BACKEND_REF,
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
