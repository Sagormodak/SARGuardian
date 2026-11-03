from datetime import date

import pytest
from shapely.geometry import Polygon, mapping

from process_gcov_job import WorkerFailure, select_covering_granules, select_date_window


def test_selected_observations_use_a_real_event_window_and_never_interpolate():
    rows = [
        {"acquisition_date": value, "passes_coverage_gate": True, "granule_names": [f"scene-{index}"]}
        for index, value in enumerate(("2026-04-01", "2026-04-10", "2026-04-20", "2026-05-01", "2026-05-15", "2026-05-31"))
    ]

    selected, event_window = select_date_window(rows, date(2026, 5, 2))

    assert selected == [row["acquisition_date"] for row in rows]
    assert event_window == {
        "before": "2026-04-20",
        "event_observation": "2026-05-01",
        "post_one": "2026-05-15",
        "post_two": "2026-05-31",
    }


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
