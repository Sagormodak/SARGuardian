# RiverShift — Final readiness, scientific validation and score-sheet evidence

**Audit date:** 2026-11-05  
**Scope:** RiverShift only. No Landslide / Find Displacements / Known Place Analysis changes are included.  
**Overall status:** Engineering and reproducibility have materially improved. Independent scientific validation is **not complete**. Latest frontend code is built and verified on a preview URL, but the production aliases have not advanced to the latest main commit.

## Executive decision

The defensible description is:

> RiverShift is a reproducible NISAR GCOV screening workflow that maps observed-date open-water and provisional river-change candidates, retains source provenance, and reports spatial-overlap diagnostics. Independent reference validation and stage-matched geomorphic confirmation remain pending.

Do not claim field validation, VERIFIED status, or a full accuracy score. CI success, Google Drive checksum verification and a computed overlap report are not independent scientific accuracy assessments.

## Merged code and repository state

### Backend — `moshiour0/SARGuardian-backend`

Latest audited main commit: `9425d0eefa7b74b40d77867dfe9234ce689d0d77`.

| PR | Merge commit | Effect |
|---|---|---|
| #149 | `9bfd7982ba61c71104f8e5ece8fa9392509df601` | Judge guide and Run #36 evidence; records exact retained outputs and failed/no-score reference attempts. |
| #150 | `6c4e1139e54af62931f374142450dbe84ae64145` | Independent-reference workflow now defaults to the FastAPI origin, not the frontend host; result summary records the first post-event acquisition and day gap. |
| #151 | `f6b919e33e612fdeea2641d9ee771c9257e11c4b` | Real GCOV worker invokes full-resolution candidate mask overlap audit, retains report, includes source + preview overlap in summary, and fails closed on invalid masks/grid or erosion/deposition conflict. |
| #152 | `9425d0eefa7b74b40d77867dfe9234ce689d0d77` | Corrects report path and documents why Run #36 has no retroactive full-resolution audit. |

Latest main checks: RiverShift worker Run #281 **255 passed** (170 warnings); repository retention/streaming regression Run #905 success; AOI/static validation Run #684 success.

### Dynamic — `moshiour0/SARGuardian_Dynamic`

Latest audited main commit: `d52f47893266cde11116ab18a04c96ab2dfa4d2b`.

| PR | Merge commit | Effect |
|---|---|---|
| #77 | `8f3ac1d7579d824e5bc8003d450f1dfb857457f9` | Separates observed-date open-water features from new-water candidates; candidate and observed-water visibility switches now operate independently. |
| #78 | `d52f47893266cde11116ab18a04c96ab2dfa4d2b` | Missing overlap report displays **NOT MEASURED · NOT ZERO**; event result displays actual first post-event NISAR observation and day gap. |

Latest main Run #309: frontend type-check/build, lint and unit tests all success. PR #78 backend tests also passed.

## Current implemented output classes

1. **Observed-date open-water extent:** low-backscatter water-screening mask for one actual NISAR acquisition date.
2. **New-water candidate:** baseline not-water to water on the selected event-proximal comparison date; relative to the chosen date pair, not automatically a flood extent.
3. **Persistent erosion candidate:** baseline land classified as water in both later morphology observations.
4. **Persistent deposition candidate:** baseline water classified as land in both later morphology observations.

**Not implemented as validated outputs:** exposed sandbar/char, persistent char, sediment volume, signed bankline migration, avulsion/cutoff, flood depth or flood cause. The UI intentionally leaves exposed bar/char unavailable. Do not alias deposition to exposed bar, or call a water/land transition a measured bank movement.

Possible future candidates—only after separate methods and reference datasets exist—include exposed bar/sandbar, persistent versus temporary bars, vegetation colonisation/stabilisation, channel-centreline/thread migration, channel width/sinuosity, and channel avulsion.

## Full-resolution overlap audit — important fix

The overlap algorithm existed before this audit, but the real worker did not call it. PR #151 closed that integration gap.

For every new GCOV job after PR #151, the worker reads the authoritative full-resolution:
- `erosion_candidate_mask.tif`
- `deposition_candidate_mask.tif`
- `newly_water_covered_mask.tif`

It requires exact common CRS, affine transform, width and height; checks binary values; records valid support and source SHA-256; calculates per-class pixels, pairwise intersections/unions/Jaccard/overlap fraction and triple intersection on common valid support. Any erosion/deposition overlap on shared valid pixels fails the job. New-water may overlap morphology classes because its temporal comparison differs; that overlap requires date-aware interpretation and is not automatically an error.

The report is retained as:

`outputs/quality-assurance/candidate_mask_overlap_audit.json`

The job summary exposes `candidate_overlap_audit` and `preview_geometry_overlap`. The preview is lower-resolution display geometry: aggregation can expand sparse patches and create apparent overlap. Compare it with the source-mask report; never calculate area or accuracy from preview GeoJSON.

### Historical Run #36 limitation

Run #36 predates PR #151. Its artifact manifest does not contain `candidate_mask_overlap_audit.json`, and its summary has no full-resolution pairwise overlap metrics. No retroactive audit of its private masks was performed. The UI therefore shows **NOT MEASURED · NOT ZERO** for missing historical metrics. A fresh job on the post-PR #151 worker is needed to populate the overlap panel.

## Retained real-data example — Run #36

Evidence: [Backend Action Run #36](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41803576163).

- Six actual NISAR GCOV dates: 2026-06-30, 2026-07-12, 2026-07-24, 2026-08-17, 2026-08-29 and 2026-09-10.
- User-supplied event date: 2026-07-28.
- First qualifying post-event acquisition: 2026-08-17 — **20 days after** the supplied event date.
- Newly water-covered candidate: **17.6721 km²**.
- Persistent erosion candidate: **1,244.230 ha**.
- Persistent deposition candidate: **5,078.140 ha**.
- Supabase artifact ledger confirms recorded outputs' remote Drive checksum verification PASS.

Those are provisional candidate areas for that AOI, acquisitions, threshold and date window. They are not field-validated area, sediment volume, signed bank displacement, event-peak flood extent or exposed population. The 20-day observation gap means 17 August is not an event-peak or same-stage measurement.

## Independent validation attempts — why there is no accuracy score

### OPERA DSWx-S1 V1

Retained-run replay attempts #13–#16 ended `NO_MATCH_NO_SCORE`. 307 OPERA DSWx-S1 granules intersected the AOI across the collection history, but no eligible WTR scene remained in the ±30-day discovery window. No reference raster, common-support comparison, F1 or IoU was produced.

This means **no eligible reference**, not zero accuracy. OPERA WTR semantics matter: class 0 = valid not-water; class 1 = open water; class 3 = inundated vegetation; 250/251/255 = mask/fill. A comparison using only 0 and 1 is open-water agreement, not full inundation validation.

### OPERA RTC-S1

Inventory returned 2,093 AOI granules and 2,020 VV burst groups. Nearest acquisition was 2026-06-26, 52 days before the 2026-08-17 NISAR observation. RTC-S1 is backscatter, not a water label, and cannot be promoted to a water reference.

### Sentinel-2 L2A

The candidate 2026-08-18 scene had reported 97.957% cloud and only 0.1554% common clear support, below the 80% support gate. No optical agreement metrics were published. It is not corroboration.

### FFWC/BWDB gauge context

FFWC historical gauge levels can provide hydrological stage context when the exact date, station and provenance are retained. A point gauge outside the AOI is not a spatial reference mask and cannot produce pixel-wise F1/IoU.

## Scientific literature implications

1. **NISAR GCOV product semantics:** GCOV contains radiometrically/terrain-corrected gamma-0 covariance/backscatter, geocoded to UTM or polar grids. Pixel posting is 10 or 20 m depending on location; adaptive multi-looking varies, so do not describe every cell as independent 10 m ground truth. Preserve the product mask, number-of-looks, term, maturity and granule provenance.  
   Sources: [ASF/NISAR GCOV guide](https://nisar-docs.asf.alaska.edu/gcov/); [NASA/JPL L2 GCOV Product Specification, 2026](https://cumulus.asf.earthdatacloud.nasa.gov/PUBLIC/DATA/NISAR/NISAR_D-102274_RevF_NASA_SDS_Product_Specification_L2_GCOV_w-esigs.pdf).

2. **Low backscatter is not a universal water classifier:** smooth open water often returns low backscatter, but wet/bare soil and radar shadow can create false positives; flooded vegetation can create strong double-bounce returns and false negatives for low-backscatter-only logic. A 2026 Remote Sensing of Environment method combines adaptive thresholding, fuzzy logic, region growing, dark-land estimation and bimodality testing to reduce these errors.  
   Sources: [Jung et al., 2026](https://doi.org/10.1016/j.rse.2026.115326); [Flood mapping under vegetation using single SAR acquisitions](https://www.sciencedirect.com/science/article/pii/S0034425719306029).

3. **River stage is a major confounder:** high-stage versus low-stage planforms can mimic erosion/accretion on both banks. Prefer comparable-stage acquisitions or explicitly condition interpretation on gauge/discharge and uncertainty.  
   Sources: [Langhorst et al., 2023](https://doi.org/10.1029/2022JF006774); [Chadwick et al., 2023](https://doi.org/10.1029/2023JF007177); [Li & Limaye, 2025, Brahmaputra-Jamuna channel threads](https://doi.org/10.1029/2024JF008196).

4. **Bars need their own object/multitemporal method:** track water and adjacent sediment together over time, separating temporary exposure due to stage from sustained bar activation/deactivation. A one-date water-to-land transition is not evidence of a char.  
   Source: [Cecchetto et al., 2026, Beyond Water: Mapping Sediment Bars](https://doi.org/10.1029/2025GL119584).

5. **Bangladesh relevance:** the 1996–2023 Teesta study combines multi-epoch bankline/sandbar mapping with BWDB stage/discharge context. It supports the research question, not direct validation of RiverShift.  
   Source: [Rahman et al., Teesta bankline and sandbar dynamics](https://doi.org/10.3329/dujees.v14i2.87591).

## Required independent validation before VERIFIED

### Water classification
1. Select a reference scene close to a NISAR acquisition with adequate support; retain timestamp, source, projection, class meaning and masks.
2. Use OPERA DSWx-S1 WTR/BWTR, clear-sky Sentinel-2 L2A MNDWI + SCL, UAV/field mapping, or defensible combinations. Keep open water and inundated vegetation separate.
3. Compare only common valid pixels; never convert no-data, shadow or masked pixels to not-water.
4. Compare current Otsu baseline with a held-out fixed threshold and adaptive/edge-informed alternative. Keep training and test reaches/dates independent.
5. Report TP/TN/FP/FN, precision, recall, specificity, F1, IoU, Cohen's kappa, water-area bias, valid sample count and spatial-block uncertainty where independent blocks permit.
6. Current ±2 dB five-scenario sensitivity is deterministic robustness analysis, not a confidence interval or total error budget.

### Erosion/deposition/bankline
1. Obtain independently digitised dated banklines or field/UAV/RTK data at comparable water stage.
2. Define active-channel boundary, reference resolution and positional uncertainty.
3. Generate consistently oriented transects and signed bank-normal distances; declare channelward/landward sign convention.
4. Report signed displacement/rate only when reference permits. Symmetric boundary distance is unsigned difference, not signed migration.
5. Separate real planform change from wetted-width/stage changes and human interventions (embankments, dredging, sand mining, bank protection).

### Exposed bar/char — future
1. Require multiple observations at comparable stage.
2. Define bare sediment using independent optical/SAR evidence and vegetation state.
3. Track objects across time, distinguishing temporary bars, persistent bars and vegetated islands.
4. Validate with high-resolution imagery, field points or channel surveys before enabling a UI toggle or reporting metrics.

### Release states
- Processing/provenance PASS = structural contracts passed.
- Overlap audit PASS = spatial comparison of masks/previews; not accuracy.
- Metrics computed = a reference comparison exists and needs review; not automatically VERIFIED.
- VERIFIED requires traceable reviewer, date, evidence reference, complete provenance and signed verification record.
- No eligible reference = NO_SCORE / PENDING, never zero accuracy and never automatic VERIFIED.

## Deployment status

- Dynamic main `d52f47893266cde11116ab18a04c96ab2dfa4d2b`: GitHub frontend build/type-check, lint and tests success (Run #309).
- Backend main `9425d0eefa7b74b40d77867dfe9234ce689d0d77`: worker, repository regression and AOI checks success (Runs #281, #905, #684).
- The updated Dynamic branch was built as a READY Vercel preview. Preview JS contains the missing-audit disclosure and event-gap note; preview page returned HTTP 200.
- Production aliases remain on earlier READY deployment commit `8f3ac1d7579d824e5bc8003d450f1dfb857457f9`. Further deployment attempts were blocked by the Vercel Hobby daily API deployment quota: `api-deployments-free-per-day`, HTTP 402, retry-after 24 hours. No production alias promotion was attempted. Existing public app and API health remain reachable.

## Score-sheet readiness (20 points each)

The score sheet in the project Library allocates 20 points each to Validity, Relevance, Impact, Creativity and Presentation. Maximum marks cannot be guaranteed by software alone.

| Criterion | Evidence now available | Remaining path to a strong/full score |
|---|---|---|
| Validity | NISAR provenance, acquisition comparability, valid support, checksums, source-mask overlap report for new jobs, no-score safeguards, 255 passing worker tests. | Fresh post-PR #151 real run; suitable independent reference; F1/IoU and uncertainty; stage-matched field/bankline check. |
| Relevance | NISAR GCOV is the primary measurement source; river-change focus; Bangladesh context. | Explain what L-band adds and exactly what the current GCOV workflow can/cannot infer. |
| Impact | AOI-specific provisional candidate areas and maps. | Add sourced assets/population/exposure only from trusted geospatial sources; no unsupported lives-saved/damage-avoided claims. |
| Creativity | Target-free AOI scan, actual-observation playback, independent class filters, transparent overlap QA. | Demonstrate it live; keep bar/char labelled as future work until validated. |
| Presentation | Map, class legend, provenance, result explorer, limitations, judge guide. | Use latest preview or deploy latest main after quota availability; record an end-to-end two-minute demo. |

### Recommended two-minute demo
1. Draw AOI and date window; state that NISAR GCOV—not the basemap—is the analysis input.
2. Show exact selected dates, product comparability and common valid support.
3. Play only actual NISAR dates; no daily interpolation.
4. Toggle erosion, deposition, new water and observed-date water independently; explain exposed bar/char is unavailable pending validation.
5. Show source-mask and preview overlap separately on a fresh post-PR #151 run.
6. Show the no-score explanation for Run #36 rather than invent F1/IoU.
7. Close with the exact external dataset/reference needed for VERIFIED status.

## Primary evidence links
- [Backend repo](https://github.com/moshiour0/SARGuardian-backend)
- [Dynamic repo](https://github.com/moshiour0/SARGuardian_Dynamic)
- [Backend RiverShift worker Run #281](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41906339065)
- [Backend regression Run #905](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41906338942)
- [Backend AOI validation Run #684](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41906338919)
- [Dynamic frontend Run #309](https://github.com/moshiour0/SARGuardian_Dynamic/actions/runs/41907020491)
- [Retained real NISAR Run #36](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41803576163)
- [OPERA retained replay / NO_MATCH_NO_SCORE](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41900559056)
- [Updated RiverShift preview](https://sar-guardi-git-589be8-moshiour-rahman-sarkers-projects-2cebe363.vercel.app/river-shift)

**Final statement:** RiverShift is now in a stronger, reproducible engineering state. The overlay-class bug and missing worker overlap-audit integration are fixed in main. It is not yet independently scientifically validated; historical Run #36 has no full-resolution overlap report; and the latest main UI is not on the production alias because of the Vercel daily deployment quota. These are the remaining evidence gates, not silently passed checks.
