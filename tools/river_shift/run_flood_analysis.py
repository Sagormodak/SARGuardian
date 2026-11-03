#!/usr/bin/env python3
"""Create before/during/after NISAR GCOV water masks and a new-water-coverage result."""
from __future__ import annotations

import argparse
import sys

from river_shift.flood import run_flood_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="Pre-event GCOV gamma0 GeoTIFF.")
    parser.add_argument("--during", required=True, help="Flood-peak/near-peak GCOV gamma0 GeoTIFF.")
    parser.add_argument("--after", required=True, help="Post-event recovery GCOV gamma0 GeoTIFF.")
    parser.add_argument("--before-date", required=True)
    parser.add_argument("--during-date", required=True)
    parser.add_argument("--after-date", required=True)
    threshold = parser.add_mutually_exclusive_group(required=True)
    threshold.add_argument("--threshold-db", type=float, help="User-selected common threshold in dB.")
    threshold.add_argument("--otsu", action="store_true", help="Exploratory common Otsu threshold over all three dates.")
    parser.add_argument("--input-units", choices=("linear", "db"), default="linear")
    parser.add_argument("--permanent-water-mask", help="Optional aligned binary mask: 1=permanent water.")
    parser.add_argument("--minimum-patch-hectares", type=float, default=0.0)
    parser.add_argument("--maturity", choices=("BETA", "PROVISIONAL"), required=True)
    parser.add_argument("--frequency", choices=("frequencyA", "frequencyB"), default="frequencyA")
    parser.add_argument("--term", choices=("HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"), required=True)
    parser.add_argument("--sensitivity-delta-db", type=float, default=2.0, help="Threshold robustness range; not a confidence interval.")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    try:
        if args.minimum_patch_hectares < 0:
            raise ValueError("minimum-patch-hectares cannot be negative.")
        result = run_flood_analysis(
            before_path=args.before,
            during_path=args.during,
            after_path=args.after,
            output_dir=args.out_dir,
            units=args.input_units,
            threshold_db=args.threshold_db,
            use_otsu=args.otsu,
            permanent_water_path=args.permanent_water_mask,
            minimum_patch_hectares=args.minimum_patch_hectares,
            dates={
                "before": args.before_date,
                "during": args.during_date,
                "after": args.after_date,
            },
            maturity=args.maturity,
            frequency=args.frequency,
            polarization_term=args.term,
            sensitivity_delta_db=args.sensitivity_delta_db,
        )
        print(f"NEW_WATER_COVERED_KM2={result['metrics']['newly_water_covered_area_km2']:.6f}")
        print(f"RESULT_JSON={args.out_dir}/river_shift_result.json")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
