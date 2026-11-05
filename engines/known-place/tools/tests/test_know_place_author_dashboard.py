from __future__ import annotations

import base64
import csv
import json
import re
import struct
import zlib
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from tools.know_place.author_dashboard import build_dashboard, write_dashboard


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_tif(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:32645",
        transform=Affine(80, 0, 351120, 0, -80, 3135040),
        nodata=-9999,
    ) as dst:
        dst.write(values.astype("float32"), 1)


def _fixture(root: Path) -> Path:
    root.mkdir(parents=True)
    h, w = 73, 80
    y, x = np.mgrid[:h, :w]
    east = (x - w / 2) / 40.0
    north = (h / 2 - y) / 35.0
    valid = np.ones((h, w), dtype=bool)
    valid[0, :10] = False
    east[~valid] = np.nan
    north[~valid] = np.nan
    crown = np.zeros((h, w), dtype=bool)
    crown[28:45, 30:49] = True
    coherence = np.where(valid, 0.65 + 0.3 * (x / w), np.nan).astype("float32")
    np.savez_compressed(
        root / "20260726__20260819_author_site_series_arrays.npz",
        east_m=east.astype("float32"),
        north_m=north.astype("float32"),
        valid_mask=valid,
        crown_mask=crown,
        directional_coherence_R=coherence,
    )

    grid = (np.arange(h * w, dtype=np.float32).reshape(h, w) % 500) / 100.0
    _write_tif(root / "footprint" / "mean_anomaly_m.tif", grid)
    _write_tif(root / "footprint" / "mean_coherence_R.tif", np.full((h, w), 0.85, dtype=np.float32))
    epochs = (np.indices((h, w)).sum(axis=0) % 6).astype("float32")
    epochs[0, :10] = -9999
    _write_tif(root / "footprint" / "n_epochs_flagged.tif", epochs)

    pairs = [
        ("2026-06-20->2026-07-02", 283, 0.995, 8.29),
        ("2026-07-02->2026-07-14", 294, 0.539, 4.49),
        ("2026-07-14->2026-07-26", 296, 0.296, 2.46),
        ("2026-07-26->2026-08-19", 292, 0.9645, 4.02),
        ("2026-08-19->2026-08-31", 195, 0.328, 2.73),
    ]
    with (root / "author-raw-site-series.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = [
            "pair", "valid_crown_displacement_pixels", "crown_median_displacement_m",
            "crown_median_rate_cm_per_day", "bulk_reference_crown_R", "bulk_reference_background_R",
            "P2_R_crown", "P2_R_background", "P2_resolved", "archive_checks_passed", "archive_checks_total",
            "source_sha256", "archive_table_comparison_status",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for i, (pair, count, disp, rate) in enumerate(pairs):
            writer.writerow({
                "pair": pair, "valid_crown_displacement_pixels": count,
                "crown_median_displacement_m": disp, "crown_median_rate_cm_per_day": rate,
                "bulk_reference_crown_R": 0.871 if i == 3 else 0.70,
                "bulk_reference_background_R": 0.687, "P2_R_crown": 0.775,
                "P2_R_background": 0.795, "P2_resolved": "False" if i == 3 else "True",
                "archive_checks_passed": 13, "archive_checks_total": 13,
                "source_sha256": f"{i:064x}", "archive_table_comparison_status": "PASS_AT_ARCHIVE_ROUNDING",
            })

    products = []
    for i, (pair, *_rest) in enumerate(pairs):
        start, end = pair.split("->")
        products.append({
            "reference_date": start,
            "secondary_date": end,
            "source_filename": f"sample_{i}_P05023.h5",
            "source_sha256": f"{i:064x}",
            "download_status": "PASS",
            "grid_validation_status": "PASS",
        })
    _write_json(root / "author-exact-analysis-status.json", {
        "structural_status": "PASS",
        "paper_reproduction_status": "PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED",
        "hazard_detection_status": "NOT_EVALUATED",
        "source_manifest_sha256": "a" * 64,
        "footprint_screen_parity_status": "PASS_AUTHOR_AGGREGATE_RASTERS_AND_CANDIDATE_INVENTORY",
    })
    _write_json(root / "author-exact-source-manifest.json", {
        "drive_version_tag": "40170290176-1",
        "repository_commit": "417cc2f0156bb310f933b72edb9ecd359812f623",
        "source_products_grid_validated": 5,
        "author_exact_source_sha256_count": 5,
        "products": products,
    })
    _write_json(root / "author-raw-site-series-report.json", {
        "author_site_series_table_comparison": {"checks_passed": 65, "checks_total": 65},
        "author_p2_table_comparison": {"checks_passed": 15, "checks_total": 15},
    })
    _write_json(root / "know-place-analysis-report.json", {"structural_status": "PASS"})
    _write_json(root / "footprint" / "author-footprint-replay-report.json", {
        "footprint_screen_parity_status": "PASS_AUTHOR_AGGREGATE_RASTERS_AND_CANDIDATE_INVENTORY",
        "author_aggregate_raster_comparison": {"rasters_passed": 3},
        "author_inventory_comparison": {
            "matched_centroid_count": 106,
            "score_formula_audit": {"status": "PASS_POSTPROCESSED_AUTHOR_SCORE_CONVENTION"},
        },
        "author_validated_zone_table_comparison": {"matched_centroid_count": 101},
    })
    return root


def test_author_dashboard_shows_run_provenance_methods_and_scientific_limitations(tmp_path):
    root = _fixture(tmp_path / "run")
    dashboard = build_dashboard(root)

    assert "What did NISAR measure before the Bhote Koshi avalanche?" in dashboard
    assert "40170290176" in dashboard
    assert "417cc2f0156bb310f933b72edb9ecd359812f623" in dashboard
    assert "P05023" in dashboard
    assert "0.965 m" in dashboard
    assert "4.02 cm/day" in dashboard
    assert "65/65" in dashboard
    assert "15/15" in dashboard
    assert "106/106" in dashboard
    assert "101/101" in dashboard
    assert "PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED" in dashboard
    assert "NOT_EVALUATED" in dashboard
    assert "displacement-null draw-level generator is absent" in dashboard
    assert "সহজ ব্যাখ্যা" in dashboard
    assert "extent_CC-BY-NC-4.0" not in dashboard  # no restricted extent data is packaged
    assert "https://www.tbsnews.net/explainer/" in dashboard
    assert "https://geopera.com/blog/bhote-koshi-stereo-elevation-model" in dashboard
    assert "this thumbnail is from the corrected follow-up, not the retracted map" in dashboard
    assert "https://unpkg.com" not in dashboard and "https://cdn." not in dashboard
    assert dashboard.count("data:image/png;base64,") == 5
    uris = re.findall(r"data:image/png;base64,([A-Za-z0-9+/=]+)", dashboard)
    decoded = base64.b64decode(uris[0])
    assert decoded.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">IIBBBBB", decoded[16:29])[2] == 8


def test_author_dashboard_is_written_as_a_standalone_html_file(tmp_path):
    root = _fixture(tmp_path / "run")
    target = write_dashboard(root, tmp_path / "out" / "dashboard.html")
    text = target.read_text(encoding="utf-8")
    assert target.is_file()
    assert target.stat().st_size > 4000
    assert "<html lang=\"en\">" in text
    assert "data:image/png;base64," in text

def test_shared_dispatcher_exposes_retained_dashboard_without_raw_download_consent():
    import yaml

    repo_root = Path(__file__).resolve().parents[2]
    dispatcher_path = repo_root / ".github" / "workflows" / "sarguardian-aoi-wkt-dispatcher.yml"
    with dispatcher_path.open("r", encoding="utf-8") as stream:
        dispatcher = yaml.load(stream, Loader=yaml.BaseLoader)

    inputs = dispatcher["on"]["workflow_dispatch"]["inputs"]
    assert "render-author-dashboard" in inputs["run_profile"]["options"]
    assert inputs["source_run_id"]["default"] == "40170290176"
    assert inputs["source_attempt"]["default"] == "1"
    assert dispatcher["permissions"]["actions"] == "read"

    render_job = dispatcher["jobs"]["render_author_dashboard"]
    assert "render-author-dashboard" in render_job["if"]
    assert render_job["uses"] == (
        "moshiour0/SARGuardian-backend/.github/workflows/"
        "know-place-author-dashboard.yml@feat/know-place-analysis"
    )
    assert render_job["with"]["source_run_id"] == "${{ inputs.source_run_id }}"
    assert render_job["with"]["source_attempt"] == "${{ inputs.source_attempt }}"
    # This profile must not be coupled to the exact-author or generic raw-download path.
    assert "render-author-dashboard" not in dispatcher["jobs"]["author_exact_p05023"]["if"]
    assert "render-author-dashboard" not in dispatcher["jobs"]["generic_aoi_date"]["if"]

def test_dashboard_workflow_reads_artifact_metadata_in_the_current_shell():
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "know-place-author-dashboard.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    # GITHUB_ENV only affects later steps; this step must read its own validated values locally.
    assert 'artifact-metadata.txt' in workflow
    assert 'mapfile -t artifact_metadata < know-place-dashboard/source/artifact-metadata.txt' in workflow
    assert 'ARTIFACT_ID="${artifact_metadata[0]}"' in workflow
    assert 'EXPECTED_ARTIFACT_SHA256="${artifact_metadata[1]}"' in workflow
    assert 'stream.write("ARTIFACT_ID="' not in workflow
    assert 'stream.write("EXPECTED_ARTIFACT_SHA256="' not in workflow
    assert 'echo "$EXPECTED_ARTIFACT_SHA256  know-place-dashboard/source/source-artifact.zip" | sha256sum --check -' in workflow
