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
        ("moshiour0/SARGuardian-backend", "know-place-paper-reproduction-dispatcher.yml"),
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
    assert observed["path"] == (
        "/repos/moshiour0/SARGuardian-backend/actions/workflows/"
        "know-place-paper-reproduction-dispatcher.yml/dispatches"
    )
    assert observed["body"]["ref"] == "main"
    inputs = observed["body"]["inputs"]
    assert inputs["request_id"] == response.request_id
    assert inputs["consent_marker"] == "[run-know-place]"
    assert inputs["geometry_height_m"] == "5151"
    assert inputs["control_draws"] == "1000"
    assert inputs["seed"] == "260826"


def test_author_exact_paper_reproduction_status_is_matched_by_request_and_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = "c19a7630-9f19-4b38-ae0e-88d53ad7c8f2"

    def fake_request(_settings, method, path, body=None):
        assert method == "GET"
        assert "know-place-paper-reproduction-dispatcher.yml/runs" in path
        return 200, {
            "workflow_runs": [
                {
                    "id": 54321,
                    "display_title": f"Known Place Paper Reproduction {request_id}",
                    "path": ".github/workflows/know-place-paper-reproduction-dispatcher.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/moshiour0/SARGuardian-backend/actions/runs/54321",
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
    assert known_place.KNOWN_PLACE_REPOSITORY == "moshiour0/SARGuardian-backend"
    assert known_place.KNOWN_PLACE_WORKFLOW == "know-place-aoi-dispatcher.yml"
    assert known_place.KNOWN_PLACE_REF == "main"
    assert known_place.KNOWN_PLACE_PAPER_REPOSITORY == "moshiour0/SARGuardian-backend"
    assert known_place.KNOWN_PLACE_PAPER_WORKFLOW == "know-place-paper-reproduction-dispatcher.yml"
    assert known_place.KNOWN_PLACE_PAPER_REF == "main"
    assert known_place.KNOWN_PLACE_PAPER_WORKFLOW != known_place.KNOWN_PLACE_WORKFLOW


def _known_place_test_artifact() -> bytes:
    import json
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    pairs = []
    features = []
    chains = []
    for track, direction, rate in (("048", "D", 24.48), ("098", "A", 0.07)):
        reference_date = "2026-08-16" if direction == "D" else "2026-08-19"
        secondary_date = "2026-08-28" if direction == "D" else "2026-08-31"
        chain_id = f"{track}-{direction}-HH-PROVISIONAL-P05023"
        pairs.append({
            "reference_date": reference_date,
            "secondary_date": secondary_date,
            "interval_days": 12,
            "track": track,
            "direction": direction,
            "polarization": "HH",
            "release_id": "P05023",
            "catalog_maturity": "PROVISIONAL",
            "status": "METRICS_COMPUTED",
            "aoi_total_grid_cells": 67,
            "valid_aoi_pixels": 9 if direction == "D" else 65,
            "valid_aoi_fraction": 9 / 67 if direction == "D" else 65 / 67,
            "high_magnitude_flagged_pixels": 9 if direction == "D" else 0,
            "high_magnitude_threshold": 10,
            "quality_gate_counts": {"valid": 9},
            "interval_coverage_warning": "Interval-averaged pairwise observation.",
        })
        features.append({
            "reference_date": reference_date,
            "secondary_date": secondary_date,
            "chain_id": chain_id,
            "measurement_status": "METRICS_COMPUTED",
            "median_horizontal_displacement_rate_m_per_day": rate,
            "mean_vector_magnitude_rate_m_per_day": rate * 0.8,
            "mean_vector_east_rate_m_per_day": 0.1,
            "mean_vector_north_rate_m_per_day": 0.2,
            "mean_vector_azimuth_deg_clockwise_from_north": 45,
            "median_directional_coherence_R": 0.4,
            "valid_aoi_pixels": 9 if direction == "D" else 65,
            "valid_aoi_fraction": 9 / 67 if direction == "D" else 65 / 67,
            "high_magnitude_flagged_pixels": 9 if direction == "D" else 0,
            "high_magnitude_flagged_fraction": 9 / 67 if direction == "D" else 0,
            "risk_score": None,
            "risk_score_status": "NOT_CALIBRATED",
            "detection_status": "NOT_EVALUATED",
            "crosses_registered_instrument_gap": direction == "A",
        })
        chains.append({
            "chain_id": chain_id,
            "geometry_key": {"track": track, "direction": direction, "polarization": "HH"},
            "processing_identity": {"release_id": "P05023", "maturity": "PROVISIONAL"},
            "pair_count": 1,
            "continuous_chain_eligible": True,
            "cumulative_displacement_status": "ELIGIBLE_FOR_SEPARATE_REVIEW",
            "grid_lattice_compatible": True,
            "pairs": [{
                "reference_date": reference_date,
                "secondary_date": secondary_date,
                "interval_days": 12,
                "relation_to_previous": "FIRST_PAIR",
                "known_instrument_data_gaps": [{"reason": "instrument gap"}] if direction == "A" else [],
                "interval_coverage_warning": "Interval gap review." if direction == "A" else "Pairwise interval.",
            }],
        })
    result = {
        "schema_version": "know-place-aoi-result/1.0",
        "engine_version": "1.0.0",
        "created_at_utc": "2026-11-02T14:28:05Z",
        "status": "SCIENTIFIC_METRICS_COMPUTED",
        "structural_status": "PASS",
        "measurement_status": "METRICS_COMPUTED_ALL_PAIRS",
        "paper_reproduction_status": "NOT_EVALUATED_GENERIC_AOI",
        "hazard_detection_status": "NOT_EVALUATED",
        "request": {
            "aoi": {"wkt": AOI},
            "scope_aoi": {"wkt": AOI},
            "reference": {"polygon_wkt": AOI},
            "date_range": {"start": "2026-06-20", "end": "2026-09-18", "inclusive": True},
            "hazard_mode": "mixed",
            "analysis_mode": "exploratory",
            "source_adapters": ["NISAR_GOFF"],
            "polarization": "HH",
            "product_selection": {"allowed_release_ids": ["P05023"], "allowed_maturities": ["PROVISIONAL"]},
            "geometry_policy": {"source": "product_height_axis_midpoint_approximation"},
            "quality_policy": {"maximum_horizontal_magnitude_m": 10},
            "coherence_policy": {"window_size": 5},
        },
        "source_adapters": ["NISAR_GOFF"],
        "reference_policy": "external_reference_polygon_component_median",
        "reference_buffer_m": 2000,
        "pairwise_series_plan": {
            "status": "PAIRWISE_SERIES_PLANNED",
            "chain_count": 2,
            "continuous_chain_eligible": False,
            "cumulative_displacement_status": "SEPARATE_CHAINS_REVIEW_REQUIRED",
            "pair_count": 2,
            "pairwise_metrics_are_not_cumulative": True,
            "warnings": ["Orbit chains must not be combined."],
            "known_nisar_data_gaps_intersecting_requested_pairs": 1,
            "chains": chains,
        },
        "grid_compatibility_status": "CONSISTENT_LATTICE_WITHIN_CHAINS",
        "grid_mismatch_pair_count": 0,
        "pairs": pairs,
        "download_evidence": [{
            "granule_name": "NISAR_L2_PR_GOFF_TEST_P05023.h5",
            "release_id": "P05023",
            "maturity": "PROVISIONAL",
            "source_sha256": "a" * 64,
            "source_bytes": 1024,
            "cache_status": "DOWNLOADED_AND_HASHED",
        }],
        "pair_measurement_counts": {"requested": 2, "metrics_computed": 2, "insufficient_data": 0},
        "limitations": ["No hazard detection was evaluated."],
        "motion_dynamics": {
            "status": "DESCRIPTIVE_MOTION_FEATURES_COMPUTED",
            "measured_feature_count": 2,
            "unmeasured_feature_count": 0,
            "risk_score": None,
            "hazard_detection_status": "NOT_EVALUATED",
            "interpretation": "Pairwise rate only.",
            "limitations": ["Not cumulative."],
            "pairs": features,
        },
        "output_files": ["timeseries.csv", "motion-features.csv"],
    }
    receipt = {
        "status": "PASS",
        "action": "UPLOADED",
        "bundle_bytes": 2048,
        "bundle_sha256_local": "b" * 64,
        "bundle_sha256_downloaded_from_drive": "b" * 64,
        "remote_bytes_verified": True,
        "raw_h5_included": False,
        "bundle": {"bundled_file_count": 4},
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("know-place-aoi-output/run/result.json", json.dumps(result))
        archive.writestr("know-place-aoi-output/run/visuals/dashboard.html", "<!doctype html><html><body>Report</body></html>")
        archive.writestr("know-place-aoi-output/run/visuals/interactive-map.html", "<!doctype html><html><body>Map</body></html>")
        archive.writestr("know-place-aoi-output/know-place-77-attempt-1.drive-upload-receipt.json", json.dumps(receipt))
    return buffer.getvalue()


def test_known_place_result_parser_preserves_separate_chains_and_claim_gates() -> None:
    archive = _known_place_test_artifact()
    run = {
        "id": 77,
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/moshiour0/SARGuardian-backend/actions/runs/77",
        "created_at": "2026-11-02T14:00:00Z",
        "updated_at": "2026-11-02T14:30:00Z",
        "head_sha": "a" * 40,
    }
    parsed = known_place._parse_known_place_result_archive(
        archive, "c19a7630-9f19-4b38-ae0e-88d53ad7c8f2", run,
    )
    result = parsed["result"]
    assert result["pair_measurement_counts"]["metrics_computed"] == 2
    assert result["pairwise_series_plan"]["chain_count"] == 2
    assert result["pairwise_series_plan"]["cumulative_displacement_status"] == "SEPARATE_CHAINS_REVIEW_REQUIRED"
    assert {pair["track"] for pair in result["pairs"]} == {"048", "098"}
    assert result["pairs"][0]["median_horizontal_displacement_rate_m_per_day"] == 24.48
    assert result["hazard_detection_status"] == "NOT_EVALUATED"
    assert result["paper_reproduction_status"] == "NOT_EVALUATED_GENERIC_AOI"
    assert parsed["storage"]["hash_verified"] is True
    assert parsed["storage"]["remote_bytes_verified"] is True
    assert parsed["storage"]["raw_h5_included"] is False
    assert "<html" in parsed["interactive_map_html"]


def test_known_place_result_lookup_requires_exact_generic_workflow_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = "c19a7630-9f19-4b38-ae0e-88d53ad7c8f2"
    observed_paths: list[str] = []

    def fake_request(_settings, method, path, body=None):
        assert method == "GET"
        observed_paths.append(path)
        if "know-place-aoi-dispatcher.yml/runs" in path:
            return 200, {"workflow_runs": [
                {
                    "id": 77,
                    "display_title": f"Known Place Analysis {request_id}",
                    "path": ".github/workflows/know-place-aoi-dispatcher.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/moshiour0/SARGuardian-backend/actions/runs/77",
                    "created_at": "2026-11-02T14:00:00Z",
                    "updated_at": "2026-11-02T14:30:00Z",
                    "head_sha": "a" * 40,
                },
                {
                    "id": 76,
                    "display_title": f"Known Place Paper Reproduction {request_id}",
                    "path": ".github/workflows/know-place-paper-reproduction-dispatcher.yml",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]}
        assert "/actions/runs/77/artifacts" in path
        return 200, {"artifacts": [
            {"id": 100, "name": "know-place-aoi-77-1", "expired": False, "created_at": "2026-11-02T14:30:00Z"},
        ]}

    monkeypatch.setattr(known_place, "_github_request", fake_request)
    monkeypatch.setattr(known_place, "_download_known_place_artifact", lambda _settings, _artifact_id: _known_place_test_artifact())
    parsed = known_place.get_known_place_analysis_results(settings(), request_id)
    assert parsed["run"]["id"] == 77
    assert parsed["result"]["pair_measurement_counts"]["requested"] == 2
    assert len(observed_paths) == 2
    assert "know-place-aoi-dispatcher.yml" in observed_paths[0]
    assert "know-place-paper-reproduction-dispatcher.yml" not in observed_paths[0]


def test_known_place_result_archive_rejects_path_traversal() -> None:
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../result.json", "{}")
    with pytest.raises(known_place.KnownPlaceWorkflowError, match="unsafe path"):
        known_place._safe_known_place_archive(buffer.getvalue())
