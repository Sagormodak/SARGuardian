from __future__ import annotations

from pathlib import Path

from tools import product_retry_gate as gate


def _full_manifest() -> dict:
    products = []
    for family, count in (("GUNW", 15), ("GOFF", 18)):
        for index in range(1, count + 1):
            product_index = len(products) + 1
            products.append({
                "id": f"{family}-{product_index:03d}",
                "product_type": family,
                "granule_name": f"NISAR_L2_{family}_TEST_PRODUCT_{index:03d}.h5",
                "maturity": "BETA",
                "expected_source_bytes": 2_400_000_000 if family == "GUNW" else 1_000_000_000,
            })
    return {
        "run_id": "test-run-1",
        "run_profile": "full-source-baseline",
        "aoi": "source",
        "science_commit": gate.__dict__.get("SCIENCE_COMMIT", "ab547ecc82bcc4d6ccef545a59852536c2beacc6"),
        "retention_profile": "derived-only",
        "products": products,
    }


def _patched_validators(monkeypatch, valid_granule_locations, valid_cleanup_locations):
    def valid_granule(path: Path, product: dict, manifest: dict):
        return (
            (path.parent.name, path.name) in valid_granule_locations,
            "reusable" if (path.parent.name, path.name) in valid_granule_locations else "fixture_missing_granule",
        )

    def valid_cleanup(path: Path, product: dict, manifest: dict, folder: str):
        return (
            (path.parent.name, path.name) in valid_cleanup_locations,
            "reusable" if (path.parent.name, path.name) in valid_cleanup_locations else "fixture_missing_cleanup",
        )

    monkeypatch.setattr(gate, "_valid_granule", valid_granule)
    monkeypatch.setattr(gate, "_valid_cleanup", valid_cleanup)

    def fake_read_json(path: Path):
        if path.name == "product-processing.json":
            return {"drive_remote_folder_id": "fixture-folder"}
        if path.name == "drive-metadata-upload-receipt.json":
            return {
                "remote_verification": "PASS",
                "remote_folder_id": "fixture-folder",
                "files": [
                    {"name": "product-processing.json"},
                    {"name": "drive-retention-receipt.json"},
                ],
            }
        return None

    monkeypatch.setattr(gate, "read_json", fake_read_json)


def test_retry_plan_only_retries_products_without_complete_current_receipts(tmp_path, monkeypatch):
    manifest = _full_manifest()
    expected = [manifest["products"][0], manifest["products"][-1]]
    valid_g = {("granules", "sarguardian-granule-GUNW-001")}
    valid_c = {("cleanups", "sarguardian-cleanup-GUNW-001")}
    _patched_validators(monkeypatch, valid_g, valid_c)

    report = gate.build_retry_plan(
        manifest,
        expected,
        tmp_path / "granules",
        tmp_path / "cleanups",
    )

    assert report["products_checked"] == 2
    assert report["products_verified"] == 1
    assert report["retry_product_ids"] == ["GOFF-033"]
    assert report["products_to_retry"] == 1


def test_preassembly_verification_accepts_current_and_resume_checkpoints(tmp_path, monkeypatch):
    manifest = _full_manifest()
    current_g = tmp_path / "current-granules"
    current_c = tmp_path / "current-cleanups"
    previous_g = tmp_path / "previous-granules"
    previous_c = tmp_path / "previous-cleanups"
    for root in (current_g, current_c, previous_g, previous_c):
        root.mkdir()

    valid_g = {
        ("current-granules", "sarguardian-granule-GUNW-001"),
        ("current-granules", "sarguardian-granule-GUNW-002"),
    }
    valid_c = {
        ("current-cleanups", "sarguardian-cleanup-GUNW-001"),
        ("current-cleanups", "sarguardian-cleanup-GUNW-002"),
    }
    for product in manifest["products"][2:]:
        pid = product["id"]
        if pid == "GOFF-033":
            continue
        valid_g.add(("previous-granules", f"sarguardian-granule-{pid}"))
        valid_c.add(("previous-cleanups", f"sarguardian-cleanup-{pid}"))
    _patched_validators(monkeypatch, valid_g, valid_c)

    report = gate.verify_manifest_checkpoints(
        manifest, current_g, current_c, previous_g, previous_c
    )

    assert report["status"] == "FAIL"
    assert report["expected_products"] == 33
    assert report["verified_products"] == 32
    assert report["current_run_checkpoints"] == 2
    assert report["resume_source_checkpoints"] == 30
    assert report["missing_or_invalid_product_ids"] == ["GOFF-033"]


def test_missing_metadata_upload_receipt_triggers_product_retry(tmp_path, monkeypatch):
    manifest = _full_manifest()
    expected = [manifest["products"][0], manifest["products"][-1]]
    valid_g = {
        ("granules", "sarguardian-granule-GUNW-001"),
        ("granules", "sarguardian-granule-GOFF-033"),
    }
    valid_c = {
        ("cleanups", "sarguardian-cleanup-GUNW-001"),
        ("cleanups", "sarguardian-cleanup-GOFF-033"),
    }
    _patched_validators(monkeypatch, valid_g, valid_c)
    original_read_json = gate.read_json

    def missing_retry_receipt(path: Path):
        if path.name == "drive-metadata-upload-receipt.json" and path.parent.name == "sarguardian-granule-GOFF-033":
            return None
        return original_read_json(path)

    monkeypatch.setattr(gate, "read_json", missing_retry_receipt)
    report = gate.build_retry_plan(
        manifest, expected, tmp_path / "granules", tmp_path / "cleanups"
    )

    assert report["products_verified"] == 1
    assert report["retry_product_ids"] == ["GOFF-033"]


def test_full_baseline_guard_rejects_wrong_product_count():
    manifest = _full_manifest()
    manifest["products"] = manifest["products"][:-1]
    try:
        gate._validate_manifest(manifest)
    except ValueError as exc:
        assert "FULL_BASELINE_PRODUCT_COUNTS_INVALID" in str(exc)
    else:
        raise AssertionError("Expected an invalid full-baseline manifest to be rejected")


def test_zero_product_resume_produces_empty_retry_plan_without_inventing_products(tmp_path):
    manifest = _full_manifest()

    report = gate.build_retry_plan(
        manifest,
        [],
        tmp_path / "granules",
        tmp_path / "cleanups",
    )

    assert report["products_checked"] == 0
    assert report["products_verified"] == 0
    assert report["products_to_retry"] == 0
    assert report["retry_product_ids"] == []
    assert report["retry_products"] == []
    assert report["decisions"] == []
