# Scientific invariants that migration must preserve

These rules constrain code movement, naming, workflow statuses, dashboards, and regression tests.

## Find Displacements

- Input is AOI + time window; users do not need to nominate a target point.
- GOFF offset anomalies and GUNW LOS diagnostics are separate data products. Never combine them numerically or display them as one displacement estimate.
- A GOFF anomaly/candidate is a screening signal, not confirmation of a landslide, glacier movement, or another physical event.
- GUNW pixel-wise diagnostics are allowed only after existing network connectedness, redundancy, grid, common-support, spatial-reference, rank, and temporal gates pass.
- An AOI-derived relative reference is not an independently surveyed stable-ground reference.
- Pairwise LOS displacement is not automatically cumulative displacement or 3-D motion.
- If no compatible repeated GUNW network exists, do not report a GUNW time series or convert missing measurements to zero.

## Known Place Analysis

- Keep this workflow separate from target-free Find Displacements discovery.
- Fixed benchmark acquisition must use author-exact P05023 products, not X05026, with the specified ascending T098 HH GOFF pairs.
- Benchmark window, five-product identity, and paper-parity checks must remain explicit.
- Preserve two-polygon semantics: Measurement Polygon and Reference Polygon are distinct; reference background cells exclude measurement cells.
- A user-provided reference polygon is not proof of reference stability.
- Preserve acquisition identity checks, paper method, uncertainty reporting, terrain/vertical-datum handling, author archive/field parity, and cleanup-after-remote-verification semantics.

## River Shift

- RiverShift is a separate NISAR GCOV processing and validation engine.
- Do not substitute GOFF or GUNW for GCOV products or merge their values.
- Keep ASF catalogue discovery, minimum acquisition-date eligibility checks, download/process orchestration, overlap audits, water/flood detection, morphology, transects, time series, and independent reference validation as traceable stages.
- Preserve Sentinel-2 and OPERA DSWx/S1 validation evidence and report overlap/coverage limitations.
- Retry only failed products; do not re-download successful products during retry waves.
- Never report success if a required processing or assembly stage failed.

## Shared dashboard language

| Status / display | Valid interpretation |
|---|---|
| PASS | Structural/provenance checks passed; not independent geophysical validation |
| GOFF anomaly | Candidate signal; not proof of movement |
| Pairwise LOS | Relative pair measurement; not necessarily cumulative or 3-D |
| Playback | Actual observation records; not interpolation or forecast |
| Not measured | Missing/unsupported measurement; never equal to zero |
| Reference polygon | User-defined background region; stability not independently verified by default |

## Migration regression expectations

For representative fixtures and workflow runs, compare acquisitions/product identities, geometries, grid/CRS/transform/masks, common-valid support, candidate counts and rejection reasons, status values, withheld/not-applicable explanations, uncertainties, reference provenance, output manifests, map overlays, retention, and terminal workflow state.

A structurally valid output file is not evidence of a geophysically validated event.
