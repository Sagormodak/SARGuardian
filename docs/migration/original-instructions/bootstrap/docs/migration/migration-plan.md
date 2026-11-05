# SARGuardian monorepo migration plan

**Plan date:** 2026-11-05  
**Execution state:** bootstrap branch; source code import has not started.

## Executive decision

Use a **preserve-first, staged monorepo migration**. Do not concatenate the three repositories into one root and do not merge their APIs in one step. Import immutable snapshots first, retain source provenance, then promote code into final app/engine locations after dependency and workflow mapping.

## Phase 0 — protect and verify inputs

- [x] Verify target repository exists and connected GitHub integration has push/admin access.
- [x] Record current default-branch SHAs for all three source repositories.
- [x] Record Known Place feature branch and open PR #85 separately from backend main.
- [ ] Capture source tags/branches and recursive tree manifests for all source refs.
- [ ] Export active workflow inventory and run evidence.
- [ ] Record Vercel project roots, production branch/alias, and Supabase linkage without changing them.
- [ ] Confirm which old backend `app/` endpoints are still called by workflows or external deployments.

**Exit condition:** immutable input refs and file-tree inventories are committed here.

## Phase 1 — safe monorepo foundation

- [x] Create README, engineering guardrails, architecture boundary document, and source-pin manifest.
- [ ] Add CODEOWNERS, contribution rules, and CI baseline.
- [ ] Set branch protection and verify required checks.
- [ ] Add secrets-free environment templates after name mapping.

**Exit condition:** repository can run basic validation and PR checks without touching production.

## Phase 2 — import source snapshots without refactoring

Recommended source mapping:
- Dynamic: `Frontend/`, active `Backend/`, tests, tools, and relevant docs.
- Backend: `tools/`, `dashboard/`, workflow definitions, tests, and supporting docs.
- NISAR science: pinned source snapshots or a versioned `science/nisar-core` import.

Keep original relative paths inside a versioned snapshot during the first pass if necessary. Do not copy nested `.github/workflows` into the active root workflow directory until duplicate-run risk is controlled.

**Integrity checks:** file count, path inventory, SHA-256 per file, symlinks, executable bits, line endings, large files, LFS objects, and secret scanning.

**Exit condition:** every imported file traces to its source repository and tree SHA; no source repository changed.

## Phase 3 — central workflow migration

The audited baseline has 42 workflow YAML files: 7 in Dynamic and 35 in backend. For each one, record:
- triggers and filters;
- job graph, dependencies, concurrency, matrix, permissions, environments;
- checkout repository/ref/path and cross-repository dispatches;
- artifact names, retention, upload/download dependencies;
- secrets/variables by name only;
- callbacks, callback authentication, expected terminal states;
- classification: production-active, CI-regression, replay/validation, historical/legacy, retirement candidate.

Do not enable duplicate production dispatch in old and new repositories. Keep original workflows authoritative while target copies run only with mocks or isolated triggers.

**RiverShift constraint:** preserve the current 20-job batch/retry/assemble graph, status barriers, artifact contracts, callback ordering, and retry-only-failed-products semantics. Re-run failed-only retry tests before any real GCOV pilot.

**Exit condition:** all 42 files have a reviewed disposition; active target workflows pass isolated tests; cutover and rollback are documented.

## Phase 4 — app, API, engine, infrastructure integration

- Promote React/Vite app into `apps/web` after Vercel build root and asset paths are tested.
- Promote Dynamic active Firebase/Supabase API into `apps/api` after route, auth, CORS, callback, and persistence tests pass.
- Keep old SQLAlchemy/session-oriented backend `app/` isolated until inbound usage is proven absent or its role is explicitly retained.
- Promote Find Displacements, Known Place, RiverShift, and NISAR code into separate engine/source boundaries.
- Keep original working directories until imports, workflow working directories, relative paths, and output manifests are verified.
- Keep Supabase schema as-is; schema consolidation is a separate reviewed migration.
- Configure Vercel root and environment only after preview build and route tests succeed.

**Exit condition:** functional and scientific tests pass in monorepo paths with no silent output-contract drift.

## Phase 5 — validation, pilot, cutover

1. Run frontend lint/build/unit tests and API tests.
2. Run backend worker tests and each engine's regression suite.
3. Compare canonical fixtures and output manifests with source baselines.
4. Run workflow dry-runs/mocks: callback auth, failure propagation, retry isolation, artifact retention, cleanup.
5. Deploy preview only; verify map, login, AOI drawing/search, dashboard, archive, and engine pages.
6. Run an isolated real-data pilot only after mock and scientific fixture checks pass.
7. Compare pilot outputs with source baseline and independent validation evidence.
8. Obtain explicit approval before moving production dispatch, Vercel aliases, or callback endpoints.
9. Retain rollback to original deployments and repositories.

## Mandatory cutover gates

- Source integrity: PASS
- Workflow inventory/disposition: PASS
- Test parity: PASS
- API contract and auth: PASS
- Supabase persistence and retention: PASS
- Vercel preview and routing: PASS
- Callback and retry semantics: PASS
- Scientific status/measurement semantics: PASS
- Security and secret scan: PASS
- Rollback rehearsal: PASS

A repository merge is not a production cutover.
