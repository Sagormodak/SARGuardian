# RiverShift GCOV worker setup

This repository contains the RiverShift scientific worker only. The authenticated RiverShift UI, Firebase identity verification, job persistence, job status API and owner-authorized private artifact download live in the separate repository moshiour0/SARGuardian_Dynamic.

The worker is launched by the Dynamic API through this repository's workflow:

- Workflow: .github/workflows/river-shift-gcov-process.yml
- Processing entry point: tools/river_shift/process_gcov_job.py
- Runtime: tools/river_shift/environment.yml
- Callback route in Dynamic: POST /api/river-shift/jobs/{job_id}/callback

## Repository secrets

Configure these GitHub Actions secrets in moshiour0/SARGuardian-backend:

| Secret | Purpose |
|---|---|
| RIVERSHIFT_CALLBACK_SECRET | HMAC secret used to authenticate worker callbacks; must match the Dynamic API environment exactly |
| EARTHDATA_TOKEN | Earthdata bearer token for exact NISAR GCOV product downloads |
| EARTHDATA_USERNAME and EARTHDATA_PASSWORD | Alternative Earthdata Login credential pair supported by the download helper |
| GOOGLE_DRIVE_OAUTH_CLIENT_JSON | Server-side Google OAuth client JSON used for private result storage |
| GOOGLE_DRIVE_REFRESH_TOKEN | Refresh token for the configured private Drive identity |
| GOOGLE_DRIVE_PARENT_FOLDER_ID | Existing parent folder for private RiverShift storage; the worker creates its fixed child folder automatically |

Only GOOGLE_DRIVE_PARENT_FOLDER_ID is used for Drive folder configuration. Under that parent, the worker creates or reuses one fixed `RiverShift` folder, then creates/reuses a UUID-named folder for each job and keeps that job's outputs beneath it. Keep all secrets in GitHub Actions secret storage; never commit them, add them to result manifests, or send them to the browser.

## Dynamic API environment

On the Dynamic API hosting service, set:

- RIVERSHIFT_ACTIONS_ENABLED=true
- RIVERSHIFT_GITHUB_ACTIONS_TOKEN (Actions write permission on this repository)
- RIVERSHIFT_GITHUB_ACTIONS_REPOSITORY=moshiour0/SARGuardian-backend
- RIVERSHIFT_GITHUB_ACTIONS_WORKFLOW=river-shift-gcov-process.yml
- RIVERSHIFT_GITHUB_ACTIONS_REF=main after this worker branch has been reviewed and merged
- RIVERSHIFT_CALLBACK_SECRET with the same value as the GitHub Actions secret
- RIVERSHIFT_PUBLIC_API_URL with the public HTTPS base URL of the Dynamic API

Before enabling the feature, merge the worker workflow to the configured Git ref and deploy the Dynamic API code. The Dynamic repository's Supabase migration 20261103100000_river_shift_jobs.sql must also be applied to its configured Supabase project.

## Processing contract

The Dynamic API sends an immutable user AOI, date window, user-supplied event date, single collection maturity, frequency, covariance term, threshold mode, exact granule names and a server-generated request fingerprint.

The worker rechecks the submitted granule names against NASA CMR before it downloads. It requires four or more distinct, compatible observed acquisition dates and then checks the selected HDF5 files for the requested GCOV layer. It uses only the submitted AOI and dates. It does not substitute a built-in Bangladesh or Nepal polygon.

The current automatic worker is bounded to twelve observed dates and twenty-four granules. It performs observed-date water time-series screening, flood-period new-water coverage screening and persistent erosion/deposition candidate screening. It does not interpolate daily rasters.

Bankline migration is a separate measurement path that requires independently digitised before/after banklines and user-oriented transects. Although the supporting scientific tool is retained in this repository, the normal automatic GCOV job does not invoke it because those independent geometries are not part of the authenticated job request.

## Result integrity and release status

The worker stores derived outputs privately in Google Drive. Original raw NISAR HDF5 granules are not published as result artifacts. The Drive helper verifies remote byte size and MD5; the worker binds each result receipt to its SHA-256 digest; the Dynamic API checks the downloaded size and SHA-256 again before returning a result to the authenticated owner.

A successful workflow callback must include:

- schema_version 1
- processing_status PASS
- release_status PROVISIONAL
- independent_validation_status PENDING
- privately retained artifact receipts with verified checksums

A workflow PASS means the worker's processing and storage checks passed. It is not independent validation, field confirmation, flood causality, hazard detection, or a geophysical accuracy statement.
