"""Regression checks for the user-facing dynamic-AOI workflow route."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / ".github" / "workflows" / "sarguardian-aoi-wkt-dispatcher.yml"


def test_aoi_dispatcher_uses_merged_main_workflow() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*uses:\s*moshiour0/SARGuardian-backend/"
        r"\.github/workflows/sarguardian-aoi-wkt-dashboard\.yml@([^\s]+)\s*$",
        text,
        re.MULTILINE,
    )
    assert match, "dispatcher must call the reusable AOI dashboard workflow"
    assert match.group(1) == "main", (
        "dispatcher must call the merged main workflow; a feature-branch ref can "
        "silently omit the latest dashboard and release fixes"
    )
