# Know Place Analysis — Engineering & Scientific Checklist

**Rule:** items are not marked complete without inspectable evidence. This file is on `feat/know-place-analysis`; no item authorizes a merge to `main`.

## Milestone 0 — Freeze and inspect baseline

- [x] Create isolated branch `feat/know-place-analysis` from the existing science-integration branch.
- [x] Freeze the last Dynamic AOI run ID, workflow commit, orchestration commit, scientific engine commit, WKT and artifact IDs.
- [x] Download and inspect manifest, processing report, summary, per-product records and pixel-stack diagnostics.
- [x] Confirm actual input start date (2026-06-17) differs from the intended paper window (2026-06-20) and document impact.
- [x] Confirm selected inventory mixes target ASC T098 pairs with descending D048 and extra pairs; isolate only the five paper-matched GOFF granules.
- [x] Record current GOFF-015 outputs and make clear they are not paper-equivalent crown magnitude.
- [x] Record zero complete GUNW series pixels and the custom-AOI candidate-check skip.
- [x] Record that raw HDF5 was removed after derived-only retention; reprocessing needs verified re-download.
- [x] Save the baseline run URL, artifact IDs, downloaded-archive SHA-256 values and findings under `docs/know-place/evidence/BASELINE_RUN_39942529304.md`.

## Milestone 1 — Lock method and provenance contract

- [x] Write blueprint with geometry roles, five exact pair dates, equations, filtering, background correction and known limitations.
- [x] Write this evidence-based checklist.
- [x] Receive and SHA-256 record the paper PDF, Supplementary Information, 101-zone CSV, and separate Zenodo code/output archive; archive byte integrity and manifest payload checks are recorded in `docs/know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md`. The Zenodo ZIP itself does not contain the raw GOFF HDF5 payloads; the subsequent exact-author download and source-byte hashes are tracked separately below.
- [x] Resolve the five exact author P05023 IDs through NASA CMR, then download/hash/validate the exact HDF5 payloads in [run 40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362). Catalog identities 5/5; payloads downloaded 5/5; SHA-256 pins 5/5; grid validations 5/5. Evidence: `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`. X05026 is not a substitute.
- [x] Validate the five exact HDF5 identities and common source grid (4311 × 4230, EPSG:32645, 80 m posting) during run 40114703362. Geometry-axis interpretation and source units/sign conventions are now exercised by the exact-author replay, whose site-series and P2 values match at archived precision. Published-bounds/source-grid mask consistency is PASS; original author editable-mask/golden-vector parity remains UNVERIFIED.
- [x] Define a versioned input/output JSON schema and separate structural / method-reproduction / interpretation statuses.
- [x] Define separate WKT masks for the reference box, crown and box-minus-crown; the supplied paper fixes the crown bounds at 85.5245–85.5400° E and 28.2847–28.2970° N (2.07 km²), and the reference box bounds. **Published-bounds/source-grid mask gate: PASS** on the real retained Run #17 artifact: for all five pairs, the 323-cell reconstructed crown and diagnostic masks have XOR=0 against inverse-projected grid-centre geometry and the endpoint/searchsorted crop; the mask SHA is common across pairs. This verifies the rectangle reconstructed from the paper bounds against retained arrays, not the original author editable vector/golden mask (still unverified). Evidence: `docs/know-place/evidence/RETAINED_RUN17_CROWN_AUDIT_20261025.md`. **Count-estimand correction (2026-10-24):** exported displacement-valid counts `[283, 294, 296, 292, 195]` match `tables/nisar_pot_series.json` key `n`; separately recomputed R-valid crown counts `[302, 299, 302, 298, 202]` match `tables/polygon_null.json` key `n_px`. The earlier 296-versus-298 comparison mixed estimands. The real retained-artifact audit now verifies published-bounds/source-grid mask consistency; this does not prove byte-level identity with an original author vector/golden mask.
- [x] Define and record deterministic exploratory control parameters (seed, draw count, PRNG, reject/accept accounting and quantile convention). The archived post-hoc polygon-null algorithm was independently replayed from all five processed TIFFs using the archived crown-slice and sampling policy; 45/45 table metrics matched at stored precision. See `docs/know-place/evidence/AUTHOR_ARCHIVE_POLYGON_NULL_REPLAY_20261025.md`. This is exported-field/output parity only, not full paper-method or raw-source-grid parity.

## Milestone 2 — Implement pure scientific kernels (no downloads in unit tests)

- [x] Unit-test horizontal dE/dN projection against hand-computed vectors including sign checks.
- [x] Unit-test quality gate order, SNR ≥ 5, magnitude ≤ 10 m, reject-not-clip behavior, and per-gate rejection counts.
- [x] Unit-test component-wise background median correction on synthetic arrays with known bias.
- [x] Unit-test crown median magnitude, mean-vector magnitude/azimuth, and day-normalized descriptive rate as distinct statistics.
- [x] Test 5×5 mean resultant length using uniform/opposed vectors and expose 1/5/10/15/20/25-neighbour sensitivity in the report.
- [x] Add explicit corner/edge and missing-centre-vector regression cases as current-kernel policy tests; these do not claim author-method parity.
- [x] Add independently labelled validation/test registry schemas, validation-only threshold selection, content-addressed frozen policies, and test-only scoring that rejects mixed-split registries.
- [x] Add deterministic event-level precision/recall/specificity/F1, coverage/NO_RESULT accounting, AOI-month false-alarm rates, lead/delay summaries and site-cluster bootstrap with a minimum-site gate; synthetic known-answer tests only. The evaluator also rejects cross-split site/exact-geometry leakage, contradictory/out-of-window alarms, model-policy hash drift, and per-case source-product SHA-256 mismatches; schemas v1.1 are documented in the multi-event plan. This checks declared cross-file provenance, not trusted execution attestation.
- [x] Add exact acquisition-midpoint interval-average rates and gate rate-change features on contiguous pairs, same processing chain, grid compatibility, valid measurements and mission-data gaps.
- [x] Export the descriptive features to `motion-features.csv`; dashboard/result/manifest state the status and keep risk score null.
- [x] Unit-test deterministic size-matched control sampling, accepted/rejected draw accounting and empirical percentile.
- [x] Unit-test missing/finite/nodata behavior and explicit failure when background/crown support is empty; test HDF5 attribute and creation-property fill handling without mistaking a default zero for nodata.
- [x] Unit-test missing or duplicate products, wrong track/direction, invalid geometry, unit/CRS mismatches and ambiguous metadata fail closed.

## Milestone 3 — Strict raw GOFF HDF5 reader

- [x] Read exact layer2 AT, SR, SNR, correlation, coordinate vectors, CRS/projection and per-product radar geometry from all five candidate raw HDF5 inputs.
- [x] Implement geometry metadata interpolation with explicit cube selection, axis/unit/CRS checks and no extrapolation; synthetic schema tests pass. Actual five-product metadata verification remains pending.
- [x] Confirm the paper's distinction: site series uses one crown-local radar geometry throughout; footprint screen interpolates geometry at per-pixel Copernicus GLO-90 elevation. [x] Inspect archived author code and implement/test the P1 estimator: median each geometry component along the height axis at the radarGrid XY cell nearest the crown reference point. The separate exact-author runner used this estimator on all five P05023 products in Run 40170290176; its 65/65 site/polygon checks pass at archive rounding. This verifies numerical archive parity for the exported site series, not an independent author golden vector/mask.
- [x] Refuse ambiguous geometry groups, missing fields, non-finite geometry, unit mismatches and out-of-domain interpolation. Verify the actual five-product geometry/unit fields and sign convention through the exact-author replay; 65/65 site/polygon checks, 15/15 P2 checks and aggregate/full-footprint outputs pass at their stated comparison criteria.
- [x] Validate all five candidate products against the common EPSG:32645 80 m native grid; the strict reader fails closed on grid mismatches.
- [x] Implement source SHA-256 and record granule name, catalog maturity evidence, CRID, exact pair dates, track, direction, polarization and layer in the report.

## Milestone 4 — Paper-method analysis

- [x] Produce per-pair raw quality-gate counts, crown/background support counts and source SHA-256 evidence.
- [x] Produce corrected dE/dN/magnitude outputs and hash-recorded NPZ diagnostic arrays on the source grid.
- [x] Produce 5×5 R from unit vectors, with valid-centre counts, an explicit minimum-neighbour policy and sensitivity outputs.
- [x] Calculate crown and box/background R and crown displacement/vector metrics with distinct, provenance-labelled masks.
- [x] Create an explicitly labelled exploratory deterministic circular-control distribution for magnitude and R; accepted/rejected draws and percentiles are recorded. - [ ] Verify author-exact spatial-control sampling before comparing published percentiles.
- [x] Screen 19–31 Aug separately: crown R is lower than its surrounding box and the report does not treat its displacement magnitude as an alarm.
- [x] Process all five required intervals separately, without pooling ascending/descending tracks or selecting only a target-positive interval.
## Milestone 4B — Footprint-wide candidate screen (separate method path)

- [x] Extract the archived wide_screen.py array equations into tools/know_place/footprint_screen.py, with attribution and source SHA-256 records: per-pixel AT/SR projection coefficients, SNR >= 5 and magnitude <= 10 m gates, 41-pixel local anomaly, 5x5 residual R, z >= 4, anomaly >= 0.50 m, R >= 0.75, at least 2 of the 5 prescribed intervals, and four-connected components >= 10 cells.
- [x] Add synthetic known-answer parity tests for the archived screen formulas, mask/interval rejection, persistence and connected-component behavior. Wire the module and test file into the explicit CI lists. Geometry→screen integration is also explicitly tested. Latest CI: 176 tests passed in [run 40050020868](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020868).
- [x] Add an array-only author geometry-coefficient builder in `tools/know_place/footprint_geometry.py` with synthetic interpolation, Y-axis normalization, median-fill/clipping, extrapolation-count, nonfinite coefficient, CRS/affine and geometry→projection→screen integration tests.
- [x] Require explicit target/geometry/DEM horizontal EPSGs, matching target/DEM affine transforms, and declared DEM/geometry vertical-reference strings. A declared mismatch fails by default; only an explicit source-reproduction override can pass the source's direct-use behavior through, with `vertical_transformation_applied=false` in the result.
- [x] Download and SHA-256-pin the 16 current public Copernicus GLO-90 tiles for the source terrain bbox, validate raster profiles, and replay the archived `terrain/elev_m.tif` mosaic/warp. The archived grid matches 18,235,529/18,235,530 Float32 cells exactly and the entire finite mask matches. This verifies current public tile raster-value parity, not original author tile-byte identity. See `docs/know-place/evidence/COPERNICUS_GLO90_SOURCE_TILE_REPLAY_20261024.md`.
- [x] Run a separate vertical-datum sensitivity using the public PROJ/NGA EGM2008 2.5-arc-minute grid and formal EPSG:9518 → EPSG:4979 conversion. Median ellipsoidal-minus-EGM2008 offset is −30.1587 m across the target grid and −31.7705 m in the 323-cell crown mask. No correction was applied to the author-reproduction path. See `docs/know-place/evidence/EGM2008_VERTICAL_DATUM_SENSITIVITY_20261024.md`.
- [ ] Obtain the author's original 16 terrain input files or verified source receipts to prove byte-level source identity; current public mirror copies are not proven identical.
- [x] Acquire and SHA-256 pin the five exact author-published P05023 GOFF HDF5 payloads, validate HDF5 identities and the common 4311 × 4230 EPSG:32645 80 m grid, and verify source bytes in [run 40128950105](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40128950105). The five raw files were deleted only after derived-only Google Drive retention and post-delete receipt verification. [ ] Re-run the source-acquisition step after explicit consent when the newly integrated full-footprint runner is to be exercised; do not substitute X05026. Full-grid coefficient/output parity remains pending until that runner produces direct comparison evidence.
- [ ] Resolve remaining source/datum provenance uncertainty with independent author input evidence; the current public GLO-90 replay and formal height transformation quantify the issue but do not prove what exact source tile bytes the author used or make the existing paper replay equivalent.
- [x] Completed exact-author full-footprint replay on all five pinned P05023 products in Run 40170290176. Source hashes and common 4230 × 4311 EPSG:32645 grid passed; all five per-pair outputs were generated. The three archived aggregate rasters passed comparison (flag-count raster exact across 18,235,530 cells; anomaly and R rasters have zero finite-mask/value mismatches across their 4,008 finite cells); the 106-candidate inventory and all 101 Table S7 numeric rows passed their declared tolerances. Glacier/RGI classification fields were excluded because exact RGI 6.0 polygon assets are not in the author archive. Evidence: `docs/know-place/evidence/FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md`.
- [ ] Recreate the separate post-hoc downslope attribution/control test from candidate_attributes.py. This must not be folded into the screen or relabel a movement candidate as an event detection.
- [x] Keep HAZARD_DETECTION_STATUS=NOT_EVALUATED. The screen detects candidate moving surfaces, not impending failure; see docs/know-place/evidence/AUTHOR_FOOTPRINT_SCREEN_KERNEL_AUDIT_20261024.md.
- [ ] Keep core diagnostic separate and state its selection bias if implemented.

## Milestone 5 — Golden comparison and interpretation

- [x] Compare the 26 Jul–19 Aug crown median (0.966 m), mean-vector magnitude (1.722 m) and azimuth (277.79°) to rounded paper targets; residual geometry/mask/input-variant differences are documented.
- [x] Compare R on the common 0.17–2.75 m pointwise window (0.869 at 150 crown centres) to the published ~0.869 at 147 centres; document background R/count mismatch and non-equivalent controls.
- [x] Retrieve and inspect archived site-series and polygon-null code and compare all five published TableS4 values to the benchmark fixture. [x] Recompute the archive's five post-hoc polygon-null distributions from the processed fields using the archived algorithm (shared RNG seed 20260907, unique candidate centres, disk edge/support rejection, strict quantile inequalities, 60% acceptance rule): 45/45 stored metrics match. See `docs/know-place/evidence/AUTHOR_ARCHIVE_POLYGON_NULL_REPLAY_20261025.md`. This does not establish a published-paper metric or original source-grid parity.
- [x] Recompute same-estimand statistics from all five exported author field GeoTIFFs and compare `nisar_pot_series.json`, `polygon_null.json` and Table S4: 120/120 comparison checks passed at archived table precision. Results and source-table hashes: `docs/know-place/evidence/AUTHOR_PROCESSED_FIELD_TABLE_PARITY_20261024.md`. This was the scope of the earlier exported-field comparison. It is superseded for the five selected author pairs by Run 40170290176, which verified exact P05023 source hashes/common grid and the selected full-footprint output comparisons. The original editable crown vector/golden-mask identity remains unverified.
- [x] Record the paper’s interpretation and explicitly avoid describing this analysis as an early-warning detector.
- [x] Keep whole-paper reproduction status PARTIAL rather than overclaiming. Exact raw P05023 bytes and native grid were verified; Run 40170290176 passed the P1/site checks, P2 15/15, aggregate footprint rasters, 106 candidate inventory rows and 101 Table S7 numeric rows. The later derived-only displacement-null replay (Run 40219393283) also matches all 15 displacement-null numeric outputs at stored precision. Exact original displacement-null generator/draw history, editable crown-mask identity and RGI overlay remain unverified. See `docs/know-place/evidence/FINISHING_GATE_20261025.md` and `docs/know-place/evidence/DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md`.
- [ ] Complete independent scientific review before claiming full-paper reproduction. The exact P05023 source hashes, P1/P2 table comparisons and footprint aggregate/inventory comparisons now pass; displacement-null sampling, original author crown-vector/golden-mask identity, exact RGI 6.0 overlay and independent event-level hazard skill remain unverified.
- [x] Keep geometry policy explicit: crown-local constant geometry for the site series; per-pixel Copernicus GLO-90 geometry for the footprint screen. The exact datum/query behind the current 5151.0 m value remains unverified; do not tune it to scalar paper targets.
- [x] Add blind split enforcement so threshold calibration only accepts validation-only labels and held-out scoring requires a separate test-only registry plus a hash-matched validation registry.

## Milestone 6 — Operational isolation and review

- [x] Keep the legacy expensive replay workflow gated; add a separate exact-author P05023 workflow with manual-dispatch-only raw access and an exact `[run-know-place]` input, so ordinary pushes never launch the raw download.
- [x] Verify compact CSV/JSON, NPZ diagnostics, source/array hashes, quality-gate accounting, scientific caveats and separate reanalysis artifacts; the latest reanalysis report and summary were remotely verified in Drive.
- [x] Run automated scientific tests, YAML parsing and `actionlint` with author-data integrity and offline ASF-gate tests included: **122 tests passed** in [validation run 40035193088](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40035193088). The historical-candidate gate passed; the separate author-exact gate recorded 4/5 exact P05023 IDs confirmed and the first ID NOT_FOUND, with zero raw downloads. A blocked science input is recorded in the artifact rather than misreported as a passing source match.
- [x] Historical isolated validation after adding the footprint-screen module and explicitly adding its test file to the CI lists: [run 40049074686](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40049074686), commit `5740407c3a477b24453c7c9728aef380869ca3f3`: **164 tests passed**, four workflow YAML files parsed, actionlint v1.7.12 checksum verified and semantic workflow validation passed. The ASF job downloaded zero source products and still records first author P05023 NOT_FOUND. [Raw replay run 40049074681](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40049074681) skipped five-pair analysis because `[run-know-place]` was absent.
- [x] Historical branch validation after event/provenance hardening: [run 40047359607](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40047359607), commit `a0c41e721a9158d47d6ebb1505451d109ab33a23`: **150 tests passed**, four workflow YAML files parsed, actionlint v1.7.12 checksum and semantic validation passed. ASF source downloads were zero; first author P05023 remains NOT_FOUND. [Raw replay run 40047359560](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40047359560) skipped five-pair analysis due to missing `[run-know-place]`.
- [x] Historical validation: [run 40056005969](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40056005969), commit `80016cfb591a6e6d7715bb36440c949cb1ca5654`: 191 tests passed; six workflow YAMLs and actionlint passed; first P05023 identity was confirmed by CMR. No payload was downloaded. [Raw replay run 40056005985](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40056005985) skipped because `[run-know-place]` was absent.
- [x] Keep every Know Place Analysis commit on `feat/know-place-analysis`; no `main` changes or merge were made.
- [ ] Do not merge to `main`. Any later integration requires explicit review and approval.

## Current gate status (updated 2026-10-24)

- **Milestone 0:** complete. Baseline run, source/dashboard artifacts, array/report checksums and findings are saved under `docs/know-place/evidence/`.
- **Milestone 1:** blueprint, method contract and provenance implemented. The Zenodo archive itself lacks raw GOFF payloads, but the later author-exact replay downloaded and SHA-256-pinned five exact P05023 HDF5 products. Published-bounds rectangle/native-grid mask consistency now passes on the retained artifact; original author editable-vector/golden-mask parity, exact displacement-null sampling policy and full-footprint golden outputs remain unverified. See `docs/know-place/evidence/AUTHOR_SUPPLEMENT_RETRIEVAL_AUDIT_20261024.md`, `docs/know-place/evidence/CMR_AUTHOR_P05023_EXACT_CATALOG_RESOLUTION_20261024.md` and `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`.
- **Milestone 2:** scientific kernels, strict synthetic HDF5/geometry/integration tests, blind-split evaluator and threshold-selector tests, motion dynamics, author benchmark integrity, offline author-catalog handling and CSV bundle contract passed **122 tests** in [validation run 40035193088](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40035193088). The same run's YAML and actionlint checks passed. Live catalog identity is reported separately from code/test status; the author-exact source gate remains BLOCKED. Edge/missing-centre tests are current-kernel policy tests only, not author-method parity.
- **Milestone 3:** five raw candidate GOFF HDF5 products were fetched one at a time during [raw replay Run 40006999011](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40006999011); all five historical file-size/SHA-256 identity checks passed, and all five metric records were produced. The later saved-array reanalysis also verified the five NPZ hashes against the source report before computing any new R values.
- **Milestone 4:** per-pair gates, corrected dE/dN/magnitude metrics, 5x5 R and spatial-control diagnostics have been computed. The original run used a too-strict 25/25 neighbour rule; the separate [saved-array R sensitivity reanalysis, Run 40015023621](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015023621), computes the 1/5/10/15/20/25 sensitivity and does not modify the original run report.
- **Milestone 5 (updated after exact-source replay):** the target pair's initial exploratory result remains only numerical similarity, not reproduction. A later author-compatible run checked five exact P05023 products; its exported 6-km dE/dN/coherence rasters matched all 15 channels at ≤1e-6 absolute error. The P1/polygon workflow has 65 selected checks, but those are not all 95 Table S4 cells. The halo-aware P2 path has been added and synthetic-tested, but its 15 P2 comparisons still require a new raw replay. The 15 core-scale values match conditionally using the author's already-supplied screen-selected candidate geometry; this is not independent full-screen recovery. Displacement-null sampler parity and direct original author-vector/golden-mask parity remain unresolved; published-bounds/native-grid mask consistency is now verified on the retained artifact. No detection claim.
- **Milestone 6:** isolated raw and saved-array workflows are branch-only; saved-array result/summary retention has passed remote Drive verification. The AOI result bundle includes `timeseries.csv`, `motion-features.csv`, native-grid GeoTIFF placeholders in synthetic tests / real geotiffs in actual measurement runs, NPZ diagnostics, result, dashboard, and checksummed manifest; ephemeral-source manifests now state whether raw HDF5 was deleted or retained. All new commits remain on `feat/know-place-analysis`; no merge or edit to `main` was performed.
- **Paper reproduction (interim snapshot superseded by Run 40219393283):** `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`. Exact P05023 source hashes and cleanup/Drive receipts passed; P1/site-series 65/65, P2/local-mean 15/15, three aggregate footprint rasters, 106 inventory rows and 101 Table S7 numeric rows match at their declared precision. The later derived-field displacement-null replay matches all 15 remaining Table S4 numeric outputs at published precision, bringing the numeric table comparison to 95/95. Exact original displacement-null generator/draw-sequence identity remains unverified. Original editable crown-mask/golden-mask parity and RGI 6.0 overlay also remain unverified. Hazard detection remains `NOT_EVALUATED`.
- **Hazard detection:** `NOT_EVALUATED`. Do not report an operational landslide alarm from these results.


- [x] Add isolated archived-author kernels and synthetic regression cases in `tools/know_place/author_parity.py` and `tools/tests/test_know_place_author_parity.py`. They are wired into the separate exact-author runner; Run 40170290176 exercises the P1/P2 paths and passes 65/65 site/polygon checks plus 15/15 P2 checks at archive rounding. This is numeric output parity, not a full-paper reproduction claim.


## Latest exact-author acquisition workflow status — 2026-10-24

- [x] Add the exact-author acquisition runner and direct CMR HDF5 URL resolver. The resolver requires exact P05023 producer identity, the pinned CMR collection, trusted ASF/earthdatacloud hosts, the exact expected HDF5 path/name and exactly one data link per product.
- [x] Preserve failure manifests in the derived output area, bind config provenance to the source-manifest SHA-256, fail closed unless the analysis exit code is zero and all five scientific metrics are complete, and validate all five raw grids against the expected 4311 x 4230 EPSG:32645 / 80 m grid with identical coordinate axes.
- [x] Add offline acquisition-contract tests and wire them explicitly into the validation workflow. Latest validation [run 40058988024](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988024), branch head 2fddad5fbd3d66fc9ade40da41ce829bfabf7610: **204 passed in 4.87 s**, seven workflow YAML parses, actionlint v1.7.12 checksum and semantic validation passed.
- [x] Live CMR/data-link check: AUTHOR_CMR_CATALOG_GATE=PASS; AUTHOR_EXACT_PRODUCTS_CONFIRMED=5/5; AUTHOR_EXACT_CMR_DATA_URLS_CONFIRMED=5. Source payload downloads=0 and raw source SHA-256 pins=0. Evidence artifact [know-place-author-exact-live-cmr-access-evidence](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988024) (artifact digest SHA-256 b81e1d2b1ba4c78a90753ed84fd1ff1da0ff72c886bf46f31ffdd99928a1c4e9).
- [x] Register the exact-author raw workflow as manual-dispatch-only with an exact `[run-know-place]` consent input and credential preflight. Push registration run [40058988016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988016) did not run the raw job; legacy run [40058988057](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988057) also skipped analysis.
- [x] Exact-author dispatch and data replay completed in [run 40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362) using the exact consent input. Five payloads were hashed/grid-validated, the analyzer ran, and Drive receipts passed remote verification.
- **Status contract:** source byte identity PASS (5/5); paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`; no merge/change to main.

- [x] Latest full code/test validation before this evidence-pointer refresh: [run 40092715120](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40092715120), commit `e0268bf891329cae4698da0bef8611606da69a4e`: **204 tests passed in 4.55 s**, seven workflow YAML files parsed, actionlint v1.7.12 checksum and semantic checks passed. The live CMR artifact ZIP (ID `12559850649`) was independently downloaded and integrity/hash checked (SHA-256 `e2d62d5b955e76083c90b64ace06f7e69109da628f7a5f37f62f15d37519377f`); exact P05023 IDs/URLs are 5/5, payload downloads 0/5.

## Milestone 7 — Run Workflow launcher and independent multi-site protocol (2026-10-24)

- [x] Add a feature-branch copy of `.github/workflows/sarguardian-aoi-wkt-dispatcher.yml` so the existing default-branch Run Workflow entry point can be opened on branch `feat/know-place-analysis` without changing `main`.
- [x] Add two explicit profiles: `author-exact-p05023` (five exact author products) and `generic-aoi-date` (arbitrary WKT + inclusive date window).
- [x] Make both child workflows reusable and pass all request inputs through typed `workflow_call` contracts.
- [x] Require the exact `[run-know-place]` consent input at the dispatcher before either raw-download path; repeat the guard in each child workflow. Generic catalog-only dry runs default to no raw downloads.
- [x] Preflight Earthdata and Drive secrets before download. Preserve derived bundle and receipts in Drive, verify remote receipts before deleting raw temporary HDF5.
- [x] Expose analysis mode metadata, optional constant HAE sensitivity input and 5x5 coherence-neighbour sensitivity in the generic AOI workflow. These are request parameters, not proof of independent validation or operational readiness.
- [x] Register a six-site benchmark inventory in `docs/know-place/reference/multi_site_benchmark_v1.json`: Bhote Koshi author-method target; four IIRS/ITS_LIVE glacier-flow measurement controls; and Budhi Gandaki as a separate GUNW no-precursor challenge. Exact AOIs, data IDs and source-byte hashes for the independent sites remain pending.
- [x] Document the run instructions, source/measurement/hazard status separation, per-pixel DEM/vertical-datum requirements, blind test protocol and site-specific limitations in `docs/know-place/REPRODUCIBLE_ENGINE_AND_MULTI_SITE_VALIDATION_20261024.md`.
- [x] Add offline multi-site registry integrity tests. They assert that pending site inputs cannot be marked as scored detections, the five Bhote Koshi P05023 intervals match the author fixture, and GUNW is not scored as GOFF.
- [x] Isolated validation passed on commit `b1768ba0ab6d8b19e0803e88a19f9d494339b867`: [run 40102852943](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40102852943) reported **213 tests passed in 5.10 s**, all eight workflow YAML files parsed, and the pinned actionlint v1.7.12 checksum plus semantic workflow validation passed. This confirms the consent-gated launcher, reusable workflow contracts and multi-site registry tests; raw source downloads remained zero.
- [x] Used Actions → `SARGuardian AOI WKT E2E (safe branch dispatcher)` on `feat/know-place-analysis` → profile `author-exact-p05023`, with exact consent `[run-know-place]`; [run 40114703362] completed raw acquisition and analysis.
- [x] Reviewed all five byte counts/SHA-256 hashes, HDF5 identity/grid checks, pair metrics, output bundle and both remote Drive receipts. See `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`.
- [ ] Verify exact author crown geometry/control sampling and full-footprint mask/golden-output parity.
- [ ] Only after the Bhote Koshi run, freeze AOI/source identities for Samudra Tapu and Bara Shigri; then validate Hubbard/Malaspina and the distinct Budhi Gandaki GUNW case. Do not tune using the final holdout.
- [ ] Do not claim paper parity, movement-detector validation or hazard detection until each distinct gate has its own evidence.

**Status rule:** Exact author raw byte identity is verified (5/5 P05023 payloads, hashes and grid checks) in run 40114703362. Metrics remain exploratory; `PAPER_REPRODUCTION_STATUS=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. This feature branch remains isolated; no merge/change to `main`.


## Latest follow-up status — 2026-10-24

- [x] Downloaded and ZIP-integrity-checked the live CMR catalog artifact from validation run [40102959304](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40102959304). SHA-256: `65e65ae2c4dec384c50ca5a8877e69b705a1861c1e85312026d62512c5dd9386`, matching the GitHub artifact digest.
- [x] Independently inspected the manifest: exact author P05023 CMR identities 5/5 and direct HDF5 URLs 5/5; source payload downloads remain 0/5 and source SHA-256 hashes 0/5.
- [ ] Execute the branch Run Workflow dispatcher with profile `author-exact-p05023`, explicit consent `[run-know-place]`, and configured Earthdata + Google Drive secrets. The available GitHub connection does not expose a workflow-dispatch action, so this step has not been launched from the assistant session.
- [ ] Review raw HDF5 hashes/grid validation, scientific output metrics, and verified Drive-retention receipts after the run. Do not mark paper reproduction or hazard detection complete merely because acquisition succeeds.


## Follow-up — dispatcher consent mismatch (2026-10-24)

- [x] Audited failed dispatcher run [40107037642](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40107037642). Actual input was run-know-place, but raw-source consent requires exact [run-know-place] including both square brackets. The consent job failed before any raw download, processing, or Drive upload; the measurement and exact-author analysis jobs were skipped.
- [x] Improved the gate error and GitHub step summary to state the exact required value; added an automated regression test that rejects the unbracketed near-match.
- [ ] Re-dispatch the branch workflow with profile author-exact-p05023, exact consent input [run-know-place], and valid Earthdata + Drive secrets. Do not start raw acquisition until the exact input is supplied.
- [ ] After an authorized run, verify five source HDF5 byte counts/SHA-256 hashes, grid/identity checks, scientific outputs and both Drive-retention receipts. Do not mark paper reproduction or hazard detection complete merely because acquisition works.


- [x] Audit the latest author-exact live run [40107851266](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40107851266): authenticated download reached the full first HDF5 size of 1,090,519,040 bytes, then was falsely rejected because the validator compared a parser filename with `.h5` against CMR's extension-free granule ID. Fix the filename/stem contract; record source byte count/SHA-256 separately from grid validation; only retry transient transfer failures once with a separate `retry-1` phase. Do not count this failed run as source-hash verification because no hash receipt was preserved by the old code.
- [x] Re-ran isolated CI after the exact-filename/byte-receipt correction: [run 40112528293](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112528293) passed **217 tests in 4.85 s**, all eight workflow YAMLs and pinned actionlint checks. Its live CMR artifact was downloaded and independently verified: SHA-256 `ab1dc5ce3e237649b9c5e404d4c92e6b87c3dae3bf1565dde28e55f66dfe9a49`, matching GitHub's digest; exact P05023 identities/URLs 5/5, raw downloads 0/5. Raw source acquisition still requires explicit `[run-know-place]` dispatch.


- [x] Audit main's last pipeline merge and retry-policy commits; reuse its Earthdata/Drive secret names, pinned science SHA, version/run labels, source-byte expectation, one-attempt-per-worker policy, and bounded receipt-aware `retry-1` handling. No four-attempt large-file retry was introduced.
- [x] Fix raw GOFF false rejection where parser name includes `.h5` but CMR granule name does not. Hash/byte receipts are now saved before HDF5/grid validation, and counts separate downloaded+hashed products from grid-valid products.
- [x] Validate the correction in [run 40109347836](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109347836): 217 tests passed, eight workflow YAML files parsed, and pinned actionlint validation passed. The catalog-only job confirmed exact P05023 IDs/URLs 5/5 with raw downloads 0.
- [ ] With explicit `[run-know-place]` authorization only, run the exact-author source workflow again; inspect each of the five actual payload byte counts/SHA-256 hashes, HDF5 identity/grid receipts, derived metrics, and both Drive receipts. Keep paper-method parity BLOCKED until true author implementation parity is demonstrated; do not substitute X05026.


## Latest follow-up — 2026-10-24 (CI 40112528293)

- [x] Validation [40112528293](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112528293), code/test/workflow/docs commit `cce3052af83d39aa6988301ea5b96b6fd776c82a`: 217 tests passed in 4.85 s; eight workflow YAMLs parsed; pinned actionlint v1.7.12 checksum and semantic checks passed.
- [x] Downloaded and independently verified `know-place-author-exact-live-cmr-access-evidence` (artifact ID `12566734581`, 4,117 bytes), SHA-256 `ab1dc5ce3e237649b9c5e404d4c92e6b87c3dae3bf1565dde28e55f66dfe9a49`, matching GitHub's digest. Manifest: CMR identities 5/5, data URLs 5/5, blocking products 0, raw downloads 0, source hashes 0/5. Evidence: `docs/know-place/evidence/LATEST_CMR_ARTIFACT_INTEGRITY_20261024.md`.
- [x] Confirmed exact-author run [40109347847](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109347847) and legacy run [40112528294](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112528294) skipped raw acquisition because exact `[run-know-place]` consent was absent.
- [ ] Manually dispatch `SARGuardian AOI WKT E2E (safe branch dispatcher)` on branch `feat/know-place-analysis`, profile `author-exact-p05023`, exact consent `[run-know-place]`, and configured Earthdata + Drive secrets. The connected GitHub tools do not expose workflow dispatch, so raw acquisition was not launched from this session.
- [ ] After consented acquisition, inspect all five byte counts/SHA-256, HDF5 identity/grid receipts, analysis outputs and both verified Drive receipts. Keep paper parity BLOCKED and hazard detection NOT_EVALUATED until distinct scientific evidence supports them.

- [x] Latest CMR artifact integrity evidence refreshed to run 40112528293; metadata confirms exact author identities/URLs 5/5, raw source downloads 0/5 and source SHA-256 pins 0/5.

## Latest exact-author raw replay — 2026-10-24

- [x] [Run 40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362) downloaded five exact P05023 GOFF HDF5 products (5,473,566,720 bytes total), verified SHA-256 5/5, HDF5 identity 5/5 and grid validation 5/5 (4311 × 4230, EPSG:32645, 80 m posting). Drive-derived bundle and both receipt uploads report remote verification PASS; raw payloads were not uploaded and temporary raw files were removed after remote retention verification.
- [x] Target pair 2026-07-26 → 2026-08-19 metrics: crown median 0.966063 m; mean vector 1.722246 m at 277.793°; median rate 0.040253 m/day; R=0.852850. These are numerical similarities, not reproduction: crown is a bounding-box approximation and controls are not author-supplement verified. Report status: `NOT_COMPARABLE_EXACT_CROWN_GEOMETRY_UNVERIFIED`.
- [x] Corrected the wrapper's stale status overwrite: after source bytes are pinned, source identity is `FIVE_EXACT_AUTHOR_SOURCE_HASHES_PINNED`; paper reproduction is `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`. The historical artifact retains its pre-fix label. Validation [40115947045](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40115947045) passed 217 tests, eight YAML parses and actionlint checks.
- [ ] Verify author-supplement crown geometry and control sampling, compare golden tables/masks, resolve terrain vertical-datum provenance, and run full-footprint screen parity. Hazard detection remains `NOT_EVALUATED`.

## Latest follow-up — 2026-10-25 (validation 40120575317)

- [x] Independently downloaded and SHA-256-verified author-exact derived artifact from run [40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362): artifact ID 12567509703, 830,510 bytes, SHA-256 `d49b6aa10da27138de6b8b8f2af6a4b5d3ffd86a8ccb87cef7765e3c597a0b59`; it contains diagnostic NPZ/CSV/reports/manifests/receipts and no raw HDF5.
- [x] Five exact P05023 source SHA-256s and grid validations are present in the source manifest; target-pair exploratory metrics are preserved in `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`.
- [!] Historical run's two Drive upload receipts are pre-cleanup and say `raw_source_deleted=false`; do not treat them as post-delete proof. Current workflow now emits, uploads, and validates a separate `author-exact-raw-cleanup-receipt.json` after rehashing all five raw files and confirming zero remain.
- [x] Validation [40120575317](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40120575317), commit `60dcde7cb3b3895d419b14b689201b6d00d3eb07`: **224 tests passed**, eight workflows plus dispatcher parsed, actionlint checksum/semantic checks passed, live exact-author CMR links 5/5, payload downloads 0.
- [ ] A fresh explicitly consented manual replay is still required to test the new post-cleanup receipt end-to-end; latest runs [40120575271](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40120575271) and [40120575285](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40120575285) correctly skipped raw acquisition without `[run-know-place]`.
- Paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection `NOT_EVALUATED`. Main remains unchanged; no merge.


## 23. Independent artifact recheck and latest validation — 2026-10-25

- [x] Re-downloaded artifact `know-place-author-exact-40114703362-1` (ID `12567509703`); independently recomputed SHA-256 `d49b6aa10da27138de6b8b8f2af6a4b5d3ffd86a8ccb87cef7765e3c597a0b59`, matching GitHub's digest. No raw HDF5 is in the artifact or its derived bundle.
- [x] Independently verified the five manifest entries are exact `P05023`, all download/hash/HDF5 identity/grid checks pass, and total source bytes are 5,473,566,720. Grid: 4311 × 4230, EPSG:32645, 80 m posting. See `docs/know-place/evidence/AUTHOR_EXACT_ARTIFACT_INDEPENDENT_RECHECK_20261025.md` for all five hashes and per-pair counts.
- [!] Both historical Drive receipts say `raw_source_deleted=false`; they prove remote verification of the derived bundle/receipt copy, not post-delete cleanup. The new post-cleanup receipt path was added later but is not yet exercised end-to-end.
- [x] Latest validation [40121243012](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40121243012), commit `56ef9f52977a7ac6a0c314b8560bfe4ff27743b0`: **224 tests passed in 2.58 s**, eight workflow YAMLs plus branch dispatcher parsed, pinned actionlint checksum/semantic validation passed; live CMR/data links confirmed 5/5 and raw downloads stayed 0.
- [x] Latest legacy run [40121243034](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40121243034) skipped acquisition because the exact consent marker was absent. No new raw products were downloaded in that run.
- [ ] Manually dispatch the author-exact workflow with exact `[run-know-place]` and configured Earthdata/Drive secrets to test post-cleanup receipt; do not infer consent from a prior request.
- Paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; do not merge or write to main.


## Independent archive polygon-null replay — 2026-10-25

- [x] Independently recomputed R from east/north bands in the five exported site-field TIFFs, replayed the archive's `code/polygon_null.py` sampling algorithm in chronological pair order, and compared all nine stored metrics for each pair against `tables/polygon_null.json`: **45/45 exact matches at archive rounding, zero mismatches**. Evidence: `docs/know-place/evidence/AUTHOR_ARCHIVE_POLYGON_NULL_REPLAY_20261025.md`.
- [x] Confirmed the exact post-hoc control analysis is reproducible from the archive's derived fields. This is not the paper's published method, does not prove raw-GOFF-to-field parity, and does not close the full-footprint screen gate.
- The separate post-cleanup Drive receipt still needs a fresh explicitly consented manual run. Paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. No merge or write to `main`.


## Author-compatible raw site-series path — 2026-10-25

- [x] Added a separate tools/know_place/author_raw_site_series.py; it uses the author's nearest-crown radar-grid cell and height-axis median geometry, the archived SNR >= 5 / magnitude <= 10 m mask (no added correlation gate), conditional outside-AOI reference correction only when more than 200 valid ring pixels exist, and separate P1/site-series versus polygon-null coherence estimands.
- [x] Added unit tests for the author geometry estimator, quality/reference policy, deterministic null sampling, fixed author WKT bounds and 65 benchmark comparisons. Added compile/test coverage to .github/workflows/know-place-analysis-validation.yml.
- [x] Integrated the separate profile into author_exact_acquisition.py so it processes the same five already downloaded raw products after the exploratory run; no second acquisition is performed. The final raw-replay gate requires all five pairs and 65/65 Table S4 archive-metric comparisons. A mismatch leaves the report and retention receipts available, but fails the workflow rather than forcing a match.
- [x] Validation [40126196592](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40126196592), commit 20c7d7b5c43d8b60b0361726ce605a65376936ac: **229 tests passed**, all eight workflow YAMLs plus the branch launcher parsed, pinned actionlint semantic validation passed, and live exact-author CMR preflight confirmed five P05023 links without downloading raw payloads.
- [x] On this commit, both raw replay workflows correctly passed their no-consent gates and skipped the expensive acquisition jobs; **new raw downloads = 0**. This is not an end-to-end raw replay result.
- [ ] Run the new author-compatible profile against the five pinned P05023 HDF5 files on an explicitly consented manual dispatch; examine all 65 comparisons and the independently generated site-series CSV/NPZs. The exact consent input [run-know-place] has not been given in this turn.
- [ ] Complete the independent full-footprint pixelwise screen comparison and terrain/vertical-reference sensitivity. No hazard-detection performance claim.
- Global paper reproduction remains unverified until the consented source-level run actually matches; hazard detection remains NOT_EVALUATED. Main remains 2218dfeb73353080d8d94bd733d9e7bd9a848886; no merge or write to main.


## Processed-field site-series cross-check — 2026-10-25

- [x] Independently recomputed five site-series rows from the archive's five cropped field TIFFs and compared exact valid-crown counts plus displacement median, daily rate, P1 crown R and P1 scene R to the original tables: **25/25 matches, zero mismatches**. Evidence: docs/know-place/evidence/AUTHOR_ARCHIVE_SITE_SERIES_REPLAY_20261025.md.
- [x] Separate post-hoc polygon-null replay remains 45/45 at stored precision: docs/know-place/evidence/AUTHOR_ARCHIVE_POLYGON_NULL_REPLAY_20261025.md. These checks are from processed fields, not direct replay from raw GOFF.
- [ ] Run raw-source author-compatible site series on the exact five P05023 HDF5 files and require 65/65 Table S4 metric comparisons before marking the site-series table matched. This is not authorized in the absence of explicit [run-know-place] consent.
- [ ] Keep full-footprint screening raster parity and hazard-detection validation as separate incomplete gates.


## Latest status addendum — 2026-10-25 (commit `f56db40f6f82b4ff2769b77023ff5a3d5a051fbd`)

- [x] Verified latest isolated CI: [run 40133358388](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40133358388) passed **238 tests**, eight workflow YAML parses and pinned actionlint v1.7.12 semantic validation. Live ASF identity checks passed without downloading raw payloads.
- [x] Corrected the workflow shell line continuations flagged by actionlint/shellcheck. The archive download uses an exact SHA-256 gate; three extracted terrain rasters are each hash-pinned.
- [x] Integrated `tools/know_place/author_footprint_replay.py` into `.github/workflows/know-place-author-exact-replay.yml`: after a newly consented run it will reprocess all five exact P05023 native grids using author-compatible per-pixel geometry and screening; compare the three full-footprint golden rasters, all 106 final candidate rows with the author’s `quality` flag and score ordering, plus the 101 quality-passing Table S7 zones; retain the replay report and derived maps through the existing private Drive upload/receipt flow; then delete raw GOFF only after verified derived retention.
- [x] The full-footprint gate is fail-closed: it requires 3/3 aggregate raster matches, 106/106 final candidate attributes including final score/quality/rank ordering, 101/101 final quality-passing Table S7 rows, and 106 connected candidate components. This is a code and CI integration gate only; **the actual full-footprint replay has not yet run**.
- [x] `main` remains unchanged at `2218dfeb73353080d8d94bd733d9e7bd9a848886`; all changes remain isolated on `feat/know-place-analysis`.
- [ ] Re-dispatch the author-exact workflow only with explicit `[run-know-place]` consent to reacquire the five raw files and run P2 + full-footprint parity. Without this marker the raw acquisition step is skipped.
- [ ] Resolve displacement-null parity from source script/draw-level controls if obtainable. The supplied Zenodo package contains summary values but not the generator needed to independently recreate those three Table S4 columns.
- [ ] Keep hazard-detection performance unevaluated until independent event-level controls, precision/recall, false-alarm and lead-time analysis exist.

Current scientific status (supersedes earlier interim snapshots): `PAPER_REPRODUCTION_STATUS=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`.


## Candidate-score chain correction — 2026-10-25

- [x] Corrected the previous provisional-score interpretation after inspecting `code/fix_zonal_attrs.py` (SHA-256 `3614d1f632e35dbcdecab8389f38e50674a087813cbefdaa2b8c027b0ebe18cb`). The archive's final inventory is produced by a three-step chain: `wide_screen.py` writes provisional centroid score; `candidate_attributes.py` adds `R_res` and terrain fields; `fix_zonal_attrs.py` replaces `n_epochs` by the zone maximum and `anom_m` by the zone mean, then calculates `score = n_epochs * anom_m * R_res` and `quality = (R_res >= 0.75) & (d_downslope < 45)`.
- [x] Superseded the initial 0/106-vs-106/106 output interpretation. It compared the final inventory against an intermediate score formula and omitted the explicit final post-processing script; it was not evidence of a source/archive contradiction. See revised `docs/know-place/evidence/AUTHOR_CANDIDATE_SCORE_CONTRACT_AUDIT_20261025.md`.
- [x] Updated the raw-source runner to reproduce final zonal `n_epochs`, zonal `anom_m`, pooled `R_res`, final score and combined `quality` flag. Pure downslope directional agreement is now tracked separately from the author quality flag.
- [x] Updated the workflow gate to compare all 106 final candidate records, 101 final quality-passing Table S7 rows and all three aggregate footprint rasters. A numerical mismatch is retained as an explicit report and cannot be promoted to a successful reproduction claim.
- [ ] Run a new five-pair replay only after the remaining source-level scope and consent gate are satisfied. No new raw HDF5 download occurred during this score-chain correction.
- Hazard detection remains `NOT_EVALUATED`; `main` remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`.


## Latest follow-up — full-footprint score/order semantics and CI (2026-10-25)

- [x] Fixed and source-audited the three-stage candidate attribute chain. The final candidate table now uses zone-max `n_epochs`, zone-mean `anom_m` rounded to 3 decimals, pooled hit-pixel `R_res`, final `score=n_epochs*anom_m*R_res`, and final `quality=(R_res>=0.75) & (d_downslope<45)`, matching the pinned archived `fix_zonal_attrs.py` semantics. The provisional screen's centroid `R` is kept as a separate column.
- [x] Added strict score-ranking order parity for the 106 final candidates. Source inventory must be descending by final score, computed score ordering must preserve every non-tied rank relationship, and only score ties within the comparison tolerance can remain unordered.
- [x] Separated pure downslope directional agreement from the author's final `quality` flag. The 101 Table S7 target is now explicitly the 101 final `quality=True` rows, not an assumed pure directional-pass count.
- [x] Latest isolated validation [run 40135538667](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40135538667) passed **238 tests in 6.79 s**; all eight workflow YAML files parsed; actionlint v1.7.12 checksum/semantic validation and live ASF exact-product identity checks passed.
- [x] Verified push-triggered raw replay gate [run 40135538673](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40135538673): the consent evaluator passed but the heavy five-product acquisition/analysis job was **skipped**. New raw downloads in that run were **0**. This is not a full-footprint source replay result.
- [ ] After an explicitly consented manual dispatch, require actual 3/3 raster parity, 106/106 final candidate/rank parity, 101/101 Table S7 parity, 65/65 site-series checks and 15/15 P2 checks. The displacement-null three columns per interval remain independently unresolved unless the author’s exact draw-level method can be sourced.
- Scientific status remains `PAPER_REPRODUCTION_STATUS=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. Numeric Table S4 coverage is 95/95 at stored precision; original null-generator/draw identity, source crown vector and RGI 6.0 overlay remain unverified. `main` remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`.


## Combined scientific-result state guard — 2026-10-25

- [x] Corrected a reporting weakness found during source audit: full-footprint raster/candidate parity alone must not produce a combined “site and footprint numerics match” status. The combined status now independently gates the 65/65 site-series table comparisons, the 15/15 P2 table comparisons, source-processing status, and full-footprint outputs.
- [x] Added pure status-assessment logic plus synthetic regression tests for site-series mismatch, P2 mismatch, footprint mismatch, and joint success/failure. The workflow keeps component statuses separate and marks the overall scientific screen complete only when the relevant site/P2 and footprint gates all pass.
- [x] Integrated the helper into the final-report step and isolated CI file lists. This change requires no raw product downloads.
- [ ] Run the newly integrated raw-source site + full-footprint analysis only after explicit `[run-know-place]` authorization. Raw source replay remains unrun in this follow-up; paper reproduction is not promoted, and hazard detection remains `NOT_EVALUATED`.


## Full-footprint input path wiring fix — 2026-10-25

- [x] Source audit found the footprint step was reading its config and source manifest from the top-level run directory, while `author_exact_acquisition.py` writes the durable copies into `derived/` and the working copies into `source-run/`. The old paths would block the footprint screen after site analysis finished.
- [x] A second path-resolution check found that the copied config contains relative product paths `raw/<filename>`. Therefore the footprint command must use the active config under `source-run/`, where `raw/` actually exists; the copied config under `derived/` is provenance only.
- [x] Corrected the footprint step to use `source-run/know-place-inputs.json` and `source-run/author-exact-source-manifest.json`; this resolves both the config-directory mismatch and the relative raw-product paths.
- [x] Strengthened the regression test to require the active source-run paths and reject the derived-copy path. No HDF5 product was downloaded or processed for this fix.
- [ ] The corrected path wiring still requires a future explicitly consented manual replay to validate the complete raw-source + footprint run. Do not claim full-footprint parity before that run.


## Status vocabulary hardening — 2026-10-25

- [x] Split comparison status into `PASS`, definitive `MISMATCH`, and `INCOMPLETE`. Missing processing outputs or missing/partial comparison sets no longer get mislabeled as a scientific parity mismatch.
- [x] Added synthetic regression tests for absent footprint outputs and incomplete site comparison reports. Actual source replay remains a separate consent-gated validation; no raw payloads were downloaded for this code change.


## Dashboard-bearing reproduction milestone — 2026-10-25

- [x] Add an author-exact dashboard renderer fed by the retained derived Run #17 bundle, with embedded scientific previews and publisher-attributed optical context images.
- [x] Keep author P1 and P2 values separate; show the selected archive comparison counts, exact source SHA-256 values, crown-geometry caveat, datum caveat, and unresolved displacement-null status.
- [x] Add regression tests for the standalone HTML, five embedded PNG previews, run/source provenance, status labels, and Bengali plain-language explanation.
- [x] Include the dashboard renderer and tests in the isolated validation workflow.
- [x] Add dashboard generation to the author-exact replay workflow and require a successful dashboard output in the final scientific/retention gate.
- [x] Add a safe, separate workflow that renders from a prior retained Actions artifact without downloading raw NISAR payloads; add it to YAML/actionlint checks and path filters.
- [x] Run the dedicated safe renderer workflow on source run ID `40170290176`, attempt `1`; [Run #19](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766) verified source digest/ZIP integrity, rendered the dashboard, uploaded HTML + manifest to Drive, remotely verified both receipts, and published artifact [12596788838](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766/artifacts/12596788838). Raw HDF5 downloads in this render run: 0.
- [ ] Inspect the rendered dashboard on mobile and desktop, especially satellite-image attribution, source/map distinctions, status badges, accessibility and complete source provenance.
- [ ] Reproduce the displacement-null draw-level calculation; until it is available and verified, keep the paper status partial.
- [x] Verify published-bounds rectangle/native-grid mask consistency on Run #17: five pairs pass, four mask-XOR comparisons per pair are zero, and valid displacement/coherence counts match their separate published table fields. Evidence: `docs/know-place/evidence/RETAINED_RUN17_CROWN_AUDIT_20261025.md`.
- [ ] Verify byte-level parity against the original author editable crown vector or golden source-grid mask; neither is supplied in the reviewed archive.
- [ ] Run separately labelled vertical-datum sensitivity analysis; do not silently change source-faithful geometry.
- [ ] Complete preregistered multi-event and non-event validation before estimating detection skill, false alarms, or lead time.
- [ ] Do not merge to or edit `main` until the dashboard-bearing E2E and scientific acceptance gates are independently reviewed.

- [x] Safe dashboard E2E completed in [Run #19](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766); Drive remote verification passed for dashboard + manifest, receipt copy passed, and GitHub artifact [12596788838](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766/artifacts/12596788838) was published.
- [ ] Next scientific gate: recover/reproduce displacement-null draw-level sampling and percentiles. Do not replace this with the polygon-null coherence percentile.

## Local Run #17 dashboard package and source-image correction — 2026-10-25

- [x] Download and verify source artifact ID `12589719900` against GitHub SHA-256 `a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`.
- [x] Confirm the derived-only archive contains no raw HDF5; verify all five source hashes shown in the dashboard against the source manifest.
- [x] Cross-check selected comparison totals: 65/65 site-series, 15/15 P2, 3/3 aggregate rasters, 106 candidate rows, and 101 Table S7 rows.
- [x] Add provenance manifest and package the standalone HTML plus scientific preview PNGs for review.
- [x] Replace the old Geopera cover imagery with the corrected WorldView-3 stereo-elevation-change image and document the original article's explicit retraction.
- [x] Run isolated CI after the image-source correction: [40187665186](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40187665186) passed 256 tests, all nine workflow YAML checks and pinned actionlint.
- [x] Dispatch `render-author-dashboard` through the shared branch dispatcher. [Run #19](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766) confirms dashboard artifact [12596788838](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766/artifacts/12596788838), Drive HTML/manifest upload and remote receipt-copy verification; no raw NISAR download occurred.
- [ ] Finish displacement-null draw-level parity and exact crown/source-grid mask verification before declaring complete paper reproduction.
- [ ] Keep hazard detection `NOT_EVALUATED` until independent held-out event/non-event evaluation is complete.
- [ ] Do not merge to or edit `main` until the dashboard-bearing E2E and separate scientific acceptance gates pass.

## Source-code audit: displacement-null gap — 2026-10-25

- [x] Inspected all Zenodo archive members and searched all bundled Python scripts for the displacement-null generator.
- [x] Confirmed `tables/displacement_null.json` is a five-row summary only; the source archive has no draw-level records or displacement-null sampling script. `polygon_null.py` is a coherence-R null and is not a substitute.
- [x] Reconciled 292 versus 298: displacement-valid `n=292` and coherence-valid `n_px=298` are separate metrics for 26 July–19 August 2026.
- [ ] Implement a separate method-derived displacement-null reconstruction on archived offset fields, retain every draw and rejection reason, pin seed/PRNG and all sampling policy choices, and compare the five aggregate rows without tuning to force agreement.
- [ ] If the exact author draw generator cannot be recovered, label outputs independent/method-derived and keep whole-paper status partial; never call the 94.7th percentile a detection.
- [x] Verify published-bounds crown rectangle against retained native-grid masks (see real-artifact audit); the reconstructed rectangle's ellipsoidal/projected areas both round to 2.07 km².
- [ ] Acquire an original author editable crown vector/golden mask if byte-level author geometry parity is required, then complete remaining terrain vertical-datum/source-level parity. Multi-site event/non-event validation remains required before any hazard-detection claim.

## First displacement-null reconstruction — 2026-10-25

- [x] Add a separately named method-derived displacement-null module with versioned seed, PRNG, region, centre-selection and acceptance assumptions.
- [x] Retain all 1,200 attempted centres per pair, rejected-draw reasons, accepted median values, source-field SHA-256/CRS/grid metadata, and comparison with published aggregate rows.
- [x] Run on all five supplied processed-field GeoTIFFs without reading raw HDF5; observed crown median values round to published two-decimal values.
- [x] Add deterministic and policy-validation regression tests and wire module/test into isolated CI.
- [ ] Run predeclared policy sensitivity over plausible compact-region and acceptance choices; do not tune to obtain published percentiles.
- [ ] Recover author draw-level implementation/output if available; otherwise retain independent-method-derived label and paper status PARTIAL.
- [ ] Verify exact crown source-grid mask and run a separate terrain vertical-datum sensitivity before proceeding to preregistered multi-site validation.
- [x] Test alternate compact-region geometries (disk, square, diamond) at fixed seed/fraction and preserve the five-pair results in DISPLACEMENT_NULL_SHAPE_SENSITIVITY_20261025.csv; no geometry was selected by result closeness.


## Current scientific gate update — crown/source-grid mask audit (2026-10-25)

- [x] Add a deterministic audit for the retained Run #17 derived-only artifact and SHA-256-pinned Zenodo archive; ZIP integrity passes and no raw HDF5 members are present.
- [x] Compare the published WGS84 rectangle using independent native-grid cell-centre inverse projection, the saved endpoint/searchsorted crop, and the halo diagnostic mask.
- [x] All five pairs have 323 crown-mask cells; every mask XOR comparison is zero after mapping the arrays to global source-grid row/column coordinates.
- [x] Confirm displacement-valid crown counts 283/294/296/292/195 against series-table n and coherence-valid counts 302/299/302/298/202 against polygon-null n_px. These are separate estimands.
- [x] Correct the stale generic geometry test fixture; old bounds selected 306 cells and omitted 17 west-edge cells, while the exact published bounds select 323.
- [x] Wire the new audit module and tests into isolated CI.
- [ ] Obtain the original editable author crown vector or golden source-grid mask. Current PASS proves saved-mask/published-bounds consistency, not independent source-vector parity.
- [ ] Reproduce the displacement-null draw-level generator; do not substitute coherence polygon-null values.
- [ ] Run separately labelled vertical-datum sensitivity, then preregistered held-out multi-site event/non-event validation.
- [ ] Keep overall paper status partial and hazard detection NOT_EVALUATED until distinct acceptance gates pass.
- [ ] Do not merge to or edit main without review and explicit approval.

Evidence: docs/know-place/evidence/CROWN_MASK_AUDIT_20261025.md and CROWN_MASK_AUDIT_20261025.json.


## Multi-site Himalayan source geometry audit — 2026-10-25

- [x] Audit the IIRS comparison article's public text; record the January 2026 label and published ranges without inventing exact pair timestamps, product IDs or AOI vectors.
- [x] Record source leads for the legacy RGI 6 IDs and Bara Shigri's literature-cited RGI 7 identifier.
- [x] Keep Samudra Tapu's RGI 7 ID unfilled because this audit has not resolved it from the official source table.
- [x] Add a machine-readable lead ledger and tests that prevent these leads from becoming fake exact AOIs or scored validation cases.
- [ ] Acquire and hash the official RGI 7 Region 14 archive; resolve Samudra Tapu's RGI 7 ID; extract and hash the actual polygons.
- [ ] Treat RGI outlines only as independent inventory-outline ROIs, not as the IIRS authors' exact mask or a date-matched January 2026 ice margin.
- [ ] Recover exact NISAR pair/granule metadata and pinned ITS_LIVE version before catalog scoring. No raw download without explicit consent.
- [ ] Keep hazard detection NOT_EVALUATED until held-out multisite event/non-event evaluation is performed.
Evidence: docs/know-place/evidence/MULTISITE_REFERENCE_GEOMETRY_AUDIT_20261025.md and docs/know-place/reference/multi_site_source_geometry_leads_20261025.json.


## Latest verified state — 2026-10-25

- [x] Run isolated validation on source-geometry leads commit: [40198744624](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40198744624), 266 tests passed, all workflow YAML and pinned actionlint checks passed; live ASF/CMR metadata-only gates passed.
- [x] Confirm linked raw-replay gate [40198744626](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40198744626) skipped analysis at the explicit consent guard. New raw NISAR GOFF downloads: 0.
- [x] Confirm main remains 2218dfeb73353080d8d94bd733d9e7bd9a848886.


## Latest exact-source provenance and safety gate — 2026-10-25

- [x] Strengthened `tools/know_place/crown_mask_audit.py` to pin and validate the five exact `P05023` identities, pair intervals, CMR concept IDs, byte counts, SHA-256 values, grid/HH/layer2 metadata, and all expected identity checks. Manifest product count alone is no longer accepted as provenance.
- [x] Validate the exact manifest-byte SHA in the post-delete receipt and compare all five deleted-source filename/byte-count/SHA rows to the pinned source identities. The gate fails closed on missing/duplicate hashes, a wrong interval/grid/collection, zero bytes, `X05026` substitution, manifest-receipt SHA tampering, or a deletion-receipt hash mismatch. This is manifest/receipt consistency evidence—not a re-hash of deleted raw HDF5.
- [x] Validation [40199955962](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40199955962), commit `27ecf27d290f3b0dd8c3c1a4da7df5f787924a94`: **276 tests passed in 4.80 s**, nine workflow YAML files plus branch dispatcher parsed, pinned actionlint v1.7.12 checksum and semantic checks passed, live ASF/CMR identity gates passed without payload download.
- [x] Matching raw replay gate [40199956018](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40199956018) passed its consent check and skipped the expensive analysis job. No new raw GOFF payloads were downloaded.
- [x] Independently re-checked `main` remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; all work remains on `feat/know-place-analysis`.
- [ ] Original author editable crown geometry/golden mask and exact control sampler: still not supplied/verified.
- [ ] Full-footprint raw-source regeneration and pixelwise comparison to author golden rasters: still not executed; it requires the explicit `[run-know-place]` authorization for any expensive raw replay.
- [ ] Independent multi-site source outline hashes, exact pair IDs and pinned comparator versions: pending.
- [ ] Hazard-labelled independent test set and out-of-sample event-detection metrics: pending; keep `HAZARD_DETECTION_STATUS=NOT_EVALUATED`.

**Finishing rule:** engineering closure means deterministic artifacts, source/receipt integrity gates, passing CI and documented blockers. It does **not** mean scientific reproduction or hazard-detector validation until those remaining gates have their own independent evidence. See `docs/know-place/evidence/SOURCE_PROVENANCE_GATE_20261025.md`.


## Latest real retained-artifact audit — 2026-10-25

- [x] Added `.github/workflows/know-place-retained-crown-audit.yml` to retrieve and audit the existing derived-only Run #17 artifact; its CI job downloads no raw HDF5. The workflow verifies the frozen 183,389,034-byte, SHA-256-pinned Zenodo archive, re-packs the retained Run #17 files only to run the existing ZIP auditor, and preserves a JSON report.
- [x] Real retained-artifact audit [Run #40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570): **PASS**, 5/5 intervals, all four mask-XOR comparisons zero, valid displacement counts and coherence counts match the two respective published fields for all five pairs, and raw HDF5 members are 0 in both outer and nested archives. Machine-readable output is retained as artifact `know-place-real-retained-crown-audit` (ID `12601033322`).
- [x] The paper's published crown rectangle has computed WGS84 geodesic area 2.072644 km² and EPSG:32645 planar area 2.072046 km²; both round to its stated 2.07 km². This supports the published-bounds rectangle interpretation but does not claim original author-vector/golden-mask identity.
- [x] Validation [Run #40200875500](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875500): **276 tests passed in 2.69 s**, ten workflow YAML files plus branch dispatcher parsed, actionlint v1.7.12 checksum/semantic checks passed, and live ASF/CMR metadata-only identity gates passed.
- [x] Raw replay gate [Run #40200875484](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875484) skipped the five-pair analysis job; no raw GOFF payloads downloaded.
- [ ] Exact displacement-null generator/sampling-policy parity and independently verified author golden mask/vector remain unresolved; full-footprint numeric replay still requires explicit `[run-know-place]` authorization.
- [ ] Paper reproduction remains **PARTIAL**; hazard detection remains `NOT_EVALUATED`. `main` remains unchanged.

See `docs/know-place/evidence/RETAINED_RUN17_CROWN_AUDIT_20261025.md` for the actual artifact hashes and all five per-pair outcomes.


## Consolidated finishing gate — exact-author replay Run 40170290176 (2026-10-25)

This section supersedes earlier interim status snapshots above where they say P2 or full-footprint numeric comparison is still pending.

- [x] Replayed the five exact P05023 HDF5 sources and verified payload hashes/grid; source payloads were removed only after the derived bundle and both receipt paths were remotely verified. Source artifact: [Run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), GitHub artifact digest SHA-256 `a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`.
- [x] Pass the author site-series and post-hoc site/polygon comparison: 65/65 checks, 0 mismatches.
- [x] Pass the halo-aware local-mean P2 comparison: 15/15 Table S4 fields (five pairs × crown R, background R, resolved flag), 0 mismatches. This uses per-pixel DEM-interpolated geometry, a 41 × 41 local mean and a 22-pixel context halo before the 5 × 5 coherence calculation.
- [x] Pass all three author aggregate footprint raster comparisons and the inventory comparisons. The flagged-epoch raster matches all 18,235,530 grid cells exactly; the two finite aggregate rasters have 0 mask/value mismatches across 4,008 finite cells. All 106 candidate rows and 101 Table S7 numeric rows match under the report's declared tolerances, with no ranking inversions across 5,564 comparisons. Exact RGI6 glacier-class and nearest-glacier overlay columns were not compared.
- [x] Pass retrospective retained crown-mask/source-provenance audit on the same evidence family: [Run 40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570), 5/5 intervals, 323-cell mask each, XOR=0 for all saved-mask/grid comparisons. Original author editable vector/golden-mask parity remains unverified.
- [x] Isolated code/workflow CI: [Run 40201602657](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40201602657), 276 tests passed; all ten Know Place workflows plus dispatcher parsed; pinned actionlint v1.7.12 checksum and semantic workflow validation passed. Paired raw gate [Run 40201602688](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40201602688) skipped the expensive job without explicit `[run-know-place]`; no new raw products were downloaded by these CI runs.
- [x] Reconstruct the displacement-null Table S4 numeric outputs from the deposited derived fields using a deterministic source-inspired random-disk/60%-support policy. All five crown summaries, null medians and percentiles match stored precision (15/15 output fields); see docs/know-place/evidence/DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md and its machine-readable companion JSON.
- [ ] Recover the original displacement-null generator or author draw/rejection history. Numeric output parity is observed, but exact source-code/draw-sequence identity remains UNVERIFIED; do not claim reconstructed accepted counts are author counts.
- [ ] Verify exact author editable crown vector/golden mask, source RGI 6.0 geometry for glacier attribution, and original terrain tile-byte provenance. The published bounds/native-grid mask consistency PASS is not the same as original vector identity.
- [ ] Evaluate hazard-detection skill only on independent labelled events/controls with separated validation/test splits. Current status remains `HAZARD_DETECTION_STATUS=NOT_EVALUATED` and `OPERATIONAL_WARNING_STATUS=NOT_IMPLEMENTED`.

**Current scientific decision:** `PAPER_REPRODUCTION_STATUS=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`. All 95 Table S4 numeric values now match stored precision across P1/P2/core checks plus the source-inspired displacement-null reconstruction. The exact original displacement-null generator/draw history remains unverified, as do original crown-vector identity, exact RGI6 overlay and independent hazard-skill evaluation. This does not demonstrate prospective landslide/glacier-collapse detection.


## Displacement-null numeric reconciliation — 2026-10-25

The former statement that all 15 displacement-null values were numerically blocked is superseded. A deterministic reconstruction of the deposited dE/dN fields now matches the five crown values, five null medians and five percentiles at archive precision. Numeric Table S4 coverage is 95/95, but the exact generator and original draw-level history are absent from the reviewed Zenodo archive. See docs/know-place/evidence/DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md. Keep whole-paper status PARTIAL and hazard detection NOT_EVALUATED.


## Engineering finishing gate — refreshed 2026-10-26

- Latest isolated validation: [Run 40221064296](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40221064296) — **281 passed**, all 11 Know Place workflows plus the dispatcher parsed, actionlint checksum verified and semantic workflow validation passed.
- Latest paired raw-replay consent gate: [Run 40221064385](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40221064385) — consent-check job passed; raw five-pair analysis job was **SKIPPED**. No new raw HDF5 payloads were downloaded by this gate.
- Derived-only displacement-null replay: [Run 40219393283](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283) — PASS at archived precision for all five pairs and all 15 numeric displacement-null outputs. Full JSON artifact: [ID 12608431799](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283/artifacts/12608431799); compact repository report: docs/know-place/evidence/DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.json.
- Confirmed current main SHA remains 2218dfeb73353080d8d94bd733d9e7bd9a848886. All work and documentation remain isolated to feat/know-place-analysis; no merge to main was performed.
- Engineering closure for the currently verified derived-only scope: **PASS**. Numeric Table S4 comparison: **95/95 at published precision**, with the displacement-null numeric reconstruction clearly labelled source-inspired. Scientific full-paper closure: **PARTIAL**, because original displacement-null generator/draw history, editable crown vector/golden mask, exact RGI 6.0 polygon overlay and original terrain byte provenance are not established. Hazard-detection skill remains NOT_EVALUATED; operational warning remains NOT_IMPLEMENTED.

See docs/know-place/evidence/FINISHING_GATE_20261025.md for the consolidated decision and remaining release gates.


## Interactive arbitrary-AOI result map — 2026-10-26

- [x] Add a separate internet-enabled Leaflet/OpenStreetMap map output while preserving the offline dashboard.
- [x] Generate the interactive map for both catalog-only dry runs and measurement reports; show AOI boundary, pair selection, approximate displacement preview, opacity/AOI controls, quality support, source provenance and native-grid GeoTIFF link.
- [x] Explicitly add `tools/tests/test_know_place_interactive_map.py` to the isolated validation workflow's test list.
- [x] CI [run 40224867156](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40224867156): 287 tests passed; compile, YAML parsing, actionlint and metadata-only catalog gates passed.
- [x] Push replay gate [run 40224867157](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40224867157) skipped the raw analysis job because no `[run-know-place]` marker was present.
- [x] Real measurement result browser smoke passed in Chromium from the retained exact-author derived-only artifact: [map render run 40237180566](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566), artifact [12615556980](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566/artifacts/12615556980). All 16 checks passed, including crown-only preview masking, five pair controls, 26 Jul–19 Aug selection and zero JS page errors; screenshot recorded.
- [ ] Full scientific measurement, paper-method reproduction and event-level detector skill are separate gates; `HAZARD_DETECTION_STATUS=NOT_EVALUATED` remains unchanged.


## AOI workflow failure correction — 2026-10-26

- [x] Root-caused catalog maturity/query, polarization normalization and release-variant selection failures from live Actions logs.
- [x] Add exact release allowlist to request schema/hash/manifest and workflow inputs; blank selection never silently resolves an ambiguous release.
- [x] Add regression tests for request release IDs and filtering X05026 when P05023 is explicitly selected.
- [x] Live ASF dry-run smoke test [run 40228894456](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40228894456): `CATALOG_AND_SERIES_PLAN_READY`, 8 eligible PROVISIONAL candidates, 4 selected P05023 pairs; offline and interactive map HTML outputs present.
- [x] CI passed: 294 tests plus Python compile, workflow YAML, actionlint, live ASF identity and CMR link gates.
- [x] Raw replay consent gate [run 40228894462](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40228894462) skipped raw five-pair processing; no raw HDF5 downloaded by the fix.
- [ ] Browser/device visual smoke test and real displacement measurement for the newly selected generic AOI remain pending; catalog dry-run is not a scientific measurement.
- [ ] Full paper reproduction remains partial and hazard detection remains `NOT_EVALUATED`.


## Live author-exact measurement and latest null audit — 2026-10-26

- [x] Run the explicitly authorized Bhote Koshi five-pair replay using exact P05023 only: [run 40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596), complete success.
- [x] Validate five of five exact CMR identities, payload byte counts, SHA-256 hashes and HDF5 grids (4311 × 4230, EPSG:32645, 80 m); source evidence is preserved in the Actions artifact and `docs/know-place/evidence/AUTHOR_EXACT_P05023_MEASUREMENT_20261026.md`.
- [x] Compute the five-pair exploratory displacement series and archive-compatible site/P2 path; 65/65 site-series and 15/15 P2 numeric checks pass at archive rounding.
- [x] Compare full-footprint author aggregate rasters (3/3), candidate inventory (106/106), validated zones (101/101), and score/ranking gates.
- [x] Upload the derived-only bundle and receipts to private Drive, remotely verify both, then delete the five raw HDF5 files. Post-delete receipt: raw HDF5 remaining 0; raw HDF5 uploaded false; cleanup receipt upload/verification PASS.
- [x] Run source-inspired displacement-null reconstruction from deposited derived GeoTIFFs only: [run 40233222258](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258), all five published crown/null medians and percentiles matched at table precision (15/15 numeric fields). See `docs/know-place/evidence/DISPLACEMENT_NULL_ARCHIVE_RECONSTRUCTION_20261026.md`.
- [x] Validate current source/dependency and workflow paths: [run 40233222222](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222222) passed.
- [ ] Original displacement-null generator/draw identity, exact RGI 6.0 overlay, DEM-to-radar-grid vertical-datum transformation, and native-grid pixel-mask edge-inclusion parity for the author-script rectangular AOI remain unverified. Archive code audit found a published rectangular AOI/crop, not a separate editable crown-vector file; keep whole-paper reproduction `PARTIAL`.
- [x] Inspect the real-measurement output through the interactive map and complete headless Chromium desktop/browser smoke: run 40237180566, artifact 12615556980; all 16 desktop assertions pass. The presentation overlay is masked to valid crown support.
- [x] Complete responsive headless Chromium QA against the retained real-measurement bundle: [run 40240016012](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40240016012), artifact [12616437285](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40240016012/artifacts/12616437285). Four viewports passed: 360×800, 390×844, 768×1024, 844×390; no horizontal overflow, map/control visibility/size and critical-pair selection all PASS. A long SHA-256 string was the viewport-expansion root cause; text wrapping fixed it. See `docs/know-place/evidence/INTERACTIVE_MAP_RESPONSIVE_BROWSER_QA_20261026.md`.
- [ ] Manual testing on a physical mobile device remains pending (headless mobile emulation is not a physical-device test). A browser test against a generic arbitrary-AOI measurement bundle also remains pending; no such new raw measurement was run.
- [ ] Independent labelled multi-event/non-event validation remains pending. `HAZARD_DETECTION_STATUS=NOT_EVALUATED`; operational warning remains `NOT_IMPLEMENTED`.
- Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no main edits or merges.
