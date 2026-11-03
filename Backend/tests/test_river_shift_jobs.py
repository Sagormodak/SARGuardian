from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import uuid4

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
        "unique_dates": ["2026-08-01", "2026-08-13", "2026-08-25", "2026-09-06"],
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
    assert river_module._acquisition_date("2026-06-27T23:30:00-02:00") == "2026-06-28"\n    assert river_module._acquisition_date("not-a-date") is None


def test_discovery_manifest_counts_compact_timestamps_and_preserves_selected_filters(monkeypatch) -> None:
    from types import SimpleNamespace

    records = [
        {"granule_name": f"scene-{index}", "start_time_utc": stamp}
        for index, stamp in enumerate((
            "20260802T124243", "20260802T124243",
            "20260814T232134", "20260826T124242", "20260907T232134",
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

    assert manifest["unique_dates"] == ["2026-08-02", "2026-08-14", "2026-08-26", "2026-09-07"]
    assert len(names) == 5
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
    assert inputs["main_band_polarization"] == "HH+HV"
    assert inputs["flight_direction"] == "DESCENDING"
    assert inputs["frame_coverage"] == "FULL"
    assert inputs["granule_names_json"] == '["granule-1"]'



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
