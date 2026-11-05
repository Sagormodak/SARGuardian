from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sarguardian-extended-science.yml"


def test_extended_science_workflow_keeps_github_expressions_live():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert chr(92) + "$" + "{{" not in text
    assert ("$" + "{{ secrets.GOOGLE_DRIVE_OAUTH_CLIENT_JSON }}") in text
    assert ("$" + "{{ github.token }}") in text
    assert ("$" + "{{ inputs.source_run_id || '' }}") in text
    assert ("$" + "{{ steps.source.outputs.run_id }}") in text
    assert ("$" + "{{ github.run_id }}") in text
    assert "workflow_dispatch:" in text
    assert "permissions:\n  contents: read\n  actions: read" in text


def test_extended_science_is_pinned_and_uses_only_derived_artifact_bundle():
    text = WORKFLOW.read_text(encoding="utf-8")
    script = (ROOT / "tools" / "run_extended_science.py").read_text(encoding="utf-8")
    assert "ref: ab547ecc82bcc4d6ccef545a59852536c2beacc6" in text
    assert "Run the extended science workflow (never extract raw HDF5)" in text
    assert "raw_hdf5_extracted" in script
    assert "RAW_HDF5_REFUSED_IN_EXTENSION_PACKAGE" in script
    assert "source-run-manifest.json" in script
    assert "source-batch-equivalence-report.json" in script
