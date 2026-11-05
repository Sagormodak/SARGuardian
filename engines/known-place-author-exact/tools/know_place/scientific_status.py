"""Conservative status assessment for the author site and footprint replay gates."""
from __future__ import annotations

from typing import Any

FOOTPRINT_PASS = "PASS_AUTHOR_AGGREGATE_RASTERS_AND_CANDIDATE_INVENTORY"
PAPER_PARTIAL_MATCH = "PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED"
BLOCKED_INCOMPLETE = "BLOCKED_AUTHOR_SITE_OR_FOOTPRINT_EVIDENCE_INCOMPLETE_DISPLACEMENT_NULL_STILL_UNVERIFIED"


def _comparison_passes(value: Any, expected_count: int) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("status") == "PASS_AT_ARCHIVE_ROUNDING"
        and value.get("checks_passed") == expected_count
        and value.get("checks_total") == expected_count
        and value.get("mismatch_count") == 0
    )


def _comparison_is_definitive_mismatch(value: Any, expected_count: int) -> bool:
    """Only classify a result as mismatch when its expected comparison set was actually evaluated."""
    if not isinstance(value, dict) or value.get("checks_total") != expected_count:
        return False
    return (
        value.get("status") == "MISMATCH"
        or value.get("mismatch_count", 0) > 0
        or value.get("checks_passed") != expected_count
    )


def assess_reproduction_status(
    status: dict[str, Any],
    site: dict[str, Any],
    footprint: dict[str, Any],
) -> dict[str, Any]:
    """Keep parity mismatch distinct from missing/incomplete evidence."""
    inventory = footprint.get("author_inventory_comparison", {})
    table7 = footprint.get("author_validated_zone_table_comparison", {})
    raster = footprint.get("author_aggregate_raster_comparison", {})
    score_audit = inventory.get("score_formula_audit", {})

    footprint_pass = (
        footprint.get("status") == "FOOTPRINT_SCREEN_COMPUTED"
        and footprint.get("footprint_screen_parity_status") == FOOTPRINT_PASS
        and raster.get("status") == "PASS"
        and raster.get("raster_count") == 3
        and raster.get("rasters_passed") == 3
        and inventory.get("status") == "PASS"
        and inventory.get("expected_candidate_count") == 106
        and inventory.get("computed_candidate_count") == 106
        and inventory.get("computed_quality_pass_count") == 101
        and score_audit.get("status") == "PASS_POSTPROCESSED_AUTHOR_SCORE_CONVENTION"
        and inventory.get("ranking_order_comparison", {}).get("status") == "PASS"
        and table7.get("status") == "PASS"
        and table7.get("expected_zone_count") == 101
        and table7.get("computed_quality_zone_count") == 101
        and table7.get("matched_centroid_count") == 101
        and footprint.get("candidate_summary", {}).get("component_count") == 106
        and footprint.get("candidate_summary", {}).get("quality_pass_count") == 101
    )

    site_profile_pass = (
        site.get("status") == "SCIENTIFIC_METRICS_COMPUTED"
        and site.get("structural_status") == "PASS"
        and site.get("method_profile") == "ARCHIVED_AUTHOR_SITE_SERIES_COMPATIBLE"
        and site.get("source_products_processed") == 5
    )
    site_comparison = site.get("author_site_series_table_comparison", {})
    p2_comparison = site.get("author_p2_table_comparison", {})
    site_table_pass = site_profile_pass and _comparison_passes(site_comparison, 65)
    p2_table_pass = site_profile_pass and _comparison_passes(p2_comparison, 15)
    analysis_ready = (
        status.get("status") == "OUTPUTS_WRITTEN"
        and status.get("analysis_metrics_complete") is True
    )
    site_and_p2_pass = analysis_ready and site_table_pass and p2_table_pass

    site_p2_definitive_mismatch = (
        analysis_ready
        and site_profile_pass
        and (
            _comparison_is_definitive_mismatch(site_comparison, 65)
            or _comparison_is_definitive_mismatch(p2_comparison, 15)
        )
    )
    site_p2_state = (
        "PASS" if site_and_p2_pass
        else "MISMATCH" if site_p2_definitive_mismatch
        else "INCOMPLETE"
    )
    footprint_state = (
        "PASS" if footprint_pass
        else "MISMATCH" if footprint.get("status") == "FOOTPRINT_SCREEN_COMPUTED"
        else "INCOMPLETE"
    )
    combined_pass = site_and_p2_pass and footprint_pass

    if combined_pass:
        paper_status = PAPER_PARTIAL_MATCH
    elif site_p2_state == "PASS" and footprint_state == "MISMATCH":
        paper_status = (
            "PARTIAL_AUTHOR_SITE_SERIES_MATCH_FOOTPRINT_PARITY_MISMATCH_"
            "DISPLACEMENT_NULL_STILL_UNVERIFIED"
        )
    elif site_p2_state == "MISMATCH" and footprint_state == "PASS":
        paper_status = (
            "PARTIAL_AUTHOR_SITE_SERIES_OR_P2_PARITY_MISMATCH_FOOTPRINT_MATCH_"
            "DISPLACEMENT_NULL_STILL_UNVERIFIED"
        )
    elif site_p2_state == "MISMATCH" and footprint_state == "MISMATCH":
        paper_status = (
            "PARTIAL_AUTHOR_SITE_SERIES_AND_FOOTPRINT_PARITY_MISMATCH_"
            "DISPLACEMENT_NULL_STILL_UNVERIFIED"
        )
    else:
        paper_status = BLOCKED_INCOMPLETE

    return {
        "author_site_series_table_parity": bool(site_table_pass),
        "site_series_table_parity_status": "PASS" if site_table_pass else (
            "MISMATCH" if _comparison_is_definitive_mismatch(site_comparison, 65) and site_profile_pass else "INCOMPLETE"
        ),
        "author_p2_table_parity": bool(p2_table_pass),
        "p2_table_parity_status": "PASS" if p2_table_pass else (
            "MISMATCH" if _comparison_is_definitive_mismatch(p2_comparison, 15) and site_profile_pass else "INCOMPLETE"
        ),
        "analysis_outputs_ready": bool(analysis_ready),
        "site_series_and_p2_complete_and_archive_matched": bool(site_and_p2_pass),
        "site_series_and_p2_evidence_status": site_p2_state,
        "footprint_screen_complete_and_archive_matched": bool(footprint_pass),
        "footprint_evidence_status": footprint_state,
        "footprint_parity_status": "PASS" if footprint_pass else (
            "MISMATCH" if footprint_state == "MISMATCH" else "INCOMPLETE"
        ),
        "overall_scientific_screen_complete": bool(combined_pass),
        "paper_reproduction_status": paper_status,
        "displacement_null_status": "UNVERIFIED",
        "hazard_detection_status": "NOT_EVALUATED",
    }
