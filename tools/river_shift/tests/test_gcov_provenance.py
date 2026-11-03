import json
import hashlib

import pytest

from river_shift.raster_io import RasterContractError, validate_gcov_series


def write_sidecar(raster_path, **overrides):
    raster_path.write_bytes(b"test COG bytes")
    metadata = {
        "source_granule_name": "NISAR_L2_PR_GCOV_023_069_A_014_4005_DHDH_A_20260618T232135_20260618T232210_P05023_N_F_J_001",
        "source_product_sha256": "a" * 64,
        "output_cog": str(raster_path.resolve()),
        "output_cog_sha256": hashlib.sha256(raster_path.read_bytes()).hexdigest(),
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "covariance_term": "HHHH",
        "bandwidth_mode": "4005",
        "polarization_code": "DHDH",
        "processing_type": "PR",
        "flight_direction": "ASCENDING",
        "relative_orbit": "069",
        "frame": "014",
        "crid": "P05023",
        "orbit_accuracy": "N",
        "frame_coverage": "F",
        "observation_source": "A",
    }
    metadata.update(overrides)
    raster_path.with_suffix(".metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_gcov_series_requires_matching_provenance_for_every_date(tmp_path):
    paths = {key: tmp_path / f"{key}.tif" for key in ("before", "during", "after")}
    for path in paths.values():
        path.touch()
        write_sidecar(path)
    records, complete = validate_gcov_series(paths, maturity="PROVISIONAL", frequency="frequencyA", term="HHHH")
    assert complete is True
    assert len(records) == 3


def test_gcov_series_rejects_mixed_processing_release(tmp_path):
    paths = {key: tmp_path / f"{key}.tif" for key in ("before", "during", "after")}
    for path in paths.values():
        path.touch()
    write_sidecar(paths["before"])
    write_sidecar(paths["during"])
    write_sidecar(paths["after"], crid="P05024")
    with pytest.raises(RasterContractError, match="same crid"):
        validate_gcov_series(paths, maturity="PROVISIONAL", frequency="frequencyA", term="HHHH")


def test_gcov_series_rejects_incomplete_checksum(tmp_path):
    path = tmp_path / "before.tif"
    path.touch()
    write_sidecar(path, source_product_sha256="not-a-checksum")
    paths = {"before": path}
    with pytest.raises(RasterContractError, match="64-character SHA-256"):
        validate_gcov_series(paths, maturity="PROVISIONAL", frequency="frequencyA", term="HHHH")


def test_gcov_series_rejects_raster_changed_after_export(tmp_path):
    path = tmp_path / "before.tif"
    write_sidecar(path)
    path.write_bytes(b"changed after export")
    with pytest.raises(RasterContractError, match="does not match its metadata sidecar"):
        validate_gcov_series({"before": str(path)}, maturity="PROVISIONAL", frequency="frequencyA", term="HHHH")
