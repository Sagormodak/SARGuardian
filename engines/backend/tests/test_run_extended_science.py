import json
import zipfile
from pathlib import Path

import pytest

from tools import run_extended_science as extension


def _valid_manifest(source_run_id="12345"):
    products = []
    for i in range(15):
        products.append({
            "id": f"GUNW-{i + 1:03d}",
            "product_type": "GUNW",
            "granule_name": f"NISAR_L2_PR_GUNW_SAMPLE_{i:03d}.h5",
            "maturity": "PROVISIONAL",
        })
    for i in range(18):
        products.append({
            "id": f"GOFF-{i + 1:03d}",
            "product_type": "GOFF",
            "granule_name": f"NISAR_L2_PR_GOFF_SAMPLE_{i:03d}.h5",
            "maturity": "PROVISIONAL",
        })
    return {
        "schema_version": "sarguardian-stream-run-manifest/1.0",
        "run_id": f"{source_run_id}-1",
        "run_profile": "full-source-baseline",
        "aoi": "source",
        "science_commit": extension.PINNED_SCIENCE_COMMIT,
        "retention_profile": "derived-only",
        "products": products,
    }


def _valid_report():
    return {
        "status": "PASS",
        "products_expected": 33,
        "products_validated": 33,
        "errors": [],
        "comparisons": [{"table": "fixture", "status": "PASS"}],
        "retention_storage_accounting": {"status": "PASS"},
    }


def _write_bundle(path: Path, include_traversal=False):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("run-manifest.json", json.dumps(_valid_manifest()))
        archive.writestr("batch-equivalence-report.json", json.dumps(_valid_report()))
        required_csvs = [
            "gunw_stats_source.csv",
            "goff_stats_source.csv",
            "scar_candidates_source.csv",
            "ts_goff_source.csv",
            "troposphere_gunw_source.csv",
            "troposphere_goff_source.csv",
        ]
        for filename in required_csvs:
            archive.writestr(f"outputs/{filename}", "file,layer\nfixture,layer2\n")
        archive.writestr("outputs/export_src/fixture.tif", "fixture")
        archive.writestr("outputs/export_goff_src/fixture.tif", "fixture")
        archive.writestr("outputs/raw-fixture.h5", "raw data must not be extracted")
        if include_traversal:
            archive.writestr("outputs/../escape.txt", "blocked")


def test_source_bundle_validator_rejects_pilot_profile():
    manifest = _valid_manifest()
    report = _valid_report()
    manifest["run_profile"] = "validation-pilot"
    with pytest.raises(extension.ExtensionError, match="SOURCE_RUN_PROFILE_NOT_FULL_BASELINE"):
        extension._validate_report(manifest, report, "12345")


def test_source_bundle_extraction_skips_raw_hdf5(tmp_path):
    bundle = tmp_path / "source.zip"
    science_root = tmp_path / "science"
    package_root = tmp_path / "package"
    package_root.mkdir()
    _write_bundle(bundle)

    manifest, report, raw_hdf5_skipped = extension.validate_and_extract_bundle(
        bundle, "12345", science_root, package_root
    )

    assert manifest["run_profile"] == "full-source-baseline"
    assert report["status"] == "PASS"
    assert raw_hdf5_skipped == 1
    assert (science_root / "outputs" / "gunw_stats_source.csv").is_file()
    assert (science_root / "outputs" / "export_src" / "fixture.tif").is_file()
    assert not (science_root / "outputs" / "raw-fixture.h5").exists()
    assert (package_root / "source-run-manifest.json").is_file()
    assert (package_root / "source-batch-equivalence-report.json").is_file()


def test_source_bundle_validator_rejects_path_traversal(tmp_path):
    bundle = tmp_path / "traversal.zip"
    science_root = tmp_path / "science"
    package_root = tmp_path / "package"
    package_root.mkdir()
    _write_bundle(bundle, include_traversal=True)

    with pytest.raises(extension.ExtensionError, match="SOURCE_BUNDLE_PATH_TRAVERSAL_REJECTED"):
        extension.validate_and_extract_bundle(bundle, "12345", science_root, package_root)
