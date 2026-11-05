"""Offline contract tests for the pre-registered multi-site NISAR benchmark."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "docs/know-place/reference/multi_site_benchmark_v1.json"
AUTHOR_PATH = ROOT / "docs/know-place/reference/author_benchmark_v1.json"


@pytest.fixture(scope="module")
def registry() -> dict:
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert value["schema_version"] == "know-place-multisite-benchmark/1.0"
    return value


@pytest.fixture(scope="module")
def author_benchmark() -> dict:
    return json.loads(AUTHOR_PATH.read_text(encoding="utf-8"))


def test_registry_has_six_unique_sites_and_no_premature_scored_result(registry: dict) -> None:
    sites = registry["sites"]
    ids = [site["site_id"] for site in sites]
    assert len(sites) == 6
    assert len(set(ids)) == len(ids)
    for site in sites:
        assert site["eligible_for_independent_holdout"] is False
        assert site["current_result"] in {
            "NOT_RUN",
            "NOT_RUN_EXACT_SOURCE_BYTES",
            "NOT_RUN; GUNW_ADAPTER_REQUIRED",
        }


def test_claim_boundary_keeps_measurement_and_hazard_detection_separate(registry: dict) -> None:
    status = registry["current_engine_claim_boundary"]["current_status"]
    assert status["generic_aoi_engine"] == "IMPLEMENTED_EXPLORATORY_MEASUREMENT"
    assert status["author_exact_p05023_source_identity"] == "CATALOG_IDENTITY_CONFIRMED_5_OF_5"
    assert status["author_exact_raw_hdf5_bytes_downloaded"] == 0
    assert status["author_exact_source_sha256_pins"] == 0
    assert status["paper_reproduction_status"] == "BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED"
    assert status["hazard_detection_status"] == "NOT_EVALUATED"


def test_bhote_koshi_frozen_pair_ids_and_published_reference_match_author_fixture(
    registry: dict, author_benchmark: dict
) -> None:
    site = next(row for row in registry["sites"] if row["site_id"] == "bhote-koshi-2026")
    assert site["role"] == [
        "AUTHOR_METHOD_REPRODUCTION_TARGET",
        "OBSERVED_PRE_EVENT_MOVEMENT_POSITIVE",
        "HAZARD_DISCRIMINATION_CHALLENGE",
    ]
    assert site["source_product_plan"]["exact_release"] == "P05023"
    ids = [row["id"] for row in author_benchmark["exact_author_granules"]]
    intervals = [row["interval"] for row in author_benchmark["exact_author_granules"]]
    assert len(ids) == 5
    assert all("_P05023_" in name for name in ids)
    assert not any("_X05026_" in name for name in ids)
    assert site["source_product_plan"]["intervals"] == intervals
    assert site["source_product_plan"]["source_sha256"] == []
    assert site["published_reference"]["median_crown_displacement_m"] == 0.96
    assert site["published_reference"]["displacement_null_percentile"] == 94.7
    assert "non-distinctive" in site["expected_engine_test"].lower()


@pytest.mark.parametrize(
    ("site_id", "nisar_range", "its_live_range"),
    [
        ("samudra-tapu-glacier-2026-01", [5.7, 139.19], [0.7, 132.53]),
        ("bara-shigri-glacier-2026-01", [1.89, 68.99], [0.47, 70.58]),
        ("hubbard-glacier-2025-10", [2.42, 2585.09], [0.29, 3247.55]),
        ("malaspina-glacier-2025-10", [3.4, 1728.31], [0.02, 1690.82]),
    ],
)
def test_external_glacier_sites_are_reference_leads_not_fake_passes(
    registry: dict, site_id: str, nisar_range: list[float], its_live_range: list[float]
) -> None:
    site = next(row for row in registry["sites"] if row["site_id"] == site_id)
    reference = site["published_reference"]
    assert reference["nisar_goff_velocity_range_m_per_year"] == nisar_range
    assert reference["its_live_velocity_range_m_per_year"] == its_live_range
    assert site["exact_product_plan"]["exact_aoi_wkt"] is None
    assert site["exact_product_plan"]["exact_nisar_granule_ids"] == []
    assert site["exact_product_plan"]["nisar_source_sha256"] == []
    assert site["current_result"] == "NOT_RUN"
    assert site["eligible_for_independent_holdout"] is False


def test_budhi_gandaki_gunw_control_is_not_scored_as_goff(registry: dict) -> None:
    site = next(row for row in registry["sites"] if row["site_id"] == "budhi-gandaki-2026-10-11")
    assert "CROSS_PRODUCT_NO_PRECURSOR_CHALLENGE" in site["role"]
    assert site["published_reference"]["product_type"].startswith("NISAR L-band GUNW")
    assert site["exact_product_plan"]["compatibility_status"] == (
        "GUNW_LOS_NOT_DIRECTLY_COMPARABLE_TO_CURRENT_GOFF_HORIZONTAL_OFFSET_PIPELINE"
    )
    assert site["current_result"] == "NOT_RUN; GUNW_ADAPTER_REQUIRED"
    assert site["exact_product_plan"]["exact_nisar_granule_ids"] == []


def test_protocol_requires_frozen_thresholds_and_separate_holdout(registry: dict) -> None:
    protocol = registry["evaluation_protocol"]
    assert "before opening the final holdout" in protocol["pass_policy"]
    assert "Bhote Koshi is the author-method reproduction target" in protocol["split_policy"]
    assert any("hazard detection" in note.lower() for note in registry["current_engine_claim_boundary"]["prohibited_claims"])


def test_himalayan_inventory_geometry_remains_a_lead_not_an_exact_paper_aoi(registry: dict) -> None:
    leads_path = ROOT / "docs/know-place/reference/multi_site_source_geometry_leads_20261025.json"
    leads = json.loads(leads_path.read_text(encoding="utf-8"))
    assert leads["schema_version"] == "know-place-multisite-source-geometry-leads/1.0"
    assert leads["execution_boundary"]["nisar_raw_payload_downloaded"] is False
    assert leads["execution_boundary"]["catalog_query_executed"] is False
    assert leads["execution_boundary"]["event_or_velocity_validation_scored"] is False
    sites = {row["site_id"]: row for row in leads["sites"]}
    samudra = sites["samudra-tapu-glacier-2026-01"]
    bara = sites["bara-shigri-glacier-2026-01"]
    assert samudra["legacy_rgi6_id"] == "RGI60-14.15613"
    assert samudra["rgi7_id"] is None
    assert samudra["geometry_wkt"] is None
    assert samudra["canonical_geometry_sha256"] is None
    assert bara["legacy_rgi6_id"] == "RGI60-14.15447"
    assert bara["rgi7_id"] == "RGI2000-v7.0-G-14-32495"
    assert bara["geometry_wkt"] is None
    assert bara["canonical_geometry_sha256"] is None
    assert all(not row["exact_product_ids"] and not row["source_product_sha256"] for row in sites.values())
    assert leads["primary_reference"]["exact_pair_start_end_dates_in_reviewed_page_text"] is None
    assert leads["primary_reference"]["exact_nisar_granule_ids_in_reviewed_page_text"] == []
    assert leads["primary_reference"]["exact_aoi_wkt_or_vector_sha256_in_reviewed_page_text"] is None
    assert leads["inventory_source"]["equivalence_to_iirs_paper_aoi"] == "NOT_ESTABLISHED"
    assert all(site["exact_product_plan"]["exact_aoi_wkt"] is None for site in registry["sites"]
               if site["site_id"] in sites)
