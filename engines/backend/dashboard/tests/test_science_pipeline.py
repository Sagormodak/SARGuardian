from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from dashboard.science_pipeline import build_science_pipeline_report


class SciencePipelineReportTests(unittest.TestCase):
    def test_network_topology_is_reported_without_fabricating_common_datum_series(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            fake = ModuleType("timeseries")
            fake.granule_metadata = lambda name: {
                "path": 48, "direction": "D", "product": "GUNW", "cycle": 26,
                "frame": 71, "subswath": 28, "bandwidth": 4000,
                "polarisation": "SH", "crid": "P05023", "processing": "PR",
            }

            class Pair:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

            fake.Pair = Pair
            fake.describe_network = lambda pairs: {
                "DESC path 048 frame 071 CRID P05023 GUNW": [
                    {"epochs": ["2026-07-11", "2026-07-23", "2026-08-16"], "n_pairs": 2, "redundancy": 0}
                ]
            }

            products = [
                {
                    "id": "GUNW-001", "product_type": "GUNW",
                    "granule_name": "NISAR_L2_PR_GUNW_026_048_D_071_028_4000_SH_20260711T000000_20260711T000000_20260723T000000_20260723T000000_P05023_N_F_J_001",
                    "reference_date": "2026-07-11", "secondary_date": "2026-07-23",
                    "valid_pixels": 10, "stats": {"mean_coherence": 0.6},
                },
                {
                    "id": "GUNW-002", "product_type": "GUNW",
                    "granule_name": "NISAR_L2_PR_GUNW_026_048_D_071_028_4000_SH_20260723T000000_20260723T000000_20260816T000000_20260816T000000_P05023_N_F_J_001",
                    "reference_date": "2026-07-23", "secondary_date": "2026-08-16",
                    "valid_pixels": 10, "stats": {"mean_coherence": 0.6},
                },
            ]

            with patch.dict("sys.modules", {"timeseries": fake}):
                report = build_science_pipeline_report(products, tmp_path, {"pixel_stack": {"status": "COMPLETED_NO_DETECTION"}})

        self.assertEqual(report["network_assessment_status"], "COMPLETED")
        self.assertEqual(report["overall_status"], "NETWORK_ASSESSED_WITH_DOWNSTREAM_STAGES_WITHHELD")
        self.assertEqual(report["networks"][0]["redundancy"], 0)
        self.assertEqual(report["networks"][0]["topology_status"], "EXACTLY_DETERMINED_NO_REDUNDANCY")
        stages = {row["name"]: row["status"] for row in report["modules"]}
        self.assertEqual(stages["timeseries.py"], "NETWORK_TOPOLOGY_ONLY_INVERSION_WITHHELD")
        self.assertEqual(stages["local_floor.py"], "NOT_REQUIRED_FOR_TARGET_FREE_FIND_DISPLACEMENTS")
        self.assertEqual(stages["inverse_velocity.py"], "WITHHELD_NO_CANDIDATE_SERIES_ON_INDEPENDENT_REFERENCE")
        self.assertEqual(stages["geometry_merge.py"], "WITHHELD_NO_PIXELWISE_LOOK_VECTORS_AND_TERRAIN_REFERENCE")
        self.assertEqual(stages["bound.py"], "NOT_APPLICABLE_GENERIC_AOI_BY_DESIGN")
        self.assertFalse(report["structural_validation_is_geophysical_validation"])

    def test_no_data_run_keeps_downstream_methods_blocked_and_reports_reader_coverage(self) -> None:
        fake = ModuleType("timeseries")
        fake.granule_metadata = lambda name: None
        fake.Pair = object
        fake.describe_network = lambda pairs: {}
        with patch.dict("sys.modules", {"timeseries": fake}):
            report = build_science_pipeline_report([], Path(tempfile.gettempdir()), {
                "candidate_checks": {"status": "SKIPPED_UNSUPPORTED_CUSTOM_AOI"}
            })
        stages = {row["name"]: row["status"] for row in report["modules"]}
        self.assertEqual(stages["gunw_reader.py"], "NO_GUNW_PRODUCTS")
        self.assertEqual(stages["goff_reader.py"], "NO_GOFF_PRODUCTS")
        self.assertEqual(stages["local_floor.py"], "NOT_REQUIRED_FOR_TARGET_FREE_FIND_DISPLACEMENTS")
        self.assertEqual(stages["bound.py"], "NOT_APPLICABLE_GENERIC_AOI_BY_DESIGN")


    def test_candidate_without_local_background_is_explicitly_withheld(self) -> None:
        fake = ModuleType("timeseries")
        fake.granule_metadata = lambda name: None
        fake.Pair = object
        fake.describe_network = lambda pairs: {}
        with patch.dict("sys.modules", {"timeseries": fake}):
            report = build_science_pipeline_report(
                [], Path(tempfile.gettempdir()),
                {"candidate_checks": {"status": "SKIPPED_UNSUPPORTED_CUSTOM_AOI"}},
                site_context={"measurement_target": {"status": "NOT_PROVIDED"}},
                common_reference_report={"status": "NOT_RUN_TARGET_FREE_FIND_DISPLACEMENTS"},
                aoi_displacement_candidates={
                    "status": "SINGLE_PAIR_CANDIDATES_NEED_TEMPORAL_CONFIRMATION",
                    "candidate_local_floor_measurements": 0,
                    "features": [{"type": "Feature", "properties": {"status": "SINGLE_PAIR_CANDIDATE_UNCONFIRMED"}}],
                },
            )
        stages = {row["name"]: row for row in report["modules"]}
        self.assertEqual(
            stages["local_floor.py"]["status"],
            "WITHHELD_INSUFFICIENT_CANDIDATE_LOCAL_BACKGROUND",
        )
        self.assertIn("minimum 30 valid nearby background pixels", stages["local_floor.py"]["reason"])


    def test_find_displacements_reports_target_free_stages_and_keeps_known_place_gates_separate(self) -> None:
        fake = ModuleType("timeseries")
        fake.granule_metadata = lambda name: None
        fake.Pair = object
        fake.describe_network = lambda pairs: {}
        relative = {
            "status": "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE",
            "networks_calculated": 2,
            "networks": [{"status": "AVAILABLE"}, {"status": "AVAILABLE"}],
            "reference_independently_validated": False,
            "reason": "Two compatible networks were inverted on an AOI-derived reference.",
        }
        candidates = {
            "status": "REPEATED_SPATIAL_CANDIDATES_NEED_GEOPHYSICAL_VALIDATION",
            "candidate_features": 4,
            "products_examined": 12,
            "candidate_local_floor_measurements": 5,
            "features": [
                {"properties": {
                    "candidate_seasonality_inventory": {"status": "MULTI_SEASON_SUPPORT_PRESENT"},
                    "candidate_phase_ceiling_review": {"status": "EXCEEDS_SINGLE_FRINGE_REVIEW_THRESHOLD"},
                }},
                {"properties": {
                    "candidate_seasonality_inventory": {"status": "INSUFFICIENT_SEASONAL_COVERAGE"},
                    "candidate_phase_ceiling_review": {"status": "WITHIN_SINGLE_FRINGE_REVIEW_THRESHOLD"},
                }},
                {"properties": {
                    "candidate_seasonality_inventory": {"status": "MULTI_SEASON_SUPPORT_PRESENT"},
                    "candidate_phase_ceiling_review": {"status": "WITHIN_SINGLE_FRINGE_REVIEW_THRESHOLD"},
                }},
                {"properties": {
                    "candidate_seasonality_inventory": {"status": "INSUFFICIENT_SEASONAL_COVERAGE"},
                    "candidate_phase_ceiling_review": {"status": "NOT_APPLICABLE_NON_GUNW_OFFSET_METRIC"},
                }},
            ],
            "reason": "Repeated spatial candidates found.",
        }
        goff = {
            "status": "COMPLETED_EXPLORATORY_RANKING",
            "candidate_count": 3,
            "series_count": 2,
            "reason": "GOFF candidates available.",
        }
        with patch.dict("sys.modules", {"timeseries": fake}):
            report = build_science_pipeline_report(
                [], Path(tempfile.gettempdir()),
                {"candidate_checks": {"status": "SKIPPED_UNSUPPORTED_CUSTOM_AOI"}},
                site_context={"measurement_target": {"status": "NOT_PROVIDED"}},
                common_reference_report={"status": "NOT_RUN_TARGET_FREE_FIND_DISPLACEMENTS"},
                aoi_displacement_candidates=candidates,
                aoi_relative_pixel_timeseries=relative,
                aoi_wide_screen=goff,
            )

        stages = {row["name"]: row for row in report["modules"]}
        self.assertEqual(
            stages["aoi_wide_displacement_screen.py"]["status"],
            "COMPLETED_EXPLORATORY_RANKING",
        )
        self.assertFalse(stages["aoi_wide_displacement_screen.py"]["target_required"])
        self.assertEqual(
            stages["aoi_displacement_candidates.py"]["candidate_features"], 4,
        )
        self.assertEqual(
            stages["aoi_relative_pixel_timeseries.py"]["networks_calculated"], 2,
        )
        self.assertEqual(
            stages["timeseries.py"]["status"],
            "AOI_RELATIVE_PIXEL_DIAGNOSTIC_AVAILABLE_REFERENCE_UNVALIDATED",
        )
        self.assertEqual(
            stages["common_ref.py"]["status"],
            "NOT_REQUIRED_FOR_TARGET_FREE_FIND_DISPLACEMENTS",
        )
        self.assertEqual(
            stages["local_floor.py"]["status"],
            "CANDIDATE_REGION_LOCAL_FLOORS_MEASURED",
        )
        self.assertEqual(
            stages["local_floor.py"]["candidate_region_local_floor_measurements"], 5,
        )
        self.assertEqual(
            stages["candidate_check.py"]["status"],
            "PARTIAL_TARGET_FREE_CANDIDATE_STRESS_TESTS_WITH_CROSS_GEOMETRY_WITHHELD",
        )
        self.assertEqual(stages["candidate_check.py"]["candidate_features_reviewed"], 4)
        self.assertEqual(stages["candidate_check.py"]["features_with_multi_season_acquisition_support"], 2)
        self.assertEqual(stages["candidate_check.py"]["features_exceeding_gunw_single_fringe_review_threshold"], 1)
        self.assertEqual(
            stages["inverse_velocity.py"]["status"],
            "WITHHELD_NO_CANDIDATE_SERIES_ON_INDEPENDENT_REFERENCE",
        )
        self.assertEqual(
            stages["geometry_merge.py"]["status"],
            "WITHHELD_NO_PIXELWISE_LOOK_VECTORS_AND_TERRAIN_REFERENCE",
        )
        self.assertEqual(
            stages["bound.py"]["status"],
            "NOT_APPLICABLE_GENERIC_AOI_BY_DESIGN",
        )
        self.assertEqual(
            report["overall_status"],
            "AOI_RELATIVE_PIXEL_DIAGNOSTICS_AVAILABLE_REFERENCE_UNVALIDATED",
        )
        self.assertFalse(report["structural_validation_is_geophysical_validation"])



    def test_unusable_rasters_do_not_claim_target_free_discovery_completed(self) -> None:
        fake = ModuleType("timeseries")
        fake.granule_metadata = lambda name: None
        fake.Pair = object
        fake.describe_network = lambda pairs: {}
        with patch.dict("sys.modules", {"timeseries": fake}):
            report = build_science_pipeline_report(
                [], Path(tempfile.gettempdir()),
                {"candidate_checks": {"status": "SKIPPED_UNSUPPORTED_CUSTOM_AOI"}},
                site_context={"measurement_target": {"status": "NOT_PROVIDED"}},
                common_reference_report={"status": "NOT_RUN_TARGET_FREE_FIND_DISPLACEMENTS"},
                aoi_displacement_candidates={"status": "NO_ELIGIBLE_RASTER_EXPORTS", "features": []},
                aoi_relative_pixel_timeseries={"status": "NO_ELIGIBLE_GUNW_EXPORTS", "networks": []},
                aoi_wide_screen={"status": "NO_USABLE_GOFF_SERIES", "series": []},
            )
        stages = {row["name"]: row for row in report["modules"]}
        self.assertEqual(
            stages["candidate_check.py"]["status"],
            "NOT_TESTABLE_NO_ELIGIBLE_RASTER_EXPORTS",
        )
        self.assertEqual(
            report["overall_status"],
            "PARTIAL_STAGE_ASSESSMENT",
        )

if __name__ == "__main__":
    unittest.main()
