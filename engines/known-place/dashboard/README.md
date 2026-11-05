# SARGuardian Dashboard Workspace

This directory is the implementation home for the product-facing geospatial dashboard and presentation bundle. It is deliberately separate from the established science algorithms: display code may summarize or render science outputs, but it must not silently change masks, displacement values, acquisition selection, or scientific acceptance criteria.

## Current state

The processing run already creates a useful evidence bundle:
- per-product, AOI-clipped multi-band GeoTIFF exports;
- PNG quicklooks (currently independently stretched per image);
- `products.csv`, `aoi-run-summary.json`, and `aoi-processing-report.json`;
- per-product metadata/provenance, reader statistics, and science diagnostics;
- an offline HTML report with summary cards, filters, a metric chart, product table, and quicklooks;
- a derived-results ZIP plus verified upload receipts for private Drive storage.

The current HTML is **not yet an interactive geospatial map**. Its AOI illustration explicitly says it is a schematic, not a basemap or raster footprint. It has no map-aligned raster layer switching or date playback. The GeoTIFFs are the correct source for spatial alignment; the PNG quicklooks are visual summaries only.

## Design decisions

1. Keep scientific values and native AOI-clipped GeoTIFFs unchanged.
2. Generate small web-display assets during aggregation, after product validation and before the result ZIP / Drive upload. Do not redownload raw HDF5 just to render a dashboard.
3. Preserve product identity, reference and secondary dates, track/look geometry, maturity, CRS, nodata, band descriptions/units, valid-pixel counts, checksums, science commit, AOI hash, and known limitations in a machine-readable manifest.
4. Use a product-pair selector and observation timeline. Do **not** draw an ordinary connected displacement time-series across different reference acquisitions, tracks, look directions, or incompatible geometry. When common-reference network inversion is unavailable, present per-pair measurements separately.
5. The first web-map representation is a transparent, georeferenced PNG preview per supported raster band with explicit geographic bounds and a shared color scale within a compatible comparison group. The native GeoTIFF remains the analytical asset.
6. Use an open map renderer (MapLibre GL JS) in the web app/presentation layer, with source attribution and graceful fallback. Do not require a commercial API key solely to view exported science data.
7. COG + OGC tile service (for example TiTiler) is a scale-up path for larger rasters or many users, not a prerequisite for the current tiny AOI exports. If adopted, validate every COG and use HTTP range-aware hosting; do not label a normal GeoTIFF as COG without validation.
8. Generate STAC-compatible per-product metadata so output assets can be reused outside SARGuardian.

## Documents

- [Evidence audit](EXISTING_OUTPUT_AUDIT.md)
- [Architecture](ARCHITECTURE.md)
- [Output data contract](DATA_CONTRACT.md)
- [Implementation checklist](CHECKLIST.md)
- [References](REFERENCES.md)

## Guardrails

- A processing/structural PASS does not equal independently validated geophysical accuracy or a hazard alert.
- A pairwise LOS measurement is not automatically cumulative 3-D ground motion.
- Every displayed value has a unit, source product/pair, and provenance.
- Empty/invalid pixels stay transparent/NoData; never interpolate them into an apparent hazard.
- A color scale is documented. Do not use per-frame auto-stretch during playback without warning because it can make stable data look dynamic.
- The requested AOI and data time window always come from the exact run manifest; do not hard-code a named place.
