# Implementation Checklist — Interactive Science Dashboard

Statuses: `DONE`, `IN_PROGRESS`, `BLOCKED`, `NOT_STARTED`. A checklist item moves to DONE only with code/test/evidence links.

## Phase 0 — Evidence and architecture
- [x] Audit the successful processing run and download dashboard artifact.
- [x] Inventory existing PNG quicklooks, multi-band GeoTIFFs, CSV/reports, provenance, and pixel-stack diagnostics.
- [x] Identify no-geospatial-map and no-playback gaps in current HTML.
- [x] Document scientific guardrails, current AOI distinction, formats, and source references.
- [x] Add a representative synthetic GeoTIFF fixture to automated tests without committing proprietary or large raw HDF5 files.

## Phase 1 — Processing-time map assets (no raw replay)
- [x] Implement a deterministic web-asset builder in `dashboard/assets/` (`prepare_web_assets.py`).
- [x] Reproject each validated raster band to display-friendly geographic coordinates from the source CRS and affine transform using Rasterio/GDAL.
- [x] Produce transparent preview PNGs with explicit corners/bounds; keep native GeoTIFFs unchanged.
- [x] Build `web-dashboard/manifest.json`, `aoi.geojson`, `timeline.json`, `metrics.json`, STAC catalog/collection/items.
- [x] Record per-layer band name/units, value range, color scale policy, NoData/valid-pixel info, source CRS/transform/hash, science/orchestration commits and AOI hash.
- [ ] Harden validation further: enforce full manifest/schema shape, true polygon-to-valid-pixel intersection (not only conservative bounding-box overlap), all-NaN/empty bands, and checksum round-trips.
- [x] Add unit tests for cross-UTM reprojection, NoData transparency, STAC paths, common scale within the same track group and source TIFF immutability.\n- [ ] Extend tests for missing band descriptions, all-empty bands, multi-export products and deterministic rebuilds.
- [x] Wire builder into AOI aggregation before ZIP creation and Drive upload. The new visualization build is best-effort and reports its own status so a render issue cannot mark scientific processing as failed.
- [ ] Add generated file list and explicit status to workflow step summary; review the private Drive package inventory and preserve the three required account artifacts.
- [ ] Run the exact committed builder against the downloaded run artifact and compare all source TIFF hashes before/after.

## Phase 2 — Interactive offline/presentation viewer
- [ ] Add map panel showing true AOI geometry and geo-located preview layer, never a schematic pretending to be the map.
- [ ] Add product/band selector, opacity slider, legend with units/scale, product details and pixel count.
- [ ] Add acquisition-pair timeline, Play/Pause, previous/next, playback speed and date labels.
- [ ] Group observations by track/view geometry; do not interpolate missing acquisitions or join incompatible pairwise measurements as a trend.
- [ ] Add scientific metric charts, data-quality/support chart, provenance card, limitation banners, and export links.
- [ ] Add graceful no-basemap/offline fallback and explicit map-data attribution.
- [ ] Add keyboard, mobile, contrast, reduced-motion, and presentation/full-screen checks.

## Phase 3 — Authenticated Dynamic app integration
- [ ] Define owner-scoped read-only dashboard metadata/assets endpoint or verified bundle download.
- [ ] Enforce Firebase owner authentication and server-side job ownership.
- [ ] Verify stored artifact byte count and SHA-256 before serving; do not leak private Drive IDs.
- [ ] Add “Open interactive dashboard” for successful jobs and a resilient direct-link route.
- [ ] Show `processing PASS`, `visual assets PASS`, and `independent scientific validation NOT PERFORMED` as distinct states.
- [ ] Preserve current Retry task, account history, and private Drive retention behavior.
- [ ] Test authorization failures, expired/missing artifacts, API retries and older schema versions.

## Phase 4 — Scientific visualization QA
- [ ] Test expected product/observation count and pair/date sorting.
- [ ] Test cross-CRS overlays (e.g. EPSG:32645 and EPSG:32646) against source affine bounds / sample coordinates.
- [ ] Ensure no values are silently converted or labeled as cumulative, vertical, 3-D, mm/day, or hazard probability.
- [ ] Check fixed-scale animation within compatible groups and compare source values to identify readouts.
- [ ] Surface unsupported candidate screen and zero common-pixel time-series diagnostics.
- [ ] Confirm no false “stable/hazard/no hazard” inference from missing data, zero valid pixels, or NoData regions.
- [ ] Independent reviewer sign-off on the visual measurement semantics before any operational hazard-alert language.

## Phase 5 — Performance and release
- [ ] Verify dashboard generation adds no source HDF5 downloads and does not increase raw retention.
- [ ] Benchmark asset build time, bundle size, first contentful display, and playback frame consistency.
- [ ] Check reproducible manifests/checksums on a second run with the same fixture.
- [ ] Document browser requirements, external basemap dependency, and offline behavior.
- [ ] Complete code review and CI; integrate only into the approved science-integration branch, never commit directly to backend `main`.
