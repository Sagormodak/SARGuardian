# Migration report — 2026-11-06

Destination: `Sagormodak/SARGuardian`. Working branch: `migration/consolidate-render`.

## Source preservation

| Source | Baseline |
|---|---|
| `moshiour0/SARGuardian_Dynamic` | `dd64b7adc90594f1d7f316b352e39fbac2013cb6` |
| `moshiour0/SARGuardian-backend` | `97d849454918b1425ac41bb70e7a32d11cfd3833` |
| `moshiour0/SARGuardian` | `9fcb543ef28a7f6fe70a379aed9cfe3e43e277ec` |
| Known Place two-polygon worker | `0e0611c12913044787ee84a39fa60a81d30ae516` |
| Known Place author-exact worker | `b825df798ea4cb9874aa10dd01174d2a8ef73cba` |

The import manifest covers **1,102 files**, including the three main snapshots, two distinct Known Place snapshots and eight instruction documents. Every original path, Git blob ID, file mode and SHA-256 is recorded. Source objects retain original commit hashes and full reachable history.

**600 original source branch/tag/PR-head references** from the three requested code repositories and **16 explicit workflow/worker revision pins** are preserved as **616 namespaced archive tags**. The source manifest checks 602 references (the 600 original references plus two Known Place pins); the workflow-pin manifest covers all 16 pins. Four additional instruction-repository branch references remain local-only; publishing that repository's unrelated history is outside the transfer scope. Selected instruction documents are preserved as provenance.

`scripts/verify_migration.py` checks file hashes against the manifest, exact recorded runtime adaptations, archive tag identities, immutable science pins, and workflow semantic equivalence. No LFS pointer or submodule is substituted for source code. Source-relative layouts remain intact. Original licenses, citations, fixtures, docs, SQL and workflows are retained.

## Runtime adaptation

Only `apps/dynamic/Backend/app/known_place.py` differs from its source snapshot: environment variables now configure the generic and author-exact repository/ref. Source defaults remain compatible. The Render configuration explicitly points both workflows to `Sagormodak/SARGuardian`.

See [exact patch](runtime-adaptation.patch) and [before/after hashes](adaptations.json). No scientific method, product identity, output interpretation, API authentication, callback signing, retention logic or database schema was changed.

## Workflow disposition

The sources contain 43 default-branch workflows (7 Dynamic, 35 backend, 1 science). Three additional pinned reusable workflow definitions are imported from feature history, producing **46 centralized source workflows**, plus one new current-tree CI workflow.

All source workflows remain in their original snapshot directories, unchanged. Root copies retain their job graphs, permissions, concurrency, matrices, callback scripts, artifacts, retention and retries. Checkouts use the **destination repository** with the **original source SHA**, so original scripts still run with their original root layout. Cross-repository reusable calls become local calls to distinct generated files. Filename collisions retain separate workflows; none are overwritten.

Automatic source CI/replay triggers are archived, while root scientific workflows remain manual/reusable. This avoids duplicate production work; current-tree CI handles automatic regression tests. [Workflow register](workflow-register.json) records both original and target triggers and every checkout/call transformation. One pre-existing shell grep expression in the RiverShift test workflow is split into adjacent quoted strings to avoid GitHub evaluating a literal `inputs.job_id` expression; its intended grep text is unchanged.

RiverShift retains its 20-job processing graph, retry barriers, retry-only-failed-products behavior, callback order and artifact contracts. Known Place's current dispatcher and its separate author-exact workflow retain their distinct source pins. Find Displacements uses the Dynamic wrapper with its unchanged scientific processing pins.

Historical replay/validation workflows still refer to historical run IDs or source-provenance labels where those are evidence inputs. Private artifacts and prior run output are not copied by code migration. They are not prerequisites for the newly configured app's fresh-job paths.

## Validation

Local checks completed:

- Source file integrity, preserved refs, 16 pins, and 46 workflow semantic contracts: PASS. Independently repeated against a fresh clone of the published destination.
- Actionlint 1.7.12 across centralized workflows: PASS.
- Frontend: production build, lint, and 155 tests: PASS.
- Active API: 214 tests pass locally; one POSIX file-permission test needs Linux. Google Maps dashboard adapter test: PASS.
- New repository dispatch/status routing: 2 tests PASS.
- NISAR science: 180 tests PASS.
- Backend/worker suite: 593 tests pass across initial/retry runs, 1 skipped; 2 tests require POSIX permissions/path separators. Windows long-path issues were resolved for validation using extended-length temporary paths, without source edits.
- Known Place two-polygon: 333 tests pass across initial/retry runs.
- Author-exact selected author/paper/footprint regression: 142 tests PASS. Its broader historical generic-AOI suite has a pre-existing string-format assertion mismatch (six versus nine WKT decimal places); the current two-polygon snapshot passes that integration test. The historical source and test are preserved unchanged. The author-exact CI job targets its author/paper/footprint behavior, and the separate current Known Place job covers the generic AOI engine.
- Gitleaks 8.30.1 full locally reachable source history and independently cloned published history: zero unreviewed findings. The 27 historical matches and seven new-path copies are documented synthetic test identifiers/dummy Maps keys; additional copies match previously reviewed five-line test contexts exactly. No real credential was copied into a new configuration.
- Root Render Blueprint: PASS against Render's official `https://render.com/schema/render.yaml.json` JSON schema (SHA-256 `8a3fb8da6b4f55fe686fbefa790e011d3dd7895f013f355953c572a21ab6494a`). This is structural validation, not an authenticated Render deploy.

## Publication and outstanding CI

All code and archive tags are published. [Draft PR #1](https://github.com/Sagormodak/SARGuardian/pull/1) contains the migration; `main` currently contains only the initialization README.

[Linux CI run 42103606490](https://github.com/Sagormodak/SARGuardian/actions/runs/42103606490) could not allocate any runner because of a GitHub account-level Actions restriction. All seven jobs ended before their first step; **no Linux test executed**, so this run is not a test-suite result. Existing local Ubuntu/WSL was also unavailable because its registered virtual disk path is missing. The Windows/POSIX limitations listed above remain unverified on Linux.

Resolve the GitHub Actions account restriction, rerun Monorepo validation, inspect the results, and complete the migration review before merging to `main`. The same runner restriction also prevents the website's scientific processing workflows from starting. Render secrets alone do not resolve it. No force-push or existing source change was made.

Local test evidence does not imply hosted integration or operational pilot success.

## Deployment boundary

The root Render Blueprint and [Bengali guide](../operations/RENDER_DEPLOYMENT_BN.md) configure two new services. No service was created, existing deployment changed, domain moved, database altered, secret transferred, or live satellite job dispatched.

Before operating the site, configure the two Render environments and new Actions secrets, reconcile/apply the seven Supabase migrations, authorize frontend domains in Firebase/Maps, and verify live login/persistence/callback/Drive behavior with a consented small pilot. Existing deployments remain available for rollback. A green unit-test suite is not real-data output parity or independent scientific validation.
