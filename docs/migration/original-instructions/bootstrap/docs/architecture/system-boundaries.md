# SARGuardian system boundaries

**Baseline date:** 2026-11-05  
**Status:** migration architecture decision; implementation not yet consolidated.

## 1. Current source topology

### Dynamic — application and active API
Source: `moshiour0/SARGuardian_Dynamic`  
Audited baseline: `dd64b7adc90594f1d7f316b352e39fbac2013cb6`

This repository contains more than a frontend:
- React/Vite application, map and engine pages, archive/dashboard UI.
- Firebase-authenticated active FastAPI service under `Backend/app`.
- Supabase-backed job persistence and API contracts for displacement, Known Place, and RiverShift.
- GitHub Actions dispatch adapters, callbacks, result-manifest and Drive retrieval adapters.
- Frontend/API tests and deployment configuration.

**Decision:** this is the current application/API source of truth unless live deployment evidence disproves it. The initial destination is `apps/web` and `apps/api`, but preserve source-relative build/import paths until safe relocation is tested.

### Backend — processing and workflow system
Source: `moshiour0/SARGuardian-backend`  
Audited baseline: `97d849454918b1425ac41bb70e7a32d11cfd3833`

Contains:
- NISAR processing workers and batch/streaming tools.
- Find Displacements AOI candidate and pixel diagnostics under `dashboard/` and `tools/`.
- RiverShift GCOV engine under `tools/river_shift/`.
- GitHub Actions workflow collection (35 YAML files at the audited baseline).
- A separate `app/` FastAPI/SQLAlchemy/session-oriented service, migrations, and legacy dispatch components.

**Decision:** import workers and workflows as source-preserving units. Do not merge the backend `app/` service into the Dynamic API. First classify it by tracing inbound dispatches, callbacks, and external deployment use.

### NISAR science source
Source: `moshiour0/SARGuardian`  
Current main at audit: `9fcb543ef28a7f6fe70a379aed9cfe3e43e277ec`

This source includes science modules such as:
- `timeseries.py`
- `local_floor.py`
- `inverse_velocity.py`
- `geometry_merge.py`
- `bound.py`
- `candidate_check.py`
- `pixel_stack.py`
- `goff_reader.py`
- `gunw_reader.py`

**Decision:** preserve exact worker-pinned revisions separately from current `main`. The source SHA used by a run is part of scientific provenance.

## 2. Engine boundaries

| Engine / category | Purpose | Boundary that must remain |
|---|---|---|
| Find Displacements | AOI + time window; target-free candidate discovery | GOFF and GUNW remain separate; GUNW is gated by network/grid/support/reference checks |
| Known Place Analysis | Fixed paper benchmark and two-polygon research | Separate from AOI-wide discovery; preserve P05023 author-exact benchmark and feature-branch/PR lineage |
| River Shift | NISAR GCOV river/flood surface-change intelligence | Independent GCOV engine and validation chain |
| Glacier Movement | Product category currently routed into Find Displacements | Do not represent as an independent processing engine without code/workflow evidence |

## 3. API boundary

Two FastAPI implementations exist:
1. Dynamic `Backend/app`: Firebase authentication, Supabase persistence, current frontend API contracts, Vercel serverless entrypoint.
2. Backend `app/`: older SQLAlchemy/session-oriented service with different persistence and auth assumptions.

They are not interchangeable. Inventory every caller, route, auth mechanism, schema, and callback before retiring or merging either one.

## 4. Target layout (provisional)

```text
apps/
  web/
  api/
engines/
  find-displacements/
  known-place/
  river-shift/
science/
  nisar-core/
.github/workflows/
infrastructure/
  supabase/
  vercel/
docs/
  architecture/
  migration/
  scientific-validation/
```

A source-layout snapshot may be retained temporarily to keep the first import behavior-preserving. Final destinations will be selected from the real import graph, not names alone.

## 5. Non-goals for first migration wave
- No new scientific algorithms or merging of GOFF, GUNW, and GCOV measurements.
- No production callback/dispatch endpoint change.
- No Vercel production-root or alias change.
- No Supabase schema migration.
- No secret-value transfer.
- No source-repository deletion or archival.
