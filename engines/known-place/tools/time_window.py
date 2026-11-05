"""Helpers for selecting NISAR baseline granules by acquisition date."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable


def parse_iso_date(value: str, field_name: str) -> date:
    """Parse a strict YYYY-MM-DD date; fail closed on ambiguous formats."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return parsed


def secondary_acquisition_date(granule_name: str) -> date:
    """Return the second acquisition's start date (3rd of 4 NISAR timestamps)."""
    timestamps = re.findall(r"_(\d{8})T\d{6}", granule_name or "")
    if len(timestamps) != 4:
        raise ValueError("granule_name must contain the four NISAR pair timestamps")
    try:
        # NISAR pair order is reference start/stop, then secondary start/stop.
        return datetime.strptime(timestamps[2], "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("granule_name contains an invalid secondary acquisition date") from exc


def filter_products_by_time_window(
    products: Iterable[dict[str, Any]], start_date: str, end_date: str
) -> list[dict[str, Any]]:
    """Filter products by inclusive secondary-acquisition date, preserving source order."""
    start = parse_iso_date(start_date, "start_date")
    end = parse_iso_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")

    selected: list[dict[str, Any]] = []
    for product in products:
        name = product.get("granule_name")
        if not isinstance(name, str) or not name:
            raise ValueError("each product must have a granule_name")
        acquired = secondary_acquisition_date(name)
        if start <= acquired <= end:
            item = dict(product)
            item["secondary_acquisition_date"] = acquired.isoformat()
            selected.append(item)
    return selected
