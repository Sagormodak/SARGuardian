"""Live ASF identity check for the author's exact five GOFF granules.

This gate confirms catalog identity only. It never downloads HDF5 or invents a
source checksum. Source-byte and SHA-256 pins are added only after exact bytes
are deliberately fetched and independently recorded.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .catalog import (
    EXPECTED_COLLECTION,
    EXPECTED_MATURITY,
    CatalogIdentityError,
    _is_trusted_asf_url,
    _normalise_product_name,
    _product_properties,
    _product_urls,
)
from .goff_io import GoffReadError, parse_granule_identity


REPO_ROOT = Path(__file__).resolve().parents[2]
CMR_COLLECTION_CONCEPT_ID = "C2854341702-ASF"
CMR_SEARCH_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
CMR_CONFIRMED_STATUSES = {"EXACT_URL_CONFIRMED", "EXACT_CMR_GRANULE_CONFIRMED"}
AUTHOR_FALLBACK_CROWN_WKT = "POLYGON ((85.5245 28.2847, 85.5400 28.2847, 85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))"
AUTHOR_BENCHMARK_PATH = (
    REPO_ROOT / "docs" / "know-place" / "reference" / "author_benchmark_v1.json"
)


def _cmr_entry_exact_identity(entry: dict[str, Any], wanted: str) -> bool:
    """Require an exact producer-granule name in a scoped CMR response."""
    for field in ("producer_granule_id", "granule_ur", "title"):
        value = entry.get(field)
        if not isinstance(value, str):
            continue
        normalized = _normalise_product_name(value)
        if normalized == wanted:
            return True
    return False


def _cmr_entry_collection_id(entry: dict[str, Any]) -> str | None:
    value = entry.get("collection_concept_id")
    if isinstance(value, str) and value:
        return value
    # A few CMR output variants include collection identity under related metadata.
    collection = entry.get("collection")
    if isinstance(collection, dict):
        nested = collection.get("concept_id") or collection.get("collection_concept_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def query_cmr_exact_author_product(
    target: dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Query NASA CMR for one exact author granule in the pinned ASF collection.

    This checks collection-scoped metadata only. It never downloads a GOFF
    payload, follows a data link, or treats CMR metadata as source-byte identity.
    Two documented CMR filters are tried individually so the query doesn't
    accidentally AND producer ID with a different granule-UR representation.
    """
    import urllib.error

    wanted = str(target["granule_name"])
    query_variants = (
        ("producer_granule_id[]", "PRODUCER_GRANULE_ID_EXACT"),
        ("readable_granule_name[]", "READABLE_GRANULE_NAME_EXACT"),
    )
    receipts: list[dict[str, Any]] = []
    seen_entries: dict[str, dict[str, Any]] = {}
    for parameter, label in query_variants:
        query = [
            ("collection_concept_id", CMR_COLLECTION_CONCEPT_ID),
            (parameter, wanted),
            ("page_size", "100"),
        ]
        url = CMR_SEARCH_URL + "?" + urlencode(query)
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "SARGuardian-KnowPlace-AuthorCatalogAudit/1.0",
                },
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                status_code = getattr(response, "status", None)
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("CMR_RESPONSE_NOT_OBJECT")
            feed = payload.get("feed", {})
            entries = feed.get("entry", []) if isinstance(feed, dict) else []
            if not isinstance(entries, list):
                raise ValueError("CMR_ENTRY_LIST_INVALID")
            receipts.append({
                "query_kind": label,
                "query_parameter": parameter,
                "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
                "http_status": status_code or 200,
                "result_count": len(entries),
                "status": "QUERY_COMPLETED",
            })
            for entry in entries:
                if not isinstance(entry, dict) or not _cmr_entry_exact_identity(entry, wanted):
                    continue
                collection_id = _cmr_entry_collection_id(entry)
                if collection_id and collection_id != CMR_COLLECTION_CONCEPT_ID:
                    continue
                identity_key = str(entry.get("id") or entry.get("granule_ur") or entry.get("producer_granule_id") or "")
                if identity_key:
                    seen_entries[identity_key] = entry
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            receipts.append({
                "query_kind": label,
                "query_parameter": parameter,
                "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
                "status": "QUERY_FAILED",
                "exception_type": type(exc).__name__,
            })

    matches = list(seen_entries.values())
    if len(matches) == 1:
        entry = matches[0]
        identity = parse_granule_identity(wanted + ".h5")
        collection_id = _cmr_entry_collection_id(entry)
        # The search itself is collection-scoped. If returned metadata omits the
        # collection field, the query provenance is still preserved explicitly.
        metadata = {
            key: entry.get(key)
            for key in (
                "id", "producer_granule_id", "granule_ur", "title",
                "collection_concept_id", "time_start", "time_end", "updated",
                "orbit_number", "day_night_flag",
            )
            if entry.get(key) is not None
        }
        links = entry.get("links")
        if isinstance(links, list):
            metadata["links"] = [
                {
                    k: link.get(k)
                    for k in ("rel", "title", "hreflang", "type", "href", "inherited")
                    if link.get(k) is not None
                }
                for link in links
                if isinstance(link, dict)
            ]
        record = {
            "granule_name": wanted,
            "interval": target["interval"],
            "processing": identity.processing,
            "track": identity.track,
            "direction": identity.direction,
            "release_id": identity.release_id,
            "collection": EXPECTED_COLLECTION,
            "catalog_maturity": EXPECTED_MATURITY,
            "catalog_url_host": "cmr.earthdata.nasa.gov",
            "catalog_identity_status": "EXACT_CMR_GRANULE_CONFIRMED",
            "catalog_identity_discovery_method": "NASA_CMR_COLLECTION_SCOPED_EXACT_QUERY",
            "catalog_maturity_evidence": (
                f"NASA CMR exact granule metadata scoped to collection {CMR_COLLECTION_CONCEPT_ID}"
            ),
            "cmr_collection_concept_id": collection_id or CMR_COLLECTION_CONCEPT_ID,
            "cmr_search_receipts": receipts,
            "cmr_metadata": metadata,
            "source_sha256": None,
            "source_sha256_status": "NOT_DOWNLOADED",
            "cmr_source_payload_downloaded": False,
        }
        return record, {
            "status": "EXACT_AUTHOR_ID_CONFIRMED",
            "target_granule_name": wanted,
            "interval": target["interval"],
            "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
            "query_receipts": receipts,
            "exact_author_id_found": True,
            "metadata_match_count": 1,
            "source_downloads": 0,
        }
    status = "NOT_FOUND" if not matches else "AMBIGUOUS"
    if all(row.get("status") == "QUERY_FAILED" for row in receipts):
        status = "QUERY_FAILED"
    return None, {
        "status": status,
        "target_granule_name": wanted,
        "interval": target["interval"],
        "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
        "query_receipts": receipts,
        "exact_author_id_found": False,
        "metadata_match_count": len(matches),
        "source_downloads": 0,
    }


def load_author_granules(path: str | Path = AUTHOR_BENCHMARK_PATH) -> list[dict[str, Any]]:
    """Load the five source IDs transcribed from Supplementary Table 1."""
    with Path(path).open("r", encoding="utf-8") as stream:
        benchmark = json.load(stream)
    pairs = benchmark.get("exact_author_granules")
    if not isinstance(pairs, list) or len(pairs) != 5:
        raise CatalogIdentityError("AUTHOR_GRANULE_MANIFEST_MUST_HAVE_FIVE_PAIRS")
    expected_intervals = [
        ("2026-06-20", "2026-07-02"),
        ("2026-07-02", "2026-07-14"),
        ("2026-07-14", "2026-07-26"),
        ("2026-07-26", "2026-08-19"),
        ("2026-08-19", "2026-08-31"),
    ]
    products: list[dict[str, Any]] = []
    for row, expected_dates in zip(pairs, expected_intervals, strict=True):
        name = row.get("id")
        interval = row.get("interval")
        if not isinstance(name, str) or not name or not isinstance(interval, str):
            raise CatalogIdentityError("AUTHOR_GRANULE_MANIFEST_ENTRY_INVALID")
        try:
            start, end = interval.split("/", maxsplit=1)
        except ValueError:
            raise CatalogIdentityError(f"AUTHOR_GRANULE_INTERVAL_INVALID:{name}") from None
        identity = parse_granule_identity(name + ".h5")
        actual_dates = (
            identity.reference_start.date().isoformat(),
            identity.secondary_start.date().isoformat(),
        )
        if (start, end) != expected_dates or actual_dates != expected_dates:
            raise CatalogIdentityError(
                f"AUTHOR_GRANULE_DATE_CONFLICT:{name}:expected={expected_dates}:actual={actual_dates}"
            )
        if identity.processing != "PR" or identity.track != "098" or identity.direction != "A":
            raise CatalogIdentityError(f"AUTHOR_GRANULE_GEOMETRY_MISMATCH:{name}")
        if identity.release_id != "P05023":
            raise CatalogIdentityError(f"AUTHOR_GRANULE_RELEASE_MISMATCH:{name}")
        products.append({"granule_name": name, "interval": interval, "days": int(row.get("days", 0))})
    if any("_P05023_" not in row["granule_name"] for row in products):
        raise CatalogIdentityError("AUTHOR_GRANULE_RELEASE_MANIFEST_CONFLICT")
    return products


def validate_author_catalog_product(
    target: dict[str, Any], results: list[Any]
) -> dict[str, Any]:
    """Confirm one exact author ID, expected collection and no conflicting maturity."""
    wanted = str(target["granule_name"])
    identity_keys = (
        "fileName", "granuleName", "sceneName", "productName",
        "producerGranuleId", "producerGranuleID", "granule_ur", "fileID", "name",
    )
    matches: list[tuple[dict[str, Any], list[str]]] = []
    for product in results:
        props = _product_properties(product)
        urls = _product_urls(product, props)
        exact_urls = [
            url for url in urls
            if _is_trusted_asf_url(url)
            and _normalise_product_name(url) == wanted
            and f"/{EXPECTED_COLLECTION}/" in urlparse(url).path
        ]
        exact_identity = any(_normalise_product_name(props.get(key)) == wanted for key in identity_keys)
        if exact_urls and (exact_identity or len(exact_urls) >= 1):
            matches.append((props, exact_urls))
    if not matches:
        raise CatalogIdentityError(f"ASF_AUTHOR_EXACT_GRANULE_NOT_FOUND:{wanted}")
    if len(matches) != 1:
        raise CatalogIdentityError(f"ASF_AUTHOR_EXACT_GRANULE_AMBIGUOUS:{wanted}:matches={len(matches)}")

    props, urls = matches[0]
    maturity_raw = props.get("dataMaturity") or props.get("maturity")
    maturity = str(maturity_raw or "").strip().upper()
    if maturity and maturity != EXPECTED_MATURITY:
        raise CatalogIdentityError(
            f"ASF_AUTHOR_MATURITY_CONFLICT:{wanted}:expected={EXPECTED_MATURITY}:actual={maturity}"
        )

    collection_values = [
        str(props[key]).strip()
        for key in ("collectionName", "collection", "collection_name")
        if props.get(key) is not None and str(props[key]).strip()
    ]
    if any(EXPECTED_COLLECTION not in value for value in collection_values):
        raise CatalogIdentityError(f"ASF_AUTHOR_COLLECTION_CONFLICT:{wanted}")

    identity = parse_granule_identity(wanted + ".h5")
    return {
        "granule_name": wanted,
        "interval": target["interval"],
        "processing": identity.processing,
        "track": identity.track,
        "direction": identity.direction,
        "release_id": identity.release_id,
        "collection": EXPECTED_COLLECTION,
        "catalog_maturity": maturity or "COLLECTION_ROUTE_ONLY",
        "catalog_url_host": urlparse(urls[0]).hostname,
        "catalog_identity_status": "EXACT_URL_CONFIRMED",
        "source_sha256": None,
        "source_sha256_status": "NOT_DOWNLOADED",
    }


def _fallback_candidate_record(
    product: Any, target: dict[str, Any]
) -> dict[str, Any] | None:
    """Summarize only trusted catalog URLs whose pair dates and orbit match."""
    props = _product_properties(product)
    urls = _product_urls(product, props)
    target_start, target_end = target["interval"].split("/", maxsplit=1)
    for url in urls:
        if not _is_trusted_asf_url(url):
            continue
        if f"/{EXPECTED_COLLECTION}/" not in urlparse(url).path:
            continue
        name = _normalise_product_name(url)
        if not name:
            continue
        try:
            identity = parse_granule_identity(name + ".h5")
        except GoffReadError:
            continue
        actual_start = identity.reference_start.date().isoformat()
        actual_end = identity.secondary_start.date().isoformat()
        if (actual_start, actual_end) != (target_start, target_end):
            continue
        if identity.track != "098" or identity.direction != "A" or identity.processing != "PR":
            continue
        reported_maturity = str(props.get("dataMaturity") or props.get("maturity") or "").strip().upper()
        return {
            "granule_name": name,
            "interval": target["interval"],
            "processing": identity.processing,
            "track": identity.track,
            "direction": identity.direction,
            "release_id": identity.release_id,
            "collection": EXPECTED_COLLECTION,
            "catalog_maturity": reported_maturity or "COLLECTION_ROUTE_ONLY",
            "catalog_url_host": urlparse(url).hostname,
            "catalog_identity_status": (
                "EXACT_AUTHOR_ID_FOUND_IN_FALLBACK_QUERY"
                if name == target["granule_name"]
                else "SAME_INTERVAL_VARIANT_CANDIDATE_ONLY"
            ),
            "source_sha256": None,
            "source_sha256_status": "NOT_DOWNLOADED",
        }
    return None


def _discover_author_products_with_fallback(*, include_cmr: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run exact-ID lookups, then an AOI/date catalog search for any unresolved pair.

    The fallback is discovery-only. It records same-pair release variants, but
    never upgrades a different product ID into the author-exact source.
    No data payload is downloaded.
    """
    try:
        import asf_search
    except ImportError as exc:
        raise CatalogIdentityError("ASF_SEARCH_DEPENDENCY_MISSING") from exc

    verified: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for target in load_author_granules():
        wanted = target["granule_name"]
        try:
            results = list(asf_search.search(dataset="NISAR", granule_list=[wanted]))
        except Exception as exc:
            raise CatalogIdentityError(
                f"ASF_AUTHOR_QUERY_FAILED:{wanted}:exception={type(exc).__name__}"
            ) from None
        try:
            row = validate_author_catalog_product(target, results)
            row["catalog_identity_discovery_method"] = "DIRECT_GRANULE_LIST_QUERY"
        except CatalogIdentityError as exc:
            # Exact-ID identity stays blocked unless trusted metadata confirms
            # the exact ID. Continue querying every pair regardless of blockers.
            identity = parse_granule_identity(wanted + ".h5")
            message = str(exc)
            if message.startswith("ASF_AUTHOR_EXACT_GRANULE_NOT_FOUND"):
                status = "NOT_FOUND"
            elif message.startswith("ASF_AUTHOR_EXACT_GRANULE_AMBIGUOUS"):
                status = "AMBIGUOUS"
            else:
                status = "REJECTED"
            row = {
                "granule_name": wanted,
                "interval": target["interval"],
                "processing": identity.processing,
                "track": identity.track,
                "direction": identity.direction,
                "release_id": identity.release_id,
                "collection": EXPECTED_COLLECTION,
                "catalog_maturity": None,
                "catalog_url_host": None,
                "catalog_identity_status": status,
                "catalog_identity_discovery_method": "DIRECT_GRANULE_LIST_QUERY",
                "blocking_reason": message,
                "source_sha256": None,
                "source_sha256_status": "NOT_DOWNLOADED",
            }
            if status == "NOT_FOUND":
                unresolved.append(target)
        verified.append(row)

    fallback_reports: list[dict[str, Any]] = []
    for target in unresolved:
        start_date, end_date = target["interval"].split("/", maxsplit=1)
        spatial_query = {
            "dataset": "NISAR",
            "intersectsWith": AUTHOR_FALLBACK_CROWN_WKT,
            "start": f"{start_date}T00:00:00Z",
            "end": f"{end_date}T23:59:59Z",
            "processingLevel": "GOFF",
            "mainBandPolarization": "HH",
            "maxResults": 500,
        }
        # ASF documents wildcard matching for granule_list. This narrower
        # filename query is deliberately separate from the AOI/date query:
        # it catches a scene's release/processing variants without assuming
        # that any returned variant equals the author-selected product.
        wildcard_pattern = target["granule_name"].replace("_P05023_", "_*_", 1)
        wildcard_query = {
            "dataset": "NISAR",
            "granule_list": [wildcard_pattern],
            "maxResults": 100,
        }
        target_row = next(row for row in verified if row["granule_name"] == target["granule_name"])
        spatial_candidates: list[Any] = []
        wildcard_candidates: list[Any] = []
        spatial_error = None
        wildcard_error = None
        try:
            spatial_candidates = list(asf_search.search(**spatial_query))
        except Exception as exc:
            spatial_error = type(exc).__name__
        try:
            wildcard_candidates = list(asf_search.search(**wildcard_query))
        except Exception as exc:
            wildcard_error = type(exc).__name__

        matching_by_name: dict[str, dict[str, Any]] = {}
        for method, products in (
            ("AOI_DATE_QUERY", spatial_candidates),
            ("GRANULE_WILDCARD_QUERY", wildcard_candidates),
        ):
            for product in products:
                record = _fallback_candidate_record(product, target)
                if record is None:
                    continue
                name = record["granule_name"]
                if name in matching_by_name:
                    prior = matching_by_name[name]
                    prior["discovery_methods"] = sorted(set(
                        prior.get("discovery_methods", []) + [method]
                    ))
                else:
                    record["discovery_methods"] = [method]
                    matching_by_name[name] = record
        matching_candidates = list(matching_by_name.values())

        combined_candidates: list[Any] = []
        seen_exact_names: set[str] = set()
        for product in spatial_candidates + wildcard_candidates:
            urls = _product_urls(product, _product_properties(product))
            exact_name = next((
                _normalise_product_name(url) for url in urls
                if _is_trusted_asf_url(url)
                and f"/{EXPECTED_COLLECTION}/" in urlparse(url).path
            ), "")
            if exact_name == target["granule_name"] and exact_name not in seen_exact_names:
                combined_candidates.append(product)
                seen_exact_names.add(exact_name)

        exact_found = False
        if combined_candidates:
            try:
                recovered = validate_author_catalog_product(target, combined_candidates)
            except CatalogIdentityError:
                target_row["spatiotemporal_fallback_search_status"] = "EXACT_ID_CANDIDATE_REJECTED"
            else:
                if any(
                    _normalise_product_name(url) == target["granule_name"]
                    for product in wildcard_candidates
                    for url in _product_urls(product, _product_properties(product))
                ):
                    method = "GRANULE_WILDCARD_QUERY_AFTER_DIRECT_ID_MISS"
                else:
                    method = "AOI_DATE_FALLBACK_QUERY_AFTER_DIRECT_ID_MISS"
                recovered["catalog_identity_discovery_method"] = method
                recovered["direct_exact_id_query_status"] = "NOT_FOUND"
                verified[verified.index(target_row)] = recovered
                target_row = recovered
                exact_found = True

        all_fallbacks_failed = spatial_error is not None and wildcard_error is not None
        result_cap_reached = (
            len(spatial_candidates) >= spatial_query["maxResults"]
            or len(wildcard_candidates) >= wildcard_query["maxResults"]
        )
        if not exact_found and target_row["catalog_identity_status"] == "NOT_FOUND":
            if all_fallbacks_failed:
                status = "QUERY_FAILED"
            elif result_cap_reached:
                status = "RESULT_CAP_REACHED_NO_EXACT_ID"
            else:
                status = "COMPLETED_NO_EXACT_AUTHOR_ID_FOUND"
            target_row["spatiotemporal_fallback_search_status"] = status
            target_row["same_interval_candidates"] = matching_candidates

        cmr_record = None
        cmr_report: dict[str, Any] = {
            "status": "NOT_RUN_OFFLINE_TEST_MODE" if not include_cmr else "NOT_NEEDED_EXACT_ASF_MATCH",
            "target_granule_name": target["granule_name"],
            "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
            "exact_author_id_found": False,
            "source_downloads": 0,
        }
        if include_cmr and not exact_found and target_row.get("catalog_identity_status") == "NOT_FOUND":
            try:
                cmr_record, cmr_report = query_cmr_exact_author_product(target)
            except Exception as exc:
                # Catalog transport/parsing failure is evidence, not an exact-ID miss.
                cmr_record = None
                cmr_report = {
                    "status": "QUERY_FAILED",
                    "target_granule_name": target["granule_name"],
                    "interval": target["interval"],
                    "collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
                    "exception_type": type(exc).__name__,
                    "exact_author_id_found": False,
                    "source_downloads": 0,
                }
            if cmr_record is not None:
                cmr_record["direct_asf_id_query_status"] = "NOT_FOUND"
                cmr_record["asf_fallback_status"] = target_row.get(
                    "spatiotemporal_fallback_search_status", "COMPLETED_NO_EXACT_AUTHOR_ID_FOUND"
                )
                cmr_record["same_interval_variant_candidates"] = matching_candidates
                cmr_record["asf_catalog_identity_status"] = "NOT_FOUND"
                cmr_record["source_sha256"] = None
                cmr_record["source_sha256_status"] = "NOT_DOWNLOADED"
                verified[verified.index(target_row)] = cmr_record
                target_row = cmr_record

        cmr_exact_found = cmr_record is not None
        fallback_status = (
            "EXACT_AUTHOR_ID_CONFIRMED_BY_CMR" if cmr_exact_found else
            ("EXACT_AUTHOR_ID_CONFIRMED_BY_ASF" if exact_found else (
                "CMR_QUERY_FAILED" if include_cmr and cmr_report.get("status") == "QUERY_FAILED" else (
                    "QUERY_FAILED" if all_fallbacks_failed else (
                        "RESULT_CAP_REACHED" if result_cap_reached else "COMPLETED_NO_EXACT_AUTHOR_ID_FOUND"
                    )
                )
            ))
        )
        fallback_reports.append({
            "target_granule_name": target["granule_name"],
            "interval": target["interval"],
            "status": fallback_status,
            "spatiotemporal_query": {
                key: value for key, value in spatial_query.items() if key != "intersectsWith"
            },
            "aoi_wkt_sha256": __import__("hashlib").sha256(
                AUTHOR_FALLBACK_CROWN_WKT.encode("utf-8")
            ).hexdigest(),
            "spatiotemporal_query_result_count": len(spatial_candidates) if spatial_error is None else None,
            "spatiotemporal_query_exception_type": spatial_error,
            "wildcard_query": wildcard_query,
            "wildcard_query_result_count": len(wildcard_candidates) if wildcard_error is None else None,
            "wildcard_query_exception_type": wildcard_error,
            "same_interval_candidates": matching_candidates,
            "asf_exact_author_id_found": exact_found,
            "cmr_exact_author_id_found": cmr_exact_found,
            "cmr_fallback": cmr_report,
            "exact_author_id_found": exact_found or cmr_exact_found,
            "source_downloads": 0,
        })
    return verified, fallback_reports


def discover_author_products() -> list[dict[str, Any]]:
    """Query ASF and NASA CMR catalog metadata; never downloads GOFF payloads."""
    return _discover_author_products_with_fallback(include_cmr=True)[0]


def write_manifest(out_path: str | Path) -> dict[str, Any]:
    products, fallback_searches = _discover_author_products_with_fallback(include_cmr=True)
    blocked = [
        row for row in products
        if row.get("catalog_identity_status") not in CMR_CONFIRMED_STATUSES
    ]
    manifest = {
        "schema_version": "know-place-author-catalog-manifest/1.0",
        "status": "BLOCKED" if blocked else "PASS",
        "catalog_checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_payload_downloaded": False,
        "source_hashes_recorded": False,
        "blocking_product_count": len(blocked),
        "warning": (
            "Catalog identity is not source-byte identity, method parity, a golden-output "
            "comparison, or a hazard detection. SHA-256 remains unknown until exact bytes "
            "are separately fetched and hashed. A BLOCKED status means the exact source "
            "identity is unresolved; it is not reinterpreted as a successful match."
        ),
        "products": products,
        "spatiotemporal_fallback_searches": fallback_searches,
        "cmr_collection_concept_id": CMR_COLLECTION_CONCEPT_ID,
        "catalog_identity_confirmed_count": sum(p.get("catalog_identity_status") in CMR_CONFIRMED_STATUSES for p in products),
        "raw_payload_downloads": 0,
    }
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = write_manifest(args.out)
    except (CatalogIdentityError, GoffReadError, OSError, ValueError) as exc:
        print("KNOW_PLACE_AUTHOR_CATALOG_STATUS=FAIL")
        print(f"ERROR={type(exc).__name__}:{exc}")
        return 2
    print(f"KNOW_PLACE_AUTHOR_CATALOG_STATUS={manifest['status']}")
    print(f"AUTHOR_GRANULE_COUNT={len(manifest['products'])}")
    print(f"CATALOG_GRANULE_IDENTITIES_CONFIRMED={manifest['catalog_identity_confirmed_count']}")
    print(f"BLOCKING_PRODUCTS={manifest['blocking_product_count']}")
    print("SOURCE_DOWNLOADS=0")
    print(f"MANIFEST={args.out.resolve()}")
    # A fully completed query that reveals a missing author product is a
    # scientific gate blocker, not a code-test failure. Query/transport errors
    # still raise above and exit nonzero.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
