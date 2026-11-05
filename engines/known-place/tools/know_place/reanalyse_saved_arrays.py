"""Recompute coherence and exploratory controls from a hashed analysis NPZ bundle.

This is a post-processing path for saved derived diagnostic arrays. It never
claims to re-read raw HDF5 or retroactively changes the source report. Each
array bundle must match the SHA-256 recorded in that report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .analyze import _coherence_sensitivity, _report_controls
from .goff_io import GoffReadError
from .paper_method import directional_coherence, summarize_crown

REPORT_SCHEMA = "know-place-analysis-report/1.0"
TARGET_PAIR = ("2026-07-26", "2026-08-19")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def reanalyse_saved_arrays(
    report_path: str | Path,
    arrays_dir: str | Path,
    output_path: str | Path,
    *,
    source_run_id: str | int | None = None,
) -> dict[str, Any]:
    """Validate every NPZ digest and recompute R policy sensitivity/control metrics."""
    report_file = Path(report_path).expanduser().resolve()
    arrays_root = Path(arrays_dir).expanduser().resolve()
    output_file = Path(output_path).expanduser().resolve()
    if not report_file.is_file():
        raise GoffReadError("SOURCE_REPORT_NOT_FOUND")
    try:
        original = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoffReadError(f"SOURCE_REPORT_INVALID:{type(exc).__name__}") from exc
    if original.get("schema_version") != REPORT_SCHEMA:
        raise GoffReadError("SOURCE_REPORT_SCHEMA_MISMATCH")
    if original.get("structural_status") != "PASS":
        raise GoffReadError("SOURCE_REPORT_STRUCTURAL_STATUS_NOT_PASS")
    source_products = original.get("products")
    if not isinstance(source_products, list) or len(source_products) != 5:
        raise GoffReadError("SOURCE_REPORT_MUST_CONTAIN_EXACTLY_FIVE_PAIRS")

    scope = original.get("run_scope") or {}
    seed = int(scope.get("control_seed", 260826))
    draws = int(scope.get("control_draws", 1000))
    pairs: list[dict[str, Any]] = []

    for item in source_products:
        if item.get("status") != "METRICS_COMPUTED":
            raise GoffReadError(
                "SOURCE_PAIR_METRICS_NOT_COMPUTED:"
                + str(item.get("reference_date")) + "->" + str(item.get("secondary_date"))
            )
        filename = str(item.get("diagnostic_arrays_file") or "")
        if not filename or Path(filename).name != filename or not filename.endswith(".npz"):
            raise GoffReadError("DIAGNOSTIC_ARRAYS_FILENAME_INVALID")
        array_path = arrays_root / filename
        if not array_path.is_file():
            raise GoffReadError("DIAGNOSTIC_ARRAYS_FILE_MISSING:" + filename)
        expected_hash = str(item.get("diagnostic_arrays_sha256") or "").lower()
        actual_hash = _sha256(array_path)
        if len(expected_hash) != 64 or actual_hash != expected_hash:
            raise GoffReadError("DIAGNOSTIC_ARRAYS_SHA256_MISMATCH:" + filename)

        try:
            with np.load(array_path, allow_pickle=False) as data:
                required = {
                    "east_m", "north_m", "horizontal_magnitude_m", "valid_mask",
                    "reference_box_mask", "crown_mask", "x_coordinates_m", "y_coordinates_m",
                }
                if not required.issubset(set(data.files)):
                    missing = sorted(required - set(data.files))
                    raise GoffReadError("DIAGNOSTIC_ARRAYS_REQUIRED_FIELD_MISSING:" + ",".join(missing))
                east = np.asarray(data["east_m"], dtype=float)
                north = np.asarray(data["north_m"], dtype=float)
                magnitude = np.asarray(data["horizontal_magnitude_m"], dtype=float)
                valid_centres = np.asarray(data["valid_mask"], dtype=bool)
                box = np.asarray(data["reference_box_mask"], dtype=bool)
                crown = np.asarray(data["crown_mask"], dtype=bool)
                x = np.asarray(data["x_coordinates_m"], dtype=float)
                y = np.asarray(data["y_coordinates_m"], dtype=float)
        except (OSError, ValueError) as exc:
            if isinstance(exc, GoffReadError):
                raise
            raise GoffReadError("DIAGNOSTIC_ARRAYS_UNREADABLE:" + filename) from exc

        shape = east.shape
        if east.ndim != 2 or any(a.shape != shape for a in (north, magnitude, valid_centres, box, crown)):
            raise GoffReadError("DIAGNOSTIC_ARRAYS_SHAPE_MISMATCH:" + filename)
        if x.ndim != 1 or y.ndim != 1 or len(x) != shape[1] or len(y) != shape[0]:
            raise GoffReadError("DIAGNOSTIC_ARRAYS_COORDINATE_SHAPE_MISMATCH:" + filename)
        if np.any(crown & ~box) or np.any(valid_centres & ~box):
            raise GoffReadError("DIAGNOSTIC_ARRAYS_MASK_RELATIONSHIP_INVALID:" + filename)
        context_valid = np.isfinite(east) & np.isfinite(north)
        if not np.any(valid_centres & crown & context_valid):
            raise GoffReadError("DIAGNOSTIC_ARRAYS_NO_VALID_CROWN_CENTRES:" + filename)

        coherence = directional_coherence(
            east, north, context_valid, window_size=5, minimum_valid_cells=1,
        )
        stats = summarize_crown(
            east, north, valid_centres & box, crown, coherence,
            interval_days=int(item["interval_days"]),
        )
        valid_box = valid_centres & box & context_valid
        full_box_R = coherence[valid_box & np.isfinite(coherence)]
        outside = valid_box & ~crown & np.isfinite(coherence)
        sensitivity = _coherence_sensitivity(
            east, north, context_valid, valid_box, box, crown, magnitude,
            include_published_magnitude_window=(
                str(item.get("reference_date")), str(item.get("secondary_date"))
            ) == TARGET_PAIR,
        )
        control = _report_controls(
            magnitude, coherence, valid_box, box, crown,
            crown_median=float(stats["crown_median_horizontal_magnitude_m"]),
            crown_R=_finite_float(stats.get("crown_median_directional_coherence_R")),
            pixel_size_x_m=float(np.median(np.abs(np.diff(x)))),
            pixel_size_y_m=float(np.median(np.abs(np.diff(y)))),
            draws=draws, seed=seed,
        )
        original_stats = item.get("crown_statistics") or {}
        pairs.append({
            "pair": item.get("pair"),
            "granule_name": item.get("granule_name"),
            "source_sha256": item.get("source_sha256"),
            "diagnostic_arrays_file": filename,
            "diagnostic_arrays_sha256_verified": actual_hash,
            "original_report_R_minimum_valid_neighbours": (
                (item.get("coherence_policy") or {}).get("minimum_valid_direction_vectors_per_window")
            ),
            "reanalysed_primary_R_minimum_valid_neighbours": 1,
            "crown_statistics_R_min1": stats,
            "reference_box_median_R_min1": (
                float(np.median(full_box_R)) if full_box_R.size else None
            ),
            "outside_crown_median_R_min1": (
                float(np.median(coherence[outside])) if outside.any() else None
            ),
            "coherence_sensitivity": sensitivity,
            "exploratory_controls_R_min1": control,
            "unchanged_scalar_check": {
                "original_crown_median_horizontal_magnitude_m": original_stats.get(
                    "crown_median_horizontal_magnitude_m"
                ),
                "reanalysed_crown_median_horizontal_magnitude_m": stats.get(
                    "crown_median_horizontal_magnitude_m"
                ),
                "absolute_difference_magnitude_m": abs(
                    float(stats["crown_median_horizontal_magnitude_m"])
                    - float(original_stats["crown_median_horizontal_magnitude_m"])
                ) if original_stats.get("crown_median_horizontal_magnitude_m") is not None else None,
            },
        })

    output = {
        "schema_version": "know-place-coherence-reanalysis/1.0",
        "project": "Know Place Analysis",
        "status": "REANALYSIS_ONLY_DIAGNOSTIC_ARRAYS",
        "source_run_id": str(source_run_id) if source_run_id is not None else None,
        "source_report_sha256": _sha256(report_file),
        "source_report_schema": original["schema_version"],
        "source_structural_status": original.get("structural_status"),
        "source_paper_reproduction_status": original.get("paper_reproduction_status"),
        "method_note": (
            "Recomputes only 5x5 directional coherence and the exploratory controls "
            "from hash-verified saved diagnostic arrays. It does not re-read raw HDF5, "
            "replace the original report, establish author-supplement parity, or evaluate "
            "a hazard alarm. The primary one-neighbour policy is an explicit estimator "
            "choice because the preprint does not report a minimum-neighbour rule."
        ),
        "coherence_policy_sensitivity_thresholds": [1, 5, 10, 15, 20, 25],
        "published_common_displacement_window_m": [0.17, 2.75],
        "products": pairs,
        "paper_reproduction_status": "BLOCKED_AUTHOR_GEOMETRY_VARIANT_AND_GOLDEN_OUTPUTS_UNVERIFIED",
        "hazard_detection_status": "NOT_EVALUATED",
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reanalyse saved, hash-verified Know Place NPZ outputs without raw-data downloads."
    )
    parser.add_argument("--report", required=True, help="Original know-place-analysis-report.json")
    parser.add_argument("--arrays-dir", required=True, help="Directory containing the named diagnostic NPZ files")
    parser.add_argument("--out", required=True, help="Destination JSON for the separate reanalysis report")
    parser.add_argument("--source-run-id", default=None, help="Original GitHub Actions run ID, for provenance")
    args = parser.parse_args()
    try:
        result = reanalyse_saved_arrays(
            args.report, args.arrays_dir, args.out, source_run_id=args.source_run_id,
        )
    except GoffReadError as exc:
        print(f"ERROR={str(exc).split(':', 1)[0]}")
        return 2
    print("REANALYSIS_STATUS=" + str(result["status"]))
    print("INPUT_ARRAY_BUNDLES_VERIFIED=" + str(len(result["products"])))
    print("PAPER_REPRODUCTION_STATUS=" + str(result["paper_reproduction_status"]))
    print("HAZARD_DETECTION_STATUS=" + str(result["hazard_detection_status"]))
    print("REPORT=" + str(Path(args.out).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
