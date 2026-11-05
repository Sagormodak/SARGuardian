import pytest

from tools import resolve_science_source_run as resolver


def test_explicit_source_run_requires_verified_bundle(monkeypatch):
    calls = []
    monkeypatch.setattr(
        resolver,
        "validate_run",
        lambda repo, run_id, token, branch: calls.append(("validate", run_id)),
    )
    monkeypatch.setattr(
        resolver,
        "has_bundle_artifact",
        lambda repo, run_id, token: run_id == "39917595212",
    )
    assert resolver.resolve("39917595212", "moshiour0/SARGuardian-backend", "main", "token") == (
        "39917595212",
        "explicit-successful-baseline",
        1,
    )
    assert calls == [("validate", "39917595212")]
    with pytest.raises(ValueError, match="SOURCE_RUN_BUNDLE_ARTIFACT_MISSING_OR_EXPIRED"):
        resolver.resolve("12345", "moshiour0/SARGuardian-backend", "main", "token")


def test_auto_source_run_skips_runs_without_an_unexpired_bundle(monkeypatch):
    candidates = [
        {
            "id": 200,
            "workflow_id": resolver.WORKFLOW_ID,
            "path": resolver.WORKFLOW_PATH,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-23T10:00:00Z",
        },
        {
            "id": 199,
            "workflow_id": resolver.WORKFLOW_ID,
            "path": resolver.WORKFLOW_PATH,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-10-23T09:00:00Z",
        },
    ]
    monkeypatch.setattr(resolver, "list_candidates", lambda repo, branch, token: candidates)
    monkeypatch.setattr(
        resolver,
        "has_bundle_artifact",
        lambda repo, run_id, token: str(run_id) == "199",
    )
    assert resolver.resolve("", "moshiour0/SARGuardian-backend", "main", "token") == (
        "199",
        "auto-latest-successful-with-bundle",
        2,
    )


def test_auto_source_run_requires_token():
    with pytest.raises(ValueError, match="GITHUB_TOKEN_REQUIRED_FOR_SOURCE_RUN_DISCOVERY"):
        resolver.resolve("", "moshiour0/SARGuardian-backend", "main", "")
