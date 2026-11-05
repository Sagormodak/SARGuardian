# References and Rationale

Official/normative references checked on 2026-10-26.

1. **OGC Cloud Optimized GeoTIFF (COG)** — https://www.ogc.org/standards/ogc-cloud-optimized-geotiff/  
   COG relies on tiled GeoTIFF layout, reduced-resolution subfiles/overviews, georeference metadata, and HTTP Range requests. A normal GeoTIFF must not be called a COG unless it meets the COG requirements and is validated.

2. **Rasterio reprojection** — https://rasterio.readthedocs.io/en/stable/topics/reproject.html  
   Use an explicit source/destination CRS, transforms and resampling strategy. The dashboard's overlay bounds must come from the raster transform rather than be guessed from AOI coordinates.

3. **OGC SpatioTemporal Asset Catalog (STAC)** — https://www.ogc.org/standards/stac/ and https://docs.ogc.org/cs/25-004/25-004.html  
   STAC items describe spatiotemporal Earth assets as GeoJSON features with datetime and asset links. Use this to make each product pair discoverable with provenance without inventing a joined time series.

4. **MapLibre GL JS raster tile source** — https://maplibre.org/maplibre-gl-js/docs/examples/add-a-raster-tile-source/  
   MapLibre supports raster sources and is a suitable open-source map renderer. Map style / tile provider attribution and usage policies remain necessary.

5. **TiTiler raster/COG support** — https://docs.eodatahub.org.uk/Analysts/visualisation/introduction/ and API reference https://titiler.nlr.gov/api.html  
   TiTiler serves web tiles from COG/STAC and avoids downloading an entire raster for every view. This is a scale-up option rather than mandatory infrastructure for current small 77 × 75 raster exports.

6. **NISAR GOFF product guide** — https://nisar-docs.asf.alaska.edu/goff/  
   GOFF is a geocoded pixel-offset product; layers are distributed without conventional post-processing, so outliers and unfiltered noise may be present. UI must not label raw offset layers as a validated displacement field or hazard detector.

7. **NASA NISAR data overview** — https://science.nasa.gov/mission/nisar/data/  
   Provides NISAR product guides and data-product context. Use product documentation to retain the correct measurement interpretation and limitations.

## Chosen approach

For current outputs: native AOI-clipped GeoTIFF + transparent reprojected preview PNG + GeoJSON AOI + versioned manifest/STAC metadata + pair-aware timeline and dashboard. For larger or multi-user raster hosting: validated COGs + HTTP Range hosting + TiTiler/OGC tile endpoints. Do not add the tile server yet just to display a 77 × 75 raster.
