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
    assert runner._common_support_fraction(pred_path, ref_path) == pytest.approx(6 / 6)


def test_common_support_fraction_rejects_grid_mismatch(tmp_path) -> None:
    values = np.ones((2, 2), dtype=np.uint8)
    pred_path = tmp_path / "prediction.tif"
    ref_path = tmp_path / "reference.tif"
    _write_mask(pred_path, values)
    _write_mask(ref_path, values, transform=from_origin(500010, 2700000, 10, 10))
    with pytest.raises(ValueError, match="same projected grid"):
        runner._common_support_fraction(pred_path, ref_path)
