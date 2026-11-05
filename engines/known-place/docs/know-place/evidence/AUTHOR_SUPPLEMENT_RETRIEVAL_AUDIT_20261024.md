# Author paper and supplementary-data audit — Know Place Analysis

**Audit date:** 2026-10-24  
**Working branch:** `feat/know-place-analysis`  
**Current paper reproduction status:** `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`  
**Hazard-detection status:** `NOT_EVALUATED`

## 1. Sources received and provenance

The user supplied the paper PDF, its supplementary-information Word file, and the 101-zone CSV. All three were opened and inspected; SHA-256 digests of the original uploaded bytes are:

| Uploaded item | Use | SHA-256 |
|---|---|---|
| `nisar_offsets_measure_pre_failure_motion_but_do_not_single_out_the_bhote_koshi_avalanche_source.pdf` | Main paper, 32 pages | `514ff22bbf8adff829605e005496cff7f80ee72596171432aa169f2ffb986705` |
| `8da4c3f71775fbc4b0d7d324.docx` | Supplementary Information, 10 pages: Supplementary Figs. 1–3 and Tables 1–6 | `37c43d7f683796aa96f9a90f0bd6abda2b1e26f4ccbbb674cfa13642da37f777` |
| `b0dbe1d825f6eb03362df3d2.csv` | Supplementary Data 1: 101 validated footprint-screen zones | `b800d90bd6e7322ef2f8548370de0fb922ef057cbdce2d0c2caa681ae76a42a8` |

The source-derived CSV is preserved in the repository at `docs/know-place/reference/author_validated_zones_supplementary_data_1.csv`. The paper/supplement values transcribed for automated integrity checks are in `docs/know-place/reference/author_benchmark_v1.json`; attribution and reuse limitations are in the neighbouring `README.md`.

**User-supplied benchmark version under test:** Sansar Raj Meena, “NISAR offsets measure pre-failure motion but do not single out the Bhote Koshi avalanche source,” posted 22 September 2026, Research Square DOI https://doi.org/10.21203/rs.3.rs-11022365/v1. The paper points to the processing code, statistics and figure/golden-data archive at https://doi.org/10.5281/zenodo.22730419.

**Manuscript-version caution:** the pre-existing `KNOW_PLACE_ANALYSIS_BLUEPRINT.md` cites a differently titled EGUsphere preprint, DOI `10.5194/egusphere-2026-5462`. A formal cross-version identity/content comparison has not been completed. The exact product IDs and table values transcribed in this audit refer only to the uploaded Research Square PDF and its supplied supplement; do not silently assume the two records are identical or mix their source manifests.

At the time of the supplement-only review, the DOCX was available but the separate Zenodo archive had not yet been supplied. The user has now supplied that archive; its hashes and payload checks are documented in `ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md`. Script-level parity and exact raw-source replay remain blocked for the reasons in that later audit. The article and supplement describe CC BY 4.0 terms, except Supplementary Figure 1 and Supplementary Table 5, identified as third-party CC BY-NC 4.0 material. Those exceptions are not copied into the repository.

## 2. Exact facts now resolved from the supplied supplement

### 2.1 Crown and reference geometry

The paper provides the crown bounds directly in the Methods and Supplementary Fig. 2. The author-published rectangle in WGS84 is:

```text
POLYGON ((85.5245 28.2847, 85.5400 28.2847,
          85.5400 28.2970, 85.5245 28.2970,
          85.5245 28.2847))
```

Published area is 2.07 km². The 6 km reference box is bounded by 85.500–85.565° E and 28.265–28.318° N. This resolves the polygon-coordinate blocker: the prior AOI WKT uses the same numerical bounds. The earlier “296 versus 298” count comparison mixed estimands: 296 is displacement-valid series count `n`, whereas 298 is polygon-null R-valid count `n_px`. Across the five exported fields, displacement counts `[283, 294, 296, 292, 195]` match `tables/nisar_pot_series.json` key `n`; separately recomputed R-valid counts `[302, 299, 302, 298, 202]` match `tables/polygon_null.json` key `n_px`. Exact pixelwise mask parity on the original GOFF source grid remains unverified.

### 2.2 Exact five author granule identities

Supplementary Table 1 specifies these exact GOFF identifiers (all release `P05023`):

| Pair | Days | Flag | Exact author granule suffix |
|---|---:|---|---|
| 20 Jun–2 Jul 2026 | 12 | N_F | `...20260620T233921_20260620T233956_20260702T233920_20260702T233955_P05023_N_F_J_001` |
| 2–14 Jul 2026 | 12 | F_F | `...20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001` |
| 14–26 Jul 2026 | 12 | N_F | `...20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001` |
| 26 Jul–19 Aug 2026 | 24 | N_F | `...20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001` |
| 19–31 Aug 2026 | 12 | N_F | `...20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_N_F_J_001` |

The earlier raw replay (Run 40006999011) and the frozen historical catalog manifest used CRID `X05026` for the first pair. The historical input's byte-size/SHA-256 checks remain valid for that file, but the variant **does not match the supplied author's manifest**. The other four identifiers match. Do not relabel the old replay as an exact five-granule author reproduction and do not overwrite the historical source hash. The live no-download author-ID query in validation Run 40035193088 confirmed trusted collection-route identities for four P05023 granules, but returned `ASF_AUTHOR_EXACT_GRANULE_NOT_FOUND` for the 20 June–2 July P05023 granule. The separate historical gate still confirms X05026 for that pair. The lookup does not establish whether the author ID survives in another archive or older catalog state; no raw data was downloaded and no author-P05023 source SHA-256 exists.

### 2.3 Site-series method as stated in the supplied paper

- Use layer2 along-track (AT) and slant-range (SR) offsets where SNR is at least 5.
- Project to horizontal east/north using the stated LOS sign convention; the LOS unit vector points target-to-sensor, positive slant-range means motion away from the sensor, and vertical motion is set to zero.
- Discard projected magnitudes greater than 10 m before reference correction.
- Remove component-wise median offset from SNR-valid cells in the fixed 6 km box outside the crown, with more than 200 samples and no additional stability selection.
- Site-series geometry uses one crown-local radar geometry throughout. In contrast, the footprint-wide screen interpolates per-pixel geometry at Copernicus GLO-90 heights. The current 5151.0 m constant is conceptually consistent with one crown-local geometry, but the paper's text does not specify the exact height datum/query, so the existing HAE value and interpolation still need comparison with the author's code/rasters.
- Directional coherence is the 5×5 mean resultant length (R) of unit displacement vectors. The paper notes that its published crown estimator crops the polygon and reflects at crop edges; a single-field, crown-excluded background recomputation is also reported. The exact missing-neighbour/edge implementation should be confirmed against source code.
- Polygon-scale nulls use compact regions matched to the crown's valid-cell count in the 6 km box; the supplement reports 857–996 accepted draws per pair. The text does not uniquely specify the PRNG, draw sequence, invalid-cell rejection, and polygon-placement implementation. Do not infer those details.

### 2.4 Published site-series golden values

The machine-readable transcription is in `author_benchmark_v1.json`. The key Table 4 rows, in pair order 20 Jun–2 Jul, 2–14 Jul, 14–26 Jul, 26 Jul–19 Aug and 19–31 Aug, are:

| Statistic | Published values |
|---|---|
| Displacement-valid crown cells (`n` from `tables/nisar_pot_series.json`) | 283, 294, 296, 292, 195 |
| Polygon-null R-valid crown cells (`n_px` from `tables/polygon_null.json`; separate estimand) | 302, 299, 302, 298, 202 |
| Median displacement (m) | 0.99, 0.54, 0.30, 0.96, 0.33 |
| Median interval-average rate (cm/day) | 8.3, 4.5, 2.5, 4.0, 2.7 |
| Displacement-null percentile | 94.9, 87.5, 81.0, 94.7, 81.3 |
| Bulk-reference crown (R) | 0.750, 0.612, 0.611, 0.871, 0.551 |
| Bulk-reference background (R) | 0.641, 0.719, 0.757, 0.687, 0.592 |
| Polygon-scale (R)-null percentile | 77.2, 23.3, 39.8, 85.2, 29.1 |

The final pre-event interval spans 24 days and ends seven days before failure because the 7 August acquisition is absent. The paper says that no pre-event interval reaches the 95th percentile for displacement or directional coherence and that no acceleration is resolved. The 0.96 m movement is an interval-average measurement, not a failure diagnosis.

### 2.5 Supplied 101-zone footprint-screen inventory

The CSV has 101 rows and 15 columns. The counts match the paper: 93 zones intersect RGI 6.0 and 8 do not. The event source corresponds to zone 43:

- centre: 85.5294° E, 28.29161° N
- area: 0.192 km²
- flagged in 3 of 5 pairs
- mean residual displacement: 4.38 m toward 276.3°
- downslope azimuth: 296.1°, misfit 19.8°
- residual directional coherence (R=0.915)
- elevation 5,084 m; slope 24.9°; RGI 6.0 ID `RGI60-15.04173`

These match the rounded source-zone values in the main paper. This is author-derived post-event inventory data, **not an independent blind holdout set** and not evidence of predictive skill. It must not be used to train and test on the same post-selected zones.

## 3. What remains blocked

- Superseded archive-retrieval note: the Zenodo code/statistics/processed-field ZIP is now downloaded and hash-verified; see `ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md`. Raw GOFF HDF5 and full-footprint per-pair rasters are not in the ZIP.
- A live ASF query confirmed four of five author P05023 granules by trusted collection URL, but the exact 20 June–2 July P05023 identifier was not found (Run 40035193088). The separate historical-candidate query confirms X05026 for that same interval. No raw source was downloaded during either gate; preserve X05026 only as historical evidence and do not call it author-identical.
- Pixelwise comparison against author east/north/magnitude/coherence rasters and exact equality/tolerance checks for all five pairs are not complete.
- A prior 296-versus-298 comparison mixed displacement-valid series count `n` with polygon-null R-valid count `n_px`. Matched count estimands agree across all five exported fields. Exact pixelwise source-grid mask parity remains unverified because the original GOFF coordinate vectors/read window and author pre-export masks or rasterization extents are absent; no cause is inferred.
- The site's constant 5151.0 m HAE query is not proven equivalent to the author's crown-local geometry sampling: the paper confirms one crown-local geometry for the site series, but exact height/datum and sampling code are not stated in the PDF/supplement text.
- The exact random-region generator and acceptance rules and the exact 5×5 coherence missing/edge policy must be taken from the author scripts, not guessed.
- At the time of the original supplement-only review, only the paper, DOCX and CSV had been supplied. The later Zenodo archive includes original analysis code, numeric tables, site fields and footprint screen rasters, but omits raw GOFF HDF5 payloads and full-footprint per-pair offset rasters.

## 4. Acceptance plan

1. [x] Obtain the Zenodo archive, save original filenames and SHA-256/MD5 values, and verify included manifest-listed payloads; see the later Zenodo archive audit.
2. Compare the archive README and source metadata with the failed live lookup for the exact first-pair P05023 ID. If the author archive includes that granule or a retrievable direct object reference, verify bytes and SHA-256 before any new run. If it remains unavailable, document the source-version mismatch and ask the corresponding archive/author for clarification; never substitute, rename or relabel X05026 as P05023.
3. Extract the author's actual scripts and reproduce their environment/commands. Use the author crown WKT now recorded in the reference manifest.
4. Compare source rasters and all Table 4 values pair-by-pair. Record pixelwise tolerances, valid masks, crown cell counts, scalar values, null distributions, and any known grid/resampling differences.
5. Reproduce the footprint inventory/screen only from the documented source input, parameters, and archive outputs. Keep source-zone inventory distinct from independent-event validation.
6. Leave paper reproduction `BLOCKED` and hazard detection `NOT_EVALUATED` until exact inputs and independent golden-output comparisons pass.

The historic raw files/arrays should be reused wherever they remain applicable; do not re-download the four matching granules merely to re-check their IDs.


## Superseding update

The archive was subsequently supplied and verified on 2026-10-24. Archive identity, file-profile discrepancy, TableS7 equality, exact site-series code details, and remaining implementation/source blockers are documented in [ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md](ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md). This document preserves the earlier supplement-only findings but does not claim the current calculation is a faithful reproduction.
