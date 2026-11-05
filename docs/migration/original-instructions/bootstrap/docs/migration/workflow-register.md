# GitHub Actions workflow migration register

**Audited baseline:** 42 workflow YAML files total — 7 in `SARGuardian_Dynamic` and 35 in `SARGuardian-backend`.  
**Status:** classification framework created; exact file-by-file mapping awaits source-tree export.

## Required register fields

Every workflow must be recorded with:

| Field | Required content |
|---|---|
| Source | Repository, path, branch, source commit |
| Trigger | Event types, filters, inputs, schedule |
| Purpose | CI, build, deploy, dispatch, callback, replay, validation, cleanup |
| Status class | Production-active, CI-regression, replay/validation, historical/legacy, retirement candidate |
| Dependencies | Reusable/called workflows, external repositories, API endpoints |
| Permissions | Minimal token scopes and job-level permissions |
| Runtime | Runner, Python/Node versions, working directory, environment |
| Data path | Inputs, generated files, artifact names/retention, Drive/Supabase writes |
| Failure model | Error continuation, retry waves, terminal status propagation |
| Security | Secret/variable names only, callback auth, log redaction |
| Migration | New path, duplicate-run guard, tests, rollback |

## Known high-risk workflow groups

### RiverShift GCOV processing

Source: `river-shift-gcov-process.yml` in backend source.

The audited graph contains 20 jobs: prepare, four sequential batch/status barriers, up to three retry waves, and final assemble. Preserve:
- batches of 15 products where configured;
- successful products are never re-downloaded in retry waves;
- failures are collected and retried only after initial attempts finish;
- retry waves operate only on failed products;
- stage-specific logs and callback ordering;
- final failure is reflected in the outer workflow conclusion;
- artifact and Drive receipt/retention contracts.

Do not collapse this into one job during migration.

### Dynamic dispatch and callbacks

Dynamic includes the active API and dispatch/callback adapters. Backend worker workflows may call back into Dynamic. Map these relationships before relocating workflows or changing repository secrets.

### Known Place author-exact replay

Author-exact replay has P05023 acquisition filters, five-product identity checks, and temporary raw HDF5 retention controls. Verify the derived bundle remotely before raw product cleanup. Preserve feature-branch lineage; do not replace it with a main-only snapshot.

## Duplicate-run prevention

- Original production workflows remain authoritative during migration.
- New copies must be disabled, mock-only, or otherwise isolated until approved.
- A single dispatch must not trigger both old and new production workers.
- Do not copy live credentials into migration workflow files.
- Record source SHA and every content-level adaptation.

## Completion criteria

The register is complete only when all 42 workflow paths have a reviewed disposition and tested migration or retirement decision. Counts alone are not sufficient evidence.
