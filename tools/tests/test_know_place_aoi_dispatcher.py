from __future__ import annotations

from pathlib import Path


def test_default_branch_dispatcher_pins_validated_backend_two_polygon_workflow() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_path = repository_root / ".github" / "workflows" / "know-place-aoi-dispatcher.yml"
    text = workflow_path.read_text(encoding="utf-8")

    science_sha = "39a6dff3585db03c51a666ad3392362994f51e27"
    assert "workflow_dispatch:" in text
    assert "run-name: Known Place Analysis ${{ inputs.request_id }}" in text
    assert f".github/workflows/know-place-aoi-analysis.yml@{science_sha}" in text
    assert f'backend_science_ref: "{science_sha}"' in text
    assert "secrets: inherit" in text
    assert "consent_marker: ${{ inputs.consent_marker }}" in text
    assert "execute_downloads: ${{ inputs.execute_downloads }}" in text
    assert 'default: false\n        type: boolean' in text


def test_dispatcher_forwards_independent_outer_measurement_and_reference_geometry() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    text = (repository_root / ".github" / "workflows" / "know-place-aoi-dispatcher.yml").read_text(encoding="utf-8")

    for field in (
        "aoi_wkt",
        "scope_aoi_wkt",
        "reference_wkt",
        "start_date",
        "end_date",
        "hazard_mode",
        "analysis_mode",
        "polarization",
        "track",
        "direction",
        "coherence_neighbours",
        "allowed_release_ids",
        "candidate_context_json",
    ):
        assert f"      {field}: ${{{{ inputs.{field} }}}}" in text



def test_author_exact_paper_dispatcher_uses_backend_scoped_entry_and_immutable_science_pin() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow_path = repository_root / ".github" / "workflows" / "know-place-paper-reproduction-dispatcher.yml"
    text = workflow_path.read_text(encoding="utf-8")

    reusable_workflow_sha = "d847b0461a2fec1bdf2abcce0a6b1d2f9dddabc9"
    science_sha = "b825df798ea4cb9874aa10dd01174d2a8ef73cba"
    reusable_path = ".github/workflows/know-place-author-exact-replay.yml"
    assert "workflow_dispatch:" in text
    assert "run-name: Known Place Paper Reproduction ${{ inputs.request_id }}" in text
    assert f"uses: moshiour0/SARGuardian-backend/{reusable_path}@{reusable_workflow_sha}" in text
    assert f'backend_code_ref: "{science_sha}"' in text
    assert "consent_marker: ${{ inputs.consent_marker }}" in text
    assert "bridge_authorized: false" in text
    assert "secrets:" in text
    assert "SARGuardian_Dynamic" not in text
