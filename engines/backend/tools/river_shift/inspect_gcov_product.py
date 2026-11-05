#!/usr/bin/env python3
"""Inspect NISAR GCOV HDF5 subdatasets with the NISAR-compatible GDAL driver."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def gdal_version() -> tuple[int, int, int]:
    result = subprocess.run(["gdalinfo", "--version"], capture_output=True, text=True, check=True)
    match = re.search(r"GDAL\s+(\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
    if not match:
        raise RuntimeError("Could not parse GDAL version from gdalinfo --version.")
    return tuple(int(part) for part in match.groups())


def gdal_driver_names() -> set[str]:
    """Return registered GDAL format-driver names, not just installed packages."""
    result = subprocess.run(["gdalinfo", "--formats"], capture_output=True, text=True, check=True)
    names: set[str] = set()
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        match = re.match(r"\s*([A-Za-z0-9_]+)\s+-", line)
        if match:
            names.add(match.group(1))
    return names


def require_hdf5_driver() -> None:
    drivers = gdal_driver_names()
    if "HDF5" not in drivers:
        raise RuntimeError(
            "GDAL HDF5 raster driver is not registered. Install the matching "
            "libgdal-hdf5 package alongside libgdal-core in the RiverShift "
            "environment, then verify it with 'gdalinfo --formats'."
        )


def inspect_product(product: Path) -> dict[str, Any]:
    if not product.is_file():
        raise FileNotFoundError(product)
    version = gdal_version()
    if version < (3, 13, 0):
        raise RuntimeError(
            "NISAR HDF5 georeferencing requires GDAL 3.13.0 or newer. "
            f"Detected {'.'.join(map(str, version))}. See the NISAR Data User Guide GDAL page."
        )

    require_hdf5_driver()
    try:
        # Force the NISAR-compatible HDF5 path instead of relying on GDAL's
        # automatic driver selection for a .h5 filename.
        result = subprocess.run(
            ["gdalinfo", "-if", "HDF5", "-json", str(product)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or "").strip()
        if diagnostic:
            detail = f"GDAL diagnostic: {diagnostic[-2000:]}"
        else:
            detail = "GDAL returned no diagnostic output."
        raise RuntimeError(
            f"GDAL HDF5 inspection failed for {product.name}. {detail}"
        ) from exc

    payload = json.loads(result.stdout)
    metadata = payload.get("metadata", {})
    subdatasets = metadata.get("SUBDATASETS", {})
    terms = []
    masks = []
    for key, value in sorted(subdatasets.items()):
        if not key.endswith("_NAME") or not isinstance(value, str):
            continue
        path = value.rsplit(":", 1)[-1].lstrip("/")
        term = path.split("/")[-1]
        frequency = next((part for part in path.split("/") if part in {"frequencyA", "frequencyB"}), None)
        if term == "mask" and frequency:
            masks.append({"frequency": frequency, "subdataset": value})
        if term in {"HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"}:
            terms.append({"frequency": frequency, "term": term, "subdataset": value})
    if not terms:
        raise RuntimeError(
            "No diagonal GCOV covariance layers were found. Check that the input is a NISAR GCOV product."
        )

    return {
        "schema_version": 1,
        "product_file": str(product.resolve()),
        "gdal_version": ".".join(map(str, version)),
        "driver": payload.get("driverShortName"),
        "size": payload.get("size"),
        "coordinate_system": payload.get("coordinateSystem", {}).get("wkt"),
        "available_diagonal_terms": terms,
        "available_valid_sample_masks": masks,
        "available_subdatasets": len(subdatasets) // 2,
        "notes": [
            "Diagonal covariance terms are real-valued backscatter power layers.",
            "The available terms depend on the acquisition polarization mode.",
            "Use one matching frequency and covariance term for every acquisition in a time series.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_product(args.product)
        output = args.out or args.product.with_suffix(".gcov_inventory.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"GDAL_VERSION={result['gdal_version']}")
        print("GCOV_TERMS=" + ",".join(item["term"] for item in result["available_diagonal_terms"]))
        print(f"INVENTORY={output}")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
