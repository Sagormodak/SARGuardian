# Authorized generic-AOI live measurement request — 2026-10-26

**Authorization:** The user explicitly authorized `[run-know-place]` and allowed the required data downloads for real measurement.

**Purpose:** Validate the production generic arbitrary-AOI workflow end-to-end through measurement, GIS output, offline dashboard, interactive Leaflet map and verified derived-only Drive retention. This is deliberately separate from the five-pair author-exact benchmark run.

**Request values**
- AOI WGS84 WKT: `POLYGON ((85.5245 28.2847, 85.5400 28.2847, 85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))`
- Stable reference polygon: `POLYGON ((85.500000 28.265000, 85.565000 28.265000, 85.565000 28.318000, 85.500000 28.318000, 85.500000 28.265000))`
- Inclusive UTC dates: 2026-06-20 through 2026-08-31
- Exact release allowlist: `P05023` only
- Polarization/track/direction: HH / 098 / ascending
- Geometry height: 5151 m, exploratory constant, not a DEM or vertical-datum correction
- Coherence minimum-neighbour setting: 1, with the runner's sensitivity table retained
- Profile: exploratory measurement, hazard metadata `ice_rock_avalanche`

**Safety and completion gates:** The generic workflow must verify exact CMR granule identity, source sizes and SHA-256 per download; keep track/release/maturity/polarization chains separate; compute only when source grids and quality gates pass; emit `visuals/dashboard.html` and `visuals/interactive-map.html`; remotely verify the derived-only Drive bundle; do not upload raw HDF5; delete each temporary raw source only after its per-product processing/retention semantics complete; preserve receipts and the request hash.

**Claims boundary:** A real arbitrary-AOI measurement and an interactive map are not, by themselves, a validated landslide/glacier-collapse detector. Keep `HAZARD_DETECTION_STATUS=NOT_EVALUATED` unless independent labelled-event validation passes.

This request belongs only on `feat/know-place-analysis`. Do not edit or merge to `main`.
