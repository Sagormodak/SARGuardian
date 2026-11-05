from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import rasterio
from rasterio.transform import from_origin

import tools.run_export_science_diagnostics as science_diagnostics

from tools.run_export_science_diagnostics import (
    candidate_export_mask_policy,
    classify_pixel_stack,
    export_identity,
    help_has_exact_option,
    read_candidate_points,
    write_target_log,
)


def test_export_identity_extracts_dates_and_processing_type():
    assert export_identity(Path("GUNW_20251128_20251210_PR.tif")) == (
        "20251128", "20251210", "PR"
    )
    assert export_identity(Path("GUNW_20251128_20251210_UR.tif")) == (
        "20251128", "20251210", "UR"
    )
    assert export_identity(Path("not-a-science-export.tif")) is None


def test_candidate_checker_option_detection_does_not_confuse_aoi_csv_with_aoi():
    help_text = """options:
      --target-log TARGET_LOG
      --aoi-csv AOI_CSV
      --lat LAT
      --lon LON
    """
    assert help_has_exact_option(help_text, "--aoi-csv")
    assert not help_has_exact_option(help_text, "--aoi")
    assert not help_has_exact_option(help_text, "--allow-event-affected-aoi")
    assert help_has_exact_option(
        help_text + "      --allow-event-affected-aoi\n",
        "--allow-event-affected-aoi",
    )


def test_pixel_stack_result_is_not_misreported_as_hazard_confirmation():
    assert classify_pixel_stack(0, "VERDICT: NO DETECTION. Cluster is within noise null.") == "COMPLETED_NO_DETECTION"
    assert classify_pixel_stack(
        0,
        "PIXEL_STACK_STATUS=WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK\n"
        "VERDICT: NO DETECTION. Legacy text must not override the strict gate.",
    ) == "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK"
    assert classify_pixel_stack(0, "cluster exceeds the noise-only 95th percentile") == "COMPLETED_CANDIDATE_REQUIRES_CROSS_CHECK"
    assert classify_pixel_stack(0, "VERDICT: NO DETECTION in chain A; chain B cluster exceeds the noise-only 95th percentile") == "COMPLETED_CANDIDATE_REQUIRES_CROSS_CHECK"
    assert classify_pixel_stack(1, "No contiguous chain of 2+ pairs; nothing to stack.") == "INSUFFICIENT_TEMPORAL_COVERAGE"
    assert classify_pixel_stack(1, "Traceback: invalid raster grid") == "FAIL"


def test_legacy_source_mask_fallback_is_pin_and_provenance_scoped():
    old_pin = "ab547ecc82bcc4d6ccef545a59852536c2beacc6"
    source_tags = {"source": "NISAR_L2_PR_GUNW_example.h5"}

    assert candidate_export_mask_policy(
        source_tags, aoi="source", science_commit=old_pin
    ) == (True, "LEGACY_SOURCE_PIN_WITH_SOURCE_PROVENANCE_TAG")
    assert candidate_export_mask_policy(
        source_tags, aoi="custom", science_commit=old_pin
    ) == (False, "AOI_MASK_TAG_MISSING_FOR_THIS_ENGINE_OR_AOI")
    assert candidate_export_mask_policy(
        {"source": "NISAR_L2_PR_GUNW_example.h5", "aoi_mask_applied": "false"},
        aoi="source", science_commit=old_pin,
    ) == (False, "AOI_MASK_EXPLICITLY_NOT_TRUE")
    assert candidate_export_mask_policy(
        {"aoi_mask_applied": "true"}, aoi="source", science_commit=old_pin
    ) == (False, "SOURCE_PROVENANCE_TAG_MISSING")
    assert candidate_export_mask_policy(
        {"source": "NISAR_L2_PR_GUNW_example.h5"},
        aoi="source", science_commit="10639a916c9829850775410b3ed7de62e527770d",
    ) == (False, "AOI_MASK_TAG_MISSING_FOR_THIS_ENGINE_OR_AOI")


def test_candidate_parser_only_keeps_detachment_like_valid_coordinates(tmp_path: Path):
    from tools.run_export_science_diagnostics import read_candidate_points

    path = tmp_path / "candidates.csv"
    path.write_text(
        "id,lat,lon,reading\n"
        "4,28.27799,85.52983,DETACHMENT-like\n"
        "6,28.28537,85.51250,deposit / flat\n"
        "bad,999,200,DETACHMENT-like\n"
        "5,28.27020,85.51853,DETACHMENT-like\n",
        encoding="utf-8",
    )
    points = read_candidate_points(path)
    assert [x["id"] for x in points] == ["4", "5"]
    assert points[0]["lat"] == 28.27799
    assert points[0]["lon"] == 85.52983


def test_target_log_preserves_candidate_checker_line_contract(tmp_path: Path):
    target = tmp_path / "target.log"
    write_target_log(target, [{
        "reference": "20251125",
        "secondary": "20251207",
        "median_mm": 1.2,
        "valid_pixels": 25,
        "median_coherence": 0.8,
        "raster": "GUNW_20251125_20251207_PR.tif",
    }])
    text = target.read_text(encoding="utf-8")
    assert "2025-11-25 -> 2025-12-07 : 1.2000 mm (25 px, coh 0.8000)" in text


def test_pixel_stack_runs_and_exports_both_common_mode_variants(tmp_path, monkeypatch):
    science_root = tmp_path / "science"
    pixel_script = science_root / "src" / "pixel_stack.py"
    pixel_script.parent.mkdir(parents=True)
    pixel_script.write_text("# fixture pixel stack entry point\n", encoding="utf-8")
    exports_root = tmp_path / "exports"
    exports_root.mkdir()
    raster_path = exports_root / "GUNW_20260101_20260113_PR.tif"
    with rasterio.open(
        raster_path, "w", driver="GTiff", width=3, height=3, count=1,
        dtype="float32", crs="EPSG:32645",
        transform=from_origin(500000, 3200000, 80, 80), nodata=float("nan"),
    ) as ds:
        ds.write(__import__("numpy").ones((3, 3), dtype="float32"), 1)

    calls = []
    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == "git":
            return SimpleNamespace(returncode=0, stdout="expected-science-sha\n")
        return SimpleNamespace(
            returncode=0,
            stdout="VERDICT: NO DETECTION. Cluster is within noise null.\n",
        )

    monkeypatch.setattr(science_diagnostics.subprocess, "run", fake_run)
    report = science_diagnostics.run_diagnostics(
        science_root, exports_root, tmp_path / "diagnostics",
        expected_science_commit="expected-science-sha",
    )

    stack_calls = [argv for argv in calls if "pixel_stack.py" in " ".join(argv)]
    assert len(stack_calls) == 2, "both common-mode policies must be executed"
    removed, retained = stack_calls
    assert "--keep-common-mode" not in removed
    assert "--keep-common-mode" in retained
    assert removed[removed.index("--geotiff") + 1].endswith(
        "pixel-stack-maps/common-mode-removed/GUNW_LOS_velocity.tif"
    )
    assert retained[retained.index("--geotiff") + 1].endswith(
        "pixel-stack-maps/common-mode-retained/GUNW_LOS_velocity.tif"
    )
    assert report["pixel_stack"]["common_mode_policy"] == "PAIRWISE_MEDIAN_REMOVED"
    assert report["common_mode_sensitivity"]["common_mode_policy"] == "PAIRWISE_MEDIAN_RETAINED"
    assert report["pixel_stack"]["status"] == "COMPLETED_NO_DETECTION"
    assert report["common_mode_sensitivity"]["status"] == "COMPLETED_NO_DETECTION"
    written = (tmp_path / "diagnostics" / "science-diagnostics.json").read_text(encoding="utf-8")
    assert '"common_mode_sensitivity"' in written
