from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from tools.know_place.goff_io import (
    GoffReadError,
    parse_granule_identity,
    inspect_goff_grid,
    read_geometry_cubes,
    read_raw_goff,
    sample_geometry,
)

TARGET_NAME = (
    "NISAR_L2_PR_GOFF_014_098_A_016_023_4000_SH_"
    "20260726T000000_20260726T000030_20260819T000000_"
    "20260819T000030_P05023_N_F_J_001.h5"
)
BASE = "/science/LSAR/GOFF"
FIELDS = {
    "incidenceAngle": 39.1,
    "losUnitVectorX": 0.2,
    "losUnitVectorY": -0.3,
    "alongTrackUnitVectorX": 0.9,
    "alongTrackUnitVectorY": 0.4,
}


def write_synthetic_goff(path: Path, *, add_duplicate_geometry=False):
    with h5py.File(path, "w") as h:
        layer = h.create_group(
            "science/LSAR/GOFF/grids/frequencyA/pixelOffsets/HH/layer2"
        )
        data = np.arange(20, dtype=np.float32).reshape(4, 5) / 100
        for field in ("alongTrackOffset", "slantRangeOffset"):
            ds = layer.create_dataset(field, data=data)
            ds.attrs["units"] = "m"
            ds.attrs["grid_mapping"] = "projection"
        snr = layer.create_dataset("snr", data=np.full((4, 5), 6.0, dtype=np.float32))
        snr.attrs["units"] = "1"
        corr = layer.create_dataset(
            "correlationSurfacePeak", data=np.full((4, 5), 0.8, dtype=np.float32)
        )
        corr.attrs["units"] = "1"
        layer.create_dataset("xCoordinates", data=np.arange(5, dtype=np.float64) + 100.0)
        layer.create_dataset("yCoordinates", data=np.arange(4, dtype=np.float64) + 200.0)
        projection = layer.create_dataset("projection", data=np.int32(32645))
        projection.attrs["epsg_code"] = 32645

        def geometry(group_name):
            group = h.create_group(f"{BASE}/metadata/{group_name}")
            group.create_dataset("xCoordinates", data=np.array([100.0, 200.0, 300.0]))
            group.create_dataset("yCoordinates", data=np.array([200.0, 300.0, 400.0]))
            group.create_dataset("heightAboveEllipsoid", data=np.array([5000.0, 6000.0]))
            for name, value in FIELDS.items():
                ds = group.create_dataset(name, data=np.full((2, 3, 3), value, np.float32))
                ds.attrs["units"] = "degrees" if name == "incidenceAngle" else "1"
            projection = group.create_dataset("projection", data=np.int32(32645))
            projection.attrs["epsg_code"] = 32645

        geometry("radarGrid")
        if add_duplicate_geometry:
            geometry("geolocationGrid")


def test_parse_granule_identity_gets_exact_pair_and_track():
    identity = parse_granule_identity(TARGET_NAME)
    assert identity.track == "098"
    assert identity.direction == "A"
    assert identity.processing == "PR"
    assert identity.reference_start.date().isoformat() == "2026-07-26"
    assert identity.secondary_start.date().isoformat() == "2026-08-19"
    assert identity.release_id == "P05023"


def test_raw_reader_preserves_unmodified_arrays_and_verifiable_provenance(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    product = read_raw_goff(path, expected_track="098", expected_direction="A")
    assert product.along_track_m.shape == (4, 5)
    assert product.slant_range_m[0, 1] == pytest.approx(0.01)
    assert product.snr.min() == pytest.approx(6.0)
    assert product.correlation.min() == pytest.approx(0.8)
    assert product.epsg == 32645
    assert len(product.source_sha256) == 64
    assert product.metadata["correction_applied"] is False
    assert product.metadata["quality_filter_applied"] is False
    assert product.metadata["aoi_clip_applied"] is False


def test_raw_reader_fails_closed_on_track_mismatch(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    with pytest.raises(GoffReadError, match="GOFF_TRACK_MISMATCH"):
        read_raw_goff(path, expected_track="048")


def test_raw_reader_fails_if_required_source_layer_is_absent(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    with h5py.File(path, "a") as h:
        del h[f"{BASE}/grids/frequencyA/pixelOffsets/HH/layer2/snr"]
    with pytest.raises(GoffReadError, match="REQUIRED_GOFF_DATASET_MISSING"):
        read_raw_goff(path)


def test_geometry_reader_and_interpolator_use_same_exact_cube_group(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    cubes = read_geometry_cubes(path, expected_epsg=32645)
    sample = sample_geometry(cubes, x_m=np.array([[150.0, 250.0]]),
                             y_m=np.array([[250.0, 350.0]]), height_m=5151.0,
                             expected_epsg=32645)
    assert cubes.group_path.endswith("/metadata/radarGrid")
    assert np.allclose(sample.incidence_deg, [[39.1, 39.1]])
    assert np.allclose(sample.los_x, [[0.2, 0.2]])
    assert np.allclose(sample.los_y, [[-0.3, -0.3]])
    assert np.allclose(sample.along_track_x, [[0.9, 0.9]])


def test_geometry_reader_fails_on_ambiguous_metadata_groups(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path, add_duplicate_geometry=True)
    with pytest.raises(GoffReadError, match="GOFF_GEOMETRY_CUBE_AMBIGUOUS"):
        read_geometry_cubes(path, expected_epsg=32645)


def test_geometry_reader_fails_when_incidence_units_are_unknown(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    with h5py.File(path, "a") as h:
        del h[f"{BASE}/metadata/radarGrid/incidenceAngle"].attrs["units"]
    with pytest.raises(GoffReadError, match="INCIDENCE_ANGLE_UNIT_MISSING"):
        read_geometry_cubes(path, expected_epsg=32645)


def test_geometry_sampling_refuses_extrapolation(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    cubes = read_geometry_cubes(path, expected_epsg=32645)
    with pytest.raises(GoffReadError, match="GEOMETRY_QUERY_X_OUTSIDE"):
        sample_geometry(cubes, x_m=np.array([500.0]), y_m=np.array([250.0]), height_m=5151.0,
                    expected_epsg=32645)
    with pytest.raises(GoffReadError, match="GEOMETRY_HEIGHT_OUTSIDE"):
        sample_geometry(cubes, x_m=np.array([150.0]), y_m=np.array([250.0]), height_m=7000.0,
                    expected_epsg=32645)



def test_raw_reader_masks_only_explicit_fill_values_and_records_them(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    with h5py.File(path, "a") as h:
        ds = h[f"{BASE}/grids/frequencyA/pixelOffsets/HH/layer2/slantRangeOffset"]
        ds.attrs["_FillValue"] = np.float32(-9999.0)
        ds[0, 0] = -9999.0
    product = read_raw_goff(path)
    assert np.isnan(product.slant_range_m[0, 0])
    assert product.fill_evidence["slant_range"] == [-9999.0]
    assert product.slant_range_m[0, 1] == pytest.approx(0.01)


def test_geometry_metadata_crs_must_match_offset_grid_crs(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    with h5py.File(path, "a") as h:
        ds = h[f"{BASE}/metadata/radarGrid/projection"]
        ds.attrs["epsg_code"] = 32644
        ds[()]  # metadata CRS now differs from the GOFF offset grid
    with pytest.raises(GoffReadError, match="GEOMETRY_CRS_MISMATCH"):
        read_geometry_cubes(path, expected_epsg=32645)



def test_grid_inspection_does_not_require_loading_full_rasters(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    grid = inspect_goff_grid(path, expected_track="098", expected_direction="A")
    assert grid.grid_shape == (4, 5)
    assert grid.x_coordinates_m.tolist() == [100, 101, 102, 103, 104]
    assert grid.y_coordinates_m.tolist() == [200, 201, 202, 203]
    assert grid.epsg == 32645
    assert grid.file_size_bytes == path.stat().st_size


def test_raw_reader_reads_only_requested_hdf5_window_and_checks_grid(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    grid = inspect_goff_grid(path, expected_track="098", expected_direction="A")
    product = read_raw_goff(
        path, expected_track="098", expected_direction="A",
        window_slices=(slice(1, 3), slice(2, 5)), expected_grid=grid,
    )
    assert product.along_track_m.shape == (2, 3)
    assert product.x_coordinates_m.tolist() == [102, 103, 104]
    assert product.y_coordinates_m.tolist() == [201, 202]
    assert product.metadata["original_grid_shape"] == [4, 5]
    assert product.metadata["read_window"] == {
        "row_start": 1, "row_stop": 3, "column_start": 2, "column_stop": 5
    }

def test_raw_reader_masks_hdf5_creation_property_fill_without_attribute(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    with h5py.File(path, "a") as h:
        layer = h[f"{BASE}/grids/frequencyA/pixelOffsets/HH/layer2"]
        del layer["slantRangeOffset"]
        ds = layer.create_dataset(
            "slantRangeOffset", shape=(4, 5), dtype=np.float32, fillvalue=-9999.0
        )
        ds[...] = np.arange(20, dtype=np.float32).reshape(4, 5) / 100
        ds[0, 0] = -9999.0
        ds.attrs["units"] = "m"
    product = read_raw_goff(path)
    assert np.isnan(product.slant_range_m[0, 0])
    assert product.fill_evidence["slant_range"] == [-9999.0]
    # Zero can be a real offset, so the HDF5 default fill value must not be guessed.
    assert product.along_track_m[0, 0] == pytest.approx(0.0)
    assert product.fill_evidence["along_track"] == []


def test_geometry_sampling_supports_per_pixel_hae_values_for_dem_backed_projection(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    cubes = read_geometry_cubes(path, expected_epsg=32645)
    # Make the synthetic incidence cube vary linearly with HAE so interpolation
    # against different per-pixel terrain heights has an independent answer.
    cubes.incidence_deg[0, :, :] = 30.0
    cubes.incidence_deg[1, :, :] = 50.0
    sample = sample_geometry(
        cubes,
        x_m=np.array([[101.0, 102.0]]),
        y_m=np.array([[201.0, 202.0]]),
        height_m=np.array([[5000.0, 6000.0]]),
        expected_epsg=32645,
    )
    assert np.allclose(sample.incidence_deg, [[30.0, 50.0]])


def test_geometry_sampling_rejects_mismatched_or_outside_per_pixel_hae_values(tmp_path):
    path = tmp_path / TARGET_NAME
    write_synthetic_goff(path)
    cubes = read_geometry_cubes(path, expected_epsg=32645)
    with pytest.raises(GoffReadError, match="GEOMETRY_QUERY_HEIGHT_SHAPE_MISMATCH"):
        sample_geometry(
            cubes, x_m=np.array([[101.0, 102.0]]), y_m=np.array([[201.0, 202.0]]),
            height_m=np.array([5150.0]), expected_epsg=32645,
        )
    with pytest.raises(GoffReadError, match="GEOMETRY_HEIGHT_OUTSIDE_METADATA_AXIS"):
        sample_geometry(
            cubes, x_m=np.array([[101.0, 102.0]]), y_m=np.array([[201.0, 202.0]]),
            height_m=np.array([[5150.0, 7000.0]]), expected_epsg=32645,
        )
