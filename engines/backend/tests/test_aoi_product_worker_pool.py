from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sarguardian-aoi-wkt-dashboard.yml"
sys.path.insert(0, str(ROOT / "tools"))

from drive_resumable_upload import DriveError
from prepare_aoi_drive_folders import prepare_drive_folders


class FakeDrive:
    def __init__(self):
        self.created = []

    def ensure_folder(self, parent, name):
        self.created.append((parent, name))
        return f"folder-{len(self.created)}"


def sample_manifest():
    return {
        "products": [
            {"id": "GUNW-001", "product_type": "GUNW", "maturity": "PROVISIONAL",
             "granule_name": "NISAR_L2_PR_GUNW_AAAAAAAAAAAA.h5"},
            {"id": "GUNW-002", "product_type": "GUNW", "maturity": "PROVISIONAL",
             "granule_name": "NISAR_L2_PR_GUNW_BBBBBBBBBBBB.h5"},
            {"id": "GOFF-003", "product_type": "GOFF", "maturity": "BETA",
             "granule_name": "NISAR_L2_PR_GOFF_CCCCCCCCCCCC.h5"},
        ]
    }


def test_aoi_workflow_bounds_initial_and_retry_workers_at_fifteen():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("max-parallel: 15") == 2
    assert "  process-products:\n" in text
    assert "  retry-plan:\n" in text
    assert "  retry-products:\n" in text
    assert "sarguardian-aoi-retry-plan" in text
    assert "execution_label: initial" in text
    assert "execution_label: retry-1" in text
    assert "needs: [manifest, process-products, retry-plan, retry-products]" in text
    assert not any(line.strip() == "max-parallel: 1" for line in text.splitlines())


def test_manifest_pins_worker_tools_to_the_dispatch_revision():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = text.split("  manifest:\n", 1)[1].split("  process-products:\n", 1)[0]
    assert "AOI_ORCHESTRATION_BRANCH: ${{ github.ref_name }}" in manifest
    assert "Checkout backend orchestration tools at the dispatched workflow revision" in manifest
    checkout = manifest.split("Checkout backend orchestration tools at the dispatched workflow revision", 1)[1].split(
        "- name:", 1
    )[0]
    assert "ref: ${{ github.sha }}" in checkout


def test_worker_records_explicit_no_valid_pixels_without_masking_real_reader_errors():
    worker = (ROOT / ".github" / "workflows" / "sarguardian-aoi-product-worker.yml").read_text(encoding="utf-8")
    reader = worker.split("- name: Run the original single-product reader with dynamic WKT-AOI settings", 1)[1].split(
        "- name: Measure target-local detection floors", 1
    )[0]
    assert 'reader_log="$CURATED_DIR/derived/science-reader.log"' in reader
    assert '2>&1 | tee "$reader_log"' in reader
    missing_guard = reader.index('if [[ ! -s "$stats" ]]')
    helper = reader.index("tools/write_no_valid_pixel_stats.py", missing_guard)
    final_check = reader.index('test -s "$stats"', helper)
    assert missing_guard < helper < final_check
    assert '--reader-log "$reader_log"' in reader
    assert '--raw-product "$RAW_PATH" --product-type "$PRODUCT_TYPE"' in reader
    assert "NO VALID PIXELS" in (ROOT / "tools" / "write_no_valid_pixel_stats.py").read_text(encoding="utf-8")


def test_drive_shared_folders_are_prepared_before_parallel_matrix():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = text.split("  manifest:\n", 1)[1].split("  process-products:\n", 1)[0]
    assert "path: workflow-support" in manifest
    assert "ref: ${{ github.sha }}" in manifest
    assert "Prepare shared Drive folder hierarchy before parallel product workers" in manifest
    assert manifest.index("Validate WKT, search ASF exact polygon and build input manifest") < manifest.index(
        "Prepare shared Drive folder hierarchy before parallel product workers"
    )
    assert manifest.index("Prepare shared Drive folder hierarchy before parallel product workers") < manifest.index(
        "Publish the selected-product manifest"
    )
    assert "DRIVE_VERSION_TAG: ${{ github.run_id }}-${{ github.run_attempt }}" in manifest


def test_folder_preflight_creates_each_shared_edge_only_once():
    drive = FakeDrive()
    count = prepare_drive_folders(
        sample_manifest(), drive, parent_id="root-parent", version_tag="12345-1"
    )
    assert count == 3
    assert len(drive.created) == 5
    assert drive.created == [
        ("root-parent", "SARGuardian-DataArchive"),
        ("folder-1", "GUNW"),
        ("folder-2", "PROVISIONAL"),
        ("folder-1", "GOFF"),
        ("folder-4", "BETA"),
    ]


def test_folder_preflight_rejects_duplicate_product_before_drive_mutation():
    manifest = sample_manifest()
    manifest["products"].append(dict(manifest["products"][0], id="GUNW-004"))
    drive = FakeDrive()
    with pytest.raises(ValueError, match="AOI_MANIFEST_DUPLICATE_OR_INCOMPLETE_PRODUCT"):
        prepare_drive_folders(manifest, drive, parent_id="root-parent", version_tag="12345-1")
    assert drive.created == []


def test_folder_preflight_rejects_empty_manifest_before_drive_mutation():
    drive = FakeDrive()
    with pytest.raises(ValueError, match="AOI_MANIFEST_HAS_NO_SELECTED_PRODUCTS"):
        prepare_drive_folders({"products": []}, drive, parent_id="root-parent", version_tag="12345-1")
    assert drive.created == []

from write_no_valid_pixel_stats import write_no_valid_pixel_stats


def test_no_valid_pixels_creates_warning_row_without_invented_measurement(tmp_path):
    raw = tmp_path / "NISAR_L2_PR_GOFF_EXAMPLE.h5"
    raw.write_bytes(b"identity-only test file")
    log = tmp_path / "reader.log"
    log.write_text(
        "=== product ===\n"
        "  --- HH/layer2 ---\n"
        "    finite 1000\n"
        "    inside AOI 0\n"
        "    NO VALID PIXELS\n"
        "  --- VV/layer2 ---\n"
        "    finite 2000\n"
        "    inside AOI 0\n"
        "    NO VALID PIXELS\n",
        encoding="utf-8",
    )
    out = tmp_path / "derived" / "stats.csv"

    result = write_no_valid_pixel_stats(log, out, raw, "GOFF")

    import csv
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert result["status"] == "NO_VALID_PIXELS_AFTER_AOI_AND_QUALITY_GATES"
    assert result["valid_pixels"] == 0
    assert result["measurement_reported"] is False
    assert len(rows) == 1
    assert rows[0]["file"] == raw.name
    assert rows[0]["layer"] == "layer2 (no valid pixels)"
    assert rows[0]["valid_px"] == "0"
    assert rows[0]["maturity"] == "UNKNOWN"
    assert rows[0]["science_status"] == "NO_VALID_PIXELS_AFTER_AOI_AND_QUALITY_GATES"
    assert not any("median" in field.lower() or "velocity" in field.lower() for field in rows[0])


def test_no_valid_pixels_helper_fails_closed_for_missing_or_mixed_markers(tmp_path):
    raw = tmp_path / "NISAR_L2_PR_GOFF_EXAMPLE.h5"
    raw.write_bytes(b"test")
    log = tmp_path / "reader.log"
    log.write_text(
        "--- HH/layer2 ---\nNO VALID PIXELS\n"
        "--- VV/layer2 ---\nrange offset median 23 mm\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="NO_VALID_PIXEL_MARKER_NOT_CONFIRMED"):
        write_no_valid_pixel_stats(log, tmp_path / "stats.csv", raw, "GOFF")
    assert not (tmp_path / "stats.csv").exists()


def test_no_valid_pixels_helper_does_not_overwrite_existing_reader_csv(tmp_path):
    raw = tmp_path / "NISAR_L2_PR_GOFF_EXAMPLE.h5"
    raw.write_bytes(b"test")
    log = tmp_path / "reader.log"
    log.write_text("--- HH/layer2 ---\nNO VALID PIXELS\n", encoding="utf-8")
    out = tmp_path / "stats.csv"
    out.write_text("file,layer\nexisting,layer2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="REFUSING_TO_REPLACE_EXISTING_READER_STATS"):
        write_no_valid_pixel_stats(log, out, raw, "GOFF")
    assert out.read_text(encoding="utf-8").startswith("file,layer")


def test_no_valid_pixels_helper_supports_gunw_without_fake_metrics(tmp_path):
    raw = tmp_path / "NISAR_L2_PR_GUNW_EXAMPLE.h5"
    raw.write_bytes(b"test")
    log = tmp_path / "reader.log"
    log.write_text(
        "--- unwrappedInterferogram/HH ---\nNO VALID PIXELS\n",
        encoding="utf-8",
    )
    out = tmp_path / "gunw-stats.csv"
    result = write_no_valid_pixel_stats(log, out, raw, "GUNW")
    assert result["valid_pixels"] == 0
    assert "median" not in out.read_text(encoding="utf-8").lower()



def test_no_valid_pixels_helper_replaces_only_a_zero_byte_reader_csv(tmp_path):
    raw = tmp_path / "NISAR_L2_PR_GOFF_EXAMPLE.h5"
    raw.write_bytes(b"test")
    log = tmp_path / "reader.log"
    log.write_text("--- HH/layer2 ---\nNO VALID PIXELS\n", encoding="utf-8")
    out = tmp_path / "stats.csv"
    out.touch()

    result = write_no_valid_pixel_stats(log, out, raw, "GOFF")

    assert result["measurement_reported"] is False
    assert out.stat().st_size > 0
    assert "NO_VALID_PIXELS_AFTER_AOI_AND_QUALITY_GATES" in out.read_text(encoding="utf-8")


def test_manifest_orchestration_branch_is_passed_to_both_worker_matrices():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    manifest = workflow.split("  manifest:\n", 1)[1].split("  process-products:\n", 1)[0]
    assert "orchestration_branch: ${{ steps.orch.outputs.branch }}" in manifest
    assert 'branch="${AOI_ORCHESTRATION_BRANCH:?AOI_ORCHESTRATION_BRANCH must be set}"' in manifest
    assert 'echo "branch=$branch" >> "$GITHUB_OUTPUT"' in manifest

    initial_block = workflow.split("  process-products:\n", 1)[1].split("  retry-plan:", 1)[0]
    retry_block = workflow.split("  retry-products:\n", 1)[1].split("  dashboard:", 1)[0]
    assert "orchestration_branch: ${{ needs.manifest.outputs.orchestration_branch }}" in initial_block
    assert "orchestration_branch: ${{ needs.manifest.outputs.orchestration_branch }}" in retry_block

    worker = (ROOT / ".github" / "workflows" / "sarguardian-aoi-product-worker.yml").read_text(encoding="utf-8")
    assert "      orchestration_branch:\n        required: true\n        type: string" in worker
    assert "AOI_ORCHESTRATION_BRANCH: ${{ inputs.orchestration_branch }}" in worker
    assert "AOI_ORCHESTRATION_BRANCH: feat/final-aoi-science-integration" not in worker
