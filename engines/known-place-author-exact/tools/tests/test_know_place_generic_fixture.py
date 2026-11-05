from __future__ import annotations

import json
from pathlib import Path


def test_generic_aoi_browser_report_is_obviously_synthetic_and_non_hazardous():
    path = Path(__file__).parent / "fixtures" / "generic_aoi_map_report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["fixture_only"] is True
    assert "not NISAR observations" in report["fixture_note"]
    assert report["measurement_status"] == "SYNTHETIC_FIXTURE_ONLY"
    assert report["paper_reproduction_status"] == "NOT_EVALUATED_GENERIC_AOI"
    assert report["hazard_detection_status"] == "NOT_EVALUATED"
    assert len(report["pairs"]) == 1
    pair = report["pairs"][0]
    assert pair["release_id"] == "SYNTHETIC_FIXTURE_ONLY"
    assert pair["status"] == "SYNTHETIC_FIXTURE_ONLY"
    assert pair["source_sha256"] == "a" * 64
    assert "geotiff_file" not in pair
    assert pair["valid_aoi_pixels"] == 8 and pair["aoi_total_grid_cells"] == 10
