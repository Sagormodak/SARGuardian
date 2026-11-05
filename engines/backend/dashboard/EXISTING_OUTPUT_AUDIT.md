# Existing Processing Output Audit

Audit source: real run [40308665800](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40308665800), dashboard artifact `sarguardian-aoi-dashboard-40308665800-1`, downloaded and inspected on 2026-10-26.

## What is already generated

| Output | Present? | Current use / finding |
|---|---:|---|
| Selected-product manifest | Yes | Exact AOI/date/catalog selection and provenance |
| Per-product clipped raster | Yes | Small multi-band GeoTIFF; valid spatial source |
| Band 1 | Yes for inspected GUNW | `LOS displacement (mm)` |
| Band 2 | Yes for inspected GUNW | `coherence` |
| Georeferencing | Yes | EPSG code, affine transform, bounds, and NoData are present |
| Per-product PNG quicklooks | Yes | Useful preview, but each image is stretched independently at symmetric 98th percentile |
| Product table CSV | Yes | Product/pair, maturity, valid pixels, median, hashes, source sizes |
| Run summary and processing report | Yes | AOI hash, run/revision provenance, validation scope, warnings |
| Pixel-stack diagnostic | Yes | Script completed, but complete common-pixel series were zero for every listed chain |
| Candidate screening for arbitrary AOI | No | Explicitly skipped as unsupported; existing candidate checker assumes named AOIs |
| Existing HTML report | Yes | Summary, table filters, quicklooks, metric chart, caveats |
| True map-aligned raster overlay | No | Current AOI drawing is schematic, not a geospatial map |
| Map layer toggles / raster click identify | No | Not generated in current report |
| Observation playback / date slider | No | No real playback control; existing chart is pairwise metric grouping only |
| Formal STAC catalog / items | No | Not generated |
| Web-ready raster tiles/COGs | No | TIFF exports must not be called COG without validation |
| Authenticated in-app science dashboard | No | Current account UI links to private Drive downloads |

## Run-specific evidence

- Workflow conclusion: `success`. One initial product download job failed, then its retry succeeded; aggregation and terminal validation both succeeded.
- Products structurally validated: 10 / 10; GUNW = 10; GOFF = 0.
- AOI is a custom polygon near longitude 90.4 E / latitude 24.7 N (Bangladesh), not the Bhote Koshi / Nepal validation AOI. This run must not be cited as Nepal reproduction evidence.
- The exported TIFF inspected for GUNW-003 is 77 × 75 pixels, 2 bands, 80 m posting, band descriptions `LOS displacement (mm)` and `coherence`, with 42 valid pixels. The product record reports a median of -131.277 mm and mean coherence ~0.407 for this pair; this is a per-product reader summary, not a cross-pair displacement trend.
- Products are not all in the same projected CRS: inspected outputs include EPSG:32645 and EPSG:32646. Every overlay must respect each source raster's CRS/transform and reproject explicitly; do not reuse one product's bounds for another.
- The stack log identifies chains A069 (3 pairs), D019 (4), and D091 (3), with **0 complete-series pixels** in each chain. It says no fit was made. Therefore timeline playback can show individual observations, but it must not draw or label a fitted displacement trend from these outputs.
- Candidate check status is `SKIPPED_UNSUPPORTED_CUSTOM_AOI`; this is a limitation, not a negative finding.

## Consequence

The pipeline already generates most numerical and provenance inputs for a good dashboard. The missing work is the **web-facing spatial representation and interactive presentation contract**, plus explicit checks ensuring the new display assets stay aligned with source data. Add light preview assets during aggregation; retain the native TIFF and reports as source evidence. Do not add more raw processing merely to create decorative charts.


## Follow-up validation on the same real artifact

On 2026-10-26, the branch's real-artifact smoke test downloaded the existing artifact for run [40308665800](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40308665800) and ran the new display builder over its 10 clipped GeoTIFFs, without replaying NISAR/raw-HDF5 processing. It produced 10 observation records and 20 transparent raster layers; all source TIFF hashes remained unchanged. The rebuilt test fixture ZIP contained the viewer, data JS, manifest, AOI GeoJSON, timeline, metrics and STAC catalog. The smoke run is [here](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40340177367).

This is compatibility evidence for the builder against the real output schema; it is **not** a retroactive modification of run 40308665800's stored ZIP and does not mean the live app is already enabled. Only a future run executed through the reviewed processing integration will naturally produce the dashboard-ready result bundle.
