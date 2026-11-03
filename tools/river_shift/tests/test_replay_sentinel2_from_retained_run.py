from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import date

import numpy as np
import rasterio
from rasterio.transform import from_origin

import replay_sentinel2_from_retained_run as replay


def _write_product(root: Path, granule: str, observed_date: str, *, run_id: str, value: int):
    directory = root / granule
    directory.mkdir(parents=True, exist_ok=True)
    raster_path = directory / f"{granule}.tif"
    array = np.full((4, 4), value, dtype=np.float32)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:32645",
        transform=from_origin(500000, 2700000, 10, 10),
        nodata=None,
    ) as dst:
        dst.write(array, 1)
        dst.write_mask(np.full((4, 4), 255, dtype=np.uint8))
    digest = replay.sha256_file(raster_path)
    sidecar_path = raster_path.with_suffix(".metadata.json")
    sidecar = {
        "source_granule_name": granule,
        "source_product_sha256": hashlib.sha256((granule + "-source").encode()).hexdigest(),
        "output_cog": "/runner/old/path/" + raster_path.name,
        "output_cog_sha256": digest,
        "maturity": "PROVISIONAL",
        "frequency": "frequencyA",
        "covariance_term": "HHHH",
        "bandwidth_mode": "4005",
        "polarization_code": "DHDH",
        "processing_type": "PR",
        "flight_direction": "ASCENDING",
        "relative_orbit": "069",
        "frame": "015",
        "crid": "P05023",
        "orbit_accuracy": "N",
        "frame_coverage": "FULL",
        "observation_source": "A",
    }
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    sidecar_digest = replay.sha256_file(sidecar_path)
    worker = {
        "status": "PASS",
        "granule_name": granule,
        "workflow_run_id": run_id,
        "raster_sha256": digest,
        "files": [
            {"name": raster_path.name, "sha256": digest, "bytes": raster_path.stat().st_size},
            {"name": sidecar_path.name, "sha256": sidecar_digest, "bytes": sidecar_path.stat().st_size},
        ],
    }
    (directory / "worker-result.json").write_text(json.dumps(worker), encoding="utf-8")
    return raster_path, sidecar_path


def _prepared(root: Path, names: list[str], *, run_id: str = "41642281327"):
    prepared_dir = root / "prepared"
    prepared_dir.mkdir()
    manifest = {
        "job_id": "a7d34520-18c9-4ef0-b135-c902044338a4",
        "request_fingerprint": "f" * 64,
        "selected_product_names": names,
        "date_by_name": {
            names[0]: "2026-07-12",
            names[1]: "2026-07-24",
        },
        "request": {
            "maturity": "PROVISIONAL",
            "frequency": "frequencyA",
            "term": "HHHH",
            "threshold_method": "otsu",
            "threshold_db": None,
        },
    }
    (prepared_dir / "prepared.json").write_text(json.dumps(manifest), encoding="utf-8")
    return prepared_dir


def test_prepare_source_observations_verifies_receipts_and_restores_local_sidecar_paths(tmp_path):
    products = tmp_path / "products"
    products.mkdir()
    names = ["granule-one", "granule-two"]
    raster_paths = []
    sidecars = []
    for index, (name, day) in enumerate(zip(names, ("2026-07-12", "2026-07-24"))):
        raster, sidecar = _write_product(products, name, day, run_id="41642281327", value=index + 1)
        raster_paths.append(raster)
        sidecars.append(sidecar)
    prepared = _prepared(tmp_path, names)

    observations, manifest, receipts = replay.prepare_source_observations(
        products,
        prepared,
        expected_source_run_id="41642281327",
    )

    assert [row["date"] for row in observations] == ["2026-07-12", "2026-07-24"]
    assert [Path(row["path"]) for row in observations] == raster_paths
    assert manifest["job_id"] == "a7d34520-18c9-4ef0-b135-c902044338a4"
    assert len(receipts) == 2
    for raster, sidecar, receipt in zip(raster_paths, sidecars, receipts):
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        assert metadata["output_cog"] == str(raster.resolve())
        assert metadata["output_cog_sha256"] == replay.sha256_file(raster)
        assert receipt["cog_sha256"] == replay.sha256_file(raster)
        assert receipt["sidecar_sha256_before_local_path_restore"]


def test_prepare_source_observations_rejects_artifact_from_wrong_workflow_run(tmp_path):
    products = tmp_path / "products"
    products.mkdir()
    names = ["granule-one", "granule-two"]
    for index, name in enumerate(names):
        _write_product(products, name, "unused", run_id="99999999", value=index + 1)
    prepared = _prepared(tmp_path, names)

    try:
        replay.prepare_source_observations(
            products,
            prepared,
            expected_source_run_id="41642281327",
        )
    except replay.ReplayError as exc:
        assert "not from source run" in str(exc)
    else:
        raise AssertionError("A product from an unrelated workflow run must be rejected.")


def test_prepare_source_observations_rejects_mixed_gcov_comparison_signatures(tmp_path):
    products = tmp_path / "products"
    products.mkdir()
    names = ["granule-one", "granule-two"]
    _write_product(products, names[0], "unused", run_id="41642281327", value=1)
    _, sidecar = _write_product(products, names[1], "unused", run_id="41642281327", value=2)
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["covariance_term"] = "VVVV"
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    prepared = _prepared(tmp_path, names)

    try:
        replay.prepare_source_observations(
            products,
            prepared,
            expected_source_run_id="41642281327",
        )
    except replay.ReplayError as exc:
        assert "identical GCOV comparison signature" in str(exc)
    else:
        raise AssertionError("Incompatible GCOV signatures must be rejected.")


def test_run_replay_uses_exact_observation_mask_and_records_source_provenance(tmp_path, monkeypatch):
    products = tmp_path / "products"
    products.mkdir()
    names = ["granule-one", "granule-two"]
    for index, name in enumerate(names):
        _write_product(products, name, "unused", run_id="41642281327", value=index + 1)
    prepared = _prepared(tmp_path, names)
    observed = {}

    def fake_timeseries(**kwargs):
        observed["timeseries"] = kwargs
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        mask = output / "water_2026-07-12_mask.tif"
        with rasterio.open(
            mask,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype="uint8",
            crs="EPSG:32645",
            transform=from_origin(500000, 2700000, 10, 10),
            nodata=255,
        ) as dst:
            dst.write(np.ones((4, 4), dtype=np.uint8), 1)
        (output / "river_shift_timeseries.json").write_text(
            json.dumps({"method": {"threshold_db": -12.3, "threshold_method": "otsu"}}),
            encoding="utf-8",
        )
        return {"method": {"threshold_db": -12.3, "threshold_method": "otsu"}}

    def fake_crosscheck(**kwargs):
        observed["crosscheck"] = kwargs
        destination = Path(kwargs["output_dir"])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "sentinel2_cross_sensor_agreement.json").write_text(
            json.dumps({"status": "NO_MATCHING_SENTINEL2_SCENE_WITHIN_FILTER", "metrics": None}),
            encoding="utf-8",
        )
        return {
            "status": "NO_MATCHING_SENTINEL2_SCENE_WITHIN_FILTER",
            "observation": None,
            "spatial_support": None,
            "metrics": None,
            "warnings": ["No optical scene matched; no metrics were calculated."],
        }

    monkeypatch.setattr(replay, "run_water_timeseries_analysis", fake_timeseries)
    monkeypatch.setattr(replay, "run_crosscheck", fake_crosscheck)

    summary = replay.run_replay(
        products_dir=products,
        prepared_dir=prepared,
        source_run_id="41642281327",
        observation_date=date(2026, 7, 12),
        output_dir=tmp_path / "output",
    )

    assert observed["timeseries"]["use_otsu"] is True
    assert observed["timeseries"]["units"] == "linear"
    assert observed["crosscheck"]["observation_date"].isoformat() == "2026-07-12"
    assert observed["crosscheck"]["nisar_mask_path"].name == "water_2026-07-12_mask.tif"
    assert summary["status"] == "NO_MATCHING_SENTINEL2_SCENE_WITHIN_FILTER"
    manifest = json.loads(Path(summary["replay_manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_workflow_run_id"] == "41642281327"
    assert manifest["quality"]["raw_nisar_hdf5_redownloaded"] is False
    assert manifest["quality"]["not_ground_truth"] is True
