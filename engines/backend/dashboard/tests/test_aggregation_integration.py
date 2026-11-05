from __future__ import annotations

from pathlib import Path

from tools.aggregate_aoi_run import measurement_aoi_grid_count


ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR = ROOT / "tools" / "aggregate_aoi_run.py"
ACCOUNT_WORKFLOW = ROOT / ".github" / "workflows" / "sarguardian-aoi-wkt-dashboard.yml"
DASHBOARD_BUILDER = ROOT / "dashboard" / "assets" / "prepare_web_assets.py"


def test_map_assets_are_built_before_zip_and_final_status_is_packaged() -> None:
    aggregator = AGGREGATOR.read_text(encoding="utf-8")
    builder_at = aggregator.index("prepare_web_dashboard(out)")
    zip_at = aggregator.index('zip_path=out/"aoi-derived-results.zip"')
    status_at = aggregator.index('summary["web_dashboard"] = web_dashboard')
    final_summary_at = aggregator.index('(out/"aoi-run-summary.json").write_text', status_at)
    final_report_at = aggregator.index('(out/"aoi-processing-report.json").write_text', status_at)

    assert builder_at < status_at < final_summary_at < zip_at
    assert status_at < final_report_at < zip_at
    assert "WEB_DASHBOARD_STATUS=" in aggregator
    assert "source_geotiffs_unchanged" in aggregator


def test_existing_private_drive_upload_and_required_account_files_remain() -> None:
    workflow = ACCOUNT_WORKFLOW.read_text(encoding="utf-8")
    aggregator_step = workflow.index("- name: Build dashboard, product table, quicklooks and result bundle")
    drive_upload_step = workflow.index("- name: Upload dashboard bundle and summary to private Drive")
    assert aggregator_step < drive_upload_step
    drive_section = workflow[drive_upload_step:]
    assert '"$root/aoi-derived-results.zip" "$root/aoi-run-summary.json" "$root/products.csv"' in drive_section
    assert "drive_resumable_upload.py" in drive_section
    assert "Upload offline HTML dashboard and result files" in workflow


def test_account_workflow_reports_dashboard_status_and_uses_retry_enabled_callback_contract() -> None:
    workflow = ACCOUNT_WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count("db6472e1c304e21242f1ab1dfd671ccb21ba5697") == 2
    assert "Interactive web-dashboard assets" in workflow
    assert "web-dashboard/index.html" in workflow
    assert "Report validated terminal state" in workflow
    assert "REQUEST_FINGERPRINT" in workflow


def test_display_builder_does_not_mutate_source_or_redownload_raw_data() -> None:
    builder = DASHBOARD_BUILDER.read_text(encoding="utf-8")
    assert "reproject_band(raster_path, band, geometry)" in builder
    assert "source_geotiffs_unchanged" in builder
    assert "urlopen(" not in builder
    assert "requests.get(" not in builder
    assert '"license": "other"' in builder
    assert builder.count('"rel": "license"') >= 2
    assert "does not relicense source data" in builder


def test_gunw_aoi_denominator_uses_unwrapped_phase_grid_not_geometry_merge_grid() -> None:
    preflight = {
        "grid_checks": [
            {"grid": "GUNW_unwrappedInterferogram", "grid_pixels_inside_aoi": 109924},
            {"grid": "GUNW_geometry_merge_radarGrid", "grid_pixels_inside_aoi": 2813},
        ]
    }
    selected, basis = measurement_aoi_grid_count(preflight, "GUNW")
    assert selected == 109924
    assert basis["selected_grid"] == "GUNW_unwrappedInterferogram"
    assert basis["counts_by_grid"]["GUNW_geometry_merge_radarGrid"] == 2813


def test_goff_uses_one_consistent_offset_lattice_count() -> None:
    preflight = {
        "grid_checks": [
            {"grid": "GOFF_pixelOffsets", "grid_pixels_inside_aoi": 110425},
            {"grid": "GOFF_pixelOffsets", "grid_pixels_inside_aoi": 110425},
            {"grid": "GOFF_pixelOffsets", "grid_pixels_inside_aoi": 110425},
        ]
    }
    selected, basis = measurement_aoi_grid_count(preflight, "GOFF")
    assert selected == 110425
    assert basis["selected_grid"] == "GOFF_pixelOffsets"
