from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import date

import numpy as np

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


def run_flood_analysis(
    *,
    before_path: str,
    during_path: str,
    after_path: str,
    output_dir: str,
    units: str,
    threshold_db: float | None,
    use_otsu: bool,
    permanent_water_path: str | None = None,
    minimum_patch_hectares: float = 0.0,
    dates: dict[str, str] | None = None,
    maturity: str = "UNSPECIFIED",
    frequency: str = "frequencyA",
    polarization_term: str = "HHHH",
    sensitivity_delta_db: float = 2.0,
) -> dict[str, Any]:
    """Screen water expansion using one baseline, event-proximal and later GCOV acquisition."""
    arrays: dict[str, np.ndarray] = {}
    valids: dict[str, np.ndarray] = {}
    profiles: dict[str, dict[str, Any]] = {}
    for key, path in {
        "before": before_path,
        "during": during_path,
        "after": after_path,
    }.items():
        arrays[key], valids[key], profiles[key] = read_band(path)

    if permanent_water_path:
        arrays["permanent"], valids["permanent"], profiles["permanent"] = read_band(permanent_water_path)
    assert_same_grid(profiles)
    series_metadata, provenance_complete = validate_gcov_series(
        {"before": before_path, "during": during_path, "after": after_path},
        maturity=maturity, frequency=frequency, term=polarization_term,
    )
    source_provenance = gcov_source_provenance(series_metadata or [])

    if dates:
        ordered_dates = [date.fromisoformat(dates[key]) for key in ("before", "during", "after")]
        if not ordered_dates[0] < ordered_dates[1] < ordered_dates[2]:
            raise ValueError("Flood observations must be ordered before < during < after.")
    if not np.isfinite(sensitivity_delta_db) or sensitivity_delta_db <= 0:
        raise ValueError("sensitivity_delta_db must be finite and greater than zero.")

    pixel_area_m2 = require_projected_metre_grid(profiles["before"])
    valid_common = valids["before"] & valids["during"] & valids["after"]

    db_arrays = {key: power_to_db(arrays[key], units) for key in ("before", "during", "after")}
    combined = np.concatenate(
        [db_arrays[key][valid_common] for key in ("before", "during", "after")]
    )
    combined_valid = np.isfinite(combined)
    if threshold_db is None:
        if not use_otsu:
            raise ValueError("Provide threshold_db or enable Otsu.")
        threshold_db = otsu_threshold_db(
            combined.reshape(1, -1),
            combined_valid.reshape(1, -1),
        )
        threshold_method = "otsu_combined_three_dates_exploratory"
    else:
        threshold_method = "fixed_user_supplied_db_threshold"

    min_pixels = int(np.ceil((minimum_patch_hectares * 10_000.0) / pixel_area_m2))
    water = {
        key: classify_open_water(
            arrays[key],
            valids[key],
            units=units,
            threshold_db=threshold_db,
            minimum_pixels=min_pixels,
        )
        for key in ("before", "during", "after")
    }

    comparison_valid = valid_common.copy()
    new_water = water["during"] & ~water["before"] & comparison_valid

    permanent_excluded = False
    if permanent_water_path:
        permanent_mask = valids["permanent"] & (arrays["permanent"] > 0)
        new_water &= ~permanent_mask
        permanent_excluded = True

    baseline_area = float(water["before"][valid_common].sum() * pixel_area_m2 / 1_000_000)
    event_proximal_area = float(water["during"][valid_common].sum() * pixel_area_m2 / 1_000_000)
    post_area = float(water["after"][valid_common].sum() * pixel_area_m2 / 1_000_000)
    new_area = float(new_water.sum() * pixel_area_m2 / 1_000_000)
    change_percent = (
        ((event_proximal_area - baseline_area) / baseline_area) * 100.0
        if baseline_area > 0
        else None
    )

    threshold_sensitivity = []
    for offset_db in (-sensitivity_delta_db, -sensitivity_delta_db / 2, 0.0, sensitivity_delta_db / 2, sensitivity_delta_db):
        candidate_threshold = float(threshold_db + offset_db)
        scenario_water = {
            key: classify_open_water(
                arrays[key], valids[key], units=units, threshold_db=candidate_threshold,
                minimum_pixels=min_pixels,
            )
            for key in ("before", "during", "after")
        }
        scenario_new = scenario_water["during"] & ~scenario_water["before"] & comparison_valid
        if permanent_water_path:
            scenario_new &= ~permanent_mask
        threshold_sensitivity.append({
            "threshold_db": candidate_threshold,
            "baseline_water_area_km2": float(scenario_water["before"][valid_common].sum() * pixel_area_m2 / 1_000_000),
            "event_proximal_water_area_km2": float(scenario_water["during"][valid_common].sum() * pixel_area_m2 / 1_000_000),
            "newly_water_covered_area_km2": float(scenario_new.sum() * pixel_area_m2 / 1_000_000),
        })

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for key in ("before", "during", "after"):
        write_mask(out / f"{key}_water_mask.tif", water[key], valids[key], profiles[key])
    write_mask(out / "newly_water_covered_mask.tif", new_water, comparison_valid, profiles["before"])
    polygon_count = write_mask_geojson(
        out / "newly_water_covered.geojson",
        new_water,
        comparison_valid,
        profiles["before"],
        class_name="newly_water_covered",
    )

    result: dict[str, Any] = {
        "schema_version": 1,
        "engine": "RiverShift",
        "analysis_type": "flood_inundation_screening",
        "source": {
            "mission": "NISAR",
            "instrument": "L-SAR",
            "product": "GCOV",
            "maturity": maturity.upper(),
            "frequency": frequency,
            "covariance_term": polarization_term,
            "quantity": "gamma0_power_or_declared_input_units",
            "granule_names": source_provenance["granule_names"],
            "source_granule_sha256": source_provenance["source_granule_sha256"],
            "observation_sources": source_provenance["observation_sources"],
        },
        "inputs": {
            "before": str(before_path),
            "during": str(during_path),
            "event_proximal_observation": dates.get("during") if dates else None,
            "after": str(after_path),
            "permanent_water_mask": str(permanent_water_path) if permanent_water_path else None,
            "dates": dates or {},
            "input_units": units,
            "input_sha256": {
                key: sha256_file(path)
                for key, path in {"before": before_path, "during": during_path, "after": after_path}.items()
            },
            "permanent_water_mask_sha256": sha256_file(permanent_water_path) if permanent_water_path else None,
        },
        "method": {
            "classification": "low_backscatter_open_water_candidate",
            "threshold_db": safe_float(threshold_db),
            "threshold_method": threshold_method,
            "threshold_sensitivity_delta_db": float(sensitivity_delta_db),
            "threshold_sensitivity_is_statistical_confidence_interval": False,
            "minimum_patch_hectares": float(minimum_patch_hectares),
            "permanent_water_excluded": permanent_excluded,
        },
        "metrics": {
            "baseline_water_area_km2": baseline_area,
            "event_proximal_water_area_km2": event_proximal_area,
            "post_event_water_area_km2": post_area,
            "newly_water_covered_area_km2": new_area,
            "water_area_change_percent": safe_float(change_percent),
            "new_water_polygon_count": int(polygon_count),
        },
        "quality": {
            "status": "SCREENING_NOT_INDEPENDENTLY_VALIDATED",
            "release_status": "PROVISIONAL",
            "provenance_complete": provenance_complete,
            "valid_comparison_pixel_count": int(comparison_valid.sum()),
            "permanent_water_filter_applied": permanent_excluded,
            "warnings": [
                "The event-proximal observation is the first qualifying NISAR acquisition strictly after the user-supplied event date; it is not a measured peak-stage observation.",
                "New water coverage relative to the pre-event observation is not automatically proof of floodplain inundation.",
                "Use comparable orbit geometry, acquisition mode, frequency, polarization, maturity and hydrological conditions.",
                "Low-backscatter screening may miss inundated vegetation because double-bounce scattering can be bright.",
                "Validate the water mask against independent reference data before reporting accuracy or impact claims.",
                "Threshold sensitivity is a deterministic method-robustness check, not a statistical confidence interval or total error budget.",
            ],
        },
        "uncertainty": {
            "classification_threshold_sensitivity": {
                "method": "recompute area metrics at five thresholds spanning the declared threshold ± sensitivity_delta_db",
                "delta_db": float(sensitivity_delta_db),
                "scenarios": threshold_sensitivity,
                "interpretation": "Scenario spread only; does not quantify reference, calibration, geolocation, stage or model uncertainty.",
            }
        },
        "outputs": {
            "before_water_mask": "before_water_mask.tif",
            "before_water_mask_sha256": sha256_file(out / "before_water_mask.tif"),
            "during_water_mask": "during_water_mask.tif",
            "during_water_mask_sha256": sha256_file(out / "during_water_mask.tif"),
            "after_water_mask": "after_water_mask.tif",
            "after_water_mask_sha256": sha256_file(out / "after_water_mask.tif"),
            "new_water_mask": "newly_water_covered_mask.tif",
            "new_water_mask_sha256": sha256_file(out / "newly_water_covered_mask.tif"),
            "new_water_geojson": "newly_water_covered.geojson",
            "new_water_geojson_sha256": sha256_file(out / "newly_water_covered.geojson"),
        },
    }
    save_json(out / "river_shift_result.json", result)
    return result
