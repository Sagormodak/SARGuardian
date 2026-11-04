# RiverShift — Final readiness, scientific validation and score-sheet evidence

**Audit date:** 2026-11-05  
**Scope:** RiverShift only. No Landslide / Find Displacements / Known Place Analysis changes are included.  
**Overall status:** RiverShift's current code is merged to both main branches, post-merge CI is green, the retained Run #36 COGs have been replayed successfully through the current worker, and the latest Dynamic frontend is live on the production alias. Independent scientific validation is **not complete**; the release remains **PROVISIONAL / NO_SCORE** for Run #36 because no eligible independent water reference or stage-matched bankline truth was available.

## Executive decision

The defensible description is:

> RiverShift is a reproducible NISAR GCOV screening workflow that maps observed-date open-water and provisional river-change candidates, retains source provenance, and reports spatial-overlap diagnostics. Independent reference validation and stage-matched geomorphic confirmation remain pending.

Do not claim field validation, VERIFIED status, or a full accuracy score. CI success, Google Drive checksum verification and a computed overlap report are not independent scientific accuracy assessments.

## Merged code and repository state

### Backend — `moshiour0/SARGuardian-backend`

Latest RiverShift worker/code merge: `3ce722233f2177d36762b62127df527d1351ddc8`. The judge guide and this readiness report were updated after that code merge.

| PR | Merge commit | Effect |
|---|---|---|
| #149 | `9bfd7982ba61c71104f8e5ece8fa9392509df601` | Judge guide and Run #36 evidence; records exact retained outputs and failed/no-score reference attempts. |
| #150 | `6c4e1139e54af62931f374142450dbe84ae64145` | Independent-reference workflow now defaults to the FastAPI origin, not the frontend host; result summary records the first post-event acquisition and day gap. |
| #151 | `f6b919e33e612fdeea2641d9ee771c9257e11c4b` | Real GCOV worker invokes full-resolution candidate mask overlap audit, retains report, includes source + preview overlap in summary, and fails closed on invalid masks/grid or erosion/deposition conflict. |
| #152 | `9425d0eefa7b74b40d77867dfe9234ce689d0d77` | Corrects report path and documents why Run #36 has no retroactive full-resolution audit. |
| #154 | `831ac7c8b3e3119062bc3bde12ef8687e55d6a65` | Adds a retained Run #36 replay workflow using exact retained COG artefacts; first iterations exposed workflow bootstrap/path issues, subsequently corrected. |
| #155 | `782f3660dcd564613cac62f66acf572c4c7a8074` | Recognises OPERA DSWx-S1 WTR class 254 (ocean mask) and retains it as NoData; extends the class semantics and integration tests. |
| #156 | `c8e33b94531686f55cec75254ff325e58532387f` | Replaces any-positive coarse polygonisation with >50% occupancy polygons plus bounded sparse MultiPoint markers; excludes markers from preview area/Jaccard. |
| #157 | `3ce722233f2177d36762b62127df527d1351ddc8` | Forces all change classes onto one shared grid, disables polygon simplification and verifies zero polygon overlap for disjoint masks. |

Latest main checks: RiverShift worker Run [41926825076](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926825076) success; repository retention/streaming regression Run [41926824877](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926824877) success; AOI/static validation Run [41926824752](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926824752) success. Retained Run #36 retrospective replay [41926490047](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926490047) also completed successfully and uploaded the full mask + preview QA artifact.

### Dynamic — `moshiour0/SARGuardian_Dynamic`

Latest Dynamic main commit: `a038596fac1ed0c1a661053488a283a4ca62260e`.

| PR | Merge commit | Effect |
|---|---|---|
| #77 | `8f3ac1d7579d824e5bc8003d450f1dfb857457f9` | Separates observed-date open-water features from new-water candidates; candidate and observed-water visibility switches now operate independently. |
| #78 | `d52f47893266cde11116ab18a04c96ab2dfa4d2b` | Missing overlap report displays **NOT MEASURED · NOT ZERO**; event result displays actual first post-event NISAR observation and day gap. |
| #79 | `ce99732937fb79fe48326937879439f85a66ac6b` | Fixes API-origin fallback: local development keeps localhost; preview/production without an explicit override uses the deployed FastAPI host. |
| #80 | `a038596fac1ed0c1a661053488a283a4ca62260e` | Displays sparse preview MultiPoint candidates as class markers and labels overlap columns as polygon-only. |

Latest main frontend Run [41925071451](https://github.com/moshiour0/SARGuardian_Dynamic/actions/runs/41925071451): frontend type-check/build, lint and unit tests all success. PR #80 backend contract tests also passed.

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

### Historical Run #36 limitation and retrospective replay

The **original** Run #36 artifact manifest predates PR #151 and still does not contain candidate_mask_overlap_audit.json. Do not say the original 2026 worker emitted a source-mask overlap report.

A separate checksum-bound replay, [backend Action Run 41926490047](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926490047), downloaded the six retained source COGs and ran the current worker's analysis/QA functions. It completed **successfully** with all six retained COG checksums matching their sidecars. Its report explicitly labels itself RETROSPECTIVE_RECOMPUTED_NOT_ORIGINAL_WORKER_ARTIFACT. It reproduced the three original areas exactly and generated source-mask plus current preview QA artefacts. This is valid retrospective evidence, but it does not rewrite the original Run #36 bundle or automatically populate its original dashboard record. New jobs on main create the overlap reports natively.

## Retrospective Run #36 audit — exact retained COG replay

Evidence: [Backend Action Run 41926490047](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926490047). The workflow downloaded the same six retained GCOV COGs and verified every downloaded file SHA-256 against its retained sidecar before using it. The report status is RETROSPECTIVE_RECOMPUTED_NOT_ORIGINAL_WORKER_ARTIFACT.

**Exact metric reproduction:** all three Run #36 areas matched at the precision retained in the original run summary:

| Metric | Original Run #36 | Retrospective replay | Match |
|---|---:|---:|---|
| Newly water-covered candidate | 17.6721 km² | 17.6721 km² | Exact |
| Persistent erosion candidate | 1,244.230 ha | 1,244.230 ha | Exact |
| Persistent deposition candidate | 5,078.140 ha | 5,078.140 ha | Exact |

**Full-resolution source-mask overlap:** common valid support was 5,581,042 pixels (62.0125% of the full raster grid). Erosion/deposition intersection was **0 pixels** (Jaccard 0); deposition/new-water intersection was **0 pixels**; erosion/new-water intersection was **61,518 pixels** (Jaccard 0.256725). The latter pair is based on different three-date Otsu thresholds/date windows (flood threshold −11.75165 dB; morphology threshold −12.01393 dB) and is not an erosion/deposition exclusivity violation. It must nevertheless remain visible for reviewer interpretation; no automatic accuracy conclusion follows.

**Current preview QA:** all three classes used one 293×384 grid with 89.557 m display cells. Erosion/deposition polygon intersection was **0 km²** (Jaccard 0). Erosion/new-water preview polygons intersect by 0.48794 km²; this is display-only and reflects the separate temporal/threshold basis. Deposition/new-water polygon intersection is numerical round-off (~4.2×10⁻¹⁴ km², effectively zero). Each class rendered 8,000 sparse marker points; the remaining sparse cells were counted as omitted from display (erosion 23,176; deposition 36,262; new-water 28,751). The full-resolution masks and pixel counts were not reduced or changed.

Downloadable evidence: [Retrospective Run #36 source-mask and preview QA ZIP (workflow artifact)](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41926490047).

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

- Dynamic production commit `a038596fac1ed0c1a661053488a283a4ca62260e` is READY and assigned to the public alias `sar-guardian-dynamic-lilac.vercel.app`. The production /river-shift page returned HTTP 200.
- The live production JavaScript bundle was fetched and inspected: it contains the sparse MultiPoint marker style, polygon-only overlap labels, and `VITE_SARGUARDIAN_API_URL=https://sarguardian-backend-api.vercel.app`. The preview API-origin fix is therefore present in the current production bundle; the explicit production URL remains the selected origin.
- The public FastAPI health endpoint `https://sarguardian-backend-api.vercel.app/health` returned HTTP 200 with service status `ok`.
- Dynamic frontend post-merge Run `41925071451` and backend post-merge Runs `41926825076`, `41926824877`, `41926824752` passed. Backend engine changes are deployed through the backend GitHub Actions worker; the FastAPI hosting commit was not changed by this UI/worker QA set.
- No Vercel production promotion was needed after the Git-linked main deployment became READY. No Landslide, Find Displacements or Known Place workflow was modified.

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

**Final statement:** RiverShift's current main code, CI and production UI have been verified; a checksum-bound replay of Run #36 reproduced every reported area exactly and computed the full-resolution and preview overlap diagnostics without modifying the original result bundle. Erosion/deposition masks and their shared-grid preview polygons are disjoint. Cross-class erosion/new-water overlap remains visible because those screens use distinct thresholds/date comparisons and requires interpretation. The project remains **PROVISIONAL / NO_SCORE** until an eligible independent water reference and stage-matched bankline/field evidence are available.
