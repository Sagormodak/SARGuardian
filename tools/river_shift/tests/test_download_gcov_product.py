import pytest

from download_gcov_product import build_product_url, trusted_asf_url


def test_build_official_provisional_asset_url_from_exact_gcove_granule():
    name = "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_20260718T155041_20260718T155059_P05023_N_F_J_001"
    url = build_product_url(name, "PROVISIONAL")
    assert url == (
        "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
        "NISAR_L2_GCOV_PROVISIONAL_V1/" + name + "/" + name + ".h5"
    )
    assert trusted_asf_url(url)


def test_url_builder_rejects_unknown_maturity_and_invalid_name():
    with pytest.raises(ValueError, match="known BETA or PROVISIONAL"):
        build_product_url("NISAR_L2_PR_GCOV_invalid", "UNKNOWN")
    with pytest.raises(ValueError, match="official NISAR"):
        build_product_url("NISAR_L2_GUNW_invalid", "PROVISIONAL")
