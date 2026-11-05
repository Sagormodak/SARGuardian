from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin

from dashboard.aoi_relative_pixel_timeseries import build_aoi_relative_pixel_timeseries_report


def _write_gunw(root: Path, product_id: str, reference: str, secondary: str, offset: float, seed: int) -> dict:
    """Create a synthetic pair on one common grid; never used as real NISAR evidence."""
    granule = (
        f"NISAR_L2_PR_GUNW_022_098_A_016_023_4000_SH_"
        f"{reference.replace('-', '')}T000000_{reference.replace('-', '')}T000030_"
        f"{secondary.replace('-', '')}T000000_{secondary.replace('-', '')}T000030_"
        "X05026_N_F_J_001"
    )
    folder = root / "product-data" / product_id
    folder.mkdir(parents=True, exist_ok=True)
    raster_path = folder / f"GUNW_{reference.replace('-', '')}_{secondary.replace('-', '')}.tif"

    rng = np.random.default_rng(seed)
    values = rng.normal(0.0, 0.75, size=(80, 80)).astype("float32")
    # A localized synthetic signal is deliberately shared between pairs. It is
    # a test fixture only, not an empirical displacement estimate.
    values[28:40, 32:44] += offset
    coherence = np.ones((80, 80), dtype="float32")
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=80,
        width=80,
        count=2,
        dtype="float32",
        crs="EPSG:32645",
        transform=from_origin(500000, 3000000, 80, 80),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)
        dataset.write(coherence, 2)
        dataset.set_band_description(1, "LOS displacement (mm)")
        dataset.set_band_description(2, "coherence")
        dataset.update_tags(
            aoi_name="custom",
            aoi_mask_applied="true",
            grid_policy="common_aoi_lattice",
            export_status="WRITTEN",
            source=granule + ".h5",
        )

    return {
        "id": product_id,
        "product_type": "GUNW",
        "granule_name": granule,
        "reference_date": reference,
        "secondary_date": secondary,
        "valid_pixels": 6400,
        "stats": {"mean_coherence": 1.0},
        "exports": [{
            "name": raster_path.name,
            "relative_path": raster_path.relative_to(root).as_posix(),
        }],
    }


class AOIRelativePixelTimeseriesTests(unittest.TestCase):
    def test_target_free_redundant_network_writes_relative_velocity_and_quality_rasters(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            products = [
                _write_gunw(root, "GUNW-001", "2026-08-01", "2026-08-13", 8.0, 7),
                _write_gunw(root, "GUNW-002", "2026-08-13", "2026-08-25", 8.0, 19),
                _write_gunw(root, "GUNW-003", "2026-08-01", "2026-08-25", 16.0, 31),
            ]

            report = build_aoi_relative_pixel_timeseries_report(
                products,
                root,
                "a" * 64,
                minimum_pairs=3,
                minimum_redundancy=1,
                minimum_common_valid_pixels=200,
            )

            self.assertFalse(report["target_required"])
            self.assertFalse(report["reference_independently_validated"])
            self.assertFalse(report["movement_confirmed"])
            self.assertFalse(report["hazard_detected"])
            self.assertEqual(report["status"], "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE")
            self.assertEqual(report["networks_calculated"], 1)

            network = report["networks"][0]
            self.assertEqual(network["status"], "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_REFERENCE_UNVALIDATED")
            self.assertEqual(network["pair_count"], 3)
            self.assertEqual(network["epoch_count"], 3)
            self.assertEqual(network["redundancy"], 1)
            self.assertGreaterEqual(network["common_valid_pixels"], 200)
            self.assertGreaterEqual(network["reference_pixels"], 200)
            self.assertGreaterEqual(network["minimum_spatial_reference_blocks_observed"], 4)
            self.assertFalse(network["reference_independent_stability"])
            self.assertIn("spatially balanced", network["reference_policy"].lower())

            artifacts = network["artifacts"]
            self.assertTrue(any("velocity-mm-year" in item["relative_path"] for item in artifacts))
            self.assertTrue(any("closure-rmse" in item["relative_path"] for item in artifacts))
            for required in (
                "candidate-mask", "candidate-pair-count", "observed-pair-count",
                "common-reference-mask",
            ):
                self.assertTrue(any(required in item["relative_path"] for item in artifacts), required)
            for item in artifacts:
                relative = Path(item["relative_path"])
                self.assertFalse(relative.is_absolute())
                artifact_path = root / relative
                self.assertTrue(artifact_path.is_file(), item["relative_path"])
                with rasterio.open(artifact_path) as dataset:
                    tags = dataset.tags()
                    self.assertEqual(tags["target_required"], "false")
                    self.assertEqual(tags["movement_confirmed"], "false")
                    self.assertEqual(tags["hazard_detected"], "false")
                    self.assertEqual(tags["aoi_wkt_sha256"], "a" * 64)

            saved = json.loads((root / "aoi-relative-pixel-timeseries.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], report["status"])
            self.assertEqual(len(saved["networks"]), 1)

    def test_no_target_is_not_a_blocker_for_spatial_pixel_inversion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            products = [
                _write_gunw(root, "GUNW-001", "2026-08-01", "2026-08-13", 8.0, 7),
                _write_gunw(root, "GUNW-002", "2026-08-13", "2026-08-25", 8.0, 19),
                _write_gunw(root, "GUNW-003", "2026-08-01", "2026-08-25", 16.0, 31),
            ]
            # No target coordinate or target metadata is supplied to this API.
            report = build_aoi_relative_pixel_timeseries_report(products, root, "b" * 64)
            self.assertFalse(report["target_required"])
            self.assertNotEqual(report["status"], "BLOCKED_NO_VALID_IN_AOI_TARGET")

    def test_spatially_concentrated_reference_is_withheld(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            products = [
                _write_gunw(root, "GUNW-001", "2026-08-01", "2026-08-13", 8.0, 7),
                _write_gunw(root, "GUNW-002", "2026-08-13", "2026-08-25", 8.0, 19),
                _write_gunw(root, "GUNW-003", "2026-08-01", "2026-08-25", 16.0, 31),
            ]

            def concentrated_candidate(item, **kwargs):
                candidate = np.ones((80, 80), dtype=bool)
                candidate[:20, :20] = False
                return item | {
                    "score_status": "SCORED",
                    "candidate_mask": candidate,
                    "score": candidate.astype("float32") * 5.0,
                    "valid_pixels": 6400,
                }

            with patch(
                "dashboard.aoi_relative_pixel_timeseries._score_pair",
                side_effect=concentrated_candidate,
            ):
                report = build_aoi_relative_pixel_timeseries_report(
                    products, root, "d" * 64,
                    minimum_pairs=3,
                    minimum_redundancy=1,
                    minimum_common_valid_pixels=200,
                    minimum_reference_blocks=4,
                )

            self.assertEqual(report["status"], "WITHHELD_SCIENCE_GATES")
            network = report["networks"][0]
            self.assertEqual(network["status"], "WITHHELD_POOR_REFERENCE_SPATIAL_DISTRIBUTION")
            self.assertEqual(network["minimum_spatial_reference_blocks_observed"], 1)
            self.assertEqual(network["artifacts"], [])
            self.assertFalse(report["movement_confirmed"])
            self.assertFalse(report["hazard_detected"])

    def test_network_without_redundant_cycles_is_withheld(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            products = [
                _write_gunw(root, "GUNW-001", "2026-08-01", "2026-08-13", 8.0, 7),
                _write_gunw(root, "GUNW-002", "2026-08-13", "2026-08-25", 8.0, 19),
            ]
            report = build_aoi_relative_pixel_timeseries_report(products, root, "c" * 64)
            self.assertEqual(report["status"], "WITHHELD_SCIENCE_GATES")
            self.assertFalse(report["movement_confirmed"])
            self.assertFalse(report["hazard_detected"])
            self.assertEqual(report["networks"][0]["status"], "WITHHELD_TOO_FEW_PAIRS")
            self.assertEqual(report["artifacts"], [])


if __name__ == "__main__":
    unittest.main()
