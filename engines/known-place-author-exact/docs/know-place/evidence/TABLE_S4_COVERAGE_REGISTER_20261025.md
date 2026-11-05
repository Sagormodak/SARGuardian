# Supplementary Table S4 cell-coverage register — 2026-10-25

Source: author-deposited `tables/TableS4_site_series.csv/json` in Zenodo `10.5281/zenodo.22730419` (CC BY 4.0). Five intervals × 19 metric columns = **95 metric cells**; the pair identifier and `days` column are not included in this metric count.

This register is updated against the latest completed exact-author replay, [Run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), and the direct evidence register [FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md](FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md). This run includes the corrected halo-aware P2 path and the full-footprint screen replay. It supersedes earlier snapshots that marked P2 pending.

| Table S4 metric column | Cells | State as of this register | Evidence / reason |
|---|---:|---|---|
| `crown_disp_m` | 5 | **Verified** | Exact author site-series runner compared the median crown displacement against the archive at published precision. |
| `crown_rate_cm_per_day` | 5 | **Verified** | Calculated from the crown median and exact pair duration; matched archive rounding. |
| `P1_R_crown` | 5 | **Verified** | Bulk-reference P1 coherence; archive comparison passed. |
| `P1_R_bg` | 5 | **Verified** | P1 background coherence; archive comparison passed. |
| `P1_resolved` | 5 | **Verified (derived)** | Boolean reconstructed from the published P1 crown/background R inequality and checked against Table S4. |
| `P2_R_crown` | 5 | **Verified** | Run 40170290176: all five P2 crown R values match `TableS4_site_series` at three decimal places; see the per-pair comparison record in `author-raw-site-series-report.json`. |
| `P2_R_bg` | 5 | **Verified** | Run 40170290176: all five P2 background R values match the author table at three decimal places using the 22-pixel context halo. |
| `P2_resolved` | 5 | **Verified (derived)** | Run 40170290176: the five P2 resolved flags agree with the archive after P2 crown/background R pass the numeric comparisons. |
| `polynull_R_crown` | 5 | **Verified** | Archive post-hoc polygon-null runner values passed the workflow comparison at published precision. |
| `polynull_R_box` | 5 | **Verified** | Same archive comparison. |
| `polynull_crown_pctile` | 5 | **Verified** | Same archive comparison; preserve its specified strict percentile convention. |
| `polynull_pct_beat_box` | 5 | **Verified** | Same archive comparison. |
| `polynull_n_draw` | 5 | **Verified** | Accepted random-candidate count matched the archived table. |
| `dispnull_crown_m` | 5 | **Numeric output reproduced; generator identity unverified** | All five crown medians match `tables/displacement_null.json` at 0.01 m precision under a deterministic source-inspired reconstruction from deposited dE/dN fields. Exact source/draw identity is not claimed. |
| `dispnull_null_med_m` | 5 | **Numeric output reproduced; generator identity unverified** | All five null medians match at 0.01 m precision under the declared random-disk/60%-support reconstruction; the exact original generator remains absent. |
| `dispnull_pctile` | 5 | **Numeric output reproduced; generator identity unverified** | All five strict empirical percentiles match at 0.1 percentage-point precision. This is output-level parity, not a verified copy of the original draw sequence. |
| `corescale_R_zone` | 5 | **Verified conditionally** | Recomputed at published precision from the run-derived raster, using the 0.19-km² candidate polygon supplied by the author archive. The screen selecting that polygon was not independently recreated. |
| `corescale_zone_pctile` | 5 | **Verified conditionally** | Recomputed using the author's archived `reconcile_scalebias.py` procedure and archived selected polygon. This is a scale diagnostic, not an unbiased detection test. |
| `corescale_npx` | 5 | **Verified conditionally** | All five source-archive zones contain 30 pixels for this diagnostic. Independent screen-selection parity remains unproven. |

## Totals

| Classification | Metric cells |
|---|---:|
| Directly checked P1/site-series/polygon-null Table S4 cells | 45 |
| P1 booleans derived from already-verified P1 values | 5 |
| Core-scale metrics independently recalculated, conditioned on archived candidate geometry | 15 |
| P2/local-mean crown R, background R and resolved flags | 15 |
| **Direct/conditional output fields matched before displacement-null replay** | **80 / 95** |
| **Displacement-null numeric outputs reproduced at archived precision** | **15 / 15** |
| **Table S4 numeric outputs matched at archived precision** | **95 / 95** |
| **Exact displacement-null source/draw identity still unverified** | **15 / 95** |

The earlier 65/65 workflow only covered its selected comparisons. After the later P2 replay and the separate displacement-null reconstruction, all 95 archived Table S4 numeric outputs match at stored precision. The remaining caveat is source-method/draw-history identity for the 15 displacement-null fields, not a numeric mismatch.

## Remaining gates

1. **Displacement-null source identity:** all 15 output values now match at stored precision under the documented source-inspired reconstruction. Retrieve the original generator or draw/rejection history before asserting exact method/draw parity; do not present reconstructed accepted counts as the author's counts.
2. **Original mask / geometry evidence:** recover the original editable crown vector or author golden mask if available. The published-bounds/native-grid mask is internally consistent, but that does not prove exact vector-file identity.
3. **Glacier overlay:** obtain the exact RGI 6.0 polygon source assets and hashes before comparing `glacier`, `RGIId`, or `d_glac_m` columns for the 101 candidate zones.
4. **Terrain provenance:** the footprint replay uses the author-deposited prepared DEM and deliberately preserves the author's no-datum-transformation code path; the physical DEM-to-radarGrid vertical-reference mismatch remains a caveat, not a correction.
5. **Detection skill:** keep `HAZARD_DETECTION_STATUS=NOT_EVALUATED`; the candidate screen's recovered inventory is not an operational hazard detector. Do not merge this branch into `main` as part of the verification exercise.


## Superseding Run 40170290176 update — 2026-10-25

P2 is no longer pending: the exact-author raw replay passed all 15 P2 fields (5 crown R, 5 background R, 5 resolved flags) at archived precision. The full-footprint runner also passed the three aggregate raster comparisons, all 106 candidate-inventory rows and all 101 Table S7 numeric rows under declared precision/tolerances. At the time of Run 40170290176 the 15 displacement-null numeric comparisons were still pending; that interim state is superseded by the derived-field replay in [Run 40219393283](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283), which matches all 15 fields at archived precision. Original displacement-null generator/draw identity, source crown-vector identity and exact RGI 6.0 glacier overlay remain unresolved; see [the full evidence report](FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md) and [the displacement-null replay report](DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md).


## Displacement-null output replay — 2026-10-25

The deterministic reconstruction in DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md and its machine-readable companion DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.json process the five deposited displacement fields. All five crown medians, null medians and percentiles match the table at stored precision. Numeric Table S4 coverage is 95/95 when combined with the P1, P2 and conditional core checks; the successful workflow replay is Run 40219393283. The exact displacement-null generator and original draw/rejection history remain unverified; that is a source-provenance caveat, not a numeric mismatch.
