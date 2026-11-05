# SARGuardian Backend

A FastAPI backend foundation for multi-user SARGuardian jobs. User authentication is separate from the central server-side Google Drive storage identity.

## Local setup

```powershell
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python scripts/init_db.py
python -m uvicorn app.main:app --reload
```

The API runs at `http://127.0.0.1:8000`. Health check: `GET /health`.

## Authentication endpoints

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout` with `X-CSRF-Token`
- `GET /auth/me`
- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`

Passwords are hashed with Argon2id. Sessions use opaque tokens whose hashes are stored in the database. The session cookie is HttpOnly; the CSRF cookie is readable by the application so it can be copied into the `X-CSRF-Token` header.

## Database

SQLite is the local default. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL for deployment. Run `python scripts/init_db.py` locally; Alembic configuration is present under `alembic/` for migration revisions.

Google Drive settings are server-side only and are intentionally empty in `.env.example`. They must never be returned by API responses or sent to the browser.

## Jobs

Authenticated `POST /jobs` requests create queued, user-owned job records only. Science execution and Drive result storage are added in later phases. The server derives ownership from the authenticated session; a client-provided `user_id` is ignored.

## Science execution

`SCIENCE_MODE=mock` is the local default. It performs no Earthdata/NASA access and writes a deterministic four-file result package under `SCIENCE_RESULT_ROOT/<job_id>`.

`SCIENCE_MODE=real` invokes the configured `SCIENCE_REAL_COMMAND` after verifying that `SCIENCE_ROOT` is at commit `SCIENCE_EXPECTED_COMMIT`. The external runner must preserve the existing pinned GOFF processing and write the same four-file package. This backend layer does not copy or rewrite the scientific algorithm.

## Central Drive storage

Drive storage is server-side only. Set `DRIVE_MODE=real` and provide these values through the backend environment or secret manager:

- `GOOGLE_DRIVE_OAUTH_CLIENT_JSON`
- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_DRIVE_PARENT_FOLDER_ID`

The refresh token must belong to the central `sarguardian.org@gmail.com` storage identity, not an end-user account. Never place these values in frontend configuration, browser storage, API responses, source files, or logs. `DRIVE_MODE=mock` is used for local tests and does not contact Google Drive.

## Science-data retention pilot

The non-destructive retention pilot lives in `.github/workflows/sarguardian-retention-pilot.yml`. It checks out the existing SARGuardian scientific engine at a fixed commit; it does not rewrite the scientific algorithm and it has no raw-source deletion step.

The default `engine-ready` profile keeps the native-resolution arrays used by the pinned readers and downstream LOS geometry: all GUNW `unwrappedInterferogram` and `pixelOffsets` datasets, all GOFF `pixelOffsets` layers/polarisations, scalar/1-D metadata and the GUNW `radarGrid` fields read by `geometry_merge.los_from_product`. It excludes high-posting GUNW `wrappedInterferogram`-grid rasters and other multidimensional fields that no pinned current `src/` processing path reads. Every exclusion is recorded with its path, shape, dtype and attributes alongside the full source inventory and source-file SHA-256.

Dataset copying uses HDF5's native object-copy operation to retain exact values and source chunks/compression filters without routing every pixel through Python and recompressing it. The archive still performs logical checksums, metadata/dimension-scale checks and raw-vs-curated reader equivalence. The `full-lossless` profile retains every dataset in supported standard NISAR HDF5 layouts. `include_wrapped=true` retains the whole high-posting wrapped grid; `derive_wrapped_phase=true` is an explicit optional phase-only derivative (radians), not spatial unwrapping and not a substitute for complex amplitude.

## Tests

```powershell
pytest
```

The science source and GitHub Actions workflows remain separate from this application foundation.

## Low-disk streaming processing for the Nepal source AOI

The sequential NISAR streaming workflow, its `validation-pilot` /
`full-source-baseline` profiles, default `derived-only` retention mode,
optional `full-lossless` archive mode, pre-cleanup baseline validation and
downstream parity gates are documented in
[docs/STREAMING_BATCH.md](docs/STREAMING_BATCH.md) and
[docs/RAW_HDF5_DEPENDENCY_AND_PARITY_PLAN.md](docs/RAW_HDF5_DEPENDENCY_AND_PARITY_PLAN.md).
The two-granule pilot and the 33-product source-baseline replay have now passed. See the run evidence and remaining scientific limits in `docs/STREAMING_BATCH.md` and `docs/RAW_HDF5_DEPENDENCY_AND_PARITY_PLAN.md`. The artifact-only replay is proven; the distinct full live `resume_from_run_id` recovery mode remains separately unverified.



## Final integration branch: dynamic AOI + reproducible science

The integration branch is **feat/final-aoi-science-integration**. It is based on
**feat/e2e-aoi-wkt-date-dashboard**, which already contains the pinned source-AOI
streaming work and the dynamic WKT/date workflow. The combined behavior,
separate science pins, candidate-check limitations, and merge acceptance gates
are documented in [docs/FINAL_INTEGRATION_BRANCH.md](docs/FINAL_INTEGRATION_BRANCH.md)
and [docs/DYNAMIC_AOI_WKT_E2E.md](docs/DYNAMIC_AOI_WKT_E2E.md).

Both the full source-AOI baseline and dynamic-WKT aggregation now invoke
tools/run_export_science_diagnostics.py to run pixel_stack.py on retained
GUNW exports. Candidate screening is integrated for the named source AOI only;
for arbitrary WKT, the current scientific script's named-polygon assumptions
are explicitly reported as a skip rather than applied incorrectly. A workflow
PASS is structural/reproducibility evidence, not proof of a landslide alert.
The default-branch WKT dispatcher remains an input-forwarding entry point and
currently targets the older AOI-only branch. To exercise this integration, run
the WKT workflow directly from `feat/final-aoi-science-integration`; update the
default dispatcher reference separately after this branch is reviewed. The
source-AOI streaming workflow remains independently callable.


## Generic Know Place polygon/date-range analysis

For continuity across chats, read and keep the [Know Place living context](docs/know-place/CONTEXT.md) updated before making further changes on `feat/know-place-analysis`.
The result also includes exact-acquisition-midpoint interval-average rates and descriptive vector-rate-change features. A rate-change/acceleration-like value is withheld if a pair is not contiguous, belongs to a different processing chain, has incompatible grid geometry, is not measurable, or crosses a documented instrument gap. These are research features only: the engine reports no risk score or operational alarm. \n\n
The isolated `feat/know-place-analysis` branch includes an opt-in [polygon/date-range workflow](.github/workflows/know-place-aoi-analysis.yml) for NISAR GOFF measurement, GIS exports, an offline dashboard, and an interactive Leaflet/OpenStreetMap presentation map (internet required for map tiles). Its default run is catalog-only, with no raw downloads. You can optionally pin exact processing releases (for example `P05023`) to avoid ambiguous same-interval variants; the engine never silently substitutes one release for another. A downloaded analysis requires explicit opt-in and configured Earthdata/Drive secrets. It reports measurement, paper-reproduction and hazard-detection statuses separately; a measurement result is not an operational landslide/glacier-collapse alarm.

Setup, output contents, limitations and the multi-event acceptance gates are documented in [the Know Place runbook](docs/KNOW_PLACE_ANALYSIS_RUNBOOK.md) and [the validation plan](docs/know-place/validation/MULTI_EVENT_VALIDATION_PLAN.md).


The [multi-event validation plan](docs/know-place/validation/MULTI_EVENT_VALIDATION_PLAN.md) defines event/non-event registry requirements, source/label provenance, site-level holdout splits, and an executable evaluator for a future frozen detector policy. Synthetic evaluator tests do not constitute real-world detection validation.
