import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from export_gcov_layer import apply_valid_sample_mask


def write_raster(path, values, *, crs="EPSG:32646", transform=None, nodata=None):
    array = np.asarray(values)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=crs,
        transform=transform or from_origin(500000, 2500000, 10, 10),
        nodata=nodata,
    ) as destination:
        destination.write(array, 1)


def test_valid_sample_mask_excludes_invalid_and_outside_pixels(tmp_path):
    backscatter = tmp_path / "backscatter.tif"
    quality_mask = tmp_path / "quality-mask.tif"
    output = tmp_path / "masked.tif"
    write_raster(backscatter, np.array([[0.1, 0.2, 0.3, 0.4]], dtype=np.float32))
    write_raster(quality_mask, np.array([[1, 0, 255, 3]], dtype=np.uint8), nodata=255)

    counts = apply_valid_sample_mask(backscatter, quality_mask, output)

    assert counts == {"valid_pixel_count": 2, "excluded_pixel_count": 2}
    with rasterio.open(output) as raster:
        assert raster.dataset_mask().tolist() == [[255, 0, 0, 255]]
        np.testing.assert_allclose(raster.read(1), [[0.1, 0.2, 0.3, 0.4]])


def test_valid_sample_mask_rejects_grid_mismatch(tmp_path):
    backscatter = tmp_path / "backscatter.tif"
    quality_mask = tmp_path / "quality-mask.tif"
    write_raster(backscatter, np.ones((2, 2), dtype=np.float32))
    write_raster(
        quality_mask,
        np.ones((2, 2), dtype=np.uint8),
        transform=from_origin(500010, 2500000, 10, 10),
    )

    with pytest.raises(ValueError, match="exact same grid"):
        apply_valid_sample_mask(backscatter, quality_mask, tmp_path / "masked.tif")
