import json
import hashlib

import pytest

from river_shift.raster_io import RasterContractError, gcov_source_provenance, validate_gcov_series


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



def test_gcov_series_preserves_individual_granule_checksums_for_a_mosaic(tmp_path):
    path = tmp_path / "mosaic.tif"
    names = ["granule-left", "granule-right"]
    hashes = ["a" * 64, "b" * 64]
    aggregate = hashlib.sha256("\\n".join(sorted(hashes)).encode("ascii")).hexdigest()
    write_sidecar(
        path,
        source_granule_name="+".join(names),
        source_granule_names=names,
        source_granule_sha256=hashes,
        source_product_sha256=aggregate,
        source_product_sha256_scope="sha256_of_sorted_source_granule_sha256_values",
        mosaic_method="deterministic test mosaic",
    )

    records, complete = validate_gcov_series(
        {"observation": str(path)},
        maturity="PROVISIONAL",
        frequency="frequencyA",
        term="HHHH",
    )
    provenance = gcov_source_provenance(records)

    assert complete is True
    assert provenance["granule_names"] == names
    assert provenance["source_granule_sha256"] == hashes
    assert provenance["observation_sources"][0]["source_product_sha256"] == aggregate
    assert provenance["observation_sources"][0]["mosaic_method"] == "deterministic test mosaic"


def test_gcov_series_rejects_mosaic_provenance_with_unmatched_name_hash_lists(tmp_path):
    path = tmp_path / "mosaic-bad.tif"
    write_sidecar(
        path,
        source_granule_name="granule-left+granule-right",
        source_granule_names=["granule-left", "granule-right"],
        source_granule_sha256=["a" * 64],
    )

    with pytest.raises(RasterContractError, match="matching source granule names"):
        validate_gcov_series(
            {"observation": str(path)},
            maturity="PROVISIONAL",
            frequency="frequencyA",
            term="HHHH",
        )


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
