#!/usr/bin/env python3
"""Validate a RiverShift binary water mask against an independent reference raster."""
from __future__ import annotations

import argparse
import sys

from river_shift.validation import save_validation_report, validate_binary_classification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", required=True, help="RiverShift mask: 1=water, 0=non-water.")
    parser.add_argument("--reference", required=True, help="Independent reference mask on the exact same grid.")
    parser.add_argument("--reference-source", required=True, help="Dataset, agency or field-survey name.")
    parser.add_argument("--reference-date", required=True, help="Reference observation date (YYYY-MM-DD).")
    parser.add_argument("--reference-method", required=True, help="How the reference water mask was produced.")
    parser.add_argument("--block-size-pixels", type=int, default=64, help="Spatial block width/height for bootstrap uncertainty.")
    parser.add_argument("--bootstrap-replicates", type=int, default=500, help="Spatial block bootstrap replicates (minimum 100).")
    parser.add_argument("--random-seed", type=int, default=42, help="Deterministic bootstrap seed.")
    parser.add_argument("--out", required=True, help="Validation JSON report.")
    args = parser.parse_args()
    try:
        result = validate_binary_classification(
            args.prediction,
            args.reference,
            reference_source=args.reference_source,
            reference_date=args.reference_date,
            reference_method=args.reference_method,
            block_size_pixels=args.block_size_pixels,
            bootstrap_replicates=args.bootstrap_replicates,
            random_seed=args.random_seed,
        )
        save_validation_report(result, args.out)
        print(f"F1_SCORE={result['metrics']['f1_score']:.4f}")
        print(f"IOU={result['metrics']['intersection_over_union']:.4f}")
        print(f"VALIDATION_REPORT={args.out}")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
