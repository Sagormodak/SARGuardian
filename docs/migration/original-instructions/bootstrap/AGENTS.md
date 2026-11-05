# SARGuardian repository guardrails

These rules apply to every migration, code review, workflow change, and deployment.

## Source provenance
- Treat the three source repositories and their recorded SHAs as immutable migration inputs.
- Do not rewrite, delete, archive, or force-push any source repository or source branch.
- Record source repository, ref, commit SHA, import date, and any transformation for every imported subtree.
- Never silently replace a pinned NISAR science revision with a newer default-branch revision.

## Engine boundaries
- Find Displacements is a target-free AOI scan. Do not add a required target point or merge GOFF and GUNW measurements.
- Known Place Analysis is a separate research reproduction workflow. Preserve author-exact acquisition rules, two-polygon semantics, feature-branch lineage, and retention checks.
- River Shift is an independent GCOV engine. Do not route it through or change the scientific methods of Find Displacements.
- Glacier Movement is currently a product route into Find Displacements; do not claim a separate engine without evidence.

## Scientific interpretation
- PASS means structural/provenance checks passed; it is not independent geophysical validation.
- A GOFF anomaly is not, by itself, proof of landslide or surface movement.
- Pairwise LOS displacement is not automatically cumulative displacement or 3-D motion.
- Playback represents actual observations only, not interpolation or forecast.
- Not measured is not zero.
- Reference stability is not independently verified unless independent evidence exists.

## Workflow safety
- Do not enable duplicate production workflows during migration.
- Preserve triggers, permissions, concurrency, artifacts, callbacks, retries, and retention behaviour.
- RiverShift must retain retry-only-failed-products semantics and staged processing/assembly barriers.
- A green outer job is invalid if a required inner stage failed; propagate failures to the final workflow conclusion.
- Never put tokens, service-account JSON, private keys, callback secrets, or signed URLs in source files, logs, docs, or artifacts.

## API and deployment safety
- Keep the active Firebase/Supabase API separate from the older SQLAlchemy/session-oriented backend service until usage, auth, schema, and contract parity are proven.
- Do not assume Render is the production host. Confirm deployment ownership from Vercel settings and deployment evidence.
- Do not change Vercel roots, production aliases, DNS, Supabase schema, or live callback destinations during source import.
- Use preview deployments and isolated/mock processing tests before any real-data pilot.

## Change control
- Work on migration branches and use draft PRs for structural changes.
- Do not merge to main or switch production until tests, source-integrity checks, workflow audits, and deployment checks pass.
- Do not make scientific algorithm changes as incidental migration cleanup.
