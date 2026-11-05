#!/usr/bin/env python3
"""Extend a verified 33-product source-AOI run with the remaining reproducible science results.

This stage consumes the completed result bundle and exported GeoTIFFs. It never
extracts or requires raw HDF5 files. Live external-data stages are reported
individually; one failing source does not conceal the status of other stages.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

PINNED_SCIENCE_COMMIT = "ab547ecc82bcc4d6ccef545a59852536c2beacc6"
EXPECTED_PRODUCTS = {"GUNW": 15, "GOFF": 18}
PUBLISHED_TARGET = (28.27799, 85.52983)
PUBLISHED_ELEVATION_M = (5200.0, 5400.0)


class ExtensionError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json_zip(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise ExtensionError(f"SOURCE_BUNDLE_METADATA_INVALID file={name} type={type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise ExtensionError(f"SOURCE_BUNDLE_METADATA_ROOT_INVALID file={name}")
    return value


def _validate_report(manifest: dict[str, Any], report: dict[str, Any], source_run_id: str) -> None:
    if manifest.get("run_profile") != "full-source-baseline":
        raise ExtensionError("SOURCE_RUN_PROFILE_NOT_FULL_BASELINE")
    if manifest.get("aoi") != "source":
        raise ExtensionError("SOURCE_RUN_AOI_MISMATCH")
    if manifest.get("science_commit") != PINNED_SCIENCE_COMMIT:
        raise ExtensionError("SOURCE_RUN_SCIENCE_COMMIT_MISMATCH")
    run_id = str(manifest.get("run_id", ""))
    if not run_id.startswith(source_run_id + "-"):
        raise ExtensionError("SOURCE_RUN_ID_DOES_NOT_MATCH_BUNDLE_MANIFEST")

    products = manifest.get("products")
    if not isinstance(products, list) or len(products) != 33:
        raise ExtensionError("SOURCE_MANIFEST_PRODUCT_COUNT_NOT_33")
    counts = {
        family: sum(1 for product in products
                    if isinstance(product, dict) and product.get("product_type") == family)
        for family in ("GUNW", "GOFF")
    }
    if counts != EXPECTED_PRODUCTS:
        raise ExtensionError(f"SOURCE_MANIFEST_FAMILY_COUNTS_INVALID counts={counts}")

    if report.get("status") != "PASS":
        raise ExtensionError("SOURCE_BATCH_EQUIVALENCE_REPORT_NOT_PASS")
    if report.get("products_expected") != 33 or report.get("products_validated") != 33:
        raise ExtensionError("SOURCE_BATCH_VALIDATION_NOT_33_OF_33")
    if report.get("errors"):
        raise ExtensionError("SOURCE_BATCH_REPORT_CONTAINS_ERRORS")
    comparison_rows = report.get("comparisons")
    if not isinstance(comparison_rows, list) or not comparison_rows:
        raise ExtensionError("SOURCE_BATCH_COMPARISON_REPORT_MISSING")
    unacceptable = [
        row for row in comparison_rows
        if not isinstance(row, dict) or row.get("status") not in {"PASS", "SKIP_NO_COMMITTED_BASELINE"}
    ]
    if unacceptable:
        raise ExtensionError("SOURCE_BATCH_COMPARISON_REPORT_HAS_FAILURES")
    retention = report.get("retention_storage_accounting")
    if not isinstance(retention, dict) or retention.get("status") != "PASS":
        raise ExtensionError("SOURCE_RETENTION_ACCOUNTING_NOT_PASS")


def validate_and_extract_bundle(
    bundle_path: Path, source_run_id: str, science_root: Path, package_root: Path
) -> tuple[dict[str, Any], dict[str, Any], int]:
    if not bundle_path.is_file():
        raise ExtensionError("SOURCE_BUNDLE_FILE_MISSING")

    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        manifest = _read_json_zip(archive, "run-manifest.json")
        report = _read_json_zip(archive, "batch-equivalence-report.json")
        _validate_report(manifest, report, source_run_id)

        extraction_root = science_root.resolve()
        raw_hdf5_skipped = 0
        extracted_names: set[str] = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            posix = PurePosixPath(info.filename)
            if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
                raise ExtensionError("SOURCE_BUNDLE_PATH_TRAVERSAL_REJECTED")
            if not posix.parts or posix.parts[0] != "outputs":
                continue
            if posix.suffix.lower() in {".h5", ".hdf5"}:
                raw_hdf5_skipped += 1
                continue
            target = (extraction_root / Path(*posix.parts)).resolve()
            if not target.is_relative_to(extraction_root):
                raise ExtensionError("SOURCE_BUNDLE_PATH_TRAVERSAL_REJECTED")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            extracted_names.add(posix.as_posix())

        required = {
            "outputs/gunw_stats_source.csv",
            "outputs/goff_stats_source.csv",
            "outputs/scar_candidates_source.csv",
            "outputs/ts_goff_source.csv",
            "outputs/troposphere_gunw_source.csv",
            "outputs/troposphere_goff_source.csv",
        }
        missing = sorted(required - extracted_names)
        if missing:
            raise ExtensionError("SOURCE_BUNDLE_REQUIRED_OUTPUTS_MISSING names=" + ",".join(missing))
        for rel in ("outputs/export_src", "outputs/export_goff_src"):
            folder = extraction_root / rel
            if not folder.is_dir() or not any(p.is_file() and p.suffix.lower() in {".tif", ".tiff"} for p in folder.rglob("*")):
                raise ExtensionError(f"SOURCE_BUNDLE_EXPORTS_MISSING path={rel}")

    extension_dir = science_root / "outputs" / "extended_science"
    if extension_dir.exists():
        shutil.rmtree(extension_dir)
    extension_dir.mkdir(parents=True, exist_ok=True)

    # Preserve the source repository's committed scar candidate list for an
    # explicit comparison with the fresh Sentinel-2-derived list.
    reference_candidate = science_root / "outputs" / "scar_candidates_source.csv"
    if reference_candidate.is_file():
        shutil.copy2(reference_candidate, extension_dir / "committed_scar_candidates_reference.csv")

    # Include the compact, already-verified core results in the final science
    # package so the extended result bundle is interpretable without extracting
    # the full source bundle again. Large reader-exported TIFFs stay in the
    # separate source-run artifact to avoid duplicating hundreds of MB.
    inherited = extension_dir / "results_4_5_from_verified_baseline"
    inherited.mkdir(parents=True, exist_ok=True)
    for filename in (
        "ts_goff_source.csv", "ts_gunw_source.csv",
        "troposphere_gunw_source.csv", "troposphere_goff_source.csv",
        "local_floor_candidates.csv", "local_floor_phase_candidates.csv",
        "local_floor_cand4.csv", "local_floor_cand4_as_floors.csv",
        "common_ref_summer.csv", "bound_source.csv",
        "ts_goff_cand4_common.csv",
    ):
        source = science_root / "outputs" / filename
        if source.is_file() and source.stat().st_size > 0:
            shutil.copy2(source, inherited / filename)

    (package_root / "source-run-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (package_root / "source-batch-equivalence-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest, report, raw_hdf5_skipped


def _run_command(
    name: str,
    argv: list[str],
    science_root: Path,
    extension_dir: Path,
    report: dict[str, Any],
    required_outputs: list[Path] | None = None,
    timeout_seconds: int = 5400,
) -> bool:
    log_dir = extension_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
    log_path = log_dir / f"{safe_name}.log"
    started = _utc_now()
    try:
        completed = subprocess.run(
            argv,
            cwd=science_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_seconds,
        )
        output = completed.stdout or ""
        code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout or ""
        output = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        output += f"\nEXTENSION_COMMAND_TIMEOUT_SECONDS={timeout_seconds}\n"
        code = 124
    except Exception as exc:
        output = f"EXTENSION_COMMAND_LAUNCH_FAILED type={type(exc).__name__}: {str(exc)[:240]}\n"
        code = 125
    log_path.write_text(output, encoding="utf-8")

    missing: list[str] = []
    for path in required_outputs or []:
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(str(path.relative_to(science_root)) if path.is_relative_to(science_root) else path.name)
    passed = code == 0 and not missing
    report.setdefault("commands", []).append({
        "name": name,
        "argv": [str(value) for value in argv],
        "started_utc": started,
        "finished_utc": _utc_now(),
        "exit_code": code,
        "status": "PASS" if passed else "FAIL",
        "missing_required_outputs": missing,
        "log": str(log_path.relative_to(extension_dir)),
        "log_tail": output[-1400:],
    })
    return passed


def _set_stage(report: dict[str, Any], name: str, outcomes: list[bool], details: dict[str, Any] | None = None) -> bool:
    passed = bool(outcomes) and all(outcomes)
    report.setdefault("stages", {})[name] = {
        "status": "PASS" if passed else "FAIL",
        "commands_passed": sum(outcomes),
        "commands_total": len(outcomes),
        **(details or {}),
    }
    return passed


def _python() -> str:
    return sys.executable


def run_model_detectability(science_root: Path, extension_dir: Path, report: dict[str, Any]) -> bool:
    py = _python()
    out = extension_dir
    return _set_stage(report, "result_1_detectability_models", [
        _run_command(
            "detectability offset-tracking sweep",
            [py, "src/detectability.py", "--sweep", "--precursor", "5", "10", "20", "40",
             "--csv", str(out / "detectability_offset_sweep.csv"),
             "--plot", str(out / "detectability_offset_sweep.png")],
            science_root, extension_dir, report,
            [out / "detectability_offset_sweep.csv", out / "detectability_offset_sweep.png"],
        ),
        _run_command(
            "Blatten calibrated NISAR L-band phase sweep",
            [py, "src/detectability.py", "--sweep", "--blatten", "--noise", "5",
             "--wavelength", "0.2384",
             "--csv", str(out / "detectability_blatten_lband_phase.csv"),
             "--plot", str(out / "detectability_blatten_lband_phase.png")],
            science_root, extension_dir, report,
            [out / "detectability_blatten_lband_phase.csv", out / "detectability_blatten_lband_phase.png"],
        ),
        _run_command(
            "Blatten calibrated offset-tracking sweep",
            [py, "src/detectability.py", "--sweep", "--blatten", "--noise", "300",
             "--csv", str(out / "detectability_blatten_offset.csv"),
             "--plot", str(out / "detectability_blatten_offset.png")],
            science_root, extension_dir, report,
            [out / "detectability_blatten_offset.csv", out / "detectability_blatten_offset.png"],
        ),
    ])


def run_geometry_sensitivity(science_root: Path, extension_dir: Path, report: dict[str, Any]) -> bool:
    py = _python()
    out = extension_dir
    return _set_stage(report, "result_2_geometry_sensitivity", [
        _run_command(
            "NISAR track sensitivity and DEM stencil sweep at the published-source hypothesis",
            [py, "src/geometry_merge.py", "--sensitivity", "--lat", "28.2877", "--lon", "85.5281",
             "--stencil-sweep", "--csv", str(out / "geometry_sensitivity.csv"),
             "--plot", str(out / "geometry_sensitivity.png")],
            science_root, extension_dir, report,
            [out / "geometry_sensitivity.csv", out / "geometry_sensitivity.png"],
        ),
        _run_command(
            "source AOI geometry coverage map",
            [py, "src/geometry_merge.py", "--map", "source",
             "--csv", str(out / "geometry_source_coverage.csv")],
            science_root, extension_dir, report,
            [out / "geometry_source_coverage.csv"],
        ),
    ])


def run_impoundment_sensitivity(science_root: Path, extension_dir: Path, report: dict[str, Any]) -> bool:
    py = _python()
    results = []
    for aoi in ("source", "langtang", "lhende", "blatten"):
        geojson = extension_dir / f"dam_sites_{aoi}.geojson"
        results.append(_run_command(
            f"impoundment susceptibility DEM analysis {aoi}",
            [py, "src/impoundment.py", "--api", "--aoi", aoi, "--cells", "12000",
             "--heights", "10", "25", "50", "100", "150", "--rank-by", "efficiency",
             "--geojson", str(geojson)],
            science_root, extension_dir, report, [geojson], timeout_seconds=5400,
        ))
    return _set_stage(
        report, "result_3_impoundment_sensitivity", results,
        {"aois": ["source", "langtang", "lhende", "blatten"], "grid_cells_target_per_aoi": 12000,
         "height_scenarios_m": [10, 25, 50, 100, 150], "dem_source": "OpenTopoData SRTM30m API"},
    )


def run_sentinel_scar_mapping(science_root: Path, extension_dir: Path, report: dict[str, Any]) -> tuple[bool, bool]:
    py = _python()
    survey = _run_command(
        "Sentinel-2 STAC survey for the source AOI",
        [py, "src/scar_map.py", "--survey"],
        science_root, extension_dir, report,
    )
    candidates = extension_dir / "scar_candidates_source.csv"
    mapping = _run_command(
        "Sentinel-2 NDSI-change scar candidate mapping",
        [py, "src/scar_map.py", "--map", "--candidates-csv", str(candidates)],
        science_root, extension_dir, report, [candidates], timeout_seconds=5400,
    )
    probe = _run_command(
        "Sentinel-2 point probe at the reported collapse coordinate",
        [py, "src/scar_map.py", "--probe", "28.28771", "85.52809"],
        science_root, extension_dir, report, timeout_seconds=5400,
    )
    _set_stage(
        report, "result_6_sentinel2_scar_map", [survey, mapping, probe],
        {"fresh_candidate_file": str(candidates.relative_to(science_root)),
         "external_source": "Sentinel-2 L2A scene catalogue and COG assets",
         "candidate_interpretation": "spectral and terrain screening; not by itself proof of the collapse scar"},
    )
    return all([survey, mapping, probe]), mapping


def _choose_published_candidate(candidate_csv: Path) -> dict[str, str]:
    with candidate_csv.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"id", "lat", "lon", "elev_m", "reading"}.issubset(reader.fieldnames):
            raise ExtensionError("FRESH_CANDIDATE_CSV_SCHEMA_INVALID")
        rows = list(reader)
    eligible: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        if row.get("reading") != "DETACHMENT-like":
            continue
        try:
            elevation = float(row["elev_m"])
            lat, lon = float(row["lat"]), float(row["lon"])
        except (ValueError, TypeError, KeyError):
            continue
        if not (PUBLISHED_ELEVATION_M[0] <= elevation <= PUBLISHED_ELEVATION_M[1]):
            continue
        # Prefer the eligible candidate nearest the documented candidate-4
        # coordinate; this is a transparent association rule, not ground truth.
        distance_score = (lat - PUBLISHED_TARGET[0]) ** 2 + (lon - PUBLISHED_TARGET[1]) ** 2
        eligible.append((distance_score, row))
    if not eligible:
        raise ExtensionError("NO_FRESH_DETACHMENT_LIKE_CANDIDATE_MATCHES_PUBLISHED_ELEVATION_BAND")
    selected = min(eligible, key=lambda item: item[0])[1]
    return selected


def run_fresh_result_7(
    science_root: Path, extension_dir: Path, report: dict[str, Any], fresh_candidates: Path
) -> bool:
    py = _python()
    outputs = science_root / "outputs"
    outcomes: list[bool] = []

    if not fresh_candidates.is_file() or fresh_candidates.stat().st_size == 0:
        return _set_stage(report, "result_7_fresh_candidate_floors_and_final_bound", [False],
                          {"reason": "fresh Sentinel-2 candidate CSV missing"})

    # Use the fresh candidate catalogue as the live input, while preserving
    # the committed list in the extension package for a side-by-side audit.
    shutil.copy2(fresh_candidates, extension_dir / "fresh_scar_candidates_source.csv")
    shutil.copy2(fresh_candidates, outputs / "scar_candidates_source.csv")

    include_goff = ["20251128", "20251210", "20251222", "20260103", "20260702", "20260714", "20260726", "20260819"]
    include_phase = ["20251128", "20251210", "20251222", "20260103", "20260620", "20260702", "20260714", "20260726"]
    goff_floor = extension_dir / "local_floor_candidates_fresh.csv"
    phase_floor = extension_dir / "local_floor_phase_candidates_fresh.csv"
    common_ref = extension_dir / "common_ref_summer_fresh.csv"
    candidate_specific_floor = extension_dir / "local_floor_published_candidate.csv"
    candidate_specific_as_floors = extension_dir / "local_floor_published_candidate_as_floors.csv"

    outcomes.append(_run_command(
        "fresh GOFF candidate local floors",
        [py, "src/local_floor.py", "--dir", "outputs/export_goff_src", "--match", "layer2",
         "--targets", str(fresh_candidates.relative_to(science_root)), "--reading", "DETACHMENT-like",
         "--radius", "6", "--exclude", "20260828", "_UR_", "--include", *include_goff,
         "--csv", str(goff_floor)],
        science_root, extension_dir, report, [goff_floor],
    ))
    outcomes.append(_run_command(
        "fresh GUNW candidate phase floors",
        [py, "src/local_floor.py", "--dir", "outputs/export_src", "--band", "1",
         "--targets", str(fresh_candidates.relative_to(science_root)), "--reading", "DETACHMENT-like",
         "--radius", "6", "--exclude", "_UR_", "--include", *include_phase,
         "--csv", str(phase_floor)],
        science_root, extension_dir, report, [phase_floor],
    ))
    outcomes.append(_run_command(
        "fresh GOFF summer common-reference diagnostics",
        [py, "src/common_ref.py", "--dir", "outputs/export_goff_src", "--match", "layer2",
         "--include", "20260702", "20260714", "20260726", "--exclude", "_UR_",
         "--targets", str(fresh_candidates.relative_to(science_root)), "--reading", "DETACHMENT-like",
         "--csv", str(common_ref)],
        science_root, extension_dir, report, [common_ref],
    ))
    if not all(outcomes):
        return _set_stage(report, "result_7_fresh_candidate_floors_and_final_bound", outcomes,
                          {"reason": "one or more fresh candidate-floor commands failed"})

    shutil.copy2(goff_floor, outputs / "local_floor_candidates.csv")
    shutil.copy2(phase_floor, outputs / "local_floor_phase_candidates.csv")
    shutil.copy2(common_ref, outputs / "common_ref_summer.csv")

    try:
        selected = _choose_published_candidate(fresh_candidates)
    except Exception as exc:
        return _set_stage(
            report, "result_7_fresh_candidate_floors_and_final_bound", [False],
            {"reason": f"{type(exc).__name__}: {str(exc)[:240]}"},
        )
    lat, lon = float(selected["lat"]), float(selected["lon"])
    candidate_label = f"Fresh candidate {selected['id']}"

    # Rebuild the point series from all 18 validated GOFF exports (16 PR + 2 UR)
    # on one fixed common datum. The reader-exported GeoTIFFs are sufficient.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from tools.aggregate_streamed_outputs import run_common_reference_target_series

        local_report: dict[str, Any] = {"commands": []}
        run_common_reference_target_series(
            science_root, local_report, target_lat=lat, target_lon=lon,
            target_label=candidate_label,
        )
        report.setdefault("commands", []).extend(local_report["commands"])
        shutil.copy2(outputs / "ts_goff_cand4_common.csv", extension_dir / "ts_goff_fresh_candidate_common.csv")
        outcomes.append(True)
    except Exception as exc:
        report.setdefault("commands", []).append({
            "name": f"{candidate_label} common-reference point series from TIFFs",
            "status": "FAIL", "exit_code": 1,
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        })
        outcomes.append(False)

    outcomes.append(_run_command(
        "fresh selected-candidate pointwise local floors",
        [py, "src/local_floor.py", "--dir", "outputs/export_goff_src", "--match", "layer2",
         "--lat", f"{lat:.8f}", "--lon", f"{lon:.8f}", "--radius", "6",
         "--exclude", "_UR_", "20260828", "20260831",
         "--csv", str(candidate_specific_floor), "--as-floors", str(candidate_specific_as_floors)],
        science_root, extension_dir, report, [candidate_specific_floor, candidate_specific_as_floors],
    ))

    outcomes.append(_run_command(
        "final fresh candidate bound table",
        [py, "src/bound.py"],
        science_root, extension_dir, report, [outputs / "bound_source.csv"],
    ))
    if (outputs / "bound_source.csv").is_file():
        shutil.copy2(outputs / "bound_source.csv", extension_dir / "bound_source_fresh.csv")

    fresh_series = extension_dir / "ts_goff_fresh_candidate_common.csv"
    if outcomes[3] and fresh_series.is_file() and fresh_series.stat().st_size > 0:
        outcomes.append(_run_command(
            "fresh candidate common-datum inverse-velocity gate",
            [py, "src/inverse_velocity.py", "--ts", str(fresh_series),
             "--floors", str(candidate_specific_as_floors), "--floors-layer", "layer2",
             "--event-date", "2026-08-26"],
            science_root, extension_dir, report,
        ))
    else:
        report.setdefault("commands", []).append({
            "name": "fresh candidate common-datum inverse-velocity gate",
            "status": "SKIPPED", "exit_code": None,
            "reason": "fresh common-datum candidate series was not successfully created; stale baseline series refused",
        })
        outcomes.append(False)
    report["stages"]["result_7_fresh_candidate_floors_and_final_bound"]["selected_candidate"] = {
        "id": selected["id"], "lat": lat, "lon": lon, "elev_m": float(selected["elev_m"]),
        "reading": selected["reading"],
        "selection_rule": "DETACHMENT-like within published elevation band; nearest to documented candidate-4 reference coordinate",
        "note": "This is a reproducible association heuristic, not independent ground-truth confirmation.",
    }
    return _set_stage(
        report, "result_7_fresh_candidate_floors_and_final_bound", outcomes,
        {"selected_candidate": report["stages"]["result_7_fresh_candidate_floors_and_final_bound"]["selected_candidate"]},
    )


def _hash_outputs(extension_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(extension_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() in {".h5", ".hdf5"}:
            continue
        rows.append({
            "path": str(path.relative_to(extension_dir)),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return rows


def _package(out_root: Path, extension_dir: Path, report_path: Path, source_manifest_path: Path,
             source_report_path: Path, source_run_id: str) -> Path:
    run_id = re_safe(os.environ.get("GITHUB_RUN_ID", "local"))
    attempt = re_safe(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    bundle = out_root / f"sarguardian-extended-science-{source_run_id}-{run_id}-{attempt}.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(extension_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".h5", ".hdf5"}:
                raise ExtensionError("RAW_HDF5_REFUSED_IN_EXTENSION_PACKAGE")
            archive.write(path, f"results/{path.relative_to(extension_dir).as_posix()}")
        archive.write(report_path, "science-extension-report.json")
        archive.write(source_manifest_path, "source-run-manifest.json")
        archive.write(source_report_path, "source-batch-equivalence-report.json")
    return bundle


def re_safe(value: str) -> str:
    import re
    return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) else "invalid"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", required=True, type=Path)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--science-root", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args()

    science_root = args.science_root.resolve()
    source_bundle = args.source_bundle.resolve()
    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    extension_dir = science_root / "outputs" / "extended_science"
    report_path = out_root / "science-extension-report.json"
    source_manifest_path = out_root / "source-run-manifest.json"
    source_report_path = out_root / "source-batch-equivalence-report.json"
    report: dict[str, Any] = {
        "schema_version": "sarguardian-extended-science/1.0",
        "started_utc": _utc_now(),
        "source_run_id": args.source_run_id,
        "science_commit": PINNED_SCIENCE_COMMIT,
        "aoi": "source",
        "raw_hdf5_required_for_extensions": False,
        "raw_hdf5_extracted": 0,
        "stages": {},
        "commands": [],
        "warnings": [],
    }
    try:
        manifest, source_report, raw_hdf5_skipped = validate_and_extract_bundle(
            source_bundle, args.source_run_id, science_root, out_root
        )
        report["source_run_manifest_id"] = manifest.get("run_id")
        report["source_run_batch_equivalence_status"] = source_report.get("status")
        report["source_products_validated"] = source_report.get("products_validated")
        report["source_retention_profile"] = manifest.get("retention_profile")
        report["raw_hdf5_members_skipped_not_extracted"] = raw_hdf5_skipped

        # Result 4 (GOFF time series) and Result 5 (troposphere reports) were
        # freshly reconstructed from per-product TIFFs during the source run.
        required_r45 = [
            science_root / "outputs" / name for name in (
                "ts_goff_source.csv", "ts_gunw_source.csv",
                "troposphere_gunw_source.csv", "troposphere_goff_source.csv",
                "local_floor_candidates.csv", "local_floor_phase_candidates.csv",
                "common_ref_summer.csv", "bound_source.csv",
            )
        ]
        r45_ok = all(p.is_file() and p.stat().st_size > 0 for p in required_r45)
        report["stages"]["result_4_5_inherited_from_verified_bundle"] = {
            "status": "PASS" if r45_ok else "FAIL",
            "outputs": [str(p.relative_to(science_root)) for p in required_r45],
            "ts_gunw_source_csv_parity": "GENERATED_NO_COMMITTED_BASELINE",
            "source": "source-run aggregation from AOI-clipped GeoTIFFs; no raw HDF5 required",
        }

        run_model_detectability(science_root, extension_dir, report)
        run_geometry_sensitivity(science_root, extension_dir, report)
        run_impoundment_sensitivity(science_root, extension_dir, report)
        _, mapping_passed = run_sentinel_scar_mapping(science_root, extension_dir, report)
        if mapping_passed:
            run_fresh_result_7(
                science_root, extension_dir, report,
                extension_dir / "scar_candidates_source.csv",
            )
        else:
            report["stages"]["result_7_fresh_candidate_floors_and_final_bound"] = {
                "status": "SKIPPED", "reason": "fresh Sentinel-2 candidate map did not produce a verified candidate CSV",
            }
    except Exception as exc:
        report.setdefault("fatal_errors", []).append({
            "type": type(exc).__name__, "detail": str(exc)[:500],
        })
        if not extension_dir.exists():
            extension_dir.mkdir(parents=True, exist_ok=True)
        report.setdefault("stages", {}).setdefault("source_bundle_validation", {
            "status": "FAIL", "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
        })

    report["finished_utc"] = _utc_now()
    report["outputs"] = _hash_outputs(extension_dir) if extension_dir.exists() else []
    report["status"] = (
        "PASS"
        if not report.get("fatal_errors")
        and all(stage.get("status") == "PASS"
                for stage in report.get("stages", {}).values())
        else "FAIL"
    )
    report["bundle_file"] = f"sarguardian-extended-science-{args.source_run_id}-{re_safe(os.environ.get('GITHUB_RUN_ID', 'local'))}-{re_safe(os.environ.get('GITHUB_RUN_ATTEMPT', '1'))}.zip"

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if source_manifest_path.is_file() and source_report_path.is_file():
        try:
            bundle = _package(out_root, extension_dir, report_path, source_manifest_path, source_report_path, args.source_run_id)
            report["bundle_file"] = bundle.name
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            bundle.unlink(missing_ok=True)
            bundle = _package(out_root, extension_dir, report_path, source_manifest_path, source_report_path, args.source_run_id)
        except Exception as exc:
            report["status"] = "FAIL"
            report.setdefault("fatal_errors", []).append({
                "type": type(exc).__name__, "detail": str(exc)[:300],
            })
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            bundle = None
    else:
        bundle = None

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as stream:
            stream.write(f"status={report['status']}\n")
            if bundle:
                stream.write(f"bundle_path={bundle}\n")
            stream.write(f"report_path={report_path}\n")

    print(f"EXTENDED_SCIENCE_STATUS={report['status']}")
    print(f"EXTENDED_SCIENCE_STAGES={len(report.get('stages', {}))}")
    print(f"SOURCE_RUN_ID={args.source_run_id}")
    print("RAW_HDF5_EXTRACTED=0")
    print(f"REPORT_PATH={report_path}")
    print(f"BUNDLE_PATH={bundle if bundle else 'NOT_CREATED'}")
    if report["status"] != "PASS":
        print("ERROR=EXTENDED_SCIENCE_PIPELINE_FAILED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
