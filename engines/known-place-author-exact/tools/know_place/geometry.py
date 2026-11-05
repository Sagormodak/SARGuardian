"""Explicit polygon handling for Know Place Analysis, independent of reader AOIs."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable

import numpy as np

from .goff_io import GoffReadError


@dataclass(frozen=True)
class AnalysisROI:
    row_slice: slice
    col_slice: slice
    x_coordinates_m: np.ndarray
    y_coordinates_m: np.ndarray
    box_mask: np.ndarray
    crown_mask: np.ndarray
    box_ring_projected: tuple[tuple[float, float], ...]
    crown_ring_projected: tuple[tuple[float, float], ...]
    # Present for the generic two-polygon workflow. None preserves the historic
    # encompassing-box/crown semantics used by the paper-specific path.
    reference_mask: np.ndarray | None = None
    reference_ring_projected: tuple[tuple[float, float], ...] | None = None


def parse_polygon_wkt(wkt: str, *, max_vertices: int = 500) -> list[tuple[float, float]]:
    """Parse one closed WGS84 exterior ring; holes and multipolygons are rejected."""
    if not isinstance(wkt, str) or not wkt.strip():
        raise GoffReadError("AOI_WKT_EMPTY")
    match = re.fullmatch(r"(?is)\s*POLYGON\s*\(\s*\((.*?)\)\s*\)\s*", wkt.strip())
    if not match:
        raise GoffReadError("AOI_WKT_MUST_BE_SINGLE_RING_POLYGON_NO_HOLES")
    body = match.group(1).strip()
    if re.search(r"\)\s*,\s*\(", body):
        raise GoffReadError("AOI_WKT_MUST_BE_SINGLE_RING_POLYGON_NO_HOLES")
    chunks = body.split(",")
    if len(chunks) > max_vertices:
        raise GoffReadError(f"AOI_WKT_TOO_MANY_VERTICES_MAX_{max_vertices}")
    ring: list[tuple[float, float]] = []
    for chunk in chunks:
        fields = chunk.split()
        if len(fields) != 2:
            raise GoffReadError("AOI_WKT_COORDINATES_MUST_BE_LON_LAT_PAIRS")
        try:
            lon, lat = float(fields[0]), float(fields[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise GoffReadError("AOI_WKT_COORDINATE_NOT_NUMERIC") from exc
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise GoffReadError("AOI_WKT_COORDINATE_NONFINITE")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise GoffReadError("AOI_WKT_COORDINATE_OUTSIDE_WGS84")
        point = (lon, lat)
        if ring and point == ring[-1]:
            raise GoffReadError("AOI_WKT_DUPLICATE_CONSECUTIVE_VERTEX")
        ring.append(point)
    if len(set(ring)) < 3:
        raise GoffReadError("AOI_WKT_NEEDS_THREE_DISTINCT_VERTICES")
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    if len(set(ring[:-1])) < 3:
        raise GoffReadError("AOI_WKT_NEEDS_THREE_DISTINCT_VERTICES")

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, p):
        return (
            min(a[0], b[0]) - 1e-12 <= p[0] <= max(a[0], b[0]) + 1e-12
            and min(a[1], b[1]) - 1e-12 <= p[1] <= max(a[1], b[1]) + 1e-12
        )

    edges = list(zip(ring[:-1], ring[1:]))
    for i, (a, b) in enumerate(edges):
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            c, d = edges[j]
            values = (orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b))
            proper_cross = (
                ((values[0] > 1e-12 and values[1] < -1e-12)
                 or (values[0] < -1e-12 and values[1] > 1e-12))
                and ((values[2] > 1e-12 and values[3] < -1e-12)
                     or (values[2] < -1e-12 and values[3] > 1e-12))
            )
            touches = (
                (abs(values[0]) <= 1e-12 and on_segment(a, b, c))
                or (abs(values[1]) <= 1e-12 and on_segment(a, b, d))
                or (abs(values[2]) <= 1e-12 and on_segment(c, d, a))
                or (abs(values[3]) <= 1e-12 and on_segment(c, d, b))
            )
            if proper_cross or touches:
                raise GoffReadError("AOI_WKT_SELF_INTERSECTING")
    twice_area = sum(
        ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        for i in range(len(ring) - 1)
    )
    if not math.isfinite(twice_area) or abs(twice_area) < 1e-12:
        raise GoffReadError("AOI_WKT_ZERO_AREA")
    return ring


def project_wkt_ring(wkt: str, epsg: int) -> tuple[tuple[float, float], ...]:
    ring = parse_polygon_wkt(wkt)
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise GoffReadError("PYPROJ_REQUIRED_FOR_AOI_PROJECTION") from exc
    if epsg <= 0:
        raise GoffReadError(f"AOI_TARGET_EPSG_INVALID:{epsg}")
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    projected = tuple((float(x), float(y)) for x, y in zip(
        *transformer.transform([p[0] for p in ring], [p[1] for p in ring])
    ))
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in projected):
        raise GoffReadError("AOI_PROJECTION_NONFINITE")
    return projected


def points_in_ring(x_grid: np.ndarray, y_grid: np.ndarray, ring: Iterable[tuple[float, float]]) -> np.ndarray:
    """Vectorized even-odd point-in-polygon test on grid-cell centres."""
    x = np.asarray(x_grid, dtype=float)
    y = np.asarray(y_grid, dtype=float)
    if x.shape != y.shape:
        raise GoffReadError("AOI_GRID_COORDINATE_SHAPE_MISMATCH")
    vertices = list(ring)
    inside = np.zeros(x.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(vertices[:-1], vertices[1:]):
        crosses = (y1 > y) != (y2 > y)
        denominator = y2 - y1
        if denominator == 0:
            continue
        x_intersection = (x2 - x1) * (y - y1) / denominator + x1
        inside ^= crosses & (x < x_intersection)
    return inside


def build_analysis_roi(
    x_coordinates_m: np.ndarray,
    y_coordinates_m: np.ndarray,
    epsg: int,
    *,
    box_wkt: str,
    crown_wkt: str,
    coherence_halo_cells: int = 2,
) -> AnalysisROI:
    """Rasterize box/crown on a window padded for full 5x5 coherence support.

    The returned read window includes a two-cell halo by default. Pixels in
    that halo can contribute to neighbourhood R for centres inside the box,
    but only pixels selected by box_mask contribute to box/crown summaries.
    This prevents treating the edge of the requested reference box as an image
    boundary when calculating a moving-window statistic.
    """
    if not isinstance(coherence_halo_cells, int) or coherence_halo_cells < 2:
        raise GoffReadError("COHERENCE_CONTEXT_HALO_MUST_BE_AT_LEAST_TWO_CELLS")
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1:
        raise GoffReadError("GOFF_XY_COORDINATES_MUST_BE_1D")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise GoffReadError("GOFF_XY_COORDINATES_NONFINITE")
    if len(x) < 2 or len(y) < 2:
        raise GoffReadError("GOFF_GRID_TOO_SMALL")
    if not (np.all(np.diff(x) > 0) or np.all(np.diff(x) < 0)):
        raise GoffReadError("GOFF_X_COORDINATES_NOT_MONOTONIC")
    if not (np.all(np.diff(y) > 0) or np.all(np.diff(y) < 0)):
        raise GoffReadError("GOFF_Y_COORDINATES_NOT_MONOTONIC")
    box = project_wkt_ring(box_wkt, epsg)
    crown = project_wkt_ring(crown_wkt, epsg)
    xmin, xmax = min(p[0] for p in box), max(p[0] for p in box)
    ymin, ymax = min(p[1] for p in box), max(p[1] for p in box)
    x_hits = np.flatnonzero((x >= xmin) & (x <= xmax))
    y_hits = np.flatnonzero((y >= ymin) & (y <= ymax))
    if not x_hits.size or not y_hits.size:
        raise GoffReadError("REFERENCE_BOX_DOES_NOT_INTERSECT_GOFF_GRID")
    box_row0, box_row1 = int(y_hits.min()), int(y_hits.max()) + 1
    box_col0, box_col1 = int(x_hits.min()), int(x_hits.max()) + 1
    # Include enough off-box neighbours to compute a centred 5x5 R on every
    # reference-box pixel that has adequate valid support.
    row0 = max(0, box_row0 - coherence_halo_cells)
    row1 = min(len(y), box_row1 + coherence_halo_cells)
    col0 = max(0, box_col0 - coherence_halo_cells)
    col1 = min(len(x), box_col1 + coherence_halo_cells)
    if (box_row0 - row0 < coherence_halo_cells
            or row1 - box_row1 < coherence_halo_cells
            or box_col0 - col0 < coherence_halo_cells
            or col1 - box_col1 < coherence_halo_cells):
        raise GoffReadError("GOFF_GRID_TOO_SMALL_FOR_FULL_COHERENCE_HALO")
    roi_x, roi_y = x[col0:col1], y[row0:row1]
    xx, yy = np.meshgrid(roi_x, roi_y)
    box_mask = points_in_ring(xx, yy, box)
    crown_mask = points_in_ring(xx, yy, crown)
    if not box_mask.any():
        raise GoffReadError("REFERENCE_BOX_HAS_NO_GRID_CELL_CENTRES")
    if not crown_mask.any():
        raise GoffReadError("CROWN_HAS_NO_GRID_CELL_CENTRES")
    if np.any(crown_mask & ~box_mask):
        raise GoffReadError("CROWN_GRID_CELLS_FALL_OUTSIDE_REFERENCE_BOX")
    # Ensure no crown polygon vertex lies outside the reference-box polygon.
    vertex_x = np.asarray([p[0] for p in crown], dtype=float)
    vertex_y = np.asarray([p[1] for p in crown], dtype=float)
    if not points_in_ring(vertex_x[:-1], vertex_y[:-1], box).all():
        raise GoffReadError("CROWN_POLYGON_NOT_CONTAINED_IN_REFERENCE_BOX")
    return AnalysisROI(
        row_slice=slice(row0, row1),
        col_slice=slice(col0, col1),
        x_coordinates_m=roi_x,
        y_coordinates_m=roi_y,
        box_mask=box_mask,
        crown_mask=crown_mask,
        box_ring_projected=box,
        crown_ring_projected=crown,
    )

def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(
    a: tuple[float, float], b: tuple[float, float],
    c: tuple[float, float], d: tuple[float, float],
    *, tolerance_m: float = 1e-7,
) -> bool:
    """Return true for crossing, collinear overlap, or touching polygon edges."""
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    # Orientations have squared-metre units; scale the tolerance by the longest
    # edge so the geometric tolerance remains expressed in metres.
    edge_scale = max(
        math.hypot(b[0] - a[0], b[1] - a[1]),
        math.hypot(d[0] - c[0], d[1] - c[1]),
        1.0,
    )
    orientation_tolerance = tolerance_m * edge_scale

    def on_segment(p, q, r) -> bool:
        return (
            min(p[0], r[0]) - tolerance_m <= q[0] <= max(p[0], r[0]) + tolerance_m
            and min(p[1], r[1]) - tolerance_m <= q[1] <= max(p[1], r[1]) + tolerance_m
        )

    if ((o1 > orientation_tolerance and o2 < -orientation_tolerance) or (o1 < -orientation_tolerance and o2 > orientation_tolerance)) and (
        (o3 > orientation_tolerance and o4 < -orientation_tolerance) or (o3 < -orientation_tolerance and o4 > orientation_tolerance)
    ):
        return True
    return (
        (abs(o1) <= orientation_tolerance and on_segment(a, c, b))
        or (abs(o2) <= orientation_tolerance and on_segment(a, d, b))
        or (abs(o3) <= orientation_tolerance and on_segment(c, a, d))
        or (abs(o4) <= orientation_tolerance and on_segment(c, b, d))
    )


def _rings_overlap_or_touch(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> bool:
    """Detect polygon containment, crossing, and boundary contact in projected metres."""
    first_x = np.asarray([[point[0] for point in first[:-1]]], dtype=float)
    first_y = np.asarray([[point[1] for point in first[:-1]]], dtype=float)
    second_x = np.asarray([[point[0] for point in second[:-1]]], dtype=float)
    second_y = np.asarray([[point[1] for point in second[:-1]]], dtype=float)
    if points_in_ring(first_x, first_y, second).any() or points_in_ring(second_x, second_y, first).any():
        return True
    return any(
        _segments_intersect(a, b, c, d)
        for a, b in zip(first[:-1], first[1:])
        for c, d in zip(second[:-1], second[1:])
    )


def polygon_pair_envelope_wkt(first_wkt: str, second_wkt: str, epsg: int) -> str:
    """Return a WGS84 rectangle covering two independent polygons in a projected CRS."""
    first = project_wkt_ring(first_wkt, epsg)
    second = project_wkt_ring(second_wkt, epsg)
    points = (*first, *second)
    xmin = min(point[0] for point in points)
    xmax = max(point[0] for point in points)
    ymin = min(point[1] for point in points)
    ymax = max(point[1] for point in points)
    if not (xmin < xmax and ymin < ymax):
        raise GoffReadError("MEASUREMENT_REFERENCE_ENVELOPE_INVALID")
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise GoffReadError("PYPROJ_REQUIRED_FOR_AOI_PROJECTION") from exc
    reverse = Transformer.from_crs(f"EPSG:{int(epsg)}", "EPSG:4326", always_xy=True)
    lon, lat = reverse.transform(
        [xmin, xmax, xmax, xmin, xmin],
        [ymin, ymin, ymax, ymax, ymin],
    )
    if not all(math.isfinite(float(x)) and math.isfinite(float(y)) for x, y in zip(lon, lat)):
        raise GoffReadError("MEASUREMENT_REFERENCE_ENVELOPE_NONFINITE")
    return "POLYGON ((" + ", ".join(
        f"{float(x):.9f} {float(y):.9f}" for x, y in zip(lon, lat)
    ) + "))"


def build_independent_reference_roi(
    x_coordinates_m: np.ndarray,
    y_coordinates_m: np.ndarray,
    epsg: int,
    *,
    measurement_wkt: str,
    reference_wkt: str,
    scope_wkt: str | None = None,
    coherence_halo_cells: int = 2,
) -> AnalysisROI:
    """Rasterize disjoint measurement and reference polygons on one native GOFF grid.

    Unlike build_analysis_roi (the historic paper box/crown contract), the
    reference polygon is an independent background region. It must neither
    contain nor overlap/touch the measurement polygon. Both masks are retained
    explicitly; the legacy box_mask is their union for existing correction and
    control kernels, so box_mask & ~crown_mask is exactly the reference mask.
    """
    if not isinstance(coherence_halo_cells, int) or coherence_halo_cells < 2:
        raise GoffReadError("COHERENCE_CONTEXT_HALO_MUST_BE_AT_LEAST_TWO_CELLS")
    x = np.asarray(x_coordinates_m, dtype=float)
    y = np.asarray(y_coordinates_m, dtype=float)
    if x.ndim != 1 or y.ndim != 1:
        raise GoffReadError("GOFF_XY_COORDINATES_MUST_BE_1D")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise GoffReadError("GOFF_XY_COORDINATES_NONFINITE")
    if len(x) < 2 or len(y) < 2:
        raise GoffReadError("GOFF_GRID_TOO_SMALL")
    if not (np.all(np.diff(x) > 0) or np.all(np.diff(x) < 0)):
        raise GoffReadError("GOFF_X_COORDINATES_NOT_MONOTONIC")
    if not (np.all(np.diff(y) > 0) or np.all(np.diff(y) < 0)):
        raise GoffReadError("GOFF_Y_COORDINATES_NOT_MONOTONIC")

    measurement = project_wkt_ring(measurement_wkt, epsg)
    reference = project_wkt_ring(reference_wkt, epsg)
    if _rings_overlap_or_touch(measurement, reference):
        raise GoffReadError("MEASUREMENT_REFERENCE_POLYGONS_OVERLAP_OR_TOUCH")
    if scope_wkt:
        scope = project_wkt_ring(scope_wkt, epsg)
        for label, ring in (("MEASUREMENT", measurement), ("REFERENCE", reference)):
            vertex_x = np.asarray([point[0] for point in ring[:-1]], dtype=float)
            vertex_y = np.asarray([point[1] for point in ring[:-1]], dtype=float)
            if not points_in_ring(vertex_x, vertex_y, scope).all():
                raise GoffReadError(f"{label}_POLYGON_OUTSIDE_OUTER_AOI")
            if any(
                _segments_intersect(a, b, c, d)
                for a, b in zip(ring[:-1], ring[1:])
                for c, d in zip(scope[:-1], scope[1:])
            ):
                raise GoffReadError(f"{label}_POLYGON_CROSSES_OR_TOUCHES_OUTER_AOI")

    vertices = (*measurement, *reference)
    xmin, xmax = min(p[0] for p in vertices), max(p[0] for p in vertices)
    ymin, ymax = min(p[1] for p in vertices), max(p[1] for p in vertices)
    x_hits = np.flatnonzero((x >= xmin) & (x <= xmax))
    y_hits = np.flatnonzero((y >= ymin) & (y <= ymax))
    if not x_hits.size or not y_hits.size:
        raise GoffReadError("MEASUREMENT_REFERENCE_POLYGONS_DO_NOT_INTERSECT_GOFF_GRID")
    row_start, row_stop = int(y_hits.min()), int(y_hits.max()) + 1
    col_start, col_stop = int(x_hits.min()), int(x_hits.max()) + 1
    row0 = max(0, row_start - coherence_halo_cells)
    row1 = min(len(y), row_stop + coherence_halo_cells)
    col0 = max(0, col_start - coherence_halo_cells)
    col1 = min(len(x), col_stop + coherence_halo_cells)
    if (
        row_start - row0 < coherence_halo_cells
        or row1 - row_stop < coherence_halo_cells
        or col_start - col0 < coherence_halo_cells
        or col1 - col_stop < coherence_halo_cells
    ):
        raise GoffReadError("GOFF_GRID_TOO_SMALL_FOR_FULL_COHERENCE_HALO")

    roi_x, roi_y = x[col0:col1], y[row0:row1]
    xx, yy = np.meshgrid(roi_x, roi_y)
    measurement_mask = points_in_ring(xx, yy, measurement)
    reference_mask = points_in_ring(xx, yy, reference)
    if not measurement_mask.any():
        raise GoffReadError("MEASUREMENT_POLYGON_HAS_NO_GRID_CELL_CENTRES")
    if not reference_mask.any():
        raise GoffReadError("REFERENCE_POLYGON_HAS_NO_GRID_CELL_CENTRES")
    if np.any(measurement_mask & reference_mask):
        raise GoffReadError("MEASUREMENT_REFERENCE_RASTER_MASKS_OVERLAP")

    envelope = (
        (xmin, ymin), (xmax, ymin), (xmax, ymax),
        (xmin, ymax), (xmin, ymin),
    )
    return AnalysisROI(
        row_slice=slice(row0, row1),
        col_slice=slice(col0, col1),
        x_coordinates_m=roi_x,
        y_coordinates_m=roi_y,
        box_mask=measurement_mask | reference_mask,
        crown_mask=measurement_mask,
        box_ring_projected=envelope,
        crown_ring_projected=measurement,
        reference_mask=reference_mask,
        reference_ring_projected=reference,
    )

