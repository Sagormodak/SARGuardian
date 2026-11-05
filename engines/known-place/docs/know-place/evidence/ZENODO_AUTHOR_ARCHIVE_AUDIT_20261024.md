# Zenodo author archive integrity and method-parity audit

**Audit date:** 2026-10-24  
**Branch:** feat/know-place-analysis  
**Archive DOI:** https://doi.org/10.5281/zenodo.22730419  
**Current paper-reproduction gate:** BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED  
**Hazard-detection gate:** NOT_EVALUATED

## 1. Files received and byte-level integrity

The user supplied README.md and bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip. The exact uploaded bytes were hashed before inspection.

| File | Bytes | MD5 | SHA-256 |
|---|---:|---|---|
| README.md | 6,473 | f6d057f28c3dbccb62f32e98e41bf594 | d20f8eb894afffc2ae469c110fb69028caef8360fc1b8039f56863eeebf11199 |
| Main archive ZIP | 183,389,034 | b07b7eb3b3178d3f69d5bca009cb0db4 | 002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3 |

The ZIP integrity check passed. MANIFEST.json declares 97 record-level files. Of those, 90 manifest-listed payloads are present in the ZIP and every one matched both declared size and MD5; mismatch count was zero. Seven manifest paths are outside the ZIP: the separately supplied README.md and six files forming the separately licensed extent_CC-BY-NC-4.0 runout shape set. MANIFEST.json is the only ZIP entry not listed in its own manifest, avoiding self-reference. This is consistent with a Zenodo record made of multiple file components; it is not evidence of a damaged ZIP.

The separate CC BY-NC 4.0 outline was not present in the uploaded ZIP and was not copied to the repository. The main record's LICENSE.txt applies CC BY 4.0 except for that separate folder. Derived terrain data retain the Copernicus DEM attribution described by the record.

## 2. What was inside the archive

The ZIP includes 33 Python source files, five per-pair site-field GeoTIFFs, site-series and null-distribution tables, canonical publication numbers, the 101-zone attributed inventory, three footprint screen rasters, and three terrain rasters.

It does **not** include the five original NISAR GOFF HDF5 granules. TableS1 lists their IDs and source file sizes (about 1.09 GB each), but identifiers and expected sizes are not source-byte checksums. It also explicitly omits five full-footprint 4230 x 4311 per-pair offset rasters; README says those need to be regenerated from public GOFF sources by the archived code.

### README-versus-file profile discrepancy

The README describes fields/offsets_*.tif as EPSG:32645 at 80 m posting, with east, north, magnitude, and coherence bands. Actual profiles inspected from all five TIFF files are **73 x 80 pixels, EPSG:4326, and three bands**: dE, dN, and R. Magnitude can be derived from dE/dN but is not stored as a band. The separate footprint screen rasters use EPSG:32645 at 80 m. This is a README-versus-file-profile discrepancy; the audit preserves both facts rather than silently normalizing the record.

The stored R band was independently recomputed from dE/dN using the author’s reflected-edge normalized uniform-filter rule. All five rasters have exactly matching finite-R masks on this comparison; common finite cells by pair are 4,539, 4,676, 4,802, 4,657 and 4,461. Median absolute errors are 1.03e-8–1.14e-8, 95th-percentile absolute errors 2.74e-8–2.79e-8, and the maximum absolute error over all five is 3.50e-8; zero cells exceed 1e-6. Each source TIFF SHA-256 and pair-level error metric is recorded in author_archive_golden_v1.json. This verifies the stored R band from the same exported dE/dN grids; it is not raw HDF5 source replay and does not validate crown-mask or full-footprint parity.

## 3. Exact match to Supplementary Data 1

The archive's tables/TableS7_all_validated_zones.csv and the user's earlier CSV are byte-identical: both are 9,085 bytes and SHA-256 b800d90bd6e7322ef2f8548370de0fb922ef057cbdce2d0c2caa681ae76a42a8. Both contain 101 rows and 15 columns, with 93 glacier-intersecting and eight off-glacier zones. Source zone 43 is a source-derived post-event inventory entry, not an independent prospective holdout.

The archive's TableS4_site_series.csv agrees with the values transcribed into author_benchmark_v1.json across all five pairs. For 26 July–19 August it reports 0.96 m median crown displacement, 4.0 cm/day, P1 crown/background R of 0.871/0.687, polygon-null crown percentile 85.2, and displacement-null percentile 94.7. A close single-pair scalar match is not sufficient evidence of all-pair or pixelwise reproduction.

## 4. Author implementation recovered from the archive

The audit read included code rather than inferring implementation only from the manuscript.

- The site series in make_pot_figure.py selects the radarGrid sample nearest the declared crown coordinate and uses the median along the geometry height axis for each geometry component. That is a crown-local scalar geometry choice. The current branch samples geometry per pixel at a configured height; it is not the same estimator.
- The author site-series quality mask requires finite SNR, SNR >= 5, and projected horizontal magnitude <= 10 m. It does not use correlationSurfacePeak as an input-validity filter. The current branch requires finite correlation for its source-valid flag.
- Reference dE/dN are component-wise medians from valid pixels in the WIDE box outside the rectangular AOI, based on coordinate axes transformed at the middle row/column. The current branch uses projected point-in-polygon masks; exact parity has not been demonstrated.
- The author 5 x 5 directional coherence uses scipy.ndimage.uniform_filter with default reflected edge behavior, normalizes by finite-vector count, and retains windows only where the filtered finite fraction is > 0.5, at least 13 of 25 vectors. In make_fig_timeseries.py, P1 crown R is computed after cropping to the crown slice; P1 scene/background R is computed over the full WIDE box. Polygon-null R is a separate estimator. These R numbers must not be treated as interchangeable. Current branch defaults to zero-padded windows and at least one valid vector.
- polygon_null.py uses seed 20260907 and tries 1200 unique candidate centres without replacement from all finite-R cells. A circular sample is accepted with at least 60% of the crown's valid-cell count; the crown percentile counts strict draws < crown, and percent beating box counts strict draws > box. This differs from the branch's exploratory sampler, which selects background centres and excludes the crown from its control mask.
- The README states displacement_null.py was planned but is absent as a separate script; tables/displacement_null.json is present. Exact generator parity for displacement-null results cannot be established from the absent script alone.
- The code has a workstation-specific I:\nisar\nepal_bhotekoshi_t098 root path and no included environment lock file, so it is not turnkey in a different environment.

## 5. Current scientific gate and next steps

The archive-integrity and published-output-reference gate is now **PASS**. The raw replay and author-method parity gate remains **BLOCKED**:

1. Original author GOFF HDF5 payloads and their SHA-256 values are not in the ZIP. Four exact P05023 IDs had trusted collection URLs in the prior catalog query, while the exact first-pair P05023 ID returned NOT_FOUND. A catalog route is not a source-byte hash.
2. The current branch's geometry sampling, correlation validity gate, coherence edge/neighbour policy, crown masking and null-control sampling differ from the archived author implementation.
3. The five exported 73 x 80 WGS84 field TIFFs reproduce their stored R bands numerically. The former “296 versus 298” comparison mixed displacement-valid crown count `n` (296) with polygon-null R-valid crown count `n_px` (298). Across all five exported fields, displacement counts `[283, 294, 296, 292, 195]` match `tables/nisar_pot_series.json` key `n`, and separately recomputed R-valid crown counts `[302, 299, 302, 298, 202]` match `tables/polygon_null.json` key `n_px`. Exact pixelwise mask parity on the original GOFF source grid remains unverified; aggregate count agreement does not resolve that.
4. Full-footprint per-pair offset rasters are absent, so the full-footprint screen must be regenerated from exact source granules before claiming replay parity.

Next work is a separately tested author-parity path, comparison against the five archived fields and TableS4, resolution and SHA-256 pinning of exact raw GOFF inputs (without substituting X05026 for P05023), and then a full-footprint regeneration. Keep paper reproduction BLOCKED and hazard detection NOT_EVALUATED until those gates pass. This audit authorizes no change or merge to main.


## Author-parity kernels (separate exploratory/reproduction boundary)

The branch now has a separate `tools/know_place/author_parity.py` module. It contains recovered kernels for reflected-edge 5×5 coherence with strict >0.5 finite support, source quality gate without a correlation threshold, author LOS projection, crown-local geometry median over height, WIDE window selection, midline-coordinate rectangular AOI mask, stable-ground correction only when ring-valid count exceeds 200, north-up flip/extent, endpoint-linear crown slicing, P1 crown-cropped coherence, and the source polygon-null algorithm. Synthetic regression tests are in `tools/tests/test_know_place_author_parity.py`. The existing exploratory `tools/know_place/analyze.py` is unchanged; the recovered kernels have not yet been integrated into a full raw-input replay, and no paper-reproduction claim is made.


## Re-running the processed-field check

Use `python -m tools.know_place.verify_author_fields /path/to/bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip --output author-field-verification.json`. The verifier checks ZIP payload entries against the archived manifest, records hashes/profiles for all five small field rasters, recomputes R from bands 1–2, and compares it with band 3. It does not extract or copy the separately licensed CC BY-NC runout outline, download raw GOFF products, or claim source-to-output parity.


## Crown-crop metric reconciliation across all five exported fields

The previous comparison was invalid because it treated two different estimands as if they were one count. The author archive contains displacement-valid crown counts in `tables/nisar_pot_series.json` under `n`, and polygon-null coherence-valid crown counts in `tables/polygon_null.json` under `n_px`. The latter is based on finite cells of the author coherence map computed over the full field and then cropped; it is not the P1 crown-R estimator, which computes coherence after cropping.

| Pair | Export displacement-valid / series `n` | Difference | Export R-valid / polygon-null `n_px` | Difference |
|---|---:|---:|---:|---:|
| 2026-06-20 → 2026-07-02 | 283 / 283 | 0 | 302 / 302 | 0 |
| 2026-07-02 → 2026-07-14 | 294 / 294 | 0 | 299 / 299 | 0 |
| 2026-07-14 → 2026-07-26 | 296 / 296 | 0 | 302 / 302 | 0 |
| 2026-07-26 → 2026-08-19 | 292 / 292 | 0 | 298 / 298 | 0 |
| 2026-08-19 → 2026-08-31 | 195 / 195 | 0 | 202 / 202 | 0 |

The counts above were independently recomputed from the five exported TIFFs with the author crown crop policy. The author coherence map was recomputed from each TIFF's dE/dN bands; its finite mask matched archived band 3 for all five fields, and the largest absolute R error was `3.4930149217515805e-8`, below the `1e-6` comparison tolerance. Exported-field counts match their respective archived table counts; there is no residual count discrepancy when the estimands are kept separate.

This does **not** establish pixelwise mask parity on the original GOFF source grid. The original GOFF coordinate vectors/read window and author pre-export masks or rasterization extents are not in the ZIP. The reason for any source-grid mask difference remains unresolved; no cause is inferred. The remaining gate is `BLOCKED_SOURCE_GRID_PIXEL_MASK_PARITY_UNVERIFIED`. Processed-field statistics and same-estimand table cross-checks for all five pairs are recorded in [AUTHOR_PROCESSED_FIELD_TABLE_PARITY_20261024.md](AUTHOR_PROCESSED_FIELD_TABLE_PARITY_20261024.md), with 120/120 processed-field/table checks passing.
