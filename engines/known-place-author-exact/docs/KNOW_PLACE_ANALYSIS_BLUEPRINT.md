# Know Place Analysis — Scientific Architecture Blueprint

**Status:** design baseline v1.0; implementation is intentionally isolated  
**Branch:** `feat/know-place-analysis`  
**Parent:** `feat/final-aoi-science-integration` at `830b054e0f60c4957d64c289e49dea86ff808803`  
**Protected boundary:** no commits, workflow edits, or merges to `main` from this work.  
**Study site:** Bhote Koshi source/crown, Nepal; NISAR GOFF pair series around the 26 August 2026 event.

## 1. Objective and scientific claim boundary

Build a reproducible, paper-method-compatible analysis path for one named study site. First priority is to reproduce the reported **measurements and comparison statistics**, not to manufacture a landslide alarm.

The original blueprint baseline cited the 24 September 2026 EGUsphere preprint, under review at NHESS: Meena, “NISAR pixel offsets measure but do not statistically resolve pre-failure motion at the 26 August 2026 Bhote Koshi ice–rock avalanche, Nepal,” DOI [10.5194/egusphere-2026-5462](https://doi.org/10.5194/egusphere-2026-5462). That citation remains as the provenance of the initial plan.

**Benchmark-version update (2026-10-24):** the user subsequently supplied a differently titled Research Square article, “NISAR offsets measure pre-failure motion but do not single out the Bhote Koshi avalanche source,” DOI [10.21203/rs.3.rs-11022365/v1](https://doi.org/10.21203/rs.3.rs-11022365/v1), its Supplementary Information and Supplementary Data 1. These uploaded Research Square materials are the source for the current exact IDs and scalar benchmark in [`author_benchmark_v1.json`](know-place/reference/author_benchmark_v1.json). A formal cross-version identity/content comparison with the EGUsphere record has not been completed, so their input manifests and method details must not be silently combined. The Research Square supplement specifies P05023 for all five pairs; live ASF lookup confirmed four exact P05023 IDs but did not find the 20 June–2 July P05023 ID. The historical X05026 source remains only a separately identified historical input. See [the full author supplement audit](know-place/evidence/AUTHOR_SUPPLEMENT_RETRIEVAL_AUDIT_20261024.md).

For the supplied Research Square version, measurements are not automatically detections, and the benchmark target is a numerical/method reproduction, not an operational hazard alarm. That version reports that no pre-event interval reaches the 95th percentile on directional coherence or displacement and that no acceleration is resolved.

Required result classes must remain separate:
- **Pipeline/structural status:** downloads, file integrity, masks, manifests and outputs are valid.
- **Method reproduction status:** paper-method inputs and calculations have passed parity checks.
- **Scientific interpretation:** measurement estimates, quality support, comparison percentiles, uncertainty and limitations. No automatic “landslide detected” label is permitted.

## 2. Forensic baseline: Run 39942529304

Evidence: [GitHub Actions run 39942529304](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39942529304), manifest and dashboard artifacts downloaded and inspected.

- Run status was structural **PASS**; 20 products were selected and validated (10 GUNW + 10 GOFF); 17 had at least one valid science pixel.
- Actual time inputs in the manifest were **2026-06-17 to 2026-08-31**, not 2026-06-20 to 2026-08-31. The reference pairs are still present, but the extra start-window products should not enter the paper-matched benchmark.
- The selected inventory mixed ascending T098 and descending D048, multiple acquisition pairs, and GUNW/GOFF families. The paper's primary comparison is five ascending T098, L-SAR HH GOFF pairs on an 80 m EPSG:32645 grid.
- The expected five target pair dates are 20 Jun–2 Jul, 2–14 Jul, 14–26 Jul, 26 Jul–19 Aug (24 days), and 19–31 Aug. The matching GOFF entries in this run are GOFF-003, GOFF-007, GOFF-011, GOFF-015 and GOFF-019. All other selected products must be excluded from the strict benchmark, not silently pooled into the series.
- For GOFF-015, the current reader produced an AOI-wide median slant-range offset of 18.07 mm and along-track median of 11.89 mm after the SARGuardian auto-reference/deramp/outlier policy. Those are **not** the paper's crown-only median horizontal displacement magnitude of 0.96 m.
- The current GUNW stack reports zero pixels with a complete time series in both the A098 and D048 chains; no velocity fit was produced. A normal script exit is not a usable scientific time-series result.
- `derived-only` cleanup removed the raw HDF5 from the worker after remote retention. Current artifacts do not preserve all inputs the paper's calculation needs (notably raw GOFF SNR, radar geometry metadata, and uncorrected paired offset layers); they cannot support exact reprocessing by themselves. The required raw GOFF granules must be reacquired, verified, and hashed for this analysis.

## 3. Author-reported method to reproduce

Reference: paper PDF, Data and methods, pp. 2–3 and Results, pp. 4–7.

### 3.1 Benchmark inventory

Strict target set (all five required; fail closed when any are absent):
1. 2026-06-20 → 2026-07-02, 12 days
2. 2026-07-02 → 2026-07-14, 12 days
3. 2026-07-14 → 2026-07-26, 12 days
4. 2026-07-26 → 2026-08-19, 24 days
5. 2026-08-19 → 2026-08-31, 12 days

Expected geometry: ascending T098, L-SAR HH, GOFF layer2, same native 80 m grid / EPSG:32645. Each exact granule ID, maturity/CRID, product checksum and source URL must be recorded. Product release variants must not be substituted without an explicit sensitivity run.

### 3.2 Three distinct geometries

- **Background/reference box:** WGS84 bounds 85.500–85.565° E, 28.265–28.318° N. The user's rectangle represents this background box.
- **Crown polygon:** WGS84 bounds 85.5245–85.5400° E, 28.2847–28.2970° N. It is a separate target region.
- **Compact core (~0.19 km²):** an explicitly different, selection-sensitive diagnostic from the paper. Do not silently treat it as the crown or use it as the primary benchmark.

The source polygon is inside the background box. Background correction uses valid pixels in the box outside the crown; the reported paper's coherence comparison also discussed the box including the crown, so outputs must label which exact mask policy was used rather than conflating the two.

### 3.3 Pixel-level processing order

For every exact GOFF pair:
1. Read **raw layer2** along-track offset (AT), slant-range offset (SR), signal-to-noise ratio (SNR), correlation/validity metadata and grid definition from the source HDF5. Do not use the current reader's already auto-referenced or deramped GeoTIFF as if it were raw.
2. Validate the product's orbit/track, polarisation, dates, CRID/maturity, grid, units, nodata and required metadata.
3. Select finite, usable pixels with **SNR ≥ 5**. Project the offset observations to horizontal displacement using that product's geometry. Reject (do not clip) pixels with projected horizontal magnitude **> 10 m**.
4. Use local geometry at the crown grid cell; the paper reports incidence angle near 39.1°. Do not hardcode an assumed angle without checking the product metadata and recording the extracted value.
5. Using the NISAR product convention, compute:
   - dE = AT × atuX − (SR / sin(θ)) × (losX / |los_h|)
   - dN = AT × atuY − (SR / sin(θ)) × (losY / |los_h|)
   
   The paper assumes vertical motion is zero. Record this assumption. Derive signs from the file's unit-vector convention; never flip signs to force agreement with the paper.
6. For each pair, remove bulk co-registration bias by subtracting the component-wise median dE and dN over valid pixels inside the background box but **outside the crown**. Do not substitute the current global AOI auto-reference plus plane deramp in the reproduction path.
7. Calculate horizontal magnitude per valid pixel: sqrt(dE² + dN²). Report crown median magnitude, mean displacement vector and direction separately. Do not compare the paper's 0.96 m crown median with a box-wide range/azimuth median.
8. Compute the 5×5 mean resultant length (R) from unit horizontal-displacement vectors. Because offset estimates use overlapping matching windows, pixels are not independent; do not use the textbook independent-direction null as the benchmark.
9. Reproduce size-matched spatial controls inside the background box, with deterministic random seed, accepted/rejected draw counts and exact masks saved. Report empirical percentile for crown displacement and R, including the paper's caveat that neither pre-event polygon-scale statistic exceeded the 95th percentile.
10. The co-event 19–31 August pair must have a quality/directional-organisation check. Metre-scale magnitude in a decorrelated field is not a valid movement estimate by itself.

### 3.4 Expected published reference values (acceptance targets, not forced output)

- 26 Jul–19 Aug: crown median displacement magnitude ≈ 0.96 m over 24 d; crown mean vector ≈ 1.72 m toward 278°; R ≈ 0.87 versus full-box R ≈ 0.69.
- Size-matched displacement controls: median ≈ 0.14 m; crown ranks at ≈ 94.7th percentile, below 95th.
- Four pre-event polygon-scale interval percentile results reported by the author do not exceed 95th; the 19–31 Aug co-event pair has directional disorder/decorrelation and must not be treated as a clean displacement estimate.
- The paper gives earlier crown medians of ≈ 0.99 m for 20 Jun–2 Jul, ≈ 0.47 m for 2–14 Jul and ≈ 0.28 m for 14–26 Jul in its figures/results. These do not establish acceleration; the 24-day pair's average rate is lower than the earlier 12-day pair's rate.

These rounded publication values are sanity/reference targets, not exact pixel-wise acceptance constants. Author supplementary rasters/scripts and their checksums must be obtained where available to build a true golden-data parity test. If supplementary data cannot be fetched, mark independent parity as BLOCKED, not PASS.

## 4. Architecture and data flow

```text
Exact five raw GOFF HDF5 files
        │
        ▼
A. Source/metadata gate ── fail if wrong pair/track/pol/maturity/grid/units
        │
        ▼
B. Raw layer2 arrays + product geometry sampling/interpolation
        │
        ▼
C. SNR + finite + projected-magnitude quality mask
        │
        ▼
D. Geometry-derived East/North displacement (vertical motion = 0)
        │
        ▼
E. Pair-specific box-outside-crown component median correction
        │
        ├───────────────┐
        ▼               ▼
F. Crown metrics    G. 5×5 directional coherence R
        │               │
        └───────┬───────┘
                ▼
H. Deterministic size-matched spatial null / percentile analysis
                │
                ▼
I. Per-pair GeoTIFFs + CSV + JSON provenance + audit report
                │
                ▼
J. Separate structural / reproduction / interpretation statuses
```

Recommended modules (all isolated within this feature branch):
- `tools/know_place_analysis.py`: strict CLI, input identity checks, orchestration and machine-readable report.
- `tools/know_place/goff_io.py`: GOFF HDF5 field discovery, metadata/geolocation sampling, no fuzzy substitution when multiple dataset paths match.
- `tools/know_place/paper_method.py`: pure, unit-tested quality gates, geometry projection, component correction, magnitude, 5×5 R and deterministic control sampling.
- `tools/know_place/footprint_screen.py`: separate author-derived footprint-wide movement-candidate screen from archived `code/wide_screen.py` (41 px local magnitude anomaly, 5×5 residual coherence, z/anomaly/R thresholds, >=2 of five prescribed intervals and 4-connected >=10-pixel components). It requires already-interpolated per-pixel geometry coefficient rasters. It does not build geometry from HDF5/DEM, regenerate full-grid/GIS outputs, run the separate downslope attribution or establish hazard detection; see `know-place/evidence/AUTHOR_FOOTPRINT_SCREEN_KERNEL_AUDIT_20261024.md`.
- `tools/know_place/footprint_geometry.py`: array-only author-derived geometry builder that interpolates supplied `(height,y,x)` radarGrid parameter cubes against a supplied DEM array, computes per-pixel `cE/cN/kE/kN`, reports extrapolation/fill/clipping/nonfinite values, and requires explicit matching horizontal CRS/transform plus declared vertical references. It does not read/hash HDF5 or DEM files; see `know-place/evidence/AUTHOR_FOOTPRINT_GEOMETRY_BUILDER_AUDIT_20261024.md`.
- `tools/know_place/benchmark.py`: strict five-pair inventory, supplement/golden-data parity and tolerance report.
- `tests/test_know_place_*.py`: small synthetic arrays with analytically known answers and negative tests.
- `docs/KNOW_PLACE_ANALYSIS_CHECKLIST.md`: gates and completion evidence.

No edit to the existing streaming/Dynamic AOI workflow, existing scientific engine, default branch, or source-AOI baseline is allowed in this phase.

## 5. Scientific invariants / fail-closed rules

- Do not classify structural pipeline success as method reproduction or hazard detection.
- Never pool tracks, polarizations, processing families, geometries or different date intervals into one comparable series.
- Never use pre-corrected/clipped output as raw AT/SR/SNR or geometry.
- Never fill missing pixels with zero, infer missing metadata from output magnitude, or silently choose among multiple metadata matches.
- Missing SNR, geometry, units, exact pair, CRS, or reference/crown polygon => explicit failure or blocked status with cause.
- The selected background/crown masks, projected grid dimensions and pixel counts are written to provenance.
- Same seed + same exact input bytes + same analysis commit must produce byte-stable scalar tables (timestamps may differ in a separately identified run metadata field).
- A 95th-percentile gate is a paper comparison criterion, not a universally validated early-warning threshold.
- The output may conclude “measured but not statistically distinctive,” “insufficient data,” or “not reproducible from available inputs.” It must never change those results to PASS to satisfy an expected value.

## Footprint-wide candidate screen — isolated path

The archive's wide_screen.py is not the crown/site-series method. The extracted array kernel preserves the author's screen thresholds and is tested against a test-local transcription on synthetic arrays. The separate `footprint_geometry.py` now provides an array-level interpolation builder and is connected to the projection/screen kernels in synthetic tests. Neither module reads actual raw GOFF/DEM files, verifies the 16 original terrain tile identities, or regenerates the full 4230 × 4311 author outputs/GIS files. The author source frames its output as coherent moving surfaces worth inspection; active glaciers dominate candidates. It must not be rephrased as a collapse prediction, early-warning alarm or validated detector. See the screen and geometry audit reports.

## Footprint geometry and vertical-reference review — 2026-10-24

The archived DEM raster and three final screening rasters share the same 4,311-column × 4,230-row EPSG:32645 grid at 80 m posting. The archived `terrain/elev_m.tif` SHA-256 is `d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1`; its tag lists `nodata=-9999`, though no stored cell equals that sentinel. Grid congruence is established; vertical-reference congruence is not.

A material caveat remains: the Copernicus DEM specification reports standard GLO-90 elevations referenced to EGM2008, while the GOFF radarGrid uses `heightAboveEllipsoid`. The archived `prep_terrain.py` reprojects the DEM from EPSG:4326 to the output horizontal CRS but shows no vertical transformation; `geometry.py` feeds the resulting heights into the HAE interpolation directly. The source may have used upstream-transformed tiles, but their original bytes/metadata are absent, so that alternative cannot be established. See the [Copernicus DEM spec](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM), [NISAR modified DEM guide](https://nisar-docs.asf.alaska.edu/nisar-dem/) and [full geometry audit](know-place/evidence/AUTHOR_FOOTPRINT_GEOMETRY_BUILDER_AUDIT_20261024.md).

The builder therefore requires explicit vertical-reference declarations and rejects different declared references by default. An explicit override preserves the archive's direct-use behavior only for source-faithful comparison and is flagged as **not datum-corrected**; it is not a scientific fix. Any datum-corrected experiment must be separately versioned and report source DEM identity, geoid model, conversion sign/software and pixelwise effect. Exact author reproduction remains blocked until raw source identities, source coordinate axes, DEM tile provenance and coefficient parity can be checked.

## 6. Acceptance gates

A benchmark run is eligible for method reproduction only if:
- exactly the five target GOFF pairs are represented once each;
- all five have verifiable raw-source SHA-256 and matching expected track/polarization/maturity fields;
- HDF5 field units/conventions and geometry source are documented and checked;
- each pair's valid-pixel counts and rejected counts are preserved by reason;
- the 26 Jul–19 Aug pair's paper metrics can be compared with independent author-supplement outputs, if available;
- scalar discrepancies, raster extent/CRS disagreements, signs, null sampling and mask differences are disclosed;
- the no-detection interpretation matches what the source supports.

## 7. Sources

- Original plan's cited version: Meena (2026), EGUsphere preprint, DOI 10.5194/egusphere-2026-5462. The relation to the uploaded Research Square manuscript is unresolved.
- Current supplied benchmark version: Meena (2026), Research Square DOI 10.21203/rs.3.rs-11022365/v1; Supplementary Information and Supplementary Data 1 supplied with this task. The separate code/statistics/processed-field archive at Zenodo DOI 10.5281/zenodo.22730419 is now checksum-verified. It includes five small site-field GeoTIFFs and published tables but not raw GOFF HDF5 granules or full-footprint per-pair offset rasters. See `know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md`.
- Detailed input/version/ASF blockers: [author supplement retrieval audit](know-place/evidence/AUTHOR_SUPPLEMENT_RETRIEVAL_AUDIT_20261024.md).
- [ASF/NISAR GOFF product guide](https://nisar-docs.asf.alaska.edu/goff/): GOFF is geocoded pixel offsets, 80 m posting; raw product contains offsets and SNR layers and is not conventionally post-processed.
- Current Dynamic AOI audit baseline: [Run 39942529304](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39942529304).

## 8. First real replay and R-policy correction (evidence added 2026-10-24)

The first real five-pair raw-input replay completed in [Run 40006999011](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40006999011). All five candidate GOFF HDF5 source hashes matched the previous Dynamic AOI source products; all five pair reports reached `METRICS_COMPUTED`. The run's report/artifact is preserved separately and was not overwritten.

A post-processing bug was then identified: the first replay defaulted to 25 valid vectors in each 5×5 R window. The preprint defines a 5×5 mean resultant length but does not state a 25/25 minimum-neighbour condition. This requirement substantially changed support counts and depressed the target-pair R estimate. The saved-array workflow in [Run 40015023621](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015023621) downloaded the original derived-only artifact, verified all five NPZ hashes against the source report, recomputed R and its neighbour-count sensitivity, and uploaded the separate report/summary to Drive with remote verification. It did **not** download or reprocess HDF5.

For the 26 July–19 August pair, the recomputed values are:
- crown median horizontal magnitude: 0.966 m (published rounded target ~0.96 m);
- mean-vector magnitude: 1.722 m (published rounded target ~1.72 m);
- mean-vector azimuth: 277.79° (published rounded target ~278°);
- 5×5 R over all eligible crown centres using at least one valid direction: 0.853;
- R on the pointwise 0.17–2.75 m common-motion window: 0.869 at 150 crown centres, versus the paper's ~0.869 at 147 centres;
- box R on the analogous pointwise window: 0.686 at 1,626 centres; the paper's comparison sample is about 0.693 on 1,572 centres.

The close scalar results are encouraging evidence that parts of the published metric are being reproduced, but the three extra crown centres and background sample mismatch must remain visible. The exact irregular crown polygon and author product variants are not verified, and our deterministic circular controls are not established to match the author's spatial-control sampling algorithm. Our exploratory circular controls give a ~0.128 m median and a ~96.08th-percentile rank; the paper reports ~0.14 m and 94.7th percentile. **Those percentiles are not comparable** and the higher rank is not an alarm.

The current primary R calculation uses a minimum of one valid direction and publishes 1/5/10/15/20/25 sensitivity. Archived author code makes the site-series policy explicit: scipy.ndimage.uniform_filter with reflected edges and a >0.5 finite support fraction (at least 13/25); the current primary kernel is exploratory and not author-equivalent. Reproduction for the supplied Research Square benchmark remains `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; live ASF did not find the exact first-pair P05023 ID while the historical catalog finds X05026. Cross-version identity with the older EGUsphere record is unresolved; hazard detection remains `NOT_EVALUATED`. Full per-pair numbers, source hashes and acceptance gates are in [RAW_REPLAY_40006999011_R_POLICY_AUDIT.md](know-place/evidence/RAW_REPLAY_40006999011_R_POLICY_AUDIT.md).

The isolated validation workflow passed 46 tests, parsed all three feature workflows and passed actionlint in [Run 40015371603](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015371603). All implementation remains on `feat/know-place-analysis`; no `main` changes or merge were made.


## Archive recovery update — 2026-10-24

The user supplied the Zenodo README and main CC BY 4.0 ZIP. Byte integrity and in-ZIP manifest-listed payloads passed verification; exact archive hashes, five processed fields, author-source method differences, README/GeoTIFF profile inconsistency, and remaining raw-source/full-footprint blockers are recorded in [the Zenodo audit](know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md). Archive retrieval is no longer a blocker; implementation parity and exact raw GOFF bytes are.


## Current execution gate — author-exact reproduction to evidence dashboard (2026-10-25)

The near-term deliverable is an inspectable dashboard built from the already-retained Run #17 derived bundle, not another raw-data download. Keep the pipeline split into three claims:

1. **Operational integrity:** exact product IDs, maturity, byte/hash checks, grid identity, source manifests, derived bundle, Drive remote verification and post-cleanup receipt.
2. **Paper-method reproduction:** selected author P1 and P2 table fields, full-footprint aggregate rasters, candidate inventory and Table S7 comparison. Current Run #17 passed these selected gates, while the displacement-null draw-level implementation remains missing; the overall paper status is therefore partial.
3. **Hazard/early-warning performance:** not implemented/evaluated yet. This requires event-level labelled cases and non-event controls, preregistered held-out splits, frozen thresholds, independent reference evidence, and measured detection/false-alarm/lead-time performance.

The author-specific renderer (`tools/know_place/author_dashboard.py`) reads the verified derived result package and embeds scientific previews from saved NPZ/GeoTIFF outputs. Optical imagery is linked to publishers as contextual evidence only. It must not be described as a NISAR-derived raster, a georeferenced crown validation layer, or a hazard alarm.

A safe retained-artifact workflow (`.github/workflows/know-place-author-dashboard.yml`) renders the source Run #17 artifact without acquiring new raw GOFF, verifies the artifact digest and nested ZIPs, prohibits HDF5 files, and uploads the dashboard + manifest to Drive with remote receipts. The author-exact raw workflow also includes dashboard creation as a required final gate for future explicitly authorized replays.

**Acceptance criterion:** one safe render run must end with a downloadable dashboard artifact and verifiable Drive receipt; the dashboard must correctly show the author-compatible 0.965 m / 4.02 cm/day 24-day pair, selected site/P2/footprint comparisons, exact source hashes, contextual-image attribution, and the explicit partial-paper / not-evaluated-hazard statuses. This accepts the dashboard as a reproduction viewer only, not a validated predictor.

No main-branch changes or merges are permitted until a separately reviewed, dashboard-bearing E2E and scientific acceptance gate pass.

