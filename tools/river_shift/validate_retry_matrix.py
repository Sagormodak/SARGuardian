#!/usr/bin/env python3
"""Validate one exact RiverShift delayed-retry matrix at the GitHub job boundary."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def validate_retry_matrix(raw: str, count_raw: str, expected_attempt: int) -> tuple[dict, int]:
    if not raw or not count_raw:
        raise ValueError("RETRY_MATRIX_HANDOFF_FAILED: retry preparation outputs are missing.")
    try:
        matrix = json.loads(raw)
        count = int(count_raw)
    except (json.JSONDecodeError, ValueError):
        raise ValueError("RETRY_MATRIX_HANDOFF_FAILED: retry matrix JSON or count is invalid.") from None

    rows = matrix.get("include") if isinstance(matrix, dict) else None
    if not isinstance(rows, list) or count < 0 or len(rows) != count:
        row_count = len(rows) if isinstance(rows, list) else "invalid"
        raise ValueError(f"RETRY_MATRIX_HANDOFF_FAILED: retry_count={count}, matrix_include_count={row_count}.")

    required = {
        "granule_name", "acquisition_date", "batch_number", "batch_count",
        "product_index", "total_products", "retry_attempt",
    }
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError("RETRY_MATRIX_HANDOFF_FAILED: retry row is missing required identity fields.")
        name = row["granule_name"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{10,250}", name)
            or name in seen
            or row["retry_attempt"] != expected_attempt
            or row["batch_number"] != 4 + expected_attempt
            or row["batch_count"] != 1
            or row["product_index"] < 1
            or row["product_index"] > count
            or row["total_products"] != count
        ):
            raise ValueError("RETRY_MATRIX_HANDOFF_FAILED: retry matrix contains an invalid or duplicate product identity.")
        seen.add(name)

    if [row["product_index"] for row in rows] != list(range(1, count + 1)):
        raise ValueError("RETRY_MATRIX_HANDOFF_FAILED: retry product indexes are not contiguous.")

    return matrix, count


def main() -> int:
    expected_attempt = int(os.environ.get("RIVERSHIFT_EXPECTED_RETRY_ATTEMPT", "1"))
    raw = os.environ.get("RIVERSHIFT_RETRY_MATRIX_JSON", "")
    count_raw = os.environ.get("RIVERSHIFT_RETRY_COUNT", "")
    try:
        matrix, count = validate_retry_matrix(raw, count_raw, expected_attempt)
    except ValueError as exc:
        print(str(exc), flush=True)
        return 1

    compact = json.dumps(matrix, separators=(",", ":"))
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as stream:
            stream.write(f"retry_matrix={compact}\n")
            stream.write(f"retry_count={count}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            "## Fresh-runner retry matrix handoff validation\n\n"
            f"- Retry wave: **{expected_attempt}/3**\n"
            f"- Queued products: **{count}**\n"
            "- Exact wave identity: **PASS**\n"
            "- Product uniqueness and contiguous indexes: **PASS**\n",
            encoding="utf-8",
        )
    print(f"RIVERSHIFT_RETRY_MATRIX_HANDOFF=PASS wave={expected_attempt} count={count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
