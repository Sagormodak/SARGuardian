from __future__ import annotations

from pathlib import Path
import copy

import pytest

from tools.know_place.aoi_request import (
    AOIRequestError,
    REQUEST_SCHEMA,
    validate_aoi_request,
)

AOI_WKT = "POLYGON ((85.52 28.28, 85.54 28.28, 85.54 28.30, 85.52 28.30, 85.52 28.28))"


def request():
    return {
        "schema_version": REQUEST_SCHEMA,
        "aoi": {"type": "Polygon", "wkt": AOI_WKT, "crs": "EPSG:4326"},
        "date_range": {"start": "2026-06-20", "end": "2026-08-31", "inclusive": True},
        "hazard_mode": "mixed",
        "analysis_mode": "retrospective_validation",
        "source_adapters": ["nisar_goff"],
        "polarization": "HH",
        "product_selection": {
            "track": "98",
            "direction": "ASCENDING",
            "preferred_granules": [],
        },
        "reference": {"policy": "external_reference_polygon_component_median", "polygon_wkt":
            "POLYGON ((85.50 28.26, 85.56 28.26, 85.56 28.32, 85.50 28.32, 85.50 28.26))"},
        "quality_policy": {"minimum_snr": 5, "maximum_horizontal_magnitude_m": 10},
        "coherence_policy": {"window_size": 5, "minimum_valid_neighbours": 1},
    }


def test_request_normalizes_dates_polygon_selection_and_hash_deterministically():
    payload = request()
    first = validate_aoi_request(payload)
    second = validate_aoi_request(copy.deepcopy(payload))

    assert first.start_date.isoformat() == "2026-06-20"
    assert first.end_date.isoformat() == "2026-08-31"
    assert first.track == "098"
    assert first.direction == "A"
    assert first.reference_wkt is not None
    assert first.request_sha256 == second.request_sha256
    assert len(first.request_sha256) == 64
    normalized = first.to_dict()
    assert normalized["date_range"]["inclusive"] is True
    assert normalized["quality_policy"]["gross_outlier_policy"] == "preserve_but_flag_above_threshold"


@pytest.mark.parametrize("dates,code", [
    ({"start": "2026-09-01", "end": "2026-08-31"}, "DATE_RANGE_START_AFTER_END"),
    ({"start": "2026-6-01", "end": "2026-08-31"}, "START_DATE_MUST_BE_ISO_DATE"),
    ({"start": "2026-06-20", "end": "2026-08-31", "inclusive": False}, "DATE_RANGE_MUST_BE_INCLUSIVE"),
])
def test_invalid_date_range_fails_closed(dates, code):
    payload = request()
    payload["date_range"] = dates
    with pytest.raises(AOIRequestError, match=code):
        validate_aoi_request(payload)


def test_invalid_or_unsupported_polygon_is_rejected_instead_of_silently_repaired():
    payload = request()
    payload["aoi"]["wkt"] = "POLYGON ((85 28, 86 29, 85 29, 86 28, 85 28))"
    with pytest.raises(AOIRequestError, match="AOI_GEOMETRY_INVALID"):
        validate_aoi_request(payload)

    payload = request()
    payload["aoi"]["wkt"] = "MULTIPOLYGON (((85 28, 86 28, 86 29, 85 29, 85 28)))"
    with pytest.raises(AOIRequestError, match="AOI_GEOMETRY_INVALID"):
        validate_aoi_request(payload)


def test_unsupported_adapter_and_even_coherence_window_fail_closed():
    payload = request()
    payload["source_adapters"] = ["SENTINEL_ALL"]
    with pytest.raises(AOIRequestError, match="SOURCE_ADAPTER_UNSUPPORTED"):
        validate_aoi_request(payload)

    payload = request()
    payload["coherence_policy"]["window_size"] = 4
    with pytest.raises(AOIRequestError, match="COHERENCE_WINDOW_MUST_BE_POSITIVE_ODD_INTEGER"):
        validate_aoi_request(payload)


def test_invalid_track_direction_and_release_pins_are_explicit_errors():
    payload = request()
    payload["product_selection"]["track"] = "98A"
    with pytest.raises(AOIRequestError, match="TRACK_MUST_BE_THREE_DIGITS"):
        validate_aoi_request(payload)

    payload = request()
    payload["product_selection"]["direction"] = "BOTH"
    with pytest.raises(AOIRequestError, match="DIRECTION_MUST_BE_ASCENDING_OR_DESCENDING"):
        validate_aoi_request(payload)

    payload = request()
    payload["product_selection"]["preferred_granules"] = "not-a-list"
    with pytest.raises(AOIRequestError, match="PREFERRED_GRANULES_MUST_BE_STRING_ARRAY"):
        validate_aoi_request(payload)

    payload = request()
    payload["product_selection"]["allowed_release_ids"] = "P05023"
    with pytest.raises(AOIRequestError, match="ALLOWED_RELEASE_IDS_MUST_BE_STRING_ARRAY"):
        validate_aoi_request(payload)

    payload = request()
    payload["product_selection"]["allowed_release_ids"] = ["not-a-release"]
    with pytest.raises(AOIRequestError, match="ALLOWED_RELEASE_ID_FORMAT_INVALID"):
        validate_aoi_request(payload)


def test_allowed_release_ids_are_normalized_and_preserved_in_request_hash():
    payload = request()
    payload["product_selection"]["allowed_release_ids"] = ["p05023", "P05023"]
    parsed = validate_aoi_request(payload)
    assert parsed.allowed_release_ids == ("P05023",)
    assert parsed.to_dict()["product_selection"]["allowed_release_ids"] == ["P05023"]

    different = request()
    different["product_selection"]["allowed_release_ids"] = ["X05026"]
    assert validate_aoi_request(different).request_sha256 != parsed.request_sha256

def test_no_reference_polygon_is_labeled_unreferenced_not_background_corrected():
    payload = request()
    payload.pop("reference")
    normalized = validate_aoi_request(payload).to_dict()
    assert normalized["reference"]["policy"] == "local_context_component_median"
    assert normalized["reference"]["fallback_buffer_m"] == 2000.0

    payload["reference"] = {"policy": "none", "fallback_buffer_m": 2000.0}
    explicit_none = validate_aoi_request(payload).to_dict()
    assert explicit_none["reference"]["policy"] == "none"


def test_allowed_maturity_and_geometry_policy_are_preserved_in_request_provenance():
    payload = request()
    payload["product_selection"]["allowed_maturities"] = ["BETA", "PROVISIONAL"]
    payload["geometry_policy"] = {"constant_hae_m": 5151.0}

    parsed = validate_aoi_request(payload)
    serialized = parsed.to_dict()

    assert serialized["product_selection"]["allowed_maturities"] == ["BETA", "PROVISIONAL"]
    assert serialized["geometry_policy"]["constant_hae_m"] == pytest.approx(5151.0)
    assert "A constant height is an approximation" in serialized["geometry_policy"]["warning"]


def test_operational_monitoring_fails_closed_until_dem_backed_geometry_is_available():
    payload = request()
    payload["analysis_mode"] = "operational_monitoring"

    with pytest.raises(AOIRequestError, match="OPERATIONAL_MODE_BLOCKED_DEM_BACKED_GEOMETRY_REQUIRED"):
        validate_aoi_request(payload)


def test_generic_mode_preserves_large_motion_by_default_but_paper_policy_is_explicit():
    payload = request()
    payload["analysis_mode"] = "exploratory"
    generic = validate_aoi_request(payload)
    assert generic.magnitude_policy == "flag_above_threshold_keep"
    assert generic.to_dict()["quality_policy"]["maximum_horizontal_magnitude_m"] == 10.0

    payload["quality_policy"]["magnitude_policy"] = "reject_above_threshold"
    paper_policy = validate_aoi_request(payload)
    assert paper_policy.magnitude_policy == "reject_above_threshold"
    assert paper_policy.to_dict()["quality_policy"]["gross_outlier_policy"] == "reject_above_threshold_not_clip"


def test_dispatcher_consent_failure_explains_exact_marker_and_remains_strict():
    repository_root = Path(__file__).resolve().parents[2]
    workflow_path = repository_root / ".github" / "workflows" / "sarguardian-aoi-wkt-dispatcher.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert '"$CONSENT_MARKER" != "[run-know-place]"' in workflow
    assert "ACTION_REQUIRED=Re-run with consent_marker exactly [run-know-place], including both square brackets." in workflow
    assert "run-know-place by itself does not authorize source downloads." in workflow
    assert "No raw source, analysis or Drive operation was performed." in workflow
    assert '"$CONSENT_MARKER" == "run-know-place"' not in workflow

def test_outer_scope_aoi_is_canonicalized_and_kept_separate_from_measurement_polygon():
    payload = request()
    outer = "POLYGON ((85.49 28.27, 85.57 28.27, 85.57 28.33, 85.49 28.33, 85.49 28.27))"
    payload["scope_aoi"] = {
        "type": "Polygon",
        "crs": "EPSG:4326",
        "role": "outer_selection_boundary",
        "wkt": outer,
    }
    parsed = validate_aoi_request(payload)
    normalized = parsed.to_dict()
    assert parsed.aoi_wkt != parsed.scope_aoi_wkt
    assert normalized["aoi"]["role"] == "measurement"
    assert normalized["scope_aoi"]["role"] == "outer_selection_boundary"
    assert normalized["scope_aoi"]["wkt"].startswith("POLYGON ((85.490000000")


def test_outer_scope_aoi_rejects_invalid_geometry_and_crs():
    payload = request()
    payload["scope_aoi"] = {"wkt": "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))", "crs": "EPSG:4326"}
    with pytest.raises(AOIRequestError, match="SCOPE_AOI_GEOMETRY_INVALID"):
        validate_aoi_request(payload)

    payload = request()
    payload["scope_aoi"] = {
        "wkt": "POLYGON ((85.49 28.27, 85.57 28.27, 85.57 28.33, 85.49 28.33, 85.49 28.27))",
        "crs": "EPSG:3857",
    }
    with pytest.raises(AOIRequestError, match="SCOPE_AOI_CRS_MUST_BE_EPSG4326_OR_CRS84"):
        validate_aoi_request(payload)

def test_goff_candidate_context_is_normalized_and_saved_as_provenance():
    payload = request()
    payload["candidate_context"] = {
        "source": "FIND_DISPLACEMENTS",
        "candidate_id": "GOFF-CANDIDATE-004",
        "product_type": "GOFF",
        "metric": "GOFF_SLANT_RANGE_OFFSET_MM",
        "evidence_class": "GOFF_OFFSET_ANOMALY_NOT_GROUND_MOTION",
        "status": "REPEATED_SPATIAL_CANDIDATE",
        "support_pairs": 3,
        "pixel_count": 42,
        "approx_area_m2": 268800.0,
        "product_ids": ["NISAR_GOFF_P05023_A"],
        "pair_intervals": [{"reference_date": "2026-07-01", "secondary_date": "2026-07-13"}],
        "geometry_original_vertices": 1800,
        "geometry_suggested_vertices": 420,
        "geometry_simplified": True,
        "geometry_edited": True,
        "interpretation": "Offset anomaly candidate; not measured ground motion.",
    }
    parsed = validate_aoi_request(payload)
    normalized = parsed.to_dict()
    assert normalized["candidate_context"]["candidate_id"] == "GOFF-CANDIDATE-004"
    assert normalized["candidate_context"]["product_type"] == "GOFF"
    assert normalized["candidate_context"]["geometry_simplified"] is True
    assert normalized["candidate_context"]["geometry_edited"] is True
    assert len(parsed.request_sha256) == 64


def test_candidate_context_rejects_gunw_cross_family_handoff_and_oversized_metadata():
    payload = request()
    payload["candidate_context"] = {
        "source": "FIND_DISPLACEMENTS",
        "candidate_id": "LOS-001",
        "product_type": "GUNW",
        "metric": "GUNW_LOS_DISPLACEMENT_MM",
        "evidence_class": "GUNW_LOS_DISPLACEMENT_ANOMALY_UNCONFIRMED",
        "status": "REPEATED_SPATIAL_CANDIDATE",
        "support_pairs": 2,
        "pixel_count": 12,
        "approx_area_m2": 80000,
        "product_ids": [],
        "pair_intervals": [],
        "geometry_original_vertices": 100,
        "geometry_suggested_vertices": 100,
        "geometry_simplified": False,
        "interpretation": "LOS anomaly",
    }
    with pytest.raises(AOIRequestError, match="CANDIDATE_CONTEXT_MUST_BE_GOFF"):
        validate_aoi_request(payload)

    payload = request()
    payload["candidate_context"] = {
        "source": "FIND_DISPLACEMENTS",
        "candidate_id": "GOFF-001",
        "product_type": "GOFF",
        "metric": "GOFF_SLANT_RANGE_OFFSET_MM",
        "evidence_class": "GOFF_OFFSET_ANOMALY_NOT_GROUND_MOTION",
        "status": "REPEATED_SPATIAL_CANDIDATE",
        "support_pairs": 1,
        "pixel_count": 10,
        "approx_area_m2": 1000.0,
        "geometry_original_vertices": 10,
        "geometry_suggested_vertices": 10,
        "geometry_simplified": False,
        "geometry_edited": False,
        "interpretation": "Offset anomaly candidate; not measured ground motion.",
        "pair_intervals": [],
        "product_ids": ["P" * 600],
    }
    with pytest.raises(AOIRequestError, match="CANDIDATE_CONTEXT_PRODUCT_IDS_INVALID"):
        validate_aoi_request(payload)

