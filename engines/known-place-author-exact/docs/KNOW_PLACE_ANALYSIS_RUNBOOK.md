# Know Place Analysis — Isolated Runbook

This guide applies only to branch `feat/know-place-analysis`. Do not run the existing source-AOI workflow as a substitute and do not merge these files to `main`. Read the [living branch context](know-place/CONTEXT.md) before resuming work in a new chat, and update it whenever material evidence or status changes.

## Current phase

The strict raw-HDF5 reader, author-exact acquisition runner, source-byte hash/grid checks, generic AOI/date measurement workflow, workflow dispatcher, and six-site benchmark registry are now implemented on `feat/know-place-analysis`. Live NASA CMR metadata resolves all five exact author P05023 identities and HDF5 access routes. However, this follow-up has **not** downloaded the five raw author HDF5 payloads, so source SHA-256 pins remain 0/5; author-method parity and paper reproduction remain blocked. The output is an exploratory displacement measurement—not a validated landslide detector or operational early-warning model.

## Run via GitHub Actions (current entry point)

**Source-selection safety:** Use the dispatcher’s `author-exact-p05023` profile for the paper-matched five-product run. The push-only `.github/workflows/know-place-analysis-run.yml` is a historical mixed-release replay; its frozen first pair is `X05026`, not the author’s `P05023`. It now requires the separate extra marker `[run-mixed-release-replay]` as well as `[run-know-place]`. Do not use that historical workflow for author-exact results.

Where a manual `workflow_dispatch` call is unavailable, the feature-only `.github/workflows/know-place-author-exact-consent-bridge.yml` calls the reusable author-exact workflow only when `docs/know-place/AUTHOR_EXACT_P05023_RUN_20261026.md` is changed and the commit message includes `[run-know-place]`. The child workflow receives the exact consent input, downloads only the five `P05023` sources, and retains derived outputs through the existing private Drive verification flow. This is a fallback trigger, not a relaxation of the source-identity gate.

The branch-specific copy of `.github/workflows/sarguardian-aoi-wkt-dispatcher.yml` shares a workflow path already present on the default branch. From **Actions**, select **SARGuardian AOI WKT E2E (safe branch dispatcher)**, choose branch `feat/know-place-analysis` in the **Run workflow** branch selector, then choose one profile:

- `author-exact-p05023`: exact five author pairs. Put `[run-know-place]` in the consent input. Defaults: geometry height 5151 m (exploratory constant; not a DEM/datum correction), 1000 control draws, seed 260826. Earthdata and Drive secrets must be configured.
- `generic-aoi-date`: enter the WGS84 AOI polygon and inclusive dates. With `execute_downloads=false`, it produces a catalog/series plan without downloading raw GOFF. Set true only when you intend to download; the same exact consent marker and required secrets are enforced.

The dispatcher and child workflows both check consent before raw-source acquisition. The generic path is exploratory measurement, not a calibrated movement/hazard detector. The existing `main` dispatcher has not been edited.

**Latest isolated validation:** [run 40102852943](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40102852943), branch commit `b1768ba0ab6d8b19e0803e88a19f9d494339b867): 213 tests passed, eight workflow YAML files parsed, and actionlint v1.7.12 checksum/semantic validation passed. This validation did not download GOFF payloads.

## Five-pair product candidates observed in Dynamic AOI Run 39942529304

The table below records the **historical raw replay inputs** from Dynamic AOI Run 39942529304, not the author-exact five-product manifest. Supplementary Table 1 specifies P05023 for every pair; the first historic input is X05026. Keep that source/hash as historical evidence and do not silently substitute or relabel it as the author input. Exact five author IDs and published scalar results are transcribed in [`docs/know-place/reference/author_benchmark_v1.json`](know-place/reference/author_benchmark_v1.json).

| Reference → secondary | Granule identifier without `.h5` | Previous run ID |
|---|---|---|
| 2026-06-20 → 2026-07-02 | `NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_X05026_N_F_J_001` | GOFF-003 |
| 2026-07-02 → 2026-07-14 | `NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001` | GOFF-007 |
| 2026-07-14 → 2026-07-26 | `NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001` | GOFF-011 |
| 2026-07-26 → 2026-08-19 | `NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001` | GOFF-015 |
| 2026-08-19 → 2026-08-31 | `NISAR_L2_PR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_N_F_J_001` | GOFF-019 |

The author series uses ascending T098, L-SAR HH, PR GOFF layer2 products. The archived Table S1 manifest and latest collection-scoped CMR evidence confirm all five exact P05023 identities and data URLs. The archive does not contain their raw HDF5 bytes, and this session has not downloaded them or pinned any source SHA-256 hashes. Do not relabel historical X05026 as P05023; keep paper-reproduction status blocked until exact bytes and method parity are verified.

## Reference box and crown

Reference box (the user's GEE polygon):

```text
POLYGON ((85.500000 28.265000, 85.565000 28.265000, 85.565000 28.318000, 85.500000 28.318000, 85.500000 28.265000))
```

The paper and Supplementary Fig. 2 specify these crown bounds, area 2.07 km²; the same rectangular bounds are used in the current WKT. The previous “296 versus 298” claim was an invalid cross-estimand comparison: 296 is the displacement-valid series count (`n`), while 298 is the polygon-null R-valid count (`n_px`). Across all five exported fields, displacement counts `[283, 294, 296, 292, 195]` match `tables/nisar_pot_series.json` key `n`; the separately recomputed R-valid counts `[302, 299, 302, 298, 202]` match `tables/polygon_null.json` key `n_px`. Pixelwise source-grid mask parity is still unverified; see the [living context](know-place/CONTEXT.md) and archive audit:

```text
POLYGON ((85.5245 28.2847, 85.5400 28.2847, 85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))
```

Do not label the rectangle `author-supplement-geometry`. The report must keep `paper_reproduction_status` blocked until exact polygon/source provenance and author reference values are independently verified.

## Input manifest

Store the raw HDF5 files locally in a private/untracked folder. Do not commit raw NISAR products, Earthdata credentials, Drive tokens or secrets. Create `know-place-inputs.json` beside that folder and use a relative or absolute path to each verified local file:

```json
{
  "schema_version": "know-place-analysis-inputs/1.0",
  "reference_box_wkt": "POLYGON ((85.500000 28.265000, 85.565000 28.265000, 85.565000 28.318000, 85.500000 28.318000, 85.500000 28.265000))",
  "crown_wkt": "POLYGON ((85.5245 28.2847, 85.5400 28.2847, 85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))",
  "crown_geometry_kind": "bounding-box-approximation",
  "crown_geometry_source": "Published crown bounds, manually encoded; not the exact author polygon",
  "geometry_height_m": 5151.0,
  "control_seed": 260826,
  "control_draws": 1000,
  "coherence_minimum_valid_cells": 1,
  "coherence_neighbour_policy": "primary minimum 1 because the preprint does not specify a minimum valid neighbour count; outputs include 1/5/10/15/20/25 sensitivity",
  "products": [
    {
      "path": "raw/<exact-local-file-1>.h5",
      "expected_granule_name": "<exact-local-file-1>.h5",
      "catalog_maturity": "PROVISIONAL",
      "catalog_maturity_evidence": "<ASF dataMaturity filter + collection response and query timestamp>"
    },
    {
      "path": "raw/<exact-local-file-2>.h5",
      "expected_granule_name": "<exact-local-file-2>.h5",
      "catalog_maturity": "PROVISIONAL",
      "catalog_maturity_evidence": "<ASF evidence>"
    },
    {
      "path": "raw/<exact-local-file-3>.h5",
      "expected_granule_name": "<exact-local-file-3>.h5",
      "catalog_maturity": "PROVISIONAL",
      "catalog_maturity_evidence": "<ASF evidence>"
    },
    {
      "path": "raw/<exact-local-file-4>.h5",
      "expected_granule_name": "<exact-local-file-4>.h5",
      "catalog_maturity": "PROVISIONAL",
      "catalog_maturity_evidence": "<ASF evidence>"
    },
    {
      "path": "raw/<exact-local-file-5>.h5",
      "expected_granule_name": "<exact-local-file-5>.h5",
      "catalog_maturity": "PROVISIONAL",
      "catalog_maturity_evidence": "<ASF evidence>"
    }
  ]
}
```

Replace every placeholder before running. The script must stop on filename, pair-date, track, direction, polarization, layer, CRS, grid, metadata, source-file identity or quality-schema mismatches. Catalog maturity statements above are examples only.

## Run locally

From the checked-out feature branch, install the analysis dependencies already used by the isolated CI:

```bash
python -m pip install -r requirements-dev.txt numpy h5py scipy pyproj
python -m py_compile tools/know_place/*.py
python -m pytest -q --confcutdir=tools/tests tools/tests/test_know_place_*.py
python -m tools.know_place.analyze --config path/to/know-place-inputs.json --out path/to/know-place-output
```

The runner first inspects only the five files' grid axes and metadata, checks they have matching 80 m EPSG:32645 grids, and then opens one raw HDF5 at a time to read the box window. It records a SHA-256 of each full source file. The raw offset reader does not consume the existing reader's auto-referenced or deramped rasters.

## Output interpretation

- `KNOW_PLACE_ANALYSIS_STATUS=SCIENTIFIC_METRICS_COMPUTED` means all five pairs produced the explicitly labelled exploratory metrics. It does **not** mean paper reproduction.
- `STRUCTURAL_STATUS=PASS` covers input identity/schema, outputs and provenance gates. An individual pair can still have insufficient pixels or reference support.
- `PAPER_REPRODUCTION_STATUS=BLOCKED_...` is expected with the current crown rectangle and without author golden output parity.
- `HAZARD_DETECTION_STATUS=NOT_EVALUATED` is intentional. No hazard alarm is produced.
- Circular size-matched controls are currently an explicitly exploratory procedure. Do not quote them as the author's exact null distribution until the author algorithm has been recovered and parity tested.
- A displacement magnitude close to 0.96 m alone is not scientific reproduction. The crown metric, background correction, quality gates, direction/coherence, per-product identity and comparison statistics must all be comparable.


## Completed first raw replay and R-policy reanalysis (2026-10-24)

- Raw-input analysis: [Run 40006999011](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40006999011). All five candidate GOFF HDF5 file sizes and SHA-256 values matched the historically inspected source objects; all five intervals produced metrics.
- Saved-array coherence reanalysis: [Run 40015023621](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015023621). This downloaded only the previous derived-only run artifact; no raw HDF5 was downloaded. All five NPZ diagnostic-array checksums matched the source report. The reanalysis report and summary passed Drive remote verification.
- Scientific comparison: for 26 July–19 August, crown median horizontal magnitude was 0.966 m, mean-vector magnitude 1.722 m, azimuth 277.79°. On the pointwise 0.17–2.75 m window, R was 0.869 for 150 crown centres; the preprint reports about 0.869 for 147 centres. Background R/count and control statistics remain different.
- The original min-25-valid-neighbours condition is no longer the primary R rule: the preprint does not specify it. The primary result uses at least one valid vector and emits sensitivity for min valid counts 1/5/10/15/20/25.
- The current circular-control result (median ~0.128 m; ~96.08th percentile) is **not comparable** with the paper's ~0.14 m / 94.7th percentile because exact crown geometry, source variants and author control sampling are not verified. It must not trigger an alarm.
- Current gate is `PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. The Zenodo archive payload is integrity-verified; see `know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md`. Evidence table, raw/source hashes, R-policy comparison and acceptance gaps: [RAW_REPLAY_40006999011_R_POLICY_AUDIT.md](know-place/evidence/RAW_REPLAY_40006999011_R_POLICY_AUDIT.md).
- Validation: [Run 40015371603](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40015371603) passed 46 tests, parsed all three isolated workflows and passed actionlint. All files remain on `feat/know-place-analysis`; `main` was not changed.


## Author footprint-wide candidate screen — separate from the crown site-series

The candidate-screen array kernel is `tools/know_place/footprint_screen.py`; the separate array-only geometry builder is `tools/know_place/footprint_geometry.py`. The screen follows the archived wide-screen thresholds: 41×41 local magnitude anomaly; 5×5 residual directional coherence; z >= 4, anomaly >= 0.50 m, residual R >= 0.75; hits in at least two of five fixed pairs; and four-connected components of at least 10 pixels. The geometry builder interpolates supplied `(height,y,x)` cubes and a supplied DEM array into per-pixel coefficients; it reports extrapolation, fill/clipping and nonfinite values. Both modules are kernel-level components, not a raw-data workflow: neither loads/verifies actual HDF5/DEM source bytes, and the builder does not independently certify CRS/datum labels or generate the 4230 × 4311 coefficient maps from the original files. It does require matching horizontal CRS/affine and explicit vertical references. See [screen audit](know-place/evidence/AUTHOR_FOOTPRINT_SCREEN_KERNEL_AUDIT_20261024.md) and [geometry/vertical-datum audit](know-place/evidence/AUTHOR_FOOTPRINT_GEOMETRY_BUILDER_AUDIT_20261024.md). The output remains a candidate movement screen with `hazard_detection_status=NOT_EVALUATED`, never a calibrated alarm.

The validation workflow compiles both modules and explicitly runs both test files. [Run 40050020868](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020868) passed **176 tests**, all four workflow YAML parses and actionlint. The paired raw-replay run [40050020872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020872) skipped the expensive replay because `[run-know-place]` was not supplied. The first author-exact P05023 product remains unresolved; do not substitute the historical X05026 variant.

## Geometry height-datum caveat — must be resolved before full-screen reproduction

The supplied author archive's `prep_terrain.py` reprojects standard Copernicus GLO-90 terrain horizontally to the screen grid; the archive's `geometry.py` feeds those elevations directly into a `heightAboveEllipsoid` interpolator with no visible vertical transformation. Standard Copernicus GLO-90 vertical reference is EGM2008, whereas NISAR's radarGrid height axis is ellipsoidal. Original terrain source-tile bytes/metadata are absent, so upstream vertical conversion cannot be ruled out. Do not claim datum-corrected geometry and do not quietly add a conversion to the author-reproduction path. The new builder rejects different declared vertical-reference strings unless the explicit, labeled source-reproduction override is selected; that override preserves source behavior without correcting the datum. Any correction experiment needs its own manifest, geoid model, software/sign convention and impact assessment.
## Generic polygon + date-range engine and dashboard

A separate arbitrary-AOI path now lives in `tools/know_place/aoi_request.py`, `series.py`, `aoi_runner.py`, `dashboard.py`, and `uncertainty.py`. It is a different interface from the five-pair paper-reproduction command above.

### GitHub Actions UI

Open the repository's **Actions** tab on `feat/know-place-analysis` and choose **Know Place AOI analysis — polygon/date-range**:

[Workflow file](../.github/workflows/know-place-aoi-analysis.yml)

1. Enter one closed WGS84 polygon WKT, inclusive UTC start/end dates, polarization, and optional track/direction. The workflow also accepts optional comma-separated exact release IDs (for example, `P05023`). Blank leaves releases open, but if the catalogue contains multiple variants for the same interval the planner fails closed; it never silently chooses another release. You may supply an external reference/background polygon. If omitted, the runner uses component-wise median correction from a 2 km local context outside the AOI; explicitly setting `reference.policy=none` disables correction. The local-context approach assumes most background pixels are stable and must be inspected.
2. Leave `execute_downloads=false` first. The dry run queries ASF and writes the exact candidate inventory and separate pair/processing chains, but downloads no raw product.
3. Inspect `catalog-manifest.json`, `series-plan.json` and the request hash in the run artifact. The plan deliberately separates tracks, direction, polarization, product maturity and CRID/release. Same-pair release ambiguity fails closed unless the request explicitly allowlists a release or pins exact granule names; excluded variants remain recorded in the catalogue manifest.
4. Set `execute_downloads=true` only after reviewing the dry-run selection and confirming Earthdata and Drive secrets are configured. The workflow downloads one selected pair at a time, checks bytes/SHA-256/receipt, calculates metrics, writes GeoTIFF/NPZ/CSV, produces `visuals/dashboard.html`, and uploads a derived-only ZIP to central Google Drive. The upload receipt records the local and downloaded-remote SHA-256 checksums.
5. Raw HDF5 files and their receipts are deleted from the workflow's ephemeral cache immediately after each pair finishes; the result manifest keeps source filename, size and SHA-256. This avoids filling the GitHub runner disk, but it means a later run reacquires raw source unless a separately configured persistent verified cache is used.

The runner caps a single download job at 30 selected products. A larger window is not silently truncated: split it into explicit date windows and preserve the resulting run manifests, keeping overlapping pair intervals separate. This is an initial bounded execution limit, not a NISAR mission limit.

### Local use

Install the dedicated runtime rather than relying on the legacy five-pair environment:

```bash
python -m pip install -r tools/know_place/requirements.txt
python -m py_compile tools/know_place/*.py
python -m pytest -q --confcutdir=tools/tests tools/tests/test_know_place_*.py
python -m tools.know_place.aoi_runner --request tools/know_place/examples/bhote_koshi_candidate_request.json --out ./know-place-results --dry-run
```

For a credentialed download/measurement run, omit `--dry-run` and set `EARTHDATA_TOKEN` or `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD`. Use a private `--cache-dir`. Add `--ephemeral-source-cache` when raw HDF5 should be deleted after processing rather than retained for future local reuse.

### Motion-dynamics features

Each measured pair's exact source acquisition start/end timestamps are reduced to reference/secondary acquisition midpoints. The pair's median horizontal displacement magnitude and mean horizontal vector are divided by the midpoint separation, producing separate **interval-average rates** in m/day. These are not instantaneous velocity and do not localize motion onset inside the interval.

The result also records `motion_dynamics` features. Changes in mean-vector rate and the corresponding descriptive rate-change magnitude (m/day) and acceleration-like feature (m/day²) are calculated only if both pairs have actual metrics, are in the same release/maturity chain, the pair intervals are contiguous, projected grid lattices match, and neither interval crosses a registered mission gap. Otherwise the rate-change field is null with an explicit block reason. No risk score or operational alarm is emitted.

`motion_dynamics.status` distinguishes complete, partial, and insufficient feature coverage. `risk_score` remains null and `hazard_detection_status=NOT_EVALUATED` until a separate model is trained/calibrated and tested on independently labelled event/non-event sites. Rate changes are candidate research features, not evidence of an impending collapse.

### Dashboard outputs and scientific status

- `visuals/dashboard.html`: offline HTML, no CDN; contains displacement trend, interval-average rates, gap-aware motion-dynamics table, AOI outline over a downsampled raster preview, source IDs/SHA-256, valid AOI pixel support, uncertainty interval and status gates. It is not a basemap or a substitute for full-resolution GIS rasters.
- `visuals/interactive-map.html`: internet-enabled Leaflet/OpenStreetMap presentation with the WGS84 AOI boundary, selectable acquisition-pair magnitude preview, opacity control, zoom-to-AOI, quality-support metadata and a link to the native-grid GeoTIFF. The preview is an approximate geographic warp of the projected grid, so use the GeoTIFF for scientific analysis. The offline `dashboard.html` remains available if the basemap/CDN is inaccessible.
- `maps/*_displacement.tif`: native-grid east/north/magnitude/coherence/valid-mask/high-magnitude-review flag/uncorrected-magnitude bands.
- `diagnostics/*_arrays.npz`: derived arrays and AOI/reference masks for numerical reanalysis.
- `timeseries.csv`: pairwise displacement metrics and interval-average magnitude rate. `motion-features.csv`: same-chain rates, gap/grid comparability, rate-change features, blocked reasons and the explicit uncalibrated risk-score status. `result.json` and `manifest.json` record request hash, runtime package versions, source checksums and derived-file checksums.
- `paper_reproduction_status=NOT_EVALUATED_GENERIC_AOI` and `hazard_detection_status=NOT_EVALUATED` are expected. The generic runner measures movement and does not issue alarms.
- Generic mode preserves and flags displacement above the configurable review threshold by default because rapid failures can be real high-magnitude motion. The Bhote Koshi paper-method example explicitly chooses `reject_above_threshold`; that method-specific setting must never be adopted as a universal “real movement” rule.
- Constant HAE is still an approximation, not DEM-derived per-pixel terrain height. Operational monitoring remains blocked until terrain-dependent geometry and independent validation are implemented and tested.

For event-level thresholds and a separate multi-event holdout strategy see [MULTI_EVENT_VALIDATION_PLAN.md](know-place/validation/MULTI_EVENT_VALIDATION_PLAN.md). Current author-supplement and method-parity blockers are documented in [AUTHOR_SUPPLEMENT_RETRIEVAL_AUDIT_20261024.md](know-place/evidence/AUTHOR_SUPPLEMENT_RETRIEVAL_AUDIT_20261024.md) and the later [Zenodo archive/method audit](know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md).


## Latest author-exact result and dashboard path — 25 October 2026

### Current evidence (not a complete-paper claim)

Source run: [SARGuardian AOI WKT E2E, Run #17](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), backend revision `417cc2f0156bb310f933b72edb9ecd359812f623`.

Five exact author P05023 GOFF pairs were downloaded, hash-verified and grid-validated; selected site-series archive comparisons passed 65/65, P2/local-mean comparisons passed 15/15, and the full-footprint comparison matched 3/3 aggregate rasters, 106 candidate rows and 101 validated Table S7 rows. Derived-only Drive retention and post-delete cleanup receipts passed.

The scientific claim remains `PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`. Hazard detection is `NOT_EVALUATED`. The generic AOI/date engine was skipped by this author-exact run.

### Render the current result without re-downloading raw NISAR data

The safe-render child workflow is on the feature branch, but a workflow that exists only on a non-default branch may not expose its own **Run workflow** UI entry. To make this usable without editing `main`, call it through the shared dispatcher path that already exists on the default branch:

1. Open [SARGuardian AOI WKT E2E (safe branch dispatcher)](https://github.com/moshiour0/SARGuardian-backend/actions/workflows/sarguardian-aoi-wkt-dispatcher.yml).
2. Select branch `feat/know-place-analysis`.
3. Set `run_profile=render-author-dashboard`. This profile does **not** require `[run-know-place]` and does not query Earthdata or download raw NISAR payloads.
4. Set `source_run_id=40170290176` and `source_attempt=1`.
5. The dispatcher calls `.github/workflows/know-place-author-dashboard.yml` as a reusable workflow. It verifies the source artifact digest and nested ZIP integrity, rejects HDF5 members, renders `dashboard.html`, creates a render manifest, uploads the dashboard/manifest to private Google Drive, verifies the Drive receipt and receipt copy, and emits a short-lived Actions artifact.

Validation run [#409](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40174655179) passed 255 tests, all nine workflow YAML parses and pinned actionlint, including the dashboard renderer and the shared dispatcher route. The dashboard profile has **not yet been manually dispatched**; its Drive receipt and final artifact therefore remain pending.

### Dashboard interpretation and unresolved work

Use the author-compatible raw site-series CSV for the main 26 July–19 August value (median displacement about 0.965 m over a 24-day interval; interval-average rate about 4.02 cm/day). Do not substitute the exploratory report's different R estimate or mean statistics for P1/P2. P1 and P2 are distinct estimators; the polygon-null percentile is not the paper's size-matched displacement-null test.

The dashboard keeps publisher-linked optical images separate from NISAR-derived scientific maps. The crown boundary in previews is still a rectangular approximation, not a verified editable source polygon. The source-method terrain path does not apply a vertical datum correction. Full-paper reproduction is partial until displacement-null and geometry/method parity are resolved. Hazard-detection metrics require a separate held-out multi-event/non-event validation design.

Main remains untouched at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.


### External-image correction note — 25 October 2026

The dashboard's Geopera image card uses the corrected stereo-elevation-change image from the 1 September follow-up: https://geopera.com/blog/bhote-koshi-stereo-elevation-model . Geopera explicitly retracted the original 28 August parallax sediment map after finding its stereo viewing-geometry assumption was wrong. The card must remain labelled as external WorldView-3 context only; it is not NISAR displacement output and must not be used as event-prediction evidence. The pre-event optical thumbnail also remains contextual and is not georegistered to the crown mask.

### Standalone Run #17 dashboard package and corrected imagery — 25 October 2026

A local dashboard artifact has been checked against the retained result bundle from [Run #17](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176). The downloaded source artifact ID is `12589719900`; SHA-256 matches GitHub's artifact digest at `a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`. The dashboard's five source-product hashes match the source manifest, and the reported selected comparison totals were cross-checked against saved reports: site-series 65/65, P2 15/15, footprint rasters 3/3, candidate inventory 106 rows, Table S7 101 rows.

The standalone HTML and its manifest/package can be downloaded from this chat. The local artifact is suitable for presenting the existing Run #17 result, but it does not establish that the GitHub safe-render workflow itself has uploaded a dashboard to Drive.

The external Geopera image is now the corrected 1 September WorldView-3 stereo-elevation-change image, linked to https://geopera.com/blog/bhote-koshi-stereo-elevation-model . Geopera's follow-up explicitly retracts the original parallax sediment map after finding an incorrect stereo viewing-geometry assumption. Treat the corrected image as contextual external imagery, not as NISAR displacement output.

Latest CI after the renderer-image change: [run 40187665186](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40187665186), **256 passed**, all nine workflow YAMLs parsed, actionlint passed. The safe workflow remains pending manual dispatch via the shared branch dispatcher: `run_profile=render-author-dashboard`, `source_run_id=40170290176`, `source_attempt=1`. This route requires no `[run-know-place]` marker because it downloads no raw NISAR products.

Paper status remains partial until displacement-null and exact geometry/mask parity are resolved; hazard detection remains not evaluated. Main is untouched at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.

## Latest run verified — safe dashboard render E2E (Run #19, 2026-10-25)

The safe retained-artifact path is no longer pending. [Run #19](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766) completed successfully on `feat/know-place-analysis` at `ddab6dfa17b9a8b3d8cda31fbca11e5121c0f7f2`.

- Selected source Run #17, attempt 1; matched exactly one isolated-branch artifact; verified GitHub SHA-256 and both ZIP CRCs; rejected raw HDF5 (0 in outer artifact, 0 in nested derived bundle).
- Renderer generated `dashboard.html` (81,214 bytes) and `dashboard-run-manifest.json`. Dashboard SHA-256: `f41ce20cf797df5b447edce42359f0a395ec26691bea61f9c1db7c073021b34c`.
- Private Drive remote verification passed for the HTML and manifest. The primary receipt was then uploaded and independently verified; `DASHBOARD_DRIVE_RETENTION=PASS`, `RAW_PRODUCT_UPLOADED=false`.
- Published Actions artifact: [know-place-author-dashboard, artifact 12596788838](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189992766/artifacts/12596788838). Run #19’s raw author-exact and generic AOI/date jobs were skipped by design.
- Post-fix isolated validation [Run #417](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40189684104) passed 257 tests, nine workflow YAML checks, pinned actionlint, and live ASF/CMR identity/link checks without downloading source payloads.

### What remains

The next task is not a dashboard rerun. Begin a source-level audit/reproduction of the paper’s size-matched displacement-null draw process. The article describes placing compact regions with the crown’s own valid-pixel count at random valid-ground positions inside the fixed 6 km box, rejecting placements with too few valid pixels, and comparing the crown median displacement against the accepted null draws (857–996 accepted draws per pair). The published 94.7th-percentile result is not independently reproduced by the current Run #17 site/footprint parity checks. The new implementation must preserve the author’s acceptance/rejection rules, mask, random-seed/RNG behavior if recoverable, and draw-level outputs; if any parameter cannot be recovered, label the result an independent sensitivity, not exact reproduction.

After that: (1) acquire/verify the exact author crown geometry and quantify pixel-mask parity, (2) compare the current source-faithful EGM2008/HAE path with explicitly named datum-sensitivity variants, and (3) run preregistered held-out event/non-event site validation before any detection/false-alarm/lead-time claims. Keep paper status partial and hazard detection not evaluated until the relevant gate passes. Main remains untouched at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.

## Displacement-null source audit — 2026-10-25

The Zenodo source archive contains aggregate displacement-null results but not the code that generated them. `tables/displacement_null.json` has five rows only: published null medians 0.17, 0.21, 0.14, 0.14 and 0.09 m; published percentiles 94.9, 87.5, 81.0, 94.7 and 81.3. The archive's `code/canonical.py` loads these values and `code/build_cee_si_tables.py` formats them; neither generates draws. The only null generator script found, `code/polygon_null.py`, samples compact regions for directional coherence R and does not compute median displacement per draw. The current backend's `author_polygon_null_statistics()` is also R-only.

The paper describes compact regions with the crown's own valid-pixel count, placed at random valid-ground positions in the fixed 6 km box, with insufficiently valid placements rejected; it reports 857–996 accepted draws per pair. But the archive does not contain the exact displacement sampler, RNG/seed, complete draw-level diagnostics or per-pair acceptance trail. Therefore the next step is a separately named, deterministic, documented **method-derived independent reconstruction** from the archived displacement fields, with explicit sensitivity tests for the unrecovered sampling choices and direct comparisons against the five published aggregate rows. Do not call it exact author-code parity unless the original implementation/policy is recovered; do not optimize parameters merely to force the published outputs.

The apparent 292/298 count difference is resolved by estimand: 292 is valid displacement count `n` in `nisar_pot_series.json`; 298 is coherence-valid crown count `n_px` in `polygon_null.json` for 26 July–19 August. They are not interchangeable.

Paper status remains partial and hazard detection remains not evaluated until the displacement-null and geometry/mask gates are addressed. No raw replay is needed for this initial archive-level reconstruction; main remains untouched.

## First independent displacement-null reconstruction — 2026-10-25

The new module `tools/know_place/displacement_null.py` reads only the five processed offset-field TIFFs in the supplied Zenodo archive. It records inputs and SHA-256, uses finite east/north vectors, ranks the crown median against up to 1,200 size-matched raster-index disks per pair, records all sampled centres and accepted/rejected outcomes, and makes the seed/PRNG and assumptions part of a versioned JSON report. The first run's complete outputs are summarized in `docs/know-place/evidence/DISPLACEMENT_NULL_RECONSTRUCTION_20261025.md`.

Results are explicitly `INDEPENDENT_METHOD_DERIVED_NOT_AUTHOR_SAMPLER_PARITY`: the supplied Zenodo archive has published aggregate values but not the displacement-null generator or its draw-level samples. Observed medians match the published two-decimal values, while some null percentiles differ (26 July–19 August: 92.2 computed vs 94.7 published). Do not tune seeds or geometry to force the expected answer. The next task is a predeclared sensitivity matrix over unrecovered region/acceptance choices, followed by exact crown-mask parity and a separately named vertical-datum sensitivity. Paper status remains partial; hazard detection remains not evaluated.

### Sensitivity checkpoint — 2026-10-25

The default disk policy was not tuned. A 35-row acceptance/seed sensitivity report is checked in at `docs/know-place/evidence/DISPLACEMENT_NULL_SENSITIVITY_20261025.csv`. With seed 20261025 the target percentile is 93.8, 93.3, 92.2, 91.4, 92.6 for minimum valid fractions 0.4–0.8 respectively; seed changes at 0.6 give 92.2, 92.7, 93.5. This confirms policy sensitivity without achieving the published 94.7 percentile. Next sensitivity must vary region shape under a declared rule, not select a configuration based on result closeness.

### Compact-region geometry sensitivity — completed diagnostic

The module and CLI now accept explicit region-shape policies `disk`, `square`, and `diamond`; default remains disk. All shapes have deterministic, version-visible rules and regression coverage. The shape sensitivity matrix is `docs/know-place/evidence/DISPLACEMENT_NULL_SHAPE_SENSITIVITY_20261025.csv`. For the target pair, percentiles were disk 92.2, square 91.8, and diamond 93.0 (published 94.7). Do not select shape by closeness. Recovering the original generator or per-draw author output is still required for exact parity.


## Current live measurement result — 26 October 2026

The authorized exact-author run is complete: [GitHub Actions #40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596). Read `docs/know-place/evidence/AUTHOR_EXACT_P05023_MEASUREMENT_20261026.md` first for the source hashes, pair-level table, verified Drive-retention receipt, dashboard, and scientific caveats. The user does not need to download the raw HDF5 files again for this existing result.

The critical 2026-07-26 → 2026-08-19 pair produced an exploratory median horizontal displacement of 0.96606 m from 292 valid crown pixels and a median descriptive rate of 4.0253 cm/day. The author-compatible site-series path reports 0.96451 m and 4.01879 cm/day. These are close to the deposited summary, but the exact author editable crown geometry is unavailable; do not call this exact-mask reproduction or a validated warning.

The run matched site-series (65/65), P2 (15/15), full-footprint aggregate rasters (3/3), candidate inventory (106/106), and validated zones (101/101), at published/archive precision. The derived-only null-table reconstruction [run #40233222258](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258) additionally matched all 15 published crown/null median and percentile values, while explicitly retaining `UNVERIFIED_NO_ORIGINAL_DRAW_OR_REJECTION_HISTORY`. The original null sampler is not included in the reviewed author archive, so whole-paper status remains partial.

Private Drive remote verification passed before all five temporary raw HDF5 files were deleted; cleanup and the post-delete receipt were verified. The current Actions artifact includes `dashboard.html`, the raw-site-series CSV, five pair diagnostic arrays, source/cleanup manifests, footprint rasters and reports; raw HDF5 is not present in the derived artifact. Artifact: [ID 12613577460](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596/artifacts/12613577460). The separately generated null audit artifact is [ID 12613704622](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258/artifacts/12613704622).

Current status labels remain `PAPER_REPRODUCTION_STATUS=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`, `HAZARD_DETECTION_STATUS=NOT_EVALUATED`, and `OPERATIONAL_WARNING_STATUS=NOT_IMPLEMENTED`. Exact crown vector/mask, RGI 6.0 overlay and HAE/DEM datum parity are unresolved. No changes were made to main (baseline SHA `2218dfeb73353080d8d94bd733d9e7bd9a848886`).

