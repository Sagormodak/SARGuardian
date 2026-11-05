import hashlib
import json

import pytest
import numpy as np

from export_gcov_layer import verify_download_receipt


GRANULE = "SYNTHETIC_NISAR_GCOV_TEST_GRANULE"


def create_product_and_receipt(raster_writer, *, overrides=None):
    seed_path = raster_writer("receipt-seed.tif", np.ones((1, 1), dtype=np.uint8))
    tmp_path = seed_path.parent
    product = tmp_path / f"{GRANULE}.h5"
    product.write_bytes(b"synthetic HDF5 placeholder")
    receipt = {
        "schema_version": 1,
        "granule_name": GRANULE,
        "product": "GCOV",
        "maturity": "PROVISIONAL",
        "source_host": "nisar.asf.earthdatacloud.nasa.gov",
        "file_path": str(product),
        "size_bytes": product.stat().st_size,
        "sha256": hashlib.sha256(product.read_bytes()).hexdigest(),
        "downloaded": True,
    }
    receipt.update(overrides or {})
    product.with_name(product.stem + ".download.json").write_text(json.dumps(receipt), encoding="utf-8")
    return product


def test_receipt_binds_exact_granule_maturity_host_and_bytes(raster_writer):
    product = create_product_and_receipt(raster_writer)

    receipt_path, source_sha256 = verify_download_receipt(product, "PROVISIONAL")

    assert receipt_path.is_file()
    assert source_sha256 == hashlib.sha256(product.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "overrides, maturity, error",
    [
        ({"maturity": "BETA"}, "PROVISIONAL", "exact GCOV granule, maturity"),
        ({"granule_name": "another-granule"}, "PROVISIONAL", "exact GCOV granule, maturity"),
        ({"source_host": "example.com"}, "PROVISIONAL", "exact GCOV granule, maturity"),
        ({"downloaded": False}, "PROVISIONAL", "exact GCOV granule, maturity"),
    ],
)
def test_receipt_rejects_identity_maturity_host_or_download_mismatch(raster_writer, overrides, maturity, error):
    product = create_product_and_receipt(raster_writer, overrides=overrides)

    with pytest.raises(ValueError, match=error):
        verify_download_receipt(product, maturity)


def test_receipt_rejects_product_bytes_that_changed_after_download(raster_writer):
    product = create_product_and_receipt(raster_writer)
    product.write_bytes(b"modified product")

    with pytest.raises(ValueError, match="SHA-256 does not match"):
        verify_download_receipt(product, "PROVISIONAL")
