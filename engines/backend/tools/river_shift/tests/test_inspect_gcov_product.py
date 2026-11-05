import subprocess

import pytest

import inspect_gcov_product


def test_inspection_fails_early_when_hdf5_driver_is_not_registered(monkeypatch, tmp_path):
    product = tmp_path / "sample.h5"
    product.write_bytes(b"synthetic placeholder")

    monkeypatch.setattr(inspect_gcov_product, "gdal_version", lambda: (3, 13, 3))
    monkeypatch.setattr(inspect_gcov_product, "gdal_driver_names", lambda: {"netCDF"})

    with pytest.raises(RuntimeError, match="libgdal-hdf5"):
        inspect_gcov_product.inspect_product(product)


def test_inspection_forces_hdf5_driver_and_surfaces_gdal_stderr(monkeypatch, tmp_path):
    product = tmp_path / "sample.h5"
    product.write_bytes(b"synthetic placeholder")
    calls = []

    def fail_gdal(command, **_kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(
            1,
            command,
            output="",
            stderr="ERROR 4: HDF5 driver could not parse the product header.",
        )

    monkeypatch.setattr(inspect_gcov_product, "gdal_version", lambda: (3, 13, 3))
    monkeypatch.setattr(inspect_gcov_product, "gdal_driver_names", lambda: {"HDF5", "netCDF"})
    monkeypatch.setattr(inspect_gcov_product.subprocess, "run", fail_gdal)

    with pytest.raises(RuntimeError, match="HDF5 driver could not parse the product header"):
        inspect_gcov_product.inspect_product(product)

    assert calls == [["gdalinfo", "-if", "HDF5", "-json", str(product)]]
