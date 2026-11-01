from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from app import main as main_module
from app.asf_catalog import ASFAdapterError, ASFSearchResult
from app.auth import get_current_user
from app.main import app
from app.persistence import PersistenceError

client = TestClient(app)


def setup_function() -> None:
    app.dependency_overrides.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def authenticated_client() -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: {"uid": "test-user"}
    return client


def valid_payload() -> dict:
    return {
        "coordinates": [[85.3, 27.7], [85.301, 27.7], [85.301, 27.701], [85.3, 27.7]],
        "start_date": "2026-08-01",
        "end_date": "2026-08-15",
        "product_type": "GUNW",
    }


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_requires_firebase_bearer_token() -> None:
    response = client.post("/api/catalog/search", json=valid_payload())
    assert response.status_code == 401
    assert "Bearer token" in response.json()["detail"]


def test_catalog_with_bearer_token_reports_missing_firebase_admin_config() -> None:
    response = client.post(
        "/api/catalog/search",
        headers={"Authorization": "Bearer test-token"},
        json=valid_payload(),
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_catalog_validates_server_side_and_returns_honest_not_configured_result(monkeypatch) -> None:
    monkeypatch.setenv("ASF_CATALOG_ENABLED", "false")
    response = authenticated_client().post("/api/catalog/search", json=valid_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_configured"
    assert body["product_count"] == 0
    assert body["products"] == []
    assert body["data_downloaded"] is False
    assert body["scientific_analysis_performed"] is False
    assert body["processing_eligibility"]["status"] == "undetermined"
    assert body["query"]["product_type"] == "GUNW"
    assert body["query"]["aoi_area_km2"] > 0


def test_catalog_rejects_date_and_area_limits() -> None:
    client_instance = authenticated_client()
    too_long = valid_payload() | {"end_date": "2026-11-01"}
    assert client_instance.post("/api/catalog/search", json=too_long).status_code == 422

    too_large = valid_payload() | {
        "coordinates": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
    }
    assert client_instance.post("/api/catalog/search", json=too_large).status_code == 422


def test_catalog_rejects_unsupported_product_type() -> None:
    response = authenticated_client().post("/api/catalog/search", json=valid_payload() | {"product_type": "OTHER"})
    assert response.status_code == 422


def test_catalog_response_contract_maps_ready_metadata_without_downloading(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "search_asf_catalog", lambda *args: ASFSearchResult(rows=[{
        "granuleName": "NISAR_L2_GUNW_TEST",
        "productType": "GUNW",
        "startTime": "2026-08-01T00:00:00Z",
        "stopTime": "2026-08-13T00:00:00Z",
        "sizeMB": {"file.h5": {"bytes": 2_000_000}},
    }], truncated=False, query_url="https://example.invalid"))
    monkeypatch.setattr(main_module, "normalize_product_rows", lambda rows, product_type: ([{
        "granule_name": "NISAR_L2_GUNW_TEST",
        "product_type": "GUNW",
        "observation_dates": ["2026-08-01", "2026-08-13"],
        "size_mb": 2,
    }], 0, []))
    class PreflightStore:
        def save_preflight(self, owner_uid, request_snapshot, manifest_snapshot):
            return uuid4()
    monkeypatch.setattr(main_module, "get_job_store", lambda: PreflightStore())
    response = authenticated_client().post("/api/catalog/search", json=valid_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["product_count"] == 1
    assert body["products"][0]["granule_name"] == "NISAR_L2_GUNW_TEST"
    assert body["scientific_analysis_performed"] is False
    assert body["processing_eligibility"]["status"] == "undetermined"


def test_catalog_both_family_combines_gunw_and_goff_without_creating_a_processing_preflight(monkeypatch) -> None:
    captured = {}

    def search(*args):
        captured["product_types"] = args[-1]
        return ASFSearchResult(rows=[
            {"granuleName": "NISAR_L2_GUNW_TEST", "productType": "GUNW", "startTime": "2026-08-01T00:00:00Z"},
            {"granuleName": "NISAR_L2_GOFF_TEST", "productType": "GOFF", "startTime": "2026-08-02T00:00:00Z"},
        ], truncated=False, query_url="https://example.invalid")

    monkeypatch.setattr(main_module, "search_asf_catalog", search)
    response = authenticated_client().post("/api/catalog/search", json=valid_payload() | {"product_type": "BOTH"})

    assert response.status_code == 200
    assert captured["product_types"] == "GUNW,GOFF"
    assert response.json()["query"]["product_type"] == "BOTH"
    assert {product["product_type"] for product in response.json()["products"]} == {"GUNW", "GOFF"}
    assert response.json()["preflight_id"] is None


def test_catalog_upstream_failure_is_not_reported_as_no_data(monkeypatch) -> None:
    def fail(*args):
        raise ASFAdapterError("ASF catalogue request timed out or could not be reached.")

    monkeypatch.setattr(main_module, "search_asf_catalog", fail)
    response = authenticated_client().post("/api/catalog/search", json=valid_payload())
    assert response.status_code == 502
    assert response.json()["status"] == "upstream_error"


def test_catalog_persistence_failure_is_reported_without_fabricating_a_preflight(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "search_asf_catalog", lambda *args: ASFSearchResult(rows=[{
        "granuleName": "NISAR_L2_GUNW_TEST",
        "productType": "GUNW",
        "startTime": "2026-08-01T00:00:00Z",
        "stopTime": "2026-08-13T00:00:00Z",
        "sizeMB": {"file.h5": {"bytes": 2_000_000}},
    }], truncated=False, query_url="https://example.invalid"))
    monkeypatch.setattr(main_module, "normalize_product_rows", lambda rows, product_type: ([{
        "granule_name": "NISAR_L2_GUNW_TEST",
        "product_type": "GUNW",
        "observation_dates": ["2026-08-01", "2026-08-13"],
        "size_mb": 2,
    }], 0, []))

    class FailingPreflightStore:
        def save_preflight(self, owner_uid, request_snapshot, manifest_snapshot):
            raise PersistenceError("database unavailable")

    monkeypatch.setattr(main_module, "get_job_store", lambda: FailingPreflightStore())
    response = authenticated_client().post("/api/catalog/search", json=valid_payload())
    assert response.status_code == 503
    assert response.json() == {
        "status": "persistence_error",
        "message": "The preflight could not be persisted for job confirmation.",
    }


def test_catalog_rejects_open_polygon_malformed_json_and_oversized_body() -> None:
    client_instance = authenticated_client()
    open_polygon = valid_payload() | {
        "coordinates": [[85.3, 27.7], [85.301, 27.7], [85.301, 27.701]],
    }
    assert client_instance.post("/api/catalog/search", json=open_polygon).status_code == 422
    malformed = client_instance.post("/api/catalog/search", content=b"{not-json", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 422
    oversized = client_instance.post(
        "/api/catalog/search",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": "1000001"},
    )
    assert oversized.status_code == 413


def test_unexpected_errors_use_a_safe_response() -> None:
    def explode() -> dict[str, str]:
        raise RuntimeError("internal test failure")

    app.dependency_overrides[get_current_user] = explode
    response = TestClient(app, raise_server_exceptions=False).post("/api/catalog/search", json=valid_payload())
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}


def test_production_requires_explicit_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as main_module

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        main_module._cors_origins()


def _dashboard_zip(
    *,
    preview: bytes = b"\x89PNG\r\n\x1a\npreview",
    manifest_padding: str = "",
    candidate_feature_count: int = 0,
    candidate_feature_padding: str = "",
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "web-dashboard/index.html",
            '<!doctype html><html><head><link rel="stylesheet" href="https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.css"></head><body>'
            '<main><div class="cards" id="summaryCards"></div><div class="mapbox"><div id="map"></div></div></main>'
            '<script src="./dashboard-data.js"></script>'
            '<script type="module">let maplibregl = null; try { maplibregl = await import(\'https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.mjs\'); } catch (error) { console.warn(\'SARGuardian map library unavailable; science panels remain available.\', error); } const tiles = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";</script>'
            '<a href="../index.html" style="color:var(--aqua);padding:9px">Processing report ↗</a></body></html>',
        )
        archive.writestr("web-dashboard/dashboard-data.js", "window.SARGUARDIAN_DASHBOARD={safe:true};")
        manifest = {
            "schema_version": "sarguardian-web-dashboard/1.0",
            "layers": [{"id": "test-layer", "preview_asset": "layers/test-layer.png"}],
        }
        if manifest_padding:
            manifest["padding"] = manifest_padding
        if candidate_feature_count:
            manifest["aoi_wide_displacement_screen"] = {
                "status": "PASS",
                "candidate_count": candidate_feature_count,
                "candidate_feature_collection": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                "candidate_id": f"candidate-{index + 1}",
                                "direction": "ASC",
                                "track": 170,
                                "area_km2_approx": 0.5,
                                "pairs_with_candidate": 2,
                                "verbose_source_metadata": candidate_feature_padding,
                            },
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[85.0, 27.0], [85.1, 27.0], [85.1, 27.1], [85.0, 27.1], [85.0, 27.0]]],
                            },
                        }
                        for index in range(candidate_feature_count)
                    ],
                },
            }
        archive.writestr("web-dashboard/manifest.json", json.dumps(manifest))
        archive.writestr("web-dashboard/layers/test-layer.png", preview)
    return buffer.getvalue()


def _dashboard_zip_with_oversized_legacy_data() -> bytes:
    buffer = BytesIO()
    with ZipFile(BytesIO(_dashboard_zip()), "r") as original, ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name in original.namelist():
            content = original.read(name)
            if name == "web-dashboard/dashboard-data.js":
                # The retired inline bundle can exceed the old 40 MiB viewer
                # ceiling. The manifest and individual PNGs are still valid.
                content = b"/*" + (b"x" * (40 * 1024 * 1024 + 1)) + b"*/"
            archive.writestr(name, content)
    return buffer.getvalue()


def _dashboard_refresh_request(job_id, expected_previous_sha256: str, *, secret: str = "refresh-secret") -> tuple[bytes, dict[str, str]]:
    payload = {
        "job_id": str(job_id),
        "source_run_id": "41268591823",
        "github_run_id": "41268591823",
        "expected_previous_sha256": expected_previous_sha256,
        "replacement": {
            "drive_file_id": "new-private-drive-file-identifier",
            "bytes": 4_000_000,
            "sha256": "b" * 64,
        },
        "web_dashboard": {
            "status": "PASS",
            "schema_version": "sarguardian-web-dashboard/1.0",
            "viewer": "web-dashboard/index.html",
            "observations": 35,
            "layers": 122,
            "derived_layers": 48,
            "renderable_layers": 170,
            "derived_layer_errors": 0,
        },
        "provenance": {
            "builder_commit": "c" * 40,
            "refresh_workflow_run_id": "41273900123",
            "raw_hdf5_replayed": False,
            "scientific_outputs_changed": False,
        },
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, {"Content-Type": "application/json", "X-SARGuardian-Signature": signature}


def _dashboard_refresh_store(job_id, old_digest: str):
    class RefreshStore:
        def __init__(self):
            self.record = {
                "id": str(job_id),
                "state": "succeeded",
                "worker_contract_version": 2,
                "github_run_id": "41268591823",
                "callback_sequence": 2,
                "result_summary": {
                    "schema_version": 2,
                    "products": [{"id": f"product-{i}"} for i in range(35)],
                    "selected_granule_counts": {"GUNW": 17, "GOFF": 18},
                    "validation": {"status": "PASS"},
                    "artifacts": [
                        {
                            "path": "aoi-derived-results.zip",
                            "kind": "result_bundle",
                            "sha256": old_digest,
                            "bytes": 4_200_000,
                            "drive_file_id": "old-private-drive-file-identifier",
                        },
                        {
                            "path": "products.csv",
                            "kind": "result_table_csv",
                            "sha256": "a" * 64,
                            "bytes": 1024,
                            "drive_file_id": "products-csv-drive-file-identifier",
                        },
                    ],
                    "web_dashboard": {"status": "PASS", "observations": 35, "layers": 100},
                },
            }
            self.update_calls = 0

        def get_displacement_job_unscoped(self, requested_job_id):
            assert requested_job_id == job_id
            return self.record

        def update_displacement_job(self, requested_job_id, values, *, expected_state=None, expected_sequence=None):
            assert requested_job_id == job_id
            assert expected_state == "succeeded"
            assert expected_sequence == 2
            self.update_calls += 1
            self.record.update(values)
            return self.record

    return RefreshStore()


def test_signed_dashboard_refresh_replaces_only_bundle_pointer_without_job_state_change(monkeypatch) -> None:
    from types import SimpleNamespace

    job_id = uuid4()
    old_digest = "a" * 64
    store = _dashboard_refresh_store(job_id, old_digest)
    monkeypatch.setattr(main_module, "get_job_store", lambda: store)
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="refresh-secret"))
    body, headers = _dashboard_refresh_request(job_id, old_digest)

    response = client.post(f"/api/displacement-jobs/{job_id}/dashboard-refresh", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "job_id": str(job_id), "job_status": "succeeded"}
    assert store.update_calls == 1
    assert store.record["state"] == "succeeded"
    assert store.record["callback_sequence"] == 2
    summary = store.record["result_summary"]
    refreshed = next(item for item in summary["artifacts"] if item["path"] == "aoi-derived-results.zip")
    untouched = next(item for item in summary["artifacts"] if item["path"] == "products.csv")
    assert refreshed["sha256"] == "b" * 64
    assert refreshed["drive_file_id"] == "new-private-drive-file-identifier"
    assert refreshed["bytes"] == 4_000_000
    assert untouched["sha256"] == "a" * 64
    assert untouched["drive_file_id"] == "products-csv-drive-file-identifier"
    assert summary["web_dashboard"]["observations"] == 35
    assert summary["dashboard_refresh"]["raw_hdf5_replayed"] is False
    assert summary["dashboard_refresh"]["scientific_outputs_changed"] is False


def test_dashboard_refresh_rejects_invalid_signature_before_reading_job(monkeypatch) -> None:
    from types import SimpleNamespace

    job_id = uuid4()
    old_digest = "a" * 64
    store = _dashboard_refresh_store(job_id, old_digest)
    monkeypatch.setattr(main_module, "get_job_store", lambda: store)
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="refresh-secret"))
    body, _headers = _dashboard_refresh_request(job_id, old_digest)

    response = client.post(
        f"/api/displacement-jobs/{job_id}/dashboard-refresh",
        content=body,
        headers={"Content-Type": "application/json", "X-SARGuardian-Signature": "sha256=" + "0" * 64},
    )

    assert response.status_code == 401
    assert store.update_calls == 0


def test_dashboard_refresh_rejects_stale_original_bundle_hash(monkeypatch) -> None:
    from types import SimpleNamespace

    job_id = uuid4()
    store = _dashboard_refresh_store(job_id, "a" * 64)
    monkeypatch.setattr(main_module, "get_job_store", lambda: store)
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="refresh-secret"))
    body, headers = _dashboard_refresh_request(job_id, "c" * 64)

    response = client.post(f"/api/displacement-jobs/{job_id}/dashboard-refresh", content=body, headers=headers)

    assert response.status_code == 409
    assert store.update_calls == 0
    assert store.record["result_summary"]["artifacts"][0]["sha256"] == "a" * 64


def test_dashboard_refresh_rejects_changed_product_inventory(monkeypatch) -> None:
    from types import SimpleNamespace

    job_id = uuid4()
    old_digest = "a" * 64
    store = _dashboard_refresh_store(job_id, old_digest)
    monkeypatch.setattr(main_module, "get_job_store", lambda: store)
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="refresh-secret"))
    payload = json.loads(_dashboard_refresh_request(job_id, old_digest)[0])
    payload["web_dashboard"]["observations"] = 34
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-SARGuardian-Signature": "sha256=" + hmac.new(
        b"refresh-secret", body, hashlib.sha256
    ).hexdigest()}

    response = client.post(f"/api/displacement-jobs/{job_id}/dashboard-refresh", content=body, headers=headers)

    assert response.status_code == 422
    assert store.update_calls == 0


def test_dashboard_refresh_rejects_running_job(monkeypatch) -> None:
    from types import SimpleNamespace

    job_id = uuid4()
    store = _dashboard_refresh_store(job_id, "a" * 64)
    store.record["state"] = "running"
    monkeypatch.setattr(main_module, "get_job_store", lambda: store)
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="refresh-secret"))
    body, headers = _dashboard_refresh_request(job_id, "a" * 64)

    response = client.post(f"/api/displacement-jobs/{job_id}/dashboard-refresh", content=body, headers=headers)

    assert response.status_code == 409
    assert store.update_calls == 0


def test_interactive_dashboard_is_returned_only_for_verified_owner_and_uses_lazy_raster_assets(monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    job_id = uuid4()
    payload = _dashboard_zip_with_oversized_legacy_data()
    artifact = {
        "path": "aoi-derived-results.zip",
        "kind": "aoi_derived_result_bundle",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            assert requested_job_id == job_id
            if owner_uid != "test-user":
                return None
            return {
                "id": str(job_id),
                "owner_uid": owner_uid,
                "state": "succeeded",
                "result_summary": {
                    "web_dashboard": {"status": "PASS", "schema_version": "sarguardian-web-dashboard/1.0"},
                    "artifacts": [artifact],
                },
            }

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="dashboard-assets-test-secret"))
    def download_bundle_to_disk(_drive_id, destination, *, max_bytes=None):
        assert max_bytes == len(payload)
        Path(destination).write_bytes(payload)
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(main_module, "download_private_result_to_path", download_bundle_to_disk)

    # Google Maps is supplied by the same restricted browser key used by AOI selection.
    response = authenticated_client().get(f"/api/displacement-jobs/{job_id}/dashboard", headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "origin"
    assert "window.SARGUARDIAN_DASHBOARD=" in response.text
    assert "window.SARGUARDIAN_LAYER_DATA=" in response.text
    assert "__SARGUARDIAN_API_BASE__/api/displacement-jobs/" in response.text
    assert "/dashboard-assets/layers/test-layer.png?ticket=" in response.text
    assert "data:image/png;base64," not in response.text
    assert 'src="./dashboard-data.js"' not in response.text
    assert "Content-Security-Policy" in response.text
    assert "const maplibregl = await window.SARGUARDIAN_GOOGLE_MAPS_ADAPTER;" in response.text
    assert "https://maps.googleapis.com/maps/api/js?key=AIzaSyFakeRestrictedKey123456789012345" in response.text
    assert "&v=weekly&loading=async&callback=" in response.text
    assert 'var callbackName = "__sarguardianGoogleMapsLoaded";' in response.text
    assert "window[callbackName] = function()" in response.text
    assert "script.onload = function()" not in response.text
    assert "https://*.googleapis.com" in response.text
    assert "https://*.gstatic.com" in response.text
    assert "window.SARGUARDIAN_GOOGLE_MAPS_ADAPTER" in response.text
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" not in response.text
    assert "SARGuardian responsive science dashboard" in response.text
    assert 'id="sg-dashboard-readiness"' in response.text
    assert "Not measured is not the same as zero motion." in response.text
    assert "This scan checks the whole drawn area. A target point is not required." in response.text
    assert "Observation coverage" in response.text
    assert "Repeated anomaly fragments" in response.text
    assert "Separate legacy GOFF screen" in response.text
    assert "not the same count as the" in response.text
    assert "This is a network-data limitation, not a missing target point." in response.text
    assert "Structural and provenance checks only." in response.text
    assert "GUNW pairwise LOS fragments" in response.text
    assert "GOFF offset fragments" in response.text
    assert "no compatible repeated gunw network" in response.text.lower()
    assert "Target-local values are optional." in response.text
    assert "private-drive-file-id" not in response.text
    assert "Processing report ↗" not in response.text


def test_interactive_dashboard_uses_google_maps_key_and_adapter(monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    job_id = uuid4()
    payload = _dashboard_zip()
    artifact = {
        "path": "aoi-derived-results.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return {
                "id": str(job_id),
                "owner_uid": owner_uid,
                "state": "succeeded",
                "result_summary": {
                    "web_dashboard": {"status": "PASS"},
                    "artifacts": [artifact],
                },
            }

    called = []
    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="dashboard-assets-test-secret"))

    def download_verified_bundle(_drive_id, destination, *, max_bytes=None):
        called.append(True)
        Path(destination).write_bytes(payload)
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(main_module, "download_private_result_to_path", download_verified_bundle)
    response = authenticated_client().get(f"/api/displacement-jobs/{job_id}/dashboard", headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"})

    assert response.status_code == 200
    assert called == [True]
    assert "https://maps.googleapis.com/maps/api/js?key=AIzaSyFakeRestrictedKey123456789012345" in response.text
    assert "&v=weekly&loading=async&callback=" in response.text
    assert 'var callbackName = "__sarguardianGoogleMapsLoaded";' in response.text
    assert "window[callbackName] = function()" in response.text
    assert "const maplibregl = await window.SARGUARDIAN_GOOGLE_MAPS_ADAPTER;" in response.text


def test_dashboard_preview_asset_uses_cached_verified_bundle_and_short_lived_ticket(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    job_id = uuid4()
    payload = _dashboard_zip()
    artifact = {
        "path": "aoi-derived-results.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }
    record = {
        "id": str(job_id),
        "owner_uid": "test-user",
        "state": "succeeded",
        "result_summary": {
            "web_dashboard": {"status": "PASS"},
            "artifacts": [artifact],
        },
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            assert owner_uid == "test-user"
            assert requested_job_id == job_id
            return record

        def get_displacement_job_unscoped(self, requested_job_id):
            assert requested_job_id == job_id
            return record

    downloads = []
    def download_bundle_to_disk(_drive_id, destination, *, max_bytes=None):
        downloads.append(True)
        assert max_bytes == len(payload)
        Path(destination).write_bytes(payload)
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="dashboard-assets-test-secret"))
    monkeypatch.setattr(main_module, "download_private_result_to_path", download_bundle_to_disk)
    monkeypatch.setattr(main_module, "DASHBOARD_ARCHIVE_CACHE_ROOT", tmp_path)

    dashboard = authenticated_client().get(
        f"/api/displacement-jobs/{job_id}/dashboard",
        headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"},
    )
    assert dashboard.status_code == 200
    cache_file = next(tmp_path.glob("*.zip"))
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    assert (cache_file.stat().st_mode & 0o777) == 0o600

    # A viewer retry reuses the checksum-verified cache rather than fetching Drive again.
    retry = authenticated_client().get(
        f"/api/displacement-jobs/{job_id}/dashboard",
        headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"},
    )
    assert retry.status_code == 200
    assert downloads == [True]

    asset_marker = "/dashboard-assets/layers/test-layer.png?ticket="
    assert asset_marker in dashboard.text
    ticket = dashboard.text.split(asset_marker, 1)[1].split('"', 1)[0]

    preview = client.get(f"/api/displacement-jobs/{job_id}{asset_marker}{ticket}")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content == b"\x89PNG\r\n\x1a\npreview"
    assert downloads == [True]


def test_dashboard_shell_streams_manifest_larger_than_vercel_buffer_limit(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    job_id = uuid4()
    payload = _dashboard_zip(manifest_padding="x" * (5 * 1024 * 1024))
    artifact = {
        "path": "aoi-derived-results.zip",
        "kind": "aoi_derived_result_bundle",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return {
                "id": str(job_id),
                "owner_uid": owner_uid,
                "state": "succeeded",
                "result_summary": {"web_dashboard": {"status": "PASS"}, "artifacts": [artifact]},
            }

    def download_bundle(_drive_id, destination, *, max_bytes=None):
        Path(destination).write_bytes(payload)
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="dashboard-assets-test-secret"))
    monkeypatch.setattr(main_module, "DASHBOARD_ARCHIVE_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(main_module, "download_private_result_to_path", download_bundle)

    response = authenticated_client().get(
        f"/api/displacement-jobs/{job_id}/dashboard",
        headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"},
    )
    assert response.status_code == 200
    assert len(response.content) > 4.5 * 1024 * 1024
    assert "window.SARGUARDIAN_DASHBOARD=" in response.text


def test_large_candidate_manifest_is_compacted_for_browser_without_changing_saved_result(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    job_id = uuid4()
    # The source manifest is >16 MiB because the candidate FeatureCollection
    # carries large per-feature metadata. That metadata remains in the verified
    # ZIP; the browser only receives the properties needed by its candidate map.
    payload = _dashboard_zip(
        candidate_feature_count=150,
        candidate_feature_padding="x" * 120_000,
    )
    with ZipFile(BytesIO(payload), "r") as source_archive:
        source_manifest = json.loads(source_archive.read("web-dashboard/manifest.json"))
    source_features = source_manifest["aoi_wide_displacement_screen"]["candidate_feature_collection"]["features"]
    assert len(json.dumps(source_manifest).encode("utf-8")) > main_module.MAX_DASHBOARD_MANIFEST_BYTES

    artifact = {
        "path": "aoi-derived-results.zip",
        "kind": "aoi_derived_result_bundle",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }
    record = {
        "id": str(job_id),
        "owner_uid": "test-user",
        "state": "succeeded",
        "result_summary": {
            "web_dashboard": {"status": "PASS", "schema_version": "sarguardian-web-dashboard/1.0"},
            "artifacts": [artifact],
        },
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return record if owner_uid == "test-user" and requested_job_id == job_id else None

    def download_bundle(_drive_id, destination, *, max_bytes=None):
        Path(destination).write_bytes(payload)
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="dashboard-assets-test-secret"))
    monkeypatch.setattr(main_module, "DASHBOARD_ARCHIVE_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(main_module, "download_private_result_to_path", download_bundle)

    response = authenticated_client().get(
        f"/api/displacement-jobs/{job_id}/dashboard",
        headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"},
    )

    assert response.status_code == 200
    assert len(response.content) < 4.5 * 1024 * 1024
    assert "candidate_features_total" in response.text
    assert '"candidate_features_displayed":100' in response.text
    assert '"candidate_features_omitted_from_map":50' in response.text
    assert '"candidate_properties_reduced_for_display":true' in response.text
    assert "Map display note:" in response.text
    assert "original candidate GeoJSON and scientific artifacts remain unchanged" in response.text
    assert len(source_features) == 150
    # The private ZIP itself is still byte-for-byte the original object.
    assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_candidate_polygon_display_simplification_preserves_a_closed_ring() -> None:
    ring = [[float(index), float((index * 7) % 19)] for index in range(360)]
    ring.append(ring[0])

    simplified, changed = main_module._simplify_geojson_ring_for_display(ring)

    assert changed is True
    assert len(simplified) <= main_module.MAX_DASHBOARD_CANDIDATE_RING_POINTS
    assert simplified[0] == simplified[-1]
    assert len(simplified) >= 4


def test_dashboard_preview_streams_png_larger_than_vercel_buffer_limit(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    job_id = uuid4()
    preview_bytes = b"\x89PNG\r\n\x1a\n" + (b"x" * (5 * 1024 * 1024))
    payload = _dashboard_zip(preview=preview_bytes)
    artifact = {
        "path": "aoi-derived-results.zip",
        "kind": "aoi_derived_result_bundle",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }
    record = {
        "id": str(job_id),
        "owner_uid": "test-user",
        "state": "succeeded",
        "result_summary": {"web_dashboard": {"status": "PASS"}, "artifacts": [artifact]},
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return record if owner_uid == "test-user" and requested_job_id == job_id else None

        def get_displacement_job_unscoped(self, requested_job_id):
            return record if requested_job_id == job_id else None

    def download_bundle(_drive_id, destination, *, max_bytes=None):
        Path(destination).write_bytes(payload)
        return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(displacement_callback_secret="dashboard-assets-test-secret"))
    monkeypatch.setattr(main_module, "DASHBOARD_ARCHIVE_CACHE_ROOT", tmp_path)
    monkeypatch.setattr(main_module, "download_private_result_to_path", download_bundle)

    dashboard = authenticated_client().get(
        f"/api/displacement-jobs/{job_id}/dashboard",
        headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"},
    )
    marker = "/dashboard-assets/layers/test-layer.png?ticket="
    ticket = dashboard.text.split(marker, 1)[1].split('"', 1)[0]
    response = client.get(f"/api/displacement-jobs/{job_id}{marker}{ticket}")
    assert response.status_code == 200
    assert len(response.content) == len(preview_bytes)
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_private_result_artifact_streams_large_verified_download(monkeypatch) -> None:
    from uuid import uuid4

    job_id = uuid4()
    artifact_bytes = b"private-result-" + (b"x" * (5 * 1024 * 1024))
    artifact = {
        "path": "aoi-derived-results.zip",
        "kind": "aoi_derived_result_bundle",
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "bytes": len(artifact_bytes),
        "drive_file_id": "private-drive-file-id",
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            assert owner_uid == "test-user"
            assert requested_job_id == job_id
            return {"state": "succeeded", "result_summary": {"artifacts": [artifact]}}

    def download_bundle(_drive_id, destination, *, max_bytes=None):
        Path(destination).write_bytes(artifact_bytes)
        return {"bytes": len(artifact_bytes), "sha256": hashlib.sha256(artifact_bytes).hexdigest()}

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "download_private_result_to_path", download_bundle)

    response = authenticated_client().get(f"/api/displacement-jobs/{job_id}/artifacts/0")
    assert response.status_code == 200
    assert response.content == artifact_bytes
    assert response.headers["cache-control"] == "private, no-store"


def test_interactive_dashboard_requires_maps_key_before_private_download(monkeypatch) -> None:
    from uuid import uuid4

    job_id = uuid4()
    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return {
                "id": str(job_id),
                "owner_uid": owner_uid,
                "state": "succeeded",
                "result_summary": {
                    "web_dashboard": {"status": "PASS"},
                    "artifacts": [{
                        "path": "aoi-derived-results.zip",
                        "sha256": "a" * 64,
                        "bytes": 100,
                        "drive_file_id": "private-drive-file-id",
                    }],
                },
            }
    called = []
    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "download_private_result_to_path", lambda *_args, **_kwargs: called.append(True))
    response = authenticated_client().get(f"/api/displacement-jobs/{job_id}/dashboard")
    assert response.status_code == 503
    assert "Google Maps is not configured" in response.json()["detail"]
    assert called == []


def test_interactive_dashboard_rejects_unavailable_old_bundle_without_drive_download(monkeypatch) -> None:
    from uuid import uuid4

    job_id = uuid4()

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return {
                "id": str(job_id),
                "state": "succeeded",
                "result_summary": {
                    "web_dashboard": {"status": "NOT_AVAILABLE"},
                    "artifacts": [],
                },
            }

    called = []
    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    monkeypatch.setattr(main_module, "download_private_result_to_path", lambda *_args, **_kwargs: called.append(True))

    response = authenticated_client().get(f"/api/displacement-jobs/{job_id}/dashboard")

    assert response.status_code == 404
    assert called == []


def test_interactive_dashboard_rejects_drive_checksum_mismatch(monkeypatch) -> None:
    from uuid import uuid4

    job_id = uuid4()
    payload = _dashboard_zip()
    wrong_payload = b"not-the-verified-bundle"
    artifact = {
        "path": "aoi-derived-results.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "drive_file_id": "private-drive-file-id",
    }

    class Store:
        def get_displacement_job(self, owner_uid, requested_job_id):
            return {
                "id": str(job_id),
                "state": "succeeded",
                "result_summary": {
                    "web_dashboard": {"status": "PASS"},
                    "artifacts": [artifact],
                },
            }

    monkeypatch.setattr(main_module, "get_job_store", lambda: Store())
    def download_wrong_bundle_to_disk(_drive_id, destination, *, max_bytes=None):
        Path(destination).write_bytes(wrong_payload)
        return {"bytes": len(wrong_payload), "sha256": hashlib.sha256(wrong_payload).hexdigest()}

    monkeypatch.setattr(main_module, "download_private_result_to_path", download_wrong_bundle_to_disk)

    response = authenticated_client().get(f"/api/displacement-jobs/{job_id}/dashboard", headers={"X-SARGuardian-Google-Maps-Key": "AIzaSyFakeRestrictedKey123456789012345"})

    assert response.status_code == 409
    assert "checksum" in response.json()["detail"]


def test_dashboard_presentation_uses_native_audience_controls_without_duplicate_wrapper() -> None:
    html = """<!doctype html><html><head><style>body{margin:0}</style></head><body><main>
      <header><h1>What did NISAR observe?</h1></header>
      <nav class="view-switcher" aria-label="Dashboard audience view">
        <button type="button" data-sg-mode="public" aria-selected="true">Public Discovery</button>
        <button type="button" data-sg-mode="evidence" aria-selected="false">Explore the Evidence</button>
        <button type="button" data-sg-mode="science" aria-selected="false">Scientific Evidence</button>
      </nav>
      <div class="warn">Processing PASS is not independent geophysical validation.</div>
      <section class="quick-panel"><div id="runStory"></div></section>
      <div class="cards" id="summaryCards"></div>
      <div class="layout">
        <section class="panel"><div class="mapbox"><div id="map"></div></div><input id="timeline" type="range"></section>
        <aside class="panel"><div class="kicker">Selected image pair</div><h2 id="productTitle">Pair</h2>
          <p id="productDescription">Real acquisition pair.</p><div id="productMetrics"></div>
          <details><div id="productTechnicalMetrics"></div></details>
          <label>Pair<select id="productSelect"></select></label><details><svg id="supportChart"></svg></details>
          <details><svg id="measurementChart"></svg></details><section class="candidate-section"><div id="aoiCandidateStatus"></div></section>
          <details><div id="scienceStages"></div></details>
        </aside>
      </div>
      <script type="module">let M=null,selected=0,playing=false,timer=null,activeLayer=null;M.addControl(new maplibregl.NavigationControl(),'top-right');M.on('load',function(){});</script>
    </main></body></html>"""

    rendered = main_module._apply_dashboard_presentation(html)

    assert rendered.count('data-sg-mode="public"') == 1
    assert rendered.count('data-sg-mode="evidence"') == 1
    assert rendered.count('data-sg-mode="science"') == 1
    assert 'id="sgDashboardModes"' not in rendered
    assert 'id="sg-dashboard-modes-script"' not in rendered
    assert 'id="sg-native-dashboard-mode-resize"' in rendered
    assert 'id="sg-dashboard-readiness"' in rendered
    assert "window.addEventListener('sarguardian:dashboard-mode'" in rendered
    assert "window.dispatchEvent(new CustomEvent('sarguardian:dashboard-mode'" in rendered
    assert 'id="sgRunReadiness"' in rendered
    assert 'id="map"' in rendered
    assert 'id="timeline"' in rendered



def test_interactive_dashboard_requires_authentication() -> None:
    response = client.get(f"/api/displacement-jobs/{uuid4()}/dashboard")
    assert response.status_code == 401


def test_dashboard_presentation_builds_three_audience_views_without_replacing_science_controls() -> None:
    html = """<!doctype html><html><head></head><body><main>
      <header><h1>What did NISAR observe?</h1></header>
      <div class="warn">Processing PASS is not independent geophysical validation.</div>
      <section class="quick-panel"><div id="runStory"></div></section>
      <div class="cards" id="summaryCards"></div>
      <div class="layout">
        <section class="panel"><div class="mapbox"><div id="map"></div></div>
          <input id="timeline" type="range"><select id="bandSelect"></select>
        </section>
        <aside class="panel">
          <div class="kicker">Selected image pair</div><h2 id="productTitle">Pair</h2>
          <p id="productDescription">Real acquisition pair.</p><div id="productMetrics"></div>
          <details><div id="productTechnicalMetrics"></div></details>
          <label>Pair<select id="productSelect"></select></label>
          <details><svg id="supportChart"></svg></details>
          <details><svg id="measurementChart"></svg></details>
          <section class="candidate-section"><div id="aoiCandidateStatus"></div></section>
          <details><div id="scienceStages"></div></details>
        </aside>
      </div>
      <script type="module">let M=null,selected=0,playing=false,timer=null,activeLayer=null;M.addControl(new maplibregl.NavigationControl(),'top-right');M.on('load',function(){});</script>
    </main></body></html>"""

    rendered = main_module._apply_dashboard_presentation(html)

    assert 'id="sgDashboardModes"' in rendered
    assert 'data-sg-mode="public"' in rendered
    assert 'data-sg-mode="evidence"' in rendered
    assert 'data-sg-mode="science"' in rendered
    assert "Public Discovery" in rendered
    assert "Explore the Evidence" in rendered
    assert "Scientific Evidence" in rendered
    assert "publicPage.id='sgPublicView';" in rendered
    assert "evidencePage.id='sgEvidenceView';" in rendered
    assert "sciencePage.id='sgScienceView';" in rendered
    assert "Candidate pattern" in rendered
    assert "Measured displacement" in rendered
    assert "Not assessed" in rendered
    assert "GUNW values are pairwise line-of-sight observations" in rendered
    assert "GOFF offset anomalies are candidate patterns" in rendered
    assert "Not measured is not the same as zero motion." in rendered
    assert 'id="map"' in rendered
    assert 'id="timeline"' in rendered
    assert 'id="bandSelect"' in rendered
    assert 'id="productTechnicalMetrics"' in rendered
    assert 'id="measurementChart"' in rendered
    assert 'id="aoiCandidateStatus"' in rendered
    assert 'id="scienceStages"' in rendered
    assert "sarguardian:dashboard-mode" in rendered
    assert "requestAnimationFrame(function(){M.resize();});" in rendered
    assert "12 cm/year" not in rendered
    assert ">70% confidence" not in rendered
