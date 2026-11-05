# Author-exact P05023 raw replay and last-run audit

**Run:** [40114703362 — SARGuardian AOI WKT E2E (safe branch dispatcher)](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362)  
**Started:** 2026-10-24 17:07:42 UTC · **Completed:** 17:09:48 UTC · **Conclusion:** success  
**Run commit:** `3b01615c7dfce923efc241eb45af2133c05fd5fb` on `feat/know-place-analysis`  
**Status-correction validation:** [40115947045](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40115947045), commit `5354a344ce19eac652fa8102c790fce18e18ec13` — 217 tests passed; all eight workflow YAMLs parsed; pinned actionlint v1.7.12 checksum and semantic checks passed.  
**Main baseline:** `2218dfeb73353080d8d94bd733d9e7bd9a848886` (unchanged).

## What the run actually did

The dispatcher selected `run_profile=author-exact-p05023`, `analysis_mode=exploratory`, geometry height 5151 m, seed 260826 and 1,000 circular-control draws. The separate generic AOI/date measurement-engine job was skipped because this run selected the exact-author profile; do not describe this run as a generic WKT/date run.

The explicit raw-source consent gate passed. Earthdata and Google Drive credential checks passed. All five exact author-selected P05023 GOFF HDF5 products were downloaded, assigned actual byte counts/SHA-256 hashes, checked for HDF5/granule identity and validated against the same source-grid contract. The analyzer exited 0 and produced metrics for all five pairs. Derived outputs and Drive receipts were retained. The log explicitly records that temporary raw HDF5 files were removed **after** remote Drive verification passed.

## Exact source-byte receipts

Source-manifest SHA-256: `69947d44fa7d332bc02b2c4c79143ab00eec34bf8e3acc5c3198793b9212d1b5`. The full source manifest and pair report are inside the GitHub artifact and the Drive-derived bundle.

| Interval | CMR granule concept ID | Downloaded bytes | SHA-256 |
|---|---|---:|---|
| 2026-06-20 → 2026-07-02 | `G4248299988-ASF` | 1,090,519,040 | `d3670f0504576feac52f75a7e8f0ff12f5f5c2ef676a0329a16f66cb91300f05` |
| 2026-07-02 → 2026-07-14 | `G4261120661-ASF` | 1,090,519,040 | `8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c` |
| 2026-07-14 → 2026-07-26 | `G4264302811-ASF` | 1,092,616,192 | `ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313` |
| 2026-07-26 → 2026-08-19 | `G4286855543-ASF` | 1,101,004,800 | `45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f` |
| 2026-08-19 → 2026-08-31 | `G4296814366-ASF` | 1,098,907,648 | `4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371` |

**Total raw payload acquired:** 5,473,566,720 bytes. Authenticated preflight passed 5/5 and estimated the same total. Each grid passed **4311 × 4230**, **EPSG:32645**, X posting +80 m and Y posting −80 m; the validator also compares the five coordinate axes. Counts are separate: downloads 5/5, source SHA-256 pins 5/5, grid validations 5/5. No X05026 product was used as a replacement.

## Five-pair exploratory measurements

These measurements were computed from exact P05023 source bytes using a **bounding-box crown approximation**. They do not establish author-method equivalence.

| Pair | Displacement-valid crown pixels | Median horizontal magnitude | Mean vector magnitude | Mean-vector azimuth | Median directional coherence R |
|---|---:|---:|---:|---:|---:|
| 2026-06-20 → 2026-07-02 | 283 | 0.994312 m | 0.914760 m | 293.821° | 0.734706 |
| 2026-07-02 → 2026-07-14 | 294 | 0.541107 m | 0.683752 m | 279.702° | 0.585831 |
| 2026-07-14 → 2026-07-26 | 296 | 0.295299 m | 0.745773 m | 273.998° | 0.586338 |
| 2026-07-26 → 2026-08-19 | 292 | 0.966063 m | 1.722246 m | 277.793° | 0.852850 |
| 2026-08-19 → 2026-08-31 | 195 | 0.327841 m | 0.693193 m | 276.835° | 0.489429 |

For 2026-07-26 → 2026-08-19, the computed crown median magnitude is **0.966063 m**, mean-vector magnitude **1.722246 m**, azimuth **277.793°**, median magnitude rate **0.040253 m/day**, and median directional coherence **R=0.852850**. These are numerically close to paper targets (0.96 m, 1.72 m, 278°, about 4 cm/day and R about 0.87). The report's comparison status is nevertheless `NOT_COMPARABLE_EXACT_CROWN_GEOMETRY_UNVERIFIED`.

Other target-pair diagnostics: reference-box median coherence is 0.681326; the bounding-box crown has 292 valid displacement pixels; the deterministic circular-control experiment accepted 638/1,000 draws, with a control median-of-medians 0.127812 m and displacement empirical percentile 96.0815. These control statistics are **not comparable** to the author's 94.7th percentile because equivalence to the supplementary control-generation method has not been established. A pointwise 0.17–2.75 m window gives R=0.868995 on 150 crown centres, but the report labels it a sensitivity diagnostic, not the matched-control sample.

## Why paper reproduction is still blocked

- The crown is the published WGS84 rectangle represented as a bounding-box approximation, not a verified author-supplement editable crown polygon. Exact pixel-mask parity is not established.
- The control sampler uses deterministic circular controls and is not shown equivalent to the author's supplementary sampling algorithm.
- Full-footprint author screen outputs, golden tables/masks and cross-version source/manuscript mapping have not been regenerated and compared.
- The archived terrain workflow's EGM2008/geoid versus ellipsoidal-height concern remains unresolved. This ROI measurement did not resolve or correct that vertical-reference question.
- No hazard-detector evaluation, operational alarm, or prediction-skill result was produced.

## Derived retention and artifact integrity

GitHub artifact `know-place-author-exact-40114703362-1`: ID `12567509703`, 830,510 bytes, SHA-256 `d49b6aa10da27138de6b8b8f2af6a4b5d3ffd86a8ccb87cef7765e3c597a0b59`. I downloaded and inspected the ZIP. It contains five per-pair diagnostic NPZs, CSV, analysis report, source/preflight manifests, config/provenance, status and Drive receipts; it contains **no raw HDF5**.

Drive derived-only bundle: `author-exact-derived-results.zip`, 414,897 bytes, SHA-256 `c82f68a11ff00f22aa5cb280116c319948c14a17bf07c8d7d3795c0f2c9aa28e`, [open in Drive](https://drive.google.com/file/d/1mz14C9s0KXqgMcVczrTM-aPmzvSjDg9f/view?usp=drivesdk). The uploaded bundle receipt and receipt-copy both report `remote_verification=PASS` and `raw_product_uploaded=false`. The workflow's cleanup step reports `RAW_HDF5_REMOVED_AFTER_DURABLE_DRIVE_VERIFICATION=true`.

## Status-label bug found in the historical artifact, and fix

The artifact from original run commit `3b01615c7dfce923efc241eb45af2133c05fd5fb` contains a status-label inconsistency: analyzer stdout logs `BLOCKED_CROWN_GEOMETRY_NOT_AUTHOR_SUPPLEMENT_VERIFIED`, but the wrapper overwrote the JSON report/status/provenance with `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`. That stale label incorrectly implied the raw bytes were still missing even though five exact P05023 files had just been hashed.

The feature-branch fix now records raw source identity independently as `FIVE_EXACT_AUTHOR_SOURCE_HASHES_PINNED`, preserves the analyzer's crown/method blocker, and makes the final workflow gate check source identity and paper-method parity separately. The canonical post-download paper status is `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Regression validation [run 40115947045](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40115947045) passed **217 tests in 2.62 s**, eight YAML parses and pinned actionlint checks. The historical artifact is immutable and still contains its pre-fix status label; we did not re-download 5.47 GB merely to rewrite that historical artifact.

**Current interpretation:** source-byte identity 5/5 PASS; HDF5/grid checks 5/5 PASS; exploratory metrics computed 5/5; paper reproduction `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection `NOT_EVALUATED`. Main is unchanged; no merge was made.
