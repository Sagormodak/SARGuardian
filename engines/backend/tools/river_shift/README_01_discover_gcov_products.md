# 01 · Discover NISAR GCOV products

## Purpose
Find real NISAR Level-2 GCOV granules intersecting a single WGS84 study polygon and an acquisition-date interval. Search NASA CMR by the official NISAR GCOV collection short name and read UMM-G 1.6.7 metadata. This is catalogue discovery only; it does not download imagery, run science processing, or claim a flood result.

## NASA challenge relevance
This is the data-acquisition gate for the NASA Space Apps 2026 challenge “Dancing with the SARs”. The output records NASA-ISRO NISAR product identifiers, CMR granule concept IDs, and ASF DAAC data links so the later analysis can show that NISAR is the primary data source.

## Scientific question
Does the selected AOI have enough compatible NISAR GCOV acquisitions to support a multi-date backscatter change analysis?

## Official collection short names
- PROVISIONAL: `NISAR_L2_GCOV_PROVISIONAL_V1`
- BETA: `NISAR_L2_GCOV_BETA_V1`

These are queried separately. `ALL` performs two collection searches and does not imply that the two maturities can be mixed into one analysis.

## Inputs
- One valid, non-empty Polygon WKT in EPSG:4326, coordinates ordered longitude then latitude.
- Inclusive acquisition start and end dates.
- Maturity filter: PROVISIONAL, BETA, or ALL (ALL is for auditing; do not mix maturities in one time series).
- Optional Frequency-A main-band polarization and orbit direction.
- NISAR frame-coverage filter: ALL, FULL or PARTIAL (default ALL for initial discovery).
- Maximum results from 1 to 2000.

`FULL` or `PARTIAL` describes the NISAR frame product. It is not the percentage of the user-defined AOI covered by a scene. See README_09 for per-date footprint coverage.
- Optional NISAR frame-coverage filter (ALL, FULL, PARTIAL; default ALL for discovery).

Important: FULL/PARTIAL is a product-frame metadata field. It does not say how much of the user-drawn AOI is covered; README_09 calculates that percentage from actual footprints.

## Method
1. Validate the WGS84 polygon and date order.
2. Query NASA CMR granules by the exact collection `short_name`, a closed counter-clockwise AOI polygon, and the requested temporal interval. Request UMM-G 1.6.7.
3. Parse the official 18-token single-acquisition GCOV granule name, including orbit, frame, bandwidth mode, polarization, timestamps, CRID and FULL/PARTIAL frame coverage; keep ASF-supplied footprint geometry for the separate AOI-coverage audit.
4. Assign maturity from the collection short name used in the query. A CRID token alone is never used to guess BETA/PROVISIONAL maturity.
5. Write the unmodified catalogue identifiers into a JSON manifest.

## Reproduce
Run from tools/river_shift:

    python -m pip install -r requirements.txt
    python discover_gcov_products.py --aoi-wkt "YOUR_DRAWN_WGS84_POLYGON_WKT" --start-date YYYY-MM-DD --end-date YYYY-MM-DD --maturity PROVISIONAL --frame-coverage ALL --out data-audit/gcov-catalogue-manifest.json

Use the polygon drawn or entered for the study and the date interval selected for that run. No Bangladesh AOI is built into the processing request. NISAR coverage and comparable acquisition availability still vary by location and time.

## Outputs
- JSON manifest containing the query and each matching GCOV granule.
- Product count and non-fabricated warning messages.
- Maturity, acquisition time, relative orbit, direction, frame, mode and polarization when present.

## Acceptance tests
- Invalid geometry and reversed dates fail before network access.
- PROVISIONAL and BETA map to their exact CMR collection short names.
- CMR UMM-G 1.6.7 is parsed and granule IDs, geometry, dates, CMR concept ID and GET DATA links are preserved.
- CMR pagination continues when local polarization/direction/frame filters reduce a page.
- Product-level filter excludes non-GCOV results.
- The NASA CMR request uses a documented collection `short_name`, polygon and temporal range with UMM-G 1.6.7.
- The official 18-token GCOV filename is parsed; malformed names are rejected.
- Frame coverage ALL/FULL/PARTIAL is preserved separately from AOI footprint percentage.
- Unknown maturity remains UNKNOWN and is not inferred from CRID.
- Official 18-token NISAR L2 GCOV product names are parsed, while malformed/pair-product names are rejected.
- ASF request uses the documented `output=json` format.
- FULL/PARTIAL frame coverage remains distinct from the user-defined AOI coverage percentage.
- BETA and PROVISIONAL products remain separated.
- The reported count equals the number of manifest products.
- No-data and result-cap warnings are preserved.
- Every returned granule name and URL originates from ASF response data.

## Scientific limitations
- Catalogue intersection means the product footprint intersects the AOI; it does not guarantee full AOI coverage.
- The presence of multiple products does not prove that they share the same observation geometry, pixel grid, polarization or maturity.
- A catalogue hit is not an analysis result.
- ASF may report missing metadata; missing fields remain unknown rather than being inferred.

## AI reviewer checklist
- Confirm the endpoint is ASF DAAC and the dataset is NISAR.
- Confirm processingLevel is GCOV.
- Confirm maturity comes from the official collection URL/metadata or is marked UNKNOWN.
- Confirm acquisition date, orbit/track, processing type, CRID and frame coverage are retained.
- Confirm all acquisition IDs/dates are retained.
- Confirm the README command is reproducible and placeholders are labelled.
- Confirm no flood/erosion metric is claimed by this script.

## Primary references
- NISAR GCOV collection short names and `earthaccess.search_data`: https://nisar-docs.asf.alaska.edu/earthaccess/
- NASA CMR granule search and polygon/temporal parameters: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html
- NISAR GCOV product guide: https://nisar-docs.asf.alaska.edu/gcov/
- NASA NISAR data: https://science.nasa.gov/mission/nisar/data/
