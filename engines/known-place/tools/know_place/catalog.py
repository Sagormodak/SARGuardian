"""Fail-closed ASF catalog identity gate for the five Know Place products.

This module only validates metadata and product identity; it never downloads raw
HDF5 and never infers a maturity from an acquisition date. Expected hashes are
from the already completed source-AOI-specific Dynamic AOI run 39942529304.
The selected CRID variants remain unverified against the paper author's inputs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlparse

from .goff_io import GoffReadError, parse_granule_identity


REFERENCE_RUN_ID = 39942529304
EXPECTED_COLLECTION = "NISAR_L2_GOFF_PROVISIONAL_V1"
EXPECTED_MATURITY = "PROVISIONAL"

# Known candidate source files from the previous Dynamic AOI run.
# Fixed byte size and SHA-256 checks prevent a changed object with the same
# public identifier from silently replacing the already-inspected input.
TARGET_PRODUCTS: tuple[dict[str, Any], ...] = (
    {
        "granule_name": "NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_X05026_N_F_J_001",
        "reference_date": "2026-06-20",
        "secondary_date": "2026-07-02",
        "expected_source_bytes": 1090519040,
        "historical_source_sha256": "df870327e662b8d4c49d242437f7a2b6e44e3c7bdf99169910c6020689736918",
        "previous_product_id": "GOFF-003",
    },
    {
        "granule_name": "NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001",
        "reference_date": "2026-07-02",
        "secondary_date": "2026-07-14",
        "expected_source_bytes": 1090519040,
        "historical_source_sha256": "8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c",
        "previous_product_id": "GOFF-007",
    },
    {
        "granule_name": "NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001",
        "reference_date": "2026-07-14",
        "secondary_date": "2026-07-26",
        "expected_source_bytes": 1092616192,
        "historical_source_sha256": "ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313",
        "previous_product_id": "GOFF-011",
    },
    {
        "granule_name": "NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001",
        "reference_date": "2026-07-26",
        "secondary_date": "2026-08-19",
        "expected_source_bytes": 1101004800,
        "historical_source_sha256": "45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f",
        "previous_product_id": "GOFF-015",
    },
    {
        "granule_name": "NISAR_L2_PR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_N_F_J_001",
        "reference_date": "2026-08-19",
        "secondary_date": "2026-08-31",
        "expected_source_bytes": 1098907648,
        "historical_source_sha256": "4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371",
        "previous_product_id": "GOFF-019",
    },
)


class CatalogIdentityError(ValueError):
    """ASF returned a missing, ambiguous, mismatched, or unresolved product."""


def _normalise_product_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        candidate = Path(parsed.path).name
    candidate = Path(candidate).name
    return candidate[:-3] if candidate.lower().endswith(".h5") else candidate


def _is_trusted_asf_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "asf.alaska.edu"
        or host.endswith(".asf.alaska.edu")
        or host.endswith(".asf.earthdatacloud.nasa.gov")
    )


def _product_properties(product: Any) -> dict[str, Any]:
    props = getattr(product, "properties", None)
    if props is None and isinstance(product, dict):
        props = product.get("properties", product)
    return props if isinstance(props, dict) else {}


def _product_urls(product: Any, props: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    get_urls = getattr(product, "get_urls", None)
    if callable(get_urls):
        try:
            urls.extend(u for u in get_urls() if isinstance(u, str))
        except Exception:
            pass
    for key in ("url", "downloadUrl", "download_url"):
        value = props.get(key)
        if isinstance(value, str):
            urls.append(value)
    return list(dict.fromkeys(urls))



def _exact_integer(value: Any) -> int | None:
    """Return an integer only when metadata represents an exact count of bytes."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        return int(value.strip())
    return None


def _catalog_size_evidence(product: Any, props: dict[str, Any], wanted: str) -> tuple[int | None, dict[str, Any]]:
    """Resolve byte size only from an unambiguous exact-byte field.

    Recent asf_search releases expose properties['bytes'] as a per-file
    mapping whose values may have a magnitude and a separate unit. Passing
    that mapping to int() is a schema error; interpreting a rounded GB/MB
    number as an exact byte count would also be unsafe. Prefer raw CMR UMM
    SizeInBytes for the exact named source file.
    """
    umm = getattr(product, "umm", None)
    if isinstance(umm, dict):
        data_granule = umm.get("DataGranule", {})
        archive_info = data_granule.get("ArchiveAndDistributionInformation", []) if isinstance(data_granule, dict) else []
        if isinstance(archive_info, list):
            matching = [
                row for row in archive_info
                if isinstance(row, dict)
                and _normalise_product_name(row.get("Name")) == wanted
            ]
            if len(matching) > 1:
                raise CatalogIdentityError(f"ASF_BYTE_SIZE_METADATA_AMBIGUOUS:{wanted}")
            if len(matching) == 1:
                exact = _exact_integer(matching[0].get("SizeInBytes"))
                if exact is not None:
                    return exact, {
                        "status": "EXACT_BYTES_FROM_CMR_UMM",
                        "source_field": "DataGranule.ArchiveAndDistributionInformation.SizeInBytes",
                    }

    for field in ("sizeBytes", "fileSize", "bytes"):
        raw = props.get(field)
        exact = _exact_integer(raw)
        if exact is not None:
            return exact, {
                "status": "EXACT_BYTES_FROM_ASF_PROPERTY",
                "source_field": field,
            }
        if not isinstance(raw, dict):
            continue
        keyed = [
            value for name, value in raw.items()
            if _normalise_product_name(str(name)) == wanted
        ]
        if len(keyed) > 1:
            raise CatalogIdentityError(f"ASF_BYTE_SIZE_METADATA_AMBIGUOUS:{wanted}:{field}")
        if len(keyed) == 1 and isinstance(keyed[0], dict):
            row = keyed[0]
            value = row.get("bytes", row.get("SizeInBytes"))
            unit = str(row.get("format", row.get("unit", ""))).strip().lower()
            exact_value = _exact_integer(value)
            if exact_value is not None and unit in {"b", "byte", "bytes", "sizeinbytes"}:
                return exact_value, {
                    "status": "EXACT_BYTES_FROM_ASF_FILE_SIZE_MAP",
                    "source_field": field,
                    "reported_unit": unit,
                }
            return None, {
                "status": "NON_EXACT_FORMATTED_SIZE_DEFERRED_TO_SOURCE_SHA256",
                "source_field": field,
                "reported_unit": unit or "not_declared",
            }
    return None, {
        "status": "EXACT_BYTE_SIZE_NOT_EXPOSED_BY_CATALOG",
        "source_field": None,
    }

def validate_exact_catalog_product(
    target: dict[str, Any],
    results: list[Any],
) -> dict[str, Any]:
    """Require exactly one exact granule, authoritative PROVISIONAL evidence and URL."""
    wanted = str(target["granule_name"])
    matches: list[tuple[dict[str, Any], list[str]]] = []
    identity_keys = (
        "fileName", "granuleName", "sceneName", "productName",
        "producerGranuleId", "producerGranuleID", "granule_ur", "fileID", "name",
    )

    for product in results:
        props = _product_properties(product)
        urls = _product_urls(product, props)
        exact_urls = [
            u for u in urls
            if _is_trusted_asf_url(u)
            and _normalise_product_name(u) == wanted
            and f"/{EXPECTED_COLLECTION}/" in urlparse(u).path
        ]
        exact_identity = any(_normalise_product_name(props.get(k)) == wanted for k in identity_keys)
        # A filename match without an official exact-object URL is insufficient;
        # a trusted URL matching the exact object is itself exact identity evidence.
        if exact_urls and (exact_identity or len(exact_urls) >= 1):
            matches.append((props, exact_urls))

    if not matches:
        raise CatalogIdentityError(f"ASF_EXACT_GRANULE_NOT_FOUND:{wanted}")
    if len(matches) != 1:
        raise CatalogIdentityError(f"ASF_EXACT_GRANULE_AMBIGUOUS:{wanted}:matches={len(matches)}")

    props, urls = matches[0]
    maturity_raw = props.get("dataMaturity") or props.get("maturity")
    maturity = str(maturity_raw or "").strip().upper()
    if maturity and maturity != EXPECTED_MATURITY:
        raise CatalogIdentityError(
            f"ASF_MATURITY_CONFLICT:{wanted}:expected={EXPECTED_MATURITY}:actual={maturity}"
        )
    if not maturity:
        # The exact object URL names the collection only if it resolves through
        # a classified collection route. Do not fall back to acquisition dates.
        if not any(f"/{EXPECTED_COLLECTION}/" in urlparse(u).path for u in urls):
            raise CatalogIdentityError(f"ASF_MATURITY_EVIDENCE_MISSING:{wanted}")

    collection_keys = ("collectionName", "collection", "collection_name")
    collection_values = [
        str(props[k]).strip()
        for k in collection_keys
        if props.get(k) is not None and str(props[k]).strip()
    ]
    conflicting_collections = [
        value for value in collection_values
        if EXPECTED_COLLECTION not in value
    ]
    if conflicting_collections:
        raise CatalogIdentityError(
            f"ASF_COLLECTION_CONFLICT:{wanted}:values={conflicting_collections}"
        )

    catalog_bytes, size_evidence = _catalog_size_evidence(product, props, wanted)
    if catalog_bytes is not None and catalog_bytes != int(target["expected_source_bytes"]):
        raise CatalogIdentityError(
            f"ASF_BYTE_SIZE_CHANGED:{wanted}:expected={target['expected_source_bytes']}:actual={catalog_bytes}"
        )

    identity = parse_granule_identity(wanted + ".h5")
    expected = {
        "reference_date": identity.reference_start.date().isoformat(),
        "secondary_date": identity.secondary_start.date().isoformat(),
    }
    for field, value in expected.items():
        if str(target[field]) != value:
            raise CatalogIdentityError(
                f"PINNED_TARGET_DATE_CONFLICT:{wanted}:{field}:expected={value}:configured={target[field]}"
            )
    if identity.track != "098" or identity.direction != "A" or identity.processing != "PR":
        raise CatalogIdentityError(f"PINNED_TARGET_GEOMETRY_MISMATCH:{wanted}")
    if identity.release_id is None:
        raise CatalogIdentityError(f"PINNED_TARGET_RELEASE_ID_MISSING:{wanted}")

    collection_evidence = (
        EXPECTED_COLLECTION if EXPECTED_COLLECTION in collection_values
        else f"exact_object_url_collection:{EXPECTED_COLLECTION}"
    )
    evidence = (
        f"current ASF Search exact-granule query; "
        f"maturity={maturity or 'collection-route-only'}; "
        f"collection={collection_evidence}; "
        f"checked_utc={datetime.now(timezone.utc).isoformat()}"
    )
    return {
        **target,
        "source_filename": wanted + ".h5",
        "product_type": "GOFF",
        "processing": identity.processing,
        "frame": identity.frame,
        "track": identity.track,
        "direction": identity.direction,
        "polarization": "HH",
        "layer": "layer2",
        "release_id": identity.release_id,
        "catalog_maturity": EXPECTED_MATURITY,
        "catalog_collection": EXPECTED_COLLECTION,
        "catalog_maturity_evidence": evidence,
        "catalog_size_bytes": catalog_bytes,
        "catalog_size_evidence": size_evidence,
        "catalog_url_host": urlparse(urls[0]).hostname,
        "expected_source_sha256": str(target["historical_source_sha256"]),
        "source_identity_comparison": f"SHA256_MATCH_REQUIRED_TO_RUN;reference_run={REFERENCE_RUN_ID}",
        "author_product_variant_status": "NOT_VERIFIED_AGAINST_AUTHOR_SUPPLEMENT",
    }


def discover_exact_products() -> list[dict[str, Any]]:
    """Call ASF Search for each exact identifier and fail closed on catalog mismatch."""
    try:
        import asf_search
    except ImportError as exc:
        raise CatalogIdentityError("ASF_SEARCH_DEPENDENCY_MISSING") from exc

    outputs: list[dict[str, Any]] = []
    for target in TARGET_PRODUCTS:
        wanted = str(target["granule_name"])
        try:
            results = list(asf_search.search(dataset="NISAR", granule_list=[wanted]))
        except Exception as exc:
            # Do not print a URL or full request exception; only its type is safe.
            raise CatalogIdentityError(
                f"ASF_CATALOG_QUERY_FAILED:{wanted}:exception={type(exc).__name__}"
            ) from None
        outputs.append(validate_exact_catalog_product(target, results))
    return outputs


def write_catalog_manifest(out_path: str | Path) -> dict[str, Any]:
    out = Path(out_path)
    products = discover_exact_products()
    manifest = {
        "schema_version": "know-place-catalog-manifest/1.0",
        "status": "PASS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_reference_run_id": REFERENCE_RUN_ID,
        "requested_collection": EXPECTED_COLLECTION,
        "requested_maturity": EXPECTED_MATURITY,
        "scientific_warning": (
            "Exact current catalog identity and source hashes are gates. "
            "These candidate granule variants have not been independently verified "
            "against an author-supplied product list or golden raster."
        ),
        "products": products,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = write_catalog_manifest(args.out)
    except (CatalogIdentityError, GoffReadError, OSError, ValueError) as exc:
        print("KNOW_PLACE_CATALOG_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:{exc}")
        return 2
    print("KNOW_PLACE_CATALOG_STATUS=PASS")
    print(f"PAPER_PAIR_CATALOG_PRODUCTS={len(manifest['products'])}")
    print(f"MANIFEST={args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
