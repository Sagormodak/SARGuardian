from __future__ import annotations

from tools.know_place.scientific_status import (
    BLOCKED_INCOMPLETE,
    FOOTPRINT_PASS,
    PAPER_PARTIAL_MATCH,
    assess_reproduction_status,
)


def comparison(count: int, passed: bool = True) -> dict:
    return {
        "status": "PASS_AT_ARCHIVE_ROUNDING" if passed else "MISMATCH",
        "checks_passed": count if passed else max(0, count - 1),
        "checks_total": count,
        "mismatch_count": 0 if passed else 1,
    }


def make_inputs(*, site_pass: bool = True, p2_pass: bool = True, footprint_pass: bool = True) -> tuple[dict, dict, dict]:
    status = {"status": "OUTPUTS_WRITTEN", "analysis_metrics_complete": True}
    site = {
        "status": "SCIENTIFIC_METRICS_COMPUTED",
        "structural_status": "PASS",
        "method_profile": "ARCHIVED_AUTHOR_SITE_SERIES_COMPATIBLE",
        "source_products_processed": 5,
        "author_site_series_table_comparison": comparison(65, site_pass),
        "author_p2_table_comparison": comparison(15, p2_pass),
    }
    footprint = {
        "status": "FOOTPRINT_SCREEN_COMPUTED",
        "footprint_screen_parity_status": FOOTPRINT_PASS if footprint_pass else "MISMATCH_AUTHOR_FOOTPRINT_PARITY",
        "author_aggregate_raster_comparison": {
            "status": "PASS" if footprint_pass else "MISMATCH",
            "raster_count": 3,
            "rasters_passed": 3 if footprint_pass else 2,
        },
        "author_inventory_comparison": {
            "status": "PASS" if footprint_pass else "MISMATCH",
            "expected_candidate_count": 106,
            "computed_candidate_count": 106,
            "computed_quality_pass_count": 101,
            "score_formula_audit": {
                "status": "PASS_POSTPROCESSED_AUTHOR_SCORE_CONVENTION"
            },
            "ranking_order_comparison": {"status": "PASS"},
        },
        "author_validated_zone_table_comparison": {
            "status": "PASS" if footprint_pass else "MISMATCH",
            "expected_zone_count": 101,
            "computed_quality_zone_count": 101,
            "matched_centroid_count": 101,
        },
        "candidate_summary": {
            "component_count": 106,
            "quality_pass_count": 101,
        },
    }
    return status, site, footprint


def test_both_site_and_footprint_gates_pass_only_reports_partial_method_match() -> None:
    assessment = assess_reproduction_status(*make_inputs())

    assert assessment["author_site_series_table_parity"] is True
    assert assessment["author_p2_table_parity"] is True
    assert assessment["footprint_screen_complete_and_archive_matched"] is True
    assert assessment["overall_scientific_screen_complete"] is True
    assert assessment["paper_reproduction_status"] == PAPER_PARTIAL_MATCH
    assert assessment["displacement_null_status"] == "UNVERIFIED"
    assert assessment["hazard_detection_status"] == "NOT_EVALUATED"


def test_footprint_pass_cannot_mask_site_series_table_mismatch() -> None:
    assessment = assess_reproduction_status(*make_inputs(site_pass=False, footprint_pass=True))

    assert assessment["footprint_screen_complete_and_archive_matched"] is True
    assert assessment["author_site_series_table_parity"] is False
    assert assessment["site_series_and_p2_complete_and_archive_matched"] is False
    assert assessment["site_series_and_p2_evidence_status"] == "MISMATCH"
    assert assessment["overall_scientific_screen_complete"] is False
    assert "SITE_SERIES_OR_P2_PARITY_MISMATCH" in assessment["paper_reproduction_status"]


def test_footprint_pass_cannot_mask_p2_table_mismatch() -> None:
    assessment = assess_reproduction_status(*make_inputs(p2_pass=False, footprint_pass=True))

    assert assessment["author_site_series_table_parity"] is True
    assert assessment["author_p2_table_parity"] is False
    assert assessment["site_series_and_p2_evidence_status"] == "MISMATCH"
    assert assessment["overall_scientific_screen_complete"] is False
    assert assessment["paper_reproduction_status"] != PAPER_PARTIAL_MATCH


def test_site_and_p2_pass_cannot_mask_footprint_mismatch() -> None:
    assessment = assess_reproduction_status(*make_inputs(site_pass=True, p2_pass=True, footprint_pass=False))

    assert assessment["site_series_and_p2_complete_and_archive_matched"] is True
    assert assessment["footprint_screen_complete_and_archive_matched"] is False
    assert assessment["footprint_evidence_status"] == "MISMATCH"
    assert assessment["overall_scientific_screen_complete"] is False
    assert "FOOTPRINT_PARITY_MISMATCH" in assessment["paper_reproduction_status"]


def test_joint_mismatch_is_reported_without_a_match_claim() -> None:
    assessment = assess_reproduction_status(*make_inputs(site_pass=False, p2_pass=False, footprint_pass=False))

    assert assessment["overall_scientific_screen_complete"] is False
    assert assessment["paper_reproduction_status"] == (
        "PARTIAL_AUTHOR_SITE_SERIES_AND_FOOTPRINT_PARITY_MISMATCH_"
        "DISPLACEMENT_NULL_STILL_UNVERIFIED"
    )


def test_missing_processing_completion_blocks_joint_match() -> None:
    values = list(make_inputs())
    values[0]["analysis_metrics_complete"] = False
    assessment = assess_reproduction_status(*values)

    assert assessment["author_site_series_table_parity"] is True
    assert assessment["overall_scientific_screen_complete"] is False
    assert assessment["paper_reproduction_status"] == BLOCKED_INCOMPLETE
    assert assessment["site_series_and_p2_evidence_status"] == "INCOMPLETE"


def test_missing_footprint_output_is_blocked_not_reported_as_parity_mismatch() -> None:
    status, site, footprint = make_inputs()
    footprint["status"] = "FOOTPRINT_REPLAY_FAILED"
    assessment = assess_reproduction_status(status, site, footprint)

    assert assessment["footprint_evidence_status"] == "INCOMPLETE"
    assert assessment["footprint_parity_status"] == "INCOMPLETE"
    assert assessment["paper_reproduction_status"] == BLOCKED_INCOMPLETE


def test_missing_site_comparison_is_blocked_not_reported_as_parity_mismatch() -> None:
    status, site, footprint = make_inputs()
    site["author_site_series_table_comparison"] = {
        "status": "MISMATCH",
        "checks_passed": 0,
        "checks_total": 0,
        "mismatch_count": 0,
    }
    assessment = assess_reproduction_status(status, site, footprint)

    assert assessment["site_series_table_parity_status"] == "INCOMPLETE"
    assert assessment["site_series_and_p2_evidence_status"] == "INCOMPLETE"
    assert assessment["paper_reproduction_status"] == BLOCKED_INCOMPLETE
