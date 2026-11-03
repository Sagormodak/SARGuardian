from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from .raster_io import (
    assert_same_grid,
    power_to_db,
    read_band,
    require_projected_metre_grid,
    safe_float,
    save_json,
    sha256_file,
    validate_gcov_series,
    gcov_source_provenance,
    write_mask,
    write_mask_geojson,
)
from .water_detection import classify_open_water, otsu_threshold_db


def run_water_timeseries_analysis(
    *,
    observations: list[dict[str, str]],
    output_dir: str,
    units: str,
    threshold_db: float | None,
    use_otsu: bool,
    maturity: str,
    frequency: str,
    polarization_term: str,
    minimum_patch_hectares: float = 0.0,
    sensitivity_delta_db: float = 2.0,
) -> dict[str, Any]:
    """Export observed-date water candidates for discrete-acquisition playback."""
    if len(observations) < 2:
        raise ValueError("At least two distinct acquisition dates are required for a time series.")
    ordered = sorted(observations, key=lambda row: date.fromisoformat(row["date"]))
    dates = [date.fromisoformat(row["date"]) for row in ordered]
    if len(set(dates)) != len(dates):
        raise ValueError("Each time-series acquisition date must be unique.")
    if not np.isfinite(minimum_patch_hectares) or minimum_patch_hectares < 0:
        raise ValueError("minimum_patch_hectares cannot be negative.")
    if not np.isfinite(sensitivity_delta_db) or sensitivity_delta_db <= 0:
        raise ValueError("sensitivity_delta_db must be finite and greater than zero.")

    arrays: list[np.ndarray] = []
    valids: list[np.ndarray] = []
    profiles: dict[str, dict[str, Any]] = {}
    paths: dict[str, str] = {}
    for row in ordered:
        arrays_item, valid_item, profile_item = read_band(row["path"])
        arrays.append(arrays_item)
        valids.append(valid_item)
        profiles[row["date"]] = profile_item
        paths[row["date"]] = row["path"]
    assert_same_grid(profiles)
    sidecars, provenance_complete = validate_gcov_series(
        paths, maturity=maturity, frequency=frequency, term=polarization_term,
    )
    source_provenance = gcov_source_provenance(sidecars or [])
    for source_row, observation in zip(source_provenance["observation_sources"], ordered):
        source_row["acquisition_date"] = observation["date"]
    pixel_area_m2 = require_projected_metre_grid(profiles[ordered[0]["date"]])
    # Every date is compared on exactly the same spatial support. Using each
    # acquisition's independent valid mask would make area changes partly a
    # function of changing coverage rather than water classification.
    common_valid = np.logical_and.reduce(valids)
    if not common_valid.any():
        raise ValueError("The selected acquisitions have no common valid pixels; a comparable time series cannot be measured.")
    db_arrays = [power_to_db(array, units) for array in arrays]
    if threshold_db is None:
        if not use_otsu:
            raise ValueError("Provide threshold_db or enable Otsu.")
        values = np.concatenate([db[common_valid & np.isfinite(db)] for db in db_arrays])
        threshold_db = otsu_threshold_db(values.reshape(1, -1), np.isfinite(values).reshape(1, -1))
        threshold_method = "otsu_combined_all_observed_dates_exploratory"
    else:
        threshold_method = "fixed_user_supplied_db_threshold"

    min_pixels = int(np.ceil(minimum_patch_hectares * 10_000.0 / pixel_area_m2))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    total_pixels = int(arrays[0].size)
    comparison_pixel_count = int(common_valid.sum())
    comparison_pixel_fraction = float(comparison_pixel_count / total_pixels) if total_pixels else 0.0
    for index, (row, array, source_valid) in enumerate(zip(ordered, arrays, valids)):
        water = classify_open_water(
            array, common_valid, units=units, threshold_db=threshold_db, minimum_pixels=min_pixels,
        )
        water_area = float(water.sum() * pixel_area_m2 / 1_000_000.0)
        mask_path = out / f"water_{row['date']}_mask.tif"
        geojson_path = out / f"water_{row['date']}.geojson"
        write_mask(mask_path, water, common_valid, profiles[row["date"]])
        polygon_count = write_mask_geojson(
            geojson_path, water, common_valid, profiles[row["date"]], class_name="open_water_candidate",
        )
        metadata = sidecars[index] if sidecars else None
        frames.append({
            "date": row["date"],
            "granule_name": metadata["source_granule_name"] if metadata else None,
            "water_area_km2": water_area,
            "valid_pixel_count": comparison_pixel_count,
            "valid_pixel_fraction": comparison_pixel_fraction,
            "source_valid_pixel_count": int(source_valid.sum()),
            "source_valid_pixel_fraction": float(source_valid.sum() / total_pixels) if total_pixels else 0.0,
            "water_polygon_count": int(polygon_count),
            "water_mask": mask_path.name,
            "water_mask_sha256": sha256_file(mask_path),
            "water_geojson": geojson_path.name,
            "water_geojson_sha256": sha256_file(geojson_path),
        })

    sensitivity = []
    for offset in (-sensitivity_delta_db, -sensitivity_delta_db / 2, 0.0, sensitivity_delta_db / 2, sensitivity_delta_db):
        scenario_threshold = float(threshold_db + offset)
        scenario_frames = []
        for row, array in zip(ordered, arrays):
            scenario_water = classify_open_water(
                array, common_valid, units=units, threshold_db=scenario_threshold, minimum_pixels=min_pixels,
            )
            scenario_frames.append({
                "date": row["date"],
                "water_area_km2": float(scenario_water.sum() * pixel_area_m2 / 1_000_000.0),
            })
        sensitivity.append({"threshold_db": scenario_threshold, "observations": scenario_frames})

    source_metadata = sidecars or []
    areas = [frame["water_area_km2"] for frame in frames]
    result: dict[str, Any] = {
        "schema_version": 1,
        "engine": "RiverShift",
        "analysis_type": "water_timeseries_screening",
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
            "input_units": units,
            "observations": [
                {"date": row["date"], "path": row["path"], "sha256": sha256_file(row["path"])}
                for row in ordered
            ],
            "grid": {
                "crs": str(profiles[ordered[0]["date"]]["crs"]),
                "width": profiles[ordered[0]["date"]]["width"],
                "height": profiles[ordered[0]["date"]]["height"],
                "transform": list(profiles[ordered[0]["date"]]["transform"])[:6],
            },
        },
        "method": {
            "classification": "low_backscatter_open_water_candidate_per_acquisition",
            "threshold_db": safe_float(threshold_db),
            "threshold_method": threshold_method,
            "minimum_patch_hectares": float(minimum_patch_hectares),
            "playback_semantics": "discrete observed acquisition dates; no temporal interpolation",
        },
        "metrics": {
            "observation_count": len(frames),
            "comparison_valid_pixel_count": comparison_pixel_count,
            "comparison_valid_pixel_fraction": comparison_pixel_fraction,
            "minimum_observed_water_area_km2": min(areas),
            "maximum_observed_water_area_km2": max(areas),
        },
        "time_series": frames,
        "quality": {
            "status": "OBSERVED_DATE_SCREENING_NOT_INDEPENDENTLY_VALIDATED",
            "release_status": "PROVISIONAL",
            "provenance_complete": provenance_complete,
            "valid_comparison_pixel_count": comparison_pixel_count,
            "valid_comparison_pixel_fraction": comparison_pixel_fraction,
            "warnings": [
                "Each frame is one satellite acquisition date; no daily observations or interpolated states are implied.",
                "Low-backscatter open-water candidates can omit flooded vegetation and include smooth bare soil or radar shadow.",
                "All observations are compared on the intersection of their valid-pixel masks; source coverage outside that common support is excluded from every date's area estimate.",
                "Water-area differences remain sensitive to water stage and threshold choice.",
                "This time series is not a flood-causation claim and requires independent reference validation.",
            ],
        },
        "uncertainty": {
            "classification_threshold_sensitivity": {
                "method": "recompute each acquisition's area at five thresholds spanning the declared threshold ± sensitivity_delta_db",
                "delta_db": float(sensitivity_delta_db),
                "scenarios": sensitivity,
                "interpretation": "Deterministic threshold sensitivity only; not a confidence interval or total error budget.",
            },
        },
    }
    save_json(out / "river_shift_timeseries.json", result)
    return result
