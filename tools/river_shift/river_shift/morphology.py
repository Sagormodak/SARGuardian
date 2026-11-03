from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import date
import math

import numpy as np
from scipy import ndimage

from .raster_io import (
    assert_same_grid,
    power_to_db,
    read_band,
    require_projected_metre_grid,
    safe_float,
    save_json,
    write_mask,
    write_mask_geojson,
    sha256_file,
    validate_gcov_series,
    gcov_source_provenance,
)
from .water_detection import classify_open_water, otsu_threshold_db


def _boundary(mask: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
    """Return water-class boundary pixels away from invalid-data edges."""
    values = np.asarray(mask, dtype=bool)
    support = np.ones(values.shape, dtype=bool) if valid is None else np.asarray(valid, dtype=bool)
    if support.shape != values.shape:
        raise ValueError("Boundary mask and valid-pixel support must have identical shapes.")
    # A shoreline is measurable only where its full 8-neighbourhood is observed.
    # This avoids turning NoData holes or the raster edge into artificial banks.
    support_interior = ndimage.binary_erosion(
        support, structure=np.ones((3, 3), dtype=bool), border_value=0,
    )
    observed_water = values & support
    edge = observed_water ^ ndimage.binary_erosion(
        observed_water, structure=np.ones((3, 3), dtype=bool), border_value=0,
    )
    return edge & support_interior


def _orthogonal_pixel_sizes(transform: Any) -> tuple[float, float]:
    """Return row/column pixel-vector lengths; EDT cannot represent affine shear."""
    column_vector = (float(transform.a), float(transform.d))
    row_vector = (float(transform.b), float(transform.e))
    column_size = math.hypot(*column_vector)
    row_size = math.hypot(*row_vector)
    dot = column_vector[0] * row_vector[0] + column_vector[1] * row_vector[1]
    scale = max(column_size * row_size, 1.0)
    if (
        not np.isfinite(column_size)
        or not np.isfinite(row_size)
        or column_size <= 0
        or row_size <= 0
        or abs(dot) > scale * 1e-8
    ):
        raise ValueError(
            "Boundary-distance analysis requires an orthogonal projected raster grid; "
            "reproject the observations to a north-up or rotated orthogonal grid."
        )
    return row_size, column_size


def symmetric_boundary_distance_m(
    before_water: np.ndarray,
    after_water: np.ndarray,
    *,
    pixel_size_y_m: float,
    pixel_size_x_m: float,
    valid_mask: np.ndarray | None = None,
) -> tuple[float | None, float | None]:
    """Return symmetric boundary distance within shared observed support only.

    This is a boundary-change screening proxy, not a signed transect-based bank
    retreat/accretion rate. Complex braided channels may have multiple nearby banks.
    Boundaries within one pixel of NoData or image edges are omitted.
    """
    before_values = np.asarray(before_water, dtype=bool)
    after_values = np.asarray(after_water, dtype=bool)
    if before_values.shape != after_values.shape:
        raise ValueError("Before and after water masks must have identical shapes.")
    support = np.ones(before_values.shape, dtype=bool) if valid_mask is None else np.asarray(valid_mask, dtype=bool)
    if support.shape != before_values.shape:
        raise ValueError("Water masks and valid-pixel support must have identical shapes.")
    if (
        not np.isfinite(pixel_size_y_m) or pixel_size_y_m <= 0
        or not np.isfinite(pixel_size_x_m) or pixel_size_x_m <= 0
    ):
        raise ValueError("Pixel-vector lengths must be finite positive metres.")

    before_edge = _boundary(before_values, support)
    after_edge = _boundary(after_values, support)
    if not before_edge.any() or not after_edge.any():
        return None, None

    distance_to_after = ndimage.distance_transform_edt(
        ~after_edge, sampling=(pixel_size_y_m, pixel_size_x_m)
    )
    distance_to_before = ndimage.distance_transform_edt(
        ~before_edge, sampling=(pixel_size_y_m, pixel_size_x_m)
    )
    distances = np.concatenate(
        [distance_to_after[before_edge], distance_to_before[after_edge]]
    )
    distances = distances[np.isfinite(distances)]
    if distances.size == 0:
        return None, None
    return float(np.mean(distances)), float(np.percentile(distances, 95))

def run_morphology_analysis(
    *,
    before_path: str,
    post_one_path: str,
    post_two_path: str,
    output_dir: str,
    units: str,
    threshold_db: float | None,
    use_otsu: bool,
    dates: dict[str, str] | None = None,
    maturity: str = "UNSPECIFIED",
    frequency: str = "frequencyA",
    polarization_term: str = "HHHH",
    sensitivity_delta_db: float = 2.0,
) -> dict[str, Any]:
    """Screen persistent post-event water/land transitions for erosion/deposition candidates."""
    paths = {
        "before": before_path,
        "post_one": post_one_path,
        "post_two": post_two_path,
    }
    arrays: dict[str, np.ndarray] = {}
    valids: dict[str, np.ndarray] = {}
    profiles: dict[str, dict[str, Any]] = {}
    for key, path in paths.items():
        arrays[key], valids[key], profiles[key] = read_band(path)
    assert_same_grid(profiles)
    series_metadata, provenance_complete = validate_gcov_series(
        paths, maturity=maturity, frequency=frequency, term=polarization_term,
    )
    source_provenance = gcov_source_provenance(series_metadata or [])
    for source_row, role in zip(source_provenance["observation_sources"], ("before", "post_one", "post_two")):
        source_row["observation_role"] = role
        source_row["acquisition_date"] = (dates or {}).get(role)

    if dates:
        ordered_dates = [date.fromisoformat(dates[key]) for key in ("before", "post_one", "post_two")]
        if not ordered_dates[0] < ordered_dates[1] < ordered_dates[2]:
            raise ValueError("Morphology observations must be ordered before < post_one < post_two.")
    if not np.isfinite(sensitivity_delta_db) or sensitivity_delta_db <= 0:
        raise ValueError("sensitivity_delta_db must be finite and greater than zero.")

    pixel_area_m2 = require_projected_metre_grid(profiles["before"])
    valid = valids["before"] & valids["post_one"] & valids["post_two"]
    db_arrays = {key: power_to_db(arrays[key], units) for key in paths}
    combined = np.concatenate([db_arrays[key][valid] for key in paths])
    combined_valid = np.isfinite(combined)
    if threshold_db is None:
        if not use_otsu:
            raise ValueError("Provide threshold_db or enable Otsu.")
        threshold_db = otsu_threshold_db(combined.reshape(1, -1), combined_valid.reshape(1, -1))
        threshold_method = "otsu_combined_three_dates_exploratory"
    else:
        threshold_method = "fixed_user_supplied_db_threshold"

    water = {
        key: classify_open_water(
            arrays[key], valids[key], units=units, threshold_db=threshold_db
        )
        for key in paths
    }

    stable_post_water = water["post_one"] & water["post_two"] & valid
    stable_post_land = ~water["post_one"] & ~water["post_two"] & valid

    erosion_candidate = ~water["before"] & stable_post_water & valid
    deposition_candidate = water["before"] & stable_post_land & valid

    erosion_area = float(erosion_candidate.sum() * pixel_area_m2 / 10_000)
    deposition_area = float(deposition_candidate.sum() * pixel_area_m2 / 10_000)
    net_land_change = deposition_area - erosion_area

    transform = profiles["before"]["transform"]
    pixel_size_y_m, pixel_size_x_m = _orthogonal_pixel_sizes(transform)
    mean_shift, p95_shift = symmetric_boundary_distance_m(
        water["before"] & valid,
        stable_post_water,
        pixel_size_y_m=pixel_size_y_m,
        pixel_size_x_m=pixel_size_x_m,
        valid_mask=valid,
    )

    threshold_sensitivity = []
    for offset_db in (-sensitivity_delta_db, -sensitivity_delta_db / 2, 0.0, sensitivity_delta_db / 2, sensitivity_delta_db):
        candidate_threshold = float(threshold_db + offset_db)
        scenario_water = {
            key: classify_open_water(arrays[key], valids[key], units=units, threshold_db=candidate_threshold)
            for key in paths
        }
        scenario_stable_water = scenario_water["post_one"] & scenario_water["post_two"] & valid
        scenario_stable_land = ~scenario_water["post_one"] & ~scenario_water["post_two"] & valid
        scenario_erosion = ~scenario_water["before"] & scenario_stable_water & valid
        scenario_deposition = scenario_water["before"] & scenario_stable_land & valid
        threshold_sensitivity.append({
            "threshold_db": candidate_threshold,
            "persistent_erosion_candidate_area_ha": float(scenario_erosion.sum() * pixel_area_m2 / 10_000),
            "persistent_deposition_candidate_area_ha": float(scenario_deposition.sum() * pixel_area_m2 / 10_000),
        })

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_mask(out / "erosion_candidate_mask.tif", erosion_candidate, valid, profiles["before"])
    write_mask(out / "deposition_candidate_mask.tif", deposition_candidate, valid, profiles["before"])
    erosion_polygons = write_mask_geojson(
        out / "erosion_candidates.geojson",
        erosion_candidate,
        valid,
        profiles["before"],
        class_name="erosion_candidate",
    )
    deposition_polygons = write_mask_geojson(
        out / "deposition_candidates.geojson",
        deposition_candidate,
        valid,
        profiles["before"],
        class_name="deposition_candidate",
    )

    result: dict[str, Any] = {
        "schema_version": 1,
        "engine": "RiverShift",
        "analysis_type": "river_morphology_screening",
        "source": {
            "mission": "NISAR",
            "instrument": "L-SAR",
            "product": "GCOV",
            "maturity": maturity.upper(),
            "frequency": frequency,
            "covariance_term": polarization_term,
            "granule_names": source_provenance["granule_names"],
            "source_granule_sha256": source_provenance["source_granule_sha256"],
            "observation_sources": source_provenance["observation_sources"],
        },
        "inputs": {
            **paths,
            "dates": dates or {},
            "input_units": units,
            "input_sha256": {key: sha256_file(path) for key, path in paths.items()},
        },
        "method": {
            "classification": "persistent_two_post_observation_water_land_transition",
            "threshold_db": safe_float(threshold_db),
            "threshold_method": threshold_method,
            "threshold_sensitivity_delta_db": float(sensitivity_delta_db),
            "threshold_sensitivity_is_statistical_confidence_interval": False,
            "post_observations_required": 2,
        },
        "metrics": {
            "persistent_erosion_candidate_area_ha": erosion_area,
            "persistent_deposition_candidate_area_ha": deposition_area,
            "net_candidate_land_change_ha": net_land_change,
            "symmetric_boundary_distance_mean_m": safe_float(mean_shift),
            "symmetric_boundary_distance_p95_m": safe_float(p95_shift),
            "erosion_polygon_count": int(erosion_polygons),
            "deposition_polygon_count": int(deposition_polygons),
        },
        "quality": {
            "status": "PERSISTENCE_SCREENED_NOT_INDEPENDENTLY_VALIDATED",
            "release_status": "PROVISIONAL",
            "provenance_complete": provenance_complete,
            "valid_comparison_pixel_count": int(valid.sum()),
            "warnings": [
                "Land-to-water and water-to-land transitions are candidate erosion/deposition zones, not confirmed geomorphic causation.",
                "Two post-event observations reduce transient-water confusion but do not replace same-stage hydrological comparison or field validation.",
                "Boundary distance is a symmetric displacement proxy, not a signed transect-derived bank migration rate.",
                "For braided rivers, interpret outer active-channel belt and individual threads separately.",
                "Check for bank protection, dredging, sand mining, embankments and seasonal channel stage before attributing change to the flood.",
                "Threshold sensitivity is a deterministic method-robustness check, not a statistical confidence interval or total error budget.",
            ],
        },
        "uncertainty": {
            "classification_threshold_sensitivity": {
                "method": "recompute candidate areas at five thresholds spanning the declared threshold ± sensitivity_delta_db",
                "delta_db": float(sensitivity_delta_db),
                "scenarios": threshold_sensitivity,
                "interpretation": "Scenario spread only; does not quantify reference, calibration, geolocation, stage or model uncertainty.",
            }
        },
        "outputs": {
            "erosion_mask": "erosion_candidate_mask.tif",
            "erosion_mask_sha256": sha256_file(out / "erosion_candidate_mask.tif"),
            "deposition_mask": "deposition_candidate_mask.tif",
            "deposition_mask_sha256": sha256_file(out / "deposition_candidate_mask.tif"),
            "erosion_geojson": "erosion_candidates.geojson",
            "deposition_geojson": "deposition_candidates.geojson",
            "erosion_geojson_sha256": sha256_file(out / "erosion_candidates.geojson"),
            "deposition_geojson_sha256": sha256_file(out / "deposition_candidates.geojson"),
        },
    }
    save_json(out / "river_shift_result.json", result)
    return result
