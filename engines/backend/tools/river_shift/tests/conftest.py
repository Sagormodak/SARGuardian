from pathlib import Path

import sys

# The original command-line tools live beside this tests/ directory. Expose
# that folder for both standalone RiverShift CI and the repository-wide pytest suite.
_RIVERSHIFT_ROOT = str(Path(__file__).resolve().parents[1])
if _RIVERSHIFT_ROOT not in sys.path:
    sys.path.insert(0, _RIVERSHIFT_ROOT)

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


@pytest.fixture
def raster_writer(tmp_path: Path):
    def write(name: str, array: np.ndarray, crs: str = "EPSG:32646") -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "driver": "GTiff",
            "height": int(array.shape[0]),
            "width": int(array.shape[1]),
            "count": 1,
            "dtype": str(array.dtype),
            "crs": crs,
            "transform": from_origin(500000, 2500000, 10, 10),
        }
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(array, 1)
        return path
    return write
