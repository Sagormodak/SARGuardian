from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds

from dashboard.assets.prepare_web_assets import prepare_web_dashboard, write_viewer


class PrepareWebAssetsTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, str]:
        (root / "product-data" / "GUNW-001").mkdir(parents=True)
        ring = [
            [90.3864, 24.7518], [90.41565, 24.77163],
            [90.4433, 24.7479], [90.4024, 24.7211],
            [90.3864, 24.7518],
        ]
        wkt = "POLYGON ((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"
        bounds = transform_bounds("EPSG:4326", "EPSG:32646", 90.38, 24.715, 90.45, 24.78)
        transform = from_bounds(*bounds, 4, 4)
        tif = root / "product-data" / "GUNW-001" / "fixture.tif"
        los = np.array([[1, 2, np.nan, -3], [4, 5, 6, 7], [8, 9, 10, 11], [12, 13, 14, 15]], dtype="float32")
        coherence = np.array([[.2, .3, .4, .5], [.6, .7, .8, .9], [.3, .4, .5, .6], [.7, .8, .9, 1.0]], dtype="float32")
        with rasterio.open(
            tif, "w", driver="GTiff", width=4, height=4, count=2,
            dtype="float32", crs="EPSG:32646", transform=transform, nodata=np.nan,
        ) as ds:
            ds.write(los, 1)
            ds.write(coherence, 2)
            ds.set_band_description(1, "LOS displacement (mm)")
            ds.set_band_description(2, "coherence")
            ds.update_tags(aoi_mask_applied="true", source="synthetic test fixture")
        tif_hash = hashlib.sha256(tif.read_bytes()).hexdigest()
        product = {
            "id": "GUNW-001", "product_type": "GUNW", "granule_name": "fixture-product",
            "reference_date": "2026-07-21", "secondary_date": "2026-08-14",
            "maturity": "PROVISIONAL", "crid": "P05023", "status": "PASS",
            "valid_pixels": 15, "grid_pixels_inside_aoi": 16, "metric_name": "median", "metric_value": 6.0,
            "source_sha256": "a" * 64, "warnings": [],
            "stats": {"track": "DESC 091", "mean_coherence": 0.6},
            "exports": [{"name": "fixture.tif", "relative_path": "product-data/GUNW-001/fixture.tif", "quicklook": None}],
            "validation_scope": "structural_and_provenance_not_independent_geophysical_validation",
            "target_measurement": {
                "status": "MEASURED",
                "measurements": {
                    "target_local_los_median_mm": 2.5, "target_local_range_median_mm": None,
                    "target_local_azimuth_median_mm": None, "mean_coherence": 0.62,
                },
            },
            "local_floor": {
                "status": "MEASURED",
                "metrics": {"radius_px": 6, "local_floor_mm_day": 8.1,
                            "local_floor_ci_lo_mm_day": 6.0, "local_floor_ci_hi_mm_day": 10.5},
            },
        }
        summary = {
            "schema_version": "sarguardian-aoi-dashboard-summary/1.0", "status": "PASS",
            "run_id": "fixture-run", "science_commit": "b" * 40, "orchestration_sha": "c" * 40,
            "aoi_name": "custom", "aoi_crs": "EPSG:4326", "aoi_wkt": wkt,
            "aoi_wkt_sha256": "d" * 64, "date_start": "2026-08-01", "date_end": "2026-08-20",
            "date_basis": "secondary_acquisition_date_from_granule_identifier",
            "date_filter_mode": "secondary-acquisition-in-window", "products_expected": 1,
            "products_validated": 1, "products_missing": 0, "gunw_count": 1, "goff_count": 0,
            "science_diagnostics": {"pixel_stack": {"status": "COMPLETED"}, "candidate_checks": {"status": "SKIPPED_UNSUPPORTED_CUSTOM_AOI", "detail": "test fixture"}},
            "science_claim_limit": "Structural validation does not independently validate geophysical accuracy.",
            "site_context": {
                "place": {"name": "Test ridge", "latitude": 24.7518, "longitude": 90.3864,
                          "coordinates_status": "VALID", "inside_aoi": True},
                "measurement_target": {"status": "IN_AOI_TARGET_CAPTURED", "latitude": 24.7518,
                                       "longitude": 90.3864, "used_by_reader": False, "is_measurement": False},
            },
            "target_measurement_count": 1,
            "local_floor_count": 1,
            "common_reference_timeseries": {
                "schema_version": "sarguardian-common-reference-timeseries/1.0",
                "status": "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED",
                "reason": "Test-only connected synthetic network passes structural gates; external stable-ground reference is not validated.",
                "networks": [{
                    "network": "DESC path 091 frame 01 CRID P05023 GUNW",
                    "common_pixels_outside_target_buffer": 240,
                }],
                "components": [{
                    "network": "DESC path 091 frame 01 CRID P05023 GUNW",
                    "component": 1,
                    "status": "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED",
                    "pairs_count": 4,
                    "redundancy": 1,
                    "series": [
                        {"epoch": "2026-07-21", "cumulative_los_mm": 0.0,
                         "graph_fit_ci95_low_mm": 0.0, "graph_fit_ci95_high_mm": 0.0},
                        {"epoch": "2026-08-02", "cumulative_los_mm": 1.5,
                         "graph_fit_ci95_low_mm": 0.9, "graph_fit_ci95_high_mm": 2.1},
                        {"epoch": "2026-08-14", "cumulative_los_mm": 2.8,
                         "graph_fit_ci95_low_mm": 2.0, "graph_fit_ci95_high_mm": 3.6},
                    ],
                }],
            },
        }
        (root / "aoi-run-summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (root / "aoi-processing-report.json").write_text(json.dumps({"summary": summary, "products": [product], "processing_report": {"status": "PASS"}}), encoding="utf-8")
        (root / "index.html").write_text("<!doctype html><html><body><main>report</main></body></html>", encoding="utf-8")
        return tif, tif_hash

    def test_builds_pair_aware_manifest_layers_and_stac_without_mutating_tiff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tif, before_hash = self._fixture(root)
            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["observations"], 1)
            self.assertEqual(receipt["layers"], 2)
            self.assertEqual(hashlib.sha256(tif.read_bytes()).hexdigest(), before_hash)

            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["validation"]["independent_geophysical_validation"], "NOT_PERFORMED")
            self.assertEqual(manifest["observations"][0]["reference_date"], "2026-07-21")
            self.assertEqual(manifest["validation"]["visual_assets_status"], "PASS")
            self.assertEqual(manifest["observations"][0]["metrics"]["reader_median_units"], "mm")
            self.assertEqual(manifest["site_context"]["place"]["name"], "Test ridge")
            self.assertEqual(manifest["common_reference_timeseries"]["status"],
                             "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED")
            self.assertEqual(len(manifest["common_reference_timeseries"]["components"][0]["series"]), 3)
            self.assertEqual(manifest["goff_common_reference_timeseries"], {})
            self.assertEqual(manifest["observations"][0]["metrics"]["target_local_los_median_mm"], 2.5)
            self.assertEqual(manifest["observations"][0]["metrics"]["target_local_floor_mm_day"], 8.1)
            site_geojson = json.loads((root / "web-dashboard" / "site.geojson").read_text(encoding="utf-8"))
            self.assertEqual(len(site_geojson["features"]), 2)
            self.assertEqual(site_geojson["features"][0]["geometry"]["coordinates"], [90.3864, 24.7518])
            self.assertIn("measurement_target", site_geojson["features"][1]["properties"]["role"])
            los = next(layer for layer in manifest["layers"] if layer["band"] == 1)
            coh = next(layer for layer in manifest["layers"] if layer["band"] == 2)
            self.assertEqual(los["units"], "mm")
            self.assertEqual(coh["display_scale"]["min"], 0.0)
            self.assertEqual(coh["display_scale"]["max"], 1.0)
            corners = los["corners"]
            self.assertEqual(len(corners), 4)
            self.assertTrue(all(-180 <= p[0] <= 180 and -90 <= p[1] <= 90 for p in corners))

            preview = root / "web-dashboard" / los["preview_asset"]
            with Image.open(preview) as image:
                self.assertEqual(image.mode, "RGBA")
                alpha = np.asarray(image)[..., 3]
                self.assertTrue((alpha == 0).any(), "NoData must remain transparent")
                self.assertTrue((alpha > 0).any(), "Valid pixels must render")

            stac_item = json.loads((root / "web-dashboard" / "stac" / "items" / "GUNW-001.json").read_text(encoding="utf-8"))
            self.assertEqual(stac_item["stac_version"], "1.1.0")
            self.assertEqual(stac_item["properties"]["datetime"], "2026-08-14T00:00:00Z")
            collection = json.loads((root / "web-dashboard" / "stac" / "collection.json").read_text(encoding="utf-8"))
            self.assertEqual(collection["license"], "other")
            license_links = [link for link in collection["links"] if link["rel"] == "license"]
            self.assertGreaterEqual(len(license_links), 2)
            self.assertTrue(any("earthdata.nasa.gov" in link["href"] for link in license_links))
            self.assertTrue(any("nisar-docs.asf.alaska.edu" in link["href"] for link in license_links))
            self.assertTrue(collection["providers"])
            self.assertIn("does not relicense source data", collection["sarguardian:license_note"])
            item_path = root / "web-dashboard" / "stac" / "items" / "GUNW-001.json"
            native_href = item_path.parent / stac_item["assets"]["native_raster"]["href"]
            self.assertTrue(native_href.resolve().is_file(), "STAC native asset href must resolve")
            preview_asset = next(v for k, v in stac_item["assets"].items() if k.startswith("preview_band_"))
            self.assertTrue((item_path.parent / preview_asset["href"]).resolve().is_file(), "STAC preview href must resolve")
            self_href = next(link["href"] for link in stac_item["links"] if link["rel"] == "self")
            parent_href = next(link["href"] for link in stac_item["links"] if link["rel"] == "parent")
            self.assertEqual((item_path.parent / self_href).resolve(), item_path.resolve())
            self.assertTrue((item_path.parent / parent_href).resolve().is_file())
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("measurementChart", viewer)
            self.assertIn("measurementTrack", viewer)
            self.assertIn("selected-site-marker", viewer)
            self.assertIn("selected-target-marker", viewer)
            self.assertIn("compare-target-marker", viewer)
            self.assertIn("Target-local GUNW LOS median (mm)", viewer)
            self.assertIn("Target-local detection floor (mm/day)", viewer)
            self.assertIn("function metricUncertainty(p,key)", viewer)
            self.assertIn("target_local_floor_ci_lo_mm_day", viewer)
            self.assertIn("stroke-width','2'", viewer)
            self.assertIn('id="pairCompare"', viewer)
            self.assertIn('id="scenarioSandbox"', viewer)
            self.assertIn("function compatiblePair(a,b)", viewer)
            self.assertIn("function renderCommonReferenceChart()", viewer)
            self.assertIn("function renderGoffCommonReferenceChart()", viewer)
            self.assertIn("manifest.goff_common_reference_timeseries", viewer)
            self.assertIn('id="goffCumulativeChart"', viewer)
            self.assertIn("not a 3-D motion estimate", viewer)
            self.assertIn("manifest.common_reference_timeseries", viewer)
            self.assertIn("DIAGNOSTIC ONLY", viewer)
            self.assertIn("No publishable cumulative diagnostic series", viewer)
            self.assertIn("White bars: fit-only 95% interval", viewer)
            self.assertIn("function renderHypotheticalScenario()", viewer)
            self.assertIn("Comparison withheld", viewer)
            self.assertIn("not a forecast", viewer.lower())
            self.assertIn("bars are not connected", viewer.lower())
            self.assertIn('<script type="module">', viewer)
            self.assertIn("maplibre-gl@6.16.0/dist/maplibre-gl.mjs", viewer)
            self.assertNotIn("dist/maplibre-gl.js", viewer)
            self.assertIn("if(maplibregl && typeof maplibregl.Map==='function')", viewer)
            self.assertNotIn("if(window.maplibregl)", viewer)
            self.assertTrue((root / "web-dashboard" / "dashboard-data.js").is_file())
            if shutil.which("node"):
                module_scripts = re.findall(r'<script type="module">(.*?)</script>', viewer, flags=re.S)
                self.assertEqual(len(module_scripts), 1)
                module_path = root / "viewer-module.mjs"
                module_path.write_text(module_scripts[0], encoding="utf-8")
                syntax = subprocess.run(["node", "--check", str(module_path)], capture_output=True, text=True)
                self.assertEqual(syntax.returncode, 0, syntax.stderr)
            updated_html = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn("web-dashboard/index.html", updated_html)


    def test_goff_common_reference_series_reaches_the_dashboard_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            summary_path = root / "aoi-run-summary.json"
            report_path = root / "aoi-processing-report.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            goff_report = {
                "schema_version": "sarguardian-goff-common-reference-timeseries/1.0",
                "status": "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED",
                "reason": "Synthetic integration fixture; stable-ground reference is unvalidated.",
                "common_reference_is_independently_validated_stable_ground": False,
                "networks": [{
                    "network": "DESC path 048 frame 71 CRID P05023 GOFF PR",
                    "common_pixels_outside_target_buffer": 240,
                }],
                "components": [{
                    "network": "DESC path 048 frame 71 CRID P05023 GOFF PR",
                    "component": "range_offset",
                    "component_index": 1,
                    "status": "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED",
                    "pairs_count": 4,
                    "redundancy": 1,
                    "series": [
                        {"epoch": "2026-07-21", "cumulative_offset_mm": 0.0,
                         "graph_fit_ci95_low_mm": -0.2, "graph_fit_ci95_high_mm": 0.2},
                        {"epoch": "2026-08-02", "cumulative_offset_mm": 1.5,
                         "graph_fit_ci95_low_mm": 0.8, "graph_fit_ci95_high_mm": 2.2},
                        {"epoch": "2026-08-14", "cumulative_offset_mm": 2.8,
                         "graph_fit_ci95_low_mm": 1.9, "graph_fit_ci95_high_mm": 3.7},
                    ],
                }],
            }
            summary["goff_common_reference_timeseries"] = goff_report
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = summary
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads(
                (root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["goff_common_reference_timeseries"]["status"],
                "DIAGNOSTIC_SERIES_AVAILABLE_REFERENCE_UNVALIDATED",
            )
            component = manifest["goff_common_reference_timeseries"]["components"][0]
            self.assertEqual(component["component"], "range_offset")
            self.assertEqual(len(component["series"]), 3)
            self.assertFalse(
                manifest["goff_common_reference_timeseries"][
                    "common_reference_is_independently_validated_stable_ground"
                ]
            )
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("function renderGoffCommonReferenceChart()", viewer)
            self.assertIn("manifest.goff_common_reference_timeseries", viewer)
            self.assertIn("Cumulative GOFF", viewer)
            self.assertIn("not a 3-D motion estimate", viewer)

    def test_target_free_pixel_velocity_raster_is_exposed_as_a_separate_analysis_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product_tif, product_before_hash = self._fixture(root)
            pixel_dir = root / "aoi-relative-pixel-timeseries"
            pixel_dir.mkdir(parents=True)
            pixel_tif = pixel_dir / "gunw-los-velocity-mm-year-test-network.tif"
            with rasterio.open(product_tif) as source:
                profile = source.profile.copy()
            profile.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
            velocity = np.array([
                [-6.0, -4.0, -2.0, 0.0],
                [-3.0, -1.0, 1.0, 3.0],
                [0.0, 2.0, 4.0, 6.0],
                [1.0, 2.0, np.nan, 4.0],
            ], dtype="float32")
            with rasterio.open(pixel_tif, "w", **profile) as destination:
                destination.write(velocity, 1)
                destination.set_band_description(1, "AOI-relative GUNW LOS velocity (mm/year)")
                destination.update_tags(
                    schema_version="sarguardian-aoi-relative-pixel-timeseries/1.0",
                    target_required="false",
                    reference_policy="AOI-derived background; not independently validated stable ground",
                    movement_confirmed="false",
                    hazard_detected="false",
                )
            pixel_sha = hashlib.sha256(pixel_tif.read_bytes()).hexdigest()

            summary_path = root / "aoi-run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["site_context"]["measurement_target"] = {"status": "NOT_PROVIDED"}
            summary["target_measurement_count"] = 0
            summary["local_floor_count"] = 0
            summary["aoi_relative_pixel_timeseries"] = {
                "schema_version": "sarguardian-aoi-relative-pixel-timeseries/1.0",
                "status": "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE",
                "target_required": False,
                "movement_confirmed": False,
                "hazard_detected": False,
                "reference_independently_validated": False,
                "networks_calculated": 1,
                "networks": [{
                    "network": "ASC path 098 frame 016 subswath 023 CRID X05026",
                    "status": "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_REFERENCE_UNVALIDATED",
                    "pair_count": 3,
                    "epoch_count": 3,
                    "redundancy": 1,
                    "common_valid_pixels": 15,
                    "reference_pixels": 14,
                    "artifacts": [{
                        "role": "AOI-relative GUNW LOS velocity",
                        "relative_path": pixel_tif.relative_to(root).as_posix(),
                        "units": "mm/year",
                        "valid_pixels": 15,
                        "sha256": pixel_sha,
                    }],
                }],
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path = root / "aoi-processing-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = summary
            report["products"][0]["target_measurement"] = {"status": "NOT_MEASURED", "measurements": {}}
            report["products"][0]["local_floor"] = {"status": "NOT_MEASURED", "metrics": {}}
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["derived_layers"], 1)
            self.assertEqual(receipt["aoi_relative_pixel_timeseries_status"],
                             "AOI_RELATIVE_GUNW_PIXEL_TIMESERIES_DIAGNOSTIC_AVAILABLE")
            self.assertEqual(receipt["derived_layer_errors"], 0)
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["aoi_relative_pixel_timeseries"]["target_required"])
            self.assertFalse(manifest["aoi_relative_pixel_timeseries"]["reference_independently_validated"])
            self.assertEqual(len(manifest["derived_layers"]), 1)
            layer = manifest["derived_layers"][0]
            self.assertEqual(layer["analysis_role"], "AOI-relative GUNW LOS velocity")
            self.assertEqual(layer["units"], "mm/year")
            self.assertFalse(layer["movement_confirmed"])
            self.assertFalse(layer["hazard_detected"])
            self.assertTrue((root / "web-dashboard" / layer["preview_asset"]).is_file())
            dashboard_data = (root / "web-dashboard" / "dashboard-data.js").read_text(encoding="utf-8")
            self.assertIn("SARGUARDIAN_DERIVED_LAYER_DATA", dashboard_data)
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="derivedLayerSelect"', viewer)
            self.assertIn("function renderDerivedLayer()", viewer)
            self.assertIn("AOI-derived background", viewer)
            self.assertEqual(hashlib.sha256(product_tif.read_bytes()).hexdigest(), product_before_hash)
            self.assertEqual(hashlib.sha256(pixel_tif.read_bytes()).hexdigest(), pixel_sha)

    def test_target_free_candidate_rasters_are_published_as_map_layers_and_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product_tif, product_before_hash = self._fixture(root)
            candidate_dir = root / "aoi-spatial-candidates"
            candidate_dir.mkdir(parents=True)
            with rasterio.open(product_tif) as source:
                profile = source.profile.copy()
            profile.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
            candidate_values = np.array([
                [0.0, 0.0, 1.0, 1.0],
                [0.0, 1.0, 1.0, 0.0],
                [0.0, 0.0, np.nan, 0.0],
                [0.0, 0.0, 0.0, 0.0],
            ], dtype="float32")
            raster_path = candidate_dir / "candidate-mask-fixture.tif"
            with rasterio.open(raster_path, "w", **profile) as dataset:
                dataset.write(candidate_values, 1)
                dataset.set_band_description(1, "AOI spatial candidate mask")
                dataset.update_tags(
                    schema_version="sarguardian-aoi-spatial-candidates-raster/1.0",
                    target_required="false",
                    aoi_wkt_sha256="d" * 64,
                    metric="AOI spatial candidate mask",
                    units="binary candidate flag",
                    movement_confirmed="false",
                    hazard_detected="false",
                )
            raster_sha = hashlib.sha256(raster_path.read_bytes()).hexdigest()
            summary_path = root / "aoi-run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["site_context"]["measurement_target"] = {"status": "NOT_PROVIDED"}
            summary["target_measurement_count"] = 0
            summary["local_floor_count"] = 0
            summary["aoi_displacement_candidates"] = {
                "status": "SINGLE_PAIR_CANDIDATES_NEED_TEMPORAL_CONFIRMATION",
                "target_required": False,
                "movement_confirmed": False,
                "hazard_detected": False,
                "candidate_features": 1,
                "candidate_local_floor_measurements": 1,
                "candidate_local_floor_policy": {
                    "background_ring_pixels": 5,
                    "minimum_background_pixels": 30,
                    "detection_floor": "3 * robust_sigma / acquisition_span_days",
                },
                "features": [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [85.0, 27.0]},
                    "properties": {
                        "product_type": "GUNW",
                        "metric": "GUNW_LOS_DISPLACEMENT_MM",
                        "status": "SINGLE_PAIR_CANDIDATE_UNCONFIRMED",
                        "support_pairs": 1,
                        "pixel_count": 8,
                        "approx_area_m2": 51200,
                        "max_robust_score": 5.2,
                        "candidate_local_floor_by_pair": [{
                            "reference_date": "2026-06-08",
                            "secondary_date": "2026-06-20",
                            "status": "MEASURED_CANDIDATE_REGION_LOCAL_FLOOR",
                            "local_detection_floor_3sigma_mm_day": 0.42,
                        }],
                        "candidate_seasonality_inventory": {
                            "status": "INSUFFICIENT_SEASONAL_COVERAGE",
                            "monsoon_pairs": 1,
                            "dry_season_pairs": 0,
                        },
                        "candidate_phase_ceiling_review": {
                            "status": "WITHIN_SINGLE_FRINGE_REVIEW_THRESHOLD",
                            "threshold_mm": 59.6,
                        },
                        "candidate_cross_geometry_status": "WITHHELD_NO_PIXELWISE_LOOK_VECTOR_AND_RATE_COVARIANCE",
                    },
                }],
                "raster_artifacts": [{
                    "role": "AOI spatial candidate mask",
                    "relative_path": raster_path.relative_to(root).as_posix(),
                    "units": "binary candidate flag",
                    "valid_pixels": int(np.isfinite(candidate_values).sum()),
                    "sha256": raster_sha,
                    "network": "GUNW fixture network",
                }],
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path = root / "aoi-processing-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = summary
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["derived_layers"], 1)
            self.assertEqual(receipt["derived_layer_errors"], 0)
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["validation"]["independent_geophysical_validation"] == "NOT_PERFORMED")
            self.assertTrue(manifest["aoi_displacement_candidates"]["target_required"] is False)
            layer = manifest["derived_layers"][0]
            self.assertEqual(layer["analysis_role"], "AOI spatial candidate mask")
            self.assertEqual(layer["units"], "binary candidate flag")
            self.assertFalse(layer["movement_confirmed"])
            self.assertFalse(layer["hazard_detected"])
            self.assertEqual(layer["source_sha256"], raster_sha)
            self.assertTrue((root / "web-dashboard" / layer["preview_asset"]).is_file())
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Candidate-local 3σ floor", viewer)
            self.assertIn("toFixed(2)+' mm/day'", viewer)
            self.assertIn("'-pixel background ring and at least '", viewer)
            self.assertIn("floorPolicy.background_ring_pixels||5", viewer)
            self.assertIn("floorPolicy.minimum_background_pixels||30", viewer)
            self.assertIn("valid nearby pixels. Same acquisition interval counts once", viewer)
            self.assertIn("not a calibrated false-alarm probability", viewer)
            self.assertIn("Season coverage", viewer)
            self.assertIn("GUNW λ/4 review", viewer)
            self.assertIn("candidate_cross_geometry_status", viewer)
            self.assertEqual(hashlib.sha256(raster_path.read_bytes()).hexdigest(), raster_sha)
            self.assertEqual(hashlib.sha256(product_tif.read_bytes()).hexdigest(), product_before_hash)

    def test_goff_screen_and_robust_inlier_counts_reach_dashboard_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _ = self._fixture(root)
            report_path = root / "aoi-processing-report.json"
            summary_path = root / "aoi-run-summary.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            folder = root / "product-data" / "GOFF-001"
            folder.mkdir(parents=True)
            bounds = transform_bounds("EPSG:4326", "EPSG:32646", 90.38, 24.715, 90.45, 24.78)
            transform = from_bounds(*bounds, 4, 4)
            raster_path = folder / "GOFF_20260721_20260814_PR_HH-layer2.tif"
            range_mm = np.arange(16, dtype="float32").reshape(4, 4) * 10.0
            azimuth_mm = range_mm * 0.5
            correlation = np.full((4, 4), 0.9, dtype="float32")
            inlier_flag = np.ones((4, 4), dtype="float32")
            inlier_flag[0, 0] = 0.0
            inlier_flag[0, 1] = 0.0
            with rasterio.open(
                raster_path, "w", driver="GTiff", width=4, height=4, count=4,
                dtype="float32", crs="EPSG:32646", transform=transform, nodata=np.nan,
            ) as ds:
                for index, values in enumerate((range_mm, azimuth_mm, correlation, inlier_flag), 1):
                    ds.write(values, index)
                ds.set_band_description(1, "slant-range offset (mm)")
                ds.set_band_description(2, "along-track offset (mm)")
                ds.set_band_description(3, "correlation")
                ds.set_band_description(4, "robust inlier flag (1=inlier, 0=global-MAD outlier retained for review)")
                ds.update_tags(
                    aoi_mask_applied="true", grid_policy="common_aoi_lattice",
                    crid="P05023", maturity="PROVISIONAL",
                    correlation_min="0.3", snr_min="3", cull_sigma="4",
                    outliers_preserved_for_screening="true",
                    screen_valid_pixels="16", robust_inlier_pixels="14",
                    robust_outlier_pixels="2",
                )

            source = dict(report["products"][0])
            goff = dict(source)
            goff.update({
                "id": "GOFF-001", "product_type": "GOFF",
                "granule_name": "NISAR_L2_PR_GOFF_006_091_D_074_007_2000_SH_20260721T125813_20260721T125848_20260814T125814_20260814T125849_P05023_N_F_J_001.h5",
                "reference_date": "2026-07-21", "secondary_date": "2026-08-14",
                "metric_name": "range_median_mm", "metric_value": 55.0,
                "valid_pixels": 14, "screen_valid_pixels": 16, "screen_outlier_pixels": 2,
                "stats": {
                    "track": "DESC 091", "range_median_mm": 55.0,
                    "azimuth_median_mm": 27.5, "mean_correlation": 0.9,
                },
                "exports": [{
                    "name": raster_path.name,
                    "relative_path": "product-data/GOFF-001/" + raster_path.name,
                    "quicklook": None,
                }],
                "target_measurement": {"status": "NOT_MEASURED", "measurements": {}},
                "local_floor": {"status": "NOT_MEASURED", "metrics": {}},
            })
            report["products"].append(goff)
            summary.update({
                "products_expected": 2, "products_validated": 2, "products_missing": 0,
                "gunw_count": 1, "goff_count": 1,
            })
            report["summary"] = summary
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            goff_observation = next(item for item in manifest["observations"] if item["id"] == "GOFF-001")
            self.assertEqual(goff_observation["valid_pixels"], 14)
            self.assertEqual(goff_observation["screen_valid_pixels"], 16)
            self.assertEqual(goff_observation["screen_outlier_pixels"], 2)
            layers = [layer for layer in manifest["layers"] if layer["observation_id"] == "GOFF-001"]
            self.assertEqual([layer["band"] for layer in layers], [1, 2, 3, 4])
            flag_layer = layers[-1]
            self.assertEqual(flag_layer["kind"], "binary_mask")
            self.assertEqual(flag_layer["display_scale"]["method"], "discrete_flag_0_outlier_1_inlier")
            self.assertEqual(flag_layer["units"], "binary flag (1=inlier, 0=global-MAD outlier retained for review)")
            self.assertEqual(flag_layer["screen_valid_pixels"], 16)
            self.assertEqual(flag_layer["robust_inlier_pixels"], 14)
            self.assertEqual(flag_layer["screen_outlier_pixels"], 2)
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Measurement-valid pixels", viewer)
            self.assertIn("Screen-valid pixels", viewer)
            self.assertIn("Global-MAD outliers retained for review", viewer)


    def test_aoi_wide_candidate_geojson_reaches_the_interactive_map_manifest(self) -> None:
        """Candidate polygons must survive summary → GeoJSON → manifest → map viewer."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            screen_dir = root / "aoi-wide-displacement-screen"
            screen_dir.mkdir(parents=True)
            candidate = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "id": "candidate-P05023-C001",
                    "properties": {
                        "candidate_id": "GOFF_PR_P05023_A098_F016_BW4000_SH-C001",
                        "series_id": "GOFF_PR_P05023_A098_F016_BW4000_SH",
                        "direction": "ASC",
                        "track": "098",
                        "area_km2_approx": 0.12,
                        "pairs_with_candidate": 5,
                        "status": "CANDIDATE_FOR_REVIEW",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [90.4050, 24.7440], [90.4070, 24.7440],
                            [90.4070, 24.7460], [90.4050, 24.7460],
                            [90.4050, 24.7440],
                        ]],
                    },
                }],
            }
            candidate_path = screen_dir / "candidates.geojson"
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

            summary_path = root / "aoi-run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["aoi_wide_displacement_screen"] = {
                "schema_version": "sarguardian-find-displacements-aoi-screen/1.0",
                "status": "COMPLETED_EXPLORATORY_RANKING",
                "purpose": "FIND_DISPLACEMENTS_AOI_WIDE",
                "target_required": False,
                "target_coordinates_used": False,
                "series_count": 1,
                "candidate_count": 1,
                "candidates_geojson": "aoi-wide-displacement-screen/candidates.geojson",
                "warnings": ["Review candidate only; not a confirmed hazard."],
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path = root / "aoi-processing-report.json"
            processing = json.loads(report_path.read_text(encoding="utf-8"))
            processing["summary"] = summary
            report_path.write_text(json.dumps(processing), encoding="utf-8")

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            screen = manifest["aoi_wide_displacement_screen"]
            self.assertEqual(screen["status"], "COMPLETED_EXPLORATORY_RANKING")
            self.assertFalse(screen["target_required"])
            self.assertFalse(screen["target_coordinates_used"])
            self.assertEqual(screen["candidate_count"], 1)
            self.assertEqual(len(screen["candidate_feature_collection"]["features"]), 1)
            feature = screen["candidate_feature_collection"]["features"][0]
            self.assertEqual(feature["properties"]["candidate_id"], "GOFF_PR_P05023_A098_F016_BW4000_SH-C001")
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("aoi-wide-candidate-fill", viewer)
            self.assertIn("candidate_feature_collection", viewer)
            self.assertIn("not a hazard detection", viewer.lower())
            self.assertIn("GOFF offset-anomaly records", viewer)
            self.assertIn("GUNW pairwise LOS anomaly records", viewer)
            self.assertIn("extended-goff", viewer)
            self.assertIn("extended-gunw", viewer)
            self.assertIn("not probability", viewer.lower())
    def test_candidate_mask_quicklook_keeps_zero_and_nodata_transparent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "candidate-mask.png"
            values = np.array([[0.0, 1.0, np.nan]], dtype="float32")
            count, _, _ = __import__(
                "dashboard.assets.prepare_web_assets", fromlist=["write_rgba"]
            ).write_rgba(values, 0.0, 1.0, "candidate_mask", path)
            self.assertEqual(count, 2)
            rgba = np.asarray(Image.open(path).convert("RGBA"))
            self.assertEqual(rgba[0, 0, 3], 0, "valid zero means no candidate and must be transparent")
            self.assertEqual(rgba[0, 1, 3], 220, "candidate pixel must be visible")
            self.assertEqual(rgba[0, 2, 3], 0, "NoData must remain transparent")

    def test_cross_utm_zones_keep_source_tiffs_and_shared_group_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first_tif, first_hash = self._fixture(root)
            report_path = root / "aoi-processing-report.json"
            summary_path = root / "aoi-run-summary.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            source = report["products"][0]
            folder = root / "product-data" / "GUNW-002"
            folder.mkdir(parents=True)
            bounds = transform_bounds("EPSG:4326", "EPSG:32645", 90.38, 24.715, 90.45, 24.78)
            transform = from_bounds(*bounds, 4, 4)
            second_tif = folder / "fixture-zone45.tif"
            los = np.array([[2, 4, np.nan, -2], [3, 5, 7, 8], [9, 10, 12, 13], [14, 15, 16, 18]], dtype="float32")
            coherence = np.array([[.25, .35, .45, .55], [.65, .75, .85, .95], [.35, .45, .55, .65], [.75, .85, .95, 1.0]], dtype="float32")
            with rasterio.open(second_tif, "w", driver="GTiff", width=4, height=4, count=2,
                               dtype="float32", crs="EPSG:32645", transform=transform, nodata=np.nan) as ds:
                ds.write(los, 1)
                ds.write(coherence, 2)
                ds.set_band_description(1, "LOS displacement (mm)")
                ds.set_band_description(2, "coherence")
            import copy
            second = copy.deepcopy(source)
            second.update({
                "id": "GUNW-002", "reference_date": "2026-08-14", "secondary_date": "2026-09-07",
                "valid_pixels": 15, "metric_value": 8.0,
                "exports": [{"name": second_tif.name, "relative_path": "product-data/GUNW-002/" + second_tif.name, "quicklook": None}],
            })
            report["products"].append(second)
            summary["products_expected"] = 2
            summary["products_validated"] = 2
            summary["products_missing"] = 0
            summary["gunw_count"] = 2
            report["summary"] = summary
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")
            second_hash = hashlib.sha256(second_tif.read_bytes()).hexdigest()

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["observations"], 2)
            self.assertEqual(receipt["layers"], 4)
            self.assertEqual(hashlib.sha256(first_tif.read_bytes()).hexdigest(), first_hash)
            self.assertEqual(hashlib.sha256(second_tif.read_bytes()).hexdigest(), second_hash)
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            first = next(layer for layer in manifest["layers"] if layer["observation_id"] == "GUNW-001" and layer["band"] == 1)
            second_layer = next(layer for layer in manifest["layers"] if layer["observation_id"] == "GUNW-002" and layer["band"] == 1)
            self.assertEqual(first["source_crs"], "EPSG:32646")
            self.assertEqual(second_layer["source_crs"], "EPSG:32645")
            self.assertEqual(first["preview_crs"], "EPSG:4326")
            self.assertEqual(second_layer["preview_crs"], "EPSG:4326")
            self.assertEqual(first["display_scale"], second_layer["display_scale"])

    def test_very_low_aoi_coverage_is_exposed_for_cautious_display(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product_tif, _ = self._fixture(root)
            with rasterio.open(product_tif, "r+") as dataset:
                band = dataset.read(1)
                keep = np.zeros(band.shape, dtype=bool)
                keep.flat[:2] = True
                band[~keep] = np.nan
                dataset.write(band, 1)
            report_path = root / "aoi-processing-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            product = report["products"][0]
            product["valid_pixels"] = 2
            product["metric_value"] = 123.4
            product["stats"].update({"aoi_px": 1000, "aoi_pct": 0.2})
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)

            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            observation = manifest["observations"][0]
            self.assertEqual(observation["valid_pixels"], 2)
            self.assertEqual(observation["aoi_support_pixels"], 1000)
            self.assertAlmostEqual(observation["aoi_coverage_pct"], 0.2)
            self.assertEqual(observation["support_level"], "VERY_LOW_COVERAGE")
            self.assertIn("Not interpreted — only", (root / "web-dashboard" / "index.html").read_text(encoding="utf-8"))
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            if shutil.which("node"):
                metric_start = viewer.index("function metricValue(p,key){")
                metric_end = viewer.index("\nfunction metricUncertainty", metric_start)
                metric_function = viewer[metric_start:metric_end]
                script = metric_function + """
const veryLow = {support_level: "VERY_LOW_COVERAGE", product_type: "GOFF",
  metrics: {goff_range_median_mm: -4851.99, goff_azimuth_median_mm: 84.34}};
const noPixels = {support_level: "NO_USABLE_PIXELS", product_type: "GUNW",
  metrics: {reader_median_units: "mm", reader_median: 29.0}};
const limited = {support_level: "LOW_COVERAGE", product_type: "GUNW",
  metrics: {reader_median_units: "mm", reader_median: 29.883}};
if (metricValue(veryLow, "goff_range_median") !== null) throw new Error("VERY_LOW_RANGE_MEDIAN_VISIBLE");
if (metricValue(veryLow, "goff_azimuth_median") !== null) throw new Error("VERY_LOW_AZIMUTH_MEDIAN_VISIBLE");
if (metricValue(noPixels, "gunw_los_median") !== null) throw new Error("NO_PIXEL_MEDIAN_VISIBLE");
if (metricValue(limited, "gunw_los_median") !== 29.883) throw new Error("LOW_COVERAGE_POLICY_CHANGED");
"""
                checked = subprocess.run(["node", "-e", script], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)


    def test_pixel_stack_sparse_support_is_explained_without_publishing_velocity_rates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            logs = root / "science-diagnostics" / "logs"
            logs.mkdir(parents=True)
            primary_log = """[INFO] 15 all pair(s)
A098  chain 1   2026-06-08 .. 2026-08-31  (6 pairs, 84 d)
  pixels with a complete series : 9 of 216,270 (0.0%)
  largest connected cluster     : 0 px
  measured correlation length   : 0.1 km
  clusters from noise ALONE     : median 7 px, 95th pct 9 px, max 9 px
  VERDICT: NO DETECTION.
D048  chain 2   2026-06-29 .. 2026-09-09  (5 pairs, 72 d)
  pixels with a complete series : 12 of 216,270 (0.0%)
  largest connected cluster     : 0 px
  measured correlation length   : 0.2 km
  clusters from noise ALONE     : median 7 px, 95th pct 9 px, max 9 px
  VERDICT: NO DETECTION.
D149  chain 3   2026-07-06 .. 2026-09-04  (4 pairs, 60 d)
  pixels with a complete series : 0 of 222,656 (0.0%)
  nothing to fit
"""
            retained_log = primary_log.replace("[INFO]", "[INFO]", 1)
            retained_log = "[INFO] 15 all pair(s)\n[WARNING] Common mode kept - atmosphere will dominate every pixel.\n" + primary_log.split("\n", 1)[1]
            (logs / "pixel_stack_common_mode_removed.log").write_text(primary_log, encoding="utf-8")
            (logs / "pixel_stack_common_mode_retained.log").write_text(retained_log, encoding="utf-8")

            summary_path = root / "aoi-run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["science_diagnostics"] = {
                "pixel_stack": {
                    "status": "COMPLETED_NO_DETECTION",
                    "log": "logs/pixel_stack_common_mode_removed.log",
                },
                "common_mode_sensitivity": {
                    "status": "COMPLETED_NO_DETECTION",
                    "log": "logs/pixel_stack_common_mode_retained.log",
                },
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path = root / "aoi-processing-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = summary
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            diagnostic = manifest["pixel_stack_diagnostic"]
            self.assertTrue(diagnostic["available"])
            self.assertEqual(diagnostic["pairs_examined"], 15)
            self.assertEqual(len(diagnostic["chains"]), 3)
            self.assertEqual(diagnostic["chains"][0]["complete_pixels"], 9)
            self.assertAlmostEqual(diagnostic["chains"][0]["complete_support_pct"], 100 * 9 / 216270, places=8)
            self.assertEqual(diagnostic["chains"][1]["largest_cluster_pixels"], 0)
            self.assertEqual(diagnostic["chains"][2]["finding"], "NO_COMPLETE_SERIES")
            self.assertTrue(diagnostic["common_mode_sensitivity"]["same_complete_pixel_support"])
            self.assertTrue(diagnostic["common_mode_sensitivity"]["atmospheric_common_mode_warning"])
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("extremely sparse complete time-series support", diagnostic["interpretation"])
            self.assertIn("renderPixelStackDiagnostic()", viewer)
            self.assertNotIn("29 mm/yr", viewer)
            self.assertNotIn("246 mm/yr", viewer)


    def test_sparse_spatial_null_is_reported_as_not_testable_not_no_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            logs = root / "science-diagnostics" / "logs"
            logs.mkdir(parents=True)
            primary_log = """[INFO] 15 all pair(s)
A098  chain 1   2026-06-08 .. 2026-08-31  (6 pairs, 84 d)
  pixels with a complete series : 9 of 216,270 (0.0%)
  largest connected cluster     : 0 px
  measured correlation length   : NOT ESTIMABLE
  valid complete pixels          : 9 (requires at least 30 pixels and neighbouring pairs)
  noise-only cluster test        : WITHHELD
  VERDICT: NOT TESTABLE. Too few valid neighbouring pixels to estimate spatial noise.
D048  chain 2   2026-06-29 .. 2026-09-09  (5 pairs, 72 d)
  pixels with a complete series : 12 of 216,270 (0.0%)
  largest connected cluster     : 0 px
  measured correlation length   : NOT ESTIMABLE
  valid complete pixels          : 12 (requires at least 30 pixels and neighbouring pairs)
  noise-only cluster test        : WITHHELD
  VERDICT: NOT TESTABLE. Too few valid neighbouring pixels to estimate spatial noise.
D149  chain 3   2026-07-06 .. 2026-09-04  (4 pairs, 60 d)
  pixels with a complete series : 0 of 222,656 (0.0%)
  nothing to fit
  VERDICT: NOT TESTABLE. No complete pixel time series is available.
"""
            retained_log = "[WARNING] Common mode kept - atmosphere will dominate every pixel.\n" + primary_log
            (logs / "pixel_stack_retained_artifact_reaudit_removed.log").write_text(primary_log, encoding="utf-8")
            (logs / "pixel_stack_retained_artifact_reaudit_retained.log").write_text(retained_log, encoding="utf-8")

            summary_path = root / "aoi-run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["science_diagnostics"] = {
                "pixel_stack": {
                    "status": "WITHHELD_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT",
                    "log": "logs/pixel_stack_retained_artifact_reaudit_removed.log",
                },
                "common_mode_sensitivity": {
                    "status": "WITHHELD_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT",
                    "log": "logs/pixel_stack_retained_artifact_reaudit_retained.log",
                },
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path = root / "aoi-processing-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = summary
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            diagnostic = manifest["pixel_stack_diagnostic"]
            self.assertEqual(diagnostic["status"], "WITHHELD_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT")
            self.assertEqual(diagnostic["chains"][0]["finding"], "NOT_TESTABLE_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT")
            self.assertEqual(diagnostic["chains"][1]["finding"], "NOT_TESTABLE_INSUFFICIENT_SPATIAL_NEIGHBOR_SUPPORT")
            self.assertEqual(diagnostic["chains"][2]["finding"], "NO_COMPLETE_SERIES")
            self.assertIn("This result is NOT TESTABLE, not a no-detection result", diagnostic["interpretation"])
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Not testable — too few nearby valid pixels to measure background noise", viewer)
            self.assertIn("noise comparison was withheld", viewer)


    def test_no_compatible_repeated_gunw_network_is_not_testable_not_no_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            logs = root / "science-diagnostics" / "logs"
            logs.mkdir(parents=True)
            primary = """[INFO] 15 all pair(s)
PIXEL_STACK_PAIRS_EXAMINED=15
PIXEL_STACK_EXACT_NETWORKS=15
PIXEL_STACK_CONTIGUOUS_RUNS=15
PIXEL_STACK_NETWORKS_WITH_2_PLUS_PAIRS=0
PIXEL_STACK_STATUS=WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK
VERDICT: NOT TESTABLE. No two consecutive pair intervals share the same complete GUNW network identity (look/path, frame, subswath, bandwidth, polarization, CRID). Joining the pairs would mix unlike LOS networks.
"""
            retained = """[INFO] 15 all pair(s)
[WARNING] Common mode kept - atmosphere will dominate every pixel.
PIXEL_STACK_PAIRS_EXAMINED=15
PIXEL_STACK_EXACT_NETWORKS=15
PIXEL_STACK_CONTIGUOUS_RUNS=15
PIXEL_STACK_NETWORKS_WITH_2_PLUS_PAIRS=0
PIXEL_STACK_STATUS=WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK
VERDICT: NOT TESTABLE. No two consecutive pair intervals share the same complete GUNW network identity (look/path, frame, subswath, bandwidth, polarization, CRID). Joining the pairs would mix unlike LOS networks.
"""
            (logs / "pixel_stack_retained_artifact_reaudit_removed.log").write_text(primary, encoding="utf-8")
            (logs / "pixel_stack_retained_artifact_reaudit_retained.log").write_text(retained, encoding="utf-8")

            summary_path = root / "aoi-run-summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["aoi_wide_displacement_screen"] = {
                "status": "COMPLETED_EXPLORATORY_RANKING",
                "gunw_per_pixel_stack": {
                    "status": "COMPLETED_NO_DETECTION",
                    "interpretation": "Legacy stack status from a broad, non-network-specific run.",
                },
            }
            summary["science_diagnostics"] = {
                "pixel_stack": {
                    "status": "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK",
                    "log": "logs/pixel_stack_retained_artifact_reaudit_removed.log",
                    "science_commit": "006d4cd1485cf80e509eaf8717c12e9c6390ac09",
                },
                "common_mode_sensitivity": {
                    "status": "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK",
                    "log": "logs/pixel_stack_retained_artifact_reaudit_retained.log",
                    "science_commit": "006d4cd1485cf80e509eaf8717c12e9c6390ac09",
                },
            }
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report_path = root / "aoi-processing-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["summary"] = summary
            report_path.write_text(json.dumps(report), encoding="utf-8")

            receipt = prepare_web_dashboard(root)
            self.assertEqual(receipt["status"], "PASS")
            manifest = json.loads((root / "web-dashboard" / "manifest.json").read_text(encoding="utf-8"))
            diagnostic = manifest["pixel_stack_diagnostic"]
            self.assertFalse(diagnostic["available"])
            self.assertEqual(diagnostic["status"], "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK")
            self.assertEqual(diagnostic["pairs_examined"], 15)
            self.assertEqual(diagnostic["exact_networks"], 15)
            self.assertEqual(diagnostic["networks_with_2_plus_pairs"], 0)
            self.assertEqual(
                manifest["aoi_wide_displacement_screen"]["gunw_per_pixel_stack"]["status"],
                "WITHHELD_NO_COMPATIBLE_REPEATED_NETWORK",
            )
            self.assertEqual(
                manifest["aoi_wide_displacement_screen"]["gunw_per_pixel_stack"]["legacy_reported_status"],
                "COMPLETED_NO_DETECTION",
            )
            self.assertTrue(
                manifest["aoi_wide_displacement_screen"]["gunw_per_pixel_stack"]["legacy_status_superseded"]
            )
            self.assertEqual(diagnostic["chains"], [])
            self.assertIn("NOT TESTABLE, not NO DETECTION", diagnostic["interpretation"])
            self.assertIn("different measurement networks", diagnostic["interpretation"])
            viewer = (root / "web-dashboard" / "index.html").read_text(encoding="utf-8")
            self.assertIn("No compatible multi-date GUNW network", viewer)
            self.assertIn("NOT TESTABLE, not NO DETECTION", viewer)


    def test_viewer_has_functional_audience_views_and_presentation_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            viewer_path = Path(temporary) / "index.html"
            write_viewer(viewer_path)
            viewer = viewer_path.read_text(encoding="utf-8")

        for mode in ("public", "evidence", "science"):
            self.assertIn(f'data-sg-mode="{mode}"', viewer)
        self.assertIn('aria-selected="true"', viewer)
        self.assertIn("function setSgDashboardMode(mode)", viewer)
        self.assertIn("body[data-dashboard-mode=public] .science-only", viewer)
        self.assertNotIn("body[data-dashboard-mode=public] .evidence-panel{display:none}", viewer)
        self.assertIn("public-candidate-results", viewer)
        self.assertIn("publicCandidateResults", viewer)
        self.assertIn("function renderPublicCandidateCards(family=activeFamily)", viewer)
        self.assertIn("No compatible multi-date GUNW network", viewer)
        self.assertIn("Pair records in screen:", viewer)
        self.assertNotIn("Compatible pair intervals:", viewer)
        self.assertIn("runPlainConclusion", viewer)
        self.assertIn("What did the satellite data show?", viewer)
        self.assertIn("public-explainer-grid", viewer)
        self.assertIn("GUNW · Measurement", viewer)
        self.assertIn("GOFF · Image pattern", viewer)
        self.assertIn("Candidate · Review lead", viewer)
        self.assertIn("GUNW pattern records", viewer)
        self.assertIn("GOFF offset review regions", viewer)
        self.assertIn("The whole-area scan found", viewer)
        self.assertIn("No area crossed the configured candidate-screening thresholds", viewer)
        self.assertIn("activeFamily='GUNW'", viewer)
        self.assertIn("function hasRenderableFamily(family)", viewer)
        self.assertIn("function firstRenderableIndex(family)", viewer)
        self.assertIn("@media(max-width:760px){.public-explainer-grid{grid-template-columns:1fr}", viewer)
        self.assertIn("@media(max-width:430px){.public-family-switch", viewer)
        self.assertIn("Locate on map", viewer)
        self.assertIn('data-public-family="GUNW"', viewer)
        self.assertIn('data-public-family="GOFF"', viewer)
        self.assertIn('id="publicTimeline"', viewer)
        self.assertIn('id="publicPlay"', viewer)
        self.assertIn("function familyIndices(family=activeFamily)", viewer)
        self.assertIn("function setFamily(family)", viewer)
        self.assertIn("timer=setInterval(()=>select((familyPosition()+1)%familyIndices().length)", viewer)
        self.assertIn("body[data-dashboard-mode=public] .advanced-controls", viewer)
        self.assertNotIn(".advanced-controls{display:flex}", viewer)
        self.assertIn("function renderPublicLegend(l)", viewer)
        self.assertNotIn("timer=setInterval(()=>select((selected+1)%n)", viewer)

        if shutil.which("node"):
            family_start = viewer.index("function familyIndices(family=activeFamily)")
            family_end = viewer.index("function familyPosition()", family_start)
            family_helper = viewer[family_start:family_end]
            playback_logic = family_helper + """
const obs = [
  {product_type: "GOFF", secondary_date: "2026-07-19", id: "GOFF-2"},
  {product_type: "GUNW", secondary_date: "2026-08-14", id: "GUNW-2"},
  {product_type: "GOFF", secondary_date: "2026-07-07", id: "GOFF-1"},
  {product_type: "GUNW", secondary_date: "2026-07-19", id: "GUNW-1"}
];
let activeFamily = "GUNW";
let selected = familyIndices()[0];
function familyPosition() {
  const indices = familyIndices();
  const position = indices.indexOf(selected);
  return position >= 0 ? position : 0;
}
function select(position) {
  const indices = familyIndices();
  selected = indices[(position + indices.length) % indices.length];
}
if (familyIndices().map(i => obs[i].id).join(",") !== "GUNW-1,GUNW-2") {
  throw new Error("GUNW_SEQUENCE_MIXED_OR_NOT_DATE_SORTED");
}
select((familyPosition() + 1) % familyIndices().length);
if (obs[selected].id !== "GUNW-2") throw new Error("GUNW_NEXT_ESCAPED_FAMILY");
activeFamily = "GOFF";
selected = familyIndices()[0];
if (familyIndices().map(i => obs[i].id).join(",") !== "GOFF-1,GOFF-2") {
  throw new Error("GOFF_SEQUENCE_MIXED_OR_NOT_DATE_SORTED");
}
select((familyPosition() + 1) % familyIndices().length);
if (obs[selected].id !== "GOFF-2") throw new Error("GOFF_NEXT_ESCAPED_FAMILY");
"""
            family_check = subprocess.run(["node", "-e", playback_logic], capture_output=True, text=True)
            self.assertEqual(family_check.returncode, 0, family_check.stderr)

            helper_start = viewer.index("function familyIndices(family=activeFamily)")
            helper_end = viewer.index("function syncFamilyControls()", helper_start)
            family_helpers = viewer[helper_start:helper_end]
            renderable_script = """
const obs = [
  {product_type: "GOFF", secondary_date: "2026-07-07", id: "GOFF-1"},
  {product_type: "GUNW", secondary_date: "2026-07-19", id: "GUNW-1"},
  {product_type: "GUNW", secondary_date: "2026-08-14", id: "GUNW-2"}
];
const layers = [{observation_id: "GOFF-1"}, {observation_id: "GUNW-2"}];
let activeFamily = "GUNW";
""" + family_helpers + """
if (!hasRenderableFamily("GUNW")) throw new Error("RENDERABLE_GUNW_NOT_FOUND");
if (firstRenderableIndex("GUNW") !== 2) throw new Error("FIRST_RENDERABLE_GUNW_NOT_SELECTED");
if (!hasRenderableFamily("GOFF")) throw new Error("GOFF_FALLBACK_NOT_FOUND");
"""
            renderable_check = subprocess.run(["node", "-e", renderable_script], capture_output=True, text=True)
            self.assertEqual(renderable_check.returncode, 0, renderable_check.stderr)
        self.assertIn("body[data-dashboard-mode=evidence] .science-only", viewer)
        self.assertIn("presentation-active", viewer)
        self.assertIn("if(!document.fullscreenElement)document.body.classList.remove('presentation-active')", viewer)
        self.assertIn('id="map"', viewer)
        self.assertIn('id="timeline"', viewer)
        self.assertIn('id="aoiCandidateList"', viewer)
        self.assertIn('id="pixelTimeseriesSummary"', viewer)
        self.assertIn('id="scienceStages"', viewer)
        self.assertIn('id="provenance"', viewer)


if __name__ == "__main__":
    unittest.main()
