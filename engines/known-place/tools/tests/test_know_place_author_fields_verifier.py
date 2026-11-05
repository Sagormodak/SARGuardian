from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from tools.know_place.author_parity import author_coherence_map, author_polygon_null_statistics, author_site_series_statistics
from tools.know_place.verify_author_fields import _author_table_parity, verify_author_archive


def _tiny_field_tiff() -> bytes:
    east = np.ones((73, 80), dtype=np.float32)
    north = np.zeros((73, 80), dtype=np.float32)
    east[0, 0] = np.nan
    north[0, 0] = np.nan
    r = author_coherence_map(east.astype(float), north.astype(float)).astype(np.float32)
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            width=80,
            height=73,
            count=3,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(85.5, 28.32, 0.001, 0.001),
            nodata=np.nan,
        ) as dst:
            dst.write(east, 1)
            dst.write(north, 2)
            dst.write(r, 3)
            dst.set_band_description(1, "dE_m ground-referenced east displacement")
            dst.set_band_description(2, "dN_m ground-referenced north displacement")
            dst.set_band_description(3, "R directional coherence, 5x5 window")
        return mem.read()


def _write_archive(path: Path, tiff_bytes: bytes) -> None:
    entry = {
        "path": "fields/offsets_synthetic.tif",
        "bytes": len(tiff_bytes),
        "md5": hashlib.md5(tiff_bytes).hexdigest(),
    }
    manifest = {"record": "synthetic-test", "files": 1, "total_bytes": len(tiff_bytes), "manifest": [entry]}
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr(entry["path"], tiff_bytes)
        zf.writestr("MANIFEST.json", json.dumps(manifest))


def test_field_verifier_accepts_manifest_valid_author_r_band(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic-author.zip"
    _write_archive(archive, _tiny_field_tiff())
    report = verify_author_archive(archive, expected_field_count=1)
    assert report["status"] == "PASS_PROCESSED_FIELD_R_VERIFIED"
    assert report["manifest"]["payload_size_or_md5_mismatches"] == []
    assert len(report["site_fields"]) == 1
    assert report["site_fields"][0]["R_band_match"] is True
    assert report["site_fields"][0]["maximum_absolute_error"] <= 1e-6
    assert report["author_table_parity"]["status"] == "NOT_APPLICABLE_FIELD_ONLY_FIXTURE"


def test_full_archive_table_parity_fails_closed_when_reference_tables_are_missing() -> None:
    result = _author_table_parity(
        names={"fields/offsets_20260620_20260702.tif"},
        payloads={},
        read_member=lambda name: b"{}",
        required=True,
    )
    assert result["status"] == "BLOCKED_REFERENCE_TABLES_MISSING"
    assert set(result["missing_tables"]) == {
        "tables/nisar_pot_series.json",
        "tables/polygon_null.json",
        "tables/displacement_null.json",
        "tables/TableS4_site_series.json",
    }


def test_author_table_parity_recomputes_distinct_estimands_and_blocks_tampered_table() -> None:
    payload = _tiny_field_tiff()
    pairs = [
        ("20260620", "20260702", 12),
        ("20260702", "20260714", 12),
        ("20260714", "20260726", 12),
        ("20260726", "20260819", 24),
        ("20260819", "20260831", 12),
    ]
    payloads = {
        f"fields/offsets_{a}_{b}.tif": payload
        for a, b, _ in pairs
    }

    with MemoryFile(payload) as mem:
        with mem.open() as src:
            east, north = src.read([1, 2]).astype(float)
            extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)

    rng = np.random.default_rng(20260907)
    site_rows = []
    polygon_rows = []
    displacement_rows = []
    s4_rows = []
    for a, b, days in pairs:
        pair = f"{a}->{b}"
        site = author_site_series_statistics(east, north, extent, days)
        polygon = author_polygon_null_statistics(east, north, extent, rng=rng, n_draw=40)
        disp = {
            "pair": pair,
            "crown": round(site["crown_median_displacement_m"], 2),
            "null_med": 0.14,
            "pctile": 80.0,
        }
        site_rows.append({
            "a": a,
            "b": b,
            "days": days,
            "R_crown": site["P1_R_crown"],
            "R_scene": site["P1_R_background"],
            "crown_median_m": site["crown_median_displacement_m"],
            "rate_m_per_day": site["crown_median_rate_cm_per_day"] / 100.0,
            "n": site["displacement_valid_crown_cells"],
        })
        polygon_rows.append({
            "pair": pair,
            "days": days,
            "n_px": polygon["crown_valid_R_cells"],
            "crown": round(polygon["crown_R"], 3),
            "box": round(polygon["box_R"], 3),
            "adv": round(polygon["crown_R"] - polygon["box_R"], 3),
            "pct_beat_box": round(polygon["fraction_controls_strictly_above_box"], 1),
            "crown_pctile": round(polygon["crown_percentile_strict_less_than"], 1),
            "n_draw": polygon["accepted_draws"],
            "null_p5": round(polygon["null_p5"], 3),
            "null_p95": round(polygon["null_p95"], 3),
        })
        displacement_rows.append(disp)
        s4_rows.append({
            "pair": pair,
            "days": days,
            "crown_disp_m": round(site["crown_median_displacement_m"], 2),
            "crown_rate_cm_per_day": round(site["crown_median_rate_cm_per_day"], 1),
            "P1_R_crown": round(site["P1_R_crown"], 3),
            "P1_R_bg": round(site["P1_R_background"], 3),
            "P1_resolved": site["P1_R_crown"] > site["P1_R_background"],
            "polynull_R_crown": round(polygon["crown_R"], 3),
            "polynull_R_box": round(polygon["box_R"], 3),
            "polynull_crown_pctile": round(polygon["crown_percentile_strict_less_than"], 1),
            "polynull_n_draw": polygon["accepted_draws"],
            "dispnull_crown_m": disp["crown"],
            "dispnull_null_med_m": disp["null_med"],
            "dispnull_pctile": disp["pctile"],
        })

    table_bytes = {
        "tables/nisar_pot_series.json": json.dumps(site_rows).encode(),
        "tables/polygon_null.json": json.dumps(polygon_rows).encode(),
        "tables/displacement_null.json": json.dumps(displacement_rows).encode(),
        "tables/TableS4_site_series.json": json.dumps({"rows": s4_rows}).encode(),
    }
    names = set(payloads) | set(table_bytes)
    read_member = lambda name: table_bytes[name]

    passed = _author_table_parity(names, payloads, read_member, required=True, n_draw=40)
    assert passed["status"] == "PASS_EXPORTED_FIELDS_MATCH_ARCHIVED_TABLES"
    assert len(passed["pair_results"]) == 5
    assert all(row["status"] == "PASS" for row in passed["pair_results"])
    assert all(row["displacement_valid_crown_cells"] > 0 for row in passed["pair_results"])
    assert all(row["polygon_null_R_valid_crown_cells"] > 0 for row in passed["pair_results"])

    tampered_polygon = json.loads(table_bytes["tables/polygon_null.json"])
    tampered_polygon[0]["n_px"] += 1
    bad_tables = dict(table_bytes)
    bad_tables["tables/polygon_null.json"] = json.dumps(tampered_polygon).encode()
    blocked = _author_table_parity(
        names,
        payloads,
        lambda name: bad_tables[name],
        required=True,
        n_draw=40,
    )
    assert blocked["status"] == "BLOCKED_ARCHIVED_TABLE_PARITY"
    assert any(
        failure.startswith("20260620->20260702:polygon_null.R_valid_count_matches_n_px")
        for failure in blocked["failed_checks"]
    )


def test_field_verifier_flags_r_band_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic-author-bad-r.zip"
    payload = _tiny_field_tiff()
    import io
    with MemoryFile(payload) as mem:
        with mem.open() as src:
            arrays = src.read().astype(np.float32)
            profile = src.profile
            descriptions = src.descriptions
    arrays[2, 3, 3] = np.float32(0.25)
    out = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(arrays)
            for index, description in enumerate(descriptions, 1):
                dst.set_band_description(index, description)
        out.write(mem.read())
    bad_payload = out.getvalue()
    archive.unlink(missing_ok=True)
    _write_archive(archive, bad_payload)
    report = verify_author_archive(archive, expected_field_count=1)
    assert report["status"] == "BLOCKED"
    assert report["site_fields"][0]["R_band_match"] is False


def test_field_verifier_checks_each_manifest_payload_hash(tmp_path: Path) -> None:
    archive = tmp_path / "synthetic-manifest-bad.zip"
    payload = _tiny_field_tiff()
    _write_archive(archive, payload)
    # Damage the manifest MD5 while preserving a readable ZIP member.
    with ZipFile(archive, "r") as zf:
        members = {name: zf.read(name) for name in zf.namelist()}
    manifest = json.loads(members["MANIFEST.json"])
    manifest["manifest"][0]["md5"] = "0" * 32
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zf:
        for name, value in members.items():
            zf.writestr(name, json.dumps(manifest) if name == "MANIFEST.json" else value)
    report = verify_author_archive(archive, expected_field_count=1)
    assert report["status"] == "BLOCKED"
    assert report["manifest"]["payload_size_or_md5_mismatches"][0]["path"] == "fields/offsets_synthetic.tif"


def test_manifest_allows_readme_and_nc_component_as_separate_zenodo_record_files(tmp_path: Path) -> None:
    archive = tmp_path / "multipart-record.zip"
    payload = _tiny_field_tiff()
    entry = {
        "path": "fields/offsets_synthetic.tif",
        "bytes": len(payload),
        "md5": hashlib.md5(payload).hexdigest(),
    }
    external_readme = {"path": "README.md", "bytes": 10, "md5": "1" * 32}
    external_extent = {
        "path": "extent_CC-BY-NC-4.0/flow_extent.shp",
        "bytes": 10,
        "md5": "2" * 32,
    }
    manifest = {
        "record": "synthetic-multipart-record",
        "files": 3,
        "total_bytes": len(payload) + 20,
        "manifest": [entry, external_readme, external_extent],
    }
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr(entry["path"], payload)
        zf.writestr("MANIFEST.json", json.dumps(manifest))
    report = verify_author_archive(archive, expected_field_count=1)
    assert report["status"] == "PASS_PROCESSED_FIELD_R_VERIFIED"
    assert report["manifest"]["unexpected_missing_paths"] == []
    assert report["manifest"]["payload_size_or_md5_mismatches"] == []
