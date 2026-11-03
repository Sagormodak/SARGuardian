from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from app import river_shift_jobs as river_module
from app.auth import get_current_user
from app.main import app


class RiverShiftStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get_river_shift_job_by_idempotency(self, owner_uid: str, key: str):
        return next((row for row in self.rows.values()
                     if row["owner_uid"] == owner_uid and row["idempotency_key"] == key), None)

    def create_river_shift_job(self, values: dict):
        existing = self.get_river_shift_job_by_idempotency(values["owner_uid"], values["idempotency_key"])
        if existing:
            return existing
        now = datetime.now(UTC)
        row = values | {"created_at": now, "updated_at": now, "github_run_id": None,
                        "github_run_url": None, "error_code": None, "error_message": None}
        self.rows[row["id"]] = row
        return row

    def list_river_shift_jobs(self, owner_uid: str, limit: int = 20):
        rows = [row for row in self.rows.values() if row["owner_uid"] == owner_uid]
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)[:limit]

    def list_active_river_shift_jobs(self, owner_uid: str):
        return [row for row in self.rows.values()
                if row["owner_uid"] == owner_uid and row["state"] in {"queued", "dispatching", "running"}][:2]

    def get_river_shift_job(self, owner_uid: str, job_id):
        row = self.rows.get(str(job_id))
        return row if row and row["owner_uid"] == owner_uid else None

    def get_river_shift_job_unscoped(self, job_id):
        return self.rows.get(str(job_id))

    def update_river_shift_job(self, job_id, values, *, expected_state=None, expected_sequence=None):
        row = self.rows[str(job_id)]
        if expected_state is not None and row["state"] != expected_state:
            raise river_module.PersistenceConflictError("state conflict")
        if expected_sequence is not None and row["callback_sequence"] != expected_sequence:
            raise river_module.PersistenceConflictError("sequence conflict")
        row.update(values)
        row["updated_at"] = datetime.now(UTC)
        return row


def setup_function() -> None:
    app.dependency_overrides.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def payload() -> dict:
    return {
        "aoi_wkt": "POLYGON ((85 27, 85.01 27, 85.01 27.01, 85 27.01, 85 27))",
        "start_date": "2026-08-01",
        "end_date": "2026-09-20",
        "analysis_mode": "event_based",
        "event_date": "2026-08-20",
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "covariance_term": "HHHH",
        "threshold_method": "otsu",
        "idempotency_key": "river-shift-request-0001",
    }


def configure(monkeypatch, store: RiverShiftStore, *, owner: str = "river-user") -> TestClient:
    monkeypatch.setattr(river_module, "get_job_store", lambda: store)
    monkeypatch.setattr(river_module, "get_settings", lambda: type("Settings", (), {
        "river_shift_actions_enabled": True,
        "river_shift_github_actions_token": "server-token",
        "river_shift_github_actions_repository": "moshiour0/SARGuardian-backend",
        "river_shift_github_actions_workflow": "river-shift-gcov-process.yml",
        "river_shift_github_actions_ref": "main",
        "river_shift_callback_secret": "river-callback-secret",
        "river_shift_public_api_url": "https://api.example.test",
        "github_api_url": "https://api.github.com",
    })())
    monkeypatch.setattr(river_module, "_discover_manifest", lambda _payload: ({
        "schema_version": 1,
        "unique_dates": ["2026-08-01", "2026-08-13", "2026-08-25", "2026-09-06", "2026-09-18"],
        "products": [{"granule_name": f"NISAR_L2_GCOV_{i:02d}"} for i in range(4)],
    }, [f"NISAR_L2_GCOV_{i:02d}" for i in range(4)]))
    monkeypatch.setattr(river_module, "_dispatch", lambda *_args: None)
    app.dependency_overrides[get_current_user] = lambda: {"uid": owner}
    return TestClient(app)


def sign_callback(body: bytes) -> str:
    digest = hmac.new(b"river-callback-secret", body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def test_create_river_shift_job_is_owner_scoped_and_idempotent(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    first = api.post("/api/river-shift/jobs", json=payload())
    assert first.status_code == 200, first.text
    job = first.json()
    assert job["state"] == "dispatching"
    assert job["stage"] == "workflow_dispatch"
    assert job["id"]
    assert len(store.rows) == 1

    duplicate = api.post("/api/river-shift/jobs", json=payload())
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == job["id"]
    assert len(store.rows) == 1

    app.dependency_overrides[get_current_user] = lambda: {"uid": "another-user"}
    hidden = api.get(f"/api/river-shift/jobs/{job['id']}")
    assert hidden.status_code == 404




def test_compact_iso_and_filename_acquisition_times_normalize_to_utc_dates() -> None:
    assert river_module._acquisition_date("20260627T124243") == "2026-06-27"
    assert river_module._acquisition_date("2026-06-27T12:42:43.000Z") == "2026-06-27"
    assert river_module._acquisition_date("2026-06-27") == "2026-06-27"
    assert river_module._acquisition_date(None, "NISAR_L2_PR_GCOV_024_019_D_076_4005_DHDH_A_20260627T124243_20260627T124249_P05023_N_P_J_001") == "2026-06-27"
    assert river_module._acquisition_date("2026-06-27T23:30:00-02:00") == "2026-06-28"
    assert river_module._acquisition_date("not-a-date") is None


def test_discovery_manifest_counts_compact_timestamps_and_preserves_selected_filters(monkeypatch) -> None:
    from types import SimpleNamespace

    records = [
        {"granule_name": f"scene-{index}", "start_time_utc": stamp}
        for index, stamp in enumerate((
            "20260802T124243", "20260802T124243",
            "20260814T232134", "20260826T124242", "20260907T232134", "20260919T124242",
        ))
    ]
    class Product:
        def __init__(self, value):
            self.value = value
        def model_dump(self, mode="json"):
            return self.value

    seen = {}
    def fake_search(request):
        seen.update({
            "polarization": request.main_band_polarization,
            "direction": request.flight_direction,
            "coverage": request.frame_coverage,
            "maturity": request.maturity,
            "max_results": request.max_results,
        })
        return SimpleNamespace(
            products=[Product(row) for row in records],
            query={"collection_short_names": ["NISAR_L2_GCOV_PROVISIONAL_V1"]},
        )

    monkeypatch.setattr(river_module, "search_gcov_catalogue", fake_search)
    request = river_module.CreateRiverShiftJobRequest.model_validate(payload() | {
        "main_band_polarization": "HH+HV",
        "flight_direction": "DESCENDING",
        "frame_coverage": "FULL",
    })

    manifest, names = river_module._discover_manifest(request)

    assert manifest["unique_dates"] == ["2026-08-02", "2026-08-14", "2026-08-26", "2026-09-07", "2026-09-19"]
    assert len(names) == 6
    assert seen == {
        "polarization": "HH+HV",
        "direction": "DESCENDING",
        "coverage": "FULL",
        "maturity": "PROVISIONAL",
        "max_results": 100,
    }
    assert manifest["discovery_filters"] == {
        "main_band_polarization": "HH+HV",
        "flight_direction": "DESCENDING",
        "frame_coverage": "FULL",
    }


def test_dispatch_payload_includes_exact_discovery_filters(monkeypatch) -> None:
    from types import SimpleNamespace

    captured = {}
    class Response:
        status = 204
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(river_module, "urlopen", fake_urlopen)
    settings = SimpleNamespace(
        river_shift_actions_enabled=True,
        river_shift_github_actions_repository="moshiour0/SARGuardian-backend",
        river_shift_github_actions_workflow="river-shift-gcov-process.yml",
        river_shift_github_actions_ref="main",
        river_shift_github_actions_token="server-token",
        github_api_url="https://api.github.com",
        river_shift_public_api_url="https://api.example.test",
    )
    request_snapshot = payload() | {
        "main_band_polarization": "HH+HV",
        "flight_direction": "DESCENDING",
        "frame_coverage": "FULL",
    }

    river_module._dispatch(settings, uuid4(), request_snapshot, ["granule-1"], "f" * 64)

    inputs = captured["body"]["inputs"]
    assert captured["body"]["ref"] == "main"
    assert captured["url"] == (
        "https://api.github.com/repos/moshiour0/SARGuardian-backend"
        "/actions/workflows/river-shift-gcov-process.yml/dispatches"
    )
    assert captured["timeout"] == 20
    assert set(inputs) == {
        "job_id", "aoi_wkt", "start_date", "end_date", "analysis_mode", "event_date", "maturity",
        "main_band_polarization", "flight_direction", "frame_coverage",
        "frequency", "covariance_term", "threshold_method", "threshold_db",
        "granule_names_json", "request_fingerprint", "callback_url",
    }
    assert all(isinstance(value, str) for value in inputs.values())
    assert inputs["job_id"]
    assert inputs["aoi_wkt"] == request_snapshot["aoi_wkt"]
    assert inputs["start_date"] == request_snapshot["start_date"]
    assert inputs["end_date"] == request_snapshot["end_date"]
    assert inputs["analysis_mode"] == "event_based"
    assert inputs["event_date"] == request_snapshot["event_date"]
    assert inputs["maturity"] == "PROVISIONAL"
    assert inputs["frequency"] == "frequencyA"
    assert inputs["covariance_term"] == "HHHH"
    assert inputs["threshold_method"] == "otsu"
    assert inputs["threshold_db"] == ""
    assert inputs["main_band_polarization"] == "HH+HV"
    assert inputs["flight_direction"] == "DESCENDING"
    assert inputs["frame_coverage"] == "FULL"
    assert inputs["granule_names_json"] == '["granule-1"]'
    assert inputs["request_fingerprint"] == "f" * 64
    assert inputs["callback_url"] == "https://api.example.test"





def test_dispatch_http_422_surfaces_only_bounded_public_validation_message(monkeypatch) -> None:
    from types import SimpleNamespace

    settings = SimpleNamespace(
        river_shift_actions_enabled=True,
        river_shift_github_actions_repository="moshiour0/SARGuardian-backend",
        river_shift_github_actions_workflow="river-shift-gcov-process.yml",
        river_shift_github_actions_ref="main",
        river_shift_github_actions_token="credential-that-must-never-appear",
        github_api_url="https://api.github.com",
        river_shift_public_api_url="https://api.example.test",
    )
    submitted_aoi = "POLYGON ((85 27, 85.01 27, 85.01 27.01, 85 27.01, 85 27))"
    request_snapshot = payload() | {
        "aoi_wkt": submitted_aoi,
        "main_band_polarization": None,
        "flight_direction": None,
        "frame_coverage": "ALL",
    }
    response_body = json.dumps({
        "message": "Unexpected inputs provided:\n  threshold_db is not valid for this workflow"
    }).encode("utf-8")

    def reject_dispatch(request, timeout):
        assert "credential-that-must-never-appear" in request.get_header("Authorization")
        assert request.data and submitted_aoi.encode("utf-8") in request.data
        raise HTTPError(
            request.full_url,
            422,
            "Unprocessable Entity",
            {},
            BytesIO(response_body),
        )

    monkeypatch.setattr(river_module, "urlopen", reject_dispatch)
    with pytest.raises(RuntimeError) as captured:
        river_module._dispatch(settings, uuid4(), request_snapshot, ["granule-1"], "f" * 64)

    message = str(captured.value)
    assert "HTTP 422" in message
    assert "Unexpected inputs provided: threshold_db is not valid for this workflow" in message
    assert "\n" not in message
    assert "credential-that-must-never-appear" not in message
    assert submitted_aoi not in message
    assert response_body.decode("utf-8") not in message
    assert len(message) < 400


def test_dispatch_http_422_without_json_message_remains_sanitized(monkeypatch) -> None:
    from types import SimpleNamespace

    settings = SimpleNamespace(
        river_shift_actions_enabled=True,
        river_shift_github_actions_repository="moshiour0/SARGuardian-backend",
        river_shift_github_actions_workflow="river-shift-gcov-process.yml",
        river_shift_github_actions_ref="main",
        river_shift_github_actions_token="server-token",
        github_api_url="https://api.github.com",
        river_shift_public_api_url="https://api.example.test",
    )

    def reject_dispatch(request, timeout):
        raise HTTPError(
            request.full_url, 422, "Unprocessable Entity", {},
            BytesIO(b"not-json: server-token and submitted AOI must not be copied"),
        )

    monkeypatch.setattr(river_module, "urlopen", reject_dispatch)
    with pytest.raises(RuntimeError) as captured:
        river_module._dispatch(
            settings, uuid4(), payload() | {"main_band_polarization": None, "flight_direction": None},
            ["granule-1"], "f" * 64,
        )

    assert str(captured.value) == "GitHub Actions rejected RiverShift dispatch (HTTP 422)."
    assert "server-token" not in str(captured.value)
    assert "submitted AOI" not in str(captured.value)


def test_dispatch_failure_response_and_persisted_job_keep_safe_github_reason(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)

    def fail_dispatch(*_args):
        raise RuntimeError(
            "GitHub Actions rejected RiverShift dispatch (HTTP 422): Unexpected inputs provided: threshold_db"
        )

    monkeypatch.setattr(river_module, "_dispatch", fail_dispatch)
    response = api.post("/api/river-shift/jobs", json=payload())

    assert response.status_code == 503
    assert "HTTP 422" in response.json()["detail"]
    assert "Unexpected inputs provided: threshold_db" in response.json()["detail"]
    assert len(store.rows) == 1
    job = next(iter(store.rows.values()))
    assert job["state"] == river_module.JobState.FAILED.value
    assert job["stage"] == "dispatch_failed"
    assert "Unexpected inputs provided: threshold_db" in job["error_message"]
    assert "server-token" not in job["error_message"]

def test_dispatch_transition_failure_does_not_leave_a_stuck_queued_job(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    original_update = store.update_river_shift_job

    def fail_transition(job_id, values, *, expected_state=None, expected_sequence=None):
        if values.get("state") == river_module.JobState.DISPATCHING.value:
            raise river_module.PersistenceError("simulated dispatch-state persistence failure")
        return original_update(job_id, values, expected_state=expected_state, expected_sequence=expected_sequence)

    monkeypatch.setattr(store, "update_river_shift_job", fail_transition)
    response = api.post("/api/river-shift/jobs", json=payload())

    assert response.status_code == 503
    assert len(store.rows) == 1
    job = next(iter(store.rows.values()))
    assert job["state"] == river_module.JobState.FAILED.value
    assert job["stage"] == "dispatch_failed"
    assert job["error_code"] == "RIVERSHIFT_DISPATCH_FAILED"



def test_river_shift_requires_one_strictly_pre_event_and_three_strictly_post_event_dates(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    monkeypatch.setattr(river_module, "_discover_manifest", lambda _payload: ({
        "unique_dates": ["2026-08-01", "2026-08-13", "2026-08-20", "2026-08-25", "2026-09-06"],
        "products": [{"granule_name": f"scene-{index}"} for index in range(5)],
    }, [f"scene-{index}" for index in range(5)]))

    response = api.post("/api/river-shift/jobs", json=payload())

    assert response.status_code == 422
    assert "strictly before" in response.json()["detail"]
    assert store.rows == {}


def test_general_river_change_scan_needs_no_event_date_or_event_bracket(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    dates = ["2026-08-25", "2026-09-01", "2026-09-08", "2026-09-15"]
    monkeypatch.setattr(river_module, "_discover_manifest", lambda _payload: ({
        "unique_dates": dates,
        "products": [{"granule_name": f"general-scene-{index}"} for index in range(4)],
    }, [f"general-scene-{index}" for index in range(4)]))

    request = payload() | {
        "analysis_mode": "general_scan",
        "event_date": None,
        "idempotency_key": "general-river-scan-0001",
    }
    response = api.post("/api/river-shift/jobs", json=request)

    assert response.status_code == 200, response.text
    job = response.json()
    assert job["analysis_mode"] == "general_scan"
    assert job["event_date"] is None
    assert job["state"] == "dispatching"
    assert store.rows[job["id"]]["event_date"] is None


def test_river_shift_requires_four_observation_dates_before_job_creation(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    monkeypatch.setattr(river_module, "_discover_manifest", lambda _payload: ({
        "unique_dates": ["2026-08-01", "2026-08-13", "2026-08-25"],
        "products": [{"granule_name": "one"}],
    }, ["one"]))
    response = api.post("/api/river-shift/jobs", json=payload())
    assert response.status_code == 422
    assert store.rows == {}


def test_signed_worker_callbacks_advance_only_the_river_shift_job(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    created = api.post("/api/river-shift/jobs", json=payload()).json()
    job_id = created["id"]
    fingerprint = store.rows[job_id]["request_fingerprint"]

    def callback(value: dict):
        body = json.dumps(value, separators=(",", ":")).encode()
        return api.post(
            f"/api/river-shift/jobs/{job_id}/callback",
            content=body,
            headers={"Content-Type": "application/json", "X-SARGuardian-Signature": sign_callback(body)},
        )

    running = callback({
        "job_id": job_id,
        "request_fingerprint": fingerprint,
        "state": "running",
        "sequence": 1,
        "stage": "worker_started",
        "github_run_id": "123456789",
        "github_run_url": "https://github.com/moshiour0/SARGuardian-backend/actions/runs/123456789",
    })
    assert running.status_code == 200, running.text
    assert running.json()["job_status"] == "running"

    result_bytes = b"verified RiverShift bytes"
    artifact = {
        "name": "river_change_candidates_preview.geojson",
        "path": "outputs/map/river_change_candidates_preview.geojson",
        "bytes": len(result_bytes),
        "sha256": hashlib.sha256(result_bytes).hexdigest(),
        "drive_file_id": "abcdefghijk",
        "remote_verification": {"status": "PASS"},
    }
    succeeded = callback({
        "job_id": job_id,
        "request_fingerprint": fingerprint,
        "state": "succeeded",
        "sequence": 2,
        "stage": "completed",
        "github_run_id": "123456789",
        "github_run_url": "https://github.com/moshiour0/SARGuardian-backend/actions/runs/123456789",
        "result_summary": {
            "schema_version": 1,
            "processing_status": "PASS",
            "release_status": "PROVISIONAL",
            "independent_validation_status": "PENDING",
        },
        "artifact_manifest": [artifact],
    })
    assert succeeded.status_code == 200, succeeded.text
    assert succeeded.json()["job_status"] == "succeeded"
    assert store.rows[job_id]["callback_sequence"] == 2

    stale = callback({
        "job_id": job_id,
        "request_fingerprint": fingerprint,
        "state": "running",
        "sequence": 1,
        "stage": "worker_started",
        "github_run_id": "123456789",
    })
    assert stale.status_code == 200
    assert store.rows[job_id]["state"] == "succeeded"


def test_river_shift_callback_rejects_invalid_signature_and_unverified_success(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    created = api.post("/api/river-shift/jobs", json=payload()).json()
    job_id = created["id"]
    fingerprint = store.rows[job_id]["request_fingerprint"]
    invalid = api.post(
        f"/api/river-shift/jobs/{job_id}/callback",
        json={"job_id": job_id},
        headers={"X-SARGuardian-Signature": "sha256=invalid"},
    )
    assert invalid.status_code == 401

    body = json.dumps({
        "job_id": job_id,
        "request_fingerprint": fingerprint,
        "state": "succeeded",
        "sequence": 1,
        "stage": "completed",
        "github_run_id": "123456789",
        "result_summary": {
            "schema_version": 1,
            "processing_status": "PASS",
            "release_status": "VERIFIED",
            "independent_validation_status": "PENDING",
        },
        "artifact_manifest": [],
    }, separators=(",", ":")).encode()
    response = api.post(
        f"/api/river-shift/jobs/{job_id}/callback",
        content=body,
        headers={"Content-Type": "application/json", "X-SARGuardian-Signature": sign_callback(body)},
    )
    assert response.status_code == 409
    assert store.rows[job_id]["state"] == "dispatching"


def test_river_shift_artifact_download_is_owner_scoped_and_checksum_checked(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    created = api.post("/api/river-shift/jobs", json=payload()).json()
    job_id = created["id"]
    # Exercise a response larger than the Vercel buffered 4.5 MB payload ceiling.
    result_bytes = b"x" * (5 * 1024 * 1024 + 1)
    store.rows[job_id].update({
        "state": "succeeded",
        "artifact_manifest": [{
            "name": "example.tif",
            "path": "outputs/example.tif",
            "bytes": len(result_bytes),
            "sha256": hashlib.sha256(result_bytes).hexdigest(),
            "drive_file_id": "abcdefghijk",
            "remote_verification": {"status": "PASS"},
        }],
    })
    downloaded_paths = []

    def write_valid_result(_file_id, destination, *, max_bytes):
        downloaded_paths.append(destination)
        assert max_bytes == len(result_bytes)
        destination.write_bytes(result_bytes)
        return {"bytes": len(result_bytes), "sha256": hashlib.sha256(result_bytes).hexdigest()}

    monkeypatch.setattr(river_module, "download_private_result_to_path", write_valid_result)
    response = api.get(f"/api/river-shift/jobs/{job_id}/artifacts/0")
    assert response.status_code == 200
    assert response.content == result_bytes
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-length"] == str(len(result_bytes))
    assert response.headers["x-content-sha256"] == hashlib.sha256(result_bytes).hexdigest()
    assert downloaded_paths and not downloaded_paths[0].exists()

    def write_corrupt_result(_file_id, destination, *, max_bytes):
        destination.write_bytes(b"oops")
        return {"bytes": 4, "sha256": hashlib.sha256(b"oops").hexdigest()}

    monkeypatch.setattr(river_module, "download_private_result_to_path", write_corrupt_result)
    corrupted = api.get(f"/api/river-shift/jobs/{job_id}/artifacts/0")
    assert corrupted.status_code == 409


def test_list_river_shift_jobs_restores_only_the_authenticated_users_recent_jobs(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    first = api.post("/api/river-shift/jobs", json=payload()).json()
    store.rows[first["id"]]["state"] = "succeeded"
    second_payload = payload() | {"idempotency_key": "river-shift-request-0002"}
    second = api.post("/api/river-shift/jobs", json=second_payload).json()
    monkeypatch.setattr(river_module, "_refresh_workflow_state", lambda _store, record: record)

    listed = api.get("/api/river-shift/jobs?limit=10")
    assert listed.status_code == 200, listed.text
    assert {row["id"] for row in listed.json()} == {first["id"], second["id"]}

    app.dependency_overrides[get_current_user] = lambda: {"uid": "another-user"}
    other_account = api.get("/api/river-shift/jobs")
    assert other_account.status_code == 200
    assert other_account.json() == []


def test_list_river_shift_jobs_enforces_bounded_limit(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    assert api.get("/api/river-shift/jobs?limit=0").status_code == 422
    assert api.get("/api/river-shift/jobs?limit=101").status_code == 422


def test_river_shift_allows_only_one_active_job_per_account_but_keeps_idempotent_replay(monkeypatch) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)

    first = api.post("/api/river-shift/jobs", json=payload())
    duplicate = api.post("/api/river-shift/jobs", json=payload())
    competing = api.post(
        "/api/river-shift/jobs",
        json=payload() | {"idempotency_key": "river-shift-request-0002"},
    )

    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]
    assert competing.status_code == 409
    assert "already has an active RiverShift job" in competing.json()["detail"]
    assert first.json()["id"] in competing.json()["detail"]
    assert len(store.rows) == 1


def test_database_active_job_conflict_is_returned_as_http_409(monkeypatch) -> None:
    class ConcurrentConflictStore(RiverShiftStore):
        def create_river_shift_job(self, values):
            raise river_module.PersistenceConflictError("concurrent active job insert")

    store = ConcurrentConflictStore()
    api = configure(monkeypatch, store)
    response = api.post("/api/river-shift/jobs", json=payload())
    assert response.status_code == 409
    assert "already has an active RiverShift job" in response.json()["detail"]


def test_river_shift_migration_enforces_one_active_job_per_owner() -> None:
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[1]
        / "supabase"
        / "migrations"
        / "20261103100000_river_shift_jobs.sql"
    ).read_text(encoding="utf-8")
    assert "create unique index river_shift_jobs_one_active_per_owner_idx" in migration.lower()
    assert "where state in ('queued', 'dispatching', 'running')" in migration.lower()
    assert "to_jsonb(new) - 'updated_at'" in migration.lower()
    assert "terminal rivershift jobs are immutable" in migration.lower()

def test_river_shift_artifact_download_logs_safe_drive_failure_diagnostics(monkeypatch, caplog) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    created = api.post("/api/river-shift/jobs", json=payload()).json()
    job_id = created["id"]
    store.rows[job_id].update({
        "state": "succeeded",
        "artifact_manifest": [{
            "name": "river_change_candidates_preview.geojson",
            "path": "outputs/map/river_change_candidates_preview.geojson",
            "bytes": 12,
            "sha256": "a" * 64,
            "drive_file_id": "private-file-id-123",
        }],
    })

    def fail_private_download(*_args, **_kwargs):
        raise river_module.DriveUploadError(
            "Could not retrieve the private result artifact."
        ) from HTTPError(
            "https://www.googleapis.com/drive/v3/files/private-file-id-123?alt=media",
            403,
            "Forbidden",
            {},
            BytesIO(b"body text must never enter the application log"),
        )

    monkeypatch.setattr(river_module, "download_private_result_to_path", fail_private_download)
    with caplog.at_level("WARNING", logger=river_module.__name__):
        response = api.get(f"/api/river-shift/jobs/{job_id}/artifacts/0")

    assert response.status_code == 503
    assert "upstream_http_status=403" in caplog.text
    assert "artifact_name=river_change_candidates_preview.geojson" in caplog.text
    assert "private-file-id-123" not in caplog.text
    assert "body text must never enter" not in caplog.text

def test_river_shift_artifact_download_logs_google_oauth_error_code_without_response_details(monkeypatch, caplog) -> None:
    store = RiverShiftStore()
    api = configure(monkeypatch, store)
    created = api.post("/api/river-shift/jobs", json=payload()).json()
    job_id = created["id"]
    store.rows[job_id].update({
        "state": "succeeded",
        "artifact_manifest": [{
            "name": "river_shift_timeseries_preview.json",
            "path": "outputs/time-series/river_shift_timeseries_preview.json",
            "bytes": 12,
            "sha256": "b" * 64,
            "drive_file_id": "private-file-id-456",
        }],
    })

    class OAuthResponse:
        status_code = 400

        @staticmethod
        def json():
            return {"error": "invalid_grant", "error_description": "do-not-log-this-sensitive-detail"}

    class OAuthRefreshError(RuntimeError):
        response = OAuthResponse()

    def fail_private_download(*_args, **_kwargs):
        raise river_module.DriveUploadError(
            "Could not authenticate to Google Drive result storage."
        ) from OAuthRefreshError("OAuth token refresh failed")

    monkeypatch.setattr(river_module, "download_private_result_to_path", fail_private_download)
    with caplog.at_level("WARNING", logger=river_module.__name__):
        response = api.get(f"/api/river-shift/jobs/{job_id}/artifacts/0")

    assert response.status_code == 503
    assert "upstream_http_status=400" in caplog.text
    assert "upstream_error_code=invalid_grant" in caplog.text
    assert "do-not-log-this-sensitive-detail" not in caplog.text
    assert "private-file-id-456" not in caplog.text
