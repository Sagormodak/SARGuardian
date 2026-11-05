# P2/local-mean reference audit and correction — 2026-10-25

## Historical failed replay (superseded by Run 40170290176)


## Superseding successful exact-author replay — Run 40170290176

The later, explicitly authorized [Run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176) exercised the corrected path on all five exact P05023 inputs. Its retained artifact reports:

- P1/site-series and post-hoc site/polygon checks: **65/65 PASS**, no mismatches.
- P2/local-mean checks: **15/15 PASS**, no mismatches at archive rounding.
- P2 method: per-pixel DEM-interpolated geometry; float32 SNR/magnitude-gated dE/dN; 41 × 41 local mean; 5 × 5 residual coherence calculated with a 22-pixel context halo before box/crown cropping.
- Full-footprint path: **PASS_AUTHOR_AGGREGATE_RASTERS_AND_CANDIDATE_INVENTORY**. Three aggregate rasters, 106 candidate rows and 101 Table S7 numeric rows passed their declared comparisons.
- Output-level limits: the exact RGI 6.0 glacier-class/nearest-glacier overlay columns were excluded because those polygon assets are not included in the author archive. The vertical-reference mismatch (prepared DEM EPSG:9518/Egm2008 height versus radarGrid HAE) was explicitly passed through to reproduce the deposited code; no datum correction was applied.

The 3/15 P2 result documented below is preserved as a historical failure analysis, not the current result. Full comparison evidence is in [FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md](FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md), and the 95-cell accounting is in [TABLE_S4_COVERAGE_REGISTER_20261025.md](TABLE_S4_COVERAGE_REGISTER_20261025.md).



The explicitly authorized exact-author run 40140476008 (https://github.com/moshiour0/SARGuardian-backend/actions/runs/40140476008) downloaded and verified all five P05023 sources (5/5 SHA-256 and grids) and completed the selected P1/site checks (65/65). The P2/local-mean comparison was 3/15, with 12 mismatches. The run did not execute full-footprint parity because the workflow tied the footprint step to the overall acquisition/site-analysis step outcome. Its run-level result was failure; green substeps for download and Google Drive retention are not scientific success.

The same run completed derived-only Drive retention and remote receipt verification, then verified source hashes, deleted all five temporary raw HDF5 files, confirmed zero remained, and uploaded/verified a post-delete cleanup receipt. These retention controls must remain intact.

## Root causes identified for correction

1. P1 site-series statistics use the archived crown-point/height-axis-median geometry approximation. The P2 footprint/local-mean path incorrectly reused that same single geometry sample. The author archive wide-screen method instead projects GOFF AT/SR at each target DEM pixel using per-pixel geometry coefficients interpolated from the radarGrid geometry cubes over height, y and x.
2. P2 recomputed directional coherence after cropping the projected residual vectors to the crown. The author footprint kernel computes the 5x5 residual-coherence raster on the contextual field and then crops that R raster, so the crown crop must not create a second reflected-edge calculation.

## Corrections added to the isolated feature branch

- P2 uses the pinned Zenodo terrain/elev_m.tif tile aligned to the raw GOFF row/column window. The code checks the DEM SHA-256, full source dimensions, CRS, affine, band type and nodata, plus GOFF pixel-centre alignment.
- P2 builds source-compatible per-pixel geometry coefficients from the first exact pair and reuses the coefficient tile across the five same-grid pairs, matching the author's cached geometry behavior. Raw AT/SR and projection operations use float32.
- P2 computes the 41x41 local mean and 5x5 residual coherence on the halo/context first. It then selects the WIDE box directly from the projected GOFF x/y axes, calculates the box's endpoint-derived geographic extent, and selects the crown from that WIDE crop's extent, matching `read_pair()` plus `crown_slice()` in the author's site-series code.
- Raw-download dispatch fails closed before any CMR query unless the pinned DEM is supplied and hash-verified.
- The independent full-footprint parity step now depends on verified source config/manifest availability and the author archive, not on P1/P2 parity success. A P2 mismatch will no longer suppress the independent raster/inventory/Table S7 audit. The final scientific gate remains strict and still fails on real mismatches.
- Private Google Drive upload, receipt-copy verification, post-delete cleanup receipt, raw-not-uploaded assertion and source-hash checks remain intact.

## Verification boundary

The earlier 3/15 P2 result described the old code path. Run 40170290176 now verifies the corrected P2 values (15/15), the three aggregate footprint rasters, the 106-row candidate inventory, the 101-row Table S7 numeric comparison and score/rank order. The only Table S4 method-parity group still blocked is the 15-cell displacement-null group because its draw-level method evidence is absent.

The archived displacement-null summary fields do not include the draw-level null-generation implementation, so those exact values remain independently unresolved. Even numerical parity would not establish detection skill. Event-wise precision/recall, false-alarm rates, lead time and independent geophysical validation are still unevaluated. hazard_detection_status must stay NOT_EVALUATED.

No work in this patch changes main. Run 40170290176 is the completed consented replay referenced here; do not run another approximately 5.47 GB raw replay without a new explicit [run-know-place] authorization.
