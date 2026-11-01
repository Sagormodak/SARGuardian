from __future__ import annotations

import numpy as np
import pytest
from pyproj import Transformer

from tools.know_place.goff_io import GoffReadError
from tools.know_place.geometry import (
    build_analysis_roi,
    build_independent_reference_roi,
    parse_polygon_wkt,
    points_in_ring,
    polygon_pair_envelope_wkt,
)


BOX_WKT = (
    "POLYGON ((85.500000 28.265000, 85.565000 28.265000, "
    "85.565000 28.318000, 85.500000 28.318000, 85.500000 28.265000))"
)
# Exact published bounds; keep the regression fixture aligned with source-grid audit.
CROWN_WKT = (
    "POLYGON ((85.524500 28.284700, 85.540000 28.284700, "
    "85.540000 28.297000, 85.524500 28.297000, 85.524500 28.284700))"
)


def test_wkt_parser_closes_ring_and_preserves_lon_lat_order():
    ring = parse_polygon_wkt("POLYGON ((85.5 28.2, 85.6 28.2, 85.6 28.3, 85.5 28.3))")
    assert ring[0] == ring[-1]
    assert ring[0] == (85.5, 28.2)
    assert len(ring) == 5


def test_wkt_parser_rejects_holes_and_self_intersections():
    with pytest.raises(GoffReadError, match="SINGLE_RING"):
        parse_polygon_wkt(
            "POLYGON ((85 28, 86 28, 86 29, 85 29, 85 28), "
            "(85.2 28.2, 85.3 28.2, 85.3 28.3, 85.2 28.3, 85.2 28.2))"
        )
    with pytest.raises(GoffReadError, match="SELF_INTERSECTING"):
        parse_polygon_wkt(
            "POLYGON ((85 28, 86 29, 85 29, 86 28, 85 28))"
        )


def test_point_in_ring_uses_grid_cell_centres():
    ring = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0))
    x = np.array([[2.0, 12.0], [3.0, 4.0]])
    y = np.array([[3.0, 3.0], [11.0, 4.0]])
    assert points_in_ring(x, y, ring).tolist() == [[True, False], [False, True]]


def test_build_roi_crops_to_reference_box_and_rasterizes_crown():
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    ring = parse_polygon_wkt(BOX_WKT)
    px, py = transformer.transform([p[0] for p in ring], [p[1] for p in ring])
    xs = np.arange(np.floor((min(px) - 500.0) / 80) * 80, np.ceil((max(px) + 500.0) / 80) * 80 + 1, 80.0)
    ys = np.arange(np.floor((min(py) - 500.0) / 80) * 80, np.ceil((max(py) + 500.0) / 80) * 80 + 1, 80.0)
    roi = build_analysis_roi(xs, ys, 32645, box_wkt=BOX_WKT, crown_wkt=CROWN_WKT)
    assert roi.box_mask.any()
    assert roi.crown_mask.any()
    assert not np.any(roi.crown_mask & ~roi.box_mask)
    assert roi.box_mask.shape == (len(roi.y_coordinates_m), len(roi.x_coordinates_m))
    assert roi.crown_mask.sum() < roi.box_mask.sum()
    assert len(roi.crown_ring_projected) == 5
    # The processing window contains the full two-cell halo required by 5x5 R.
    assert not roi.box_mask[0, :].any()
    assert not roi.box_mask[-1, :].any()
    assert not roi.box_mask[:, 0].any()
    assert not roi.box_mask[:, -1].any()


def test_build_roi_rejects_crown_outside_reference_box():
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    ring = parse_polygon_wkt(BOX_WKT)
    px, py = transformer.transform([p[0] for p in ring], [p[1] for p in ring])
    xs = np.arange(np.floor((min(px) - 500.0) / 80) * 80, np.ceil((max(px) + 500.0) / 80) * 80 + 1, 80.0)
    ys = np.arange(np.floor((min(py) - 500.0) / 80) * 80, np.ceil((max(py) + 500.0) / 80) * 80 + 1, 80.0)
    outside = (
        "POLYGON ((85.560 28.290, 85.570 28.290, 85.570 28.300, "
        "85.560 28.300, 85.560 28.290))"
    )
    with pytest.raises(GoffReadError):
        build_analysis_roi(xs, ys, 32645, box_wkt=BOX_WKT, crown_wkt=outside)

MEASUREMENT_WKT = CROWN_WKT
REFERENCE_WKT = (
    "POLYGON ((85.500000 28.284700, 85.515000 28.284700, "
    "85.515000 28.297000, 85.500000 28.297000, 85.500000 28.284700))"
)


def _two_polygon_grid(measurement_wkt: str, reference_wkt: str):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    points = parse_polygon_wkt(measurement_wkt) + parse_polygon_wkt(reference_wkt)
    px, py = transformer.transform(
        [point[0] for point in points],
        [point[1] for point in points],
    )
    xs = np.arange(
        np.floor((min(px) - 500.0) / 80) * 80,
        np.ceil((max(px) + 500.0) / 80) * 80 + 1,
        80.0,
    )
    ys = np.arange(
        np.floor((min(py) - 500.0) / 80) * 80,
        np.ceil((max(py) + 500.0) / 80) * 80 + 1,
        80.0,
    )
    return xs, ys


def test_independent_measurement_and_reference_polygons_are_rasterized_separately():
    xs, ys = _two_polygon_grid(MEASUREMENT_WKT, REFERENCE_WKT)
    roi = build_independent_reference_roi(
        xs, ys, 32645,
        measurement_wkt=MEASUREMENT_WKT,
        reference_wkt=REFERENCE_WKT,
    )

    assert roi.reference_mask is not None
    assert roi.crown_mask.any()
    assert roi.reference_mask.any()
    assert not np.any(roi.crown_mask & roi.reference_mask)
    assert np.array_equal(roi.box_mask, roi.crown_mask | roi.reference_mask)
    assert roi.reference_ring_projected is not None
    assert len(roi.reference_ring_projected) == 5
    assert not roi.box_mask[0, :].any()
    assert not roi.box_mask[-1, :].any()
    assert not roi.box_mask[:, 0].any()
    assert not roi.box_mask[:, -1].any()

    envelope = polygon_pair_envelope_wkt(MEASUREMENT_WKT, REFERENCE_WKT, 32645)
    assert envelope.startswith("POLYGON ((")


@pytest.mark.parametrize(
    "reference_wkt",
    [
        # Partial overlap.
        "POLYGON ((85.535 28.290, 85.550 28.290, 85.550 28.310, 85.535 28.310, 85.535 28.290))",
        # Contains the measurement polygon.
        BOX_WKT,
        # Touches the measurement polygon along its eastern edge.
        "POLYGON ((85.540000 28.284700, 85.550000 28.284700, 85.550000 28.297000, 85.540000 28.297000, 85.540000 28.284700))",
    ],
)
def test_independent_reference_polygon_rejects_overlap_containment_and_touch(reference_wkt):
    xs, ys = _two_polygon_grid(MEASUREMENT_WKT, reference_wkt)
    with pytest.raises(GoffReadError, match="OVERLAP_OR_TOUCH"):
        build_independent_reference_roi(
            xs, ys, 32645,
            measurement_wkt=MEASUREMENT_WKT,
            reference_wkt=reference_wkt,
        )

