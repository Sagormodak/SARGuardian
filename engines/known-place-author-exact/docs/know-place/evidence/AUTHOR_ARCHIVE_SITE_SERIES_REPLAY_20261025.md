# Independent replay of the archived author site-series metrics — 2026-10-25

## Result

**PASS: 25/25 site-series comparisons matched at the published Table S4 precision, with zero mismatches.**

This is an independent, offline calculation from the five exported processed-field GeoTIFFs in the supplied Zenodo archive. It recomputes the displacement median and rate, crown-cropped P1 directional coherence, and whole-WIDE-field P1 background coherence from bands 1 and 2 (east/north displacement), then compares the outputs to `tables/nisar_pot_series.json` and `tables/TableS4_site_series.json`.

- Archive: `bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip`
- Archive SHA-256: `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`
- Processed inputs: `fields/offsets_20260620_20260702.tif`, `fields/offsets_20260702_20260714.tif`, `fields/offsets_20260714_20260726.tif`, `fields/offsets_20260726_20260819.tif`, `fields/offsets_20260819_20260831.tif`
- Reference outputs: `tables/nisar_pot_series.json` and `tables/TableS4_site_series.json`
- No raw NISAR payloads were downloaded or used in this check.

## Method

The computation follows the supplied `code/make_pot_figure.py` and `code/make_fig_timeseries.py` site-series formulas:

1. Read east and north displacement bands from each archived field TIFF; cells lacking finite east/north values are treated as invalid.
2. Derive the crown crop from the raster extent, its array dimensions, and the author AOI bounds `(85.5245, 28.2847, 85.5400, 28.2970)`, using the same linear lon/lat axes and `searchsorted` convention as the source.
3. Compute median horizontal displacement over finite crown cells, divide by exact pair duration, and convert to cm/day.
4. Compute directional coherence from unit displacement vectors with a 5 × 5 uniform filter, reflected edges, finite-support fraction strictly greater than 0.5, and the source's (10^{-9}) magnitude floor. Crown P1 coherence is computed on the crown-cropped array; scene/background P1 coherence is computed separately on the full field. The different cropped versus full-field window context is intentional and must not be conflated with the polygon-null estimator.
5. Compare counts exactly; compare displacement to 2 decimal places, rate to 1 decimal place, and each P1 R metric to 3 decimal places, matching the archive's published precision.

## Pair-level results

| Pair | Valid crown cells | Median displacement (m) | Rate (cm/day) | P1 crown R | P1 scene R | Checks |
|---|---:|---:|---:|---:|---:|---:|
| 20 Jun–2 Jul 2026 | 283 | 0.994960 | 8.291333 | 0.750095 | 0.641110 | 5/5 |
| 2–14 Jul 2026 | 294 | 0.539071 | 4.492261 | 0.611518 | 0.718879 | 5/5 |
| 14–26 Jul 2026 | 296 | 0.295551 | 2.462925 | 0.610544 | 0.756955 | 5/5 |
| 26 Jul–19 Aug 2026 | 292 | 0.964510 | 4.018793 | 0.871067 | 0.686507 | 5/5 |
| 19–31 Aug 2026 | 195 | 0.327832 | 2.731931 | 0.551478 | 0.592465 | 5/5 |

Comparison totals: **25 passed, 0 failed**.

## Interpretation limits

- This verifies the post-processing formulas and the archived summary values from the supplied *cropped processed fields*. It does not prove raw-GOFF-to-field pixelwise parity.
- The five TIFFs are 80 × 73 EPSG:4326 processed windows, not the full 4,230 × 4,311 original GOFF grid.
- The polygon-null outputs are a distinct coherence estimand: full-WIDE-field R is computed first and then sampled within the crown mask. That separate replay is recorded in `AUTHOR_ARCHIVE_POLYGON_NULL_REPLAY_20261025.md` (45/45 matches). P1 crown R and polygon-null crown R intentionally differ because their 5 × 5 windows are constructed on different array extents.
- The new raw author-site-series workflow must still reproduce these values directly from the five exact P05023 GOFF files. Until that consented run passes the 65 comparisons, the source-level replay remains unverified.
- The full-footprint screening raster pipeline, original-source-grid pixelwise parity, vertical-datum sensitivity, and hazard-detection skill are not validated by this check. Hazard detection remains `NOT_EVALUATED`.

Source attribution: Sansar Raj Meena (2026), Zenodo dataset, DOI `10.5281/zenodo.22730419`, CC BY 4.0.
