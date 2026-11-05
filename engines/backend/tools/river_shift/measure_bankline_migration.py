#!/usr/bin/env python3
"""Measure signed bankline movement using user-oriented perpendicular transects."""
from __future__ import annotations

import argparse
import sys

from river_shift.transects import measure_bankline_migration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-bankline", required=True)
    parser.add_argument("--after-bankline", required=True)
    parser.add_argument("--transects", required=True)
    parser.add_argument("--analysis-crs", required=True, help="Projected metre CRS, e.g. EPSG:32646.")
    parser.add_argument("--before-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--after-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--positive-direction-label", required=True, help="Meaning of the transect start-to-end direction, e.g. toward_channel.")
    parser.add_argument("--source-mission", default="NISAR")
    parser.add_argument("--source-product", default="GCOV")
    parser.add_argument("--maturity", choices=("BETA", "PROVISIONAL", "UNKNOWN"), required=True)
    parser.add_argument("--before-bankline-sigma-m", type=float, help="Optional 1-sigma bankline position error in metres.")
    parser.add_argument("--after-bankline-sigma-m", type=float, help="Optional 1-sigma bankline position error in metres.")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        result = measure_bankline_migration(
            before_bankline_path=args.before_bankline,
            after_bankline_path=args.after_bankline,
            transects_path=args.transects,
            analysis_crs=args.analysis_crs,
            before_date=args.before_date,
            after_date=args.after_date,
            positive_direction_label=args.positive_direction_label,
            source_mission=args.source_mission,
            source_product=args.source_product,
            maturity=args.maturity,
            output_dir=args.out_dir,
            before_bankline_sigma_m=args.before_bankline_sigma_m,
            after_bankline_sigma_m=args.after_bankline_sigma_m,
        )
        metrics = result["metrics"]
        print("VALID_TRANSECTS=" + str(metrics["valid_transect_count"]))
        print("MEAN_SIGNED_DISPLACEMENT_M=" + str(metrics["mean_signed_displacement_m"]))
        print("MEAN_NET_RATE_M_PER_YEAR=" + str(metrics["mean_net_rate_m_per_year"]))
        print("SUMMARY_JSON=" + args.out_dir + "/bankline_migration_summary.json")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
