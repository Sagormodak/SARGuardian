#!/usr/bin/env python3
"""Select a successful, artifact-backed full-source baseline for science extensions."""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from typing import Any

from tools.resolve_resume_run import API_ROOT, SCIENCE_COMMIT, WORKFLOW_ID, WORKFLOW_PATH, api_json, get_run_manifest

REPOSITORY = "moshiour0/SARGuardian-backend"
DEFAULT_BRANCH = "main"


def list_candidates(repo: str, branch: str, token: str) -> list[dict[str, Any]]:
    """Read a bounded, newest-first window of manual runs for the batch workflow."""
    found: list[dict[str, Any]] = []
    for page in range(1, 6):
        query = urllib.parse.urlencode({
            "branch": branch, "event": "workflow_dispatch", "per_page": 100, "page": page,
        })
        payload = api_json(
            f"{API_ROOT}/repos/{repo}/actions/workflows/{WORKFLOW_ID}/runs?{query}", token
        )
        batch = payload.get("workflow_runs")
        if not isinstance(batch, list) or not batch:
            break
        found.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
    return sorted(found, key=lambda item: str(item.get("created_at", "")), reverse=True)


def validate_run(repo: str, run_id: str, token: str, branch: str) -> dict[str, Any]:
    if not run_id.isdigit():
        raise ValueError("SOURCE_RUN_ID_MUST_BE_NUMERIC")
    info = api_json(f"{API_ROOT}/repos/{repo}/actions/runs/{run_id}", token)
    if info.get("workflow_id") != WORKFLOW_ID or info.get("path") != WORKFLOW_PATH:
        raise ValueError("SOURCE_RUN_IS_NOT_SARGUARDIAN_STREAMING_BATCH")
    if info.get("head_branch") != branch:
        raise ValueError("SOURCE_RUN_BRANCH_MISMATCH")
    if info.get("event") != "workflow_dispatch":
        raise ValueError("SOURCE_RUN_MUST_BE_MANUALLY_DISPATCHED")
    if info.get("status") != "completed" or info.get("conclusion") != "success":
        raise ValueError("SOURCE_RUN_NOT_COMPLETED_SUCCESSFULLY")
    return info


def has_bundle_artifact(repo: str, run_id: str, token: str) -> bool:
    """Require a full 33-product compatible manifest plus its final report bundle.

    The workflow also publishes successful validation-pilot artifacts. They
    are deliberately ineligible as a source for a scientific extension run.
    """
    manifest, has_checkpoints = get_run_manifest(repo, run_id, token)
    if not manifest or not has_checkpoints:
        return False
    products = manifest.get("products")
    if (
        manifest.get("run_profile") != "full-source-baseline"
        or manifest.get("aoi") != "source"
        or manifest.get("science_commit") != SCIENCE_COMMIT
        or manifest.get("retention_profile") not in {"derived-only", "full-lossless"}
        or not str(manifest.get("run_id", "")).startswith(run_id + "-")
        or not isinstance(products, list)
        or len(products) != 33
    ):
        return False
    counts = {
        family: sum(
            1 for product in products
            if isinstance(product, dict) and product.get("product_type") == family
        )
        for family in ("GUNW", "GOFF")
    }
    if counts != {"GUNW": 15, "GOFF": 18}:
        return False

    payload = api_json(
        f"{API_ROOT}/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", token
    )
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return False
    required_prefix = f"sarguardian-streaming-run-{run_id}-"
    return any(
        isinstance(item, dict)
        and not item.get("expired")
        and str(item.get("name", "")).startswith(required_prefix)
        for item in artifacts
    )

def resolve(requested: str, repo: str, branch: str, token: str) -> tuple[str, str, int]:
    requested = (requested or "").strip().lower()
    if requested:
        if requested == "none":
            raise ValueError("SOURCE_RUN_ID_CANNOT_BE_NONE")
        validate_run(repo, requested, token, branch)
        if not has_bundle_artifact(repo, requested, token):
            raise ValueError("SOURCE_RUN_BUNDLE_ARTIFACT_MISSING_OR_EXPIRED")
        return requested, "explicit-successful-baseline", 1
    if not token:
        raise ValueError("GITHUB_TOKEN_REQUIRED_FOR_SOURCE_RUN_DISCOVERY")

    inspected = 0
    for candidate in list_candidates(repo, branch, token):
        run_id = str(candidate.get("id", ""))
        inspected += 1
        if (
            candidate.get("workflow_id") != WORKFLOW_ID
            or candidate.get("path") != WORKFLOW_PATH
            or candidate.get("head_branch") != branch
            or candidate.get("event") != "workflow_dispatch"
            or candidate.get("status") != "completed"
            or candidate.get("conclusion") != "success"
            or not run_id.isdigit()
        ):
            continue
        if has_bundle_artifact(repo, run_id, token):
            return run_id, "auto-latest-successful-with-bundle", inspected
    raise ValueError("NO_SUCCESSFUL_FULL_BASELINE_WITH_UNEXPIRED_BUNDLE_FOUND")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requested-run-id", default="")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    args = parser.parse_args()
    try:
        run_id, mode, inspected = resolve(args.requested_run_id, args.repo, args.branch, args.token)
    except Exception as exc:
        print(f"ERROR=SCIENCE_SOURCE_RUN_RESOLUTION_FAILED type={type(exc).__name__} detail={str(exc)[:240]}")
        return 2

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"run_id={run_id}\n")
            stream.write(f"mode={mode}\n")
    print(f"SCIENCE_SOURCE_SELECTION_MODE={mode}")
    print(f"SCIENCE_SOURCE_RUN_ID={run_id}")
    print(f"SUCCESSFUL_RUN_CANDIDATES_INSPECTED={inspected}")
    print("SECRET_VALUES_PRINTED=no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
