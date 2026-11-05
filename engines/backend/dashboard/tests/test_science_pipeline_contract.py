from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / "dashboard" / "assets" / "prepare_web_assets.py"
AGGREGATOR = ROOT / "tools" / "aggregate_aoi_run.py"
PIPELINE = ROOT / "dashboard" / "science_pipeline.py"
RETAINED_REFRESH = ROOT / ".github" / "workflows" / "dashboard-real-artifact-smoke.yml"


class SciencePipelineContractTests(unittest.TestCase):
    def test_real_goff_metrics_are_carried_to_the_interactive_viewer(self) -> None:
        builder = BUILDER.read_text(encoding="utf-8")
        self.assertIn('"goff_range_median_mm": metric_number(stats.get("range_median_mm"))', builder)
        self.assertIn('"goff_azimuth_median_mm": metric_number(stats.get("azimuth_median_mm"))', builder)
        self.assertIn('"goff_detect_floor_mm_day": metric_number(stats.get("detect_floor_mm_day"))', builder)
        self.assertIn("GOFF range-offset median (mm)", builder)
        self.assertIn("GOFF along-track offset median (mm)", builder)
        self.assertIn("GOFF detection floor (mm/day)", builder)
        self.assertIn("detection floors are noise bounds, not observed motion", builder)
        self.assertIn('"target_local_los_median_mm": metric_number(target_metrics.get("target_local_los_median_mm"))', builder)
        self.assertIn('"target_local_floor_mm_day": metric_number(floor_metrics.get("local_floor_mm_day"))', builder)
        self.assertIn("selected-site-marker", builder)
        self.assertIn("selected-target-marker", builder)
        self.assertIn("compare-target-marker", builder)
        self.assertIn('"site_context": summary.get("site_context") or {}', builder)
        self.assertIn("sameSourceGrid(a,b)", builder)
        self.assertIn("function compatiblePair(a,b)", builder)
        self.assertIn("function metricUncertainty(p,key)", builder)
        self.assertIn("target_local_floor_ci_hi_mm_day", builder)
        self.assertIn("Selected bands do not satisfy the common-grid and common-band contract", builder)
        self.assertIn("not a forecast", builder.lower())
        self.assertIn("This ratio is a simple sensitivity comparison", builder)

    def test_every_main_science_module_has_an_explicit_dynamic_aoi_stage_gate(self) -> None:
        pipeline = PIPELINE.read_text(encoding="utf-8")
        aggregator = AGGREGATOR.read_text(encoding="utf-8")
        builder = BUILDER.read_text(encoding="utf-8")
        for name in (
            "timeseries.py", "local_floor.py", "inverse_velocity.py",
            "geometry_merge.py", "bound.py", "gunw_reader.py", "goff_reader.py",
            "pixel_stack.py", "candidate_check.py",
        ):
            self.assertIn(name, pipeline)
        self.assertIn("timeseries.describe_network(pairs)", pipeline)
        self.assertIn("NETWORK_TOPOLOGY_ONLY_INVERSION_WITHHELD", pipeline)
        self.assertIn("NOT_REQUIRED_FOR_TARGET_FREE_FIND_DISPLACEMENTS", pipeline)
        self.assertIn("WITHHELD_NO_CANDIDATE_SERIES_ON_INDEPENDENT_REFERENCE", pipeline)
        self.assertIn("PAIRWISE_LOCAL_FLOOR_MEASURED", pipeline)
        self.assertIn("measured_targets", pipeline)
        self.assertIn("NOT_APPLICABLE_GENERIC_AOI_BY_DESIGN", pipeline)
        self.assertIn("aoi_relative_pixel_timeseries.py", pipeline)
        self.assertIn("aoi_wide_displacement_screen.py", pipeline)
        self.assertIn("PARTIAL_TARGET_FREE_CANDIDATE_STRESS_TESTS_WITH_CROSS_GEOMETRY_WITHHELD", pipeline)
        self.assertIn("OPTIONAL_POINT_LOCAL_DIAGNOSTIC_WITH_TARGET_FREE_CANDIDATE_EXTENSION", pipeline)
        self.assertIn("build_science_pipeline_report", aggregator)
        self.assertIn("aoi_displacement_candidates,\n            aoi_relative_pixel_timeseries, aoi_wide_screen,", aggregator)
        self.assertIn('"science_pipeline":science_pipeline', aggregator)
        self.assertIn('science-pipeline-report.json', aggregator)
        self.assertIn('"science_pipeline": summary.get("science_pipeline") or {}', builder)


    def test_retained_artifact_refresh_recomputes_target_free_candidates_without_raw_replay(self) -> None:
        workflow = RETAINED_REFRESH.read_text(encoding="utf-8")
        self.assertIn("Download the existing verified AOI dashboard artifact", workflow)
        self.assertIn("build_aoi_spatial_candidate_report", workflow)
        self.assertIn("build_science_pipeline_report", workflow)
        self.assertIn("CANDIDATE_LOCAL_FLOOR_MEASUREMENTS=", workflow)
        self.assertIn("CANDIDATE_FEATURES_WITH_LOCAL_FLOOR=", workflow)
        self.assertIn("RAW_HDF5_REPLAYED=false", workflow)
        self.assertIn("SOURCE_TIFFS_UNCHANGED=PASS", workflow)
        self.assertIn("WITHHELD_NO_CANDIDATE_SERIES_ON_INDEPENDENT_REFERENCE", workflow)
        self.assertIn("WITHHELD_NO_PIXELWISE_LOOK_VECTORS_AND_TERRAIN_REFERENCE", workflow)
        self.assertIn('science_pipeline["science_commit_expected"] = retained_audit_commit', workflow)
        self.assertIn('science_pipeline["source_processing_science_commit"] = source_processing_commit', workflow)
        self.assertIn('science_pipeline["science_reaudit_commit"] = retained_audit_commit', workflow)
        self.assertIn('assert retained_audit_commit == "006d4cd1485cf80e509eaf8717c12e9c6390ac09"', workflow)


if __name__ == "__main__":
    unittest.main()
