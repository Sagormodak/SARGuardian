# Know Place Analysis — Living Context (read first)

**Last reviewed:** 2026-10-26  
**Explicit raw-replay authorization:** On 2026-10-26, the user explicitly authorized one Bhote Koshi five-pair replay using the exact author `P05023` release and supplied `[run-know-place]`. Scope is limited to `feat/know-place-analysis`: download the required exact raw GOFF inputs, compute the exploratory displacement metrics, and use the workflow's existing private Drive retention/verification path. This is not authorization to edit or merge `main`. The new execution remains unverified until its run logs and outputs are inspected.
**Repository:** [moshiour0/SARGuardian-backend](https://github.com/moshiour0/SARGuardian-backend)  
**Working branch:** feat/know-place-analysis  
**Latest CI-validated code/test/workflow baseline:** `a5fa40ad51a8fa46d70b57430940586b38c52179` (validation run [40228894456](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40228894456): 294 tests passed; live arbitrary-AOI catalogue/series/map-output smoke test passed with explicit P05023 selection)
**Main baseline (rechecked):** 2218dfeb73353080d8d94bd733d9e7bd9a848886  
**Purpose:** durable handoff for future ChatGPT sessions. Read this file and the linked blueprint/checklist before continuing; update it whenever material code, evidence, decisions, validation status, or blockers change.

## 1. Non-negotiable rules

- All Know Place work stays isolated on feat/know-place-analysis. Never commit, merge, cherry-pick or otherwise write Know Place changes to main.
- The known main-branch baseline supplied for this task is 2218dfeb73353080d8d94bd733d9e7bd9a848886; previous branch validation reported main unchanged. Always verify refs before any operation that could affect them.
- **Do not run a raw GOFF replay/download workflow unless the user explicitly authorizes it using the exact consent marker [run-know-place].** Do not infer authorization from a general request to continue the audit. No raw replay is authorized by this context update.
- Scientific claims are fail-closed. Do not claim paper reproduction, source-data parity, full-footprint reproduction, hazard detection, prediction skill, or operational early warning without direct and suitable evidence.
- Never silently replace or relabel the author-exact first-pair P05023 product as the historical X05026 variant.
- Preserve the licensing boundary in Zenodo DOI https://doi.org/10.5281/zenodo.22730419: the main archive is CC BY 4.0 except the separate extent_CC-BY-NC-4.0 runout outline, which is CC BY-NC 4.0. Do not copy that extent into this repository or treat it as CC BY 4.0.
- Preserve the distinction between displacement-valid pixels, R-valid coherence pixels, P1, P2, polygon-null and displacement-null estimands. Never compare their counts or percentiles as though they measured the same thing.

## 2. Current verified state

### Current Run Workflow entry point

- Default-branch `main` remains unchanged (`2218dfeb73353080d8d94bd733d9e7bd9a848886`). A feature-branch copy of `.github/workflows/sarguardian-aoi-wkt-dispatcher.yml` is registered on `feat/know-place-analysis` so the existing Run Workflow UI path can be used without changing main.
- In Actions, select **SARGuardian AOI WKT E2E (safe branch dispatcher)**, select branch `feat/know-place-analysis`, then choose `author-exact-p05023` for the five-pair author run or `generic-aoi-date` for arbitrary WKT/date measurement.
- The author profile requires exact manual input `[run-know-place]`. It checks Earthdata/Google Drive secrets before download, obtains exactly five P05023 sources, hashes and validates the HDF5s/grids, runs the analyzer, retains derived-only evidence in Drive, verifies remote receipts, then removes temporary raw files only after durable retention is verified.
- The generic profile has `execute_downloads=false` by default. That profile is a no-source-download catalog/series dry run. Set it true only with `[run-know-place]` and working Earthdata + Drive credentials.
- Runbook: `docs/KNOW_PLACE_ANALYSIS_RUNBOOK.md`. Architecture/validation plan: `docs/know-place/REPRODUCIBLE_ENGINE_AND_MULTI_SITE_VALIDATION_20261024.md`. Benchmark registry: `docs/know-place/reference/multi_site_benchmark_v1.json`.
- Multi-site registry is pre-registered but not scored: Bhote Koshi (author-method reproduction target and hazard-discrimination challenge); Samudra Tapu and Bara Shigri (glacier-flow positives); Hubbard and Malaspina (high-speed/speckle challenges); Budhi Gandaki (GUNW cross-product no-precursor challenge). Four non-Bhote site geometries/product IDs remain pending. Budhi Gandaki is not directly comparable to GOFF until a versioned GUNW adapter exists.

### Repository and validation baseline

- Branch exists: feat/know-place-analysis.
- Latest fully CI-validated code/test/workflow baseline: `a5fa40ad51a8fa46d70b57430940586b38c52179` (294 tests passed; see run 40228894456).
- Previous baseline validation: [run 40040361146](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40040361146), with 141 tests passed before this correction.
- **Latest CI-validated code/test/workflow baseline:** `5354a344ce19eac652fa8102c790fce18e18ec13` (validation: [run 40115947045](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40115947045)).
- **Latest isolated validation:** [run 40115947045](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40115947045), commit `5354a344ce19eac652fa8102c790fce18e18ec13`. Result: **217 tests passed in 2.62 s**; all eight workflow YAML files parsed, pinned actionlint v1.7.12 checksum and semantic validation passed, and both jobs succeeded. This validates the corrected post-download paper-status contract.
- The validated tree includes separate footprint-screen equations, an array-only per-pixel geometry builder, geometry → dE/dN projection → screen integration tests, fail-closed vertical-reference checks, a public Copernicus GLO-90 terrain-tile acquisition workflow, and a separate exact-author P05023 CMR link/acquisition path. The acquisition workflow downloaded and verified 16 public tiles in [run 40052506016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40052506016); an independent local replay found their raster values reproduce the archived `terrain/elev_m.tif` to float32 rounding. This does not prove original tile-byte identity or process raw GOFF geometry cubes.
- The geometry builder audit records a material vertical-reference risk: Copernicus GLO-90 is EGM2008-referenced, while the NISAR radarGrid height axis is ellipsoidal. The original author tile bytes remain absent, but current public-mirror tiles were downloaded and their archived preparation recipe reproduced the archived `terrain/elev_m.tif` to Float32 rounding. A separate official-grid experiment quantifies the crown-area ellipsoidal-minus-EGM2008 offset at median −31.7705 m; no correction is applied to the author path. See `docs/know-place/evidence/EGM2008_VERTICAL_DATUM_SENSITIVITY_20261024.md`.
- Earlier catalog-only runs recorded zero source downloads. The later author-exact replay [40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362) downloaded and verified all five exact P05023 payloads, recorded source SHA-256 pins 5/5, and validated grids 5/5. Full receipts: `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`.
- Latest actual raw acquisition/analysis is [run 40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362), which passed with explicit consent and downloaded/hashed/validated all five P05023 products. Subsequent code-push runs skipped raw acquisition because no new consent input was supplied; raw files were not downloaded again just to refresh the historical artifact.
- Main was rechecked and remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`. The branch remains separate. This current handoff refresh is context-only and does not change code/tests; any future code/test change requires fresh validation.
- Use `.github/workflows/know-place-analysis-validation.yml`, `.github/workflows/know-place-aoi-analysis.yml`, `.github/workflows/know-place-dem-source-acquisition.yml`, and `.github/workflows/know-place-terrain-datum-sensitivity.yml`. The author-catalog gate in `tools/know_place/author_catalog.py` now performs direct exact-ID, AOI/date, and granule-wildcard searches without downloading payloads. Changes to `tools/tests/test_know_place_*.py` trigger isolated validation.
- Do not run the separate expensive raw replay job without [run-know-place].

### Scientific status (must not be relaxed)

- **Paper reproduction:** `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED` (raw source byte identity is pinned 5/5; exact author crown geometry and method parity remain unverified).
- **Hazard detection:** NOT_EVALUATED.
- **Operational status:** blocked; no calibrated risk score or operational alarm.
- Archive integrity/payload audit: pass.
- Exported derived-R band vs recomputation from archived dE/dN: pass.
- Exact author source-byte identity is pinned 5/5. Exact crown-mask parity, full-footprint author-screen replay, terrain vertical-datum resolution, and independent event/non-event validation remain unestablished.

## 3. Author archive: byte integrity and actual contents

User-supplied source: [Zenodo record](https://doi.org/10.5281/zenodo.22730419), “Bhote Koshi 2026 ice–rock avalanche: NISAR L2 GOFF site series and footprint-wide offset-tracking screen — data and code”.

- ZIP: bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip
- ZIP size: 183389034 bytes
- MD5: b07b7eb3b3178d3f69d5bca009cb0db4
- SHA-256: 002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3
- ZIP integrity: PASS; 90 manifest-listed in-ZIP payloads match declared size and MD5, with zero mismatches.
- Contents include author scripts, five small processed site-field GeoTIFFs, tables/null distributions, the 101-zone inventory and three footprint-screen rasters.
- The ZIP does **not** contain the five raw source GOFF HDF5 granules or the five full-footprint 4230 × 4311 per-pair offset rasters.
- The five exported TIFFs are 80 × 73 pixels, EPSG:4326, three bands (dE, dN, R). This disagrees with the README's stated four-band EPSG:32645 field profile; preserve and report that documentation/profile inconsistency.
- The archive's tables/TableS7_all_validated_zones.csv is byte-identical to the supplied 101-zone CSV after the documented source-byte/line-ending handling. The post-event zone inventory is not an independent prospective validation set.
- Detailed evidence: docs/know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md; reference records: docs/know-place/reference/author_archive_golden_v1.json and author_benchmark_v1.json.

## 4. Critical metric correction — completed 2026-10-24

### What was wrong

An earlier diagnostic incorrectly compared:
- displacement-valid crown cells from tables/nisar_pot_series.json field n; against
- polygon-null coherence-valid crown cells from tables/polygon_null.json field n_px.

These are different estimands. The prior statement that 296 displacement-valid pixels disagreed with 298 R-valid cells was wrong and must not be repeated.

### Independent recomputation on all five exported fields

The archive was read directly. For each field, I recomputed the author's 5 × 5 directional-coherence map using scipy.ndimage.uniform_filter default reflected edges, finite-vector normalization, and finite-support fraction strictly greater than 0.5. I then applied the exact author crown_slice policy using the exported GeoTIFF bounds as extent endpoints. This diagnoses the **exported raster grids only**, not the original GOFF source-grid mask.

| Pair | Displacement-valid crown cells (export / nisar_pot_series.json:n) | R-valid crown cells (export / polygon_null.json:n_px) |
|---|---:|---:|
| 2026-06-20 → 2026-07-02 | 283 / 283 | 302 / 302 |
| 2026-07-02 → 2026-07-14 | 294 / 294 | 299 / 299 |
| 2026-07-14 → 2026-07-26 | 296 / 296 | 302 / 302 |
| 2026-07-26 → 2026-08-19 | 292 / 292 | 298 / 298 |
| 2026-08-19 → 2026-08-31 | 195 / 195 | 202 / 202 |

Results:
- Difference from each corresponding source-table count is zero for all five pairs, for both estimands.
- Full-field recomputed-R finite masks equal archived TIFF band 3 finite masks for all five fields.
- Maximum absolute R-band error across the five fields is 3.4930149217515805e-8, below 1e-6.
- This resolves the former **count comparison** error. It does **not** establish exact pixelwise mask parity on the original GOFF source grid. The original source coordinate vectors/read window and pre-export author masks/rasterization extents are absent; the reason for any source-grid mask difference remains unresolved. **Do not invent a cause.**

Machine-readable per-field details are in docs/know-place/reference/author_archive_golden_v1.json. The benchmark was also corrected to schema v1.1 in docs/know-place/reference/author_benchmark_v1.json: displacement_valid_crown_pixels references nisar_pot_series.json key n; polygon_null_R_valid_crown_pixels references polygon_null.json key n_px; the ambiguous legacy valid_crown_pixels key was removed. Both tools/tests/test_know_place_author_archive.py and tools/tests/test_know_place_author_reference_data.py enforce the separation. Full audit: docs/know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md.

## 5. Exact author source IDs and historical variant warning

The supplied Research Square paper and Supplementary Information identify five ascending T098, L-SAR HH, GOFF layer-2 pairs, all with P05023. The authoritative manifest is docs/know-place/reference/author_benchmark_v1.json.

- 2026-06-20 → 2026-07-02: author P05023 was NOT_FOUND in the earlier ASF-only lookup; collection-scoped CMR later confirmed the producer metadata. Direct raw bytes remain unverified.
- 2026-07-02 → 2026-07-14: P05023; route found.
- 2026-07-14 → 2026-07-26: P05023; route found.
- 2026-07-26 → 2026-08-19: P05023; route found.
- 2026-08-19 → 2026-08-31: P05023; route found.

The historical replay used X05026 for the first pair. Its hash remains valid for those historical bytes only; it is **not** an author-exact source substitute. Four of five P05023 routes do not mean the raw bytes have been downloaded or hashed. Original GOFF source SHA-256 values for the exact author five-product set, especially the first P05023 ID, are not pinned in this archive.

## 6. Author method facts that must remain distinct

Implementation kernels live in tools/know_place/author_parity.py; offline tests live in tools/tests/test_know_place_author_parity.py; processed-field integrity check is tools/know_place/verify_author_fields.py.

- Author site-series geometry uses the nearest radarGrid sample at the stated crown coordinate, then a median of each geometry component over the height axis. The current exploratory runner's fixed-height per-pixel geometry is not equivalent.
- Author source validity gate: finite SNR, SNR ≥ 5, and projected horizontal magnitude ≤ 10 m. Do not add correlationSurfacePeak as a validity gate for this author path.
- Author coherence kernel: 5 × 5 scipy.ndimage.uniform_filter, reflected edges, normalize using finite-vector support, retain finite support fraction > 0.5 (at least 13/25 vectors).
- Author stable-reference correction is applied only if the valid outside-AOI ring has **more than 200 cells**.
- Author P1 crown coherence is calculated **after cropping** to the crown. Full-box/background R and polygon-null R are different estimators.
- polygon_null.py uses a shared RNG sequence with seed 20260907; unique candidate centres sampled without replacement from all finite-R cells; radius sqrt(n_px/pi); accept a disk if at least 60% of target valid cells are present; strict comparisons (draw < crown, draw > box). This is not the same as displacement null, P1, or P2.
- The archive has no standalone displacement_null.py despite a planned reference to it; its output table is present. Exact generator parity for displacement-null cannot be claimed solely from that missing script.

Always label P1, P2, polygon-null and displacement-null separately.

## 7. Event-evaluation leakage, timing and provenance safeguards — updated 2026-10-24

The held-out evaluator is a research scoring contract, not a hazard detector. The event evaluator/threshold selector were hardened and CI-tested in the current code/test tree:

- Registry canonicalization rejects one exact canonical WGS84 AOI ring assigned to multiple site IDs inside the same registry.
- The held-out evaluator rejects any site ID overlap and any exact canonical AOI-ring overlap between validation and test splits, including reversed polygon winding or rotated starting vertex. It reports disjoint site/geometry split counts.
- A supplied `first_alarm_time_utc` is only allowed for `ALERT` and must fall within the declared observation window; `NO_ALERT`/`NO_RESULT` cannot claim an alarm timestamp.
- Threshold policy schema is now `know-place-frozen-threshold-policy/1.1`; validation score and prediction payload schemas are now `know-place-validation-scores/1.1` and `know-place-event-predictions/1.1`.
- Threshold CLI requires a `know-place-detector-policy/1.0` manifest and hashes the exact file bytes. The model-policy hash is included in the frozen threshold, validation score payload, and held-out prediction payload; mismatched hashes are rejected.
- Each validation-score and prediction case carries `source_product_sha256s`, which must match the source-product hashes declared by the corresponding registry case. The evaluation report hashes the prediction payload and records `PASS_ALL_CASE_SOURCE_HASHES_MATCH_REGISTRY` after consistency checks.
- Regression tests exercise model-policy mismatch, source-product hash mismatch, exact geometry leakage, repeated AOI under different site IDs, and contradictory/out-of-window alarm timestamps.

**Limit of these protections:** they validate declared manifests/hashes and cross-file consistency. They do not prove that the claimed implementation actually ran on precisely those source bytes; that needs an independently captured run attestation/receipt tying runtime, code revision, inputs and outputs. Exact geometry matching also does not detect all partial AOI overlaps or nearby spatial leakage. Those must be handled by a spatial buffer/separation audit before independent-site validation is credible.

These changes do not change scientific status: `PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`.

## 8. Author footprint-wide candidate-screen kernel — added 2026-10-24

Added `tools/know_place/footprint_screen.py` and `tools/tests/test_know_place_footprint_screen.py`, adapted with attribution from the Zenodo archive's `code/wide_screen.py` (SHA-256 `60e4238b9a10510f52a4673939a9708bf513d8bae460ba797d2dd27a1357d7c9`) and `tables/TableS6_screen_params.json` (SHA-256 `85743e828c4d684046acf43bdb0bfbc8b8c194626aacad8fd58e154e925d8e76`). Full notes: `docs/know-place/evidence/AUTHOR_FOOTPRINT_SCREEN_KERNEL_AUDIT_20261024.md`.

The pure-array kernel keeps this estimator separate from the crown/site-series path and includes:
- Per-pixel AT/SR formula dE = AT*cE + SR*kE; dN = AT*cN + SR*kN. The footprint screen requires verified per-pixel coefficients; a separate array-only builder in `tools/know_place/footprint_geometry.py` interpolates supplied geometry cubes/DEM to produce them. It does not read/hash HDF5 or DEM files and has not been run on the exact author raw inputs.
- SNR >= 5 and projected magnitude <= 10 m gate; float32 local mean with reflected default edges and support fraction strictly > 0.15.
- 41-pixel local magnitude anomaly; scale is local mean absolute anomaly with 0.05 m floor; 5x5 residual-vector coherence requires finite direction support > 0.5.
- Same-pair screen requires z >= 4, anomaly >= 0.50 m and residual R >= 0.75. Candidate cell must flag in >=2 of five exact author intervals. Candidate connected components use scipy.ndimage.label default four-connectivity and minimum 10 cells.
- Result status remains `hazard_detection_status=NOT_EVALUATED`.

CI [run 40049074686](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40049074686) passed 164 tests including the newly explicitly wired footprint test. This establishes synthetic equation/policy checks only; it does not execute the original script, process exact author GOFF products, verify the 4230 x 4311 grid, create geometry coefficients, recreate author GIS outputs or validate detection skill. The archive's three screening rasters do not replace the missing five raw GOFF HDF5 inputs/full-footprint per-pair offset rasters. The first author P05023 input remains NOT_FOUND; do not substitute X05026. Active glaciers dominate the author screen's own candidates; it is a movement screen, not a failure prediction.

## 9. Author per-pixel geometry builder and vertical-reference risk — updated 2026-10-24

Added `tools/know_place/footprint_geometry.py` as an array-only implementation of the archived `code/geometry.py` interpolation recipe. It uses supplied radarGrid height/y/x axes and five geometry cubes, supplied warped DEM elevations, linear `RegularGridInterpolator((height, y, x), ..., bounds_error=False, fill_value=None)`, source-method median fill for DEM nodata/nonfinite cells, height-axis clipping, and coefficient equations `cE=alongTrackUnitVectorX`, `cN=alongTrackUnitVectorY`, `kE=-(losX/hypot(losX,losY))/sin(incidence)`, analogous `kN`. It reports XY extrapolation and nonfinite coefficients.

Horizontal CRS and exact affine-grid agreement are checked. Vertical references must now be explicitly declared; differing reference strings are rejected by default. An explicit source-reproduction override can preserve the author code's direct-use behavior, but report fields state that no vertical transformation was applied and the output is not datum-corrected.

Verified archived DEM facts: `terrain/elev_m.tif` SHA-256 `d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1`, MD5 `a5451bac63051bdf36ed2bde6acca7cc`, 59,400,495 bytes, 4,311 × 4,230 Float32 cells, EPSG:32645, 80 m transform, all 18,235,530 cells finite, values 77.5–8,146.092 m, median 4,674.589 m. All three archived footprint screen rasters share the same 4,311 × 4,230 horizontal grid. These profile checks do not establish datum compatibility.

**Unresolved datum caveat — now quantified in a separate experiment:** Copernicus GLO-90 specifies EGM2008 height, while NISAR's radarGrid `heightAboveEllipsoid` axis is ellipsoidal. In [datum-sensitivity run 40053719232](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40053719232), the selected PROJ/NGA 2.5-arc-minute grid operation (grid SHA-256 `4191d471eefebf24091b56dbc604353cb3b8cf8cc70e448bb9ae56a272bef17a`) gives a median ellipsoidal-minus-EGM2008 offset of −31.7705 m across the 323 cells in the published crown rectangle. This is a separate experimental DEM; the author reproduction path has **not** been modified. The original author tile bytes and raw GOFF geometry cube remain unavailable, so coefficient-map sensitivity is still uncomputed. See [full datum sensitivity audit](evidence/EGM2008_VERTICAL_DATUM_SENSITIVITY_20261024.md).

Validation run [40050020868](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020868) passed 176 tests, four workflow YAML parses and actionlint. Raw replay [40050020872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020872) skipped the five-pair analysis for lack of `[run-know-place]`.

### Additional terrain-source acquisition and raster replay — 2026-10-24

The isolated public-data workflow `.github/workflows/know-place-dem-source-acquisition.yml` downloaded sixteen Copernicus GLO-90 GeoTIFF tiles covering 83–87°E, 27–31°N, and recorded per-tile SHA-256 hashes and raster-profile checks. Successful acquisition: [run 40052506016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40052506016); artifact ZIP digest from GitHub is `sha256:0499832696ccf4dbda584a848f6373771c498b168232b3acc486576c2bda26f8`. Full tile hash ledger is `reference/copernicus_glo90_current_manifest_20261024.json`; replay evidence is `evidence/COPERNICUS_GLO90_SOURCE_TILE_REPLAY_20261024.md`.

Using those tiles, the archived `code/prep_terrain.py` mosaic → bilinear reproject recipe reproduced `terrain/elev_m.tif` on the exact archived 4311 × 4230 EPSG:32645 80 m grid: all 18,235,530 target cells were finite in both rasters, finite masks were identical, 18,235,529 cells were bitwise-identical Float32 values, the only difference was 0.000244140625 m, and RMSE was 5.717166719e-8 m. This supports that the archived elevation grid contains current public GLO-90 values resampled as in the source code. It does **not** establish byte identity of the original 16 author input files. The source script contains horizontal warp/resampling but no visible vertical datum operation; the EGM2008 ↔ ellipsoidal-height discrepancy remains unresolved, and no correction has been applied. Raw GOFF download remains separately gated.
### EGM2008 vertical datum sensitivity — separate experiment, 2026-10-24

- Workflow: [run 40053719232](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40053719232), artifact `know-place-egm2008-vertical-datum-sensitivity-40053719232-1`, SHA-256 `4defe3a608e8514ce76d22f948264fd9aa806fb286a7aa413ea384756d39a13c`.
- Official PROJ/NGA grid SHA-256 `4191d471eefebf24091b56dbc604353cb3b8cf8cc70e448bb9ae56a272bef17a`; selected EPSG:9518 → EPSG:4979 grid operation, declared accuracy 0.113 m; ballpark/no-op rejected.
- Across all 18,235,530 cells, signed offset median −30.1587 m and range −67.0417 to −24.2041 m. In the published crown rectangle, 323 cells yield median −31.7705 m (range −31.9634 to −31.5728 m).
- Archived prepared DEM replay still matches current public GLO-90 inputs on the exact 80 m target grid: finite masks identical, 18,235,529 / 18,235,530 float32 cells bitwise equal, maximum difference 0.000244140625 m, RMSE 5.71717e−8 m.
- The height conversion is experimental and **not** used by the author reproduction path. Original terrain tile byte identity is unknown, raw GOFF geometry is still missing, and `cE/cN/kE/kN` impact is not yet computed. Audit: `docs/know-place/evidence/EGM2008_VERTICAL_DATUM_SENSITIVITY_20261024.md`; machine-readable summary: `docs/know-place/reference/terrain_vertical_datum_sensitivity_20261024.json`.

### Extended author P05023 catalog audit — 2026-10-24

ASF exact-ID/AOI-date/wildcard queries did not find first author P05023 and only exposed X05026 as the same-interval candidate. A follow-up collection-scoped NASA CMR lookup resolved catalog identity: exact P05023 producer ID in collection `C2854341702-ASF`, concept ID `G4248299988-ASF`, with producer-ID and readable-name filters both returning HTTP 200 / one record each. All five author IDs now have catalog identity confirmations, but none has a source-byte SHA-256; paper reproduction remains blocked. See `docs/know-place/evidence/CMR_AUTHOR_P05023_EXACT_CATALOG_RESOLUTION_20261024.md`; validation [40056005969](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40056005969) passed 191 tests.

### Latest exact-source catalog resolution — 2026-10-24

NASA CMR confirms the exact first-pair P05023 record in collection `C2854341702-ASF`: granule concept `G4248299988-ASF`, exact producer granule ID, and CMR update timestamp `2026-07-15T16:07:07.506Z`. The collection-scoped producer-ID and readable-name queries each returned HTTP 200 / one result. This corrects the earlier ASF-only `NOT_FOUND`; it does not prove source-byte identity. Catalog identity is now 5/5, source hashes remain 0/5, and raw source downloads remain 0. Exact HDF5 URL and metadata: `docs/know-place/evidence/CMR_AUTHOR_P05023_EXACT_CATALOG_RESOLUTION_20261024.md`. Validation [40056005969](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40056005969) passed 191 tests.

## 10. Design blueprint and validation gates

Read these before implementing further changes:
1. [Scientific architecture blueprint](../KNOW_PLACE_ANALYSIS_BLUEPRINT.md)
2. [Engineering & scientific checklist](../KNOW_PLACE_ANALYSIS_CHECKLIST.md)
3. [Isolated runbook](../KNOW_PLACE_ANALYSIS_RUNBOOK.md)
4. [Multi-event validation plan](validation/MULTI_EVENT_VALIDATION_PLAN.md)
5. [Author-supplement retrieval audit](evidence/AUTHOR_SUPPLEMENT_RETRIEVAL_AUDIT_20261024.md)
6. [Raw replay and R-policy audit](evidence/RAW_REPLAY_40006999011_R_POLICY_AUDIT.md)
7. [Zenodo author archive audit](evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md)
8. [Footprint-wide screen-kernel audit](evidence/AUTHOR_FOOTPRINT_SCREEN_KERNEL_AUDIT_20261024.md)
9. [Footprint geometry builder and vertical-datum audit](evidence/AUTHOR_FOOTPRINT_GEOMETRY_BUILDER_AUDIT_20261024.md)
10. [Author archive golden/reference fixture](reference/author_archive_golden_v1.json)
11. [Offline regression test](../../tools/tests/test_know_place_author_archive.py)
12. [Isolated validation workflow](../../.github/workflows/know-place-analysis-validation.yml)
13. [Exact-author acquisition workflow audit](evidence/AUTHOR_EXACT_ACQUISITION_WORKFLOW_AUDIT_20261024.md)

Promotion gates from the multi-event validation plan:
- **G0 structural:** schemas, exact identity metadata, hashes, grid checks and synthetic known-answer tests.
- **G1 measurement:** vector projection/sign/units, source masks, georeferencing and provenance independently verified.
- **G2 paper parity:** exact raw source IDs/bytes, author geometry/method, pixelwise/summarized golden comparisons.
- **G3 external validation:** independently labelled event and non-event cohort, held-out evaluation, uncertainty and false-alarm reporting.
- **G4 operational research pilot:** terrain-backed geometry, cadence/latency, drift, no-result behavior and human review.

Current state: archive integrity and exported derived-R verification pass; the correction above resolves count-estimand bookkeeping. Full source input and author-method parity are still **BLOCKED** (below G2), G1 remains partial, G3/G4 are blocked, and hazard detection remains **NOT_EVALUATED**.

## 11. Next actions — continue in this order

- [x] Inspect blueprint, checklist, runbook, source/validation audits, author archive fixture, author kernel and archive verifier.
- [x] Recompute displacement-valid and R-valid crown counts independently from all five exported fields and separate the two estimands in machine-readable evidence.
- [x] Correct both the author-archive diagnostic and benchmark fixture so displacement-valid n and polygon-null R-valid n_px are separate. CI passed in [run 40043977505](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40043977505), with 141 tests, four workflow YAML parses and actionlint passing. The ASF job downloaded zero products; the raw-replay job was skipped for lack of explicit consent.
- [x] Extend same-estimand comparison of archived per-pair tables and raster statistics; keep P1/P2/polygon-null/displacement-null separate. See `docs/know-place/evidence/AUTHOR_PROCESSED_FIELD_TABLE_PARITY_20261024.md` (120/120 checks; exported fields only).
- [ ] Continue integrating the isolated author-parity path, always testing against archived processed fields/tables without silently changing the exploratory runner.
- [x] Resolve, download and SHA-256-pin the five exact author P05023 GOFF HDF5 inputs; all five passed HDF5 identity and 4311 × 4230 EPSG:32645 / 80 m grid validation in [run 40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362). Do not substitute X05026.
- [x] Run the consent-gated source replay and review the source hashes, five-pair metrics and remote Drive receipts; evidence is `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`.
- [ ] Verify the author-supplement crown geometry/control sampling, golden tables/masks and full-footprint author screen outputs.
- [x] Extract and test the author footprint-wide candidate-screen equations in a separate module; synthetic kernel tests included in CI. See `docs/know-place/evidence/AUTHOR_FOOTPRINT_SCREEN_KERNEL_AUDIT_20261024.md`.
- [x] Add an array-only per-pixel coefficient builder with synthetic tests and geometry-to-screen integration; horizontal CRS/affine and vertical-reference mismatch guards are explicit. See `docs/know-place/evidence/AUTHOR_FOOTPRINT_GEOMETRY_BUILDER_AUDIT_20261024.md`.
- [x] Download and SHA-256-pin all 16 current public Copernicus GLO-90 tiles for the terrain bbox and independently recreate the archived `terrain/elev_m.tif` warp. See `docs/know-place/evidence/COPERNICUS_GLO90_SOURCE_TILE_REPLAY_20261024.md` and `docs/know-place/reference/copernicus_glo90_current_manifest_20261024.json`. This is raster-value parity, not original input-file byte parity.
- [ ] Obtain the author's original 16 terrain-tile hashes/copies or exact delivery version, and resolve/quantify EGM2008-to-ellipsoid height conversion before asserting correct GOFF geometry coefficients. The archived source appears to use EGM2008 elevations directly against `heightAboveEllipsoid` with no visible vertical conversion; no correction has been applied.
- [x] Downloaded and SHA-256-pinned the five exact author-published GOFF HDF5 inputs in run 40114703362; all passed identity and common-grid validation. [ ] Verify geometry-axis interpretation, units/sign conventions, exact crown mask and full-footprint outputs against an author reference. Do not substitute X05026.
- [ ] Recreate full-footprint outputs from documented exact sources and author method; archived full-footprint per-pair offset rasters are absent. The exact-source site-ROI replay is complete, but the full-footprint parity check remains pending.
- [ ] Assemble an independently labelled event/non-event registry, perform explicit partial-overlap/spatial-buffer auditing, and run held-out evaluation under the pre-registered multi-event plan. The 101-zone post-event inventory is not a prospective holdout. Hash checks validate declared provenance consistency, not proof of actual execution; add trusted run attestation before relying on production evaluation.

## 12. Update protocol for future chats

When continuing from a new chat:
1. Read this file first, then KNOW_PLACE_ANALYSIS_BLUEPRINT.md, KNOW_PLACE_ANALYSIS_CHECKLIST.md, and the relevant evidence report.
2. Verify the current branch head, main SHA, and latest validation run; do not assume SHAs/results remain current.
3. Inspect the exact current files and their diff before editing; do not reapply old fixes blindly.
4. Keep an evidence ledger: what ran, inputs/hashes, output hashes, tested commit SHA, CI run URL, and any skipped expensive jobs.
5. Update this file as part of the same branch-only work whenever a scientific decision, blocker, code path, test or validation state changes.
6. Never mark a checklist item complete unless inspectable evidence supports the exact claim.


## 13. Exact-author acquisition workflow and latest CI — 2026-10-24

Current branch head at the start of this update: 2fddad5fbd3d66fc9ade40da41ce829bfabf7610. Main remains unchanged at 2218dfeb73353080d8d94bd733d9e7bd9a848886. The workflow/runner audit is in docs/know-place/evidence/AUTHOR_EXACT_ACQUISITION_WORKFLOW_AUDIT_20261024.md.

- Validation run [40058988024](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988024): 204 tests passed in 4.87 s, seven workflow YAML files parsed, actionlint v1.7.12 checksum and semantic validation passed.
- Live catalog workflow resolved exactly five author-P05023 direct HDF5 data URLs: AUTHOR_CMR_CATALOG_GATE=PASS, AUTHOR_EXACT_PRODUCTS_CONFIRMED=5/5, AUTHOR_EXACT_CMR_DATA_URLS_CONFIRMED=5. The metadata artifact is know-place-author-exact-live-cmr-access-evidence (SHA-256 digest b81e1d2b1ba4c78a90753ed84fd1ff1da0ff72c886bf46f31ffdd99928a1c4e9); the artifact records accessible link evidence, not source payload hashes.
- The source payload count is still 0/5 and source SHA-256 count 0/5. Direct URL resolution is not byte acquisition, HDF5 validation, or paper-method parity.
- The new .github/workflows/know-place-author-exact-replay.yml is manual-dispatch-only for raw work; it requires the exact consent input [run-know-place] and checks Earthdata and Drive credentials before download. The latest dispatch-shaped workflow run had no consent input, so its acquisition job skipped. The legacy X05026 replay also skipped. No raw source was downloaded in this turn.
- The GitHub connector used for this task can inspect runs and update branch files but has no workflow-dispatch operation. Therefore manual dispatch was not initiated from this session. To execute the raw download, open the exact-author workflow in the Actions tab, choose Run workflow, enter [run-know-place] in consent_marker, and ensure the Earthdata and Google Drive secrets are configured. The workflow will record size/SHA-256, validate HDF5 identity/grid, analyze, retain derived-only outputs in Drive, and only delete temporary raw files after verified Drive receipts.
- Scientific state remains PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED and HAZARD_DETECTION_STATUS=NOT_EVALUATED. Do not treat this as a hazard detector.


## 14. Prior post-documentation CI confirmation — 2026-10-24

Validation run 40059962163 tested the integrated audit/checklist commit 5901c10c2bb38379acd23c0a0e2c01952c4e7d1e: 204 tests passed in 6.56 s, seven workflow YAML files parsed, and actionlint v1.7.12 checksum plus semantic validation passed. Both validation jobs succeeded. Live metadata logs report AUTHOR_CMR_CATALOG_GATE=PASS, AUTHOR_EXACT_PRODUCTS_CONFIRMED=5/5, AUTHOR_EXACT_CMR_DATA_URLS_CONFIRMED=5, SOURCE_DOWNLOADS=0. Artifact `know-place-author-exact-live-cmr-access-evidence` (ID 12546952625; 4,117 bytes) has SHA-256 digest `7b91d3db92422d1e39f3412e1318b1455dc87aeb1e8677897339ee24f459dbb7`; the ZIP was downloaded and independently integrity/hash checked.

Legacy push run 40093380207 skipped raw analysis, and exact-author workflow run 40058988016 skipped its acquisition job because the exact consent input [run-know-place] was absent. Raw source payload count remains 0/5, raw SHA-256 count remains 0/5, paper reproduction remains blocked, and hazard detection remains NOT_EVALUATED. The available GitHub connector has no workflow_dispatch operation, so no manual dispatch occurred from this session. A user must open the exact-author workflow in GitHub Actions, choose Run workflow, enter [run-know-place], and ensure Earthdata and Drive secrets are configured. Main remains unchanged at 2218dfeb73353080d8d94bd733d9e7bd9a848886.

## 15. Latest exact-author CMR artifact independently verified — 2026-10-24

The latest complete validation is [run 40093352981](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40093352981), testing commit `87dce99f5f20b7e02c46d8e5a168c4c877d8a3d2`: **204 tests passed in 4.73 s**, all seven workflow YAML files parsed, and actionlint v1.7.12 checksum plus semantic workflow validation passed. The exact-author artifact `know-place-author-exact-live-cmr-access-evidence` (ID `12559877337`, 4,118 bytes) was downloaded and ZIP integrity checked; its SHA-256 `20929525a6d20e4011563d23ddde16d1144b5f4afbad44505b54c220c42e8897` matches GitHub's artifact digest.

The live manifest confirms all five author P05023 product IDs and exact HDF5 URLs. For each product, both `producer_granule_id[]` and `readable_granule_name[]` queries returned HTTP 200 / one exact record. Counts: CMR identities 5/5; data URLs 5/5; blocking products 0; raw source downloads 0; source SHA-256 pins 0/5. Raw source identity is still unverified; paper reproduction remains blocked and hazard detection remains not evaluated.

Latest legacy raw-replay run [40060195873](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40060195873) completed only its decision job and skipped analysis. Dedicated author-exact workflow run [40058988016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988016) also skipped because the exact manual input `[run-know-place]` was absent. No raw GOFF payload was downloaded. This session's available GitHub connector has no `workflow_dispatch` operation; actual replay must be manually initiated in Actions after confirming Earthdata and Drive secrets. Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`.


## 16. Follow-up verification — 2026-10-24 (latest branch head 85bbda3)

- Latest isolated validation remains [run 40102959304](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40102959304), on commit `cc0f2d101c717e80f4abcf2d9ace1479dc1168d2`: **213 tests passed**, all eight Know Place workflow YAMLs plus the branch dispatcher parsed, and actionlint v1.7.12 checksum/semantic checks passed.
- The latest exact-author live CMR artifact from that run is `know-place-author-exact-live-cmr-access-evidence`, artifact ID `12562589832`, size 4,117 bytes. I downloaded it, checked ZIP integrity, and independently calculated SHA-256 `65e65ae2c4dec384c50ca5a8877e69b705a1861c1e85312026d62512c5dd9386`, matching GitHub's artifact digest. Its manifest confirms all five exact P05023 producer IDs, five direct HTTPS HDF5 links on `nisar.asf.earthdatacloud.nasa.gov`, and exact collection-scoped CMR identities. This is catalog/link evidence only: `source_downloads=0`, source payload SHA-256 values remain 0/5.
- Latest branch push run [40103092615](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40103092615) passed the no-download decision gate and skipped the expensive five-pair analysis job because the exact `[run-know-place]` input was not supplied. The exact-author raw replay workflow has not been manually dispatched with consent. No raw GOFF payload was downloaded in this follow-up.
- I rechecked the active GitHub connector capabilities: it supports reading runs/artifacts and branch-file updates, but exposes no workflow-dispatch API. I cannot truthfully claim to have clicked **Run workflow** or launched the raw job from this session. The remaining operational step is to open the branch-specific dispatcher in Actions, select branch `feat/know-place-analysis`, choose `author-exact-p05023`, enter the exact marker `[run-know-place]`, and ensure Earthdata and Google Drive secrets are configured. This marker is required before raw HDF5 acquisition.
- Scientific status remains `PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED` and `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. Do not substitute `X05026` for author `P05023`; do not merge to main.
- Main was rechecked at `2218dfeb73353080d8d94bd733d9e7bd9a848886`; it remains untouched. Working branch head before this context-only update: `85bbda3294f2305e6e5a706bde003a5360d49931`.


## 17. Dispatcher consent failure and fix — 2026-10-24

Failed run [40107037642](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40107037642) stopped in the first consent gate. Log evidence is CONSENT_MARKER=run-know-place; the required exact value is [run-know-place]. Both raw-processing jobs were skipped; source downloads, analysis and Drive upload were not started. This was a consent-input mismatch, not a data/science failure. The dispatcher now states the exact correction in the log and step summary; a regression test keeps the bracket requirement strict. Full audit: docs/know-place/evidence/DISPATCHER_CONSENT_MISMATCH_20261024.md. Main remains unchanged.


## 18. Main-branch downloader/retry audit and author-exact failure — 2026-10-24

- Main baseline was rechecked at `2218dfeb73353080d8d94bd733d9e7bd9a848886`. The last integration merge is `5465efdaba097581e1b6973e638360b4d0de1e13`; the retry policy was deliberately reduced to one attempt in `05cbecea1c3728a0820131690fd085eb3a92cce1`.
- The proven main worker carries `EARTHDATA_TOKEN`, `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`, `GOOGLE_DRIVE_OAUTH_CLIENT_JSON`, `GOOGLE_DRIVE_REFRESH_TOKEN`, `GOOGLE_DRIVE_PARENT_FOLDER_ID`; run metadata includes `PRODUCT_ID`, `GRANULE_NAME`, `PRODUCT_TYPE`, `MATURITY`, `EXPECTED_SOURCE_BYTES`, `DRIVE_VERSION_TAG=${{ github.run_id }}-${{ github.run_attempt }}`, `AOI_NAME`, `SCIENCE_COMMIT`, `RETENTION_PROFILE`, and `PRODUCT_EXECUTION_LABEL`. Main uses one whole-product attempt per worker (90-minute step timeout), and receipt-gated targeted retry `execution_label=retry-1` only when receipts are missing/invalid. The worker does not repeatedly download a failed large product four times.
- Author-exact dispatcher run [40107851266](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40107851266) successfully authenticated and completed the first exact P05023 HDF5 transfer: `1,090,519,040` bytes. It then falsely rejected the product because GOFF parser identity includes `.h5`, while CMR `granule_name` omits the extension. This is an implementation comparison bug, not an Earthdata authentication or network download failure.
- Fix: compare the parsed HDF5 filename to the exact source filename, separately compare its stem to the extension-free CMR granule ID, and save byte count/SHA-256 before grid validation. Failure receipts now distinguish downloaded+hashed payloads from grid-validated products. Retry is limited to one separately labeled `retry-1` phase for retryable network/HTTP failures; schema/identity/grid failures do not trigger an expensive redownload.
- The failed run had no durable source hash before this correction; its temporary HDF5 was removed only after the derived artifact and both Drive receipts were remotely verified. So no source hash from that run is claimed. The corrected code has regression tests for the extension mismatch, wrong release/CRS, and separate byte/hash vs grid-validated counts.
- Scientific result remains `PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`, `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. Do not treat this first source-transfer test as a completed analysis. No changes to `main`.


## 19. Main download/retry variables adopted and byte/grid receipt fix verified — 2026-10-24

- Main is unchanged at `2218dfeb73353080d8d94bd733d9e7bd9a848886`. Reference history: merge `5465efdaba097581e1b6973e638360b4d0de1e13`; one-attempt downloader policy `05cbecea1c3728a0820131690fd085eb3a92cce1`.
- The author-exact workflow now uses the main pipeline's Earthdata and Drive secret names: `EARTHDATA_TOKEN`, `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`, `GOOGLE_DRIVE_OAUTH_CLIENT_JSON`, `GOOGLE_DRIVE_REFRESH_TOKEN`, and `GOOGLE_DRIVE_PARENT_FOLDER_ID`. It also records `DRIVE_VERSION_TAG=${{ github.run_id }}-${{ github.run_attempt }}`, `RUN_ID_SAFE`, `PRODUCT_EXECUTION_LABEL`, `RETENTION_PROFILE=derived-only`, `SCIENCE_COMMIT=10639a916c9829850775410b3ed7de62e527770d`, `PRODUCT_ID`, `GRANULE_NAME`, `PRODUCT_TYPE=GOFF`, `MATURITY=PROVISIONAL`, `EXPECTED_SOURCE_BYTES`, and `RAW_DIR`. The pinned scientific checkout is explicitly verified before analysis.
- Download retry policy now mirrors the main worker's intent: one transfer attempt per worker phase (`max_attempts=1`), one separately labeled `retry-1` phase only for failures classified retryable, bounded `min(15 * 2^(phase-1), 120)` sleep, and no repeated download for HDF5 identity/grid-validation failures. Drive upload and receipt-upload verification remain required before deleting temporary raw source.
- Fixed the false `RAW_HDF5_NOT_EXACT_AUTHOR_GRID_OR_INTERVAL` reject: the GOFF parser returns a basename including `.h5`, while CMR's `granule_name` is extension-free. Identity validation now checks the exact filename and stem separately, plus release/date/CRS. New offline tests cover this suffix bug, reject X05026/wrong CRS, and ensure downloaded+hashed source counts are separate from grid-validated count.
- A completed transfer now records byte count/SHA-256 before HDF5 and grid validation. Failure manifests distinguish `source_downloads`, `source_sha256_count`, and `source_products_grid_validated`; an HDF5 or grid-validation failure cannot be misreported as though no bytes were transferred. The failed run [40107851266](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40107851266) had transferred the first P05023 payload (1,090,519,040 bytes) before the old string comparison rejected it, but it did not save a durable hash receipt; its temporary raw file was removed only after derived output and Drive receipt verification. No hash is claimed for that old run.
- Validation [40109194403](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109194403) passed 217 tests in 3.25 s; eight workflow YAML files parsed, and actionlint v1.7.12 checksum/semantic checks passed. The subsequent receipt-order hardening is tested in [40109347836](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109347836): **217 tests passed in 5.73 s**, eight YAML files parsed and actionlint checks passed. The live CMR job confirms 5/5 exact-author P05023 HDF5 URLs; metadata-validation payload downloads remain 0.
- Raw replay run [40109347847](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109347847) skipped the acquire/analyze job because the exact `[run-know-place]` consent marker was absent. No raw replay was run on this follow-up. Paper reproduction remains `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Do not rerun the raw replay until the exact marker is deliberately supplied, and do not merge to main.


## 20. Latest live CMR artifact integrity and raw-run status — 2026-10-24

- Latest validation [40112970146](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112970146) tested commit `bc0913a203511879dc6ba6d101f04194bd307383`: **217 tests passed in 4.99 s**; eight workflow YAML files parsed; pinned actionlint v1.7.12 checksum and semantic validation passed; both jobs succeeded.
- Latest independently downloaded CMR artifact is from run [40112528293](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112528293): ID `12566734581`, 4,117 bytes, SHA-256 `ab1dc5ce3e237649b9c5e404d4c92e6b87c3dae3bf1565dde28e55f66dfe9a49`, matches GitHub's digest. Manifest: exact CMR identities 5/5, direct HDF5 URLs 5/5, blocking count 0, raw downloads 0, SHA-256 pins 0/5.
- Latest legacy raw replay [40112970152](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112970152) passed its decision job but skipped analysis because the branch commit message did not contain the exact `[run-know-place]` marker. Latest dedicated author-exact run [40109347847](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109347847) also skipped acquisition because its exact consent input was absent. No raw GOFF payload was downloaded.
- Paper reproduction remains `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Main remains unchanged at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.
- Report: `docs/know-place/evidence/LATEST_CMR_ARTIFACT_INTEGRITY_20261024.md`. Connected GitHub tools do not expose workflow dispatch; actual raw acquisition must be manually dispatched in Actions with `[run-know-place]` and configured Earthdata/Drive secrets.

## 21. Latest author-exact raw replay and status-label correction — 2026-10-24

- [x] Audited [run 40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362): exact author profile and consent passed; all five P05023 GOFF HDF5 files were downloaded, SHA-256-pinned, HDF5 identity-checked and grid-validated. Total bytes 5,473,566,720; grid 4311 × 4230, EPSG:32645, 80 m posting. Derived bundle and both Drive receipts were remotely verified; temporary raw files were removed after durable retention. Full receipts: `docs/know-place/evidence/AUTHOR_EXACT_RAW_REPLAY_AUDIT_20261024.md`.
- [x] Five-pair metrics were computed. The 2026-07-26 → 2026-08-19 pair gives median crown magnitude 0.966063 m, mean vector 1.722246 m, azimuth 277.793°, median rate 0.040253 m/day and median coherence R=0.852850. This is numerical agreement only; the report marks the comparison `NOT_COMPARABLE_EXACT_CROWN_GEOMETRY_UNVERIFIED`.
- [x] Corrected the wrapper's stale post-download status overwrite. Raw byte identity is now `FIVE_EXACT_AUTHOR_SOURCE_HASHES_PINNED`; paper status is `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard remains `NOT_EVALUATED`. The historical run artifact is immutable and keeps its pre-fix status label. No raw files were re-downloaded just to refresh the artifact.
- [x] Validation [40115947045](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40115947045), commit `5354a344ce19eac652fa8102c790fce18e18ec13`: 217 tests passed in 2.62 s; eight workflow YAMLs parsed; pinned actionlint v1.7.12 checksum and semantic validation passed. The live catalog stage downloaded zero payloads; raw replay skipped on subsequent push because no new consent marker was supplied.
- [ ] Verify the author-supplement crown geometry and control sampling, compare golden tables/masks, resolve terrain vertical-datum provenance, and run full-footprint screen parity. Do not claim hazard detection.
- Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no merge or write to main.

## 22. Follow-up: independently inspect the exact-author run artifact and validate post-cleanup receipt hardening — 2026-10-25

- [x] Downloaded GitHub artifact `know-place-author-exact-40114703362-1` (artifact ID `12567509703`) and independently verified its archive SHA-256 `d49b6aa10da27138de6b8b8f2af6a4b5d3ffd86a8ccb87cef7765e3c597a0b59` against GitHub's artifact digest; size 830,510 bytes. It contains five per-pair diagnostic NPZ files, CSV, reports, source/preflight manifests, provenance and Drive receipts; no raw `.h5`/`.hdf5` payload is in the artifact.
- [x] Inspected the five source SHA-256s and confirmed each exact P05023 product has `download_status=PASS`, `grid_validation_status=PASS`; manifest states 5 downloads, 5 hashes and 5 grid-valid products. Five HDF5 files totalled 5,473,566,720 bytes per authenticated preflight.
- [x] Reconfirmed target 2026-07-26 → 2026-08-19 exploratory statistics: 292 displacement-valid crown pixels; median magnitude 0.966063 m; mean vector magnitude 1.722246 m; azimuth 277.793°; median rate 0.040253 m/day; median directional coherence R=0.852850. This is a bounding-box crown approximation and exploratory controls, not author-method parity.
- [x] Independently verified derived Drive bundle SHA-256 `c82f68a11ff00f22aa5cb280116c319948c14a17bf07c8d7d3795c0f2c9aa28e` (414,897 bytes); both pre-cleanup Drive receipts show `remote_verification=PASS`, `raw_product_uploaded=false`. [Derived bundle in Drive](https://drive.google.com/file/d/1mz14C9s0KXqgMcVczrTM-aPmzvSjDg9f/view?usp=drivesdk).
- [!] Important evidence distinction: that historical artifact's original `drive-upload-receipt.json` and receipt-copy both say `raw_source_deleted=false`; those are pre-cleanup upload receipts, not post-cleanup evidence. The workflow's cleanup step did succeed, but the historical artifact does not independently prove cleanup in a durable post-delete receipt. Do not overstate that old receipt as proof.
- [x] Added a separate fail-closed post-cleanup receipt path in the current workflow: verify all five raw files against manifest SHA-256 and byte counts, verify remote derived bundle and receipt-copy, delete only the exact five raw HDF5 files, confirm zero remain, write `author-exact-raw-cleanup-receipt.json`, upload and verify that receipt, and check it in the final gate. Offline cleanup tests cover success, failed Drive verification, altered bytes, unexpected extra HDF5, and incomplete source manifest.
- [x] Latest isolated validation [40120575317](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40120575317), commit `60dcde7cb3b3895d419b14b689201b6d00d3eb07`: **224 tests passed in 4.00 s**; all eight Know Place workflows plus branch dispatcher parsed as YAML; pinned actionlint v1.7.12 checksum and semantic validation passed; both jobs succeeded. Live CMR confirms all five exact author data URLs with source downloads 0.
- [x] Latest raw replay workflow checks [40120575271](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40120575271) and [40120575285](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40120575285) completed their consent-gate jobs successfully and skipped acquisition/analysis because no new exact `[run-know-place]` marker was provided. No raw data were downloaded by these latest runs.
- [ ] Exercise the new post-cleanup receipt end-to-end only on a deliberately consented manual dispatch with `[run-know-place]`. Do not rerun the 5.47 GB replay without that explicit marker.
- Paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; do not merge or write to main.


## 23. Independent artifact recheck and latest validation — 2026-10-25

- [x] Re-downloaded artifact `know-place-author-exact-40114703362-1` (ID `12567509703`); independently recomputed SHA-256 `d49b6aa10da27138de6b8b8f2af6a4b5d3ffd86a8ccb87cef7765e3c597a0b59`, matching GitHub's digest. No raw HDF5 is in the artifact or its derived bundle.
- [x] Independently verified the five manifest entries are exact `P05023`, all download/hash/HDF5 identity/grid checks pass, and total source bytes are 5,473,566,720. Grid: 4311 × 4230, EPSG:32645, 80 m posting. See `docs/know-place/evidence/AUTHOR_EXACT_ARTIFACT_INDEPENDENT_RECHECK_20261025.md` for all five hashes and per-pair counts.
- [!] Both historical Drive receipts say `raw_source_deleted=false`; they prove remote verification of the derived bundle/receipt copy, not post-delete cleanup. The new post-cleanup receipt path was added later but is not yet exercised end-to-end.
- [x] Latest validation [40121243012](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40121243012), commit `56ef9f52977a7ac6a0c314b8560bfe4ff27743b0`: **224 tests passed in 2.58 s**, eight workflow YAMLs plus branch dispatcher parsed, pinned actionlint checksum/semantic validation passed; live CMR/data links confirmed 5/5 and raw downloads stayed 0.
- [x] Latest legacy run [40121243034](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40121243034) skipped acquisition because the exact consent marker was absent. No new raw products were downloaded in that run.
- [ ] Manually dispatch the author-exact workflow with exact `[run-know-place]` and configured Earthdata/Drive secrets to test post-cleanup receipt; do not infer consent from a prior request.
- Paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; do not merge or write to main.


## 24. Independent archive polygon-null replay — 2026-10-25

- The supplied Zenodo archive was read offline; no NISAR product was downloaded. Archive SHA-256 remains `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`.
- Recomputed the author's 5 × 5 R field from the five exported east/north site-field TIFFs using the archived finite-support/reflect-edge rule. Then replayed the archived `code/polygon_null.py` policy over all five pairs in one shared RNG sequence (`default_rng(20260907)`, up to 1,200 unique candidate centers, equal-area-in-pixel disk, reject supports below 60%). Compared all nine output values per pair to `tables/polygon_null.json`: **45/45 matches at stored precision, zero mismatches**, including accepted draw counts [857, 887, 920, 916, 996].
- Detailed evidence: `docs/know-place/evidence/AUTHOR_ARCHIVE_POLYGON_NULL_REPLAY_20261025.md`; checklist updated in `docs/KNOW_PLACE_ANALYSIS_CHECKLIST.md`.
- Interpretation limit: the archived polygon null is a post-hoc analysis, not a metric in the published paper. This check proves repeatability from cropped processed fields only; it does not establish source-grid pixel-mask parity, raw HDF5-to-field parity, full-footprint raster replay, or hazard-detection skill.
- Next independent/offline target: compare full author-compatible site-series calculations and geometry estimator against source code/processed fields, and inspect vertical-reference effects as a separate sensitivity. The raw source workflow still requires a new manual dispatch with the exact explicit input `[run-know-place]` to exercise the revised post-cleanup Drive receipt. Do not infer that consent from a normal continuation request.
- Paper reproduction remains `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; this work is confined to `feat/know-place-analysis`.


## 25. Author-compatible raw site-series profile integrated — 2026-10-25

- Added tools/know_place/author_raw_site_series.py as an explicit author-compatible alternative to the exploratory fixed-height analyzer. It uses nearest crown radar-grid XY cell geometry and nan-median across the height axis, SNR/magnitude-only validity, the author's conditional >200-valid-reference-ring correction, author north-up extent, and separate cropped-crown P1 and whole-WIDE polygon-null calculations.
- The runner expects the same five prevalidated P05023 products and writes a metric-by-metric comparison against the checked-in author Table S4 benchmark. It records source hashes, metadata/geometry policy, per-pair derived NPZ diagnostics, a CSV summary, and the complete JSON report. It cannot by itself reproduce the footprint-wide screen or evaluate hazard-detection skill.
- The acquisition wrapper runs this profile after the existing exploratory profile, reusing the same five local HDF5 files so it does not download the source products a second time. The author-exact workflow final gate requires five processed pairs and 65/65 Table S4 metric comparisons; mismatch reports remain available through the derived artifact and Drive retention, while the workflow fails closed.
- Validation run 40126196592 at commit 20c7d7b5c43d8b60b0361726ce605a65376936ac passed 229 tests, YAML parse for all eight workflows and the dispatcher, pinned actionlint semantic validation, and live exact-author CMR link preflight. The live preflight was catalog/link-only (raw payload downloads = 0).
- On commit 20c7d7b5c43d8b60b0361726ce605a65376936ac, both legacy and author-exact replay dispatches skipped the heavy acquisition jobs because the exact consent marker was absent. They are gate checks, not raw replay validation.
- Next step is one manual explicit-consent run of the author-exact replay with the exact [run-know-place] input, then inspect all 65 comparisons and the CSV/NPZ outputs. No consent is implied by continuation instructions. Continue to leave main untouched (baseline SHA 2218dfeb73353080d8d94bd733d9e7bd9a848886).
- Scientific status is unchanged until real source replay proves otherwise: no claim of full paper reproduction; no claim of hazard detection; full-footprint pixelwise screen parity and vertical-datum sensitivity remain separate gates.


## 26. Independent processed-field site-series replay — 2026-10-25

- Using only the supplied Zenodo ZIP's five 80 × 73 EPSG:4326 processed field TIFFs, recomputed valid crown counts, median crown displacement, interval rate, crown-cropped P1 coherence, and scene P1 coherence. All 25/25 values matched the archived nisar_pot_series and TableS4_site_series values at the published precision. Full per-pair values and method: docs/know-place/evidence/AUTHOR_ARCHIVE_SITE_SERIES_REPLAY_20261025.md.
- This is complementary to the separate polygon-null replay (45/45). P1 crown coherence is computed on the crown-cropped field, while polygon-null crown coherence comes from the full-WIDE coherence raster masked by crown bounds; these are intentionally different estimands.
- These archive-only checks prove derived-field post-processing reproducibility, not raw HDF5-to-field parity or full-footprint screen parity. The five exact P05023 input files were previously downloaded and hash-pinned in run 40114703362, but the newly added author-compatible raw runner has not yet been exercised against them in a fresh run.
- Validation of the author-compatible runner and integration at run 40126196592: 229 tests passed; all eight workflow YAMLs and the dispatcher parsed; pinned actionlint passed; live ASF/CMR found exact author links 5/5, with raw downloads = 0. Subsequent edits after this validation are documentation-only; raw workflow gates have also skipped acquisition as expected.
- Next gate: an explicitly consented author-exact workflow run must actually process the five P05023 HDF5 files through both profiles, then compare 65 archived Table S4 metrics. Do not infer consent from a continuation request. Full footprint screen parity, terrain vertical-datum sensitivity, and hazard-detection skill remain unverified; main baseline is still 2218dfeb73353080d8d94bd733d9e7bd9a848886.


## 27. 2026-10-25 — Run #17 source of truth, author dashboard, and safe render path

This section supersedes earlier status descriptions where the five exact author P05023 products were still described as unavailable. It does not erase the historical notes: previous X05026 observations remain historical-only, not author-exact inputs.

### Verified scientific result (run 40170290176, workflow run number 17)

- Source workflow: [SARGuardian AOI WKT E2E, Run #17](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), on `feat/know-place-analysis` at backend commit `417cc2f0156bb310f933b72edb9ecd359812f623`.
- Exact product identity: five author-selected NISAR L2 PR GOFF P05023, ascending T098, L-SAR HH, layer 2, 20 June–31 August 2026. All five payload SHA-256 values are in `author-exact-source-manifest.json`; HDF5 identity, byte count, grid shape and EPSG were validated.
- Site series: selected author-table checks 65/65 at archive rounding. P2/local-mean checks 15/15 at archive rounding.
- Full-footprint screen: three aggregate raster comparisons passed; the 106-row candidate inventory and 101-row Table S7 validated-zone table matched the archive.
- Retention: a derived-only result bundle and its receipts were uploaded and remotely verified in private Google Drive; five raw HDF5 files were deleted after the cleanup gate, and the post-delete receipt was remotely verified.
- Final scientific status remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `hazard_detection_status=NOT_EVALUATED`. Do not turn processing success into a complete-paper or hazard-detection claim.
- The arbitrary AOI/date measurement-engine job was skipped in Run #17 because its selected profile was the exact-author replay. This run therefore does not prove the generic AOI/date path or a website-to-dashboard product integration.

### Dashboard implementation

- New renderer: `tools/know_place/author_dashboard.py`. It consumes the author-exact derived result directory, not raw files. It draws embedded PNG previews from the saved author-compatible site arrays and the three footprint GeoTIFFs, and presents the five-interval displacement table, exact source hashes, P1/P2 comparisons, the author-table parity counts, the unresolved displacement-null status, and a Bengali plain-language explanation.
- Optical satellite images from The Business Standard and Geopera are linked to their publishers and explicitly labelled contextual; they are not registered to the crown mask and are not used in the displacement calculation. NISAR scientific maps are generated only from saved derived arrays/rasters. The rectangular crown outline remains an approximation, not an author-supplied editable polygon.
- New tests: `tools/tests/test_know_place_author_dashboard.py`; the isolated validation suite includes the dashboard module and tests. Validation run [#407](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40174209941) passed 255 tests and actionlint before the safe retained-artifact renderer was added.
- The author-exact replay workflow now has a dashboard-generation step and the final gate requires `dashboard.html`. This will be exercised only on a future explicitly authorized raw replay; that replay has not been run as part of this documentation/code change.
- New safe renderer workflow: `.github/workflows/know-place-author-dashboard.yml`. It takes an existing source Run ID/attempt, verifies the GitHub artifact digest and both ZIP integrity levels, rejects any HDF5 member, renders the HTML from the retained derived-only bundle, then uploads the HTML/manifest to Drive with remote receipts and publishes a short-lived Actions artifact. Default source is Run ID `40170290176`, attempt `1`. It downloads no NISAR raw payloads. The dedicated isolated validation run [#409](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40174655179), commit `b881fd73c65543c47c241df3f48ed96dfade69fd`, passed **255 tests in 4.36 s**, parsed all nine Know Place workflows plus the branch launcher, and passed pinned actionlint validation including `.github/workflows/know-place-author-dashboard.yml`. The safe render workflow itself has not yet been manually dispatched. Because its file is feature-branch-only, the usable UI route is through the shared-path [SARGuardian AOI WKT E2E dispatcher](https://github.com/moshiour0/SARGuardian-backend/actions/workflows/sarguardian-aoi-wkt-dispatcher.yml): select `feat/know-place-analysis`, choose `run_profile=render-author-dashboard`, then set `source_run_id=40170290176` and `source_attempt=1`. This branch-only route does not edit `main` and does not require `[run-know-place]` because it downloads no raw NISAR source.
- The safe renderer is intended to avoid a redundant five-product raw replay merely to render the current dashboard. The new dashboard workflow has not yet been manually dispatched; Drive receipt and artifact output from that workflow are therefore still pending.

### Next scientific acceptance gates

1. Render the existing Run #17 bundle using the safe dashboard workflow, then inspect the standalone HTML, image provenance, mobile layout, and Drive upload receipts. No raw replay is needed for this step.
2. Investigate the missing displacement-null draw-level generator / author sampling implementation. Until that comparison is reproduced, keep the paper reproduction status partial; never substitute the polygon-null percentile for the displacement-null result.
3. Obtain and verify the exact author crown vector or mask and quantify source-grid pixel-mask parity.
4. Keep the source-faithful EGM2008-versus-ellipsoidal-height behaviour explicitly disclosed. Any datum correction is a separate, named sensitivity experiment with its own manifest and comparison—not a silent edit to the author method.
5. Continue the six-site / event and non-event validation plan with frozen event-level splits, exact product identities, independent labels, held-out thresholds, and false-alarm / lead-time metrics. Only after this can detection or early-warning performance be evaluated.

### Branch safety

All changes in this continuation are confined to `feat/know-place-analysis`. Backend `main` remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; do not merge, cherry-pick, or edit main until the dashboard-bearing E2E gate and a separately reviewed scientific acceptance gate pass. No new raw NISAR downloads were authorized or performed in this continuation.


### External imagery provenance correction — 2026-10-25

- The dashboard's Geopera context card now uses the corrected stereo-elevation-change map and links to the 1 September follow-up, not the original 28 August cover image. The follow-up explicitly retracts the earlier parallax sediment map because the assumed opposite-side stereo viewing geometry was wrong; it says the derived sediment wedge was noise, not measured deposition. Source: https://geopera.com/blog/bhote-koshi-stereo-elevation-model .
- Keep this image strictly as **external WorldView-3 stereo context**, not as NISAR-derived displacement and not as a SARGuardian measurement input. The original article and its retracted map must not be used to substantiate scientific claims.
- The TBS pre-event optical thumbnail remains publisher-attributed context only; neither external image is registered to the NISAR crown or included in displacement calculations.

## 28. 2026-10-25 — Run #17 standalone dashboard artifact and external imagery correction

- Downloaded Run #17 artifact ID `12589719900`, `know-place-author-exact-40170290176-1`, from [run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176). Archive size: 18,313,236 bytes; computed SHA-256 `a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`, matching GitHub's published artifact digest. ZIP CRC passed. Its nested `author-exact-derived-results.zip` contains derived outputs and no raw HDF5.
- Checked the dashboard's five embedded source SHA-256 values against the Run #17 source manifest: 5/5 found. Cross-checked the displayed target pair and comparison totals against the source JSON/CSV reports: 65/65 selected site-series checks, 15/15 P2 checks, 3/3 aggregate footprint rasters, 106 candidate rows, and 101 Table S7 validated zones.
- Standalone HTML: `SARGuardian_Know_Place_Bhote_Koshi_dashboard_run17.html`, 94,467 bytes, SHA-256 `ff8700f363068e41581ec2075598305144b76cf41e53731c943c9fc319f71c5e`. Its companion manifest records the source artifact and output hashes. A ZIP package includes the HTML, manifest, readme, and five extracted scientific preview PNGs. This local package is usable for inspection; it is not proof that the GitHub dashboard-render workflow has completed or uploaded to Drive.
- Material imagery-source correction: replaced the old Geopera cover image with the corrected stereo-elevation-change image from its 1 September follow-up. The follow-up explicitly retracts the original parallax sediment map because the viewing-geometry assumption was wrong. Source: https://geopera.com/blog/bhote-koshi-stereo-elevation-model . The corrected WorldView-3 product is contextual only, not a NISAR displacement input. Regression tests enforce the new source URL and corrected-versus-retracted note.
- Latest isolated validation [run 40187665186](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40187665186), branch commit `a075dd867d9116589f6b076403038d60e283ff53`: **256 tests passed**, all nine Know Place workflows plus the shared dispatcher parsed as YAML, and pinned actionlint v1.7.12 semantic validation passed. The current branch contains the renderer and safe `render-author-dashboard` profile.
- The safe renderer UI workflow has not been manually dispatched in this session; the available GitHub actions connector does not expose a workflow-dispatch call. No new raw GOFF replay was launched; the latest push-triggered raw replay job was skipped at the explicit-consent gate. Use the shared dispatcher on `feat/know-place-analysis`, profile `render-author-dashboard`, source run ID `40170290176`, attempt `1`, to exercise artifact-to-dashboard-to-Drive E2E without NISAR raw downloads.
- Current paper status remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`.

## 29. 2026-10-25 — Safe dashboard render E2E passed (Run #19)

- Safe dispatcher run [40189992766](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766) completed successfully on `feat/know-place-analysis` at `ddab6dfa17b9a8b3d8cda31fbca11e5121c0f7f2`.
- The source Run #17 artifact (`know-place-author-exact-40170290176-1`) was selected on the isolated branch, its GitHub SHA-256 and ZIP CRC were verified, the nested derived bundle integrity passed, and both containers were confirmed to contain zero raw HDF5 files.
- Required evidence files passed preflight and the dashboard renderer reported `AUTHOR_DASHBOARD_STATUS=PASS`. The output HTML is 81,214 bytes; manifest records source artifact SHA-256 `a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`, source manifest SHA-256 `99fbc858116fa67e88c67ce6d33139a2df53bb56ca3a725780bb508c918d9a5b`, and dashboard SHA-256 `f41ce20cf797df5b447edce42359f0a395ec26691bea61f9c1db7c073021b34c`.
- Google Drive upload verified both `dashboard.html` and `dashboard-run-manifest.json`; the first receipt was then uploaded and independently verified via a second receipt. Log status: `DASHBOARD_DRIVE_RETENTION=PASS`, `RAW_PRODUCT_UPLOADED=false`. The published Actions artifact is [artifact 12596788838](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766/artifacts/12596788838), digest `74ff461d77553aba29f2a959cf744a0fc31a1bb1eeec6de12ac89284721d66c2`.
- Run #19 ran only the safe retained-artifact dashboard profile; both raw author-exact replay and generic AOI/date jobs were skipped. The push-triggered replay Run #477 also skipped its analysis job because no explicit `[run-know-place]` consent was present. No raw HDF5 was downloaded by these render/gate runs.
- Isolated validation [run #417](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189684104) passed 257 tests, all nine workflow YAML checks, pinned actionlint v1.7.12, and live ASF/CMR identity/link checks without source payload download.
- The dashboard E2E is now complete. The science status is unchanged: `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`.
- Next science gates: reproduce the paper's displacement-null sampling/percentile from author code or a fully specified independent reconstruction; verify exact crown vector/polygon and source-grid mask parity; run a separately labelled vertical-datum sensitivity; then complete preregistered multi-site event/non-event validation. Do not present the 94.7th percentile or 0.965 m as detection/early-warning evidence by themselves.
- Backend `main` remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no merge or main-branch edit was made.

## 30. 2026-10-25 — Source-code audit of the displacement-null gap

- Inspected the supplied Zenodo archive `bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip` by listing its 91 members and searching all 34 Python scripts for displacement-null generation calls and algorithms.
- The archive contains `tables/displacement_null.json` with five aggregate rows only. They report crown medians [0.99, 0.54, 0.30, 0.96, 0.33] m, null medians [0.17, 0.21, 0.14, 0.14, 0.09] m, and percentiles [94.9, 87.5, 81.0, 94.7, 81.3]. It contains no draw-level samples, per-draw valid counts, or generation seed in that table.
- No displacement-null generator script exists in the archive's code folder. `code/canonical.py` loads the JSON and `code/build_cee_si_tables.py` consumes it to build Supplementary Table 4; those are data readers/formatters, not the sampler.
- `code/polygon_null.py` generates size-matched random-region statistics for directional coherence `R`: it samples candidate centres from finite-`R` cells, constructs disks, accepts at least 60% of target R-valid cells, and computes `R) percentiles. It does **not** calculate per-draw median displacement magnitude. Current backend `author_polygon_null_statistics()` follows this coherence-only path; its seed/policy must not be presented as the displacement-null seed/policy.
- The paper's methods describe compact regions matching the crown's valid-pixel count, placed at random valid-ground positions inside the fixed 6 km box, rejecting insufficiently valid placements; reported accepted draws are 857–996 per pair. This is enough to specify a method-derived independent reconstruction, but the available archive does not prove the exact displacement sampler's shape, RNG/seed, sampling order, or per-draw acceptance implementation.
- Next gate: implement/test a separately named displacement-null reconstruction over the archived displacement fields, expose and version every sampling decision, retain per-draw diagnostics and a source/data manifest, and compare the aggregate outputs to the five published rows. Unless the exact author generator/policy is independently recovered, label this `METHOD_DERIVED_INDEPENDENT_RECONSTRUCTION`, not exact author-code parity; do not silently tune seeds/parameters until the published percentiles match.
- The 292-versus-298 count is not a mismatch: 292 is displacement-valid count `n` in `tables/nisar_pot_series.json`; 298 is full-field coherence-valid crown count `n_px` in `tables/polygon_null.json` for the 26 July–19 August pair. The two quantities use distinct validity masks/estimands.
- Scientific status remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`. Backend `main` remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`.

## 31. 2026-10-25 — First independent displacement-null reconstruction

- Added `tools/know_place/displacement_null.py` and tests; wired both into the isolated validation workflow.
- Source audit found the five aggregate displacement-null values in the Zenodo archive but no generator, RNG/seed, draw-level values, or rejection trail. The archive's `code/polygon_null.py` computes directional coherence R and is not the displacement sampler.
- Ran policy `method-derived-displacement-null-v1` on the five deposited processed offset TIFFs only; raw HDF5 was not read. The deterministic seed is 20261025, NumPy PCG64, shared across ordered pairs. Policy assumes raster-index disks, at most 1,200 centres sampled without replacement, and >=60% valid-cell acceptance. These are disclosed independent assumptions, not source-recovered author policy.
- Observed crown medians round to the deposited values at two decimals; independent null medians are close but percentiles differ (for 26 Jul–19 Aug: 92.2 vs published 94.7). This must remain `INDEPENDENT_METHOD_DERIVED_NOT_AUTHOR_SAMPLER_PARITY`; do not tune settings to force matching.
- The full run report, including every draw and reject reason, is locally packaged for review. Its source TIFF hashes are recorded in the report and it was generated with zero raw-HDF5 reads.
- Next: run a predeclared sensitivity matrix over plausible compact-region and acceptance choices, record variation rather than select the best-looking setting, and keep paper reproduction partial. Crown source-grid mask parity and vertical-datum sensitivity follow.
- Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no main edits or raw replay.

### 32. 2026-10-25 — Displacement-null seed / acceptance sensitivity completed

- A fixed, reported 35-row sensitivity matrix has been run over minimum valid fraction 0.4, 0.5, 0.6, 0.7, 0.8 at seed 20261025 and seeds 20261026/20261027 at the 0.6 default. Full rows: `docs/know-place/evidence/DISPLACEMENT_NULL_SENSITIVITY_20261025.csv`.
- For the 26 Jul–19 Aug pair, the tested acceptance fractions yield 91.4–93.8 percentile; three seeds at 0.6 yield 92.2–93.5. That range shows sampling-policy dependence; no setting was selected to match the published 94.7.
- Remaining sensitivity: alternate region geometry (disk vs another explicitly specified compact shape). The method-derived default remains unchanged. Paper status remains partial and hazard detection not evaluated.

### 33. 2026-10-25 — Compact-region shape sensitivity completed

- Extended the independent null module to support three explicitly named raster-index shapes: disk (default), square and diamond. All three policies are written into the report; an invalid shape fails closed.
- Added a deterministic regression test proving reproducibility per shape and a distinct result when the spatial statistic varies.
- Ran a predeclared shape comparison at seed 20261025, minimum-valid fraction 0.6 and 1,200 candidate centres per pair. On the 26 Jul–19 Aug pair: disk 92.2nd percentile (835 accepted), square 91.8 (807 accepted), diamond 93.0 (918 accepted). Full five-pair table is `docs/know-place/evidence/DISPLACEMENT_NULL_SHAPE_SENSITIVITY_20261025.csv`.
- None is selected by proximity to published 94.7. These are method-derived sensitivity analyses because exact author source remains unavailable. Paper reproduction remains partial; hazard detection remains not evaluated.


## 34. 2026-10-25 — Crown/source-grid mask consistency audit

- Added the crown-mask audit module, regression tests, and evidence on the isolated branch.
- Source artifact SHA-256: a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682; author archive SHA-256: 002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3. Outer and nested ZIP CRC passed; raw HDF5 member count is zero.
- Each of the five site and halo masks contains 323 cells. Independent inverse-projection against the published WGS84 rectangle, saved endpoint/searchsorted crop, and cross-array source-grid mapping all have zero XOR cells.
- Displacement-valid counts [283, 294, 296, 292, 195] match series table n; distinct coherence-valid counts [302, 299, 302, 298, 202] match polygon-null n_px.
- Corrected a stale generic test fixture whose smaller bounds dropped 17 western-edge cells on the pinned crop. The published exact bounds are now used.
- The audit is saved-mask/published-bounds consistency, not proof of original author-vector parity; the archive contains no editable vector or golden pixel mask. Paper status remains PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED; hazard detection remains NOT_EVALUATED.
- No raw replay was run. All modifications remain on feat/know-place-analysis; main remains 2218dfeb73353080d8d94bd733d9e7bd9a848886.


## 35. 2026-10-25 — Multi-site Himalayan source-geometry leads

- Reviewed the public IIRS article for NISAR/ITS_LIVE Himalayan comparison details. It reports January 2026 ranges for Samudra Tapu and Bara Shigri but the reviewed page text does not pin exact NISAR pairs/granules, AOI polygon/vector hash, or a pinned ITS_LIVE product/version.
- Added a metadata-only source-geometry lead ledger. Samudra Tapu's RGI 6 ID RGI60-14.15613 is cited in a published review; its RGI 7 identifier is left null until verified against source data. Bara Shigri's RGI 6 ID RGI60-14.15447 and RGI 7 lead RGI2000-v7.0-G-14-32495 are cited in literature, but the actual inventory archive and polygon bytes have not yet been hash-verified.
- RGI 7.0 is an inventory snapshot targeted around year 2000; Region 14 documentation describes GAMDAM/GGI18 replacement outlines mostly mapped from imagery around 2002. Such geometry can be used only as a separate independent inventory-outline ROI, not silently equated with the IIRS mask or January 2026 ice boundary.
- Test contract forbids exact AOI/product/source hashes or scores from being inferred from these leads. No RGI archive, ITS_LIVE payload or NISAR raw payload was downloaded; no catalog query/scoring executed.
- Evidence: docs/know-place/evidence/MULTISITE_REFERENCE_GEOMETRY_AUDIT_20261025.md; ledger: docs/know-place/reference/multi_site_source_geometry_leads_20261025.json.


## 36. 2026-10-25 — Crown audit integration + glacier geometry lead CI gate

- Latest commit before this note: 55dc8c2b27e44531d0ebff65178397846cfd0131 on feat/know-place-analysis.
- Isolated validation [run 40198744624](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40198744624) completed successfully: 266 tests passed in 5.70 s, all nine Know Place workflow YAML files plus the shared dispatcher parsed, pinned actionlint v1.7.12 passed, and both live ASF/CMR metadata-only catalog gates passed.
- Matching push-triggered raw replay gate [run 40198744626](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40198744626) completed successfully with the five-pair analysis job SKIPPED because no explicit [run-know-place] consent was present. No new raw GOFF HDF5 was downloaded.
- The crown-mask audit's new full-archive synthetic tests passed, including a deliberately corrupted mask failing closed. The actual retained Run #17 source artifact and pinned Zenodo archive were independently inspected earlier; saved masks match the published rectangle/source grid with zero XOR differences, while original author-vector parity remains unverified.
- The Himalayan source-geometry lead ledger records the IIRS article's published velocity ranges and RGI7 lineage, without asserting exact AOIs or source IDs not present in public text. No RGI archive, NISAR/ITS_LIVE payload or geometry bytes were fetched; Samudra Tapu's RGI7 ID remains unresolved, and Bara Shigri's cited RGI7 ID remains literature-sourced but not source-archive verified.
- Scientific state remains partial: exact displacement-null sampler still unresolved; vertical datum's effect on actual GOFF geometry coefficients cannot be quantified without the source geometry cube; paper reproduction remains partial and hazard detection remains NOT_EVALUATED.
- Backend main remains 2218dfeb73353080d8d94bd733d9e7bd9a848886; all work is isolated on feat/know-place-analysis.


## 37. 2026-10-26 — Arbitrary-AOI interactive map integrated

- Added `tools/know_place/interactive_map.py` and wired `tools/know_place/aoi_runner.py` to write `visuals/interactive-map.html` for catalog-only dry runs and for measurement-result rendering. The existing offline `visuals/dashboard.html` is retained.
- The Leaflet/OpenStreetMap view presents the request's WGS84 AOI polygon, selectable acquisition pair, approximate downsampled displacement-magnitude overlay, overlay-opacity control, AOI visibility toggle, zoom-to-AOI, valid/total AOI pixels, median magnitude, interval-average rate, high-motion review count, source hash, CRS, scientific-status gates, and a relative link to the native-grid GeoTIFF.
- The map requires an internet connection for Leaflet assets and OpenStreetMap tiles; the original dashboard remains offline-capable. The browser overlay is a presentation-only geographic warp of a small preview. The linked native-grid GeoTIFF and run manifest remain authoritative; do not report map pixels as independent measurements.
- The generic AOI workflow supports a valid single-ring WGS84 polygon plus inclusive dates, but usable measurements still depend on actual NISAR GOFF catalogue/source coverage, product maturity/track and the selected time range. This is not a guarantee of worldwide or all-date coverage. Downloaded jobs retain the configured product-count guard and require the exact `[run-know-place]` marker plus Earthdata/Drive credentials.
- Code commit: `00adc9b308360fec1314aba17f4fa8d4a1f34343`. Validation workflow/test-manifest correction: `7d6e8789c2cc7bd93c2c1c8790e23f6f636b8039`. Isolated CI [run 40224867156](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40224867156) passed **287 tests in 3.44 s**; Python compilation, workflow YAML parsing, actionlint checksum/semantic validation, and metadata-only ASF/CMR gates passed. The interactive-map test module is explicitly listed in CI; an earlier run's unchanged count of 281 was insufficient because it omitted the new test file.
- Paired push-triggered replay gate [run 40224867157](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40224867157) passed its consent gate and **skipped** the expensive five-pair raw replay; no new raw GOFF HDF5 payloads were downloaded. Do not dispatch a source replay without the exact consent marker.
- At the time of the initial map UI commit, live end-to-end catalogue validation had not yet been performed. Section 38 records the later successful catalogue-only AOI smoke test. That smoke test creates the map file but does not perform a browser/device visual test or displacement measurement. Paper-reproduction status remains partial; hazard detection remains `NOT_EVALUATED`; operational warning remains `NOT_IMPLEMENTED`.
- Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`. All changes stay on `feat/know-place-analysis`.


## 38. 2026-10-26 — AOI catalog failure fixed; explicit release policy and live dry-run pass

- Root cause of failed live run [40226250585](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40226250585): the AOI catalog path was using a fragile NISAR collection/maturity query, then excluded real GOFF products due polarization normalization. Once that was corrected, the planner correctly failed closed on an interval with both X05026 and P05023. The next failure was a validation false positive: it required every excluded catalog row (including non-GOFF products) to have PROVISIONAL maturity.
- Fixed and regression-tested the ASF query using the `ASFSearchOptions` collection-alias control, a versioned `asf_search==13.0.1` runtime, exact GOFF product-type gates, normalized HH/HV polarization tokens, and metadata diagnostics for no-result runs. Non-GOFF records are preserved as exclusions, not misparsed as GOFF.
- Added normalized `product_selection.allowed_release_ids` to the AOI request contract, request hash, manifest and runner. The child workflow accepts optional comma-separated exact release IDs and the shared dispatcher forwards them. Blank leaves the choice open; release ambiguity still fails closed. This does not silently replace an exact P05023 product with historical X05026.
- The live smoke test explicitly allowed `P05023` for the historical Bhote Koshi AOI/date window (2026-06-20 to 2026-08-31, HH, track 098 ascending). Its result: `CATALOG_AND_SERIES_PLAN_READY`, 8 eligible PROVISIONAL candidates, 4 selected P05023 pairs, `visuals/dashboard.html` and `visuals/interactive-map.html` present. The gate passed without raw downloads; `MEASUREMENT_STATUS=NOT_RUN_DRY_RUN` is intentional.
- Latest isolated CI [run 40228894456](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40228894456) passed 294 tests, compile, all workflow YAML parsing, actionlint, live ASF identity gates, exact-author CMR URL gates, and the arbitrary-AOI smoke test. Matching raw replay gate [run 40228894462](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40228894462) skipped its five-pair raw analysis job because this patch did not include explicit consent for source acquisition; no raw GOFF HDF5 was downloaded during this fix.
- Browser/device rendering and actual displacement measurement from this newly selected AOI remain separate, not-yet-performed validation steps. The smoke test validates HTML generation and artifact inclusion, not a real browser screenshot or scientific displacement result.
- Main is still `2218dfeb73353080d8d94bd733d9e7bd9a848886`; all edits remain isolated to `feat/know-place-analysis`.

## 39. Exact-author authorization and cancellation of the mismatched historical replay (2026-10-26)

- The user explicitly authorized a Bhote Koshi raw-source run using the exact author release `P05023`, with the exact marker `[run-know-place]`. Authorization does not include substituting or relabelling historical `X05026`.
- A push-triggered legacy workflow was mistakenly enabled by that marker before its source-selection boundary was checked. Run [40231488633](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40231488633) was then cancelled. Its logs show that it downloaded the historical first product `NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_X05026_N_F_J_001` (1,090,519,040 bytes; SHA-256 `df870327e662b8d4c49d242437f7a2b6e44e3c7bdf99169910c6020689736918)), three complete `P05023` granules, and a partial fifth `P05023` download. This run is **not** a usable analysis result.
- The run was cancelled before manifest-based measurement, scientific analysis, Drive upload, or derived-output retention. Its Actions artifact contains only the small catalog/download-plan/log bundle (8,105 bytes), not raw HDF5. The temporary raw files remained only on the GitHub-hosted ephemeral runner; no raw HDF5 was uploaded to Drive or committed to Git. The canceled run's scientific and Drive gates failed as expected because analysis/retention had not run.
- Safety correction: `.github/workflows/know-place-analysis-run.yml` is now explicitly a historical mixed-release replay and requires BOTH `[run-know-place]` and `[run-mixed-release-replay]`. The ordinary author-exact consent marker alone cannot enable a workflow whose frozen manifest includes `X05026`.
- Added `.github/workflows/know-place-author-exact-consent-bridge.yml`, which calls the reusable `.github/workflows/know-place-author-exact-replay.yml` with the exact `[run-know-place]` input only when a request-file push carries that exact commit-message marker. Added the bridge to the isolated workflow validator. The current user-authorized P05023 execution must go only through this author-exact workflow.
- Until a new author-exact run produces inspectable source hashes, per-pair metrics, the scientific report, and verified private Drive receipts, do not describe the newly requested run as completed. The separate historical successful exact-author run remains prior evidence, not a substitute for the current run.
- Main remains at `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no Know Place changes were written to main.

## 40. 2026-10-26 — First consented live P05023 measurement complete; displacement-null numeric audit passes

- User authorization was provided for the actual Bhote Koshi run with exact release `P05023` and marker `[run-know-place]`. Author-exact workflow [run 40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596) completed successfully on this branch at backend commit `8063e9fa699a5f53e835da2f93d22d3a2a07f3a0`; this supersedes section 39's “new run still pending” statement.
- Five of five exact CMR GOFF granules were downloaded, HDF5 identity/byte count/SHA-256 verified, and each grid validated at 4311 × 4230, EPSG:32645, 80 m. Full hashes/bytes and pair metrics: `docs/know-place/evidence/AUTHOR_EXACT_P05023_MEASUREMENT_20261026.md`; source manifest and complete diagnostics reside in the run artifact.
- Measured 26 Jul–19 Aug exploratory pair: 292 valid crown pixels, median horizontal magnitude 0.96606 m, median magnitude rate 4.0253 cm/day, mean-vector magnitude 1.72225 m, azimuth 277.793° clockwise from north, median directional coherence R=0.85285. In the separately labelled author-compatible site-series calculation, median=0.96451 m and rate=4.01879 cm/day. These are measured quantities, not a verified warning threshold.
- Exact-author site-series table checks: 65/65 at archive rounding; P2 checks: 15/15; footprint aggregate rasters: 3/3; 106/106 candidate inventory and 101/101 validated zones passed. The self-contained `dashboard.html` (81,214 bytes) and derived-only bundle were preserved.
- Private Drive verified the derived bundle (9,200,117 bytes) and receipts. After remote bundle/receipt verification, 5/5 temporary raw HDF5 files were deleted; remaining raw HDF5 count=0; raw HDF5 uploaded=false. Post-delete cleanup receipt was itself uploaded and remotely verified. Actions artifact [12613577460](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596/artifacts/12613577460).
- Derived-only displacement-null workflow [run 40233222258](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258) passed all five crown medians, null medians, and percentiles at published table precision (15/15 numeric fields, 5/5 intervals). Its evidence report is `docs/know-place/evidence/DISPLACEMENT_NULL_ARCHIVE_RECONSTRUCTION_20261026.md` and artifact [12613704622](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258/artifacts/12613704622). This audit used the deposited GeoTIFFs only; it did not download raw GOFF HDF5.
- Critical limitation remains: the Zenodo archive does not contain the original displacement-null generator or draw/rejection history, so original generator/draw-sequence identity remains UNVERIFIED despite numeric match. The crown is a published-bounds rectangle approximation, not the original author editable vector; exact crown geometry and original RGI 6.0 overlay remain unverified. Prepared DEM elevations and radar-grid HAE were not vertically transformed in the author-compatible P2 path.
- Overall paper status remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`; operational warning `NOT_IMPLEMENTED`. No event-level detection skill was evaluated.
- Isolated validation [run 40233222222](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222222) passed (semantic workflow validation, test suite and no-download live catalog gates). The historical mixed-release raw job was skipped because this commit did not have its separate `[run-mixed-release-replay]` token. Main SHA remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no main edits or merges.
- The real-measurement map, browser smoke and private-Drive retention are now complete; see section 41. Generic arbitrary-AOI measurement-map coverage and manual mobile-device smoke are still open.

## 41. 2026-10-26 — Real-measurement interactive map and crown-masked Chromium smoke PASS

- Rendered from retained derived-only artifact of exact-author measurement [run 40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596); latest corrected map workflow [run 40237180566](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566) succeeded. It reused verified derived outputs and downloaded no raw GOFF HDF5.
- Latest artifact [12615556980](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566/artifacts/12615556980), source commit `6863a771c27a91135ba4c7d107b8d3d3293dd266`; ZIP SHA-256 `f5e9827889018bcc30476f02c2e6eab88d309d87ee42ba44214537b474292627`. Includes `interactive-map.html`, browser screenshot, machine-readable smoke checks, provenance and two Drive receipts.
- Chromium opened the real measurement map, all five pair options were present, selected 2026-07-26 → 2026-08-19, Leaflet loaded, and zero JS page errors occurred. **16/16 assertions passed.** Selected pair: exact `P05023`; 292/323 (90.4%) valid crown-mask pixels; median horizontal magnitude 0.966 m; descriptive rate 0.0403 m/day; source EPSG:32645.
- Preview correction: only valid pixels within the crown/AOI mask are coloured; outside-mask and invalid pixels are transparent. UI explicitly states this, identifies the crown as a published-bounds rectangle approximation (not the original author editable vector), renders the paper-reproduction state in readable form, shows missing review count as an em dash, and hides the non-existent native-grid GeoTIFF link. Coloured preview remains a downsampled, geographically warped presentation layer, not an authoritative raster.
- Private Drive upload and remote verification passed for the new map evidence ZIP (379,261 bytes); receipt copy also remotely verified; raw product upload=false. [Open retained Drive evidence ZIP](https://drive.google.com/file/d/1PoQgB8rfeaKYMh4qauYfO35wzY3DnKjA/view?usp=drivesdk). Artifact [12615556980](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566/artifacts/12615556980).
- Isolated validation [run 40237084749](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237084749) passed after the preview-mask changes, including tests enforcing masking of surrounding pixels. The paired raw replay was skipped; no raw HDF5 was downloaded for these UI changes.
- Remaining: exercise a generic arbitrary-AOI measurement result through this exact browser/retention path, perform manual mobile-device smoke, obtain author-exact editable crown/RGI/terrain provenance, and independently validate event/non-event hazard-detection skill. `HAZARD_DETECTION_STATUS=NOT_EVALUATED`; `OPERATIONAL_WARNING_STATUS=NOT_IMPLEMENTED`.
- Main SHA remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no changes or merges to `main`.

## 42. 2026-10-26 — Crown-masked interactive map final QA complete

- Final corrected map workflow [40237180566](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566) succeeded on commit `6863a771c27a91135ba4c7d107b8d3d3293dd266`; artifact [12615556980](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237180566/artifacts/12615556980), SHA-256 `f5e9827889018bcc30476f02c2e6eab88d309d87ee42ba44214537b474292627`.
- Reused existing measurement artifact #40232441596 only: no raw GOFF download and no new measurement. The preview now renders colour only where pixels are both valid and inside the crown mask; valid surrounding-scene pixels are transparent.
- Final Chromium report `browser-smoke.json`: **PASS 16/16 checks**, zero page errors. It checked five pair options, critical 2026-07-26 → 2026-08-19 selection, exact release `P05023`, 292/323 (90.4%) valid crown-mask pixels, median 0.966063 m / 0.0402526 m/day, source SHA, source grid EPSG:32645, readable partial reproduction caveat, geometry approximation warning, transparent crown-only preview, missing review count shown as `—`, no fictitious native-grid GeoTIFF link and Leaflet loaded.
- Private Drive uploaded rendered evidence ZIP (`author-map-rendered-evidence.zip`, 379,261 bytes) and copied the receipt; both remote verification fields are `PASS`; `raw_product_uploaded=false`. No HDF5 is present in either the rendered bundle or final user-facing ZIP.
- Locally assembled delivery files: `BhoteKoshi_Interactive_Map.html`, `BhoteKoshi_Interactive_Map_Browser_Smoke.png`, `BhoteKoshi_Interactive_Map_Browser_Smoke.json`, `BhoteKoshi_Interactive_Map_Provenance.json`, and `BhoteKoshi_Interactive_Map_Evidence_2026-10-26.zip`. Map SHA-256: `64a0c9a948dfeb462bbbfb2700ebf8ca5081b881f8672717c5c9b7901031637b`; delivery ZIP SHA-256: `ed471a2339888ab16efe1760baee7d2f997990bf3ab5c7249e195ae2039e3b22`.
- Current measurement result is still exploratory: paper reproduction remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; original null-generator/draw identity and exact author crown/RGI/terrain provenance remain unresolved. `HAZARD_DETECTION_STATUS=NOT_EVALUATED`; `OPERATIONAL_WARNING_STATUS=NOT_IMPLEMENTED`. Mobile-device smoke and a generic arbitrary-AOI measurement bundle test remain future release gates.
- Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no changes/merge to main.



## 43. 2026-10-26 — Responsive browser gate passes for retained author-exact map

- Branch is `feat/know-place-analysis`; latest map-render code and diagnostics commit: `a6c5a4ed696e3066bf770ed5634339a9b655073d`. No merge or edit to `main`.
- Successful end-to-end map render: [GitHub Actions run #40240016012](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40240016012), artifact [#12616437285](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40240016012/artifacts/12616437285). The retained source is still derived-only artifact of run #40232441596; map render did not read/download raw HDF5 and did not make a new measurement.
- Desktop browser gate remains 16/16 PASS, zero JavaScript page errors; responsive gate passed at 360×800 mobile, 390×844 mobile, 768×1024 tablet and 844×390 landscape, with five assertions per viewport (no horizontal overflow, map fits, usable map height, pair control visible, 26 July–19 August critical interval selectable). Detailed viewport widths are recorded in `browser-smoke.json`.
- Diagnosed actual viewport expansion to a 568px+ layout viewport: the unbroken 64-character source SHA-256 string created excess min-content width. Added wrapping to `#source-hash` and shortened selector option labels (date interval + release; detailed status remains in the selected-pair panel). Verified the root-cause fix with isolated Chromium plus the same GitHub Actions browser run; mobile viewports now report window/document/body widths of exactly 360 and 390 pixels respectively and selector widths 306/336 pixels.
- Private Drive remote verification PASS for evidence ZIP `author-map-rendered-evidence.zip`, 1,052,241 bytes, SHA-256 `710835c48a477848335d74b688f1a371669a7da747288b2454c4d896ab09a0e8`; receipt-of-receipt remote verification PASS; `raw_product_uploaded=false`. No HDF5 members in the rendered evidence ZIP.
- Whole-paper status remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. Browser QA is presentation QA, not hazard validation.
- The isolated validation for the same commit passed in run #40240016149, including scientific/unit/integration tests, live ASF identity gates with no downloads, exact-author CMR link checks without payload download and arbitrary-AOI catalog-only dry-run.
- Remaining gates: physical-device mobile smoke; a browser test for a generic arbitrary-AOI **measurement** bundle; exact editable author crown geometry/RGI/terrain provenance and original null-generator identity; independent labelled multi-event/non-event hazard validation. Do not silently substitute historical `X05026` for `P05023` and do not call this hazard detection.


## 44. 2026-10-26 — Author-deposited crown AOI source-code audit

- Independently inspected the deposited CC BY 4.0 source/code archive (91 members; ZIP CRC test passed; no `.h5`/`.hdf5` members).
- `code/make_pot_figure.py:45` defines `AOI = (85.5245, 28.2847, 85.5400, 28.2970)` and calls it the source AOI; `code/nhess_content.py:150–152` documents the same extent as the crown polygon. `code/make_fig_timeseries.py:53–58` applies `crown_slice` by deriving longitude/latitude axes and selecting row/column index ranges with `searchsorted`. Thus the deposited reference implementation defines a rectangular AOI window; no separate editable crown-vector file is present in the archive inventory.
- Do **not** mistake `extent_CC-BY-NC-4.0/flow_extent.shp` for the source crown AOI: it is a separately licensed flow/runout extent (CC BY-NC 4.0), not the pre-event crown mask. `inventory/candidates_attributed.gpkg` and the associated shapefile are footprint-wide candidate inventory, not a dedicated crown vector.
- Updated the interactive map note to show the exact author-script rectangle bounds and explicitly state that native-grid pixel-mask edge-inclusion parity is still unverified. This is more precise than saying the geographical bounds themselves are unknown, but does not claim a matching golden mask.
- Remaining geometry validation: reproduce the author crop index semantics from `crown_slice` on the identical source geolocation arrays/grid, then compare the resulting selected-cell mask and all five per-pair valid-count/statistic outputs. Without those exact grids/masks the pixel support remains an unresolved source-parity gate.
- Scientific status remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`.
