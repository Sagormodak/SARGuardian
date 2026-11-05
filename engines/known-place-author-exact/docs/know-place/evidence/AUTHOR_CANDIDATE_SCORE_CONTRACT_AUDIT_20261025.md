# Author candidate-score processing-chain audit — 2026-10-25

## Correction to the initial interpretation

The initial audit compared the deposited final candidate `score` column against the provisional expression in `code/wide_screen.py` and called the difference a possible source/output conflict. That interpretation was incomplete and is superseded by this note.

The Zenodo archive includes a later explicit post-processing step, `code/fix_zonal_attrs.py`. This step intentionally replaces the provisional centroid-derived `n_epochs`, `anom_m`, and `score` after `candidate_attributes.py` has added residual-coherence and terrain attributes. The final inventory is therefore expected to differ from the *provisional* score formula in `wide_screen.py`.

Source archive: `bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip`, SHA-256 `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`.

## Exact script chain and pinned identities

| Archive member | SHA-256 | Role |
|---|---|---|
| `code/wide_screen.py` | `60e4238b9a10510f52a4673939a9708bf513d8bae460ba797d2dd27a1357d7c9` | Produces components and provisional centroid-sampled `n_epochs`, `anom_m`, `R`; initial score is `n_epochs * anom_m * R`. |
| `code/candidate_attributes.py` | `dde30645bed46f7b44f6d0469c8224e1b8f630726fd9849f11471880edc6e196` | Adds per-zone pooled hit-pixel motion vectors, raw and residual coherence (`R_raw`, `R_res`), terrain directions, `d_downslope`, glacier fields and diagnostics. Does not finalize the score formula. |
| `code/fix_zonal_attrs.py` | `3614d1f632e35dbcdecab8389f38e50674a087813cbefdaa2b8c027b0ebe18cb` | Re-rasterizes current candidate polygons; replaces `n_epochs` with the maximum epoch count within each zone, replaces `anom_m` with mean finite zonal anomaly rounded to 3 decimals, computes final `score = n_epochs * anom_m * R_res`, computes `quality = (R_res >= 0.75) & (d_downslope < 45)`, then re-sorts by final score. |
| `inventory/candidates_attributed.csv` | `519b527fbbbde7ab8a78365e5f5ee39e66837fd5ea942b8196d4368c1e1e3f9d` | Deposited final attributed inventory after the zonal post-processing chain. |

The `fix_zonal_attrs.py` header explicitly says that it must run after `candidate_attributes.py`, verifies that the attributed and screen candidate counts still match, and explains why centroid sampling can yield impossible `n_epochs < 2` values on concave zones.

## Correct interpretation of the score arithmetic

The earlier 0/106 vs 106/106 arithmetic was not a valid end-to-end source/output inconsistency test because it evaluated the *final* zonal values against the *provisional* centroid score formula. That apparent conflict is explained by the pinned downstream script above; it is not evidence that the archive contradicts itself.

I independently recalculated the final arithmetic directly from the hash-verified CSV bytes: **106/106** final scores equal `n_epochs * anom_m * R_res` at full stored numeric precision (absolute difference within 1e-8 for the comparison), and **106/106** `quality` flags match `R_res >= 0.75 and d_downslope < 45`. There are 106 candidate rows, 101 `quality=True` rows, and 101 rows in Table S7. This checks the deposited CSV's internal arithmetic; it does not by itself prove the raw-GOFF screen regenerates those values.

The authoritative final-chain formula to reproduce is:

`n_epochs = max(n_epochs_flagged inside the candidate polygon)`

`anom_m = round(mean(finite mean_anomaly_m inside the candidate polygon), 3)`

`score = n_epochs * anom_m * R_res`

`quality = (R_res >= 0.75) and (d_downslope < 45 degrees)`

Here `R_res` is populated by `candidate_attributes.py` from pooled finite residual-coherence observations on hit pixels over the five intervals. The screen-stage `R` is a different, provisional centroid-sampled value and remains an independent inventory column; it is not the factor in the final score.

The end-to-end runner in `tools/know_place/author_footprint_replay.py` now reproduces this chain: it retains provisional centroid `R`, calculates zone-max `n_epochs` and zone-mean `anom_m`, builds final score from pooled zonal `R_res`, and keeps the pure directional-alignment flag separate from the combined author `quality` flag.

## 106 candidates versus 101 quality-passing zones

The archive contains **106** candidate rows. The final `quality` expression is true for **101** rows, and `tables/TableS7_all_validated_zones.csv` contains those 101 validated zones. The runner compares these as separate targets:
- all 106 rows and final attributes in `inventory/candidates_attributed.csv`, including the final score and author quality flag;
- the 101 `quality=True` features against Table S7 at displayed numeric precision.

A pure downslope-direction match is not itself identical to the final author quality flag, because the latter also requires `R_res >= 0.75`. The runner and workflow keep those counts separately named.

The exact RGI 6.0 polygon assets are not packaged in this archive. The current comparator does not independently reproduce `glacier`, `RGIId`, or nearest-glacier distance.

## Validation boundary

The code-chain correction is based on direct inspection of the verified author archive and does not require raw GOFF downloads. The updated runner/tests and strict workflow gate are being validated on `feat/know-place-analysis`; **no new full-footprint raw replay has been launched in this follow-up**.

A score-formula unit test is not itself numerical source replay. Full-footprint parity remains unverified until an explicitly authorized run independently generates:
- all three archived full-footprint rasters (cell-by-cell);
- all 106 final candidate rows and their final attributes/score/quality;
- all 101 Table S7 quality-passing rows at the published precision.

Even if these screen outputs match, the archive's displacement-null draw-level generator remains unavailable in the supplied package, so the three displacement-null Table S4 cells per interval must remain unverified unless the missing author source evidence is found. Hazard detection precision, recall, false-alarm rate, lead time and operational warning skill remain `NOT_EVALUATED`.

No change to `main` is authorized or intended. All work remains isolated on `feat/know-place-analysis`.
