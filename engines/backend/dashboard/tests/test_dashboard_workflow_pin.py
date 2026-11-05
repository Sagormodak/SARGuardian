from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "sarguardian-aoi-wkt-dashboard.yml"
AGGREGATOR = ROOT / "tools" / "aggregate_aoi_run.py"
BUILDER = ROOT / "dashboard" / "assets" / "prepare_web_assets.py"
EXPECTED_SCIENCE_SHA = "006d4cd1485cf80e509eaf8717c12e9c6390ac09"


class DashboardWorkflowPinTests(unittest.TestCase):
    def test_workflow_uses_the_dispatched_immutable_revision_for_aggregator_and_viewer(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("repository: moshiour0/SARGuardian-backend", workflow)
        self.assertIn("ref: ${{ needs.manifest.outputs.orchestration_sha }}", workflow)
        self.assertIn("path: dashboard-source", workflow)
        self.assertIn("EXPECTED_DASHBOARD_SHA: ${{ needs.manifest.outputs.orchestration_sha }}", workflow)
        self.assertIn('test "$actual" = "${EXPECTED_DASHBOARD_SHA:?}"', workflow)
        self.assertNotIn("ecd125f68ed61c276406f73a1d77eb27979e204e", workflow)

    def test_workflow_pins_exact_guarded_science_revision(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        worker = (ROOT / ".github" / "workflows" / "sarguardian-aoi-product-worker.yml").read_text(encoding="utf-8")
        code_validation = (ROOT / ".github" / "workflows" / "sarguardian-aoi-code-validation.yml").read_text(encoding="utf-8")
        discovery = (ROOT / "tools" / "discover_aoi_products.py").read_text(encoding="utf-8")
        self.assertEqual(workflow.count(EXPECTED_SCIENCE_SHA), 2)
        self.assertEqual(worker.count(EXPECTED_SCIENCE_SHA), 2)
        self.assertEqual(code_validation.count(EXPECTED_SCIENCE_SHA), 1)
        self.assertIn(f'SCIENCE_COMMIT = "{EXPECTED_SCIENCE_SHA}"', discovery)

    def test_pinned_source_contract_has_interactive_asset_builder(self) -> None:
        aggregator = AGGREGATOR.read_text(encoding="utf-8")
        builder = BUILDER.read_text(encoding="utf-8")
        worker = (ROOT / ".github" / "workflows" / "sarguardian-aoi-product-worker.yml").read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("prepare_web_dashboard", aggregator)
        self.assertIn('web-dashboard/manifest.json', builder)
        self.assertIn('web-dashboard/index.html', builder)
        self.assertIn("target_latitude:", workflow)
        self.assertIn("TARGET_LATITUDE: ${{ inputs.target_latitude }}", worker)
        self.assertIn("measure_target_from_raster.py", worker)
        self.assertIn('--aoi-wkt "$SARGUARDIAN_AOI_WKT"', worker)
        self.assertIn("--minimum-valid-pixels 6", worker)
        self.assertIn("science-source/src/local_floor.py", worker)
        self.assertIn('find "$CURATED_DIR/derived" -type f -print | sort', worker)
        self.assertIn("LOCAL_FLOOR_STATUS=", worker)
        self.assertIn("TARGET_MEASUREMENT_STATUS=", worker)
        self.assertIn('SITE_PLACE_NAME: ${{ inputs.place_name }}', workflow)
        self.assertIn('SITE_TARGET_LATITUDE: ${{ inputs.target_latitude }}', workflow)
        self.assertIn('place_name:', workflow)
        self.assertIn('target_longitude:', workflow)
        self.assertIn("def build_site_context(ring:", aggregator)
        self.assertIn('"site_context": summary.get("site_context") or {}', builder)
        self.assertIn("def collect_target_evidence(artifact:", aggregator)


if __name__ == "__main__":
    unittest.main()
