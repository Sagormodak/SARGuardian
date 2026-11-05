# Know Place Analysis — Raw Replay and R-Policy Audit

**Branch:** `feat/know-place-analysis`  
**Main-branch changes:** none  
**Evidence date:** 2026-10-24  
**Source replay:** [Run 40006999011](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40006999011)  
**Saved-array reanalysis:** [Run 40015023621](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015023621)  
**Validation:** [Run 40015023775](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015023775)

## 1. What has actually been executed

The isolated raw replay downloaded all five candidate GOFF HDF5 products, verified byte-size and SHA-256 against the historical Dynamic AOI products, read the raw layer2 offset/SNR arrays and geometry metadata, computed per-pair metrics, and uploaded its derived outputs. The workflow removed its temporary raw HDF5 files only after verified Drive retention; raw HDF5 is not included in the derived analysis archive.

- Raw-replay artifact ID: `12524093978`; archive: `know-place-analysis-40006999011-1`.
- Raw-replay downloaded artifact ZIP SHA-256: `ef25282bab6d143242b3269c41c4b3e9208db7d336d4dda14a85febf4e4f7f89`.
- Source analysis report SHA-256: `20863b27529245ded25d972679845401f22407bd82d0ff69c3b39b44745f1636`.
- The reanalysis workflow downloaded that existing report and its five NPZ diagnostic arrays. All five NPZ SHA-256 values matched the source report; the reanalysis did not download or reprocess raw HDF5.
- Saved-array reanalysis artifact ID: `12528206900`; ZIP SHA-256: `5d9a63e3338ba040fdfbac968604b2a215f09fedb4382d9b52ca1e8c126c4a31`.
- Reanalysis report SHA-256: `45c23917e446628db4fff96e6e7c47925ccebde0805da9f6554b1fdb88a6e7f4`.
- Drive remote verification for the reanalysis report and summary: **PASS, 2 files**.

These hashes identify the specific evidence and derived arrays used for this audit. The NPZ files contain derived, corrected arrays, not source GOFF inputs.

## 2. Exact candidate products used

The five source products are pinned by granule identity and by source bytes from the earlier verified Dynamic AOI run.

| Pair | Previous product ID | Release | Source SHA-256 |
|---|---|---|---|
| 20 Jun → 2 Jul | GOFF-003 | X05026 | `df870327e662b8d4c49d242437f7a2b6e44e3c7bdf99169910c6020689736918` |
| 2 Jul → 14 Jul | GOFF-007 | P05023 | `8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c` |
| 14 Jul → 26 Jul | GOFF-011 | P05023 | `ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313` |
| 26 Jul → 19 Aug | GOFF-015 | P05023 | `45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f` |
| 19 Aug → 31 Aug | GOFF-019 | P05023 | `4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371` |

The first product is currently supported by ASF provisional-collection evidence but its X05026 processing variant has not been confirmed against the paper author's exact inputs. All five product identities are valid candidates for this study; they must **not** be called author-identical products until the original supplement/input manifest is independently verified.

## 3. Per-pair measurements

The measurements below use the published coordinate bounds as a **rectangular crown approximation**, not the exact author crown polygon. Components were projected from GOFF layer2 using the per-product geometry arrays; the vertical component was assumed zero; quality gates were SNR ≥ 5 and projected horizontal magnitude ≤ 10 m, rejecting rather than clipping gross outliers. Component-wise background offsets were removed using valid reference-box pixels outside the crown.

| Pair | Valid crown pixels | Crown median horizontal magnitude | Mean-vector magnitude | Mean-vector azimuth | Crown R, ≥1 neighbour | Box R, ≥1 neighbour | Crown R, ≥25 neighbours |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20 Jun → 2 Jul | 283 | 0.994 m | 0.915 m | 293.82° | 0.735 | 0.638 | 0.737 |
| 2 Jul → 14 Jul | 294 | 0.541 m | 0.684 m | 279.70° | 0.586 | 0.732 | 0.593 |
| 14 Jul → 26 Jul | 296 | 0.295 m | 0.746 m | 274.00° | 0.586 | 0.746 | 0.535 |
| 26 Jul → 19 Aug | 292 | 0.966 m | 1.722 m | 277.79° | 0.853 | 0.681 | 0.555 |
| 19 Aug → 31 Aug | 195 | 0.328 m | 0.693 m | 276.84° | 0.489 | 0.581 | 0.380 |

A large displacement is not by itself a detection. The post-event 19–31 August pair has much lower crown directional coherence than the 26 July–19 August pair; it must be interpreted as a quality/decorrelation-sensitive interval, not treated as a clean movement continuation.

## 4. R-policy defect and independent recomputation

The first report set `coherence_minimum_valid_cells=25`, which requires every one of the 25 cells in a 5×5 neighbourhood to contain a usable direction. The preprint defines a 5×5 mean resultant length but does not specify that minimum-neighbour rule. The strict 25/25 rule therefore removed many otherwise eligible centre pixels and made R materially sample-dependent.

For 26 July–19 August:

- All eligible crown centres (minimum 1 valid direction in each 5×5 window): R = **0.853**, `n=292`.
- On the common pointwise displacement window 0.17–2.75 m: crown R = **0.869**, `n=150`; background-box R = **0.686**, `n=1626`.
- With the earlier 25/25 rule on that same displacement window: crown R = **0.757**, `n=84`; background-box R = **0.673**, `n=458`.

The paper reports roughly **R = 0.869 for 147 crown pixels** on its common-motion window and background R roughly **0.693** on its published comparison sample. This is close in scalar R, but the crown counts and background sample differ. The mismatch is evidence of a sample-mask/geometry difference, not a reason to tweak values until they match.

The current primary implementation uses a **minimum of one valid direction**, because that does not add an undocumented 25/25 rule, and records sensitivity for minimum counts `1, 5, 10, 15, 20, 25`. This is an explicit, versioned analysis policy—not a claim that the preprint specified “minimum 1”.

## 5. Displacement parity and the control-statistic mismatch

For 26 July–19 August, the method computes:

- Crown median horizontal displacement magnitude: **0.966 m**, versus the published approximately **0.96 m**.
- Crown mean-vector magnitude: **1.722 m**, versus approximately **1.72 m**.
- Mean-vector azimuth: **277.79°**, versus approximately **278°**.

These three scalar summaries are close to the paper's rounded target for this bounding-box crown approximation.

Our current exploratory circular controls yield control median displacement about **0.128 m** and a crown rank of about **96.08th percentile**. The paper reports control median about **0.14 m** and crown rank about **94.7th percentile**. **These percentile values are not directly comparable:** the crown geometry is approximate, the exact product variants are not confirmed against the author inputs, and our explicitly documented circular-control sampling is not verified to match the author-supplement control method. The 96.08th percentile must not be interpreted as a hazard alarm or used to overturn the author's stated conclusion.

## 6. Scientific gate status

- **Structural processing:** PASS for the five-pair run.
- **Input integrity:** historical source sizes/SHA-256 matched for all five candidate files; NPZ hashes matched the source report during reanalysis.
- **Metric computation:** completed for all five exact date intervals.
- **Directional-coherence sensitivity:** computed and separately archived; the 25-neighbour rule is no longer the primary policy.
- **Paper reproduction:** **BLOCKED** — exact author crown geometry, source-product variants, and the author's exact spatial-control/golden outputs are not independently verified.
- **Hazard detection:** **NOT EVALUATED**. No early-warning or landslide-detection claim is supported by this workflow.

## 7. Next acceptance gates

1. Obtain and hash-check the author's exact crown polygon and supplemental control scripts/rasters or statistic tables, if publicly available.
2. Confirm whether the X05026 candidate product is the exact product version used for the 20 June–2 July published comparison; if not, run a labelled variant-sensitivity comparison.
3. Make the control sampler identical to the author's method before comparing percentiles. Keep sensitivity outputs even if they do not match.
4. Re-run a new source analysis only after those method inputs are settled; compare all five intervals, not only the interval closest to 0.96 m.
5. Keep every change on `feat/know-place-analysis`; no merge into `main` is authorized.
