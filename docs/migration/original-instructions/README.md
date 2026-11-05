# SARGuardian Monorepo

A controlled consolidation of SARGuardian's web application, active API, independent processing engines, NISAR science source, and GitHub Actions workflows.

> **Migration status: bootstrap in progress.** The original repositories remain authoritative and unchanged. No production deployment, live processing, secret transfer, or workflow cutover is performed by this repository yet.

## Source systems

| Source | Responsibility | Audited baseline |
|---|---|---|
| [SARGuardian_Dynamic](https://github.com/moshiour0/SARGuardian_Dynamic) | React/Vite web app, active Firebase-authenticated FastAPI API, Supabase job persistence, deployment adapters | `dd64b7adc90594f1d7f316b352e39fbac2013cb6` |
| [SARGuardian-backend](https://github.com/moshiour0/SARGuardian-backend) | Scientific processing workers, RiverShift GCOV engine, Find Displacements diagnostics, reusable Actions workflows | `97d849454918b1425ac41bb70e7a32d11cfd3833` |
| [SARGuardian](https://github.com/moshiour0/SARGuardian) | NISAR science source used by pinned processing workflows | Current main at audit: `9fcb543ef28a7f6fe70a379aed9cfe3e43e277ec` |

These are provenance references, not proof that all source files have already been imported. See [source pins](docs/migration/source-pins.json).

## Engine boundaries

- **Find Displacements:** target-free AOI-wide candidate discovery. GOFF offsets and GUNW LOS diagnostics remain separate measurement families.
- **Known Place Analysis:** a separate fixed-benchmark and two-polygon research workflow. Its feature-branch and open-PR lineage must be preserved; it is not assumed to exist in backend `main`.
- **River Shift:** an independent NISAR GCOV engine with ASF acquisition discovery, processing, overlap diagnostics, transects, and external validation.
- **Glacier Movement:** currently a product/category route into the shared Find Displacements engine, not a separately proven processing engine.

## Migration principles

1. Preserve the original repositories and immutable source SHAs until the monorepo passes acceptance.
2. Import source snapshots with provenance before refactoring or relocating code.
3. Keep the active Dynamic API distinct from the older backend `app/` service until a usage and contract review proves consolidation safe.
4. Preserve all workflow triggers, permissions, artifacts, callbacks, retries, and retention behaviour.
5. Never copy secret values into Git. Build an explicit secret-name mapping and configure target secrets separately.
6. Validate in an isolated migration branch and preview environment before any production cutover.
7. No engine algorithm or scientific status semantics may change as a side effect of repository consolidation.

## Planned layout

The final layout will be adjusted to the verified import graph and workflow working directories. The initial target is:

```text
apps/
  web/                 # React/Vite frontend
  api/                 # active Firebase/Supabase API
engines/
  find-displacements/
  known-place/
  river-shift/
science/
  nisar-core/           # immutable/pinned NISAR source
.github/workflows/      # curated central workflows
infrastructure/
  supabase/
  vercel/
docs/
  architecture/
  migration/
  scientific-validation/
```

The first import phase may retain source-layout snapshots to avoid changing runtime paths before dependency and deployment checks are complete.

## Current readiness

- [x] New private repository created and write access verified.
- [x] Source repository baselines verified.
- [ ] Full file-level import and source integrity checks.
- [ ] Workflow-by-workflow centralization and permissions audit.
- [ ] API/deployment path and Vercel project-root verification.
- [ ] Secret and Supabase configuration mapping (names only).
- [ ] Regression tests, preview deploy, and isolated pilot.
- [ ] Explicit production cutover approval.

See [migration plan](docs/migration/migration-plan.md), [architecture boundaries](docs/architecture/system-boundaries.md), and [scientific invariants](docs/scientific-validation/invariants.md).
