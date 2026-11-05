"""Transparent independent reconstruction of the Bhote Koshi displacement null.

The supplied archive contains aggregate displacement-null results but omits their
generator and draw-level values. This module reconstructs the described size-
matched-region test from exported displacement fields. It is NOT claimed to be
exact author-code parity.

Policy v1 explicitly assumes raster-index disks, a 60% valid-cell acceptance
threshold, 1,200 centre candidates per pair, and a NumPy PCG64 stream seeded at
20261025 and shared across pairs chronologically. The source paper says only
"compact regions" and does not disclose the displacement sampler's exact shape,
seed/PRNG, sampling order, or rejection rule in the supplied code archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = "method-derived-displacement-null/1.0"
POLICY_VERSION = "method-derived-displacement-null-v1"
DEFAULT_SEED = 20261025
DEFAULT_CANDIDATE_CENTRES = 1200
DEFAULT_MIN_VALID_FRACTION = 0.60
CROWN_BOUNDS_LONLAT = (85.5245, 28.2847, 85.5400, 28.2970)
WIDE_BOUNDS_LONLAT = (85.500, 28.265, 85.565, 28.318)
PAIR_FIELD_FILES = (
    ("20260620->20260702", "offsets_20260620_20260702.tif"),
    ("20260702->20260714", "offsets_20260702_20260714.tif"),
    ("20260714->20260726", "offsets_20260714_20260726.tif"),
    ("20260726->20260819", "offsets_20260726_20260819.tif"),
    ("20260819->20260831", "offsets_20260819_20260831.tif"),
)
PUBLISHED_SUMMARY = (
    {"pair": "20260620->20260702", "crown_m": 0.99, "null_median_m": 0.17, "percentile": 94.9},
    {"pair": "20260702->20260714", "crown_m": 0.54, "null_median_m": 0.21, "percentile": 87.5},
    {"pair": "20260714->20260726", "crown_m": 0.30, "null_median_m": 0.14, "percentile": 81.0},
    {"pair": "20260726->20260819", "crown_m": 0.96, "null_median_m": 0.14, "percentile": 94.7},
    {"pair": "20260819->20260831", "crown_m": 0.33, "null_median_m": 0.09, "percentile": 81.3},
)


class DisplacementNullError(ValueError):
    """Invalid inputs or insufficient support for the null calculation."""


def _mask(value: Any, shape: tuple[int, int], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=bool)
    if result.ndim != 2 or result.shape != shape:
        raise DisplacementNullError(f"DISPLACEMENT_NULL_{name.upper()}_SHAPE_MISMATCH")
    return result


def _disk(shape: tuple[int, int], row: int, col: int, radius: float) -> np.ndarray:
    rows, cols = np.ogrid[:shape[0], :shape[1]]
    return (rows - row) ** 2 + (cols - col) ** 2 <= radius * radius


def _region_mask(shape: tuple[int, int], row: int, col: int, target_n: int, region_shape: str) -> np.ndarray:
    """Build an explicit compact region with approximately target_n cells of area."""
    if region_shape == "disk":
        return _disk(shape, row, col, math.sqrt(target_n / math.pi))
    if region_shape == "square":
        side = max(1, int(round(math.sqrt(target_n))))
        r0, c0 = row - side // 2, col - side // 2
        r1, c1 = r0 + side, c0 + side
        result = np.zeros(shape, dtype=bool)
        rr0, cc0 = max(0, r0), max(0, c0)
        rr1, cc1 = min(shape[0], r1), min(shape[1], c1)
        if rr0 < rr1 and cc0 < cc1:
            result[rr0:rr1, cc0:cc1] = True
        return result
    if region_shape == "diamond":
        rows, cols = np.ogrid[:shape[0], :shape[1]]
        radius = math.sqrt(target_n / 2.0)
        return np.abs(rows - row) + np.abs(cols - col) <= radius
    raise DisplacementNullError("DISPLACEMENT_NULL_REGION_SHAPE_INVALID")


def displacement_null_for_pair(
    east_m: Any,
    north_m: Any,
    crown_mask: Any,
    analysis_mask: Any,
    rng: np.random.Generator,
    *,
    candidate_centres: int = DEFAULT_CANDIDATE_CENTRES,
    minimum_valid_fraction: float = DEFAULT_MIN_VALID_FRACTION,
    region_shape: str = "disk",
    pair: str = "unspecified",
    include_draws: bool = True,
) -> dict[str, Any]:
    """Calculate null medians from finite east/north fields and same-grid masks.

    The caller supplies/reuses the RNG so the series-level stream and draw order
    are explicit and deterministic. Every attempted centre is retained in the
    diagnostics, including rejected placements and their reason.
    """
    east, north = np.asarray(east_m, float), np.asarray(north_m, float)
    if east.ndim != 2 or north.shape != east.shape:
        raise DisplacementNullError("DISPLACEMENT_NULL_OFFSET_SHAPE_MISMATCH")
    if not isinstance(rng, np.random.Generator):
        raise DisplacementNullError("DISPLACEMENT_NULL_RNG_TYPE_INVALID")
    if isinstance(candidate_centres, bool) or not isinstance(candidate_centres, int) or candidate_centres < 1:
        raise DisplacementNullError("DISPLACEMENT_NULL_CANDIDATE_CENTRES_INVALID")
    if not math.isfinite(float(minimum_valid_fraction)) or not 0 < float(minimum_valid_fraction) <= 1:
        raise DisplacementNullError("DISPLACEMENT_NULL_VALID_FRACTION_INVALID")
    if region_shape not in {"disk", "square", "diamond"}:
        raise DisplacementNullError("DISPLACEMENT_NULL_REGION_SHAPE_INVALID")

    crown = _mask(crown_mask, east.shape, "crown")
    analysis = _mask(analysis_mask, east.shape, "analysis")
    valid = analysis & np.isfinite(east) & np.isfinite(north)
    magnitude = np.hypot(east, north)
    valid &= np.isfinite(magnitude)
    crown_valid = crown & valid
    target_n = int(crown_valid.sum())
    if target_n == 0:
        raise DisplacementNullError("DISPLACEMENT_NULL_NO_VALID_CROWN_PIXELS")
    observed = float(np.median(magnitude[crown_valid]))
    ys, xs = np.nonzero(valid)
    if not ys.size:
        raise DisplacementNullError("DISPLACEMENT_NULL_NO_VALID_CENTRE_CANDIDATES")

    selected = rng.choice(ys.size, size=min(candidate_centres, int(ys.size)), replace=False)
    required_n = int(math.ceil(minimum_valid_fraction * target_n))
    accepted_values: list[float] = []
    diagnostics: list[dict[str, Any]] = []
    for draw_index, selected_index in enumerate(selected):
        row, col = int(ys[int(selected_index)]), int(xs[int(selected_index)])
        sample_mask = _region_mask(east.shape, row, col, target_n, region_shape) & valid
        valid_n = int(sample_mask.sum())
        if valid_n < required_n:
            diagnostics.append({
                "draw_index": draw_index, "centre_row": row, "centre_col": col,
                "valid_cells": valid_n, "minimum_valid_cells": required_n,
                "accepted": False, "rejection_reason": "insufficient_valid_pixels_in_region",
                "median_displacement_m": None,
            })
            continue
        value = float(np.median(magnitude[sample_mask]))
        accepted_values.append(value)
        diagnostics.append({
            "draw_index": draw_index, "centre_row": row, "centre_col": col,
            "valid_cells": valid_n, "minimum_valid_cells": required_n,
            "accepted": True, "rejection_reason": None, "median_displacement_m": value,
        })

    if not accepted_values:
        raise DisplacementNullError("DISPLACEMENT_NULL_NO_ACCEPTED_DRAWS")
    values = np.asarray(accepted_values, dtype=float)
    result: dict[str, Any] = {
        "pair": pair,
        "status": "COMPUTED_INDEPENDENT_METHOD_DERIVED",
        "policy_version": POLICY_VERSION,
        "estimand": "median horizontal displacement magnitude in compact size-matched regions",
        "observed_crown_valid_pixels": target_n,
        "observed_crown_median_displacement_m": observed,
        "candidate_centres_examined": int(len(selected)),
        "accepted_draws": int(values.size),
        "rejected_draws": int(len(selected) - values.size),
        "minimum_valid_fraction": float(minimum_valid_fraction),
        "minimum_valid_cells_per_region": required_n,
        "region_shape": region_shape,
        "region_area_policy": "disk area ~= n; square side=round(sqrt(n)); diamond L1 radius=sqrt(n/2)",
        "centre_population": "finite east/north displacement cells inside analysis mask",
        "centre_sampling": "uniform without replacement from valid cell centres",
        "rank_definition": "100 * mean(null draw median < observed crown median); ties count as not below",
        "null_median_displacement_m": float(np.median(values)),
        "null_p05_displacement_m": float(np.percentile(values, 5)),
        "null_p95_displacement_m": float(np.percentile(values, 95)),
        "observed_crown_percentile": float(np.mean(values < observed) * 100.0),
        "null_draw_median_values_m": [float(value) for value in values],
    }
    if include_draws:
        result["draw_diagnostics"] = diagnostics
    return result


def masks_from_north_up_grid(
    shape: tuple[int, int],
    transform: Any,
    *,
    crown_bounds_lonlat: tuple[float, float, float, float] = CROWN_BOUNDS_LONLAT,
    analysis_bounds_lonlat: tuple[float, float, float, float] = WIDE_BOUNDS_LONLAT,
) -> tuple[np.ndarray, np.ndarray]:
    """Build inclusive bounding-box masks using processed grid-cell centres.

    This is a geographic bounding-box window, not the exact author crown vector.
    Source-grid pixel-mask parity is a separate unresolved acceptance gate.
    """
    if len(shape) != 2 or min(shape) < 1:
        raise DisplacementNullError("DISPLACEMENT_NULL_GRID_SHAPE_INVALID")
    for bounds in (crown_bounds_lonlat, analysis_bounds_lonlat):
        if len(bounds) != 4 or not bounds[0] < bounds[2] or not bounds[1] < bounds[3]:
            raise DisplacementNullError("DISPLACEMENT_NULL_BOUNDS_INVALID")
    rows, cols = np.indices(shape, dtype=float)
    cols += 0.5
    rows += 0.5
    lon = transform.c + transform.a * cols + transform.b * rows
    lat = transform.f + transform.d * cols + transform.e * rows

    def inside(bounds: tuple[float, float, float, float]) -> np.ndarray:
        x0, y0, x1, y1 = bounds
        return (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1)

    crown, analysis = inside(crown_bounds_lonlat), inside(analysis_bounds_lonlat)
    if not crown.any():
        raise DisplacementNullError("DISPLACEMENT_NULL_CROWN_MASK_EMPTY")
    if not analysis.any():
        raise DisplacementNullError("DISPLACEMENT_NULL_ANALYSIS_MASK_EMPTY")
    return crown, analysis


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_archive_fields(
    fields_dir: str | Path,
    output_path: str | Path,
    *,
    seed: int = DEFAULT_SEED,
    candidate_centres: int = DEFAULT_CANDIDATE_CENTRES,
    minimum_valid_fraction: float = DEFAULT_MIN_VALID_FRACTION,
    region_shape: str = "disk",
) -> dict[str, Any]:
    """Run on the five processed-field GeoTIFFs; never downloads or opens HDF5."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover
        raise DisplacementNullError("DISPLACEMENT_NULL_RASTERIO_REQUIRED") from exc
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise DisplacementNullError("DISPLACEMENT_NULL_SEED_INVALID")

    fields_dir, output = Path(fields_dir), Path(output_path)
    rng = np.random.default_rng(seed)
    pair_results, manifests = [], []
    common_grid = None
    for pair, filename in PAIR_FIELD_FILES:
        path = fields_dir / filename
        if not path.is_file():
            raise DisplacementNullError(f"DISPLACEMENT_NULL_FIELD_MISSING:{filename}")
        with rasterio.open(path) as dataset:
            if dataset.count < 2:
                raise DisplacementNullError(f"DISPLACEMENT_NULL_FIELD_BANDS_MISSING:{filename}")
            if dataset.crs is None or dataset.crs.to_string() != "EPSG:4326":
                raise DisplacementNullError(f"DISPLACEMENT_NULL_FIELD_CRS_UNSUPPORTED:{filename}")
            grid = (dataset.height, dataset.width, dataset.crs.to_string(), tuple(dataset.transform))
            if common_grid is None:
                common_grid = grid
            elif grid[:3] != common_grid[:3] or not np.allclose(
                np.asarray(grid[3]), np.asarray(common_grid[3]), rtol=0, atol=1e-12
            ):
                raise DisplacementNullError(f"DISPLACEMENT_NULL_FIELD_GRID_MISMATCH:{filename}")
            east = dataset.read(1, masked=True).filled(np.nan).astype(float)
            north = dataset.read(2, masked=True).filled(np.nan).astype(float)
            crown_mask, analysis_mask = masks_from_north_up_grid((dataset.height, dataset.width), dataset.transform)
            transform, crs = tuple(dataset.transform), dataset.crs.to_string()

        pair_result = displacement_null_for_pair(
            east, north, crown_mask, analysis_mask, rng,
            candidate_centres=candidate_centres,
            minimum_valid_fraction=minimum_valid_fraction,
            region_shape=region_shape,
            pair=pair,
            include_draws=True,
        )
        published = next(item for item in PUBLISHED_SUMMARY if item["pair"] == pair)
        comparison = {
            "published_summary_source": "Zenodo tables/displacement_null.json; aggregate only",
            "published_crown_m_2dp": published["crown_m"],
            "computed_crown_m_2dp": round(pair_result["observed_crown_median_displacement_m"], 2),
            "crown_median_matches_2dp": round(pair_result["observed_crown_median_displacement_m"], 2) == published["crown_m"],
            "published_null_median_m": published["null_median_m"],
            "computed_null_median_m": pair_result["null_median_displacement_m"],
            "null_median_difference_m": pair_result["null_median_displacement_m"] - published["null_median_m"],
            "published_percentile": published["percentile"],
            "computed_percentile": pair_result["observed_crown_percentile"],
            "percentile_difference_points": pair_result["observed_crown_percentile"] - published["percentile"],
            "exact_author_sampler_parity": "UNVERIFIABLE_AUTHOR_GENERATOR_NOT_IN_SUPPLIED_ARCHIVE",
        }
        pair_result["published_aggregate_comparison"] = comparison
        pair_results.append(pair_result)
        manifests.append({
            "pair": pair, "filename": filename, "sha256": _sha256(path), "bytes": path.stat().st_size,
            "bands_used": {"east_m": 1, "north_m": 2}, "crs": crs, "grid_transform": list(transform),
        })

    output_doc = {
        "schema_version": SCHEMA_VERSION,
        "overall_status": "INDEPENDENT_METHOD_DERIVED_NOT_AUTHOR_SAMPLER_PARITY",
        "author_draw_generator_available_in_archive": False,
        "source_archive_component": "processed offset-field GeoTIFFs, bands 1-2; raw GOFF HDF5 not read",
        "source_archive_reference": "Bhote Koshi 2026 NISAR L2 GOFF site-series archive, Zenodo DOI 10.5281/zenodo.22730419",
        "policy": {
            "version": POLICY_VERSION, "seed": seed, "prng": "numpy.default_rng / PCG64",
            "single_rng_stream_shared_across_pairs_in_chronological_order": True,
            "candidate_centres_per_pair_max": candidate_centres,
            "candidate_centres_sampled_without_replacement": True,
            "minimum_valid_fraction": minimum_valid_fraction,
            "region_shape": region_shape,
            "region_area_policy": "disk area ~= n; square side=round(sqrt(n)); diamond L1 radius=sqrt(n/2)",
            "geometry": "inclusive WGS84 bounding-box masks tested against processed-grid cell centres",
            "rank_ties": "ties do not count as below the observed crown statistic",
            "unrecovered_author_choices": [
                "exact compact-region shape and pixel-count construction",
                "seed, PRNG and random draw order",
                "displacement-null acceptance threshold and valid-ground definition",
                "draw-level source values and per-draw acceptance trail",
            ],
        },
        "input_fields": manifests,
        "pairs": pair_results,
        "summary": [{
            "pair": item["pair"],
            "observed_crown_valid_pixels": item["observed_crown_valid_pixels"],
            "observed_crown_median_displacement_m": item["observed_crown_median_displacement_m"],
            "accepted_draws": item["accepted_draws"], "rejected_draws": item["rejected_draws"],
            "null_median_displacement_m": item["null_median_displacement_m"],
            "observed_crown_percentile": item["observed_crown_percentile"],
            "published_null_median_m": item["published_aggregate_comparison"]["published_null_median_m"],
            "published_percentile": item["published_aggregate_comparison"]["published_percentile"],
        } for item in pair_results],
        "interpretation_limit": (
            "This deterministic run exposes its assumptions and all attempted draws. Aggregate "
            "similarity/disagreement does not establish author-sampler parity or hazard-detection skill."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(output_doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    output_doc["output_path"] = str(output)
    output_doc["output_sha256"] = _sha256(output)
    return output_doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fields-dir", required=True, help="Directory with the five offsets_*.tif processed fields")
    parser.add_argument("--output", required=True, help="Output JSON path; contains every draw and rejection")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--candidate-centres", type=int, default=DEFAULT_CANDIDATE_CENTRES)
    parser.add_argument("--minimum-valid-fraction", type=float, default=DEFAULT_MIN_VALID_FRACTION)
    parser.add_argument("--region-shape", choices=("disk", "square", "diamond"), default="disk")
    args = parser.parse_args()
    result = run_archive_fields(
        args.fields_dir, args.output, seed=args.seed,
        candidate_centres=args.candidate_centres,
        minimum_valid_fraction=args.minimum_valid_fraction,
        region_shape=args.region_shape,
    )
    print("DISPLACEMENT_NULL_STATUS=" + result["overall_status"])
    print("PAIR_COUNT=" + str(len(result["pairs"])))
    for row in result["summary"]:
        print(
            "PAIR={} CROWN_N={} ACCEPTED={}/{} NULL_MEDIAN_M={:.3f} PERCENTILE={:.1f} PUBLISHED={:.1f}".format(
                row["pair"], row["observed_crown_valid_pixels"], row["accepted_draws"],
                row["accepted_draws"] + row["rejected_draws"], row["null_median_displacement_m"],
                row["observed_crown_percentile"], row["published_percentile"],
            )
        )
    print("RAW_HDF5_READ=0")
    print("REPORT_SHA256=" + result["output_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
