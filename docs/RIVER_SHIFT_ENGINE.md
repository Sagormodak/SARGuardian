# River Shift — independent NISAR GCOV engine

River Shift is a separate SARGuardian engine. It is not a mode of Landslide, Find Displacements, or Known Place Analysis.

## Isolation contract

| Engine | UI/API namespace | Processing workflow |
|---|---|---|
| Landslide — Find Displacements | Existing /landslide workspace and /api/displacement-jobs | Existing workflows in moshiour0/SARGuardian-backend |
| Known Place Analysis | Existing Known Place routes and /api/known-place-analysis | Existing Know Place workflows in moshiour0/SARGuardian-backend |
| River Shift | New /river-shift workspace and /api/river-shift/* | New river-shift-gcov-process.yml in moshiour0/SARGuardian-backend |

River Shift uses its own river_shift_jobs table, request fingerprint, callback sequence, HMAC callback and private artifact routes. It does not read or mutate displacement_jobs, and it does not reuse the Known Place request workflow.

## User workflow

1. Open the River Shift engine from Home.
2. Draw or enter one WGS84 AOI polygon on the Google Maps satellite map.
3. Choose the observation window, user-supplied event date, one collection maturity, frequency, diagonal covariance term and a common water threshold method.
4. Search the NASA CMR NISAR GCOV catalogue. This is metadata-only: it downloads no HDF5 and performs no scientific classification.
5. Start processing. The authenticated Dynamic API creates an immutable owner-scoped job and dispatches the River Shift worker in SARGuardian-backend.
6. The dashboard polls that River Shift job, loads its private checksum-bound results and shows actual observed-date frames. It never interpolates daily observations.

## Automated processing scope and scientific limits

The current automated worker supports:

- NISAR L2 GCOV collection discovery for one selected maturity (BETA or PROVISIONAL).
- Acquisition comparability and catalogue footprint screening.
- Exact product download, HDF5 dataset inspection and selected AOI raster extraction.
- Observed-date water time-series screening.
- Flood-period new-water coverage screening.
- Persistent erosion/deposition candidate screening.
- Private Google Drive result retention and checksum-verified artifact delivery.

The API/worker requires at least four distinct catalogue acquisition dates before dispatch. The worker then checks compatible acquisition groups, exact HDF5 availability and per-date AOI footprint coverage. Product footprint coverage is not proof of valid raster coverage; the worker performs further checks after it opens the data. The worker is currently bounded to 12 observed dates and 24 selected granules. These are resource limits, not a claim that every AOI has sufficient NISAR coverage.

**Not yet an automated live-job measurement:** bankline migration. A separate scientific script can measure signed displacement along supplied, user-oriented transects from independently digitised banklines. It is not invoked by the current automatic GCOV job because the workflow does not yet collect or independently verify those banklines/transects. The UI may load compatible research reports, but do not claim automatic bankline migration results from a normal River Shift run.

Every successful worker result is labelled PROVISIONAL; independent validation remains PENDING. A processing PASS means the configured processing and private-storage checks passed. It does not prove flood causality, field-confirmed erosion/deposition, hazard detection or real-world accuracy. The event date is user supplied and is not independently verified by an authoritative gauge feed. A GOFF/GUNW displacement or Landslide alert is not inferred from GCOV.

## Dynamic API and persistence

New API routes:

- POST /api/river-shift/catalog/search — public, read-only CMR metadata search.
- POST /api/river-shift/jobs — Firebase-authenticated job creation.
- GET /api/river-shift/jobs/{job_id} — owner-scoped status and workflow reconciliation.
- POST /api/river-shift/jobs/{job_id}/callback — HMAC-signed worker callback.
- GET /api/river-shift/jobs/{job_id}/artifacts/{artifact_index} — owner-scoped private artifact download, byte-count and SHA-256 verification.

New Supabase migration:

Backend/supabase/migrations/20261103100000_river_shift_jobs.sql

Apply this migration to the same Supabase project used by the Dynamic API before enabling job dispatch. The new code is fail-closed when River Shift Actions are disabled or its required configuration is missing.

## Configuration — Dynamic API

Set these as server-side environment variables on the deployed Dynamic API service. They must not be VITE_* browser variables.

| Variable | Required value |
|---|---|
| RIVERSHIFT_ACTIONS_ENABLED | true only after worker PR is merged, migration is applied and secrets are configured |
| RIVERSHIFT_GITHUB_ACTIONS_TOKEN | GitHub token with Actions workflow-dispatch permission in moshiour0/SARGuardian-backend |
| RIVERSHIFT_GITHUB_ACTIONS_REPOSITORY | moshiour0/SARGuardian-backend |
| RIVERSHIFT_GITHUB_ACTIONS_WORKFLOW | river-shift-gcov-process.yml |
| RIVERSHIFT_GITHUB_ACTIONS_REF | main after the worker PR is merged |
| RIVERSHIFT_CALLBACK_SECRET | High-entropy HMAC secret; must exactly match the backend repository Actions secret |
| RIVERSHIFT_PUBLIC_API_URL | Public HTTPS base URL of the Dynamic API, without a trailing path |

The token can fall back to the existing server-only GITHUB_ACTIONS_TOKEN, and the public API URL can fall back to PUBLIC_API_URL; separate River Shift values are preferred so that worker lifecycle credentials can be rotated independently. The default is RIVERSHIFT_ACTIONS_ENABLED=false.

## Configuration — SARGuardian-backend Actions secrets

Add these secrets in the moshiour0/SARGuardian-backend repository:

- RIVERSHIFT_CALLBACK_SECRET — exact same secret value as the Dynamic API.
- EARTHDATA_TOKEN, or the existing EARTHDATA_USERNAME and EARTHDATA_PASSWORD credentials accepted by the downloader.
- GOOGLE_DRIVE_OAUTH_CLIENT_JSON.
- GOOGLE_DRIVE_REFRESH_TOKEN.
- GOOGLE_DRIVE_PARENT_FOLDER_ID — the sole configured parent folder for RiverShift. The worker automatically finds or creates the fixed `RiverShift` child folder beneath it, then a UUID-named job folder and output hierarchy. Do not configure `GOOGLE_DRIVE_FOLDER_ID` for RiverShift.

Drive result storage remains private. The worker does not publish original raw HDF5 products as downloadable result artifacts. The Dynamic API authorizes the signed-in owner before it reads any Drive artifact.

The API reads each already-retained file by its `drive_file_id`, then verifies the byte count and SHA-256 before streaming it to the authenticated owner. It does not create the `RiverShift` folder or upload job results; those operations belong to the backend GitHub Actions worker.

## Activation order

1. Review and merge the SARGuardian-backend River Shift worker PR.
2. Review and merge the SARGuardian_Dynamic River Shift engine PR.
3. Apply the new river_shift_jobs Supabase migration.
4. Configure the Dynamic API environment and backend Actions secrets above.
5. Deploy the Dynamic frontend/API code when the release window is approved.
6. Run one controlled AOI/date validation and inspect the Action run, callback receipts, Drive checksums and rendered map before opening the feature to general use.

Do not enable RIVERSHIFT_ACTIONS_ENABLED or run a live satellite-data job before steps 1–4 are complete. A deployment is not part of the current feature branch work.
