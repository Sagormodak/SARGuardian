# SARGuardian Science Engine — End-to-End Checklist

Status is deliberately separated into confirmed source-code findings and implementation gates. A checked source-code audit item does not mean the scientific engine is complete.

## Phase 0 — Source/workflow audit

- [x] Locate `timeseries.py`, `local_floor.py`, `inverse_velocity.py`, `geometry_merge.py`, and `bound.py` in the core science repository.
- [x] Trace the dynamic WKT dispatcher and reusable AOI workflow.
- [x] Trace the fixed-source streaming baseline and separate extended-science workflow.
- [x] Confirm the dynamic WKT aggregation uses `run_export_science_diagnostics.py` (pixel stack and conditionally supported candidate screening), not the complete five-script chain.
- [x] Confirm the fixed-source aggregate calls local-floor, inverse-velocity, and bound steps; the extended-science workflow invokes geometry sensitivity and fresh source-candidate analyses.
- [x] Confirm the fixed-source extension expects a successful full-baseline source bundle and is not arbitrary-AOI processing.
- [x] Record that the reviewed backend orchestrators do not directly invoke `src/timeseries.py`; the fixed-source series is reconstructed by a backend common-reference routine, requiring parity documentation/tests.
- [x] Identify the dispatcher’s stale `@feat/final-aoi-science-integration` reusable-workflow ref.

## Phase 1 — Safe workflow routing

- [x] In this feature branch, change only the dispatcher reusable-workflow ref to `@main`, so the manual entry point reaches the merged dashboard-enabled AOI workflow.
- [x] Add an automated regression test for the dispatcher ref.
- [x] Add the regression test to the AOI code-validation workflow.
- [ ] PR CI passes on the new branch.
- [ ] Review/merge the routing + documentation PR; do not start the full new-place science run before this is complete.

## Phase 2 — Dynamic-AOI science contract

- [ ] Define versioned schemas for product pair, track/path, raster measurement, valid-pixel support, target/candidate, local floor, time-series epoch, and stage report.
- [ ] Ensure every downstream stage receives the exact WKT hash and explicit AOI geometry; remove accidental dependency on named source/langtang/lhende polygons for dynamic runs.
- [ ] Ensure the current product manifest distinguishes GUNW phase LOS from GOFF offset measurements and keeps units/processing maturity.
- [ ] Add an explicit compatible-pair inventory and graph-connectivity report; never mix ascending/descending networks.
- [ ] Establish grid, CRS, registration, common-reference and target-exclusion contracts before inversion.

## Phase 3 — Scientific stages for arbitrary WKT

- [ ] Time series: produce per-track cumulative LOS estimates from a connected pair graph; report component, reference epoch, pair count, residuals, uncertainty and valid support. Prove parity to established science semantics.
- [ ] Local floor: compute per-target/per-pair floors from the new AOI's supported measurements, with finite-pixel counts and quality-mask provenance.
- [ ] Geometry: accept AOI/target coordinates as inputs; report DEM/track coverage and sensitivity without using fixed Langtang coordinates.
- [ ] Inverse velocity: use only a vetted series and compatible floor table, with explicit pre-event cutoff/event date and tests against leakage.
- [ ] Bound: parameterize inputs and output paths; keep source-study bound results separate from new-place estimates.
- [ ] Candidate screening: use a candidate set built for the submitted AOI or explicitly mark it unsupported; do not substitute the source candidate CSV.
- [ ] Status semantics: separate `PASS`, `FAIL`, `INSUFFICIENT_DATA`, `NO_ALARM`, and `SKIPPED_UNSUPPORTED_AOI`; do not collapse them to one green status.

## Phase 4 — Reproducible tests

- [ ] Known synthetic cumulative motion yields the expected sign/magnitude within a stated tolerance.
- [ ] No-motion data do not produce an inverse-velocity alarm.
- [ ] Disconnected pair networks are reported as separate components and never stitched together.
- [ ] ASC/DESC or incompatible product families are not silently mixed.
- [ ] CRS/grid mismatch fails or uses a documented, tested transform.
- [ ] AOI boundary masking and valid-pixel counts match the submitted polygon.
- [ ] Low/zero support is `INSUFFICIENT_DATA`, not a quiet detection.
- [ ] A stale CSV, stale source-AOI target list, or mismatched pair ID is refused.
- [ ] Event/post-event pairs cannot enter a purported pre-event forecast.
- [ ] Dashboard and ZIP are built from the exact stage outputs whose hashes appear in the run report.
- [ ] Drive upload and receipt verification remain mandatory for the configured retained result bundle.

## Phase 5 — New-place release gates

- [ ] Run the small `validation-pilot` after routing fix and science-adapter changes land.
- [ ] Inspect product manifest, AOI hash, pins, pair graph, per-product valid pixels and every stage status.
- [ ] Confirm result ZIP contains science outputs, logs, manifest, checksums, dashboard assets and caveats.
- [ ] Confirm viewer can display available observations and does not imply interpolation/prediction.
- [ ] Only then choose `full-aoi-baseline` for a broader new-place run.
- [ ] Review scientific results separately from GitHub Actions status; independently validate any physical/hazard claim.

## Do not mark complete merely because

- the action is green;
- the dashboard rendered;
- some raster pixels are valid;
- a time-series CSV exists;
- inverse velocity prints a predicted date without passing the floor/temporal/event gates; or
- source-AOI historic outputs are packaged alongside a new AOI request.
