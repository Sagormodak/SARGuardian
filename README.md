# SARGuardian

Consolidated frontend, active Firebase/Supabase API, scientific workers, and pinned NISAR source from the three original SARGuardian repositories. Scientific algorithms and measurement/status semantics are preserved.

**Render setup:** [বাংলা deployment guide](docs/operations/RENDER_DEPLOYMENT_BN.md). The root [render.yaml](render.yaml) defines the frontend static site and active API. Credentials are configured separately in Render and GitHub Actions; none are included here.

| Component | Location |
|---|---|
| React/Vite frontend | [apps/dynamic/Frontend](apps/dynamic/Frontend) |
| Active Firebase/Supabase FastAPI API | [apps/dynamic/Backend](apps/dynamic/Backend) |
| Find Displacements and RiverShift workers; preserved older API | [engines/backend](engines/backend) |
| Pinned two-polygon Known Place engine | [engines/known-place](engines/known-place) |
| Pinned author-exact Known Place engine | [engines/known-place-author-exact](engines/known-place-author-exact) |
| Current NISAR science source and committed results | [science/nisar-core](science/nisar-core) |
| Central workflows | [.github/workflows](.github/workflows) |
| Supabase SQL, in timestamp order | [apps/dynamic/Backend/supabase/migrations](apps/dynamic/Backend/supabase/migrations) |

The original directory layouts inside each source tree are intentional: tests, worker imports, relative paths, and provenance checks continue to work. The two APIs are separate; Render runs **only** the Dynamic API.

Original branches, tags, and pull-request source heads from the three code repositories are retained under `archive/<source>/...` Git tags. Worker checkouts use these preserved Git objects at their original SHAs, from this repository. Do not delete archive tags. Development changes in a worker snapshot do not automatically change the pinned worker version: update the pin and its tests deliberately.

See [migration evidence and limitations](docs/migration/REPORT.md), [workflow register](docs/migration/workflow-register.json), [source manifest](docs/migration/source-manifest.json), and [scientific invariants](docs/migration/original-instructions/bootstrap/docs/scientific-validation/invariants.md).

Local validation from the repository root:

```sh
python -m pip install PyYAML==6.0.3
python scripts/verify_migration.py
```

Use a full clone with tags for integrity checks. [Monorepo CI](.github/workflows/monorepo-ci.yml) validates the app, API, worker tests, science tests, and retained history. Imported live-processing/replay workflows are manual or reusable; automatic regression testing is centralized to avoid duplicate production work.

Repository readiness does not establish a live deployment: Firebase/Maps domains, Supabase migrations, credential permissions, callbacks, private Drive access, and a consented small processing pilot must be checked after configuration. The migration does not run live science, change existing deployments, apply database migrations, or move private artifacts.

Original attribution, licenses, citation files, source READMEs and commit histories remain preserved within their respective source trees and archive tags.
