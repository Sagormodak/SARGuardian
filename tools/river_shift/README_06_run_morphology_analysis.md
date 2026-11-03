# 06 · River morphology change screening

## Purpose
Identify candidate persistent land-to-water transitions (erosion candidates) and water-to-land transitions (deposition candidates) using one pre-event and two post-recession GCOV observations.

## NASA challenge relevance
The script uses repeated NISAR L-band observations to visualize surface changes in a dynamic river corridor. The result supports the challenge goal of tracking and communicating Earth-surface change over time.

## Inputs
- One pre-event GCOV raster.
- Two post-recession GCOV rasters.
- Same frequency, diagonal covariance term, maturity, acquisition geometry and pixel grid.
- Observation dates and explicit gamma0 units.
- Common threshold in dB or exploratory Otsu threshold.

## Method
1. Validate all three rasters share exact CRS, dimensions and affine grid.
2. Convert positive linear gamma0 power to dB when required.
3. Apply one common low-backscatter threshold to each date.
4. Intersect the two post-event water masks to identify water that persisted in both post observations.
5. Identify erosion candidates where pre-event land became persistent post-event water.
6. Identify deposition candidates where pre-event water became persistent post-event land.
7. Calculate area and symmetric boundary-distance screening metrics.
8. Export candidate masks, GeoJSON and a provenance-rich JSON report.

Definitions:
    erosion_candidate = LAND_before AND WATER_post_one AND WATER_post_two
    deposition_candidate = WATER_before AND LAND_post_one AND LAND_post_two

## Reproduce
    python run_morphology_analysis.py --before data/processed/before.tif --post-one data/processed/post1.tif --post-two data/processed/post2.tif --before-date 2026-06-01 --post-one-date 2026-08-01 --post-two-date 2026-09-01 --threshold-db -12 --input-units linear --maturity PROVISIONAL --frequency frequencyA --term HHHH --out-dir results/morphology

Dates and threshold are examples only. Use actual data acquisition dates and validated thresholds. A five-threshold table reports deterministic method sensitivity, not statistical uncertainty. The result remains PROVISIONAL until independent review evidence is supplied.

## Outputs
- erosion_candidate_mask.tif and erosion_candidates.geojson.
- deposition_candidate_mask.tif and deposition_candidates.geojson.
- JSON metrics with areas, source metadata and warning statements.

## Metrics
- Persistent erosion candidate area (ha).
- Persistent deposition candidate area (ha).
- Net candidate land change (ha).
- Symmetric mean and 95th-percentile boundary distance (m).

## Acceptance tests
- Raster grids must match exactly.
- Two post-event water masks are required for persistence screening.
- Areas are calculated from a projected metre-based pixel area.
- Erosion and deposition candidates are disjoint directional land-cover transitions.
- The output is labelled as candidate screening, not field-confirmed erosion/deposition.
- Boundary-distance outputs are described as a symmetric proxy, not a signed bank retreat/accretion rate.

## Scientific limitations
- Seasonal water-level differences can mimic morphology change. Compare similar hydrological stages whenever possible.
- A land-to-water conversion is not proof that a flood caused erosion.
- A water-to-land conversion can be temporary exposure rather than permanent sediment deposition.
- Dredging, bank protection, sand mining, embankments, sediment supply and other processes can explain changes.
- The symmetric boundary metric does not identify signed movement direction and is not a substitute for transect-based migration rates.
- Braided rivers require separate interpretation of channel threads and the outer active-channel belt.

## AI reviewer checklist
- Verify the 2-post-observation persistence condition.
- Verify erosion and deposition equations are implemented as documented.
- Verify pixel area and projected CRS checks.
- Verify no signed migration-rate or causal claims are made from the symmetric boundary proxy.
- Verify warning messages remain in river_shift_result.json.

## Primary references
- NISAR GCOV guide: https://nisar-docs.asf.alaska.edu/gcov/
- DSAS methodology (transect-based boundary change): https://www.usgs.gov/centers/whcmsc/science/digital-shoreline-analysis-system-dsas
- Bangladesh Jamuna riverbank erosion study: https://nhess.copernicus.org/articles/23/1749/2023/
