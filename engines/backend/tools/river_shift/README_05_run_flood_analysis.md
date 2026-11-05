# 05 · Flood inundation screening

## Purpose
Compare co-registered pre-event, flood-period and post-event GCOV backscatter rasters to create open-water candidate masks and measure new water coverage relative to the pre-event observation.

## NASA challenge relevance
This is the main NISAR surface-change use case in RiverShift. NISAR GCOV supplies calibrated gamma0 power layers; the script evaluates a selected same-frequency, same-diagonal-polarization time series.

## Inputs
- Before-event, during-event and after-event GCOV COG rasters.
- Exact observation dates.
- Declared input units: linear gamma0 power or dB.
- One fixed dB threshold selected from a documented validation experiment, or exploratory combined Otsu threshold.
- Optional aligned permanent-water mask.
- One consistent maturity, frequency and covariance term.

## Method
1. Read all raster values and NoData masks.
2. Require exact CRS, dimensions and affine transform equality.
3. Require a projected CRS with metre units for area computation.
4. Convert positive linear gamma0 power to dB using 10 log10(power). If inputs are already dB, do not convert again.
5. Classify low-backscatter open-water candidates using the common threshold.
6. Compare during-event water against before-event water.
7. Optionally exclude a supplied aligned permanent-water mask.
8. Calculate pixel-area sums and polygonize new-water coverage to GeoJSON.

New water coverage is defined as:
    new_water = water_during AND NOT water_before

The reported area is new water coverage relative to the before-event image. It is not automatically a verified floodplain inundation area.

## Reproduce
    python run_flood_analysis.py --before data/processed/before.tif --during data/processed/during.tif --after data/processed/after.tif --before-date 2026-06-01 --during-date 2026-07-01 --after-date 2026-08-01 --threshold-db -12 --input-units linear --maturity PROVISIONAL --frequency frequencyA --term HHHH --out-dir results/flood

The threshold and dates are examples. Determine a site-specific threshold using independent reference observations; do not adopt -12 dB as universal. The result includes a five-threshold sensitivity table. This is a deterministic robustness check, not a confidence interval. The release status remains PROVISIONAL until review evidence is supplied.

## Outputs
- Before/during/after water masks.
- New-water coverage raster and GeoJSON polygons.
- river_shift_result.json with NISAR provenance, dates, method, metrics, QA status and warnings.

## Metrics
- Baseline water area (km2).
- Peak water area (km2).
- Post-event water area (km2).
- New water coverage relative to pre-event (km2).
- Water-area change percentage.

## Acceptance tests
- Different CRS, affine grids or dimensions fail closed.
- Non-projected or non-metre-area CRS is rejected.
- Linear power and dB input contracts are explicit.
- NoData is excluded from the comparison.
- New-water raster is calculated from the during and before masks.
- Output values are finite JSON numbers or null.
- Result status explicitly says screening is not independently validated.

## Scientific limitations
- Low-backscatter screening can miss flooded vegetation because double-bounce scattering may be bright.
- Smooth bare soil, radar shadow and other low-return surfaces can be false positives.
- Water levels and acquisition timing matter; dates must be tied to an actual hydrological event.
- Median composites can hide flood peaks; choose the actual acquisition nearest the event peak.
- Permanent-water exclusion is only as good as the supplied reference mask.
- This module does not estimate water depth or prove flood causality.

## AI reviewer checklist
- Verify NISAR GCOV is the declared primary input.
- Verify linear-power conversion is 10 log10, not 20 log10.
- Verify pixel-wise comparison requires exactly matching grids.
- Verify newly inundated area is not labelled as flood depth or proven flood damage.
- Verify date, maturity, frequency, covariance term and threshold are recorded.
- Verify QA warnings are displayed with every result.

## Primary references
- NISAR GCOV guide: https://nisar-docs.asf.alaska.edu/gcov/
- NASA NISAR data: https://science.nasa.gov/mission/nisar/data/
- NISAR data maturity: https://nisar-docs.asf.alaska.edu/availability-overview/
