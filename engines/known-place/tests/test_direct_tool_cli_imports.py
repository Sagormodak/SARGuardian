from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _isolated_env() -> dict[str, str]:
    env = os.environ.copy()
    # Do not accidentally make the repository importable through pytest's
    # PYTHONPATH; the workflow invokes each script directly from another cwd.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("GITHUB_OUTPUT", None)
    return env


def test_resume_resolver_cli_imports_from_an_unrelated_working_directory(tmp_path: Path):
    script = ROOT / "tools" / "resolve_resume_run.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--science-root", str(tmp_path / "science-source"),
            "--run-profile", "validation-pilot",
            "--start-date", "2025-01-01",
            "--end-date", "2026-12-31",
            "--retention-profile", "derived-only",
            "--requested-run-id", "none",
        ],
        cwd=tmp_path,
        env=_isolated_env(),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "RESUME_SELECTION_MODE=disabled-by-user" in result.stdout


def test_aggregator_cli_imports_its_pinned_suite_when_called_directly(tmp_path: Path):
    script = ROOT / "tools" / "aggregate_streamed_outputs.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=_isolated_env(),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "Aggregate single-granule SARGuardian reader outputs" in result.stdout
