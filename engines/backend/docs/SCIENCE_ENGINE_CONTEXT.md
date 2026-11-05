# SARGuardian Science Engine — Current Context

**Audit date:** 2026-10-27  
**Scope:** GitHub Actions routing, science-script execution, and the gap between the fixed source-AOI science baseline and an arbitrary user-supplied WKT AOI.  
**Safety boundary:** This is a source-code/workflow audit. It does not launch NISAR downloads, mutate science algorithms, or claim that any hazard was detected.

## Executive finding

The repository contains the scientific scripts, and some backend Actions call several of them. However, **there is not one current workflow that runs all five named scripts as a correctly scoped, end-to-end science chain for an arbitrary new WKT AOI**.

The two principal paths serve different purposes:

1. **Dynamic WKT processing** is the user-facing path for a new place and date range. It discovers NISAR L2 products, processes products independently, validates AOI-clipped derivatives, and generates a report/dashboard. Its downstream science adapter currently runs the per-pixel stack and only runs candidate screening when the pinned script can safely support the requested AOI. It does not yet run the complete reusable time-series / local-floor / geometry / inverse-velocity / bound chain for arbitrary WKT.
2. **Fixed source-AOI baseline + extended science** performs much more of the historical research analysis, but it is anchored to the committed source AOI, committed baseline inventory, named candidate locations, and the documented 2026-08-26 event. It must not be relabelled as arbitrary-AOI science.

## Workflow map

| Workflow | What it actually does | Important boundary |
|---|---|---|
| `.github/workflows/sarguardian-aoi-wkt-dispatcher.yml` | User-facing manual entry point for WKT, dates, profile, and retention profile | It previously called the reusable workflow on `feat/final-aoi-science-integration`, not the merged dashboard-enabled `main` workflow. This PR changes that reference to `@main` and adds a regression test. |
| `.github/workflows/sarguardian-aoi-wkt-dashboard.yml` | Discovers supported products for the exact WKT/date window; fan-out product workers; aggregation, reports, dashboard, Drive/result packaging | The dynamic science pin is `10639a916c9829850775410b3ed7de62e527770d`. A processing/dashboard PASS is not a full scientific detector PASS. |
| `.github/workflows/sarguardian-streaming-batch.yml` | Processes the fixed, committed source-AOI product baseline and compares outputs with committed batch results | Default `validation-pilot` processes two products; select `full-source-baseline` for the 33-product suite. This is not a free-form AOI workflow. |
| `.github/workflows/sarguardian-extended-science.yml` | Manually consumes a successful full-baseline result bundle, reuses verified Results 4–5 outputs, and reruns selected Results 1, 2, 3, 6, and 7 analyses | Pinned to `ab547ecc82bcc4d6ccef545a59852536c2beacc6`; the report declares `aoi: source`. It is a separate follow-on, not automatically part of a dynamic WKT run. |
| `.github/workflows/nisar-gunw-timeseries-test.yml` | Historical real-data time-series feasibility test with its own embedded test implementation | Pins the older `Sagormodak/SARGuardian@77cc9646cfa46d3aff3669d351912f984cf67aa3`; do not treat it as the current production AOI science pipeline. |
| `SARGuardian/.github/workflows/science-tests.yml` | Runs `pytest tests/` on source/test changes | Regression tests only; it does not perform live AOI acquisition or a full processing run. |

## Named science-script audit

| Script | Scientific role | What current backend orchestration establishes |
|---|---|---|
| `src/timeseries.py` | Invert a connected network of pairwise GUNW observations into a per-track cumulative LOS time series; disconnected components and ascending/descending mixing must be refused | No direct invocation of this script was found in the reviewed backend runtime orchestrators. The fixed-source stream aggregator reconstructs point-series outputs through `run_common_reference_target_series()`; a verified `ts_*.csv` is not evidence that `timeseries.py` itself ran. The dynamic WKT aggregator does not currently run the equivalent complete graph inversion. |
| `src/local_floor.py` | Estimate local, candidate-level measurement/noise floors using valid per-product pixels and configured spatial windows | Invoked by the fixed-source streaming/extended-science paths. The current contract depends on named AOI/candidate inputs and must be generalized and tested before arbitrary WKT candidates can use it safely. |
| `src/inverse_velocity.py` | Apply the Fukuzono inverse-velocity gate to a measured series using compatible noise-floor evidence and a specified event/cutoff policy | Invoked by fixed-source aggregation/extended science against source-AOI series and source-era settings. A forecast result is not valid unless its series, floors, track, dates, and event cut are provenance-matched. |
| `src/geometry_merge.py` | Evaluate track geometry and, where assumptions and observations permit, project/combine compatible LOS series | Invoked by extended science for the documented source/candidate geometry. It must not combine raw ascending/descending phase; custom AOI/target and track-geometry coverage must be explicit. |
| `src/bound.py` | Build the published source-study bound table from validated candidate/floor/sensitivity evidence | Reads the committed source-study outputs and enforces the source polygon. It is not currently a generic `--aoi-wkt` bound estimator. |

Additional dynamic-WKT adapter: `tools/run_export_science_diagnostics.py` runs `src/pixel_stack.py` on available retained GUNW exports. It reports candidate-check status separately; the candidate checker is deliberately skipped for arbitrary WKT if it cannot prove it is using the submitted polygon. That is safer than accidentally applying the old source polygon.

## Correct interpretation of current outputs

The dynamic WKT workflow can produce per-product derived raster exports/quicklooks, product and provenance tables, pixel-support counts, science diagnostics, and an interactive map/dashboard. These support inspection of *what the individual products measured and where data are valid*. They are not, by themselves, a cumulative displacement history, a validated accelerating-motion detector, or a calibrated landslide/glacier-collapse alert.

Before claiming an AOI-wide scientific result, we still need the submitted AOI to be carried through a tested pair-network inversion, candidate/local-floor analysis, per-track geometry assessment, and (only when justified) inverse-velocity gate. Each stage must expose `PASS`, `FAIL`, `INSUFFICIENT_DATA`, and `SKIPPED_UNSUPPORTED_AOI` distinctly.

## Immutable scientific provenance pins

- Dynamic WKT product processing: `10639a916c9829850775410b3ed7de62e527770d`.
- Fixed source-AOI streaming/baseline and extended science: `ab547ecc82bcc4d6ccef545a59852536c2beacc6`.
- Historical GUNW feasibility workflow: `77cc9646cfa46d3aff3669d351912f984cf67aa3` from a different repository fork.

Do not quietly substitute one pin for another. Updating a pin is a scientific/provenance change and requires reviewing output schema, AOI assumptions, regression baselines, and tests.

## Current work item

The dispatcher is being corrected in this feature branch to invoke the merged `main` reusable workflow, with an automated contract test so this routing issue does not return. The remaining science generalization is documented in `SCIENCE_ENGINE_ARCHITECTURE.md` and tracked in `SCIENCE_ENGINE_CHECKLIST.md`.
