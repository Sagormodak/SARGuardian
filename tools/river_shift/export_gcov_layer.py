#!/usr/bin/env python3
"""Extract one calibrated GCOV diagonal covariance term to an AOI-clipped GeoTIFF."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from shapely import wkt as shapely_wkt
from shapely.geometry import mapping
import numpy as np
import rasterio

from inspect_gcov_product import inspect_product


SUPPORTED_TERMS = {"HHHH", "HVHV", "VVVV", "VHVH", "RHRH", "RVRV"}


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apply_valid_sample_mask(backscatter_path: Path, mask_path: Path, output_path: Path) -> dict[str, int]:
    """Exclude GCOV pixels whose matching subswath mask is 0 or fill 255."""
    with rasterio.open(backscatter_path) as source, rasterio.open(mask_path) as quality:
        if source.crs != quality.crs or source.transform != quality.transform or (
            source.width != quality.width or source.height != quality.height
        ):
            raise ValueError("Backscatter and GCOV valid-sample mask are not on the exact same grid.")
        values = source.read(1)
        mask_values = quality.read(1)
        valid = (
            (source.dataset_mask() > 0)
            & np.isfinite(values)
            & (quality.dataset_mask() > 0)
            & (mask_values >= 1)
            & (mask_values <= 254)
        )
        profile = source.profile.copy()
        profile.update(
            driver="GTiff", count=1, dtype=source.dtypes[0], tiled=True,
            blockxsize=256, blockysize=256, compress="DEFLATE",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_path, "w", **profile) as destination:
            destination.write(values, 1)
            destination.write_mask(valid.astype(np.uint8) * 255)
    return {
        "valid_pixel_count": int(valid.sum()),
        "excluded_pixel_count": int(valid.size - valid.sum()),
    }


def verify_download_receipt(product: Path, maturity: str) -> tuple[Path, str]:
    """Bind a local HDF5 file to the exact ASF granule receipt and maturity."""
    receipt_path = product.with_name(product.stem + ".download.json")
    if not receipt_path.is_file():
        raise ValueError("Download receipt is missing; download the exact manifest granule with download_gcov_product.py first.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Download receipt is unreadable.") from exc
    receipt_host = str(receipt.get("source_host") or "").lower()
    trusted_receipt_host = (
        receipt_host == "asf.alaska.edu"
        or receipt_host.endswith(".asf.alaska.edu")
        or receipt_host.endswith(".asf.earthdatacloud.nasa.gov")
    )
    if (
        receipt.get("granule_name") != product.stem
        or receipt.get("product") != "GCOV"
        or receipt.get("maturity") != maturity
        or receipt.get("downloaded") is not True
        or not trusted_receipt_host
        or not isinstance(receipt.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", receipt["sha256"])
    ):
        raise ValueError("Download receipt must match this exact GCOV granule, maturity and trusted ASF host.")
    source_sha256 = sha256_file(product)
    if receipt["sha256"].lower() != source_sha256:
        raise ValueError("Download receipt SHA-256 does not match the product file.")
    return receipt_path, source_sha256


def export_layer(
    product: Path,
    output: Path,
    *,
    frequency: str,
    term: str,
    aoi_wkt: str,
    maturity: str,
) -> dict[str, Any]:
    if term not in SUPPORTED_TERMS:
        raise ValueError(f"term must be one of {sorted(SUPPORTED_TERMS)}.")
    if frequency not in {"frequencyA", "frequencyB"}:
        raise ValueError("frequency must be frequencyA or frequencyB.")
    if maturity not in {"BETA", "PROVISIONAL"}:
        raise ValueError("A verified BETA or PROVISIONAL product maturity is required.")
    name_fields = product.stem.split("_")
    if len(name_fields) != 18 or name_fields[:2] != ["NISAR", "L2"] or name_fields[2] not in {"PR", "UR", "OD"} or name_fields[3] != "GCOV":
        raise ValueError("Product filename must be an exact NISAR Level-2 single-acquisition GCOV granule name.")
    receipt_path, source_sha256 = verify_download_receipt(product, maturity)
    geometry = shapely_wkt.loads(aoi_wkt)
    if geometry.geom_type != "Polygon" or geometry.is_empty or not geometry.is_valid:
        raise ValueError("AOI must be one valid, non-empty WGS84 POLYGON WKT.")

    inventory = inspect_product(product)
    expected_suffix = f"/science/LSAR/GCOV/grids/{frequency}/{term}"
    matches = [
        item["subdataset"]
        for item in inventory["available_diagonal_terms"]
        if item["subdataset"].endswith(expected_suffix)
    ]
    if not matches:
        raise ValueError(f"Requested GCOV layer was not found: {frequency}/{term}.")

    mask_matches = [
        item["subdataset"]
        for item in inventory.get("available_valid_sample_masks", [])
        if item.get("frequency") == frequency
    ]
    if len(mask_matches) != 1:
        raise ValueError(f"Expected one {frequency} GCOV valid-sample mask; found {len(mask_matches)}.")

    subdataset = matches[0]
    mask_subdataset = mask_matches[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    clipped = output.with_name(output.stem + ".backscatter-intermediate.tif")
    clipped_mask = output.with_name(output.stem + ".quality-mask-intermediate.tif")
    masked = output.with_name(output.stem + ".masked-intermediate.tif")
    cutline = output.with_name(output.stem + ".cutline.geojson")
    cutline.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": mapping(geometry),
            }],
        }),
        encoding="utf-8",
    )

    # GDAL -cutline expects a vector datasource, so pass this temporary GeoJSON.
    # Warp the selected HDF5 subdataset directly to the AOI to avoid a full-frame raster.
    run([
        "gdalwarp", "-overwrite", "-of", "GTiff",
        "-cutline", str(cutline),
        "-cutline_srs", "EPSG:4326",
        "-crop_to_cutline",
        "-dstalpha",
        "-co", "TILED=YES",
        "-co", "COMPRESS=DEFLATE",
        subdataset, str(clipped),
    ])
    run([
        "gdalwarp", "-overwrite", "-of", "GTiff", "-r", "near",
        "-cutline", str(cutline),
        "-cutline_srs", "EPSG:4326",
        "-crop_to_cutline",
        "-dstnodata", "255",
        "-co", "TILED=YES",
        "-co", "COMPRESS=DEFLATE",
        mask_subdataset, str(clipped_mask),
    ])
    mask_counts = apply_valid_sample_mask(clipped, clipped_mask, masked)
    run([
        "gdal_translate", "-of", "COG",
        "-co", "COMPRESS=DEFLATE",
        "-co", "BLOCKSIZE=512",
        str(masked), str(output),
    ])

    clipped.unlink(missing_ok=True)
    clipped_mask.unlink(missing_ok=True)
    masked.unlink(missing_ok=True)
    cutline.unlink(missing_ok=True)
    metadata = {
        "schema_version": 1,
        "source_product_file": str(product.resolve()),
        "source_product_type": "NISAR_L2_GCOV",
        "source_granule_name": product.stem,
        "source_granule_names": [product.stem],
        "source_granule_sha256": [source_sha256],
        "source_product_sha256": source_sha256,
        "download_receipt": str(receipt_path.resolve()),
        "processing_type": name_fields[2],
        "relative_orbit": name_fields[5],
        "flight_direction": {"A": "ASCENDING", "D": "DESCENDING"}.get(name_fields[6], name_fields[6]),
        "frame": name_fields[7],
        "bandwidth_mode": name_fields[8],
        "polarization_code": name_fields[9],
        "observation_source": name_fields[10],
        "acquisition_start_utc": name_fields[11],
        "acquisition_end_utc": name_fields[12],
        "crid": name_fields[13],
        "orbit_accuracy": name_fields[14],
        "frame_coverage": "FULL" if name_fields[15] == "F" else "PARTIAL",
        "processing_center": name_fields[16],
        "maturity": maturity,
        "frequency": frequency,
        "covariance_term": term,
        "output_cog": str(output.resolve()),
        "output_cog_sha256": sha256_file(output),
        "input_dataset": subdataset,
        "valid_sample_mask_dataset": mask_subdataset,
        "valid_sample_mask_rule": "Keep GCOV mask values 1..254; exclude 0 (invalid ensemble) and 255 (outside acquisition).",
        **mask_counts,
        "aoi_wkt": aoi_wkt,
        "units": "gamma0_power",
        "gdal_version": inventory["gdal_version"],
    }
    output.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True, type=Path)
    parser.add_argument("--frequency", choices=("frequencyA", "frequencyB"), default="frequencyA")
    parser.add_argument("--term", choices=sorted(SUPPORTED_TERMS), required=True)
    parser.add_argument("--maturity", choices=("BETA", "PROVISIONAL"), required=True)
    parser.add_argument("--aoi-wkt", required=True, help="WGS84 polygon WKT copied from the study-area AOI.")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = export_layer(
            args.product, args.out, frequency=args.frequency, term=args.term,
            aoi_wkt=args.aoi_wkt, maturity=args.maturity,
        )
        print(f"GCOV_COG={result['output_cog']}")
        print(f"GCOV_TERM={args.frequency}/{args.term}")
        print(f"MATURITY={args.maturity}")
        return 0
    except Exception as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
