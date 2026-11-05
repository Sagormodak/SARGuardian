# Know Place Analysis — multi-event measurement and detection validation

**Status:** validation design; not yet a validated hazard detector  
**Branch:** `feat/know-place-analysis`  
**Baseline rule:** do not merge this work to `main` from this task  
**Scope:** reproducible NISAR GOFF displacement measurement first; independently evaluated hazard interpretation second

## 1. Scientific objective and claim boundary

Know Place Analysis accepts one user-drawn WGS84 polygon and an inclusive UTC date range. It discovers exact NISAR GOFF products, preserves product identities and maturity, measures pairwise horizontal displacement with explicit geometry and quality policies, creates GIS outputs, uncertainty diagnostics, and a self-contained dashboard, and records a checksum-verifiable run manifest.

This is a **measurement engine**. It does not become an early-warning detector merely because it reproduces a published displacement statistic. The product must report these states separately:

- `STRUCTURAL_STATUS`: inputs, source identities, checksums, grid alignment, masks and output bundle are structurally valid.
- `MEASUREMENT_STATUS`: the requested measurements are computable with sufficient AOI pixel support.
- `PAPER_REPRODUCTION_STATUS`: exact source identities, geometry, analysis masks, method and golden outputs agree with a published procedure within pre-registered tolerances.
- `DETECTION_VALIDATION_STATUS`: independently labelled event and non-event cases have been evaluated without leakage.
- `OPERATIONAL_STATUS`: intentionally blocked until geometry, latency, uncertainty, drift, ground-truth and false-alarm validation gates are met.

No generic threshold may silently be tuned to recover a favourite benchmark value. A valid fast-moving failure may exceed 10 m; generic analysis preserves and flags high magnitudes, while a paper-method request may explicitly choose a versioned rejection policy.

## 2. Authoritative scientific references

1. Meena, S. R. (2026), *NISAR pixel offsets measure but do not statistically resolve pre-failure motion at the 26 August 2026 Bhote Koshi ice–rock avalanche, Nepal*, EGUsphere preprint, DOI: https://doi.org/10.5194/egusphere-2026-5462 . The paper reports 0.96 m median horizontal displacement for 26 July–19 August, but none of its pre-event polygon-scale displacement or directional-coherence comparisons exceeds the 95th-percentile spatial-control threshold. It is a measurement-reproduction benchmark, not a positive early-warning label.
2. ASF/NISAR, *Available NISAR Data*: https://hyp3-docs.asf.alaska.edu/nisar-docs/availability-overview/ . Provisional products start 17 June 2026; the published guide documents an instrument data gap from 27 July 2026 22:03:25 UTC to 10 August 2026 00:55:27 UTC and warns that processing maturity/CRID differences can look like landscape changes.
3. ASF/NISAR, *NISAR Data Products*: https://hyp3-docs.asf.alaska.edu/nisar-docs/products-overview/ . BETA and PROVISIONAL collections differ in processing; cross-maturity differencing must not be treated as physical motion without a separate, independently justified inter-release comparison.
4. Malviya, Garg & Thakur (13 October 2026), *NISAR for Monitoring Glacier Motion*, DOI: https://doi.org/10.65456/iirs.2026.10.3.1 . The IIRS assessment compares NISAR GOFF-derived glacier velocities with ITS_LIVE for four glaciers (Samudra Tapu, Bara Shigri, Hubbard and Malaspina), with differing performance across flow regimes. Use as a candidate cross-sensor/motion-field benchmark only after the precise source dates, masks, projection and table/raster references are obtained; do not assume the paper's summary ranges are pixelwise golden truth.
5. Wang et al. (2026), *Robust sequential pixel offset tracking (RS-POT): A novel monitoring approach for landslides with long-term large deformations*, Remote Sensing of Environment 335, 115275, DOI: https://doi.org/10.1016/j.rse.2026.115275 . Highlights temporal-network/closure concerns when large displacement breaks target correspondence. This supports strict interval-chain identity and cautions against summing pairwise magnitudes into a cumulative displacement.
6. The *ITS_LIVE Regional Glacier and Ice Sheet Surface Velocities, Version 2* reference dataset (NASA NSIDC DAAC), DOI: https://doi.org/10.5067/JQ6337239C96 . It is a multi-sensor, multi-year comparison product; compare only matched spatial and temporal support, and report differences in temporal averaging/measurement physics.

## 3. Pre-registered benchmark tiers

### Tier A — exact method reproduction

**Bhote Koshi source/crown, Nepal.** The first target is the 26 July–19 August 2026 pair and the reported 0.96 m crown median horizontal displacement, mean-vector magnitude around 1.72 m, and mean-vector azimuth around 278°. Before claiming reproduction, obtain and hash the author supplement; extract exact polygon(s), five granule IDs/release variants, source code, derived GeoTIFFs and statistical tables. The currently pinned X05026/PROVISIONAL candidates, rectangle geometry, fixed HAE assumption, and circular controls are *candidate inputs*, not proof of author parity.

Reproduction acceptance requires, at minimum:
- exact granule names, maturities/CRIDs and SHA-256 checksums match the declared input manifest;
- exact author polygon WKT/geometry hash and CRS transform are verified;
- geometry projection, AT/SR units, LOS/along-track convention and sign, valid-mask rules, SNR gate, gross-magnitude treatment, background correction and 5×5 neighbourhood semantics match the author code;
- the control-region generator, random seed/draw order, valid-pixel-count acceptance rule, and percentile/rank convention match the author implementation;
- pixelwise comparison to the five author-derived rasters and the tabulated summary values passes pre-registered numerical tolerances;
- any deliberately different sensitivity policy is labelled as a separate experiment rather than a reproduction pass.

A scalar of 0.96 m within tolerance is necessary but not sufficient.

### Tier B — independent displacement cross-check

**Four-glacier NISAR/ITS_LIVE study:** Samudra Tapu, Bara Shigri, Hubbard and Malaspina. Retrieve the paper's exact supplementary data and product intervals first. Compare matched spatial regions after projecting to compatible horizontal axes and matching temporal units. Report:
- common valid area and valid-data fraction;
- median/percentile speed difference, MAE/RMSE over common pixels, robust slope and intercept;
- vector-direction error only where both speeds exceed a declared minimum, with circular statistics;
- sensitivity to mask erosion, edge pixels, source product maturity and spatial aggregation;
- whether the comparison is between a single NISAR pair and a multi-year ITS_LIVE average. Never describe those as identical measurement windows.

### Tier C — event and non-event screening validation

Create a versioned case registry with independent evidence, not labels inferred from SARGuardian output. Each case must have:
- event ID, event category, published source URL/DOI, publication date and event time/uncertainty;
- author-provided event/source polygon file and hash, provenance/CRS, or explicit label that the polygon is independently digitized;
- AOI-level date window fixed before analysis; known event interval and whether acquisitions are pre-event, co-event or post-event;
- exact source product IDs/maturities/checksums and the data availability window;
- independent reference measurements (GNSS, optical feature tracking, field mapping, inventories, documented failure scar) with reference uncertainty;
- at least one nearby stable/non-event control AOI chosen without looking at the measured output;
- inclusion/exclusion reason, including gaps, insufficient valid pixels and unsuitable geometry.

First registry candidates:
1. Bhote Koshi, 26 August 2026 — main method-reproduction and event-pair decorrelation case. The published paper says pre-event motion was measurable but not statistically diagnostic.
2. Samudra Tapu and Bara Shigri glaciers — slow/moderate-flow measurement checks in the IIRS/ITS_LIVE study.
3. Hubbard and Malaspina glaciers — fast-flow and high-speckle/noise stress tests; expect the same method not to have uniform error across regimes.
4. Published landslide displacement cases with GNSS/UAV/optical reference, e.g. Qantaishan/Qiantaishan landslide in the RS-POT paper and Zhenba landslide in the 2026 multi-source POT study (DOI: https://doi.org/10.3390/rs18101591). Add them only if their image dates and exact source products are actually available through a supported adapter; non-NISAR cases test cross-sensor methodology, not NISAR-only performance.

These candidates form a *case registry plan*, not a claim that the present branch has already processed/validated every case.

## 4. Train/validation/test separation

**Independent-site split requirement:** validation and held-out test registries must have disjoint `site_id` sets. Multiple windows or event cases from one physical site must stay in the same split; changing the case ID is not independence. The evaluator rejects any cross-split site overlap before computing test metrics, preventing threshold calibration on one site's observations from being described as an independent test on that same site. It also rejects exact canonical WGS84 AOI-ring reuse even if a new `site_id` is assigned. Within each registry, the same canonical geometry cannot be assigned multiple `site_id` values, which would inflate independent-site counts. This exact-geometry gate does not detect all partial polygon overlaps or nearby AOIs; those still require an explicit spatial-separation/buffer audit.


- **Development set:** Bhote Koshi reproduction and synthetic known-answer fixtures. Parameters may be debugged here, but benchmark values must not be used to tune hazard thresholds and then reported as held-out accuracy.
- **Validation set:** independently sourced events and matched non-event AOIs; used for one-time policy selection of thresholds, temporal persistence and quality gates.
- **Held-out test set:** spatially separate events/sites and later acquisition intervals not used to choose thresholds. Freeze a test-registry manifest (with a SHA-256) before final scoring.
- **Cross-sensor set:** NISAR vs ITS_LIVE/Sentinel-1/optical/GNSS comparisons. Keep these evaluations distinct because temporal averaging, frequency, geometry and displacement components differ.
- Use event-level splits, not random pixel splits. Neighbouring pixels are spatially autocorrelated; millions of pixels from one landslide do not constitute millions of independent events.

## 5. Metrics and scorecards

### Measurement performance

For displacement magnitude (m) and independent reference (r), on a predeclared common-valid mask report median bias, MAE, RMSE, robust regression slope/intercept, and 50/90/95% error quantiles. For vectors, report east/north component errors and circular azimuth error, conditional on adequate speed. Report valid-pixel support and no-data coverage beside every score.

Bootstrap uncertainty must resample spatial blocks, not individual pixels. State block size, origin, seed, PRNG, replicate count, and show sensitivity to at least three block sizes. These intervals only describe conditional spatial sampling uncertainty; they do not include systematic errors from geometry/HAE, reference correction, product release, orbit, or sensor calibration.

### Detection performance

Only after labels and thresholds are independently frozen, report event-level precision, recall/sensitivity, specificity, false alarms per AOI-month, missed-event count, lead-time distribution, detection delay, and precision-recall curve/AUPRC. Provide confidence intervals clustered/resampled by *event/site*, not pixel. A “no measurable signal” or “not enough data” is distinct from a negative event label.

Do not use a percentile from a single circular spatial sampler as an alert threshold until it is calibrated against a large predeclared event/non-event corpus and the author's sampling procedure has been independently replicated.

### Availability/operability

Record time of acquisition, product publication time, actual download/processing time, available valid pair cadence, gaps, product maturity/CRID, source latency, total processing time and failure status. A retrospective measurement from 12- or 24-day intervals cannot claim a final-week precursor when that temporal window is not observed.

## 6. Core engineering invariants

1. No source-product release or maturity mixing inside a cumulative series. Pairwise measurements from separate chains can be viewed side by side but must not be concatenated or summed.
2. Pairwise displacement magnitude is not cumulative displacement. A connected pair chain is necessary but not sufficient: common grid, reference frame, target-correspondence and closure checks remain required.
3. A horizontal GOFF result assumes vertical motion is zero and uses geometry/HAE; it is not a 3-D motion vector. Constant HAE is exploratory until compared to per-pixel terrain/DEM geometry.
4. A high-magnitude vector can be a real fast failure or an outlier. Generic runs preserve and flag it; paper replay uses only the explicit, versioned method-specific rejection policy.
5. SNR/coherence, correlation, mask and pixel-support rules are all part of the measurement result. Publish rejection counts and common valid-area masks.
6. No product in the catalog or date window means “not observed/available,” not “no movement.”
7. A successful workflow or clean dashboard does not mean the site is safe or that a hazard was detected.

## 7. Promotion gates

- **G0 — structural:** all schemas, identity checks, hashes, grid checks and deterministic synthetic known-answer tests pass.
- **G1 — measurement engine:** independent vector-projection, sign/units, mask and GeoTIFF georeferencing tests pass; source product and run manifest are complete.
- **G2 — paper parity:** author geometry/source IDs/code/golden rasters are verified; pixelwise and summary parity tests pass.
- **G3 — external validation:** held-out event and non-event cohort has frozen labels, product availability, precision/recall/false-alarm confidence intervals, and cross-sensor uncertainty analysis.
- **G4 — operational research pilot:** per-pixel DEM-backed geometry, temporal latency/cadence policy, calibration/drift monitoring, quality-based “no result” behavior, and documented human review are verified end to end.

Current branch is below G2: author supplement and exact author inputs are still unresolved. Current hazard detection remains `NOT_EVALUATED`, and operational monitoring is blocked.


## Executable held-out event evaluator

The measurement runner deliberately does not emit a hazard score. To make later detector claims auditable, `tools/know_place/event_validation.py` now implements a separate event-level scoring contract. This module evaluates externally produced predictions; it does **not** derive a score from displacement or certify a detector.

### Case registry requirements

Each case must have a stable `case_id`, `site_id`, `split` (development/validation/test), independent event label, hazard type, WGS84 AOI WKT, source URL/DOI and method for the independent label, observation-window UTC bounds, monitoring exposure in AOI-months, and each source granule's exact SHA-256. Positive event cases also carry the best independently supported event timestamp. Site is the resampling unit because cases from the same site are correlated. The normalized registry has its own checksum; changing any case invalidates a threshold policy bound to that registry.

A case without enough valid data must have `state=NO_RESULT`, **not** `NO_ALERT`. The evaluator reports usable coverage separately. It excludes `NO_RESULT` from conditional confusion-matrix metrics, while the conservative recall over all labelled events treats an event with no alert/result as not detected. Thus a failed measurement cannot silently become proof of safety.

### Threshold policy

The frozen threshold policy records the model/policy name, the exact SHA-256 of the detector-policy manifest, score name, scalar threshold, comparison rule, validation split, pre-test freeze declaration, registry checksum, validation-score checksum, and policy checksum. The manifest must identify the algorithm, implementation revision, feature-manifest SHA-256, score units, and parameters; the threshold selector hashes the exact manifest bytes and requires the validation-score payload to carry the same hash. Each validation-score and held-out-prediction case must also list the SHA-256 values of the exact source products used/attempted, and those hashes must match the corresponding registry case. `evaluate_heldout_events` rejects missing, duplicated or source-mismatched cases, model-policy hash mismatches, source-product hash mismatches, invalid alarm times, and scores inconsistent with the declared threshold.

From the **held-out test cases only**, the evaluator reports event-level precision, recall, specificity and F1 on evaluable cases, coverage/no-result counts, conservative recall over all labelled events, false alarms per monitored AOI-month, event lead-time/detection-delay summaries, and site-cluster bootstrap intervals. It withholds site-cluster intervals when fewer than five independent sites are present by default, or when fewer than five independent positive-event sites or five non-event sites are available. Each metric interval is also withheld unless at least 95% of requested bootstrap replicates define that metric; the report records the defined-replicate counts/fractions instead of silently presenting a conditional interval. These statistics are meaningful only when the registry labels, split assignments and model outputs were frozen independently of one another.

### Prediction timing contract

A supplied `first_alarm_time_utc` is valid only when the prediction state is `ALERT`, and it must fall within that case's declared `observation_window_utc` (inclusive start/end). `NO_ALERT` and `NO_RESULT` records must not carry an alarm timestamp. This prevents lead-time/detection-delay metrics from being calculated from alarms outside the case's monitored period or from contradictory states. A missing alarm timestamp on an `ALERT` remains permissible but contributes no lead-time/delay value; it must be disclosed as timing unavailable, not inferred. The evaluator reports `alarm_time_coverage` with positive-event alert counts, alerts lacking timestamps, and the resulting COMPLETE/PARTIAL timing status so this missingness cannot be hidden behind a lead-time median computed on only the timed subset.

### CLI contract

Once a real detector emits per-case scores and a policy/threshold has been selected exclusively on the validation split, save:
- `validation-registry.json`: only `split=validation` cases with independently reviewed labels and source/geometric provenance;
- `heldout-test-registry.json`: only `split=test` cases, kept separate from the calibration input;
- `detector-policy.json`: the frozen detector/score manifest, hashed as exact file bytes and recording implementation revision, feature manifest, parameters, score definition and units;
- `validation-scores.json`: one finite `SCORED` value or a `NO_RESULT` for every validation case, with the policy hash and exact registry source-product hashes;
- `heldout-test-predictions.json`: one `ALERT`, `NO_ALERT`, or `NO_RESULT` record for every held-out test case, with the policy hash and exact registry source-product hashes; scored predictions must agree with the frozen threshold;
- `threshold-policy.json`: the content-addressed policy bound to the validation-only registry and validation scores.

Before evaluating test predictions, generate the frozen threshold policy from **validation-only** scores. The registry checksum binds the split membership, and any test case accidentally included in the score file is rejected:

```bash
python -m tools.know_place.select_threshold \
  --registry validation-registry.json \
  --validation-scores validation-scores.json \
  --model-policy-name YOUR_DECLARED_DETECTOR_VERSION \
  --model-policy-manifest detector-policy.json \
  --score-name YOUR_DECLARED_RISK_SCORE \
  --objective max_youden_j \
  --out threshold-selection-report.json \
  --threshold-policy-out threshold-policy.json
```

The threshold selector now rejects any registry containing development/test cases, and the held-out evaluator requires two explicit inputs: a validation-only registry whose SHA-256 matches the frozen policy, plus a test-only registry. Do not pass the same combined registry to both CLIs. Keep the master multi-split registry in a controlled data-curation step and export split-specific files with their own hashes. This prevents test labels from entering the threshold-selection stage, rather than merely promising not to use them.

The score file uses schema `know-place-validation-scores/1.1`, includes the top-level `model_policy_sha256`, and has one record per validation case with a finite `SCORED` value or `NO_RESULT`/null score plus `source_product_sha256s` exactly matching that case's registry source products. The held-out prediction file uses `know-place-event-predictions/1.1` and likewise includes the top-level model-policy hash and each case's exact source-product hash list. The detector-policy manifest must be frozen with the threshold-selection run; editing the model, parameters, feature definition, or score units creates a new hash and requires recalibration on validation data. The threshold selector accepts a predeclared `max_youden_j`, `max_f1`, or `max_recall_at_min_specificity` objective. Use the last objective only when the minimum-specificity constraint was chosen before inspecting validation scores. Record the chosen objective, score units and detector version in the experiment log.

The event evaluator defaults to at least five independent total sites, five positive-event sites, and five non-event sites for confidence intervals. Synthetic unit tests may pass lower explicit values, but those low thresholds are not a scientific validation recommendation.

Then run:

```bash
python -m tools.know_place.event_validation \
  --registry heldout-test-registry.json \
  --validation-registry validation-registry.json \
  --predictions heldout-test-predictions.json \
  --threshold-policy threshold-policy.json \
  --out heldout-evaluation.json
```

**Current limit:** the generic AOI runner has no scientifically calibrated hazard score yet, so this evaluator has only synthetic known-answer tests and no real detector validation result. The synthetic test suite is an implementation check, not evidence of landslide/glacier-collapse detection accuracy. Promotion still requires the externally labelled, held-out event/non-event cohort and independent reference measurements described above.
