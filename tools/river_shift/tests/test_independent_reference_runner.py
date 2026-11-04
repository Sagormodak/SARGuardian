from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import validate_independent_reference as runner


def _write_mask(path: Path, values: np.ndarray, *, nodata: int = 255, transform=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:32646",
        transform=transform or from_origin(500000, 2700000, 10, 10),
        nodata=nodata,
        compress="deflate",
    ) as dataset:
        dataset.write(values.astype("uint8"), 1)


def test_safe_https_base_rejects_http_and_embedded_credentials() -> None:
    assert runner._safe_https_base("https://api.example.test/") == "https://api.example.test"
    with pytest.raises(ValueError, match="HTTPS"):
        runner._safe_https_base("http://api.example.test")
    with pytest.raises(ValueError, match="HTTPS"):
        runner._safe_https_base("https://user:password@api.example.test")


def test_signed_source_manifest_request_uses_exact_hmac_body(monkeypatch) -> None:
    monkeypatch.setenv("RIVERSHIFT_CALLBACK_SECRET", "runner-test-secret")
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "schema_version": 1,
                "engine": "RiverShift",
                "job_id": "4e6e4071-fb9d-4e20-a331-867f3f2bd88f",
                "prediction_observation_date": "2026-08-17",
                "prediction": {
                    "path": "outputs/flood/during_water_mask.tif",
                    "drive_file_id": "prediction-file-123",
                    "bytes": 12,
                    "sha256": "a" * 64,
                },
                "result_report": {
                    "path": "outputs/flood/river_shift_result.json",
                    "drive_file_id": "result-file-123",
                    "bytes": 13,
                    "sha256": "b" * 64,
                },
            }

    def fake_post(url, *, data, headers, timeout):
        captured.update(url=url, data=data, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(runner.requests, "post", fake_post)
    result = runner._resolve_source_manifest(
        "4e6e4071-fb9d-4e20-a331-867f3f2bd88f",
        "https://api.example.test",
    )
    expected_body = json.dumps(
        {"prediction_path": "outputs/flood/during_water_mask.tif"},
        separators=(",", ":"),
    ).encode()
    expected_signature = "sha256=" + hmac.new(
        b"runner-test-secret", expected_body, hashlib.sha256
    ).hexdigest()
    assert captured["url"] == (
        "https://api.example.test/api/river-shift/jobs/"
        "4e6e4071-fb9d-4e20-a331-867f3f2bd88f/validation-inputs"
    )
    assert captured["data"] == expected_body
    assert captured["headers"]["X-SARGuardian-Signature"] == expected_signature
    assert captured["timeout"] == (10, 30)
    assert result["prediction"]["path"] == "outputs/flood/during_water_mask.tif"


def test_signed_source_manifest_rejects_wrong_job_or_wrong_artifact_contract(monkeypatch) -> None:
    monkeypatch.setenv("RIVERSHIFT_CALLBACK_SECRET", "runner-test-secret")

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "schema_version": 1,
                "engine": "RiverShift",
                "job_id": "another-job",
                "prediction_observation_date": "2026-08-17",
                "prediction": {"path": "outputs/map/preview.geojson"},
                "result_report": {"path": "outputs/flood/river_shift_result.json"},
            }

    monkeypatch.setattr(runner.requests, "post", lambda *_args, **_kwargs: Response())
    with pytest.raises(ValueError, match="contract"):
        runner._resolve_source_manifest(
            "4e6e4071-fb9d-4e20-a331-867f3f2bd88f",
            "https://api.example.test",
        )


def test_download_receipt_is_sha256_and_size_verified(monkeypatch, tmp_path) -> None:
    payload = b"independent-source-receipt"
    item = {
        "drive_file_id": "private-file-id-123",
        "name": "during_water_mask.tif",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    def fake_download(file_id, destination, *, max_bytes):
        assert file_id == item["drive_file_id"]
        assert max_bytes == len(payload)
        destination.write_bytes(payload)
        return {"bytes": len(payload)}

    monkeypatch.setattr(runner, "download_private_result_to_path", fake_download)
    target = tmp_path / "during_water_mask.tif"
    runner._download_verified(item, target)
    assert target.read_bytes() == payload

    bad = item | {"sha256": "0" * 64}
    with pytest.raises(ValueError, match="verification failed"):
        runner._download_verified(bad, tmp_path / "corrupt.tif")


def test_common_support_fraction_uses_prediction_valid_footprint(tmp_path) -> None:
    prediction = np.asarray([[1, 1, 0, 0], [1, 0, 1, 0]], dtype=np.uint8)
    reference = np.asarray([[1, 0, 255, 0], [1, 1, 1, 255]], dtype=np.uint8)
    pred_path = tmp_path / "prediction.tif"
    ref_path = tmp_path / "reference.tif"
    _write_mask(pred_path, prediction)
    _write_mask(ref_path, reference)
    assert runner._common_support_fraction(pred_path, ref_path) == pytest.approx(6 / 8)


def test_common_support_fraction_rejects_grid_mismatch(tmp_path) -> None:
    values = np.ones((2, 2), dtype=np.uint8)
    pred_path = tmp_path / "prediction.tif"
    ref_path = tmp_path / "reference.tif"
    _write_mask(pred_path, values)
    _write_mask(ref_path, values, transform=from_origin(500010, 2700000, 10, 10))
    with pytest.raises(ValueError, match="exact target grid"):
        runner._common_support_fraction(pred_path, ref_path)


def test_independent_reference_alignment_uses_nearest_neighbour_and_preserves_nodata(tmp_path) -> None:
    prediction = np.zeros((4, 4), dtype=np.uint8)
    reference = np.asarray([[1, 0], [0, 255]], dtype=np.uint8)
    prediction_path = tmp_path / "prediction.tif"
    reference_path = tmp_path / "reference-source.tif"
    aligned_path = tmp_path / "reference-aligned.tif"
    _write_mask(prediction_path, prediction)
    _write_mask(
        reference_path,
        reference,
        transform=from_origin(500000, 2700000, 20, 20),
    )

    details = runner._align_reference_to_prediction(prediction_path, reference_path, aligned_path)

    with rasterio.open(prediction_path) as prediction_ds, rasterio.open(aligned_path) as aligned_ds:
        assert aligned_ds.crs == prediction_ds.crs
        assert aligned_ds.transform == prediction_ds.transform
        assert aligned_ds.width == prediction_ds.width
        assert aligned_ds.height == prediction_ds.height
        values = aligned_ds.read(1)
        assert set(np.unique(values)).issubset({0, 1, 255})
        assert int(np.count_nonzero(values == 255)) == 4
    assert details["method"] == "nearest_neighbour_categorical_reprojection"
    assert details["aligned_valid_pixels"] == 8


def test_independent_reference_alignment_rejects_non_binary_valid_labels(tmp_path) -> None:
    prediction_path = tmp_path / "prediction.tif"
    reference_path = tmp_path / "reference-source.tif"
    _write_mask(prediction_path, np.zeros((2, 2), dtype=np.uint8))
    _write_mask(
        reference_path,
        np.asarray([[0, 1], [2, 255]], dtype=np.uint8),
    )
    with pytest.raises(ValueError, match="must be binary"):
        runner._align_reference_to_prediction(
            prediction_path,
            reference_path,
            tmp_path / "aligned.tif",
        )


def test_validate_runs_end_to_end_and_keeps_release_provisional(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    job_id = "4e6e4071-fb9d-4e20-a331-867f3f2bd88f"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    prediction_path = source_dir / "during_water_mask.tif"
    prediction_values = (np.indices((20, 20)).sum(axis=0) % 2).astype(np.uint8)
    _write_mask(prediction_path, prediction_values)
    prediction_sha = hashlib.sha256(prediction_path.read_bytes()).hexdigest()

    result_report = {
        "analysis_type": "flood_inundation_screening",
        "source": {
            "mission": "NISAR",
            "product": "GCOV",
            "maturity": "PROVISIONAL",
            "frequency": "A",
            "covariance_term": "HHHH",
            "granule_names": ["NISAR_L2_GCOV_TEST_GRANULE"],
            "source_granule_sha256": ["a" * 64],
        },
        "outputs": {
            "during_water_mask": "during_water_mask.tif",
            "during_water_mask_sha256": prediction_sha,
        },
        "quality": {"provenance_complete": True},
    }
    report_path = source_dir / "river_shift_result.json"
    report_path.write_text(json.dumps(result_report), encoding="utf-8")

    reference_values = prediction_values[::2, ::2].copy()
    reference_values[0, 0] = 255
    reference_path = tmp_path / "reference-original.tif"
    _write_mask(
        reference_path,
        reference_values,
        transform=from_origin(500000, 2700000, 20, 20),
    )
    blobs = {
        "prediction-file-123": prediction_path.read_bytes(),
        "result-file-123": report_path.read_bytes(),
        "reference-file-123": reference_path.read_bytes(),
    }
    items = {
        "prediction": {
            "name": "during_water_mask.tif",
            "path": "outputs/flood/during_water_mask.tif",
            "drive_file_id": "prediction-file-123",
            "bytes": len(blobs["prediction-file-123"]),
            "sha256": hashlib.sha256(blobs["prediction-file-123"]).hexdigest(),
        },
        "result_report": {
            "name": "river_shift_result.json",
            "path": "outputs/flood/river_shift_result.json",
            "drive_file_id": "result-file-123",
            "bytes": len(blobs["result-file-123"]),
            "sha256": hashlib.sha256(blobs["result-file-123"]).hexdigest(),
        },
    }
    monkeypatch.setattr(
        runner,
        "_resolve_source_manifest",
        lambda *_args: {
            "schema_version": 1,
            "engine": "RiverShift",
            "job_id": job_id,
            "github_run_id": "41803576163",
            "prediction_observation_date": "2026-08-17",
            "prediction": items["prediction"],
            "result_report": items["result_report"],
        },
    )

    def fake_download(file_id, destination, *, max_bytes):
        payload = blobs[file_id]
        assert len(payload) <= max_bytes
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return {"bytes": len(payload)}

    monkeypatch.setattr(runner, "download_private_result_to_path", fake_download)
    output_path = tmp_path / "output" / "independent_reference_validation.json"
    args = SimpleNamespace(
        source_job_id=job_id,
        api_base_url="https://api.example.test",
        reference_drive_file_id="reference-file-123",
        reference_source="Independent high-resolution reference mapping v1",
        reference_date="2026-08-17",
        reference_method="Blind binary water/non-water digitisation with independent QA",
        maximum_date_offset_days=3,
        minimum_common_support_fraction=0.80,
        block_size_pixels=4,
        bootstrap_replicates=100,
        random_seed=42,
        work_dir=tmp_path / "work",
        output=output_path,
    )

    result = runner.validate(args)

    assert output_path.is_file()
    assert result["quality"]["status"] == "VALIDATION_METRICS_COMPUTED_REVIEW_REQUIRED"
    assert result["quality"]["release_status"] == "PROVISIONAL"
    assert result["reference"]["independence_verified"] is False
    assert result["reference"]["alignment"]["method"] == "nearest_neighbour_categorical_reprojection"
    assert result["reference"]["common_support_fraction"] == pytest.approx(0.99)
    assert result["source"]["river_shift_job_id"] == job_id
    assert result["source"]["prediction_analysis"]["mission"] == "NISAR"
    assert result["metrics"]["valid_pixel_count"] > 0
    assert result["metrics"]["f1_score"] is not None
