#!/usr/bin/env python3
"""Retrospectively replay Run #36 from retained AOI-extracted NISAR COG artifacts.

This deliberately calls the current RiverShift science and QA functions. It does
not rerun CMR discovery or download NISAR products, and it does not modify the
original Supabase job or claim that the old worker emitted these diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from process_gcov_job import create_web_previews  # noqa: E402
from river_shift.flood import run_flood_analysis  # noqa: E402
from river_shift.morphology import run_morphology_analysis  # noqa: E402
from river_shift.overlap_audit import audit_candidate_mask_overlap  # noqa: E402
from river_shift.raster_io import sha256_file  # noqa: E402


SOURCE_RUN_ID = 41803576163
SOURCE_RUN_NUMBER = 36
SOURCE_JOB_ID = "4e6e4071-fb9d-4e20-a331-867f3f2bd88f"
ORIGINAL_METRICS = {
    "newly_water_covered_area_km2": 17.6721,
    "persistent_erosion_candidate_area_ha": 1244.230,
    "persistent_deposition_candidate_area_ha": 5078.140,
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def _find_prepared(prepared_root: Path) -> Path:
    matches = list(prepared_root.rglob("prepared.json"))
    if len(matches) != 1:
        raise ValueError(f"Expected one prepared.json under {prepared_root}, found {len(matches)}")
    return matches[0]


def _find_product(products_root: Path, granule_name: str) -> Path:
    matches = list(products_root.rglob(f"{granule_name}.tif"))
    if len(matches) != 1:
        raise ValueError(
            f"Expected one retained COG for {granule_name}, found {len(matches)}"
        )
    return matches[0]


def _prepare_inputs(
    prepared: dict[str, Any],
    products_root: Path,
    work_dir: Path,
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    """Copy retained COGs and rebind only the sidecar's local path field.

    The product COG and its content SHA-256 are never altered. Its original
    worker path is preserved in the output manifest for auditability.
    """
    input_dir = work_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    date_by_name = prepared.get("date_by_name")
    if not isinstance(date_by_name, dict) or not date_by_name:
        raise ValueError("prepared.json has no date_by_name catalogue")

    by_date: dict[str, Path] = {}
    provenance: list[dict[str, Any]] = []
    for granule_name, acquisition_date in sorted(date_by_name.items(), key=lambda item: item[1]):
        if not isinstance(granule_name, str) or not isinstance(acquisition_date, str):
            raise ValueError("prepared date_by_name contains an invalid row")
        source = _find_product(products_root, granule_name)
        source_sidecar = source.with_suffix(".metadata.json")
        metadata = _json(source_sidecar)
        actual_sha = sha256_file(source)
        expected_sha = metadata.get("output_cog_sha256")
        if not isinstance(expected_sha, str) or actual_sha.lower() != expected_sha.lower():
            raise ValueError(f"Retained COG checksum mismatch for {granule_name}")
        if metadata.get("source_granule_name") != granule_name:
            raise ValueError(f"COG sidecar granule name mismatch for {granule_name}")

        destination = input_dir / source.name
        sidecar_destination = destination.with_suffix(".metadata.json")
        shutil.copy2(source, destination)
        metadata["output_cog"] = str(destination.resolve())
        sidecar_destination.write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if acquisition_date in by_date:
            raise ValueError(f"Duplicate retained COG acquisition date {acquisition_date}")
        by_date[acquisition_date] = destination
        provenance.append({
            "acquisition_date": acquisition_date,
            "granule_name": granule_name,
            "retained_artifact_cog": source.name,
            "source_cog_sha256": actual_sha,
            "sidecar_cog_sha256": expected_sha,
            "checksum_match": True,
            "original_worker_output_path": _json(source_sidecar).get("output_cog"),
            "replay_input_path": str(destination),
            "metadata_sidecar_rebound_only_for_local_path": True,
        })

    required_dates = set(prepared.get("dates") or [])
    missing = sorted(required_dates - set(by_date))
    if missing:
        raise ValueError(f"Missing retained COG dates: {', '.join(missing)}")
    return by_date, provenance


def _close_enough(actual: float, expected: float, *, tolerance: float = 1e-8) -> bool:
    return abs(float(actual) - float(expected)) <= tolerance


def replay(prepared_root: Path, products_root: Path, output_root: Path) -> dict[str, Any]:
    prepared_path = _find_prepared(prepared_root)
    prepared = _json(prepared_path)
    request = prepared.get("request")
    windows = prepared.get("analysis_window")
    if not isinstance(request, dict) or not isinstance(windows, dict):
        raise ValueError("prepared.json is missing request or analysis_window")
    if request.get("analysis_mode") != "event_based":
        raise ValueError("This retrospective runner is pinned to the retained event-based Run #36")
    if request.get("maturity") != "PROVISIONAL" or request.get("frequency") != "frequencyA" or request.get("term") != "HHHH":
        raise ValueError("Run #36 product contract differs from the expected PROVISIONAL/frequencyA/HHHH contract")

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    input_by_date, cogs = _prepare_inputs(prepared, products_root, output_root)

    before_date = windows["before"]
    during_date = windows["event_proximal_observation"]
    post_one_date = windows["post_one"]
    post_two_date = windows["post_two"]
    for item in (before_date, during_date, post_one_date, post_two_date):
        if item not in input_by_date:
            raise ValueError(f"Run #36 comparison date {item} has no retained COG")
    before = input_by_date[before_date]
    during = input_by_date[during_date]
    post_one = input_by_date[post_one_date]
    post_two = input_by_date[post_two_date]

    flood_dir = output_root / "analysis" / "flood"
    morphology_dir = output_root / "analysis" / "morphology"
    threshold_method = request.get("threshold_method")
    use_otsu = threshold_method == "otsu"
    if not use_otsu:
        raise ValueError("Run #36 replay expected the original exploratory Otsu method")

    flood_result = run_flood_analysis(
        before_path=str(before),
        during_path=str(during),
        after_path=str(post_one),
        output_dir=str(flood_dir),
        units="linear",
        threshold_db=None,
        use_otsu=True,
        dates={"before": before_date, "during": during_date, "after": post_one_date},
        maturity=request["maturity"],
        frequency=request["frequency"],
        polarization_term=request["term"],
        sensitivity_delta_db=2.0,
    )
    morphology_result = run_morphology_analysis(
        before_path=str(before),
        post_one_path=str(post_one),
        post_two_path=str(post_two),
        output_dir=str(morphology_dir),
        units="linear",
        threshold_db=None,
        use_otsu=True,
        dates={"before": before_date, "post_one": post_one_date, "post_two": post_two_date},
        maturity=request["maturity"],
        frequency=request["frequency"],
        polarization_term=request["term"],
        sensitivity_delta_db=2.0,
    )

    comparison_window = {
        "baseline": before_date,
        "morphology_post_one": post_one_date,
        "morphology_post_two": post_two_date,
        "new_water_comparison": during_date,
    }
    quality_dir = output_root / "outputs" / "quality-assurance"
    source_audit_path = quality_dir / "candidate_mask_overlap_audit.json"
    source_audit = audit_candidate_mask_overlap(
        {
            "erosion": morphology_dir / "erosion_candidate_mask.tif",
            "deposition": morphology_dir / "deposition_candidate_mask.tif",
            "new_water": flood_dir / "newly_water_covered_mask.tif",
        },
        source_audit_path,
        comparison_window=comparison_window,
    )

    # Reuse the current worker's exact preview generator and geometry-overlap
    # function. An empty acquisition-frame list is intentional: this replay is
    # restricted to the three change-class previews, not the observed-date
    # playback layers.
    time_dir = output_root / "analysis" / "time-series"
    time_dir.mkdir(parents=True, exist_ok=True)
    time_report_path = time_dir / "river_shift_timeseries.json"
    time_report_path.write_text(
        json.dumps({"time_series": [], "quality": {"warnings": []}}, indent=2),
        encoding="utf-8",
    )
    create_web_previews(
        output_root,
        time_dir,
        flood_dir,
        morphology_dir,
        before,
        time_report_path,
    )
    combined_preview_path = output_root / "outputs" / "map" / "river_change_candidates_preview.geojson"
    combined_preview = _json(combined_preview_path)
    preview_metadata = combined_preview.get("river_shift_preview")
    if not isinstance(preview_metadata, dict):
        raise ValueError("Current worker preview has no river_shift_preview metadata")
    preview_audit = preview_metadata.get("preview_geometry_overlap")
    if not isinstance(preview_audit, dict):
        raise ValueError("Current worker preview geometry overlap was not generated")

    event_date = date.fromisoformat(request["event_date"])
    event_observation_date = date.fromisoformat(during_date)
    observation_offset = (event_observation_date - event_date).days
    if observation_offset <= 0:
        raise ValueError("Run #36 first event-proximal observation must follow the supplied event date")

    reproduced_metrics = {
        "newly_water_covered_area_km2": float(flood_result["metrics"]["newly_water_covered_area_km2"]),
        "persistent_erosion_candidate_area_ha": float(morphology_result["metrics"]["persistent_erosion_candidate_area_ha"]),
        "persistent_deposition_candidate_area_ha": float(morphology_result["metrics"]["persistent_deposition_candidate_area_ha"]),
    }
    match_flags = {
        key: _close_enough(value, ORIGINAL_METRICS[key])
        for key, value in reproduced_metrics.items()
    }
    reproduction_status = "EXACT_AREA_REPRODUCTION" if all(match_flags.values()) else "AREA_REPRODUCTION_DIVERGED"

    output_manifest = {
        "schema_version": 1,
        "engine": "RiverShift",
        "audit_origin": "RETROSPECTIVE_REPLAY_USING_CURRENT_MAIN_WORKER_FUNCTIONS",
        "status": "RETROSPECTIVE_RECOMPUTED_NOT_ORIGINAL_WORKER_ARTIFACT",
        "source_run": {
            "repository": "moshiour0/SARGuardian-backend",
            "run_id": SOURCE_RUN_ID,
            "run_number": SOURCE_RUN_NUMBER,
            "job_id": SOURCE_JOB_ID,
            "prepared_manifest_sha256": sha256_file(prepared_path),
        },
        "product_contract": {
            "mission": "NISAR",
            "product": "GCOV",
            "maturity": request["maturity"],
            "frequency": request["frequency"],
            "covariance_term": request["term"],
            "threshold_method": "combined_three_date_exploratory_otsu",
            "input_units": "linear_gamma0_power",
            "grid": {
                "crs": source_audit["grid"]["crs"],
                "width": source_audit["grid"]["width"],
                "height": source_audit["grid"]["height"],
                "transform": source_audit["grid"]["transform"],
                "pixel_area_m2": source_audit["grid"]["pixel_area_m2"],
            },
        },
        "cogs": cogs,
        "comparison_window": comparison_window,
        "event_observation_timing": {
            "event_date": event_date.isoformat(),
            "first_post_event_observation": event_observation_date.isoformat(),
            "offset_days": observation_offset,
            "interpretation": "first qualifying NISAR observation after the user-supplied event date; not peak-stage or same-stage evidence",
        },
        "area_reproduction": {
            "status": reproduction_status,
            "original_run_36_metrics": ORIGINAL_METRICS,
            "recomputed_metrics": reproduced_metrics,
            "matches": match_flags,
            "flood_otsu_threshold_db": float(flood_result["method"]["threshold_db"]),
            "morphology_otsu_threshold_db": float(morphology_result["method"]["threshold_db"]),
        },
        "candidate_overlap_audit": source_audit,
        "preview_geometry_overlap": preview_audit,
        "artifact_paths": {
            "source_mask_audit": str(source_audit_path.relative_to(output_root)),
            "combined_preview": str(combined_preview_path.relative_to(output_root)),
            "class_previews": [
                "outputs/map/erosion_candidates_preview.geojson",
                "outputs/map/deposition_candidates_preview.geojson",
                "outputs/map/newly_water_covered_preview.geojson",
            ],
        },
        "scientific_boundary": [
            "This is a retrospective replay from the original retained Run #36 COGs using current main processing functions.",
            "It is not a new original Run #36 worker artifact and does not mutate the original Supabase job.",
            "The overlap diagnostics do not establish independent accuracy or field-confirmed geomorphic change.",
            "New-water may overlap a morphology class because the temporal comparison differs.",
            "The first event-proximal acquisition was 20 days after the user-supplied event date and is not event-peak evidence.",
            "No F1, IoU, accuracy or independent reference score is produced by this replay.",
        ],
    }
    manifest_path = output_root / "run36_retrospective_overlap_replay.json"
    manifest_path.write_text(json.dumps(output_manifest, indent=2, allow_nan=False), encoding="utf-8")
    manifest_sha = sha256_file(manifest_path)
    manifest_path.with_suffix(".json.sha256").write_text(
        f"{manifest_sha}  {manifest_path.name}\\n",
        encoding="utf-8",
    )
    output_manifest["manifest_sha256"] = manifest_sha
    return output_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", required=True, type=Path)
    parser.add_argument("--products-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    result = replay(args.prepared_root, args.products_root, args.output_root)
    print("RIVERSHIFT_RUN36_REPLAY_STATUS=" + result["area_reproduction"]["status"], flush=True)
    print("RIVERSHIFT_RUN36_SOURCE_OVERLAP_SHA256=" + result["candidate_overlap_audit"]["report_sha256"], flush=True)
    print("RIVERSHIFT_RUN36_PREVIEW_OVERLAP_STATUS=" + result["preview_geometry_overlap"]["status"], flush=True)
    print("RIVERSHIFT_RUN36_REPLAY_MANIFEST_SHA256=" + result["manifest_sha256"], flush=True)
    return 0 if result["area_reproduction"]["status"] == "EXACT_AREA_REPRODUCTION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
