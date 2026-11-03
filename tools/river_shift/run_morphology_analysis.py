#!/usr/bin/env python3
"""Screen persistent riverbank erosion and deposition candidates from three GCOV dates."""
from __future__ import annotations

import argparse
import sys

from river_shift.morphology import run_morphology_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="Pre-event reference GCOV gamma0 GeoTIFF.")
    parser.add_argument("--post-one", required=True, help="First post-recession GCOV observation.")
    parser.add_argument("--post-two", required=True, help="Second post-recession GCOV observation.")
    parser.add_argument("--before-date", required=True)
    parser.add_argument("--post-one-date", required=True)
    parser.add_argument("--post-two-date", required=True)
    threshold = parser.add_mutually_exclusive_group(required=True)
    threshold.add_argument("--threshold-db", type=float, help="User-selected common threshold in dB.")
    threshold.add_argument("--otsu", action="store_true", help="Exploratory common Otsu threshold over all dates.")
    parser.add_argument("--input-units", choices=("linear", "db"), default="linear")
    parser.add_argument("--maturity", choices=("BETA", "PROVISIONAL"), required=True)
    parser.add_argument("--frequency", choices=("frequencyA", "frequencyB"), default="frequencyA")
    parser.add_argument("--term", choices=("HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"), required=True)
    parser.add_argument("--sensitivity-delta-db", type=float, default=2.0, help="Threshold robustness range; not a confidence interval.")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    try:
        result = run_morphology_analysis(
            before_path=args.before,
            post_one_path=args.post_one,
            post_two_path=args.post_two,
            output_dir=args.out_dir,
            units=args.input_units,
            threshold_db=args.threshold_db,
            use_otsu=args.otsu,
            dates={
                "before": args.before_date,
                "post_one": args.post_one_date,
                "post_two": args.post_two_date,
            },
            maturity=args.maturity,
            frequency=args.frequency,
            polarization_term=args.term,
            sensitivity_delta_db=args.sensitivity_delta_db,
        )
        metrics = result["metrics"]
        print(f"EROSION_CANDIDATE_HA={metrics['persistent_erosion_candidate_area_ha']:.3f}")
        print(f"DEPOSITION_CANDIDATE_HA={metrics['persistent_deposition_candidate_area_ha']:.3f}")
        print(f"RESULT_JSON={args.out_dir}/river_shift_result.json")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
