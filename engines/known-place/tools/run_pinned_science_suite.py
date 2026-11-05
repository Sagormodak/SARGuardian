#!/usr/bin/env python3
"""Run the remaining documented SARGuardian science experiments from the pinned src/ tree.

This runner deliberately does not reimplement scientific formulas. It calls the
unchanged scripts from the checked-out SARGuardian source commit and records the
exact argv, attempts, stdout logs, outputs, and reference-output checks.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PINNED_SCIENCE_COMMIT = "ab547ecc82bcc4d6ccef545a59852536c2beacc6"
NETWORK_RETRY = re.compile(
    r"\b(?:429|500|502|503|504)\b|timed?\s*out|connection reset|"
    r"connection aborted|temporary failure in name resolution|"
    r"temporarily unavailable|remote end closed|urlopen error|"
    r"sslerror|remoteDisconnected",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_plan() -> list[dict[str, Any]]:
    """Reproduce the documented supplementary Results 1, 2, 3 and 6."""
    py = sys.executable
    return [
        {
            "name": "result1_detectability_noise_gates",
            "argv": [py, "src/detectability.py", "--sweep", "--precursor", "5", "10", "20", "40",
                     "--csv", "outputs/detectability.csv"],
            "outputs": ["outputs/detectability.csv"], "network": False,
        },
        {
            "name": "result1_detectability_legacy_fixed_gate",
            "argv": [py, "src/detectability.py", "--sweep", "--precursor", "5", "10", "20", "40", "--gate", "fixed",
                     "--csv", "outputs/detectability_fixed_gate.csv"],
            "outputs": ["outputs/detectability_fixed_gate.csv"], "network": False,
        },
        {
            "name": "result1_detectability_blatten_phase",
            "argv": [py, "src/detectability.py", "--sweep", "--blatten", "--noise", "5",
                     "--wavelength", "0.2384", "--csv", "outputs/detectability_blatten_phase.csv"],
            "outputs": ["outputs/detectability_blatten_phase.csv"], "network": False,
        },
        {
            "name": "result1_detectability_blatten_offsets",
            "argv": [py, "src/detectability.py", "--sweep", "--blatten", "--noise", "300",
                     "--csv", "outputs/detectability_blatten_offsets.csv"],
            "outputs": ["outputs/detectability_blatten_offsets.csv"], "network": False,
        },
        {
            "name": "result2_track_sensitivity_and_dem_stencil_sweep",
            "argv": [py, "src/geometry_merge.py", "--sensitivity", "--lat", "28.2877", "--lon", "85.5281",
                     "--stencil-sweep", "--csv", "outputs/geometry_sensitivity_source.csv"],
            "outputs": ["outputs/geometry_sensitivity_source.csv"], "network": True,
            "required_log_text": ["sensitivity across dem stencil widths"],
        },
        {
            "name": "result2_north_face_aspect_hypothesis",
            "argv": [py, "src/geometry_merge.py", "--sensitivity", "--lat", "28.28771", "--lon", "85.52809",
                     "--aspect", "0"],
            "outputs": [], "network": True,
            "required_log_text": ["[override] aspect"],
        },
        {
            "name": "result6_sentinel2_scene_survey",
            "argv": [py, "src/scar_map.py", "--survey"],
            "outputs": [], "network": True,
            "required_log_text": ["scenes over the source zone"],
        },
        {
            "name": "result6_sentinel2_candidate_map",
            "argv": [py, "src/scar_map.py", "--map", "--candidates-csv", "outputs/scar_candidates_source.csv"],
            "outputs": ["outputs/scar_candidates_source.csv"], "network": True,
            "required_log_text": ["detachment-like"],
        },
        {
            "name": "result6_reported_point_probe",
            "argv": [py, "src/scar_map.py", "--probe", "28.28771", "85.52809"],
            "outputs": [], "network": True,
            "required_log_text": ["not a scar", "usable pixels"],
        },
    ] + [
        {
            "name": f"result3_impoundment_{aoi}",
            "argv": [py, "src/impoundment.py", "--api", "--aoi", aoi, "--heights",
                     "10", "25", "50", "100", "150", "--rank-by", "efficiency",
                     "--geojson", f"outputs/dam_sites_{aoi}.geojson"],
            "outputs": [f"outputs/dam_sites_{aoi}.geojson"], "network": True,
            "required_log_text": ["caveats: pools are not tested"],
        }
        for aoi in ("source", "langtang", "lhende", "blatten")
    ]


def validate_output_file(path: Path) -> str | None:
    """Validate fresh output structure rather than accepting an old/stale file."""
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                if not reader.fieldnames or not any(str(k).strip() for k in reader.fieldnames):
                    return "CSV_HEADER_MISSING"
                if next(reader, None) is None:
                    return "CSV_HAS_NO_DATA_ROWS"
        elif path.suffix.lower() == ".geojson":
            payload = json.loads(path.read_text(encoding="utf-8"))
            features = payload.get("features") if isinstance(payload, dict) else None
            if payload.get("type") != "FeatureCollection" or not isinstance(features, list) or not features:
                return "GEOJSON_NOT_A_NONEMPTY_FEATURE_COLLECTION"
        elif not path.is_file() or path.stat().st_size == 0:
            return "OUTPUT_FILE_EMPTY"
    except Exception as exc:
        return f"OUTPUT_VALIDATION_FAILED:{type(exc).__name__}"
    return None


def retryable_network_failure(text: str, returncode: int, is_network: bool) -> bool:
    return bool(is_network and returncode != 0 and NETWORK_RETRY.search(text))


def run_suite(
    science_root: Path,
    out_root: Path,
    *,
    max_attempts: int = 3,
    base_delay: float = 5.0,
    runner: Callable[..., Any] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    science_root = science_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    log_root = out_root / "logs" / "pinned-science-suite"
    log_root.mkdir(parents=True, exist_ok=True)
    outputs_root = science_root / "outputs"
    outputs_root.mkdir(parents=True, exist_ok=True)

    rev = runner(
        ["git", "-C", str(science_root), "rev-parse", "HEAD"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=30,
    )
    actual_commit = (rev.stdout or "").strip()
    report: dict[str, Any] = {
        "schema_version": "sarguardian-pinned-science-suite/1.0",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "pinned_science_commit_expected": PINNED_SCIENCE_COMMIT,
        "pinned_science_commit_actual": actual_commit,
        "source_scripts_modified": False,
        "raw_hdf5_used_by_supplementary_suite": False,
        "commands": [],
        "reference_checks": [],
        "errors": [],
    }
    if rev.returncode != 0 or actual_commit != PINNED_SCIENCE_COMMIT:
        report["errors"].append({
            "problem": "PINNED_SCIENCE_REVISION_MISMATCH",
            "returncode": rev.returncode,
            "actual": actual_commit,
        })
        report["status"] = "FAIL"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (log_root / "pinned-science-suite.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report

    # The pipeline must execute the committed engine, not a modified local copy.
    source_status = runner(
        ["git", "-C", str(science_root), "status", "--porcelain", "--untracked-files=all", "--", "src"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=30,
    )
    if source_status.returncode != 0 or (source_status.stdout or "").strip():
        report["source_scripts_modified"] = True
        report["errors"].append({
            "problem": "PINNED_SCIENCE_SOURCE_TREE_IS_DIRTY",
            "returncode": source_status.returncode,
            "status_output": (source_status.stdout or "")[:800],
        })
        report["status"] = "FAIL"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (log_root / "pinned-science-suite.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return report

    reference_names = [
        "outputs/detectability.csv", "outputs/detectability_fixed_gate.csv",
        "outputs/scar_candidates_source.csv",
        "outputs/dam_sites_source.geojson", "outputs/dam_sites_langtang.geojson",
        "outputs/dam_sites_lhende.geojson", "outputs/dam_sites_blatten.geojson",
    ]
    snapshots: dict[str, str] = {}
    for rel in reference_names:
        path = science_root / rel
        if path.is_file():
            snapshots[rel] = sha256_file(path)

    for item in command_plan():
        name = item["name"]
        attempts: list[dict[str, Any]] = []
        stdout_text = ""
        success = False
        limit = max_attempts if item["network"] else 1
        for attempt in range(1, limit + 1):
            # Clear targets before every attempt. A previous partially failed
            # network attempt must not leave a file that makes a later no-op
            # success appear to have generated validated output.
            for rel in item["outputs"]:
                (science_root / rel).unlink(missing_ok=True)
            try:
                done = runner(
                    item["argv"],
                    cwd=str(science_root),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=900 if item["network"] else 600,
                )
                stdout_text = done.stdout or ""
                record = {"attempt": attempt, "returncode": int(done.returncode)}
                attempts.append(record)
                if done.returncode == 0:
                    output_errors = []
                    for rel in item["outputs"]:
                        problem = validate_output_file(science_root / rel)
                        if problem:
                            output_errors.append(f"{rel}:{problem}")
                    required_text = item.get("required_log_text", [])
                    missing_text = [phrase for phrase in required_text if phrase not in stdout_text.lower()]
                    if name == "result6_sentinel2_scene_survey":
                        match = re.search(r"(\d+) Sentinel-2 L2A scenes over the source zone", stdout_text)
                        if not match or int(match.group(1)) <= 0:
                            missing_text.append("one or more retrievable Sentinel-2 scenes")
                    record["output_validation_errors"] = output_errors
                    record["missing_required_log_text"] = missing_text
                    if output_errors:
                        stdout_text += "\nERROR=OUTPUT_VALIDATION_FAILED details=" + ";".join(output_errors)
                    if missing_text:
                        stdout_text += "\nERROR=EXPECTED_SCIENCE_EVIDENCE_MISSING items=" + ";".join(missing_text)
                    if not output_errors and not missing_text:
                        success = True
                        break
                retryable = retryable_network_failure(stdout_text, int(done.returncode), bool(item["network"]))
                # A source command can catch a transient HTTP error and still exit
                # zero. If expected evidence or a fresh output is then missing,
                # retry the network stage only when its diagnostics identify a
                # known transient condition; never retry deterministic stages. 
                if (
                    item["network"]
                    and int(done.returncode) == 0
                    and not success
                    and NETWORK_RETRY.search(stdout_text)
                ):
                    retryable = True
            except subprocess.TimeoutExpired as exc:
                stdout_text = str(exc)
                attempts.append({"attempt": attempt, "returncode": None, "exception": "TimeoutExpired"})
                retryable = bool(item["network"])
            except OSError as exc:
                stdout_text = f"{type(exc).__name__}: {exc}"
                attempts.append({"attempt": attempt, "returncode": None, "exception": type(exc).__name__})
                retryable = bool(item["network"])
            if not retryable or attempt >= limit:
                break
            delay = base_delay * (2 ** (attempt - 1))
            stdout_text += f"\nSCIENCE_NETWORK_RETRY next_attempt={attempt + 1}/{limit} sleep_seconds={delay:g}\n"
            sleeper(delay)

        log_path = log_root / f"{name}.log"
        log_path.write_text(stdout_text, encoding="utf-8")
        row = {
            "name": name,
            "argv": item["argv"],
            "network_stage": bool(item["network"]),
            "attempts": attempts,
            "status": "PASS" if success else "FAIL",
            "log": str(log_path.relative_to(out_root)),
            "outputs": item["outputs"],
        }
        report["commands"].append(row)
        print(f"PINNED_SCIENCE_STEP={name} STATUS={row['status']} ATTEMPTS={len(attempts)}")
        if not success:
            report["errors"].append({
                "problem": "PINNED_SCIENCE_STEP_FAILED",
                "name": name,
                "log": row["log"],
                "last_returncode": attempts[-1].get("returncode") if attempts else None,
                "output_tail": stdout_text[-1200:],
            })

    for rel, previous_hash in snapshots.items():
        current_path = science_root / rel
        if current_path.is_file():
            current_hash = sha256_file(current_path)
            report["reference_checks"].append({
                "file": rel,
                "status": "MATCH" if current_hash == previous_hash else "LIVE_OR_REGENERATED_OUTPUT_DIFFERS_FROM_COMMITTED_REFERENCE",
                "committed_sha256": previous_hash,
                "generated_sha256": current_hash,
            })
        else:
            report["reference_checks"].append({
                "file": rel,
                "status": "MISSING_AFTER_RUN",
                "committed_sha256": previous_hash,
                "generated_sha256": None,
            })

    # Re-check the maintained science source after every experiment. This
    # makes the "unchanged pinned src/" guarantee an end-to-end invariant, not
    # merely a precondition checked before the commands start.
    post_source_status = runner(
        ["git", "-C", str(science_root), "status", "--porcelain", "--untracked-files=all", "--", "src"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=30,
    )
    post_status_text = (post_source_status.stdout or "").strip()
    source_integrity_status = "PASS" if post_source_status.returncode == 0 and not post_status_text else "FAIL"
    report["source_integrity_after_run"] = {
        "status": source_integrity_status,
        "returncode": post_source_status.returncode,
        "status_output": post_status_text[:800],
    }
    if source_integrity_status != "PASS":
        report["source_scripts_modified"] = True
        report["errors"].append({
            "problem": "PINNED_SCIENCE_SOURCE_TREE_CHANGED_DURING_RUN",
            "returncode": post_source_status.returncode,
            "status_output": post_status_text[:800],
        })

    report["status"] = "PASS" if not report["errors"] else "FAIL"
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    (log_root / "pinned-science-suite.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"PINNED_SCIENCE_SUITE_STATUS={report['status']}")
    print(f"PINNED_SCIENCE_STEPS={len(report['commands'])}")
    print(f"PINNED_SCIENCE_ERRORS={len(report['errors'])}")
    print(f"PINNED_SCIENCE_REPORT={log_root / 'pinned-science-suite.json'}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--science-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--base-delay", type=float, default=5.0)
    args = parser.parse_args()
    if args.max_attempts < 1 or args.base_delay < 0:
        parser.error("--max-attempts must be >=1 and --base-delay must be >=0")
    report = run_suite(args.science_root, args.out_root, max_attempts=args.max_attempts,
                       base_delay=args.base_delay)
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
