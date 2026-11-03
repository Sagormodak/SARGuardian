from datetime import date
from netrc import netrc
import stat

import pytest
from shapely.geometry import Polygon, mapping

from process_gcov_job import (
    WorkerFailure,
    _configure_earthdata_credentials,
    _product_date,
    select_covering_granules,
    select_date_window,
)


def test_selected_observations_use_a_real_event_window_and_never_interpolate():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": [f"scene-{index}"]}
        for index, value in enumerate(("2026-04-01", "2026-04-10", "2026-04-20", "2026-05-01", "2026-05-15", "2026-05-31", "2026-06-15"))
    ]

    selected, event_window = select_date_window(rows, date(2026, 5, 2))

    assert selected == [row["acquisition_date"] for row in rows]
    assert event_window == {
        "before": "2026-05-01",
        "event_proximal_observation": "2026-05-15",
        "post_one": "2026-05-31",
        "post_two": "2026-06-15",
    }


def test_event_window_does_not_use_pre_event_scene_as_event_observation():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
        for value in ("2026-04-01", "2026-04-10", "2026-04-20", "2026-05-01")
    ]
    with pytest.raises(WorkerFailure, match="one qualifying acquisition before"):
        select_date_window(rows, date(2026, 5, 2))


def test_compact_and_iso_acquisition_timestamps_are_normalized():
    assert _product_date({"start_time_utc": "20260627T124243"}) == "2026-06-27"
    assert _product_date({"start_time_utc": "2026-06-27T12:42:43.000Z"}) == "2026-06-27"
    assert _product_date({"granule_name": "NISAR_L2_PR_GCOV_024_019_D_076_4005_DHDH_A_20260627T124243_20260627T124249_P05023_N_P_J_001"}) == "2026-06-27"
    assert _product_date({"start_time_utc": "invalid"}) is None


def test_selected_observation_window_fails_closed_without_four_dates():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
        for value in ("2026-04-01", "2026-04-10", "2026-04-20")
    ]

    with pytest.raises(WorkerFailure, match="at least four comparable"):
        select_date_window(rows, date(2026, 4, 10))


def test_covering_scene_selection_can_mosaic_multiple_real_footprints():
    aoi = Polygon([(89.0, 24.0), (89.2, 24.0), (89.2, 24.2), (89.0, 24.2), (89.0, 24.0)])
    left = Polygon([(89.0, 24.0), (89.11, 24.0), (89.11, 24.2), (89.0, 24.2), (89.0, 24.0)])
    right = Polygon([(89.09, 24.0), (89.2, 24.0), (89.2, 24.2), (89.09, 24.2), (89.09, 24.0)])
    products = [
        {"granule_name": "scene-left", "footprint": mapping(left)},
        {"granule_name": "scene-right", "footprint": mapping(right)},
    ]

    selected = select_covering_granules(aoi, products, ["scene-left", "scene-right"], "EPSG:32645")

    assert {row["granule_name"] for row in selected} == {"scene-left", "scene-right"}


def test_covering_scene_selection_rejects_incomplete_single_scene_coverage():
    aoi = Polygon([(89.0, 24.0), (89.2, 24.0), (89.2, 24.2), (89.0, 24.2), (89.0, 24.0)])
    scene = Polygon([(89.0, 24.0), (89.08, 24.0), (89.08, 24.2), (89.0, 24.2), (89.0, 24.0)])
    products = [{"granule_name": "scene-one", "footprint": mapping(scene)}]

    with pytest.raises(WorkerFailure, match="cover"):
        select_covering_granules(aoi, products, ["scene-one"], "EPSG:32645")


def test_earthdata_bearer_token_does_not_write_a_netrc(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-bearer-token")
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)

    _configure_earthdata_credentials()

    assert not (tmp_path / ".netrc").exists()


def test_earthdata_username_password_create_private_parseable_netrc(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.setenv("EARTHDATA_PASSWORD", 'secret "value" \\ with slash')

    _configure_earthdata_credentials()

    path = tmp_path / ".netrc"
    credentials = netrc(str(path)).authenticators("urs.earthdata.nasa.gov")
    assert credentials == ("researcher@example.test", "", 'secret "value" \\ with slash')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_earthdata_netrc_rejects_control_characters(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "secret\npassword")

    with pytest.raises(WorkerFailure, match="unsupported control characters"):
        _configure_earthdata_credentials()


def test_earthdata_credentials_require_a_token_or_complete_login(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setenv("EARTHDATA_USERNAME", "researcher@example.test")
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)

    with pytest.raises(WorkerFailure, match="EARTHDATA_TOKEN"):
        _configure_earthdata_credentials()
