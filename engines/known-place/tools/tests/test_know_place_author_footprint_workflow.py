from pathlib import Path


def test_footprint_workflow_uses_source_run_config_for_relative_raw_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "know-place-author-exact-replay.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Run full-footprint screen and compare archive golden outputs")
    end = workflow.index("      - name: Remove temporary public author archive and terrain", start)
    step = workflow[start:end]

    assert '--config "$RUN_ROOT/source-run/know-place-inputs.json"' in step
    assert '--source-manifest "$RUN_ROOT/source-run/author-exact-source-manifest.json"' in step
    assert '--config "$RUN_ROOT/know-place-inputs.json"' not in step
    assert '--config "$DERIVED_ROOT/know-place-inputs.json"' not in step
    assert '--source-manifest "$RUN_ROOT/author-exact-source-manifest.json"' not in step
    assert '--source-manifest "$DERIVED_ROOT/author-exact-source-manifest.json"' not in step


def test_footprint_audit_is_not_skipped_when_site_p2_parity_is_incomplete() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "know-place-author-exact-replay.yml").read_text(
        encoding="utf-8"
    )
    assert "id: footprint_inputs" in workflow
    assert "if: always() && steps.credentials.outputs.secrets_ready == 'true' && steps.author_archive.outputs.archive_ready == 'true'" in workflow
    assert 'echo "present=true" >> "$GITHUB_OUTPUT"' in workflow
    assert "steps.footprint_inputs.outputs.present == 'true'" in workflow
    assert "if: steps.analysis.outcome == 'success'" not in workflow
    assert '--terrain-root "$AUTHOR_TERRAIN_ROOT"' in workflow
