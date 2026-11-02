from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.know_place.aoi_request import REQUEST_SCHEMA, validate_aoi_request
from tools.know_place import aoi_runner
from tools.know_place.geometry import polygon_pair_envelope_wkt
from tools.know_place.aoi_runner import (
    AOIRunError,
    _download_exact_product,
    _cleanup_ephemeral_source,
    _estimate_roi_window_cells,
    _exact_bytes,
    _grid_identity_sha256,
    _grid_lattice_compatible,
    _magnitude_gate_limit,
    _high_magnitude_review_flag,
    _maturity,
    _polarization_codes,
    _product_name,
    _preview,
    _trusted_download_url,
    discover_nisar_goff,
    run_aoi_analysis,
)
import numpy as np
from pyproj import Transformer

PAIR_NAMES = [
    "NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_X05026_N_F_J_001.h5",
    "NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001.h5",
]

def request(allowed_release_ids=(), reference_wkt=None):
    payload = {
        "schema_version": REQUEST_SCHEMA,
        "aoi": {"type": "Polygon", "wkt": "POLYGON ((85.52 28.28, 85.54 28.28, 85.54 28.30, 85.52 28.30, 85.52 28.28))", "crs": "EPSG:4326"},
        "date_range": {"start": "2026-06-20", "end": "2026-07-14", "inclusive": True},
        "hazard_mode": "landslide",
        "analysis_mode": "retrospective_validation",
        "source_adapters": ["NISAR_GOFF"],
        "product_selection": {"allowed_maturities": ["PROVISIONAL"], "allowed_release_ids": list(allowed_release_ids)},
    }
    if reference_wkt:
        payload["reference"] = {
            "policy": "external_reference_polygon_component_median",
            "polygon_wkt": reference_wkt,
        }
    return validate_aoi_request(payload)

def product(name, *, maturity="PROVISIONAL", polarization="HH", bytes_size=101):
    url = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_{maturity}_V1/{name}"
    return SimpleNamespace(
        properties={
            "granuleName": name,
            "dataMaturity": maturity,
            "mainBandPolarization": polarization,
            "fileSizeBytes": bytes_size,
        },
        get_urls=lambda: [url],
    )

def test_ambiguous_release_failure_is_explained_and_stops_before_download(tmp_path, monkeypatch):
    duplicate = PAIR_NAMES[0].replace("_X05026_", "_P05023_")
    records = [
        {"granule_name": PAIR_NAMES[0], "polarization": "HH", "release_id": "X05026", "maturity": "PROVISIONAL"},
        {"granule_name": duplicate, "polarization": "HH", "release_id": "P05023", "maturity": "PROVISIONAL"},
    ]
    manifest = {
        "schema_version": "know-place-aoi-catalog-manifest/1.0",
        "result_count": 2,
        "eligible_count": 2,
        "candidates": [
            {"granule_name": row["granule_name"], "release_id": row["release_id"], "decision": "ELIGIBLE_CATALOG_CANDIDATE"}
            for row in records
        ],
    }
    monkeypatch.setattr(aoi_runner, "discover_nisar_goff", lambda _request: (records, manifest))
    monkeypatch.setattr(
        aoi_runner,
        "_download_exact_product",
        lambda *_args, **_kwargs: pytest.fail("ambiguous series must be rejected before any raw product download"),
    )

    output_root = tmp_path / "output"
    with pytest.raises(AOIRunError, match="AMBIGUOUS_PRODUCT_RELEASE_VARIANTS") as exc_info:
        run_aoi_analysis(request().to_dict(), output_root, cache_root=tmp_path / "cache", ephemeral_source_cache=True)

    assert exc_info.value.code == "AMBIGUOUS_PRODUCT_RELEASE_VARIANTS"
    run_dirs = [path for path in output_root.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    failure = json.loads((run_dirs[0] / "failure.json").read_text(encoding="utf-8"))
    detail = failure["failure"]
    assert detail["code"] == "AMBIGUOUS_PRODUCT_RELEASE_VARIANTS"
    assert detail["selection_diagnostics"]["candidate_release_ids"] == ["P05023", "X05026"]
    assert detail["selection_diagnostics"]["ambiguous_pairs"][0]["candidate_granules"] == sorted([PAIR_NAMES[0], duplicate])
    assert "catalog-only preflight" in detail["selection_diagnostics"]["required_action"]
    assert "never silently substitute" in detail["required_user_action"]
    assert not list((tmp_path / "cache").rglob("*.h5"))

def test_asf_catalog_contract_preserves_exact_ids_and_query_evidence(monkeypatch):
    calls = {}
    fake = SimpleNamespace(
        ASFSearchOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        search=lambda **kwargs: (calls.update(vars(kwargs["opts"])) or [product(n) for n in PAIR_NAMES]),
    )
    monkeypatch.setitem(sys.modules, "asf_search", fake)

    products, manifest = discover_nisar_goff(request())

    assert [item["granule_name"] for item in products] == PAIR_NAMES
    assert manifest["eligible_count"] == 2
    assert manifest["query"]["start_utc"] == "2026-06-20T00:00:00Z"
    assert manifest["query"]["end_utc"] == "2026-07-14T23:59:59Z"
    assert calls["shortName"] == ["NISAR_L2_GOFF_PROVISIONAL_V1"]
    assert calls["dataset"] == "NISAR"
    assert calls["collectionAlias"] is False
    assert "processingLevel" not in calls
    assert "dataMaturity" not in calls
    assert calls["shortName"] == ["NISAR_L2_GOFF_PROVISIONAL_V1"]
    assert calls["intersectsWith"].startswith("POLYGON ((")
    assert calls["mainBandPolarization"] == "HH"
    assert all(row["decision"] == "ELIGIBLE_CATALOG_CANDIDATE" for row in manifest["candidates"])

def test_polarization_codes_normalize_dual_pol_delimiters_without_substring_matches():
    assert _polarization_codes("HH") == {"HH"}
    assert _polarization_codes("HH+HV") == {"HH", "HV"}
    assert _polarization_codes("HH/HV") == {"HH", "HV"}
    assert _polarization_codes("HH-HV") == {"HH", "HV"}
    assert _polarization_codes("HH, HV") == {"HH", "HV"}
    assert _polarization_codes("VH only") == {"VH"}
    assert _polarization_codes("unknown") == set()

def test_catalog_excludes_unexpected_product_type_without_aborting(monkeypatch):
    wrong_name = "NISAR_L2_UR_GUNW_029_098_A_016_030_4000_SH_20260831T233918_20260831T233952_20260912T233918_20260912T233952_P05023_F_F_J_001.h5"
    wrong_product = SimpleNamespace(
        properties={"granuleName": wrong_name},
        get_urls=lambda: [f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/{wrong_name}"],
    )
    fake = SimpleNamespace(
        ASFSearchOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        search=lambda **kwargs: [wrong_product],
    )
    monkeypatch.setitem(sys.modules, "asf_search", fake)

    products, manifest = discover_nisar_goff(request())

    assert products == []
    assert manifest["result_count"] == 1
    assert manifest["candidates"][0]["decision"] == "EXCLUDED_PRODUCT_TYPE_MISMATCH"
    assert manifest["candidates"][0]["expected_product_type"] == "NISAR_L2_PR_GOFF"

def test_explicit_release_allowlist_excludes_other_release_variants(monkeypatch):
    historical = PAIR_NAMES[0]
    preferred = historical.replace("_X05026_", "_P05023_")
    products_from_catalog = [product(historical), product(preferred)]
    fake = SimpleNamespace(
        ASFSearchOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        search=lambda **kwargs: products_from_catalog,
    )
    monkeypatch.setitem(sys.modules, "asf_search", fake)

    products, manifest = discover_nisar_goff(request(["P05023"]))

    assert [item["granule_name"] for item in products] == [preferred]
    excluded = next(row for row in manifest["candidates"] if row["granule_name"] == historical)
    assert excluded["decision"] == "EXCLUDED_RELEASE_NOT_ALLOWED"
    assert excluded["release_id"] == "X05026"
    assert manifest["query"]["allowed_release_ids"] == ["P05023"]

def test_catalog_maturity_allowlist_excludes_unselected_variants(monkeypatch):
    fake = SimpleNamespace(
        ASFSearchOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        search=lambda **kwargs: [product(PAIR_NAMES[0], maturity="BETA")],
    )
    monkeypatch.setitem(sys.modules, "asf_search", fake)

    products, manifest = discover_nisar_goff(request())

    assert products == []
    assert manifest["eligible_count"] == 0
    assert manifest["candidates"][0]["decision"] == "EXCLUDED_MATURITY_NOT_ALLOWED"

def test_catalog_uses_singleton_maturity_filter_when_asf_omits_property(monkeypatch):
    calls = {}
    name = PAIR_NAMES[0]
    result = SimpleNamespace(
        properties={"granuleName": name, "mainBandPolarization": "HH", "fileSizeBytes": 101},
        get_urls=lambda: [f"https://nisar.asf.earthdatacloud.nasa.gov/data/{name}"],
    )
    fake = SimpleNamespace(
        ASFSearchOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        search=lambda **kwargs: (calls.update(vars(kwargs["opts"])) or [result]),
    )
    monkeypatch.setitem(sys.modules, "asf_search", fake)

    products, manifest = discover_nisar_goff(request())

    assert calls["shortName"] == ["NISAR_L2_GOFF_PROVISIONAL_V1"]
    assert calls["dataset"] == "NISAR"
    assert calls["collectionAlias"] is False
    assert len(products) == 1
    assert products[0]["maturity"] == "PROVISIONAL"
    assert products[0]["maturity_evidence"] == "authoritative_asf_search_filter:shortName=NISAR_L2_GOFF_PROVISIONAL_V1"
    assert manifest["query"]["short_name_filter"] == ["NISAR_L2_GOFF_PROVISIONAL_V1"]


def test_unknown_explicit_maturity_fails_closed_even_if_query_is_singleton():
    known_url = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/{PAIR_NAMES[0]}"
    with pytest.raises(AOIRunError) as exc_info:
        _maturity({"dataMaturity": "UNRECOGNIZED"}, [known_url], ("PROVISIONAL",))
    assert exc_info.value.code == "CATALOG_MATURITY_INVALID"


def test_multiple_allowed_maturities_cannot_be_inferred_when_asf_omits_metadata():
    with pytest.raises(AOIRunError) as exc_info:
        _maturity({}, ["https://nisar.asf.earthdatacloud.nasa.gov/unknown/a.h5"], ("BETA", "PROVISIONAL"))
    assert exc_info.value.code == "CATALOG_MATURITY_UNRESOLVED"


def test_catalog_product_identity_and_trusted_host_gates():
    good_url = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/{PAIR_NAMES[0]}"
    assert _trusted_download_url(good_url)
    assert not _trusted_download_url(good_url.replace("https://", "http://"))
    assert not _trusted_download_url("https://not-asf.example.com/a.h5")
    assert _product_name({"granuleName": PAIR_NAMES[0]}, [good_url]) == PAIR_NAMES[0]
    assert _maturity({"dataMaturity": "PROVISIONAL"}, [good_url])[0] == "PROVISIONAL"
    assert _exact_bytes({"fileSizeBytes": "101"}) == 101
    assert _exact_bytes({"fileSizeBytes": "101.5"}) is None
    with pytest.raises(AOIRunError) as exc_info:
        _maturity({}, ["https://nisar.asf.earthdatacloud.nasa.gov/unknown/a.h5"])
    assert exc_info.value.code == "CATALOG_MATURITY_UNRESOLVED"

def test_download_cache_reuses_only_source_receipt_with_matching_sha256(tmp_path, monkeypatch):
    name = PAIR_NAMES[0]
    url = f"https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/{name}"
    cache_root = tmp_path / "cache"
    product_dir = cache_root / hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    product_dir.mkdir(parents=True)
    target = product_dir / name
    data = b"synthetic-source-data-for-cache-contract"
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    url_fingerprint = hashlib.sha256(url.encode("utf-8")).hexdigest()
    (product_dir / f"{name}.source-receipt.json").write_text(json.dumps({
        "schema_version": "know-place-source-receipt/1.0",
        "granule_name": name, "release_id": "X05026", "maturity": "PROVISIONAL",
        "source_url_fingerprint": url_fingerprint, "source_sha256": digest,
        "source_bytes": len(data),
    }))
    fake = SimpleNamespace(download_urls=lambda **kwargs: pytest.fail("valid cache should not download again"))
    monkeypatch.setitem(sys.modules, "asf_search", fake)

    path, evidence = _download_exact_product({
        "granule_name": name, "release_id": "X05026", "maturity": "PROVISIONAL",
        "download_url": url, "source_bytes": len(data),
    }, cache_root, session=object())

    assert path == target
    assert evidence["source_sha256"] == digest
    assert evidence["cache_status"] == "REUSED_HASH_VERIFIED"

def test_preview_is_downsampled_visual_only_and_keeps_nodata_explicit():
    values = np.arange(10000, dtype=float).reshape(100, 100)
    values[0:10, 0:10] = np.nan
    preview = _preview(values, np.arange(100, dtype=float), np.arange(100, dtype=float),
                       ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0), (10.0, 10.0)))
    assert max(preview["width"], preview["height"]) <= 72
    assert preview["description"].startswith("Median magnitude per block")
    assert len(preview["aoi_ring_xy"]) == 5


def test_generic_large_displacement_is_retained_and_flagged_but_paper_policy_rejects_it():
    from tools.know_place.paper_method import apply_paper_quality_gates

    east = np.array([[25.0, 0.5]], dtype=float)
    north = np.array([[0.0, 0.0]], dtype=float)
    snr = np.array([[8.0, 8.0]], dtype=float)
    input_valid = np.array([[True, True]])

    generic = request()  # generic default: preserve high magnitude and flag it
    assert generic.magnitude_policy == "flag_above_threshold_keep"
    generic_valid, generic_counts, magnitude = apply_paper_quality_gates(
        east, north, snr, input_valid=input_valid,
        minimum_snr=generic.min_snr,
        maximum_horizontal_magnitude_m=_magnitude_gate_limit(generic),
    )
    generic_flags = _high_magnitude_review_flag(magnitude, snr, input_valid, generic)
    assert generic_valid.tolist() == [[True, True]]
    assert generic_counts.rejected_magnitude == 0
    assert generic_flags.tolist() == [[True, False]]

    payload = {
        "schema_version": REQUEST_SCHEMA,
        "aoi": {"type": "Polygon", "wkt": "POLYGON ((85.52 28.28, 85.54 28.28, 85.54 28.30, 85.52 28.30, 85.52 28.28))", "crs": "EPSG:4326"},
        "date_range": {"start": "2026-06-20", "end": "2026-07-14", "inclusive": True},
        "hazard_mode": "ice_rock_avalanche",
        "analysis_mode": "retrospective_validation",
        "quality_policy": {"minimum_snr": 5, "maximum_horizontal_magnitude_m": 10, "magnitude_policy": "reject_above_threshold"},
    }
    paper_policy = validate_aoi_request(payload)
    paper_valid, paper_counts, _ = apply_paper_quality_gates(
        east, north, snr, input_valid=input_valid,
        minimum_snr=paper_policy.min_snr,
        maximum_horizontal_magnitude_m=_magnitude_gate_limit(paper_policy),
    )
    paper_flags = _high_magnitude_review_flag(magnitude, snr, input_valid, paper_policy)
    assert paper_valid.tolist() == [[False, True]]
    assert paper_counts.rejected_magnitude == 1
    assert paper_flags.tolist() == [[True, False]]


def test_ephemeral_source_cleanup_removes_h5_and_receipt_without_reuploading_raw_data(tmp_path):
    product_dir = tmp_path / "goff-products" / "product-id"
    product_dir.mkdir(parents=True)
    source = product_dir / (PAIR_NAMES[0])
    receipt = product_dir / (PAIR_NAMES[0] + ".source-receipt.json")
    source.write_bytes(b"raw HDF5 fixture")
    receipt.write_text('{"source_sha256":"example"}', encoding="utf-8")
    pending = [source]

    _cleanup_ephemeral_source(source, pending)

    assert not product_dir.exists()
    assert pending == []


def test_grid_lattice_contract_accepts_extent_changes_but_rejects_subpixel_shift_and_crs_change():
    base = SimpleNamespace(
        epsg=32645,
        x_coordinates_m=np.arange(1000.0, 1800.0, 80.0),
        y_coordinates_m=np.arange(2400.0, 1600.0, -80.0),
    )
    different_extent_same_lattice = SimpleNamespace(
        epsg=32645,
        x_coordinates_m=np.arange(1160.0, 1800.0, 80.0),
        y_coordinates_m=np.arange(2320.0, 1600.0, -80.0),
    )
    shifted_half_pixel = SimpleNamespace(
        epsg=32645,
        x_coordinates_m=np.arange(1040.0, 1840.0, 80.0),
        y_coordinates_m=np.arange(2400.0, 1600.0, -80.0),
    )
    wrong_crs = SimpleNamespace(
        epsg=32646,
        x_coordinates_m=base.x_coordinates_m.copy(),
        y_coordinates_m=base.y_coordinates_m.copy(),
    )

    assert _grid_lattice_compatible(base, different_extent_same_lattice)
    assert not _grid_lattice_compatible(base, shifted_half_pixel)
    assert not _grid_lattice_compatible(base, wrong_crs)
    assert _grid_identity_sha256(base) != _grid_identity_sha256(different_extent_same_lattice)


def test_oversized_reference_context_fails_before_roi_allocation():
    wkt = "POLYGON ((85.52 28.28, 85.54 28.28, 85.54 28.30, 85.52 28.30, 85.52 28.28))"
    corners = [(85.52, 28.28), (85.54, 28.28), (85.54, 28.30), (85.52, 28.30)]
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
    xs, ys = transformer.transform([p[0] for p in corners], [p[1] for p in corners])
    x = np.arange(np.floor(min(xs) / 80) * 80 - 1000, np.ceil(max(xs) / 80) * 80 + 1000, 80.0)
    y = np.arange(np.ceil(max(ys) / 80) * 80 + 1000, np.floor(min(ys) / 80) * 80 - 1000, -80.0)

    with pytest.raises(AOIRunError) as exc_info:
        _estimate_roi_window_cells(x, y, wkt, 32645, max_window_cells=10)
    assert exc_info.value.code == "AOI_WINDOW_TOO_LARGE"

    permitted_cells = _estimate_roi_window_cells(x, y, wkt, 32645, max_window_cells=10000)
    assert 0 < permitted_cells <= 10000

def test_asf_catalog_search_envelope_covers_separate_measurement_and_reference_polygons(monkeypatch):
    reference_wkt = (
        "POLYGON ((85.500 28.284, 85.515 28.284, 85.515 28.297, "
        "85.500 28.297, 85.500 28.284))"
    )
    calls = {}
    fake = SimpleNamespace(
        ASFSearchOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        search=lambda **kwargs: (calls.update(vars(kwargs["opts"])) or [product(n) for n in PAIR_NAMES]),
    )
    monkeypatch.setitem(sys.modules, "asf_search", fake)
    known_place_request = request(reference_wkt=reference_wkt)

    products, manifest = discover_nisar_goff(known_place_request)

    expected = polygon_pair_envelope_wkt(
        known_place_request.aoi_wkt,
        known_place_request.reference_wkt,
        4326,
    )
    assert len(products) == 2
    assert calls["intersectsWith"] == expected
    assert manifest["query"]["catalog_search_geometry"] == "measurement_reference_combined_envelope"
    assert manifest["query"]["intersects_wkt_sha256"]
    assert manifest["query"]["measurement_wkt_sha256"]
    assert manifest["query"]["reference_wkt_sha256"]

