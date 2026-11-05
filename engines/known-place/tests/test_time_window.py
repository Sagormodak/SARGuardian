from __future__ import annotations

import pytest

from tools.time_window import (
    filter_products_by_time_window,
    parse_iso_date,
    secondary_acquisition_date,
)


GUNW_NOV = (
    "NISAR_L2_PR_GUNW_006_048_D_074_007_2000_SH_"
    "20251125T125813_20251125T125848_20251207T125814_20251207T125849_X05010_N_F_J_001.h5"
)
GOFF_AUG = (
    "NISAR_L2_PR_GOFF_026_048_D_074_028_4000_SH_"
    "20260723T125813_20260723T125848_20260816T125812_20260816T125846_P05023_N_F_J_001.h5"
)


def test_secondary_acquisition_date_uses_third_pair_timestamp():
    assert secondary_acquisition_date(GUNW_NOV).isoformat() == "2025-12-07"
    assert secondary_acquisition_date(GOFF_AUG).isoformat() == "2026-08-16"


def test_window_includes_both_date_boundaries_and_preserves_order():
    products = [
        {"product_type": "GUNW", "granule_name": GUNW_NOV},
        {"product_type": "GOFF", "granule_name": GOFF_AUG},
    ]
    assert filter_products_by_time_window(products, "2025-12-07", "2025-12-07") == [
        {
            "product_type": "GUNW",
            "granule_name": GUNW_NOV,
            "secondary_acquisition_date": "2025-12-07",
        }
    ]
    assert filter_products_by_time_window(products, "2025-12-07", "2026-08-16") == [
        {**products[0], "secondary_acquisition_date": "2025-12-07"},
        {**products[1], "secondary_acquisition_date": "2026-08-16"},
    ]


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2026-08-17", "2026-08-16", "on or before"),
        ("2026/01/01", "2026-08-16", "YYYY-MM-DD"),
        ("2026-02-30", "2026-08-16", "YYYY-MM-DD"),
    ],
)
def test_invalid_window_rejected(start, end, message):
    with pytest.raises(ValueError, match=message):
        filter_products_by_time_window(
            [{"granule_name": GOFF_AUG}], start, end
        )


def test_invalid_granule_timestamp_rejected():
    with pytest.raises(ValueError, match="four NISAR pair timestamps"):
        secondary_acquisition_date("NISAR_L2_PR_GUNW_invalid-name.h5")


def test_filter_rejects_a_missing_granule_identifier():
    with pytest.raises(ValueError, match="granule_name"):
        filter_products_by_time_window([{"product_type": "GUNW"}], "2025-01-01", "2026-12-31")


def test_parse_iso_date_is_strict():
    assert parse_iso_date("2025-01-01", "start_date").isoformat() == "2025-01-01"
