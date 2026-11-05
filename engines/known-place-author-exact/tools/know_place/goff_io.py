"""Strict raw NISAR L2 GOFF IO for isolated Know Place Analysis.

This module does not call SARGuardian's current reader/exporter: those outputs
already include auto-reference, deramping, filtering and cropping, which are not
inputs to the paper-equivalent calculation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any

import h5py
import numpy as np

from .paper_method import ScientificInputError

PRODUCT_PREFIX = "/science/LSAR/GOFF/grids/frequencyA/pixelOffsets"
METADATA_PREFIX = "science/LSAR/GOFF/metadata/"
GEOMETRY_FIELDS = (
    "incidenceAngle",
    "losUnitVectorX",
    "losUnitVectorY",
    "alongTrackUnitVectorX",
    "alongTrackUnitVectorY",
)
TIMESTAMP_RE = re.compile(r"(\d{8}T\d{6})")
PRODUCT_RE = re.compile(
    r"^NISAR_L2_(?P<processing>PR|UR|OD)_GOFF_(?P<frame>\d{3})_"
    r"(?P<track>\d{3})_(?P<direction>[AD])_"
)


class GoffReadError(ScientificInputError):
    """A raw GOFF product fails strict schema, identity, or geometry checks."""


@dataclass(frozen=True)
class GoffIdentity:
    granule_name: str
    processing: str
    frame: str
    track: str
    direction: str
    reference_start: datetime
    reference_end: datetime
    secondary_start: datetime
    secondary_end: datetime
    release_id: str | None


@dataclass(frozen=True)
class GoffGridInfo:
    path: str
    identity: GoffIdentity
    polarization: str
    layer: str
    x_coordinates_m: np.ndarray
    y_coordinates_m: np.ndarray
    epsg: int
    grid_shape: tuple[int, int]
    file_size_bytes: int
    file_mtime_ns: int
    unit_evidence: dict[str, str]


@dataclass(frozen=True)
class RawGoffProduct:
    identity: GoffIdentity
    polarization: str
    layer: str
    along_track_m: np.ndarray
    slant_range_m: np.ndarray
    snr: np.ndarray
    correlation: np.ndarray
    x_coordinates_m: np.ndarray
    y_coordinates_m: np.ndarray
    epsg: int
    source_sha256: str
    dataset_paths: dict[str, str]
    unit_evidence: dict[str, str]
    fill_evidence: dict[str, list[float | str]]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class GeometryCubes:
    group_path: str
    height_m: np.ndarray
    y_m: np.ndarray
    x_m: np.ndarray
    incidence_deg: np.ndarray
    los_x: np.ndarray
    los_y: np.ndarray
    along_track_x: np.ndarray
    along_track_y: np.ndarray
    source_paths: dict[str, str]
    unit_evidence: dict[str, str]
    metadata_epsg: int


@dataclass(frozen=True)
class GeometrySample:
    incidence_deg: np.ndarray
    los_x: np.ndarray
    los_y: np.ndarray
    along_track_x: np.ndarray
    along_track_y: np.ndarray
    metadata_group: str


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict").strip()
    if isinstance(value, np.ndarray) and value.size == 1:
        return _text(value.reshape(-1)[0])
    return str(value).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_dataset(handle: h5py.File, path: str) -> h5py.Dataset:
    if path not in handle:
        raise GoffReadError(f"REQUIRED_GOFF_DATASET_MISSING:{path}")
    item = handle[path]
    if not isinstance(item, h5py.Dataset):
        raise GoffReadError(f"REQUIRED_GOFF_PATH_NOT_DATASET:{path}")
    return item


def _array_units(dataset: h5py.Dataset) -> str | None:
    raw = dataset.attrs.get("units")
    if raw is None:
        return None
    return _text(raw).lower().replace(" ", "")


def _read_float_dataset_masking_declared_fill(
    dataset: h5py.Dataset, selection: tuple[slice, slice] | None = None,
) -> tuple[np.ndarray, list[float | str]]:
    """Mask only declared HDF5 fill sentinels, including user-defined creation fill."""
    values = np.asarray(dataset[()] if selection is None else dataset[selection], dtype=np.float64)
    markers: list[float | str] = []

    def apply_marker(raw_value: Any, source: str) -> None:
        try:
            marker = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            raise GoffReadError(f"NONNUMERIC_FILL_MARKER:{dataset.name}:{source}") from None
        if np.isnan(marker):
            label: float | str = "NaN"
            values[np.isnan(values)] = np.nan
        elif not np.isfinite(marker):
            label = "Infinity" if marker > 0 else "-Infinity"
            values[values == marker] = np.nan
        else:
            label = marker
            values[values == marker] = np.nan
        if label not in markers:
            markers.append(label)

    for attribute in ("_FillValue", "missing_value", "fill_value", "noDataValue"):
        if attribute not in dataset.attrs:
            continue
        raw = np.asarray(dataset.attrs[attribute]).reshape(-1)
        for item in raw:
            apply_marker(item, attribute)

    # HDF5 can define a dataset's fill value in its creation property list
    # without copying the same value into a conventional attribute. Only mask
    # it when HDF5 explicitly marks it USER_DEFINED: h5py otherwise exposes a
    # default zero fill value, and zero can be a physically valid offset.
    try:
        creation_status = dataset.id.get_create_plist().fill_value_defined()
        user_defined_status = h5py.h5d.FILL_VALUE_USER_DEFINED
    except (AttributeError, RuntimeError):
        creation_status = None
        user_defined_status = object()
    if creation_status == user_defined_status:
        apply_marker(dataset.fillvalue, "HDF5_creation_property_list")
    return values, markers


def _coordinate_units_evidence(dataset: h5py.Dataset, field: str) -> str:
    units = _array_units(dataset)
    metre_units = {"m", "meter", "meters", "metre", "metres"}
    if units is not None and units not in metre_units:
        raise GoffReadError(f"COORDINATE_UNIT_MISMATCH:{dataset.name}:{units}")
    if units is not None:
        return f"dataset_attribute:{units}"
    return f"NISAR_L2_GOFF_grid_specification:projected_metres:{field}"


def _offset_units_evidence(dataset: h5py.Dataset, field: str) -> str:
    unit = _array_units(dataset)
    metre_units = {"m", "meter", "meters", "metre", "metres"}
    if unit is not None:
        if unit not in metre_units:
            raise GoffReadError(
                f"OFFSET_UNIT_MISMATCH:{dataset.name}:expected_metres:actual={unit}"
            )
        return f"dataset_attribute:{unit}"
    # NISAR L2 GOFF product specification defines AT/SR offsets in metres.
    # This is an explicit schema contract, not a magnitude-based unit guess.
    return "NISAR_L2_GOFF_product_specification:metres"


def parse_granule_identity(path_or_name: str | Path) -> GoffIdentity:
    """Parse acquisition and geometry identity from an official granule name."""
    name = Path(path_or_name).name
    if not name.lower().endswith(".h5"):
        raise GoffReadError(f"GOFF_FILENAME_EXTENSION_INVALID:{name}")
    stem = name[:-3]
    match = PRODUCT_RE.match(stem)
    if not match:
        raise GoffReadError(f"GOFF_GRANULE_NAME_PATTERN_INVALID:{name}")
    stamps = TIMESTAMP_RE.findall(stem)
    if len(stamps) != 4:
        raise GoffReadError(f"GOFF_EXPECTED_FOUR_ACQUISITION_TIMESTAMPS:{name}")
    try:
        parsed = [datetime.strptime(stamp, "%Y%m%dT%H%M%S") for stamp in stamps]
    except ValueError as exc:
        raise GoffReadError(f"GOFF_ACQUISITION_TIMESTAMP_INVALID:{name}:{exc}") from exc
    if parsed[0] > parsed[1] or parsed[2] > parsed[3]:
        raise GoffReadError(f"GOFF_ACQUISITION_INTERVAL_ORDER_INVALID:{name}")
    if parsed[0] >= parsed[2]:
        raise GoffReadError(f"GOFF_REFERENCE_MUST_PRECEDE_SECONDARY:{name}")
    crids = re.findall(r"(?<![A-Z0-9])[PX]\d{5}(?![A-Z0-9])", stem)
    if len(crids) > 1:
        raise GoffReadError(f"GOFF_MULTIPLE_RELEASE_IDS:{name}:{crids}")
    return GoffIdentity(
        granule_name=name,
        processing=match.group("processing"),
        frame=match.group("frame"),
        track=match.group("track"),
        direction=match.group("direction"),
        reference_start=parsed[0],
        reference_end=parsed[1],
        secondary_start=parsed[2],
        secondary_end=parsed[3],
        release_id=crids[0] if crids else None,
    )


def _epsg_from_projection(dataset: h5py.Dataset) -> int:
    candidate = dataset.attrs.get("epsg_code")
    if candidate is None:
        scalar = np.asarray(dataset[()])
        if scalar.size != 1:
            raise GoffReadError(f"PROJECTION_EPSG_UNRESOLVED:{dataset.name}")
        candidate = scalar.reshape(-1)[0]
    try:
        epsg = int(candidate)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GoffReadError(f"PROJECTION_EPSG_INVALID:{dataset.name}") from exc
    if epsg <= 0:
        raise GoffReadError(f"PROJECTION_EPSG_INVALID:{dataset.name}:{epsg}")
    return epsg


def _validate_coordinate_axis(values: np.ndarray, name: str) -> np.ndarray:
    axis = np.asarray(values, dtype=float)
    if axis.ndim != 1 or axis.size < 2 or not np.isfinite(axis).all():
        raise GoffReadError(f"COORDINATE_AXIS_INVALID:{name}")
    delta = np.diff(axis)
    if not (np.all(delta > 0) or np.all(delta < 0)):
        raise GoffReadError(f"COORDINATE_AXIS_NOT_STRICTLY_MONOTONIC:{name}")
    return axis


def _goff_dataset_paths(polarization: str, layer: int) -> dict[str, str]:
    base = f"{PRODUCT_PREFIX}/{polarization}/layer{layer}"
    names = {
        "along_track": "alongTrackOffset",
        "slant_range": "slantRangeOffset",
        "snr": "snr",
        "correlation": "correlationSurfacePeak",
        "x": "xCoordinates",
        "y": "yCoordinates",
        "projection": "projection",
    }
    return {key: f"{base}/{value}" for key, value in names.items()}


def _validate_granule_request(
    source: Path,
    polarization: str,
    layer: int,
    expected_track: str | None,
    expected_direction: str | None,
    expected_processing: str,
) -> tuple[GoffIdentity, str]:
    identity = parse_granule_identity(source)
    pol = polarization.strip().upper()
    if pol not in {"HH", "HV", "VH", "VV"}:
        raise GoffReadError(f"POLARIZATION_UNSUPPORTED:{polarization}")
    if layer != 2:
        raise GoffReadError("PAPER_METHOD_REQUIRES_GOFF_LAYER2")
    if identity.processing != expected_processing:
        raise GoffReadError(
            f"GOFF_PROCESSING_MISMATCH:expected={expected_processing}:actual={identity.processing}"
        )
    if expected_track is not None and identity.track != str(expected_track).zfill(3):
        raise GoffReadError(
            f"GOFF_TRACK_MISMATCH:expected={str(expected_track).zfill(3)}:actual={identity.track}"
        )
    if expected_direction is not None and identity.direction != expected_direction.upper():
        raise GoffReadError(
            f"GOFF_DIRECTION_MISMATCH:expected={expected_direction}:actual={identity.direction}"
        )
    return identity, pol


def inspect_goff_grid(
    path: str | Path,
    *,
    polarization: str = "HH",
    layer: int = 2,
    expected_track: str | None = None,
    expected_direction: str | None = None,
    expected_processing: str = "PR",
) -> GoffGridInfo:
    """Read only granule identity, grid axes and schema; do not load full pixel layers."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise GoffReadError(f"GOFF_SOURCE_FILE_NOT_FOUND:{source}")
    identity, pol = _validate_granule_request(
        source, polarization, layer, expected_track, expected_direction, expected_processing
    )
    data_paths = _goff_dataset_paths(pol, layer)
    unit_evidence: dict[str, str] = {}
    with h5py.File(source, "r") as handle:
        datasets = {key: _require_dataset(handle, value) for key, value in data_paths.items()}
        full_shape = datasets["along_track"].shape
        if len(full_shape) != 2:
            raise GoffReadError(f"GOFF_MEASUREMENT_NOT_2D:{datasets['along_track'].name}:{full_shape}")
        for key in ("slant_range", "snr", "correlation"):
            if datasets[key].shape != full_shape:
                raise GoffReadError(
                    f"GOFF_MEASUREMENT_SHAPE_MISMATCH:{key}:{datasets[key].shape}:expected={full_shape}"
                )
        for key in ("along_track", "slant_range"):
            unit_evidence[key] = _offset_units_evidence(datasets[key], key)
        for key in ("snr", "correlation"):
            units = _array_units(datasets[key])
            if units not in (None, "1", "unitless", "dimensionless"):
                raise GoffReadError(f"GOFF_QUALITY_LAYER_UNIT_MISMATCH:{key}:{units}")
            unit_evidence[key] = (
                f"dataset_attribute:{units}" if units is not None
                else f"NISAR_L2_GOFF_product_specification:dimensionless:{key}"
            )
        x = _validate_coordinate_axis(np.asarray(datasets["x"][()], dtype=float), datasets["x"].name)
        y = _validate_coordinate_axis(np.asarray(datasets["y"][()], dtype=float), datasets["y"].name)
        if len(x) != full_shape[1] or len(y) != full_shape[0]:
            raise GoffReadError(
                f"GOFF_COORDINATE_SHAPE_MISMATCH:grid={full_shape}:x={len(x)}:y={len(y)}"
            )
        epsg = _epsg_from_projection(datasets["projection"])
        unit_evidence["x_coordinates"] = _coordinate_units_evidence(datasets["x"], "x")
        unit_evidence["y_coordinates"] = _coordinate_units_evidence(datasets["y"], "y")
    stat = source.stat()
    return GoffGridInfo(
        path=str(source),
        identity=identity,
        polarization=pol,
        layer=f"layer{layer}",
        x_coordinates_m=x,
        y_coordinates_m=y,
        epsg=epsg,
        grid_shape=(int(full_shape[0]), int(full_shape[1])),
        file_size_bytes=stat.st_size,
        file_mtime_ns=stat.st_mtime_ns,
        unit_evidence=unit_evidence,
    )


def _validate_window(
    window_slices: tuple[slice, slice] | None,
    shape: tuple[int, int],
) -> tuple[slice, slice]:
    if window_slices is None:
        return slice(0, shape[0]), slice(0, shape[1])
    if len(window_slices) != 2:
        raise GoffReadError("GOFF_WINDOW_MUST_HAVE_ROW_AND_COLUMN_SLICE")
    out = []
    for label, item, limit in zip(("row", "column"), window_slices, shape):
        if not isinstance(item, slice) or item.step not in (None, 1):
            raise GoffReadError(f"GOFF_WINDOW_SLICE_INVALID:{label}")
        start = 0 if item.start is None else item.start
        stop = limit if item.stop is None else item.stop
        if (not isinstance(start, int) or not isinstance(stop, int)
                or start < 0 or stop > limit or stop <= start):
            raise GoffReadError(f"GOFF_WINDOW_SLICE_OUT_OF_RANGE:{label}:{start}:{stop}:{limit}")
        out.append(slice(start, stop))
    return out[0], out[1]


def read_raw_goff(
    path: str | Path,
    *,
    polarization: str = "HH",
    layer: int = 2,
    expected_track: str | None = None,
    expected_direction: str | None = None,
    expected_processing: str = "PR",
    window_slices: tuple[slice, slice] | None = None,
    expected_grid: GoffGridInfo | None = None,
) -> RawGoffProduct:
    """Load raw GOFF arrays, optionally reading a bounded ROI directly from HDF5."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise GoffReadError(f"GOFF_SOURCE_FILE_NOT_FOUND:{source}")
    identity, pol = _validate_granule_request(
        source, polarization, layer, expected_track, expected_direction, expected_processing
    )
    stat_before = source.stat()
    if expected_grid is not None:
        if str(source) != expected_grid.path:
            raise GoffReadError("GOFF_INSPECTED_PATH_CHANGED")
        if (stat_before.st_size, stat_before.st_mtime_ns) != (
            expected_grid.file_size_bytes, expected_grid.file_mtime_ns
        ):
            raise GoffReadError("GOFF_SOURCE_FILE_CHANGED_AFTER_GRID_INSPECTION")
    data_paths = _goff_dataset_paths(pol, layer)
    fields: dict[str, np.ndarray] = {}
    unit_evidence: dict[str, str] = {}
    fill_evidence: dict[str, list[float | str]] = {}
    with h5py.File(source, "r") as handle:
        datasets = {key: _require_dataset(handle, value) for key, value in data_paths.items()}
        full_shape = datasets["along_track"].shape
        if len(full_shape) != 2:
            raise GoffReadError(f"GOFF_MEASUREMENT_NOT_2D:{datasets['along_track'].name}:{full_shape}")
        for key in ("slant_range", "snr", "correlation"):
            if datasets[key].shape != full_shape:
                raise GoffReadError(
                    f"GOFF_MEASUREMENT_SHAPE_MISMATCH:{key}:{datasets[key].shape}:expected={full_shape}"
                )
        rows, cols = _validate_window(window_slices, (int(full_shape[0]), int(full_shape[1])))
        selection = (rows, cols)
        for key in ("along_track", "slant_range", "snr", "correlation"):
            fields[key], fill_evidence[key] = _read_float_dataset_masking_declared_fill(
                datasets[key], selection=selection
            )
        x_full = _validate_coordinate_axis(
            np.asarray(datasets["x"][()], dtype=float), datasets["x"].name
        )
        y_full = _validate_coordinate_axis(
            np.asarray(datasets["y"][()], dtype=float), datasets["y"].name
        )
        if len(x_full) != full_shape[1] or len(y_full) != full_shape[0]:
            raise GoffReadError(
                f"GOFF_COORDINATE_SHAPE_MISMATCH:grid={full_shape}:x={len(x_full)}:y={len(y_full)}"
            )
        epsg = _epsg_from_projection(datasets["projection"])
        unit_evidence["along_track"] = _offset_units_evidence(datasets["along_track"], "along_track")
        unit_evidence["slant_range"] = _offset_units_evidence(datasets["slant_range"], "slant_range")
        for key in ("snr", "correlation"):
            units = _array_units(datasets[key])
            if units not in (None, "1", "unitless", "dimensionless"):
                raise GoffReadError(f"GOFF_QUALITY_LAYER_UNIT_MISMATCH:{key}:{units}")
            unit_evidence[key] = (
                f"dataset_attribute:{units}" if units is not None
                else f"NISAR_L2_GOFF_product_specification:dimensionless:{key}"
            )
        unit_evidence["x_coordinates"] = _coordinate_units_evidence(datasets["x"], "x")
        unit_evidence["y_coordinates"] = _coordinate_units_evidence(datasets["y"], "y")
        for key in ("along_track", "slant_range", "snr", "correlation"):
            grid_mapping = datasets[key].attrs.get("grid_mapping")
            if grid_mapping is not None and _text(grid_mapping) != "projection":
                raise GoffReadError(
                    f"GOFF_GRID_MAPPING_CONFLICT:{datasets[key].name}:{_text(grid_mapping)}"
                )
        field_paths = {key: datasets[key].name for key in data_paths}

    x = x_full[cols]
    y = y_full[rows]
    for key in ("along_track", "slant_range", "snr", "correlation"):
        if fields[key].shape != (len(y), len(x)):
            raise GoffReadError(f"GOFF_WINDOW_ARRAY_SHAPE_MISMATCH:{key}:{fields[key].shape}")
    digest = _sha256(source)
    stat_after = source.stat()
    if (stat_before.st_size, stat_before.st_mtime_ns) != (stat_after.st_size, stat_after.st_mtime_ns):
        raise GoffReadError("GOFF_SOURCE_FILE_CHANGED_DURING_READ_OR_HASH")
    if expected_grid is not None:
        if epsg != expected_grid.epsg:
            raise GoffReadError("GOFF_EPSG_CHANGED_AFTER_GRID_INSPECTION")
        if not np.array_equal(x_full, expected_grid.x_coordinates_m) or not np.array_equal(
            y_full, expected_grid.y_coordinates_m
        ):
            raise GoffReadError("GOFF_GRID_COORDINATES_CHANGED_AFTER_INSPECTION")
    return RawGoffProduct(
        identity=identity,
        polarization=pol,
        layer=f"layer{layer}",
        along_track_m=fields["along_track"],
        slant_range_m=fields["slant_range"],
        snr=fields["snr"],
        correlation=fields["correlation"],
        x_coordinates_m=x,
        y_coordinates_m=y,
        epsg=epsg,
        source_sha256=digest,
        dataset_paths=field_paths,
        unit_evidence=unit_evidence,
        fill_evidence=fill_evidence,
        metadata={
            "source_path_name_only": source.name,
            "raw_data_only": True,
            "correction_applied": False,
            "quality_filter_applied": False,
            "aoi_clip_applied": False,
            "original_grid_shape": list(full_shape),
            "read_window": {
                "row_start": rows.start, "row_stop": rows.stop,
                "column_start": cols.start, "column_stop": cols.stop,
            },
            "release_id": identity.release_id,
            "reference_date": identity.reference_start.date().isoformat(),
            "secondary_date": identity.secondary_start.date().isoformat(),
        },
    )


def _incidence_to_degrees(dataset: h5py.Dataset, values: np.ndarray) -> tuple[np.ndarray, str]:
    units = _array_units(dataset)
    if units in {"degree", "degrees", "deg"}:
        result = values.astype(float, copy=False)
        evidence = f"dataset_attribute:{units}"
    elif units in {"rad", "radian", "radians"}:
        result = np.rad2deg(values)
        evidence = f"dataset_attribute:{units}->degrees"
    else:
        raise GoffReadError(
            f"INCIDENCE_ANGLE_UNIT_MISSING_OR_UNSUPPORTED:{dataset.name}:units={units}"
        )
    finite = result[np.isfinite(result)]
    if finite.size == 0 or np.any((finite <= 0) | (finite >= 90)):
        raise GoffReadError(f"INCIDENCE_ANGLE_VALUES_OUT_OF_RANGE:{dataset.name}")
    return result, evidence


def _geometry_units_evidence(dataset: h5py.Dataset) -> str:
    units = _array_units(dataset)
    if units is None:
        return "NISAR_metadata_product_specification:dimensionless_unit_vector"
    if units not in {"1", "unitless", "dimensionless"}:
        raise GoffReadError(f"GEOMETRY_VECTOR_UNIT_MISMATCH:{dataset.name}:{units}")
    return f"dataset_attribute:{units}"


def read_geometry_cubes(path: str | Path, *, expected_epsg: int) -> GeometryCubes:
    """Find one complete metadata cube group; reject mixed or ambiguous groups.

    The selected group must contain all geometry parameter cubes and the exact
    x/y/height axes. Cubes use HAE, y, x order. Dataset names are matched exactly.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise GoffReadError(f"GOFF_SOURCE_FILE_NOT_FOUND:{source}")
    required = set(GEOMETRY_FIELDS) | {"xCoordinates", "yCoordinates", "heightAboveEllipsoid"}
    candidates: set[str] = set()
    with h5py.File(source, "r") as handle:
        def visit(name: str, obj: Any) -> None:
            if isinstance(obj, h5py.Dataset) and name.startswith(METADATA_PREFIX):
                if name.rsplit("/", 1)[-1] in required:
                    candidates.add(name.rsplit("/", 1)[0])
        handle.visititems(visit)

        complete: list[str] = []
        reasons: list[str] = []
        for group in sorted(candidates):
            if not all(f"{group}/{name}" in handle for name in required):
                continue
            axes = {
                "x": np.asarray(handle[f"{group}/xCoordinates"][()], dtype=float),
                "y": np.asarray(handle[f"{group}/yCoordinates"][()], dtype=float),
                "height": np.asarray(handle[f"{group}/heightAboveEllipsoid"][()], dtype=float),
            }
            try:
                for axis_name, axis_values in axes.items():
                    _validate_coordinate_axis(axis_values, f"{group}/{axis_name}")
                expected_shape = (len(axes["height"]), len(axes["y"]), len(axes["x"]))
            except GoffReadError as exc:
                reasons.append(str(exc))
                continue
            shape_ok = all(
                isinstance(handle[f"{group}/{field}"], h5py.Dataset)
                and handle[f"{group}/{field}"].ndim == 3
                and handle[f"{group}/{field}"].shape == expected_shape
                for field in GEOMETRY_FIELDS
            )
            if shape_ok:
                complete.append(group)
            else:
                reasons.append(f"GEOMETRY_CUBE_SHAPE_MISMATCH:{group}:expected={expected_shape}")

        if len(complete) != 1:
            detail = ";".join(reasons[:8])
            if not complete:
                raise GoffReadError(f"GOFF_GEOMETRY_CUBE_NOT_FOUND_OR_INVALID:{detail}")
            raise GoffReadError(f"GOFF_GEOMETRY_CUBE_AMBIGUOUS:{complete}")

        group = complete[0]
        projection_path = f"{group}/projection"
        if projection_path not in handle:
            raise GoffReadError(f"GEOMETRY_CRS_EVIDENCE_MISSING:{group}")
        metadata_epsg = _epsg_from_projection(handle[projection_path])
        if metadata_epsg != int(expected_epsg):
            raise GoffReadError(
                f"GEOMETRY_CRS_MISMATCH:offset_epsg={int(expected_epsg)}:metadata_epsg={metadata_epsg}"
            )
        x = _validate_coordinate_axis(
            np.asarray(handle[f"{group}/xCoordinates"][()], dtype=float),
            f"{group}/xCoordinates",
        )
        y = _validate_coordinate_axis(
            np.asarray(handle[f"{group}/yCoordinates"][()], dtype=float),
            f"{group}/yCoordinates",
        )
        height = _validate_coordinate_axis(
            np.asarray(handle[f"{group}/heightAboveEllipsoid"][()], dtype=float),
            f"{group}/heightAboveEllipsoid",
        )
        cubes: dict[str, np.ndarray] = {}
        paths: dict[str, str] = {}
        evidence: dict[str, str] = {}
        for field in GEOMETRY_FIELDS:
            dataset = handle[f"{group}/{field}"]
            cube = np.asarray(dataset[()], dtype=float)
            if not np.isfinite(cube).any():
                raise GoffReadError(f"GEOMETRY_CUBE_ALL_NONFINITE:{dataset.name}")
            if field == "incidenceAngle":
                cube, evidence[field] = _incidence_to_degrees(dataset, cube)
            else:
                evidence[field] = _geometry_units_evidence(dataset)
            cubes[field] = cube
            paths[field] = dataset.name

        # Normalize descending axes and flip every cube along its matching axis.
        if np.all(np.diff(x) < 0):
            x = x[::-1].copy()
            cubes = {key: np.flip(value, axis=2) for key, value in cubes.items()}
        if np.all(np.diff(y) < 0):
            y = y[::-1].copy()
            cubes = {key: np.flip(value, axis=1) for key, value in cubes.items()}
        if np.all(np.diff(height) < 0):
            height = height[::-1].copy()
            cubes = {key: np.flip(value, axis=0) for key, value in cubes.items()}

    return GeometryCubes(
        group_path=group,
        height_m=height,
        y_m=y,
        x_m=x,
        incidence_deg=cubes["incidenceAngle"],
        los_x=cubes["losUnitVectorX"],
        los_y=cubes["losUnitVectorY"],
        along_track_x=cubes["alongTrackUnitVectorX"],
        along_track_y=cubes["alongTrackUnitVectorY"],
        source_paths=paths,
        unit_evidence=evidence,
        metadata_epsg=metadata_epsg,
    )


def sample_geometry(
    cubes: GeometryCubes,
    *,
    x_m: Any,
    y_m: Any,
    height_m: Any,
    expected_epsg: int,
) -> GeometrySample:
    """Interpolate geometry at projected grid points and HAE elevation(s).

    height_m may be one scalar or a per-pixel array matching x_m/y_m. The array
    form permits DEM-derived terrain heights instead of a constant-height
    approximation. No out-of-domain extrapolation is permitted. x/y must use
    the GOFF grid CRS; the caller is responsible for verifying its EPSG.
    """
    try:
        from scipy.interpolate import RegularGridInterpolator
    except ImportError as exc:
        raise GoffReadError("SCIPY_REQUIRED_FOR_GEOMETRY_CUBE_INTERPOLATION") from exc
    if cubes.metadata_epsg != int(expected_epsg):
        raise GoffReadError(
            f"GEOMETRY_CRS_MISMATCH:expected={int(expected_epsg)}:metadata_epsg={cubes.metadata_epsg}"
        )
    xq, yq = np.asarray(x_m, float), np.asarray(y_m, float)
    if xq.shape != yq.shape:
        raise GoffReadError("GEOMETRY_QUERY_XY_SHAPE_MISMATCH")
    hq = np.asarray(height_m, dtype=float)
    if hq.ndim == 0:
        if not np.isfinite(float(hq)):
            raise GoffReadError("GEOMETRY_QUERY_HEIGHT_NONFINITE")
        hq = np.full(xq.shape, float(hq), dtype=float)
    elif hq.shape != xq.shape:
        raise GoffReadError("GEOMETRY_QUERY_HEIGHT_SHAPE_MISMATCH")
    if not np.isfinite(hq).all():
        raise GoffReadError("GEOMETRY_QUERY_HEIGHT_NONFINITE")
    if np.any((hq < cubes.height_m[0]) | (hq > cubes.height_m[-1])):
        low = float(np.min(hq))
        high = float(np.max(hq))
        raise GoffReadError(
            f"GEOMETRY_HEIGHT_OUTSIDE_METADATA_AXIS:{low}..{high}:"
            f"{cubes.height_m[0]}..{cubes.height_m[-1]}"
        )
    if not np.isfinite(xq).all() or not np.isfinite(yq).all():
        raise GoffReadError("GEOMETRY_QUERY_XY_NONFINITE")
    if np.any((xq < cubes.x_m[0]) | (xq > cubes.x_m[-1])):
        raise GoffReadError("GEOMETRY_QUERY_X_OUTSIDE_METADATA_AXIS")
    if np.any((yq < cubes.y_m[0]) | (yq > cubes.y_m[-1])):
        raise GoffReadError("GEOMETRY_QUERY_Y_OUTSIDE_METADATA_AXIS")
    points = np.column_stack(
        [hq.reshape(-1), yq.reshape(-1), xq.reshape(-1)]
    )
    def evaluate(cube: np.ndarray) -> np.ndarray:
        interpolator = RegularGridInterpolator(
            (cubes.height_m, cubes.y_m, cubes.x_m),
            cube,
            method="linear",
            bounds_error=True,
            fill_value=np.nan,
        )
        values = np.asarray(interpolator(points), dtype=float).reshape(xq.shape)
        if not np.isfinite(values).all():
            raise GoffReadError("GEOMETRY_INTERPOLATION_NONFINITE_RESULT")
        return values

    return GeometrySample(
        incidence_deg=evaluate(cubes.incidence_deg),
        los_x=evaluate(cubes.los_x),
        los_y=evaluate(cubes.los_y),
        along_track_x=evaluate(cubes.along_track_x),
        along_track_y=evaluate(cubes.along_track_y),
        metadata_group=cubes.group_path,
    )
