from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform_geom


class RasterContractError(ValueError):
    """Raised when rasters cannot be compared without unsafe assumptions."""


def read_band(path: str | Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Read band 1 as float64 with a validity mask and a copy of its profile."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Raster does not exist: {path}")

    with rasterio.open(path) as src:
        if src.count < 1:
            raise RasterContractError(f"Raster contains no bands: {path}")
        raw = src.read(1)
        array = np.asarray(raw, dtype=np.float64)
        valid = (src.dataset_mask() > 0) & np.isfinite(array)
        profile = src.profile.copy()
        profile["transform"] = src.transform
        profile["crs"] = src.crs
        profile["width"] = src.width
        profile["height"] = src.height
        profile["nodata"] = src.nodata
    return array, valid, profile


def assert_same_grid(named_profiles: dict[str, dict[str, Any]]) -> None:
    """Require exact dimensions, affine transform and CRS before pixel comparison."""
    if len(named_profiles) < 2:
        return

    items = list(named_profiles.items())
    base_name, base = items[0]
    if base.get("crs") is None:
        raise RasterContractError(f"{base_name} has no CRS.")

    for name, profile in items[1:]:
        if profile.get("crs") != base.get("crs"):
            raise RasterContractError(
                f"CRS mismatch: {base_name}={base.get('crs')} vs {name}={profile.get('crs')}. "
                "Reproject all inputs to one common projected CRS before analysis."
            )
        if profile.get("width") != base.get("width") or profile.get("height") != base.get("height"):
            raise RasterContractError(f"Raster dimensions differ: {base_name} vs {name}.")
        if profile.get("transform") != base.get("transform"):
            raise RasterContractError(f"Affine grids differ: {base_name} vs {name}.")


def require_projected_metre_grid(profile: dict[str, Any]) -> float:
    """Return pixel area in square metres; reject geographic or non-metre CRS."""
    crs = profile.get("crs")
    if crs is None or not crs.is_projected:
        raise RasterContractError(
            "Area calculations require a projected CRS. Reproject the inputs to a "
            "metric projected CRS such as the appropriate UTM zone."
        )

    units = str(getattr(crs, "linear_units", "") or "").lower()
    if units not in {"metre", "meter", "metres", "meters", "m"}:
        raise RasterContractError(
            f"Area calculations require metre units; source CRS units are {units!r}."
        )

    transform = profile["transform"]
    pixel_area_m2 = abs(transform.a * transform.e - transform.b * transform.d)
    if not np.isfinite(pixel_area_m2) or pixel_area_m2 <= 0:
        raise RasterContractError("Raster pixel area is invalid.")
    return float(pixel_area_m2)


def power_to_db(array: np.ndarray, units: str) -> np.ndarray:
    """Convert positive linear power to dB, or pass through explicitly declared dB."""
    if units == "db":
        return np.asarray(array, dtype=np.float64)
    if units != "linear":
        raise ValueError("units must be either 'linear' or 'db'.")

    result = np.full(array.shape, np.nan, dtype=np.float64)
    positive = np.isfinite(array) & (array > 0)
    result[positive] = 10.0 * np.log10(array[positive])
    return result


def write_mask(path: str | Path, mask: np.ndarray, valid: np.ndarray, profile: dict[str, Any]) -> None:
    """Write a binary UInt8 GeoTIFF: 1=class present, 0=class absent, 255=NoData."""
    output = np.full(mask.shape, 255, dtype=np.uint8)
    output[valid] = 0
    output[np.asarray(mask, dtype=bool) & valid] = 1

    out_profile = {
        key: profile[key]
        for key in ("driver", "height", "width", "transform", "crs")
        if key in profile
    }
    out_profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=255,
        compress="deflate",
        predictor=2,
        tiled=True,
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **out_profile) as dst:
        dst.write(output, 1)
        dst.set_band_description(1, "Binary RiverShift classification")


def write_mask_geojson(
    path: str | Path,
    mask: np.ndarray,
    valid: np.ndarray,
    profile: dict[str, Any],
    *,
    class_name: str,
) -> int:
    """Polygonize a binary mask and write GeoJSON in EPSG:4326."""
    src_crs = profile.get("crs")
    if src_crs is None:
        raise RasterContractError("Cannot polygonize a raster without a CRS.")

    features_out = []
    for geometry, value in shapes(
        np.asarray(mask, dtype=np.uint8),
        mask=np.asarray(valid, dtype=bool) & np.asarray(mask, dtype=bool),
        transform=profile["transform"],
    ):
        if int(value) != 1:
            continue
        wgs84_geometry = transform_geom(src_crs, "EPSG:4326", geometry, precision=7)
        features_out.append(
            {
                "type": "Feature",
                "properties": {"class": class_name},
                "geometry": wgs84_geometry,
            }
        )

    collection = {
        "type": "FeatureCollection",
        "name": class_name,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features_out,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(collection, indent=2), encoding="utf-8")
    return len(features_out)


def save_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def safe_float(value: float | np.floating[Any] | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gcov_source_provenance(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Flatten exact source-granule identities without mislabelling mosaic hashes."""
    observations = []
    granule_names: list[str] = []
    granule_hashes: list[str] = []
    for record in records:
        names = list(record.get("source_granule_names") or [record["source_granule_name"]])
        hashes = list(record.get("source_granule_sha256") or [record["source_product_sha256"]])
        if len(names) != len(hashes):
            raise RasterContractError("GCOV source granule names and checksums do not have matching lengths.")
        granule_names.extend(names)
        granule_hashes.extend(hashes)
        observations.append({
            "source_granule_names": names,
            "source_granule_sha256": hashes,
            "source_product_sha256": record["source_product_sha256"],
            "source_product_sha256_scope": record.get("source_product_sha256_scope", "single_granule"),
            "mosaic_method": record.get("mosaic_method"),
        })
    return {
        "granule_names": granule_names,
        "source_granule_sha256": granule_hashes,
        "observation_sources": observations,
    }


def read_gcov_sidecar(path: str | Path) -> dict[str, Any] | None:
    """Read the exporter provenance sidecar adjacent to a GCOV-derived raster."""
    raster_path = Path(path)
    sidecar = raster_path.with_suffix(".metadata.json")
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_gcov_series(
    paths: dict[str, str], *, maturity: str, frequency: str, term: str
) -> tuple[list[dict[str, Any]], bool]:
    """Fail closed on mixed GCOV provenance when exporter sidecars are present."""
    records = [read_gcov_sidecar(path) for path in paths.values()]
    if not any(records):
        return [], False
    if any(record is None for record in records):
        raise RasterContractError("Every GCOV input must have its exporter metadata sidecar when any sidecar is supplied.")

    required = (
        "source_granule_name", "source_product_sha256", "output_cog", "output_cog_sha256",
        "maturity", "frequency", "covariance_term",
        "bandwidth_mode", "polarization_code", "processing_type", "flight_direction", "relative_orbit",
        "frame", "crid", "orbit_accuracy", "frame_coverage", "observation_source",
    )
    normalized: list[dict[str, Any]] = []
    for input_path, record in zip(paths.values(), records):
        assert record is not None
        missing = [key for key in required if not record.get(key)]
        if missing:
            raise RasterContractError("GCOV metadata sidecar is incomplete: " + ", ".join(missing) + ".")
        for key in required:
            if not isinstance(record.get(key), str):
                raise RasterContractError(f"GCOV metadata sidecar field {key} must be text.")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", record["source_product_sha256"]):
            raise RasterContractError("GCOV metadata sidecar source_product_sha256 must be a 64-character SHA-256.")
        source_names = record.get("source_granule_names", [record["source_granule_name"]])
        source_hashes = record.get("source_granule_sha256", [record["source_product_sha256"]])
        if (
            not isinstance(source_names, list)
            or not source_names
            or not all(isinstance(name, str) and name for name in source_names)
            or not isinstance(source_hashes, list)
            or len(source_hashes) != len(source_names)
            or not all(isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest) for digest in source_hashes)
            or record["source_granule_name"] != "+".join(source_names)
        ):
            raise RasterContractError("GCOV metadata sidecar must preserve matching source granule names and individual SHA-256 values.")
        record["source_granule_names"] = source_names
        record["source_granule_sha256"] = source_hashes
        if not re.fullmatch(r"[0-9a-fA-F]{64}", record["output_cog_sha256"]):
            raise RasterContractError("GCOV metadata sidecar output_cog_sha256 must be a 64-character SHA-256.")
        raster_path = Path(input_path).resolve()
        if Path(record["output_cog"]).resolve() != raster_path:
            raise RasterContractError("GCOV input path does not match its metadata sidecar output_cog.")
        if sha256_file(raster_path).lower() != record["output_cog_sha256"].lower():
            raise RasterContractError("GCOV raster does not match its metadata sidecar output_cog_sha256.")
        if record["maturity"].upper() != maturity.upper():
            raise RasterContractError("GCOV maturity does not match the requested analysis maturity.")
        if record["frequency"] != frequency or record["covariance_term"] != term:
            raise RasterContractError("GCOV frequency/diagonal term does not match the requested analysis layer.")
        normalized.append(record)

    comparison_fields = (
        "maturity", "frequency", "covariance_term", "bandwidth_mode", "polarization_code", "processing_type",
        "flight_direction", "relative_orbit", "frame", "crid", "orbit_accuracy", "frame_coverage", "observation_source",
    )
    for field in comparison_fields:
        if len({str(record[field]).upper() for record in normalized}) != 1:
            raise RasterContractError(f"GCOV inputs do not share the same {field}; do not compare this stack.")
    return normalized, True
