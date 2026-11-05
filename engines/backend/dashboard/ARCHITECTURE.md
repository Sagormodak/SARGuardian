# SARGuardian Interactive Science Dashboard — Architecture

## Goals

Present AOI-scoped NISAR outputs as a fast, reproducible and reviewable scientific interface:
- an interactive map with georeferenced product overlays and AOI boundary;
- a pair-aware observation timeline with Play/Pause and previous/next controls;
- scientific metrics, data-quality/provenance tables, and downloadable evidence;
- full-screen presentation mode that visibly retains caveats and source attribution;
- an offline/downloadable report and an authenticated account dashboard.

This is a visualization layer over the scientific pipeline, not a separate detector.

## Chosen architecture

### A. Processing-time outputs (no second raw-data replay)

Extend the existing aggregation step after each product export and report has passed its current checks. Re-use those outputs to produce:

```text
dashboard/
  README.md
  ARCHITECTURE.md
  CHECKLIST.md
  DATA_CONTRACT.md
  EXISTING_OUTPUT_AUDIT.md
  REFERENCES.md
  tests/
  assets/
    prepare_web_assets.py
    schema/
  # generated per run, inside the downloaded result bundle:
  web-dashboard/
    index.html
    manifest.json
    aoi.geojson
    timeline.json
    metrics.json
    stac/
      catalog.json
      collection.json
      items/<product-id>.json
    layers/
      <product-id>-band-<n>.png
```

The generated layer PNGs are display previews in EPSG:4326 with transparent NoData. Their geographic corner coordinates, source CRS/transform, band description, unit, color limits, selected acquisition pair, and source hashes are stored beside them. The original clipped GeoTIFFs remain the authoritative spatial assets and are included unchanged in the data package.

### B. Browser map and timeline

- Map renderer: MapLibre GL JS (open-source, WebGL-capable); OSM-compatible basemap only with visible attribution and responsible tile usage. The static downloadable viewer should degrade gracefully if the network/basemap is unavailable.
- Add the requested WKT polygon as GeoJSON, fitted to its own bounds. Product raster preview is an image source with the exact geographic coordinates produced by the reprojecting step; never assume all source TIFFs share a CRS.
- Layer controls: LOS displacement, coherence, and any explicitly supported GOFF layer, with opacity and legend. GOFF offsets are noisy/unfiltered in the source product and must be described accordingly.
- Timeline selector: one selectable product per real acquisition pair, labeled reference → secondary date, track/look geometry, maturity, valid pixels, and processing ID.
- Playback switches among observations at a deliberate pace. It is **not** interpolation, a forecast, or evidence that a connected sequence is a common-reference time series.
- When products from distinct tracks/look directions are displayed, mark comparison as geometry-dependent and prevent misleading combined line plots.
- Raster pixel inspection can show values only when a reliable map-to-pixel transform is available; show the exact product, band and units in the identify panel.

### C. Scientific dashboard and graphs

Show:
- pipeline status versus scientific-accuracy validation status as distinct statuses;
- GUNW/GOFF counts, validated/missing products, valid pixels, AOI support, maturity, and coverage;
- per-product distributions (median, quantiles, coherence/support) with units and sample count;
- the current product's raster preview and metadata;
- pairwise metric charts grouped by measurement, unit, track and viewing geometry;
- completeness diagnostics (e.g., common pixel series count) and explicit skipped analyses.
Only call a graph a time series when the observations are demonstrably comparable and support a common-reference solution. A “PASS” in structural/provenance validation is not a hazard label.

### D. Authenticated in-app results

The SARGuardian Dynamic account page should add an “Open interactive dashboard” action for successful jobs. The browser must obtain dashboard metadata/assets through an authenticated, owner-scoped API or a verified bundle download. Never expose raw private Drive IDs as unauthenticated data endpoints; the server must verify owner, expected artifact inventory, byte count and SHA-256 before serving assets. Keep Drive upload and current result bundle retention intact.

Preferred integration sequence:
1. Enhance the processing bundle and static viewer first; this needs no new raw replay and preserves evidence offline.
2. Add a narrow authenticated API contract in Dynamic to read the verified dashboard bundle, not a duplicate science computation.
3. Add an in-app dashboard route and reuse the same manifest/renderer.
4. Only then consider COG/tile hosting if real raster size/traffic justifies it.

### E. Storage format and scale choice

Current raster exports are roughly 77 × 75 pixels and each contains two bands; a heavy raster-tile service is disproportionate for this preview stage. Keep native GeoTIFF + transparent web preview PNG + manifest. Build and validate COG assets only if future export sizes, multi-resolution access or concurrent traffic require it. If so, use standards-compliant COG creation and validation, immutable versioned assets, HTTP Range support and a tile service such as TiTiler; do not assume any GeoTIFF is a COG.

STAC Item/Collection metadata is the recommended catalog contract. It makes per-product assets and acquisition times discoverable without changing the data itself.

## Trust boundaries and acceptance invariants

1. **Source preservation:** map preparation reads only processed, AOI-clipped exports. It never mutates or rewrites the original TIFF.
2. **Geolocation:** a layer's preview bounds come from the source raster's CRS and affine transform through an explicit reprojection. Verify corners fall near the requested AOI, not merely in a numerical range.
3. **NoData:** transparent in rendered PNGs; never render NaN/NoData as a strong displacement color.
4. **Units:** preserve band descriptions and units. For the current GUNW export the first band is LOS displacement in millimetres and second band coherence; do not relabel as 3-D movement or speed.
5. **Comparability:** no line joining across distinct pair geometries unless a tested common-reference/network inversion says the values are comparable. Preserve gaps.
6. **Display scaling:** use one color scale per compatible geometry/track/band group for playback and document any clipping; no per-frame auto-stretch that visually exaggerates change.
7. **Validation distinction:** structural validation, visual asset validation and independent geophysical validation are separate fields.
8. **Provenance:** every run manifest records AOI WKT hash, actual science and orchestration commit SHAs, source-product SHA-256, processing dates, CRS and output checksums.
9. **Security:** user account access controls stay in force; a job ID alone is not authorization.
10. **Accessibility/presentation:** keyboard-operable controls, visible legend/units, readable mobile layout, screen-reader labels, and caveats visible in full-screen mode.

## Definition of done

A clean run creates the current bundle plus schema-valid web assets; an independent test opens the generated viewer and checks the expected products, accurate bounds, map layer toggles, real date labels, non-misleading graphs, and provenance/limitation panels. The dashboard renders the current run without any new raw data downloads.
