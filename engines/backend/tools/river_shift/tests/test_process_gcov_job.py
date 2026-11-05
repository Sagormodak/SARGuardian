from datetime import date
import json
from netrc import netrc
import stat

import pytest
from shapely.geometry import Polygon, mapping

from process_gcov_job import (
    WorkerFailure,
    event_observation_timing,
    _configure_earthdata_credentials,
    _ensure_credentials,
    _product_date,
    _read_input,
    select_covering_granules,
    select_date_window,
    select_event_compatible_group,
    select_general_compatible_group,
    select_general_date_window,
    generalize_flood_result,
    generalize_morphology_result,
    require_worker_source_provenance,
    build_source_granule_manifest,
    sha256_file,
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



def test_acquisition_on_event_calendar_day_is_not_assumed_post_event():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
        for value in ("2026-04-20", "2026-05-02", "2026-05-15", "2026-05-31", "2026-06-15")
    ]

    selected, event_window = select_date_window(rows, date(2026, 5, 2))

    assert event_window == {
        "before": "2026-04-20",
        "event_proximal_observation": "2026-05-15",
        "post_one": "2026-05-31",
        "post_two": "2026-06-15",
    }
    assert "2026-05-02" in selected  # Kept as an actual time-series date, not used as event-proximal.


def test_event_window_does_not_use_pre_event_scene_as_event_observation():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
        for value in ("2026-04-01", "2026-04-10", "2026-04-20", "2026-05-01")
    ]
    with pytest.raises(WorkerFailure, match="one qualifying acquisition strictly before"):
        select_date_window(rows, date(2026, 5, 2))





def test_general_scan_selects_four_actual_dates_without_event_bracketing():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
        for value in ("2026-08-01", "2026-08-13", "2026-08-25", "2026-09-06")
    ]
    selected, window = select_general_date_window(rows)
    assert selected == ["2026-08-01", "2026-08-13", "2026-08-25", "2026-09-06"]
    assert window == {
        "before": "2026-08-01",
        "event_proximal_observation": "2026-08-13",
        "post_one": "2026-08-25",
        "post_two": "2026-09-06",
    }


def test_general_compatible_group_skips_groups_without_four_qualified_dates():
    def group(values):
        return {"relative_orbit": "101", "dates": [
            {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
            for value in values
        ]}
    selected_group, dates, window = select_general_compatible_group([
        group(("2026-08-01", "2026-08-13", "2026-08-25")),
        group(("2026-08-01", "2026-08-13", "2026-08-25", "2026-09-06")),
    ])
    assert selected_group["relative_orbit"] == "101"
    assert dates == ["2026-08-01", "2026-08-13", "2026-08-25", "2026-09-06"]
    assert window["before"] == "2026-08-01"


def test_general_scan_flood_report_uses_comparison_labels_and_no_event_wording(tmp_path):
    report_path = tmp_path / "river_shift_result.json"
    report_path.write_text(json.dumps({
        "schema_version": 1,
        "engine": "RiverShift",
        "analysis_type": "flood_inundation_screening",
        "source": {"mission": "NISAR", "product": "GCOV"},
        "inputs": {
            "dates": {"before": "2026-08-01", "during": "2026-08-13", "after": "2026-08-25"},
            "event_proximal_observation": "2026-08-13",
        },
        "method": {"threshold_method": "common_otsu"},
        "metrics": {
            "baseline_water_area_km2": 10.0,
            "event_proximal_water_area_km2": 11.0,
            "post_event_water_area_km2": 12.0,
            "newly_water_covered_area_km2": 1.0,
        },
        "quality": {"status": "SCREENING_NOT_INDEPENDENTLY_VALIDATED", "warnings": ["event date"]},
    }), encoding="utf-8")
    selection = {
        "analysis_mode": "general_scan",
        "comparison_window": {
            "baseline": "2026-08-01",
            "comparison_one": "2026-08-13",
            "comparison_two": "2026-08-25",
        },
    }

    result = generalize_flood_result(report_path, selection)

    assert result["analysis_type"] == "river_change_scan"
    assert result["analysis_mode"] == "general_scan"
    assert result["metrics"]["comparison_one_water_area_km2"] == 11.0
    assert result["metrics"]["comparison_two_water_area_km2"] == 12.0
    assert "post_event_water_area_km2" not in result["metrics"]
    assert result["inputs"]["dates"] == {
        "baseline": "2026-08-01",
        "comparison_one": "2026-08-13",
        "comparison_two": "2026-08-25",
    }
    warnings = [warning.lower() for warning in result["quality"]["warnings"]]
    assert any("no event date was supplied" in warning for warning in warnings)
    assert all("post-event" not in warning and "event-proximal" not in warning for warning in warnings)


def test_general_scan_morphology_report_uses_later_observation_wording(tmp_path):
    report_path = tmp_path / "river_shift_result.json"
    report_path.write_text(json.dumps({
        "schema_version": 1,
        "engine": "RiverShift",
        "analysis_type": "river_morphology_screening",
        "inputs": {"dates": {"before": "2026-08-01", "post_one": "2026-08-13", "post_two": "2026-08-25"}},
        "method": {
            "classification": "persistent_two_post_observation_water_land_transition",
            "post_observations_required": 2,
        },
        "quality": {"warnings": ["Two post-event observations reduce transient-water confusion."]},
    }), encoding="utf-8")
    selection = {
        "analysis_mode": "general_scan",
        "comparison_window": {"baseline": "2026-08-01", "comparison_one": "2026-08-13", "comparison_two": "2026-08-25"},
    }

    result = generalize_morphology_result(report_path, selection)

    assert result["analysis_mode"] == "general_scan"
    assert result["method"]["classification"] == "persistent_two_later_observation_water_land_transition"
    assert result["method"]["later_observations_required"] == 2
    assert "post_observations_required" not in result["method"]
    assert all("post-event" not in warning.lower() for warning in result["quality"]["warnings"])
    assert "no event date supplied or inferred" in result["inputs"]["comparison_basis"]


def test_source_granule_manifest_retains_download_and_hdf5_inventory_checksums(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    name = "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_20260718T155041_20260718T155059_P05023_N_F_J_001"
    receipt = {
        "granule_name": name,
        "product": "GCOV",
        "maturity": "PROVISIONAL",
        "source_host": "nisar.asf.earthdatacloud.nasa.gov",
        "size_bytes": 123456,
        "sha256": "a" * 64,
        "downloaded": True,
    }
    inventory = {
        "product_file": f"/runner/raw/{name}.h5",
        "gdal_version": "3.13.0",
        "available_diagonal_terms": [{"frequency": "frequencyA", "term": "HHHH"}],
        "available_valid_sample_masks": [{"frequency": "frequencyA", "subdataset": "mask"}],
    }
    (raw_dir / f"{name}.download.json").write_text(json.dumps(receipt))
    (raw_dir / f"{name}.gcov_inventory.json").write_text(json.dumps(inventory))

    manifest = build_source_granule_manifest(
        raw_dir, [name], maturity="PROVISIONAL", frequency="frequencyA", term="HHHH"
    )

    row = manifest["granules"][0]
    assert row["granule_name"] == name
    assert row["source_product_sha256"] == "a" * 64
    assert row["download_receipt_sha256"] == sha256_file(raw_dir / f"{name}.download.json")
    assert row["hdf5_inventory_sha256"] == sha256_file(raw_dir / f"{name}.gcov_inventory.json")
    assert row["gdal_version"] == "3.13.0"


def test_source_granule_manifest_rejects_missing_or_mismatched_receipt(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    name = "NISAR_L2_PR_GCOV_025_151_A_011_4005_DHDH_A_20260718T155041_20260718T155059_P05023_N_F_J_001"
    (raw_dir / f"{name}.download.json").write_text(json.dumps({
        "granule_name": "another-granule",
        "product": "GCOV",
        "maturity": "PROVISIONAL",
        "downloaded": True,
        "size_bytes": 1,
        "sha256": "a" * 64,
    }))
    (raw_dir / f"{name}.gcov_inventory.json").write_text(json.dumps({
        "product_file": f"/runner/raw/{name}.h5",
        "available_diagonal_terms": [{"frequency": "frequencyA", "term": "HHHH"}],
    }))

    with pytest.raises(WorkerFailure, match="does not match selected granule"):
        build_source_granule_manifest(
            raw_dir, [name], maturity="PROVISIONAL", frequency="frequencyA", term="HHHH"
        )


def test_live_worker_rejects_missing_source_sidecars(tmp_path):
    observation_paths = {}
    for key in ("before", "event", "post_one", "post_two"):
        path = tmp_path / f"{key}.tif"
        path.write_bytes(b"raster placeholder")
        observation_paths[key] = path

    with pytest.raises(WorkerFailure, match="verified exporter sidecar"):
        require_worker_source_provenance(
            observation_paths,
            maturity="PROVISIONAL",
            frequency="frequencyA",
            term="HHHH",
        )


def test_worker_input_preserves_the_catalogue_discovery_filters(monkeypatch):
    import json
    from uuid import uuid4

    granule = "NISAR_L2_PR_GCOV_024_019_D_076_4005_DHDH_A_20260802T124243_20260802T124249_P05023_N_F_J_001"
    values = {
        "RIVERSHIFT_JOB_ID": str(uuid4()),
        "RIVERSHIFT_REQUEST_FINGERPRINT": "a" * 64,
        "RIVERSHIFT_CALLBACK_URL": "https://api.example.test",
        "RIVERSHIFT_AOI_WKT": "POLYGON ((89 25, 89.1 25, 89.1 25.1, 89 25.1, 89 25))",
        "RIVERSHIFT_START_DATE": "2026-06-20",
        "RIVERSHIFT_END_DATE": "2026-09-18",
        "RIVERSHIFT_EVENT_DATE": "2026-07-23",
        "RIVERSHIFT_MATURITY": "PROVISIONAL",
        "RIVERSHIFT_MAIN_BAND_POLARIZATION": "HH+HV",
        "RIVERSHIFT_FLIGHT_DIRECTION": "DESCENDING",
        "RIVERSHIFT_FRAME_COVERAGE": "FULL",
        "RIVERSHIFT_FREQUENCY": "frequencyA",
        "RIVERSHIFT_COVARIANCE_TERM": "HHHH",
        "RIVERSHIFT_THRESHOLD_METHOD": "otsu",
        "RIVERSHIFT_THRESHOLD_DB": "",
        "RIVERSHIFT_GRANULE_NAMES_JSON": json.dumps([granule]),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    request = _read_input()

    assert request["main_band_polarization"] == "HH+HV"
    assert request["flight_direction"] == "DESCENDING"
    assert request["frame_coverage"] == "FULL"
    assert request["granule_names"] == [granule]


def test_worker_input_accepts_general_scan_without_event_date(monkeypatch):
    values = {
        "RIVERSHIFT_JOB_ID": "a7d34520-18c9-4ef0-b135-c902044338a4",
        "RIVERSHIFT_REQUEST_FINGERPRINT": "b" * 64,
        "RIVERSHIFT_AOI_WKT": "POLYGON ((89 25, 89.1 25, 89.1 25.1, 89 25.1, 89 25))",
        "RIVERSHIFT_START_DATE": "2026-06-20",
        "RIVERSHIFT_END_DATE": "2026-09-18",
        "RIVERSHIFT_ANALYSIS_MODE": "general_scan",
        "RIVERSHIFT_EVENT_DATE": "",
        "RIVERSHIFT_MATURITY": "PROVISIONAL",
        "RIVERSHIFT_FREQUENCY": "frequencyA",
        "RIVERSHIFT_COVARIANCE_TERM": "HHHH",
        "RIVERSHIFT_THRESHOLD_METHOD": "otsu",
        "RIVERSHIFT_GRANULE_NAMES_JSON": json.dumps(["NISAR_L2_PR_GCOV_001_001"]),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    request = _read_input()
    assert request["analysis_mode"] == "general_scan"
    assert request["event_date"] is None


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



def test_group_selection_skips_highest_ranked_group_without_event_bracket():
    def rows(values):
        return [
            {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": ["scene"]}
            for value in values
        ]

    first = {"relative_orbit": "101", "dates": rows(("2026-04-01", "2026-04-10", "2026-04-20", "2026-05-01"))}
    second = {"relative_orbit": "151", "dates": rows(("2026-04-20", "2026-05-15", "2026-05-31", "2026-06-15"))}

    selected_group, dates, event_window = select_event_compatible_group(
        [first, second], date(2026, 5, 2)
    )

    assert selected_group is second
    assert dates == ["2026-04-20", "2026-05-15", "2026-05-31", "2026-06-15"]
    assert event_window["event_proximal_observation"] == "2026-05-15"


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

def test_drive_preflight_uses_list_and_create_for_the_parent(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("EARTHDATA_TOKEN", "test-earthdata-token")
    monkeypatch.setenv(
        "GOOGLE_DRIVE_OAUTH_CLIENT_JSON",
        json.dumps({"client_id": "test-client", "client_secret": "test-client-secret"}),
    )
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "test-refresh-token")
    monkeypatch.setenv("GOOGLE_DRIVE_PARENT_FOLDER_ID", "parent-folder-123")

    folder_calls = []
    privacy_checks = []

    class FakeDrive:
        def __init__(self, config):
            self.config = config

        def verify_authenticated_account(self):
            return None

        def find_or_create_folder(self, name, parent_id):
            folder_calls.append((name, parent_id))
            return "fixed-rivershift-folder-id"

        def require_private_folder(self, folder_id):
            privacy_checks.append(folder_id)

        def verify_parent_folder(self, _folder_id):
            raise AssertionError("parent metadata GET must not be used as the access gate")

    monkeypatch.setattr("process_gcov_job.DriveClient", FakeDrive)

    _ensure_credentials()

    assert folder_calls == [("RiverShift", "parent-folder-123")]
    assert privacy_checks == ["fixed-rivershift-folder-id"]
    output = capsys.readouterr().out
    assert '"stage": "drive_parent_folder_access"' in output
    assert '"verification_method": "list_children_then_find_or_create"' in output
    assert "parent-folder-123" not in output
    assert "test-refresh-token" not in output



def test_event_observation_timing_reports_actual_gap_without_claiming_peak_stage():
    timing = event_observation_timing(
        date(2026, 7, 28), {"event_proximal_observation": "2026-08-17"}
    )
    assert timing["event_date"] == "2026-07-28"
    assert timing["first_post_event_observation"] == "2026-08-17"
    assert timing["offset_days"] == 20
    assert "not a measured event-peak" in timing["interpretation"]


def test_event_observation_timing_is_absent_for_general_scan():
    assert event_observation_timing(None, None) is None


def test_event_observation_timing_rejects_same_day_or_pre_event_acquisition():
    with pytest.raises(WorkerFailure) as error:
        event_observation_timing(
            date(2026, 7, 28), {"event_proximal_observation": "2026-07-28"}
        )
    assert error.value.code == "EVENT_WINDOW_INVALID"
