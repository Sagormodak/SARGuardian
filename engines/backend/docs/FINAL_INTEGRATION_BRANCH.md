# Final integration branch — AOI + pinned science

**Branch:** `feat/final-aoi-science-integration`  
**Base:** `feat/e2e-aoi-wkt-date-dashboard` (which already includes the pinned source-baseline work).

This is the integration branch to test before proposing a merge. Creating it does not by itself make SARGuardian a scientifically validated operational hazard detector.

## What is combined

- Dynamic AOI WKT acquisition discovery, inclusive date-window policy, NISAR product processing, per-product provenance and checks, retained exports, HTML dashboard and Drive upload remain in the AOI workflow.
- The fixed source-AOI streaming baseline, its 33-product inventory, existing parity checks, retention accounting and documented downstream Results 1–7 workflows remain in the streaming workflow.
- The previously disconnected `src/pixel_stack.py` and `src/candidate_check.py` entry points are invoked by `tools/run_export_science_diagnostics.py` using the retained GUNW exports. The adapter writes a structured `science-diagnostics.json` report and per-stage logs rather than replacing either scientific script with a new algorithm.

## Two scientific source pins are intentionally kept separate

| Path | Science commit | Why |
|---|---|---|
| Fixed source-AOI / committed baseline | `ab547ecc82bcc4d6ccef545a59852536c2beacc6` | The existing baseline suite enforces this exact revision and compares against the results committed with it. |
| Dynamic WKT / date-window workflow | `10639a916c9829850775410b3ed7de62e527770d` | This revision supplies the WKT-aware acquisition/readers and AOI-specific output metadata used by the dynamic workflow. |

Do not change either SHA independently without updating the related baselines and running the full source tests. A commit pin is part of provenance and reproducibility, not just a dependency version.

## Added diagnostics and their interpretation

### Per-pixel stack

For both workflows, the adapter finds retained PR GUNW GeoTIFFs, flattens them for the script's top-level input scan, verifies the actual scientific checkout SHA, and executes `pixel_stack.py --season all`. Its log records temporal support, each pixel fit's uncertainty, the spatial-noise null and whether a cluster survives that particular test. A surviving cluster is a candidate for cross-checking, not a confirmed landslide. Insufficient rasters, a failed stack or no detection are reported distinctly.

### Candidate screening

For the source-AOI baseline, candidate points are taken from `outputs/scar_candidates_source.csv`. The adapter derives each target's per-pair window measurements from the retained 2-band PR GUNW exports (band 1 LOS displacement, band 2 coherence; 11×11 target window; coherence threshold 0.3) and writes the line format expected by `candidate_check.py`. These are explicitly labelled as retained-raster window measurements, not as a direct `timeseries.py` execution. It can reject or leave a target inconclusive; it cannot prove motion.

For arbitrary WKT AOIs, the current `candidate_check.py` assumes the named `source`, `langtang`, or `lhende` AOI polygons. The integration therefore records candidate screening as `SKIPPED_UNSUPPORTED_CUSTOM_AOI` in that mode instead of applying the wrong polygon. Dynamic-WKT runs still get the per-pixel stack where usable multi-date GUNW support exists. Generalizing the candidate-checker's geometry contract is a separate scientific change and must include tests.

## Run controls

- The source streaming workflow defaults to `validation-pilot` (2 products) to avoid unexpected large downloads. Choose `full-source-baseline` to request the 33-product baseline and downstream scientific suite.
- The AOI/WKT workflow exposes an explicit polygon and date filtering mode. Its default dashboard `PASS` means acquisition, exact-AOI masking, provenance and structural checks passed; it is not independent geophysical validation.
- Download attempts, cleanup gates, checksum verification and Drive upload receipts remain separate from scientific interpretation. Do not loosen them just to get a green workflow.

## Acceptance gate before calling the branch ready to merge

1. The `SARGuardian AOI branch code validation` action must pass on this branch (compileall, YAML parse, dashboard JavaScript syntax and tool tests).
2. Run the WKT workflow on a small, documented pilot AOI/date range; inspect the summary, per-product evidence and science-diagnostics report.
3. Run `full-source-baseline` from the source streaming workflow; inspect pixel support, candidate outcomes, parity output and Drive receipts.
4. Review all `FAIL`, `WARNING`, `NO_DETECTION`, `NOT_MEASURABLE`, and `SKIPPED` statuses rather than reading only the top-level workflow conclusion.

A run may correctly return “no alarm” or “insufficient evidence.” The earlier source-baseline replay completed its technical stages but its inverse-velocity gates did **not** produce an alarm. A workflow success therefore must never be described as a demonstrated landslide prediction or as field-validated early warning.
