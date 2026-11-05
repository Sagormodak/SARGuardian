# Dynamic AOI WKT E2E processing

## Launch

Run the **SARGuardian AOI WKT E2E + Dashboard** workflow directly on `feat/final-aoi-science-integration` from the Actions tab to process an explicit WKT polygon and date window. The dispatcher on `main` still targets `feat/e2e-aoi-wkt-date-dashboard`; it has deliberately not been changed from this feature branch. Until that dispatcher reference is updated after review, run the integration workflow directly on this branch. The fixed source-AOI streaming workflow remains available separately, and both paths invoke the shared export-science diagnostics adapter.

Inputs:

- **AOI WKT**: one `POLYGON ((lon lat, ...))` exterior ring, coordinates in EPSG:4326 and in longitude/latitude order. An open ring is closed automatically. Holes, `MULTIPOLYGON`, 3-D coordinates and other SRIDs are rejected.
- **Start / end date**: inclusive interval applied by default to the **secondary acquisition date** in each GUNW/GOFF pair. This is practical when the requested window refers to the pair's secondary-time endpoint: a pair whose reference acquisition was a few days earlier can still be selected if its secondary acquisition is inside the interval. The manifest retains both dates and flags reference dates outside the interval. Choose `both-acquisitions-in-window` for a stricter interpretation requiring both dates to fall inside. ASF catalog search begins in 2024 so a valid pair can be found even when its reference acquisition predates the requested start.
- **validation-pilot**: newest supported GUNW and newest supported GOFF intersecting the AOI/window. A quick operational check, not a full baseline.
- **full-aoi-baseline**: all supported GUNW and GOFF granules discovered for the exact polygon/window. Discovery stops on an incomplete ASF result set or more than 200 selected products; narrow the dates/AOI instead of silently truncating.
- **derived-only**: store derived maps, metrics and provenance; raw worker copies can be deleted only after remote storage verification.
- **full-lossless**: also retain the lossless HDF5 archive and require raw/archive reader equivalence.

## Pipeline design

1. Validate WKT geometry and dates.
2. Query the ASF DAAC catalog with the exact polygon WKT (`intersectsWith`) separately for GUNW and GOFF, using `dataset=NISAR`, exact `processingLevel`, GeoJSON, and two independent `dataMaturity` filters (`PROVISIONAL` and `BETA`). ASF documents `dataMaturity` as the search filter for calibration/validation class. The workflow merges results by exact granule ID and fails closed if one granule is returned in both maturity classes. Response normalization handles GeoJSON feature properties and nested-list responses; logs keep separate maturity-filter counts.
3. Parse both reference and secondary acquisition dates from the four timestamps in the pair granule identifier. Apply the selected date-window mode. The product date fields are distinct from processing/production time and do not, by themselves, define maturity. Record catalog counts, date exclusions, maturity evidence, AOI WKT SHA-256 and the exact science commit.
4. Resolve maturity from the authoritative ASF `dataMaturity` filter and corroborate it with the returned collection label and CRID mapping. The explicit maturity filter takes priority over the pinned local CRID helper when a new CRID is not mapped locally, but both sources are retained in provenance. In the live catalog, `X05026` is returned by ASF's PROVISIONAL filter and appears in `NISAR_L2_GUNW_PROVISIONAL_V1` / `NISAR_L2_GOFF_PROVISIONAL_V1`, although the local helper does not map X05026; this is recorded as an unmapped-CRID caveat, not reclassified from acquisition date and not called BETA. If a recognized CRID conflicts with ASF's explicit maturity label, exclude it as a metadata conflict. `PR`, `UR`, and `OD` identify processing type; the post-CRID `P/M/N/F` field describes orbit/pointing accuracy, not maturity.
5. Collapse release and processing variants of the same product family, geometry/mode and reference-secondary pair; a different CRID is not a new observation. Prefer PROVISIONAL over BETA for the same pair, then standard `PR` over `OD` science-on-demand and `UR` urgent-response. If same-pair `PR` releases both exist, prefer the documented P-series release over a locally unmapped X-series release, recording both in the manifest; this avoids treating reprocessed CRID variants as separate acquisitions. Then prefer precise/medium/near-real-time/forecast orbit accuracy and full coverage over partial coverage. Variant selection is deterministic and auditable.
6. Download and validate each exact selected granule with the existing protected worker pattern, but use the `custom` AOI all the way through product preflight, GUNW/GOFF reader, export, provenance and retention receipts.
7. Retry only products that lack a complete, hash-consistent processing/cleanup receipt pair.
8. Generate a downloadable, self-contained HTML dashboard, CSV product table, per-product quicklooks and a result ZIP. If Drive credentials are configured, also upload summary/bundle files to the configured private Drive location.

## Important interpretation limits

- This dashboard is generated as a **GitHub Actions artifact**; it is not automatically mounted into the public website/API. The UI can be opened offline after downloading the `sarguardian-aoi-dashboard-*` artifact and opening `index.html`.
- The existing 33-product source-AOI baseline is deliberately not used for numeric pixel-by-pixel comparison: a custom AOI has different spatial support, so that comparison would be scientifically invalid.
- Structural PASS means the requested AOI was used, the catalog/product identity and source SHA were recorded, the product grid intersects the AOI, exports exist and retention receipts validate. It is **not** independent geophysical validation, proof of slope failure, or a validated common-reference displacement time series.
- Per-image quicklook colour scales are independent. Cross-product medians are not directly comparable unless geometry, reference datum, coherence/quality support, atmosphere and release effects have been handled.
- No-valid-pixel products are surfaced as warnings rather than described as zero motion.
- The workflow needs the existing Earthdata credentials and private-Drive secrets required by the worker's chosen retention mode. These secrets must never be placed in WKT inputs.


## Scientific policy sources

- NISAR naming convention identifies GUNW and GOFF as products generated from a **pair** of acquisitions: https://nisar-docs.asf.alaska.edu/naming-conventions/
- ASF/NISAR data availability documents P05023+ for PROVISIONAL, acquisitions beginning June 17, 2026, and warns that processor changes across maturities can mimic landscape change: https://nisar-docs.asf.alaska.edu/availability-overview/
- ASF Search documents `dataMaturity=PROVISIONAL` and `dataMaturity=BETA` as calibration/validation classification filters: https://nisar-docs.asf.alaska.edu/asf-search/
- ASF's Search guide explicitly documents `dataMaturity=PROVISIONAL` and `dataMaturity=BETA` as the calibration/validation filter: https://nisar-docs.asf.alaska.edu/asf-search/
- PROVISIONAL means calibrated and partially validated, not fully validated. Known issues and ongoing processing improvements remain: https://nisar-docs.asf.alaska.edu/provisional-known-issues/
