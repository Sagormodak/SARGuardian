# Author processed-field / archived-table parity — 2026-10-24

**Repository:** `moshiour0/SARGuardian-backend`  
**Branch:** `feat/know-place-analysis`  
**Input archive:** `bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip`  
**Archive SHA-256:** `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`  
**Scope status:** `PASS_EXPORTED_FIELDS_MATCH_ARCHIVED_TABLES`  
**Raw-source reproduction status:** `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`  
**Hazard-detection status:** `NOT_EVALUATED`

## Purpose and limits

This check independently recomputes metrics from the five exported site-field GeoTIFFs in the CC BY 4.0 archive and compares them with the archived author tables. All calculations use the author-compatible functions now available in `tools/know_place/author_parity.py`; the repeatable archive verifier is `tools/know_place/verify_author_fields.py`.

This is a processed-field consistency check, **not** a raw GOFF replay, a pixelwise comparison to the original source grid, a full-footprint reproduction, or detection validation. The ZIP contains neither the five raw GOFF HDF5 inputs nor the five full-footprint per-pair offset rasters. Extents for the crown crop come from the exported GeoTIFF bounds used as endpoint coordinates by the author crop function; this does not establish the original source-grid sample axes or mask.

## Exact estimands kept separate

- **Displacement-valid crown cells**: finite exported (dE,dN) cells in the author crown crop. Compared to `tables/nisar_pot_series.json` key `n`.
- **P1 R-valid cells**: finite coherence values after cropping the field to the crown and then computing author coherence; the P1 estimator therefore reflects at the crop boundary.
- **Polygon-null R-valid crown cells**: finite values of the full-field coherence map within the crop. Compared to `tables/polygon_null.json` key `n_px`. This uses a different boundary estimand from P1.
- **Displacement-null**: the archived output `tables/displacement_null.json` is cross-checked against corresponding Table S4 fields. A standalone generator script is absent, so this report does not claim to regenerate that null distribution.

The earlier “296 versus 298” discrepancy was an invalid cross-estimand comparison. These are separate displacement and coherence support counts, not contradictory counts.

## Per-pair recomputation

| Pair | Displacement crown cells `n` | Median displacement (m) | Rate (cm/day) | P1 crown R | P1 background R | P1 R-valid crown cells | Polygon-null R-valid cells `n_px` | Polygon-null crown R / box R | Crown percentile | Accepted draws |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 Jun–2 Jul | 283 | 0.994960 | 8.29133 | 0.750095 | 0.641110 | 308 | 302 | 0.738532 / 0.641110 | 77.2462 | 857 |
| 2–14 Jul | 294 | 0.539071 | 4.49226 | 0.611518 | 0.718879 | 304 | 299 | 0.583001 / 0.718879 | 23.3371 | 887 |
| 14–26 Jul | 296 | 0.295551 | 2.46292 | 0.610544 | 0.756955 | 306 | 302 | 0.593569 / 0.756955 | 39.7826 | 920 |
| 26 Jul–19 Aug | 292 | 0.964510 | 4.01879 | 0.871067 | 0.686507 | 300 | 298 | 0.847894 / 0.686507 | 85.1528 | 916 |
| 19–31 Aug | 195 | 0.327832 | 2.73193 | 0.551478 | 0.592465 | 199 | 202 | 0.511221 / 0.592465 | 29.1165 | 996 |

All five displacement counts agree with `nisar_pot_series.json:n`. All five polygon-null R counts agree with `polygon_null.json:n_px`. P1 crown R-valid counts are listed separately because the crop-edge policy differs.

## Null-distribution and cross-table checks

The polygon-null calculation used one shared `numpy.default_rng(20260907)` sequence across the five pairs; 1,200 unique candidate centres were examined per pair. The accepted draw counts exactly match the archived table. The R-valid mask recomputed from each exported (dE,dN) pair matches the stored band-3 finite mask in all five fields; maximum absolute error was `3.4930149217515805e-8`, below the `1e-6` tolerance.

The comparison checked:
- 5 per-pair `nisar_pot_series` values (count, median displacement, interval-average rate, P1 crown R and scene R);
- 9 per-pair polygon-null metrics (R count, accepted draws, crown/box R, R difference, strict percentile ranks and 5th/95th percentiles);
- 10 per-pair Table S4 checks (crown displacement, rate, P1 values/resolution inequality, polygon-null values and draw count, plus cross-check of the archived displacement-null table).

**Result: 120/120 same-estimand checks passed** at exact integer counts and at the precision stored by the author tables.

Table-file checksums used by this audit:

| Archive table | Bytes | SHA-256 |
|---|---:|---|
| `tables/nisar_pot_series.json` | 1,138 | `a50e1a1853f270aafcc4a0e04e01e6017166473d2739d278089e0386e6a5b73a` |
| `tables/polygon_null.json` | 1,185 | `141249f00b05f7ad4cbb405600006e4c0395fea4341895b3fd5b409fb967eb87` |
| `tables/displacement_null.json` | 497 | `b8a16de84a0c3f732daf7d3d3cd261596edbe312a432d7f65978a1a5947ac207` |
| `tables/TableS4_site_series.json` | 4,348 | `38cbda0bcd7e5920bfdc33e1fceb80a79a6fa3f00ccbf23985ee657c61f46f4a` |

Machine-readable metrics are in `docs/know-place/reference/author_archive_golden_v1.json` under `processed_field_table_parity`. The regression test enforces the count-estimand separation and parity summary. The verifier now blocks a full-archive result if required reference tables are absent or same-estimand comparisons fail.

## What remains unproven

- Original GOFF source-grid pixel-by-pixel crop/mask parity.
- Exact author-exact raw source bytes and SHA-256, especially the first-pair P05023 product.
- Full-footprint offset-raster reproduction.
- Independent event/non-event validation and hazard-detection accuracy.

Do not promote this pass to a paper-reproduction or hazard-detection claim. Keep the paper-reproduction gate blocked and detection `NOT_EVALUATED` until those separate gates pass.
