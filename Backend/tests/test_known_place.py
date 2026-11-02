from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import known_place


AOI = "POLYGON ((85.50 28.25, 85.54 28.25, 85.54 28.29, 85.50 28.29, 85.50 28.25))"
REQUEST = {
    "aoi_wkt": AOI,
    "start_date": "2026-07-01",
    "end_date": "2026-07-20",
    "hazard_mode": "ice_rock_avalanche",
    "analysis_mode": "exploratory",
    "polarization": "HH",
    "track": "ANY",
    "direction": "A",
    "coherence_neighbours": "5",
    "execute_downloads": False,
}


def settings() -> SimpleNamespace:
    return SimpleNamespace(displacement_actions_enabled=True, github_actions_token="test-token")


def test_known_place_request_canonicalizes_wkt_and_defaults_to_no_raw_downloads() -> None:
    request = known_place.KnownPlaceAnalysisRequest(**REQUEST)
    assert request.aoi_wkt.startswith("POLYGON((")
    assert request.execute_downloads is False
    assert request.confirm_raw_downloads is False


def test_known_place_request_requires_explicit_consent_for_raw_downloads() -> None:
    with pytest.raises(ValidationError, match="EXPLICIT_RAW_DOWNLOAD_CONSENT_REQUIRED"):
        known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"execute_downloads": True}))


def test_known_place_request_rejects_bad_track_and_invalid_polygon() -> None:
    with pytest.raises(ValidationError, match="TRACK_MUST_BE_ANY_OR_THREE_DIGITS"):
        known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"track": "98"}))
    with pytest.raises(ValidationError, match="AOI_WKT_INVALID"):
        known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"aoi_wkt": "POLYGON ((0 0, 1 0, 1 1))"}))


@pytest.mark.parametrize(
    "repository,workflow",
    [
        ("moshiour0/SARGuardian-backend", "know-place-aoi-dispatcher.yml"),
        ("moshiour0/SARGuardian_Dynamic", "known-place-paper-reproduction.yml"),
    ],
)
def test_github_dispatch_403_explains_target_repository_permission(
    monkeypatch: pytest.MonkeyPatch, repository: str, workflow: str,
) -> None:
    from io import BytesIO
    from urllib.error import HTTPError

    def forbidden(*_args, **_kwargs):
        raise HTTPError("https://api.github.com", 403, "Forbidden", {}, BytesIO(b""))

    monkeypatch.setattr(known_place, "urlopen", forbidden)
    owner, name = repository.split("/")
    path = f"/repos/{owner}/{name}/actions/workflows/{workflow}/dispatches"
    with pytest.raises(known_place.KnownPlaceWorkflowError, match="GitHub denied workflow dispatch to") as exc:
        known_place._github_request(settings(), "POST", path, {"ref": "main", "inputs": {}})
    assert repository in str(exc.value)
    assert "Actions: read and write" in str(exc.value)


def test_dry_run_dispatch_does_not_include_raw_download_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict = {}

    def fake_request(_settings, method, path, body=None):
        observed.update({"method": method, "path": path, "body": body})
        return 204, {}

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    request = known_place.KnownPlaceAnalysisRequest(**REQUEST)
    response = known_place.dispatch_known_place_analysis(settings(), request)

    assert response.status == "dispatching"
    assert response.execute_downloads is False
    assert observed["method"] == "POST"
    assert observed["path"] == (
        "/repos/moshiour0/SARGuardian-backend/actions/workflows/"
        "know-place-aoi-dispatcher.yml/dispatches"
    )
    assert observed["body"]["ref"] == "main"
    inputs = observed["body"]["inputs"]
    assert inputs["request_id"] == response.request_id
    assert inputs["execute_downloads"] is False
    assert inputs["consent_marker"] == ""


def test_raw_analysis_dispatch_needs_confirmed_checkbox_and_sets_exact_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict = {}

    def fake_request(_settings, method, path, body=None):
        observed.update({"method": method, "path": path, "body": body})
        return 204, {}

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    request = known_place.KnownPlaceAnalysisRequest(**(
        REQUEST | {"execute_downloads": True, "confirm_raw_downloads": True}
    ))
    response = known_place.dispatch_known_place_analysis(settings(), request)

    assert response.execute_downloads is True
    assert observed["method"] == "POST"
    assert observed["path"].startswith("/repos/moshiour0/SARGuardian-backend/")
    assert observed["path"].endswith("/know-place-aoi-dispatcher.yml/dispatches")
    assert observed["body"]["inputs"]["execute_downloads"] is True
    assert observed["body"]["inputs"]["consent_marker"] == "[run-know-place]"


def test_status_is_matched_by_random_request_id_and_workflow_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = "c19a7630-9f19-4b38-ae0e-88d53ad7c8f2"

    def fake_request(_settings, method, path, body=None):
        assert method == "GET"
        assert "/repos/moshiour0/SARGuardian-backend/actions/workflows/know-place-aoi-dispatcher.yml/runs" in path
        return 200, {
            "workflow_runs": [
                {
                    "id": 12345,
                    "display_title": f"Known Place Analysis {request_id}",
                    "path": ".github/workflows/know-place-aoi-dispatcher.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/moshiour0/SARGuardian-backend/actions/runs/12345",
                    "created_at": "2026-10-28T00:00:00Z",
                    "updated_at": "2026-10-28T00:01:00Z",
                },
                {
                    "id": 12344,
                    "display_title": "Unrelated workflow",
                    "path": ".github/workflows/sarguardian-displacement.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        }

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    response = known_place.get_known_place_analysis_status(settings(), request_id)
    assert response.status == "completed"
    assert response.github_run_id == "12345"
    assert response.conclusion == "success"
    assert response.github_run_url.endswith("/12345")


def test_status_with_unknown_request_id_remains_dispatching(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(known_place, "_github_request", lambda *_args, **_kwargs: (200, {"workflow_runs": []}))
    response = known_place.get_known_place_analysis_status(
        settings(), "c19a7630-9f19-4b38-ae0e-88d53ad7c8f2"
    )
    assert response.status == "dispatching"
    assert response.github_run_id is None

def test_known_place_request_preserves_outer_scope_polygon_and_dispatches_it(monkeypatch: pytest.MonkeyPatch) -> None:
    outer = "POLYGON ((85.49 28.24, 85.55 28.24, 85.55 28.30, 85.49 28.30, 85.49 28.24))"
    observed: dict = {}

    def fake_request(_settings, _method, _path, body=None):
        observed.update(body or {})
        return 204, {}

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    request = known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"scope_aoi_wkt": outer}))
    assert request.scope_aoi_wkt is not None
    response = known_place.dispatch_known_place_analysis(settings(), request)
    assert response.status == "dispatching"
    assert observed["inputs"]["scope_aoi_wkt"].startswith("POLYGON((" )


def test_known_place_request_rejects_invalid_outer_scope_polygon() -> None:
    with pytest.raises(ValidationError, match="SCOPE_AOI_WKT_INVALID"):
        known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"scope_aoi_wkt": "POLYGON ((0 0, 1 0, 1 1))"}))

def test_author_exact_paper_reproduction_requires_explicit_raw_download_consent() -> None:
    with pytest.raises(ValidationError, match="EXPLICIT_AUTHOR_EXACT_RAW_DOWNLOAD_CONSENT_REQUIRED"):
        known_place.KnownPlacePaperReproductionRequest()
    request = known_place.KnownPlacePaperReproductionRequest(confirm_raw_downloads=True)
    assert request.confirm_raw_downloads is True


def test_author_exact_paper_reproduction_dispatches_immutable_backend_pin_and_exact_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict = {}

    def fake_request(_settings, method, path, body=None):
        observed.update({"method": method, "path": path, "body": body})
        return 204, {}

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    request = known_place.KnownPlacePaperReproductionRequest(confirm_raw_downloads=True)
    response = known_place.dispatch_known_place_paper_reproduction(settings(), request)

    assert response.status == "dispatching"
    assert response.execute_downloads is True
    assert observed["method"] == "POST"
    assert observed["path"].endswith("/known-place-paper-reproduction.yml/dispatches")
    assert observed["body"]["ref"] == "main"
    inputs = observed["body"]["inputs"]
    assert inputs["request_id"] == response.request_id
    assert inputs["consent_marker"] == "[run-know-place]"
    assert inputs["backend_code_ref"] == known_place.KNOWN_PLACE_AUTHOR_BACKEND_REF
    assert len(inputs["backend_code_ref"]) == 40
    assert inputs["geometry_height_m"] == "5151"
    assert inputs["control_draws"] == "1000"
    assert inputs["seed"] == "260826"


def test_author_exact_paper_reproduction_status_is_matched_by_request_and_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = "c19a7630-9f19-4b38-ae0e-88d53ad7c8f2"

    def fake_request(_settings, method, path, body=None):
        assert method == "GET"
        assert "known-place-paper-reproduction.yml/runs" in path
        return 200, {
            "workflow_runs": [
                {
                    "id": 54321,
                    "display_title": f"Known Place Paper Reproduction {request_id}",
                    "path": ".github/workflows/known-place-paper-reproduction.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/moshiour0/SARGuardian_Dynamic/actions/runs/54321",
                    "created_at": "2026-11-02T00:00:00Z",
                    "updated_at": "2026-11-02T00:30:00Z",
                },
                {
                    "id": 54320,
                    "display_title": "Unrelated workflow",
                    "path": ".github/workflows/know-place-aoi-dispatcher.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "failure",
                },
            ]
        }

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    response = known_place.get_known_place_paper_reproduction_status(settings(), request_id)
    assert response.status == "completed"
    assert response.github_run_id == "54321"
    assert response.conclusion == "success"
    assert response.github_run_url.endswith("/54321")


def candidate_context() -> dict:
    return {
        "source": "FIND_DISPLACEMENTS",
        "candidate_id": "GOFF-CANDIDATE-004",
        "product_type": "GOFF",
        "metric": "GOFF_SLANT_RANGE_OFFSET_MM",
        "evidence_class": "GOFF_OFFSET_ANOMALY_NOT_GROUND_MOTION",
        "status": "REPEATED_SPATIAL_CANDIDATE",
        "support_pairs": 3,
        "pixel_count": 42,
        "approx_area_m2": 268800.0,
        "product_ids": ["NISAR_GOFF_P05023_A", "NISAR_GOFF_P05023_B"],
        "pair_intervals": [{"reference_date": "2026-07-01", "secondary_date": "2026-07-13"}],
        "geometry_original_vertices": 1800,
        "geometry_suggested_vertices": 420,
        "geometry_simplified": True,
        "geometry_edited": True,
        "interpretation": "Offset anomaly candidate; not measured ground motion.",
    }


def test_goff_candidate_provenance_is_validated_and_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict = {}

    def fake_request(_settings, _method, _path, body=None):
        observed.update(body or {})
        return 204, {}

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    request = known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"candidate_context": candidate_context()}))
    known_place.dispatch_known_place_analysis(settings(), request)
    sent = __import__("json").loads(observed["inputs"]["candidate_context_json"])
    assert sent["source"] == "FIND_DISPLACEMENTS"
    assert sent["product_type"] == "GOFF"
    assert sent["candidate_id"] == "GOFF-CANDIDATE-004"
    assert sent["geometry_simplified"] is True


def test_gunw_candidate_cannot_be_sent_to_goff_known_place_measurement() -> None:
    value = candidate_context() | {"product_type": "GUNW", "evidence_class": "GUNW_LOS_DISPLACEMENT_ANOMALY_UNCONFIRMED"}
    with pytest.raises(ValidationError, match="CANDIDATE_CONTEXT_MUST_BE_A_GOFF"):
        known_place.KnownPlaceAnalysisRequest(**(REQUEST | {"candidate_context": value}))


def test_generic_known_place_dispatch_is_backend_owned_and_paper_reproduction_stays_separate() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    paper_workflow = (repository_root / ".github" / "workflows" / known_place.KNOWN_PLACE_PAPER_WORKFLOW).read_text(encoding="utf-8")

    assert known_place.KNOWN_PLACE_REPOSITORY == "moshiour0/SARGuardian-backend"
    assert known_place.KNOWN_PLACE_WORKFLOW == "know-place-aoi-dispatcher.yml"
    assert known_place.KNOWN_PLACE_REF == "main"
    assert known_place.KNOWN_PLACE_PAPER_REPOSITORY == "moshiour0/SARGuardian_Dynamic"
    assert known_place.KNOWN_PLACE_PAPER_WORKFLOW != known_place.KNOWN_PLACE_WORKFLOW
    assert "moshiour0/SARGuardian-backend/.github/workflows/know-place-author-exact-replay.yml@" in paper_workflow
    assert known_place.KNOWN_PLACE_AUTHOR_BACKEND_REF in paper_workflow
    assert 'backend_code_ref: "' + known_place.KNOWN_PLACE_AUTHOR_BACKEND_REF + '"' in paper_workflow
    assert "consent_marker: ${{ inputs.consent_marker }}" in paper_workflow
    assert "bridge_authorized: false" in paper_workflow
    assert "know-place-aoi-analysis.yml@" not in paper_workflow
    assert "know-place-author-exact-replay.yml@" in paper_workflow
