import pytest

from audit_gcov_acquisitions import audit_manifest


AOI = "POLYGON ((89.6 24.5, 89.7 24.5, 89.7 24.6, 89.6 24.6, 89.6 24.5))"
FOOTPRINT = {
    "type": "Polygon",
    "coordinates": [[[89.59, 24.49], [89.71, 24.49], [89.71, 24.61], [89.59, 24.61], [89.59, 24.49]]],
}


def make_product(day: int, cycle: int = 25, orbit: int = 151, footprint=FOOTPRINT):
    start = f"202609{day:02d}T010203"
    end = f"202609{day:02d}T010245"
    name = (
        f"NISAR_L2_PR_GCOV_{cycle:03d}_{orbit:03d}_A_011_4005_DHDH_A_"
        f"{start}_{end}_P05023_N_F_J_001"
    )
    return {
        "granule_name": name,
        "maturity": "PROVISIONAL",
        "collection_short_name": "NISAR_L2_GCOV_PROVISIONAL_V1",
        "product": "GCOV",
        "flight_direction": "ASCENDING",
        "relative_orbit": f"{orbit:03d}",
        "bandwidth_mode": "4005",
        "polarization_code": "DHDH",
        "processing_type": "PR",
        "acquisition_start_utc": start,
        "frame_coverage": "FULL",
        "cycle": f"{cycle:03d}",
        "crid": "P05023",
        "orbit_accuracy": "N",
        "observation_source": "ACQUIRED_SINGLE_MODE",
        "processing_center": "J",
        "product_counter": "001",
        "footprint": footprint,
    }


def test_three_compatible_dates_with_full_aoi_coverage_pass():
    manifest = {
        "query": {"aoi_wkt": AOI, "start_date": "2026-09-01", "end_date": "2026-09-30"},
        "products": [make_product(day, cycle=25 + i) for i, day in enumerate([1, 13, 25])],
    }
    report = audit_manifest(manifest, minimum_dates=3, minimum_aoi_coverage_percent=90)
    assert report["status"] == "READY_FOR_PRODUCT_LEVEL_COMPATIBILITY_CHECK"
    assert report["metrics"]["qualifying_group_count"] == 1
    group = report["qualifying_groups"][0]
    assert group["eligible_acquisition_dates"] == 3
    assert group["frame"] == "011"
    assert all(item["aoi_coverage_percent"] >= 90 for item in group["dates"])
    assert group["frequency_selection"] == {
        "frequency": "frequencyA",
        "diagonal_term": "HHHH",
        "bandwidth_code_mhz": 40,
        "expected_pixel_spacing_m": 10,
        "polarization_code": "DH",
        "term_encoded_as_available": True,
        "hdf5_layer_verified": False,
    }
    assert report["acceptance"]["catalogue_proves_raster_compatibility"] is False
    assert report["acceptance"]["requires_same_frame"] is True


def test_three_dates_on_different_orbits_do_not_form_one_time_series():
    products = [
        make_product(1, orbit=149),
        make_product(13, orbit=150),
        make_product(25, orbit=151),
    ]
    report = audit_manifest({"query": {"aoi_wkt": AOI}, "products": products})
    assert report["status"] == "INSUFFICIENT_COMPARABLE_ACQUISITIONS"
    assert report["metrics"]["qualifying_group_count"] == 0


def test_incomplete_footprint_coverage_does_not_pass():
    small = {
        "type": "Polygon",
        "coordinates": [[[89.6, 24.5], [89.65, 24.5], [89.65, 24.6], [89.6, 24.6], [89.6, 24.5]]],
    }
    products = [make_product(day, cycle=25 + i, footprint=small) for i, day in enumerate([1, 13, 25])]
    report = audit_manifest({"query": {"aoi_wkt": AOI}, "products": products})
    assert report["status"] == "INSUFFICIENT_COMPARABLE_ACQUISITIONS"
    assert report["metrics"]["qualifying_group_count"] == 0


def test_missing_footprint_geometry_is_explicitly_incomplete():
    products = [make_product(day, cycle=25 + i, footprint=None) for i, day in enumerate([1, 13, 25])]
    report = audit_manifest({"query": {"aoi_wkt": AOI}, "products": products})
    assert report["status"] == "FOOTPRINT_DATA_INCOMPLETE"
    assert report["metrics"]["products_without_usable_footprint"] == 3


def test_requested_term_must_match_each_band_polarization_code():
    products = [make_product(day, cycle=25 + i) for i, day in enumerate([1, 13, 25])]
    report = audit_manifest(
        {"query": {"aoi_wkt": AOI}, "products": products},
        frequency="frequencyA", term="VVVV",
    )
    assert report["status"] == "INSUFFICIENT_COMPARABLE_ACQUISITIONS"
    assert report["metrics"]["qualifying_group_count"] == 0
    assert report["metrics"]["products_rejected_or_not_groupable"] == 3


def test_frequency_b_uses_secondary_band_spacing_and_term_code():
    products = [make_product(day, cycle=25 + i) for i, day in enumerate([1, 13, 25])]
    report = audit_manifest(
        {"query": {"aoi_wkt": AOI}, "products": products},
        frequency="frequencyB", term="HHHH",
    )
    selection = report["qualifying_groups"][0]["frequency_selection"]
    assert selection["bandwidth_code_mhz"] == 5
    assert selection["expected_pixel_spacing_m"] == 80


def test_different_crid_does_not_enter_one_qualifying_group():
    products = [make_product(day, cycle=25 + i) for i, day in enumerate([1, 13, 25])]
    products[-1]["granule_name"] = products[-1]["granule_name"].replace("P05023", "P05024")
    report = audit_manifest({"query": {"aoi_wkt": AOI}, "products": products})
    assert report["status"] == "INSUFFICIENT_COMPARABLE_ACQUISITIONS"
    assert report["metrics"]["qualifying_group_count"] == 0


def test_different_nisar_frame_does_not_enter_one_qualifying_group():
    products = [make_product(day, cycle=25 + i) for i, day in enumerate([1, 13, 25])]
    products[-1]["granule_name"] = products[-1]["granule_name"].replace("_011_4005_", "_012_4005_")
    report = audit_manifest({"query": {"aoi_wkt": AOI}, "products": products})
    assert report["status"] == "INSUFFICIENT_COMPARABLE_ACQUISITIONS"
    assert report["metrics"]["qualifying_group_count"] == 0


@pytest.mark.parametrize(
    "field, value",
    [
        ("crid", "P05024"),
        ("orbit_accuracy", "PRECISE"),
        ("observation_source", "MIXED_MODE"),
        ("processing_center", "X"),
        ("product_counter", "002"),
        ("collection_short_name", "NISAR_L2_GCOV_BETA_V1"),
    ],
)
def test_catalogue_metadata_must_match_filename_tokens(field, value):
    products = [make_product(day, cycle=25 + i) for i, day in enumerate([1, 13, 25])]
    products[-1][field] = value

    report = audit_manifest({"query": {"aoi_wkt": AOI}, "products": products})

    assert report["metrics"]["qualifying_group_count"] == 0
    assert report["metrics"]["products_rejected_or_not_groupable"] == 1
