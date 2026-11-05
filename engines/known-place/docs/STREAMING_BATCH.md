# SARGuardian streaming batch run

This workflow processes the exact Nepal source-AOI manifest committed in
moshiour0/SARGuardian at science commit
ab547ecc82bcc4d6ccef545a59852536c2beacc6. It does not substitute the
Langtang or Lhende polygons.

## Run it safely

1. Live processing is manual by design: open **Actions → SARGuardian Streaming
   Batch (source AOI) → Run workflow**. Ordinary code pushes run regression
   tests only; they do not automatically start large downloads or consume Drive
   storage.
2. Choose the inclusive `start_date` and `end_date` inputs in `YYYY-MM-DD`
   format. The window is applied to each baseline granule's **secondary
   acquisition date** (the third timestamp in the NISAR granule name). The
   default `2025-01-01` through `2026-12-31` covers the currently pinned
   products. The `source` AOI is fixed by the scientific project; there is no
   AOI input and its polygon is not changed.
3. Choose `retention_profile=derived-only` by default to save Drive space. It
   uploads the validated CSV/GeoTIFF products, source inventory, source SHA-256,
   preflight and validation receipts without creating or retaining a
   `*.science.h5` archive. Choose `full-lossless` only when future unrestricted
   HDF5 reprocessing is worth retaining a near-source-size archive. Quota is
   checked against actual files and each remote file's size/MD5 is verified.
   Final ZIP/report/receipts are checked separately; no raw-download-size guess
   is used as the retained-output estimate.
4. Keep `validation-pilot` for the first real run. It picks one GUNW and one
   GOFF within the selected window. Each reader's complete product row is
   compared against the pinned `gunw_stats_source.csv` or
   `goff_stats_source.csv` baseline before deletion, and every required TIFF
   must be present/readable with valid grid, CRS, band layout and source identity.
5. After the pilot passes, choose `full-source-baseline` to process every
   committed baseline product inside the selected window. A window containing
   all **15 GUNW + 18 GOFF = 33** pinned products uses the full-baseline
   downstream comparison. A narrower window is recorded as
   `time-window-selection`: it validates selected product rows and exports but
   intentionally does not claim a full-network time-series/bound equivalence
   comparison. `max-parallel: 1` keeps raw HDF5 processing sequential.
6. Each product's cleanup gate checks the baseline-validation report and remote
   receipt, requires all expected CSV/GeoTIFF outputs to appear in the verified
   Drive receipt, and checks that the archive presence matches the selected
   retention profile. Only then may the temporary raw HDF5 (and, in
   `full-lossless` mode, the temporary local archive) be deleted. The uploaded
   cleanup receipt records the policy and deletion evidence.
7. Open the `sarguardian-streaming-run-*` artifact and inspect
   `batch-equivalence-report.json`. The final Drive bundle is uploaded only
    when the applicable product-level checks (and, for the full baseline, the
   regenerated downstream results and all cleanup receipts) pass. The JSON
   report's `retention_storage_accounting` section totals actual verified
   remote file sizes by product (archive bytes are zero under `derived-only`),
   plus unique remote files and net-new bytes. The final run ZIP/report are uploaded
   afterward and are quota-checked/logged separately, so they are not folded
   into the product-retention total.

**Scope:** the selectable window filters the 33 products in the committed
source-AOI baseline. It does not yet discover additional granules outside those
committed CSVs; the live catalog discovery path has been returning upstream
ASF errors. The AOI remains the original fixed `source` polygon either way.

## Per-product sequence and retention rules

For each granule the workflow does the following:

1. Load the pinned `science-source/src/nisar_acquisition.py` and set its canonical `source` AOI. Because the baseline already supplies the exact granule name and maturity, form the documented NISAR direct HTTPS path `https://nisar.asf.earthdatacloud.nasa.gov/NISAR/{NISAR_L2_TYPE_MATURITY_V1}/{GRANULE}/{GRANULE}.h5`; probe its HTTP status and size, then download through the same authenticated `build_session()` and `asf_search.download_url()` used by the source project. This avoids the ASF catalog endpoint, which returned wrapped CMR HTTP 500/502 errors on live runs. The separate raster AOI preflight still verifies that the downloaded HDF5 grid intersects the original source polygon before science processing or Drive retention.
2. Run the AOI-grid preflight for `source`.
3. Inventory every source dataset/attribute.
4. By default, run in `derived-only`: do not create an HDF5 archive. An
   optional `full-lossless` archive is built only when that retention profile is
   selected.
5. Run the original per-product GUNW/GOFF reader, exporting each baseline
   GeoTIFF and its statistics CSV. Verify the single-reader row against the
   pinned source-ZIP row **before deletion**, then validate export readability,
   grid/CRS/bands, dimensions and valid-pixel consistency. If `full-lossless`
   was selected, also compare raw and archived reads with the science engine.
6. Upload outputs, source inventory/attributes, source SHA-256, AOI preflight,
   validation report and download manifest into the granule-specific Drive
   folder. `full-lossless` adds the archive, archive manifest and reader
   equivalence report. Remote byte-size/MD5 checks and manifest-specific file
   checks must pass.
7. Delete runner-local raw HDF5 only after every required derived output is
   uploaded and verified. Delete the temporary archive as well if one was made.
   Store and verify the cleanup receipt. In `derived-only`, arbitrary future
   raw-dataset queries such as a new product-native LOS geometry analysis are
   not preserved unless a compact equivalent was explicitly exported.

A failed upload or failed verification never reaches the explicit `rm` step.
After the initial product matrix completes, the workflow checks all processed
product and cleanup receipts and retries each incomplete product once through
the same full processing worker. The separate preassembly gate verifies every
selected product—including valid checkpoints reused from a compatible resume
source—before any reassembly starts. If a product is still incomplete after
that retry, the final verification report is preserved and reassembly is
blocked; inspect the per-product diagnostic and retry report rather than
treating a partial set as success. The manifest is deterministic. The Drive
uploader refuses to overwrite a same-name scientific/derived output with
different checksums. On a bounded same-workflow-run retry, only the allowlisted
attempt-dependent sidecar receipts (`product-processing.json`,
`drive-retention-receipt.json`, and `local-cleanup-receipt.json`) may be
replaced in the unique current-run folder; all replacements remain subject to
remote size/MD5 verification.

## What is regenerated in full-source-baseline

- `gunw_stats_source.csv` and `goff_stats_source.csv`: merged in the committed
  baseline row order and compared against every expected row/value.
- AOI-clipped `export_src` and `export_goff_src` GeoTIFFs, collected from each
  product artifact.
- GOFF and GUNW summary time series built from the per-pair AOI GeoTIFFs. The finite-pixel median is recomputed at full raster precision and every PR/UR granule is kept as a graph edge, matching the pinned `--dir` path; the rounded statistics CSV and its PR/UR deduplication helper are deliberately not used for this baseline replay.
- Pre-event inverse-velocity check with the explicit 2026-08-26 event cutoff.
- Both `troposphere_gunw_source.csv` and `troposphere_goff_source.csv`, using
  the committed options (GOFF filtered to `layer2`).
- Candidate GOFF and GUNW local floors, summer common-reference table, and
  `bound_source.csv`.
- Candidate-4 local floors (`local_floor_cand4.csv` and
  `local_floor_cand4_as_floors.csv`) plus its common-datum inverse-velocity gate.
- `ts_goff_cand4_common.csv`: this point-level common-datum time series is
  reassembled from **all 18** fixed-lattice GOFF layer2 GeoTIFF exports (16 PR
  plus 2 UR), with the same `common_mask`, target buffer, `rereference`,
  window median and time-series inversion functions as the pinned science
  engine. Do not drop the UR files merely because their acquisition dates
  duplicate PR products: both the shared reference mask and least-squares
  uncertainty depend on those edges. The workflow fails closed if the expected
  16 PR + 2 UR source stack is incomplete. The raw HDF5 stack is not
  re-downloaded or kept on the aggregation runner.

The report records each table comparison. Float comparisons use a small
explicit tolerance for the float32 AOI-raster representation and rounded CSV
outputs; file identity, row identity, required fields, export sets and
missing/extra rows are checked too. The supplied source ZIP has no
`ts_gunw_source.csv` baseline, so that table is labeled generated/unbaselined
rather than claimed as a parity PASS. GeoTIFFs are not in the ZIP; the workflow
validates raster structure and product statistics, but cannot claim historical
pixel-for-pixel parity against absent TIFF files.
The output bundle is not marked PASS if any required table differs or any
product artifact is missing.

## Complete documented science suite

For a `full-source-baseline` run, aggregation also executes the supplementary
Results 1, 2, 3 and 6 from the exact pinned `SARGuardian/src/` tree:

- Result 1 regenerates the noise-gated and legacy fixed-gate detectability
  sweeps, plus the pinned Blatten phase and offset-tracking comparisons.
- Result 2 runs SRTM-based track sensitivity/stencil tests and the explicit
  north-face aspect hypothesis.
- Result 3 regenerates the terrain impoundment GeoJSON outputs for source,
  Langtang, Lhende and Blatten.
- Result 6 surveys the Sentinel-2 scenes, re-generates the candidate map, and
  probes the reported point. The point must be observed and the pinned script
  must produce its documented `NOT A SCAR` evidence; missing data is not a
  negative detection.

Results 4, 5 and 7 remain built from the raw-product jobs' pinned scientific
readers and their verified source-AOI GeoTIFFs: GOFF/GUNW exports,
time-series/inverse-velocity checks, troposphere, local floors, common
reference and final bounds. The supplementary runner requires the exact
`ab547ecc82bcc4d6ccef545a59852536c2beacc6` commit and a clean `src/` tree,
removes generated targets before executing each command, validates newly
generated CSV/GeoJSON outputs, records exact arguments/logs, and retries
transient errors for network-dependent steps. A remaining required failure
keeps the batch result at FAIL. Terrain GeoJSON hashes are reported for
inspection, not treated as strict parity gates because public elevation
services can change independently.

The final aggregation job does not need original raw HDF5: it consumes the
validated, AOI-clipped GeoTIFFs produced by each product job. Any operation
that must compare raw against a retained lossless HDF5 copy runs while the
raw file still exists, before that product can pass its cleanup gate. If a
future analysis depends on a dataset not represented in the validated derived
outputs, retain `full-lossless` and add the required science/equivalence gate
before enabling source deletion.

## Drive layout

Single-granule assets are isolated per workflow run:

`SARGuardian-DataArchive/{GUNW|GOFF}/{BETA|PROVISIONAL}/NISAR_L2_.../Runs/<run-id>-<attempt>/`

Aggregate run-level output remains separate:

`SARGuardian-DataArchive/Runs/SARGuardian-<run-id>-<attempt>/`

Each folder contains checksummed receipts. Identical content is reused within
the same run folder; a later run gets a new folder rather than overwriting a
previous archive with the same filename. Conflicting scientific/derived
filenames and insufficient Drive quota still fail closed. Only the three
allowlisted attempt-dependent sidecar receipts may be refreshed inside the
same workflow run's unique version folder during its bounded retry. This
intentionally retains older archives; do not delete them merely to make space. Raw .h5 source files are
excluded from uploads; only explicitly named `*.science.h5` retained archives
are accepted by the upload helper.

## Required Actions secrets

The workflow needs the same secrets as the existing retention pilot:

- `EARTHDATA_USERNAME`
- `EARTHDATA_PASSWORD`
- `GOOGLE_DRIVE_OAUTH_CLIENT_JSON`
- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_DRIVE_PARENT_FOLDER_ID`

No credentials should be put into committed files or workflow inputs.


## Resuming a failed full-baseline run

To resume a failed full-baseline run, use the test branch
`feat/e2e-pinned-science-pipeline` and choose `full-source-baseline`, keeping
the same date window and retention mode.

- Leave `resume_from_run_id` blank to search for the newest compatible
  failed/cancelled/timed-out manual run from this workflow on the testing
  branch or `main`.
- Enter a numeric run ID to select a specific run.
- Enter `none` to disable discovery and force a cold run.

Discovery checks the old manifest, the pinned science commit, source AOI,
date window, retention mode and ordered product identities. Only products with
passing derived-output validation, verified Drive retention, required local
checkpoint files, and a remotely verified cleanup receipt are reusable.
Missing/incomplete per-product or cleanup artifacts are treated as unverified,
so those products are processed again. In the aggregation job, current-run and
prior-run product/cleanup artifact-family downloads are optional: this permits
an all-reused resume (which may have an empty processing matrix) to reach the
same evidence and science gates instead of failing just because there are no
new artifacts to download.

Storage accounting uses unique verified Drive file IDs and actual receipt sizes.
Its `net_new_remote_bytes_in_run` excludes products reused from a prior checkpoint;
the receipt's `reused` flag describes the original upload attempt and is not by
itself proof that those bytes were uploaded during this new run.

A green auto-resume CI test does not replace a live resumed full-baseline run;
operational status remains pending until the branch's manual run succeeds
end-to-end.

The aggregation job combines the prior checkpoint artifacts with results from the new attempt. A failed retry's diagnostics-only artifact cannot replace a previously verified product checkpoint. Use this for transient infrastructure failures, not to bypass a scientific parity failure. The final run must still reproduce all required baseline rows, downstream tables and receipt/accounting gates. The retry/resume implementation needs one live resumed run before being treated as operationally proven.


## Why the automatic retry gate exists

The prior live failure evidence shows why a granule must not be labelled
permanently bad just because one run exhausts its retry budget:

- In [Run #31](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39529540908),
  `GOFF-018`, `GOFF-022`, and `GOFF-025` exhausted four download attempts
  after a `ConnectionError` while reaching the Earthdata Login token endpoint
  `urs.earthdata.nasa.gov/oauth/tokens/user`. These errors occurred during
  authentication/probing, before the granule bytes were successfully obtained;
  they are not evidence of a corrupt HDF5 file.
- In the same run, `GOFF-021` completed the download and scientific processing,
  uploaded its derived products, and then failed while uploading metadata due
  to `DRIVE_CHUNK_UPLOAD_HTTP_500`. That is a separate transient Drive upload
  failure, and it can leave some same-run outputs remotely present.
- In [Run #51](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39602014392),
  those four product jobs later completed successfully. This supports retrying
  the product job after the initial sequential matrix and checking the actual
  receipts, rather than assuming the previous failure is a permanent granule
  problem.

The gate therefore tests the resulting product/retention/cleanup evidence,
not merely the initial job's green/red state. It retries only incomplete
products, verifies source SHA-256 before refreshing attempt-dependent Drive
sidecars, does not replace changed scientific outputs, and blocks reassembly
if any product still lacks a valid complete receipt pair.

## Retry failed products before reassembly

The streaming workflow factors the existing per-product processing sequence
into a reusable worker. The initial matrix still honors the selected
`resume_from_run_id` behavior: `none` forces a fresh run, blank selects the
automatic compatible-resume path, and a numeric ID selects a manual resume
source.

After the initial matrix is complete, `retry-plan` validates each product's
`product-processing.json`, derived-output validation and remote-retention
receipt, required export inventory, and both post-cleanup receipts. Only
products with a missing or invalid granule/cleanup receipt pair are added to
the retry-only matrix. The original downloader retains its four-attempt
bounded retry for transient download failures; if the whole product job still
fails or its output receipt is incomplete, that product gets one additional
full-worker attempt. A retry reuses the same run-scoped Drive folder: matching
scientific outputs are reused and counted once as retained by this run, while
a changed same-name science output remains a hard conflict. Because receipt
timestamps and same-run reuse evidence can differ between attempts, only the
three allowlisted metadata/cleanup receipts may be replaced on retry; the
replacement is recorded and final receipts still verify remote file IDs, sizes
and MD5 checksums.

The `preassembly-verify` job then checks every product in the complete manifest,
not only the products processed in the latest matrix. In full-baseline mode it
requires exactly 33 ordered product identities (15 GUNW and 18 GOFF). It
accepts a product only when its granule and cleanup receipts form one complete,
compatible pair from either this run or the selected compatible resume source.
Reassembly is gated on this job passing. If any product remains missing or
invalid after retry, the workflow fails closed, retains
`sarguardian-preassembly-retry-plan` and
`sarguardian-preassembly-verification` reports when available, and skips the
aggregate/reassembly job. The science commit, pinned source scripts and
scientific comparison tolerances are not changed by this retry orchestration.

A manual full-baseline run on the updated testing branch is still required to
verify this exact retry-before-reassembly path against all live 33 products;
regression CI alone does not count as live end-to-end proof.

## Optional Earthdata user-token authentication

The downloader supports the optional `EARTHDATA_TOKEN` repository Actions secret. The streaming-batch, live-validation, and retention-pilot workflows now pass that secret through to the downloader. When set, it builds an ASF session with `ASFSession.auth_with_token()` instead of requesting a new login token for each session through `urs.earthdata.nasa.gov/api/users/find_or_create_token`. If ASF rejects the user token with HTTP 401/403, the downloader retries once using the existing `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` credentials, if present. If the token endpoint/network itself is temporarily unreachable, a valid pre-generated user token avoids that particular dependency; it cannot prevent an unrelated outage on the ASF data host.

To enable it:

1. Sign in to [Earthdata Login](https://urs.earthdata.nasa.gov/), open your profile's **User Tokens / Generate Token** page, and create a user token.
2. In this GitHub repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Set the secret name to `EARTHDATA_TOKEN` and paste the token only into its secret value. Do not commit it, put it in workflow inputs, or paste it into logs/issues/chat.
4. Leave `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` configured as a fallback. The workflow never prints the token value.

Earthdata Login's current user-token documentation says tokens are valid for 60 days and a user may have at most two valid tokens at a time. Rotate/update the secret before it expires. See the [official token documentation](https://urs.earthdata.nasa.gov/documentation/for_users/user_token) and the [ASFSession token-authentication reference](https://docs.asf.alaska.edu/asf_search/ASFSession/).

The direct HDF5 transfer is also streamed using the authenticated ASF session with a 30-second connect timeout and 120-second read-idle timeout. Progress is logged every 128 MiB. A content-length mismatch or transient network interruption marks the attempt retryable; the incomplete staging file is removed before the workflow retries it. The full download step also has a 90-minute cap.

The current resumed run #39520455676 was started before this token support was committed, so it does not have the new token-authentication code. Do not assume it is using the new secret; its active downloader step uses the older code from the run's pinned commit. A subsequent workflow attempt from the updated branch will use the optional token.


## Bounded retry and recovery policy (2026-10-21)

The product downloader has a four-attempt workflow-level retry for failures it
classifies as transient, plus bounded retries for Earthdata authentication,
direct-product probes, and exact ASF catalogue fallback. Configure the optional
repository Actions secret `EARTHDATA_TOKEN` from a valid pre-generated
Earthdata user token to avoid exchanging username/password for a new token on
every fresh runner. Keep `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` as the
fallback credentials. An unset token secret preserves the existing credential
exchange path; it does not itself solve a network outage at the Earthdata Login
host.

The Google Drive uploader now retries transient token-refresh and safe API
requests (network failures and HTTP 408/425/429/500/502/503/504), uses bounded
exponential backoff and honours a numeric `Retry-After`. Folder creation
re-queries the exact folder after an ambiguous transient failure before trying
another create request. If a resumable chunk upload fails with a network error
or retryable server status, the uploader queries the upload session for the
server-acknowledged byte range and continues from that offset; it does not
blindly restart a partially accepted chunk. Final file size and MD5 checks
remain mandatory. Package installation uses explicit pip retry and timeout
settings.

Retries are deliberately bounded and limited to transient infrastructure
failures. A reproducible science exception, AOI mismatch, invalid HDF5 schema,
missing export, baseline mismatch, quota exhaustion, or checksum mismatch is
not blindly retried as if it were a network outage. Those stages fail closed;
the per-product checkpoint/resume workflow reuses only complete, remotely
verified products and reprocesses incomplete ones. If only downstream
aggregation/parity failed after product artifacts were retained, use the
artifact-only reassembly workflow rather than downloading raw HDF5 again.

## Candidate-4 replay correction

Historical run #39520455676 was started before the token support was
committed, so its downloader used the older username/password token-exchange
path. The newer live run #39524783921 verified that GOFF-033 downloads and
processes successfully using the updated branch. Its aggregation exposed a
separate candidate-4 replay bug: the common-reference series selected only 16
PR layer2 rasters even though the committed baseline includes 16 PR plus 2 UR
rasters. The fix now preserves all 18 inputs and adds a regression test to
prevent accidental UR-edge omission. The official artifact-only replay is complete and passed; see the dated result section below. This proves the retained-checkpoint aggregation path, not an independent end-to-end `resume_from_run_id` live rerun.


## Reassemble existing successful artifacts without another HDF5 download

When a product transfer and reader validation succeed but a downstream comparison fails, use
**Actions → SARGuardian Reassemble Existing Product Artifacts → Run workflow** on
`work/raw-hdf5-derived-only-parity`. This manual-only workflow takes two run IDs:
- `checkpoint_run_id=39510497044`: the original run containing the 32 complete product checkpoints.
- `product_run_id=39524783921`: the newer run containing the successful GOFF-033 product and cleanup evidence.

These defaults reflect the currently verified runs; choose the IDs matching the evidence you want to combine. The workflow validates both manifests (AOI, source revision, date window, retention profile and exact ordered granule identities), merges the prior complete checkpoints with the newer successful product, then runs the same complete product, retention, cleanup and downstream parity gates. It does not call Earthdata or re-download source HDF5. It publishes a replay artifact even on comparison failure and uploads the final bundle/report to the run-scoped Google Drive folder only if every required gate passes.

The baseline run's per-product artifacts expire after the configured retention period, so perform this replay while the source artifacts remain available. If the merged replay still fails, inspect `batch-equivalence-report.json`; only change the relevant downstream reconstruction where the report's row-key and field-mismatch evidence identifies a real discrepancy. Never relax a required baseline comparison just to force an overall PASS.

## Official full-baseline artifact replay result (2026-10-21)

The artifact-only reassembly workflow completed successfully in [run #39527193872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39527193872), using checkpoints from run #39510497044 and the successfully processed replacement product from run #39524783921. The replay checked out backend aggregation commit `d9e67df7d800032c37d23f74df44c98e3ab655f7` and the pinned science source commit `ab547ecc82bcc4d6ccef545a59852536c2beacc6`.

- `BATCH_EQUIVALENCE_STATUS=PASS`; 33/33 products validated; aggregation report has no errors.
- All 12 committed downstream table comparisons passed with 0 missing keys, 0 extra keys and 0 field mismatches. This includes `outputs/ts_goff_cand4_common.csv` (20 rows), fixing the previous 26 field mismatches by using all 18 GOFF layer2 inputs (16 PR + 2 UR).
- Cleanup evidence and actual product-retention accounting passed for 33/33 products. The report accounts for 297 unique remote files totaling 10,411,698 bytes (0.009697 GiB) for per-product retained outputs. This figure excludes the run-level bundle/report; the uploaded replay bundle, report and receipt total 2,469,359 bytes. No raw HDF5 was uploaded or re-downloaded during replay.
- The report explicitly marks `ts_gunw_source.csv` as `GENERATED_NO_COMMITTED_BASELINE`; it is not counted among the 12 baseline comparisons. Because the source ZIP contains no historical TIFFs, this result does not claim pixel-by-pixel parity with original raster files. Trend logs also retain their `UNTESTED` / `NOT ROBUST` cautions; table parity does not independently validate geophysical interpretations.

The artifact-only replay is now operationally proven for these retained artifacts. The separate full live `resume_from_run_id` path has not yet had an independent end-to-end run, so do not claim that exact recovery mode is fully proven until it is exercised.
