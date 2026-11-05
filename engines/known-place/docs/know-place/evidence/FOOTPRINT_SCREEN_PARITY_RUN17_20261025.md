# Exact-author site/P2 and footprint-wide screen parity — Run 40170290176

## Gate decision

**PASS for the site-series/P2 table comparisons and the deposited full-footprint aggregate raster/candidate-inventory comparisons.** This is numeric reproducibility evidence for the specified author paths on exact P05023 GOFF sources. It is not a full-paper reproduction claim, and it is not a hazard-detection evaluation.

- Raw replay: [Run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176).
- Execution revision: `417cc2f0156bb310f933b72edb9ecd359812f623`, branch `feat/know-place-analysis`.
- GitHub artifact ID: `12589719900`, 18,313,236 bytes, SHA-256 `a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`.
- Author archive: 183,389,034 bytes, SHA-256 `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`, DOI [10.5281/zenodo.22730419](https://doi.org/10.5281/zenodo.22730419).
- Exact source set: 5/5 author-selected `P05023` products, 5,473,566,720 source bytes total; per-product source byte count, SHA-256, HDF5/container, identity and native-grid checks passed. The retained artifact has derived outputs and receipts but **0 raw HDF5 files**, because raw files were removed only after durable Drive retention/receipt verification.
- Key retained members: `author-raw-site-series-report.json`, `author-exact-analysis-status.json`, `footprint/author-footprint-replay-report.json`, five `footprint/pairs/*_footprint_screen.tif` files and three aggregate rasters.

## 1. Site series and P2/local-mean reference — Supplementary Table S4

### P1/site-series and post-hoc polygon controls

- `author_site_series_table_comparison.status=PASS_AT_ARCHIVE_ROUNDING`
- Checks passed: **65/65**, mismatches: **0**
- Direct Table S4 coverage: **45/95 cells** (the other 20 of the 65 checks are supporting diagnostics not themselves Table S4 metric columns).
- The P1 crown-local geometry estimator uses the radarGrid XY cell nearest the declared crown reference point and the median of each geometry field along the height axis. All five raw pair paths recorded finite geometry/unit evidence.

### P2/local-mean reference

- `author_p2_table_comparison.status=PASS_AT_ARCHIVE_ROUNDING`
- Checks passed: **15/15**, mismatches: **0** (five intervals × `P2_R_crown`, `P2_R_bg`, `P2_resolved`).
- The implemented method uses per-pixel DEM-interpolated radarGrid geometry coefficients, float32 AT/SR projection and quality gates, a 41 × 41 local mean, then 5 × 5 residual directional coherence. The 22-pixel context halo is processed before the wide-box/crown crops so crop-edge padding does not alter the residual R calculation.
- Comparison values (archive target precision):

| Pair | Computed crown R | Archive | Computed background R | Archive | Resolved flag |
|---|---:|---:|---:|---:|---|
| 20 Jun–2 Jul | 0.669284 | 0.669 | 0.678225 | 0.678 | No |
| 2–14 Jul | 0.679403 | 0.679 | 0.666995 | 0.667 | Yes |
| 14–26 Jul | 0.725870 | 0.726 | 0.697202 | 0.697 | Yes |
| 26 Jul–19 Aug | 0.774637 | 0.775 | 0.794986 | 0.795 | No |
| 19–31 Aug | 0.666216 | 0.666 | 0.661457 | 0.661 | Yes |

The declared vertical-reference discrepancy remains explicit: the author-deposited code uses prepared Copernicus DEM elevation directly against the radarGrid HAE height axis and applies no vertical transformation. The replay preserved that source method for comparison. This is not a datum-correctness certification; the independent EGM2008/HAE sensitivity remains relevant to physical interpretation.

## 2. Full-footprint screen — 4230 × 4311 native grid

The replay processed all five exact P05023 pairs on EPSG:32645, 80 m posting, affine `(80, 0, 126720; 0, -80, 3347280)`. The full grid contains **18,235,530 cells**.

### Aggregate raster comparisons

| Author aggregate output | Compared support | Finite-mask mismatches | Maximum absolute difference | Tolerance | Result |
|---|---:|---:|---:|---:|---|
| `n_epochs_flagged.tif` | 18,235,530 cells | 0 | 0 | exact | PASS |
| `mean_anomaly_m.tif` | 4,008 finite cells | 0 | 0 m | 1e-5 m | PASS |
| `mean_coherence_R.tif` | 4,008 finite cells | 0 | 0 | 1e-5 | PASS |

The finite support of the two float aggregate rasters is the persistent-candidate region, not the full grid. Their report has zero finite-mask mismatch and zero value difference on all 4,008 finite cells. This is stronger than matching only a summary statistic.

### Persistence and candidate inventory

| Check | Author/reference | Computed | Result |
|---|---:|---:|---|
| Persistent cells | 4,008 | 4,008 | PASS |
| Connected components before size filter | — | 1,029 | Recorded |
| Retained components (≥10 cells) | 106 | 106 | PASS |
| Directional/quality-pass zones | 101 | 101 | PASS |
| Missing / extra candidate rows | 0 / 0 | 0 / 0 | PASS |
| Inventory numeric mismatches | 0 | 0 | PASS |
| Strict ranking inversions | 0 across 5,564 checked pairs | 0 | PASS |

The 106-row candidate inventory matches all compared numeric attributes under absolute tolerance `1e-4`; maximum reported errors are `1.40091e-5` in `range_az` and `6.15388e-6` in `downslope_az`. The source inventory's post-processed score convention also passes: zone-max epoch count × zone-mean anomaly rounded to 3 decimals × zone-mean residual R. The provisional centroid score is not mislabelled as the author's final score.

The 101-row Table S7 comparison passes all included columns at displayed precision with zero missing rows, extras or mismatches. Its compared columns include centroid, area, epochs, residual displacement, displacement/downslope/range directions, coherence, elevation and slope.

**Not compared:** `glacier`, `RGIId`, and `d_glac_m` fields require exact RGI 6.0 polygons that are not packaged in this author archive. The replay does not infer these classifications from old RGI identifiers or from a modern outline.

## 3. Retention and source-integrity boundary

The source manifest records all five exact `P05023` granule filenames, CMR IDs, byte counts and SHA-256 hashes. The cleanup receipt ties its source-manifest hash to the manifest bytes and records five hash-verified files deleted, zero raw files remaining, and remote verification of the derived bundle and receipt copy. The subsequent [Run 40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570) re-audited the retained artifact and its cleanup/manifest chain and passed the five-pair published-bounds mask/source-grid consistency check. That later audit did not read or re-hash the deleted HDF5 bytes.

## 4. What is and is not finished

**Completed with direct evidence:** exact P05023 source acquisition and grid checks; P1/site and post-hoc site/polygon comparisons (65/65); P2/local-mean comparisons (15/15); aggregate full-footprint rasters (3/3); 106 candidate inventory rows; 101 numeric Table S7 rows; retained-only artifact/cleanup provenance; and the published-bounds/native-grid crown-mask reconstruction check.

**Still open:**
1. **Displacement-null source identity:** the source-inspired deterministic replay now matches all 15 displacement-null Table S4 output fields (five crown medians, five null medians and five percentiles) at archived precision. The exact original generator and draw/rejection history remain absent, so source-code/draw-sequence identity is unverified. See DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md and DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.json; the full report is artifact [12608431799 from Run 40219393283](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283/artifacts/12608431799). Do not represent reconstructed accepted counts as author counts.
2. **Original source mask:** no editable author crown vector or saved golden grid mask is in the reviewed author archive. The 323-cell mask's internal grid/bounds consistency passes; identity with an absent author vector/golden mask remains unverified.
3. **Glacier overlay:** exact RGI 6.0 source polygon files and hashes are absent, so glacier class, RGI ID and nearest-glacier distance are not compared.
4. **Terrain vertical reference:** the archived code's direct DEM-to-HAE interpolation is reproduced, but the underlying vertical-reference mismatch is not corrected or declared physically validated.
5. **Hazard detection:** there is no independent labelled event/test set scored here; `HAZARD_DETECTION_STATUS=NOT_EVALUATED` and `OPERATIONAL_WARNING_STATUS=NOT_IMPLEMENTED`.

**Overall status:** `PAPER_REPRODUCTION_STATUS=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`. All 95 Table S4 numeric outputs now match archived precision across direct P1/P2/core checks plus the source-inspired displacement-null reconstruction. Exact displacement-null source-code/draw identity remains a provenance caveat, not a numeric mismatch. None of these results demonstrates a prospective landslide or glacier-collapse alarm.
