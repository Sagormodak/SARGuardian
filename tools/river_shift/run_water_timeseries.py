#!/usr/bin/env python3
"""Create per-acquisition water masks for observed-date RiverShift playback."""
from __future__ import annotations

import argparse
import sys

from river_shift.timeseries import run_water_timeseries_analysis


def parse_observation(value: str) -> dict[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Use DATE=PATH, for example 2026-06-18=data/processed/date.tif.")
    observed_date, path = value.split("=", 1)
    if not observed_date.strip() or not path.strip():
        raise argparse.ArgumentTypeError("Both the acquisition date and raster path are required.")
    return {"date": observed_date.strip(), "path": path.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", action="append", type=parse_observation, required=True,
                        help="Repeat DATE=PATH once for each co-registered acquisition; at least two are required.")
    threshold = parser.add_mutually_exclusive_group(required=True)
    threshold.add_argument("--threshold-db", type=float, help="One validated common water threshold in dB.")
    threshold.add_argument("--otsu", action="store_true", help="Exploratory common Otsu threshold across all observed dates.")
    parser.add_argument("--input-units", choices=("linear", "db"), default="linear")
    parser.add_argument("--minimum-patch-hectares", type=float, default=0.0)
    parser.add_argument("--maturity", choices=("BETA", "PROVISIONAL"), required=True)
    parser.add_argument("--frequency", choices=("frequencyA", "frequencyB"), default="frequencyA")
    parser.add_argument("--term", choices=("HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"), required=True)
    parser.add_argument("--sensitivity-delta-db", type=float, default=2.0,
                        help="Threshold-robustness range; it is not a confidence interval.")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        result = run_water_timeseries_analysis(
            observations=args.observation,
            output_dir=args.out_dir,
            units=args.input_units,
            threshold_db=args.threshold_db,
            use_otsu=args.otsu,
            maturity=args.maturity,
            frequency=args.frequency,
            polarization_term=args.term,
            minimum_patch_hectares=args.minimum_patch_hectares,
            sensitivity_delta_db=args.sensitivity_delta_db,
        )
        print(f"OBSERVATION_COUNT={result['metrics']['observation_count']}")
        print(f"RESULT_JSON={args.out_dir}/river_shift_timeseries.json")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
