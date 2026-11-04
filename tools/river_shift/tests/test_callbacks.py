import json
import uuid

import pytest
import requests

import process_gcov_job
from process_gcov_job import JobCallbacks, WorkerFailure


def _response(status_code: int):
    class FakeResponse:
        def __init__(self, status):
            self.status_code = status
            self.url = "https://api.example.test/api/river-shift/callback"

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(
                    f"HTTP {self.status_code}",
                    response=self,
                )

    return FakeResponse(status_code)


def _callbacks(monkeypatch):
    monkeypatch.setenv("RIVERSHIFT_CALLBACK_SECRET", "callback-test-secret")
    monkeypatch.setenv("GITHUB_RUN_ID", "41768024393")
    monkeypatch.setenv("GITHUB_REPOSITORY", "moshiour0/SARGuardian-backend")
    return JobCallbacks(
        str(uuid.UUID("b60c50d4-1013-4605-a492-94a883e28973")),
        "a" * 64,
        "https://sarguardian-backend-api.vercel.app",
    )


def test_signed_callback_retries_transient_http_failure_with_same_signed_payload(monkeypatch):
    callbacks = _callbacks(monkeypatch)
    attempts = []
    delays = []

    def fake_post(url, **kwargs):
        attempts.append((url, kwargs))
        return _response(503 if len(attempts) == 1 else 200)

    monkeypatch.setattr(process_gcov_job.requests, "post", fake_post)
    monkeypatch.setattr(process_gcov_job.time, "sleep", delays.append)

    callbacks.send("running", "result_package_assembly")

    assert len(attempts) == 2
    assert attempts[0][0] == attempts[1][0]
    assert attempts[0][1]["data"] == attempts[1][1]["data"]
    assert attempts[0][1]["headers"] == attempts[1][1]["headers"]
    payload = json.loads(attempts[0][1]["data"])
    assert payload["sequence"] == 1
    assert payload["stage"] == "result_package_assembly"
    assert delays == [1.0]
    assert callbacks.sequence == 1


def test_signed_callback_does_not_retry_permanent_client_rejection(monkeypatch):
    callbacks = _callbacks(monkeypatch)
    attempts = []
    delays = []

    def fake_post(_url, **_kwargs):
        attempts.append(True)
        return _response(401)

    monkeypatch.setattr(process_gcov_job.requests, "post", fake_post)
    monkeypatch.setattr(process_gcov_job.time, "sleep", delays.append)

    with pytest.raises(WorkerFailure, match="CALLBACK_REJECTED"):
        callbacks.send("running", "result_package_assembly")

    assert len(attempts) == 1
    assert delays == []
    assert callbacks.sequence == 0


def test_signed_callback_bounds_retries_for_origin_timeout(monkeypatch):
    callbacks = _callbacks(monkeypatch)
    attempts = []
    delays = []

    def fake_post(_url, **_kwargs):
        attempts.append(True)
        return _response(522)

    monkeypatch.setattr(process_gcov_job.requests, "post", fake_post)
    monkeypatch.setattr(process_gcov_job.time, "sleep", delays.append)

    with pytest.raises(WorkerFailure, match="CALLBACK_REJECTED"):
        callbacks.send("running", "result_package_assembly")

    assert len(attempts) == 4
    assert delays == [1.0, 2.0, 4.0]
    assert callbacks.sequence == 0
