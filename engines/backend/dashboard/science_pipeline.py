"""AOI-specific scientific stage eligibility and network diagnostics.

This module reports which pinned SARGuardian analyses actually ran and which
must be withheld for the current dynamic-AOI contract. It deliberately does not
turn pairwise reader medians into a common-reference time series.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
import sys
from typing import Any


def _valid_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def build_science_pipeline_report(
    products: list[dict[str, Any]],
    science_root: Path,
    science_diagnostics: dict[str, Any] | None,
    site_context: dict[str, Any] | None = None,
    common_reference_report: dict[str, Any] | None = None,
    aoi_displacement_candidates: dict[str, Any] | None = None,
    aoi_relative_pixel_timeseries: dict[str, Any] | None = None,
    aoi_wide_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run time-series network topology analysis and gate downstream methods.

    Network topology uses the pinned timeseries.py implementation. Numeric
    inversion is intentionally withheld because pair-wise exports do not prove
    that each acquisition pair used the same stable-ground reference datum.
    """
    report: dict[str, Any] = {
        "schema_version": "sarguardian-science-pipeline-readiness/1.0",
        "science_commit_expected": None,
        "structural_validation_is_geophysical_validation": False,
        "network_assessment_status": "NOT_STARTED",
        "networks": [],
        "modules": [],
        "warnings": [
            "This is a stage-eligibility report, not a hazard declaration.",
            "Pairwise medians from independently referenced products are not a common-datum time series.",
        ],
    }
    diagnostics = science_diagnostics if isinstance(science_diagnostics, dict) else {}
    stack = diagnostics.get("pixel_stack") if isinstance(diagnostics.get("pixel_stack"), dict) else {}
    candidate = diagnostics.get("candidate_checks") if isinstance(diagnostics.get("candidate_checks"), dict) else {}

    gunw_count = sum(str(row.get("product_type", "")).upper() == "GUNW" for row in products)
    goff_count = sum(str(row.get("product_type", "")).upper() == "GOFF" for row in products)
    report["product_counts"] = {"GUNW": gunw_count, "GOFF": goff_count, "total": len(products)}
    report["modules"].extend([
        {
            "name": "gunw_reader.py",
            "status": "EXECUTED_PER_PRODUCT" if gunw_count else "NO_GUNW_PRODUCTS",
            "products": gunw_count,
            "produces": "LOS displacement and coherence rasters/statistics",
            "limitation": "LOS displacement is relative to the product's reference; it is not direct 3-D motion.",
        },
        {
            "name": "goff_reader.py",
            "status": "EXECUTED_PER_PRODUCT" if goff_count else "NO_GOFF_PRODUCTS",
            "products": goff_count,
            "produces": "range/along-track offsets, correlation/quality metrics and pair-specific detection floors where available",
            "limitation": "Offsets require geometry-aware interpretation and are not interchangeable with GUNW phase measurements.",
        },
    ])

    src = str((Path(science_root).resolve() / "src"))
    if src not in sys.path:
        sys.path.insert(0, src)

    pairs = []
    invalid = []
    structures: dict[str, Any] = {}
    network_error = None
    try:
        import timeseries
        for row in products:
            name = str(row.get("granule_name") or "")
            meta = timeseries.granule_metadata(name)
            ref = _valid_date(row.get("reference_date"))
            sec = _valid_date(row.get("secondary_date"))
            if meta is None or ref is None or sec is None or sec <= ref:
                invalid.append({
                    "product_id": row.get("id"),
                    "granule_name": name,
                    "reason": "Granule identity or acquisition dates are not parseable by the pinned time-series engine.",
                })
                continue
            pairs.append(timeseries.Pair(
                path=meta["path"],
                direction=meta["direction"],
                ref=ref,
                sec=sec,
                value=None,
                n_px=row.get("valid_pixels"),
                coherence=(row.get("stats") or {}).get("mean_coherence"),
                source=name,
                metadata=meta,
            ))
        if pairs:
            captured = StringIO()
            with redirect_stdout(captured):
                structures = timeseries.describe_network(pairs)
            report["network_assessment_status"] = "COMPLETED"
        else:
            report["network_assessment_status"] = "NO_PARSEABLE_PAIRS"
    except Exception as exc:
        network_error = type(exc).__name__ + ":" + str(exc)[:250]
        report["network_assessment_status"] = "UNAVAILABLE"
    report["invalid_pair_rows"] = invalid
    report["site_context"] = site_context or {}
    common_reference_report = common_reference_report if isinstance(common_reference_report, dict) else {}
    aoi_displacement_candidates = aoi_displacement_candidates if isinstance(aoi_displacement_candidates, dict) else {}
    aoi_relative_pixel_timeseries = aoi_relative_pixel_timeseries if isinstance(aoi_relative_pixel_timeseries, dict) else {}
    aoi_wide_screen = aoi_wide_screen if isinstance(aoi_wide_screen, dict) else {}
    report["common_reference_timeseries"] = common_reference_report
    report["aoi_displacement_candidates"] = aoi_displacement_candidates
    report["aoi_relative_pixel_timeseries"] = aoi_relative_pixel_timeseries
    report["aoi_wide_displacement_screen"] = aoi_wide_screen
    report["network_assessment_log_excerpt"] = captured.getvalue()[-8000:] if "captured" in locals() else ""
    report["network_error"] = network_error

    for label, components in sorted(structures.items()):
        for index, component in enumerate(components, 1):
            epochs = component.get("epochs", [])
            pairs_n = int(component.get("n_pairs", 0))
            redundancy = int(component.get("redundancy", pairs_n - max(0, len(epochs) - 1)))
            report["networks"].append({
                "geometry": label,
                "component": index,
                "first_epoch": epochs[0] if epochs else None,
                "last_epoch": epochs[-1] if epochs else None,
                "epochs": epochs,
                "n_epochs": len(epochs),
                "n_pairs": pairs_n,
                "redundancy": redundancy,
                "formal_residual_error_estimable": redundancy > 0,
                "topology_status": "REDUNDANT" if redundancy > 0 else "EXACTLY_DETERMINED_NO_REDUNDANCY",
            })

    target_info = (site_context or {}).get("measurement_target", {})
    target_status = (target_info.get("status") or "NOT_PROVIDED") if isinstance(target_info, dict) else "NOT_PROVIDED"
    measured_targets = sum(
        isinstance(row.get("target_measurement"), dict)
        and row["target_measurement"].get("status") == "MEASURED"
        for row in products
    )
    measured_floors = sum(
        isinstance(row.get("local_floor"), dict)
        and row["local_floor"].get("status") == "MEASURED"
        for row in products
    )
    if target_status == "IN_AOI_TARGET_CAPTURED":
        local_floor_status = "PAIRWISE_LOCAL_FLOOR_MEASURED" if measured_floors else "TARGET_CAPTURED_FLOOR_UNAVAILABLE"
        local_floor_reason = (
            f"An in-AOI point was supplied. {measured_targets} product(s) have target-window measurements and "
            f"{measured_floors} have a measured radius-6 local noise floor. These are pair-specific values in each reader's "
            "reference frame; they do not provide a shared stable-ground datum or authorize cumulative inversion."
        )
    elif target_status == "NOT_PROVIDED":
        candidate_floor_measurements = int(aoi_displacement_candidates.get("candidate_local_floor_measurements") or 0)
        candidate_rows = aoi_displacement_candidates.get("features")
        has_candidate_features = isinstance(candidate_rows, list) and bool(candidate_rows)
        if candidate_floor_measurements:
            local_floor_status = "CANDIDATE_REGION_LOCAL_FLOORS_MEASURED"
            local_floor_reason = (
                f"Find Displacements automatically measured {candidate_floor_measurements} candidate/interval local residual floor(s) "
                "from valid nearby background pixels; no user target was required. These are pair-specific detectability diagnostics, "
                "not observed motion and not independently validated stable-ground noise."
            )
        elif has_candidate_features:
            local_floor_status = "WITHHELD_INSUFFICIENT_CANDIDATE_LOCAL_BACKGROUND"
            local_floor_reason = (
                f"{len(candidate_rows)} target-free candidate feature(s) were found, but none had the minimum 30 valid nearby "
                "background pixels needed for a candidate-local 3-sigma floor. The candidates remain review leads; their local "
                "detectability is not measured and must not be interpreted as zero noise or zero movement."
            )
        else:
            local_floor_status = "NOT_REQUIRED_FOR_TARGET_FREE_FIND_DISPLACEMENTS"
            local_floor_reason = (
                "Find Displacements is target-free. A point-local floor is not a prerequisite for AOI-wide discovery; "
                "GOFF uses its per-pair reader floor where available and GUNW uses spatially screened per-pixel evidence. "
                "No point coordinate or point-local measurement is invented. No candidate region was available for a candidate-local floor."
            )
    else:
        local_floor_status = "BLOCKED_INVALID_OR_OUTSIDE_TARGET"
        local_floor_reason = f"Target context was rejected or incomplete ({target_status}); no target-specific inference is allowed."

    has_diagnostic_series = common_reference_report.get("status") == "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED"
    has_common_datum = common_reference_report.get("status") in {
        "COMMON_DATUM_PAIRWISE_ONLY", "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED",
    }
    if has_diagnostic_series:
        timeseries_status = "DIAGNOSTIC_CUMULATIVE_LOS_SERIES_COMPUTED_REFERENCE_UNVALIDATED"
        timeseries_reason = (
            "A common-grid, common-pixel GUNW stack was re-referenced and at least one connected, redundant component passed the pinned graph solver and leave-one-out velocity-sign check. "
            "This is still diagnostic only: its zero is the median of common-valid AOI pixels outside the target buffer, not an independently surveyed stable-ground reference."
        )
    elif has_common_datum:
        timeseries_status = "COMMON_DATUM_PAIRWISE_ONLY_NO_PUBLISHABLE_CUMULATIVE_SERIES"
        timeseries_reason = str(common_reference_report.get("reason") or "Common datum was computed but no component met cumulative-series publication gates.")
    else:
        timeseries_status = "NETWORK_TOPOLOGY_ONLY_INVERSION_WITHHELD" if pairs else report["network_assessment_status"]
        if target_status == "NOT_PROVIDED":
            timeseries_reason = (
                "The legacy timeseries.py region-mean path reports acquisition topology only and does not create a target-free per-pixel series. "
                "Find Displacements uses aoi_relative_pixel_timeseries.py for that purpose; its result is recorded separately, and only eligible "
                "connected/redundant GUNW networks with common valid spatial support produce a diagnostic series."
            )
        else:
            timeseries_reason = (
                "The point-aware series did not satisfy the common-grid, common-reference-pixel, target-support and/or robust redundant-network gate. "
                "No cumulative values were inferred."
                if pairs else "Pair topology could not be assessed from the supplied product identities and acquisition dates."
            )
    common_status = str(common_reference_report.get("status") or "NOT_REPORTED")
    if target_status == "NOT_PROVIDED" and common_status == "NOT_RUN_TARGET_FREE_FIND_DISPLACEMENTS":
        common_status = "NOT_REQUIRED_FOR_TARGET_FREE_FIND_DISPLACEMENTS"
    candidate_features = [
        feature for feature in (aoi_displacement_candidates.get("features") or [])
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
    ]
    candidate_properties = [feature["properties"] for feature in candidate_features]
    candidate_screen_status = str(aoi_displacement_candidates.get("status") or "NOT_REPORTED")
    phase_review_count = sum(
        isinstance(row.get("candidate_phase_ceiling_review"), dict)
        and row["candidate_phase_ceiling_review"].get("status") == "EXCEEDS_SINGLE_FRINGE_REVIEW_THRESHOLD"
        for row in candidate_properties
    )
    multi_season_count = sum(
        isinstance(row.get("candidate_seasonality_inventory"), dict)
        and row["candidate_seasonality_inventory"].get("status") == "MULTI_SEASON_SUPPORT_PRESENT"
        for row in candidate_properties
    )
    if candidate.get("status") == "SKIPPED_UNSUPPORTED_CUSTOM_AOI":
        if candidate_features:
            candidate_check_status = "PARTIAL_TARGET_FREE_CANDIDATE_STRESS_TESTS_WITH_CROSS_GEOMETRY_WITHHELD"
            candidate_check_reason = (
                "The target-free path reports pairwise spatial differential, candidate-local 3-sigma floors, season-coverage inventory "
                "and GUNW single-fringe review flags. These are triage checks, not a statistically conclusive seasonal test. "
                "Cross-geometry motion-vs-delay validation remains withheld without pixelwise look vectors and rate covariance."
            )
        elif candidate_screen_status == "NO_CANDIDATES_AT_CONFIGURED_THRESHOLD":
            candidate_check_status = "NOT_APPLICABLE_NO_CANDIDATES_AT_SCREEN_THRESHOLD"
            candidate_check_reason = "No spatial candidate reached the configured review threshold, so candidate-level stress tests were not applicable; this does not prove zero movement."
        elif candidate_screen_status == "NO_ELIGIBLE_RASTER_EXPORTS":
            candidate_check_status = "NOT_TESTABLE_NO_ELIGIBLE_RASTER_EXPORTS"
            candidate_check_reason = "The target-free candidate screen had no eligible raster exports; candidate-level stress tests could not be run."
        else:
            candidate_check_status = "NOT_TESTABLE_TARGET_FREE_CANDIDATE_SCREEN_UNAVAILABLE"
            candidate_check_reason = "The legacy named-AOI target stress test is not applicable to this WKT and the target-free candidate screen did not provide candidate features."
    else:
        candidate_check_status = str(candidate.get("status") or "NOT_REPORTED")
        candidate_check_reason = str(candidate.get("detail") or "Inspect saved candidate diagnostics.")
    report["modules"].extend([
        {
            "name": "common_ref.py",
            "status": common_status,
            "reason": str(common_reference_report.get("reason") or "See common-reference-timeseries.json for per-network grid, mask, target-support and common-pixel checks."),
            "stable_ground_independently_validated": False,
            "scope": "OPTIONAL_KNOWN_PLACE_POINT_DIAGNOSTIC",
            "interpretation": "The point-buffered common-datum calculation is optional for Known Place Analysis. It is deliberately not a gate on target-free Find Displacements.",
        },
        {
            "name": "timeseries.py",
            "status": (
                "AOI_RELATIVE_PIXEL_DIAGNOSTIC_AVAILABLE_REFERENCE_UNVALIDATED"
                if aoi_relative_pixel_timeseries.get("status") == "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE"
                else timeseries_status
            ),
            "legacy_pair_graph_status": timeseries_status,
            "aoi_relative_pixel_timeseries_status": str(aoi_relative_pixel_timeseries.get("status") or "NOT_REPORTED"),
            "pairs_parsed": len(pairs),
            "networks": len(structures),
            "reason": timeseries_reason,
            "minimum_next_evidence": "For an independently validated movement series, supply/validate a stable-ground reference or external stable-area evidence and verify the AOI-derived datum sensitivity; do not use a diagnostic line as a hazard alert.",
        },
        {
            "name": "local_floor.py",
            "scope": "OPTIONAL_POINT_LOCAL_DIAGNOSTIC_WITH_TARGET_FREE_CANDIDATE_EXTENSION",
            "implementation": "Target-free candidate-region floors are calculated by dashboard/aoi_displacement_candidates.py::_candidate_local_floor_rows; src/local_floor.py remains the selected-point CLI.",
            "status": local_floor_status,
            "reason": local_floor_reason,
            "products_with_measured_local_floor": measured_floors,
            "products_with_target_window_measurement": measured_targets,
            "candidate_region_local_floor_measurements": int(aoi_displacement_candidates.get("candidate_local_floor_measurements") or 0),
            "available_related_metrics": "A local floor is a pair-specific detectability/noise estimate, not observed motion or a common-reference time series.",
        },
        {
            "name": "inverse_velocity.py",
            "scope": "CANDIDATE_OR_KNOWN_PLACE_ACCELERATION_ANALYSIS",
            "status": "WITHHELD_NO_CANDIDATE_SERIES_ON_INDEPENDENT_REFERENCE",
            "reason": "Candidate-local pair floors are now measured where background support allows, but no candidate-specific cumulative time series is tied to an independently validated stable-ground reference. An AOI-relative LOS series alone cannot support a failure-time forecast; the inverse-velocity fit remains withheld.",
        },
        {
            "name": "geometry_merge.py",
            "scope": "OPTIONAL_MULTI_GEOMETRY_PHYSICAL_INTERPRETATION",
            "status": "WITHHELD_NO_PIXELWISE_LOOK_VECTORS_AND_TERRAIN_REFERENCE",
            "reason": "The current AOI raster contract exports LOS displacement but not a co-registered per-pixel look-vector solution plus validated terrain slope/aspect and matched ASC/DESC uncertainty/covariance. A numeric 2-D or 3-D merge cannot be inferred from track labels alone.",
        },
        {
            "name": "bound.py",
            "scope": "KNOWN_PLACE_EVENT_SPECIFIC_ONLY",
            "status": "NOT_APPLICABLE_GENERIC_AOI_BY_DESIGN",
            "reason": "This module uses fixed source-event, published-candidate and event-date priors. Applying those constants to an arbitrary user AOI would be scientifically invalid; it remains in Known Place Analysis only.",
        },
        {
            "name": "pixel_stack.py",
            "status": str(stack.get("status") or "NOT_REPORTED"),
            "interpretation": str(stack.get("interpretation") or "Inspect the saved science-diagnostics.json and pixel-stack log."),
        },
        {
            "name": "candidate_check.py",
            "scope": "KNOWN_PLACE_LEGACY_STRESS_TEST_WITH_TARGET_FREE_PARTIAL_REVIEW",
            "status": candidate_check_status,
            "candidate_features_reviewed": len(candidate_features),
            "features_with_multi_season_acquisition_support": multi_season_count,
            "features_exceeding_gunw_single_fringe_review_threshold": phase_review_count,
            "cross_geometry_validation": "WITHHELD_NO_PIXELWISE_LOOK_VECTOR_AND_RATE_COVARIANCE" if candidate.get("status") == "SKIPPED_UNSUPPORTED_CUSTOM_AOI" else "SEE_KNOWN_PLACE_DIAGNOSTIC",
            "reason": candidate_check_reason,
        },
    ])
    report["modules"].extend([
        {
            "name": "aoi_wide_displacement_screen.py",
            "status": str(aoi_wide_screen.get("status") or "NOT_REPORTED"),
            "purpose": "FIND_DISPLACEMENTS_AOI_WIDE",
            "target_required": False,
            "candidate_count": int(aoi_wide_screen.get("candidate_count") or 0),
            "series_count": int(aoi_wide_screen.get("series_count") or 0),
            "reason": str(aoi_wide_screen.get("reason") or "See aoi-wide-displacement-screen/screen-summary.json."),
            "interpretation": "GOFF-only offset-anomaly review candidates; offsets are not ground displacement or 3-D motion.",
        },
        {
            "name": "aoi_displacement_candidates.py",
            "status": str(aoi_displacement_candidates.get("status") or "NOT_REPORTED"),
            "target_required": False,
            "candidate_features": int(aoi_displacement_candidates.get("candidate_features") or 0),
            "products_examined": int(aoi_displacement_candidates.get("products_examined") or 0),
            "reason": str(aoi_displacement_candidates.get("reason") or "See aoi-displacement-candidates.json."),
            "interpretation": "Target-free GUNW LOS and GOFF offset spatial anomaly candidates. Metric families remain separate; candidate does not mean confirmed motion.",
        },
        {
            "name": "aoi_relative_pixel_timeseries.py",
            "status": str(aoi_relative_pixel_timeseries.get("status") or "NOT_REPORTED"),
            "target_required": False,
            "networks_calculated": int(aoi_relative_pixel_timeseries.get("networks_calculated") or 0),
            "networks_examined": len(aoi_relative_pixel_timeseries.get("networks") or []),
            "reference_independently_validated": bool(aoi_relative_pixel_timeseries.get("reference_independently_validated", False)),
            "reason": str(aoi_relative_pixel_timeseries.get("reason") or "See aoi-relative-pixel-timeseries.json."),
            "interpretation": "Target-free per-pixel GUNW LOS inversion; only eligible redundant networks produce maps. AOI-derived zero is not independent stable ground.",
        },
    ])
    candidate_screen_completed = candidate_screen_status in {
        "REPEATED_SPATIAL_CANDIDATES_NEED_GEOPHYSICAL_VALIDATION",
        "SINGLE_PAIR_CANDIDATES_NEED_TEMPORAL_CONFIRMATION",
        "NO_CANDIDATES_AT_CONFIGURED_THRESHOLD",
    }
    goff_screen_status = str(aoi_wide_screen.get("status") or "NOT_REPORTED")
    goff_screen_completed = goff_screen_status in {
        "COMPLETED_EXPLORATORY_RANKING",
        "INSUFFICIENT_TEMPORAL_SUPPORT",
    }
    report["overall_status"] = (
        "AOI_RELATIVE_PIXEL_DIAGNOSTICS_AVAILABLE_REFERENCE_UNVALIDATED"
        if aoi_relative_pixel_timeseries.get("status") == "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE"
        else (
            "AOI_WIDE_TARGET_FREE_SCREEN_COMPLETED_GUNW_STACK_WITHHELD"
            if candidate_screen_completed or goff_screen_completed
            else (
                "NETWORK_ASSESSED_WITH_DOWNSTREAM_STAGES_WITHHELD"
                if report["network_assessment_status"] == "COMPLETED"
                else "PARTIAL_STAGE_ASSESSMENT"
            )
        )
    )
    return report
