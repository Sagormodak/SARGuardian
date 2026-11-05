# Implementation Checklist — Interactive Science Dashboard

Statuses: `DONE`, `IN_PROGRESS`, `BLOCKED`, `NOT_STARTED`. A checklist item moves to DONE only with code/test/evidence links.

## Phase 0 — Evidence and architecture
- [x] Run the builder against existing successful real-run artifact 40308665800 without replaying source-data downloads; verified 10 observations, 20 layers and unchanged source TIFF hashes. See [latest smoke run](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40350497667). The historical original ZIP remains unchanged; the smoke test created a separate refreshed fixture bundle.
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
- [x] Add unit tests for cross-UTM reprojection, NoData transparency, STAC paths, common scale within the same track group and source TIFF immutability.
- [ ] Extend tests for missing band descriptions, all-empty bands, multi-export products and deterministic rebuilds.
- [x] Wire builder into AOI aggregation before ZIP creation and Drive upload. The new visualization build is best-effort and reports its own status so a render issue cannot mark scientific processing as failed.
- [x] Add a machine-readable per-run science-stage report and embed it in the result manifest; use the pinned `timeseries.py` engine for acquisition-network topology, and visibly gate inversion/floor/velocity/geometry/bound stages when required evidence is absent.
- [ ] Add generated file list and explicit status to the GitHub workflow step summary; review the private Drive package inventory and preserve the three required account artifacts.
- [ ] Run the exact committed builder against the downloaded run artifact and compare all source TIFF hashes before/after.

## Phase 2 — Interactive offline/presentation viewer
- [x] Add map panel showing the true AOI polygon and georeferenced raster preview layers, never a schematic pretending to be the map.
- [x] Add product/band selector, opacity slider, legend with units/scale, product details and pixel count.
- [x] Add acquisition-pair timeline, Play/Pause, previous/next, playback speed and date labels.
- [ ] Group observations by track/view geometry; do not interpolate missing acquisitions or join incompatible pairwise measurements as a trend.
- [x] Add pairwise LOS median chart filtered to one track, valid-pixel support chart, provenance card and always-visible science limitation banner.
- [x] Add a unit-separated metric selector for GUNW LOS median, GOFF range-offset median, GOFF along-track-offset median and GOFF detection floor; the floor is explicitly labelled as detectability, not measured motion.
- [ ] Add native GeoTIFF/quicklook export actions inside the static viewer itself; the original bundle currently retains those assets.
- [x] Add graceful map-library/basemap fallback messaging and explicit OpenStreetMap attribution; note that actual basemap rendering requires network access.
- [x] Add keyboard-operable native controls, responsive mobile layout and full-screen presentation toggle.
- [x] Pin MapLibre GL JS 6.16.0 using its v6 ESM entry point; test the imported module guard and syntax-check the module with Node in CI.\n- [ ] Add explicit reduced-motion behavior and independent browser/contrast/accessibility audit. A full real-browser visual test remains pending; the CI smoke test verifies generated artifacts, JS syntax and bundle contract.

## Phase 3 — Authenticated Dynamic app integration
- [x] Define owner-scoped, read-only dashboard HTML endpoint in Dynamic PR [#6](https://github.com/moshiour0/SARGuardian_Dynamic/pull/6).
- [x] Enforce Firebase bearer authentication and server-side job ownership in Dynamic PR #6.
- [x] Verify stored artifact byte count/SHA-256 before serving; do not leak private Drive IDs.
- [x] Add the “Open interactive dashboard” action for successful jobs with a PASS dashboard receipt in Dynamic PR #6. The action is intentionally hidden for old jobs.
- [x] Keep processing status and visual asset status separate in the bundle; expose web dashboard status to the account UI. The viewer visibly states that independent geophysical validation was not performed.
- [x] Preserve existing Retry task, account history and private Drive retention code paths.
- [x] Test authorization failure, old bundles without dashboard assets, checksum mismatch, and duplicate manifest compatibility.
- [ ] Add expiry and transient-storage retry tests for the dashboard endpoint.

## Phase 4 — Scientific visualization QA
- [ ] Test expected product/observation count and pair/date sorting.
- [ ] Test cross-CRS overlays (e.g. EPSG:32645 and EPSG:32646) against source affine bounds / sample coordinates.
- [ ] Ensure no values are silently converted or labeled as cumulative, vertical, 3-D, mm/day, or hazard probability.
- [ ] Check fixed-scale animation within compatible groups and compare source values to identify readouts.
- [ ] Surface unsupported candidate screen and zero common-pixel time-series diagnostics.
- [ ] Confirm no false “stable/hazard/no hazard” inference from missing data, zero valid pixels, or NoData regions.
- [ ] Independent reviewer sign-off on the visual measurement semantics before any operational hazard-alert language.

## Phase 5 — Performance and release
- [x] Builder consumes only already validated AOI-clipped GeoTIFFs and metadata; no raw HDF5 re-download or retention-profile change is introduced.
- [ ] Benchmark asset build time, bundle size, first contentful display, and playback frame consistency.
- [ ] Check reproducible manifests/checksums on a second run with the same fixture.
- [x] Document MapLibre/OpenStreetMap network dependency, offline fallback, native TIFF and bundle behavior.
- [x] Dashboard builder tests and backend regression CI pass on the feature branch.
- [ ] Complete review and integration. PR #44 targets `main` for review only; no merge or direct main commit has been made; it does not change backend `main`. Dynamic app PR #6 is separate and remains unmerged.
- [ ] Merge the reviewed dashboard integration PR only after CI review. The dynamic workflow currently pins an older dashboard builder, which omits the `web-dashboard/` assets; PR #47 updates that immutable pin and adds a guard test.
- [ ] After the pin fix is merged, run a dashboard-only smoke test against retained derived outputs (no raw replay), verify `web_dashboard.status == PASS`, and confirm the authenticated in-app route can open the exact result bundle before calling the integration production-ready.
- [ ] Separately implement and validate common-reference provenance and target-point contracts before enabling numeric cumulative inversion, local target floors, inverse-velocity, or ASC/DESC fusion for arbitrary AOIs.
