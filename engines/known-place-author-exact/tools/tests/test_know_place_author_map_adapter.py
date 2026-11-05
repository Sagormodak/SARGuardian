from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest

import tools.know_place.author_map_adapter as adapter


PAIRS = [
    ("2026-06-20", "2026-07-02", "023"),
    ("2026-07-02", "2026-07-14", "024"),
    ("2026-07-14", "2026-07-26", "025"),
    ("2026-07-26", "2026-08-19", "026"),
    ("2026-08-19", "2026-08-31", "028"),
]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _name(index: int, a: str, b: str, scene: str) -> str:
    a_token, b_token = a.replace("-", ""), b.replace("-", "")
    return (
        f"NISAR_L2_PR_GOFF_{scene}_098_A_016_024_4000_SH_"
        f"{a_token}T233921_{a_token}T233956_{b_token}T233920_{b_token}T233955_"
        "P05023_N_F_J_001"
    )


def _make_artifact_root(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    products = []
    csv_rows = []
    derived = io.BytesIO()
    with zipfile.ZipFile(derived, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (a, b, scene) in enumerate(PAIRS):
            granule = _name(index, a, b, scene)
            digest = _sha("source-" + granule)
            products.append({
                "granule_name": granule,
                "interval": f"{a}/{b}",
                "release_id": "P05023",
                "download_status": "PASS",
                "grid_validation_status": "PASS",
                "source_sha256": digest,
                "grid_epsg": 32645,
            })
            csv_rows.append({
                "reference_date": a,
                "secondary_date": b,
                "granule_name": granule + ".h5",
                "status": "METRICS_COMPUTED",
                "crown_valid_pixels": "2",
                "crown_median_horizontal_magnitude_m": "0.7",
                "source_sha256": digest,
            })
            x = np.asarray([100.0, 180.0, 260.0, 340.0])
            y = np.asarray([500.0, 420.0, 340.0])
            mag = np.full((3, 4), 0.7 + index * 0.1, dtype=np.float32)
            valid = np.ones((3, 4), dtype=np.uint8)
            valid[0, 0] = 0
            valid[1, 2] = 0
            crown = np.zeros((3, 4), dtype=np.uint8)
            crown[1, 1] = 1
            crown[1, 2] = 1
            crown[2, 1] = 1
            payload = io.BytesIO()
            np.savez(
                payload,
                horizontal_magnitude_m=mag,
                valid_mask=valid,
                crown_mask=crown,
                x_coordinates_m=x,
                y_coordinates_m=y,
            )
            archive.writestr(f"{a.replace('-', '')}__{b.replace('-', '')}_diagnostic_arrays.npz", payload.getvalue())

    (root / "author-exact-derived-results.zip").write_bytes(derived.getvalue())
    (root / "author-exact-source-manifest.json").write_text(json.dumps({
        "status": "PASS_FIVE_EXACT_HDF5_DOWNLOADED_HASHED_AND_GRID_VALIDATED",
        "author_release_id": "P05023",
        "source_sha256_count": 5,
        "repository_commit": "b" * 40,
        "products": products,
    }), encoding="utf-8")
    (root / "know-place-analysis-report.json").write_text(json.dumps({
        "status": "SCIENTIFIC_METRICS_COMPUTED",
        "structural_status": "PASS",
        "paper_reproduction_status": "PARTIAL",
        "hazard_detection_status": "NOT_EVALUATED",
        "run_scope": {
            "crown_wkt": (
                "POLYGON ((85.5245 28.2847, 85.5400 28.2847, "
                "85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))"
            ),
            "crown_geometry_kind": "bounding-box-approximation",
        },
    }), encoding="utf-8")
    with (root / "know-place-analysis-pairs.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    return root


def test_build_author_map_report_is_exact_p05023_and_five_pairs(tmp_path: Path):
    root = _make_artifact_root(tmp_path / "source")
    report = adapter.build_author_map_report(root, 40232441596)

    assert report["source_run_id"] == 40232441596
    assert report["status"] == "PASS"
    assert report["source_granules"] == 5
    assert report["map_pairs"] == 5
    assert report["hazard_detection_status"] == "NOT_EVALUATED"
    assert report["aoi_geometry_note"] == (
        "Author-script AOI rectangle: 85.5245–85.5400° E, 28.2847–28.2970° N; "
        "native-grid pixel-mask parity remains unverified."
    )
    assert report["raw_hdf5_read_or_downloaded"] is False
    assert [p["reference_date"] for p in report["pairs"]] == [p[0] for p in PAIRS]
    assert all(p["release_id"] == "P05023" for p in report["pairs"])
    assert all(p["support_region_label"] == "Valid crown-mask pixels" for p in report["pairs"])
    assert all(p["valid_aoi_pixels"] == 2 and p["aoi_total_grid_cells"] == 3 for p in report["pairs"])
    assert all(p.get("geotiff_file") is None and p.get("geotiff_href") is None for p in report["pairs"])
    assert all(p["map_preview"]["pixel_size_x_m"] == 80 for p in report["pairs"])
    assert all(p["map_preview"]["support_mask_label"].startswith("Crown-mask only") for p in report["pairs"])
    for pair in report["pairs"]:
        values = pair["map_preview"]["values"]
        assert values[0][1] is None  # valid scene pixel but outside the crown mask
        assert values[1][1] is not None  # valid pixel inside the crown mask
        assert values[1][2] is None  # invalid pixel inside the crown mask


def test_map_renderer_writes_a_five_pair_map_and_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = _make_artifact_root(tmp_path / "source")
    out = tmp_path / "output"

    def fake_renderer(report: dict, path: str | Path) -> Path:
        target = Path(path)
        assert len(report["pairs"]) == 5
        assert report["request"]["date_range"] == {"start": "2026-06-20", "end": "2026-08-31"}
        assert report["hazard_detection_status"] == "NOT_EVALUATED"
        target.write_text("<html><title>Interactive AOI map</title></html>", encoding="utf-8")
        return target

    monkeypatch.setattr(adapter, "write_interactive_map", fake_renderer)
    # Exercise the CLI path without requiring a real command-line invocation.
    monkeypatch.setattr(
        "sys.argv",
        ["author_map_adapter", "--artifact-root", str(root), "--out-root", str(out), "--source-run-id", "40232441596"],
    )
    assert adapter.main() == 0
    assert (out / "interactive-map.html").is_file()
    receipt = json.loads((out / "author-map-provenance.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    assert receipt["interactive_map_bytes"] > 0


def test_refuses_non_p05023_source(tmp_path: Path):
    root = _make_artifact_root(tmp_path / "source")
    manifest_path = root / "author-exact-source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["products"][0]["release_id"] = "X05026"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(adapter.AuthorMapAdapterError, match="NON_AUTHOR_RELEASE_IN_SOURCE_MANIFEST"):
        adapter.build_author_map_report(root, 40232441596)


def test_refuses_csv_source_hash_mismatch(tmp_path: Path):
    root = _make_artifact_root(tmp_path / "source")
    csv_path = root / "know-place-analysis-pairs.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8", newline="")))
    rows[0]["source_sha256"] = "0" * 64
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(adapter.AuthorMapAdapterError, match="CSV_SOURCE_SHA256_MISMATCH"):
        adapter.build_author_map_report(root, 40232441596)


def test_refuses_raw_hdf5_member_in_artifact_root(tmp_path: Path):
    root = _make_artifact_root(tmp_path / "source")
    (root / "unexpected.h5").write_bytes(b"not a real HDF5 file")
    with pytest.raises(adapter.AuthorMapAdapterError, match="RAW_HDF5_FOUND_IN_ARTIFACT_ROOT"):
        adapter.build_author_map_report(root, 40232441596)
