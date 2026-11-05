# SARGuardian raw-HDF5 dependency and parity plan

Status: implementation in progress.
Baseline authority: the user-supplied SARGuardian-main.zip, especially REPRODUCE_RESULTS.md, src/, and committed outputs/*_source.csv.
Operational repository: moshiour0/SARGuardian-backend.
Safety rule: do not delete a temporary raw HDF5 until required raw-dependent outputs and provenance are validated, uploaded, and remotely verified. The two-product pilot passed, but a failed 33-product run showed source-availability gaps; do not repeat the expensive full run until the selected UR granules pass the new early availability preflight.

## 1. Dependency inventory

### Direct HDF5 readers
- src/gunw_reader.py / read_gunw(): opens GUNW HDF5 and reads unwrapped phase, matching coherence, connected components, mask, ionosphere phase screen, x/y coordinates, projection and wavelength. It performs quality/AOI/reference logic and emits statistics and clipped GeoTIFF through --read / --batch.
- src/goff_reader.py / read_goff(): opens GOFF HDF5 and reads range/azimuth offsets, correlation, SNR, variance, coordinate axes and projection. It applies quality/AOI/reference/deramp logic and emits statistics and clipped GeoTIFF.
- src/timeseries.py --dir: discovers raw .h5 and calls read_gunw/read_goff again. A merged stats CSV alone is not equivalent to this path; time-series replay must preserve per-product raster precision, product identity and the documented reference/inversion options.
- src/geometry_merge.py / los_from_product(): opens GUNW metadata/radarGrid LOS unit vectors, incidence angle, coordinates/projection and identification/lookDirection. It is a direct raw dependency for product-native LOS queries. The documented source-AOI bound chain does not call it, so derived-only retention must not claim arbitrary future LOS queries remain available unless a compact equivalent is exported or an archive is retained.

### Raster/CSV downstream stages
- src/troposphere.py consumes exported GeoTIFF and DEM; source-ZIP baselines: outputs/troposphere_gunw_source.csv and outputs/troposphere_goff_source.csv.
- src/local_floor.py consumes exported GeoTIFF plus candidate CSV; baseline outputs include local_floor_candidates.csv and local_floor_phase_candidates.csv.
- src/common_ref.py consumes GOFF GeoTIFF and candidate metadata; baseline common_ref_summer.csv.
- src/bound.py consumes previously derived source CSVs; baseline bound_source.csv.
- src/inverse_velocity.py consumes reconstructed GOFF time series and GOFF floors; event cutoff must be 2026-08-26.
- Candidate-4 common-datum time-series must be reconstructed using the fixed-lattice exports and common-reference logic, not per-pair auto-reference values.
Any newly added output that calls a raw-HDF5 helper must be added to this map before cleanup can be approved.

## 2. Baseline facts

- gunw_stats_source.csv has 15 rows / 15 unique GUNW products.
- goff_stats_source.csv has 18 rows / 18 unique GOFF products (HH/layer2; includes routine and urgent-response products).
- Product-level validation must compare the complete relevant CSV row with the matching source-ZIP baseline, including fields and row identity. Only GDAL-sensitive export_mb gets a documented relaxed tolerance.
- Available downstream baselines include ts_goff_source.csv, both troposphere CSVs, local_floor_candidates.csv, local_floor_phase_candidates.csv, common_ref_summer.csv, ts_goff_cand4_common.csv and bound_source.csv.
- The supplied ZIP has no ts_gunw_source.csv baseline. If generated, it must be labeled generated / no committed baseline, not counted as source-ZIP parity PASS.
- Historical exported GeoTIFFs are not committed in the ZIP. Validate completeness, readability, source tags, bands, CRS, affine transform, dimensions, nodata/valid pixels and common fixed-lattice invariants; do not claim pixel-for-pixel comparison against a raster that is absent.

## 3. Required order and deletion gate

1. Pin and record the exact science commit and validate its product CSV inventory before downloading any granule.
2. Download one raw product at a time; record original bytes and SHA-256, run AOI grid preflight and inventory all source datasets/attributes.
3. Run the original single-product GUNW or GOFF reader with the matching batch settings. Export every raster needed by the declared downstream chain.
4. Before deletion, compare this product's CSV row to its exact source-ZIP baseline row; verify every export is present/readable and has expected grid, CRS, bands, source identity and valid data. Write a machine-readable validation report.
5. If a declared result depends on raw-only information (including product-native LOS geometry), export a validated compact representation or retain an explicit archive for that product. Never silently drop a dependency.
6. Upload derived files, inventory, preflight, source hash, parameters and validation evidence to the product-specific Drive run folder. Verify remote sizes/checksums and ensure all required exports are represented in receipts.
7. Only after all checks pass, delete the runner's raw HDF5. For full-lossless mode, independently verify the remote archive and then delete the temporary archive. Upload and verify the post-cleanup receipt.
8. Aggregate all product artifacts in original baseline row order. Fail closed on missing/duplicate products or exports.
9. Re-run the combined downstream chain from compact outputs: GOFF/GUNW time series as required, inverse-velocity event cutoff, both troposphere reports, both candidate-floor tables, summer common-reference table, candidate-4 common-datum series and final bound.
10. Compare every available source-ZIP baseline with schema, identity, missing/extra row and numeric checks. Report PASS, FAIL, and SKIP_NO_COMMITTED_BASELINE distinctly. A full run must not pass when a required baseline comparison is missing/skipped.
11. Upload the final bundle, command logs, report, manifest, all product/cleanup receipts and actual Drive byte accounting. Separate product outputs from optional archive and run-level report storage.

## 4. Retention modes

- derived-only: do not retain .science.h5. Only the documented output chain and explicit compact sidecars are preserved; arbitrary future access to original HDF5 datasets is not preserved.
- full-lossless: retain a logically lossless HDF5 dataset-tree archive, compare raw/archive reader results, and still retain all derived outputs. The archive consumes near-raw storage and must remain an explicit option, not be confused with derived-only output.

Storage accounting must be policy-aware: derived-only cleanup must require all derived files and their remote checksums, not an archive.

## 5. Live pilot, full-baseline result, and corrective work

- [x] The streaming workflow defaults to `derived-only`; `full-lossless` remains explicit.
- [x] Product-level CSV validation and GeoTIFF validation run before the raw-HDF5 deletion gate.
- [x] Downstream replay includes both troposphere reports and the candidate-4 floor/common-datum chain.
- [x] The workflow pins the declared scientific commit and checks it before processing.
- [ ] The supplied source ZIP has no `ts_gunw_source.csv` baseline; generated GUNW time series must remain explicitly unbaselined.
- Historical context: run #15 failed the stale science-commit guard; run #19 GUNW succeeded but GOFF Drive upload hit HTTP 502.
- Validation pilot [run #21](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39493497798) completed successfully on the branch after fixing the prior JSON newline bug.
- Full-baseline [run #22](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39495122444), pinned to the expected science commit, selected all 33 products but finished FAIL: 28/33 validated; 5 downloads failed. The two exact source-AOI primary CSV comparisons reported zero field mismatches among available rows but were missing 2 GUNW and 3 GOFF identities. The downstream parity chain did not complete, so this run does not establish full baseline parity.
- Run #22 product-download failures:
  - GUNW-006 and GOFF-020: transient `ConnectionError` while contacting the Earthdata Login token endpoint. Bounded session retry was added.
  - GUNW-015, GOFF-032, and GOFF-033: `DIRECT_PRODUCT_HTTP_STATUS_404` on the standard production URL. These names are `UR` (urgent-response) products and need their exact ASF catalog access URLs rather than the standard production bucket URL. The acquisitions are from late August 2026, and run #22 occurred on 2026-10-20; ASF documentation says UR products are kept in a separate bucket with a 30-day retention period. If the exact catalog URL now returns 404 or the exact granule has left the catalog, the raw bytes must be recovered from an independent archive to achieve the original baseline identity; retrying or substituting a different product cannot count as parity.
- 28 completed product jobs validated and remotely retained their derived outputs; cleanup receipts verified 28/33. Accounting from verified Drive receipts was 8,854,129 bytes across 252 unique remote files (about 0.008246 GiB), excluding the GitHub run-result bundle. The five failed jobs did not produce product-processing/cleanup receipts, and their raw download step never succeeded.
- [x] Added bounded retries for transient Earthdata/session and HTTP 429/5xx errors; added exact ASF catalog URL fallback for UR products and non-UR direct-URL 404s; added `--probe-only` to check exact source availability without downloading or writing raw data.
- [x] Added a full-baseline manifest preflight that checks every selected UR product before launching any of the 33 product jobs. It stops early with a sanitized error if a required historical UR granule is no longer retrievable, instead of spending most of an hour processing the other products first.
- [x] Product diagnostics now keep sanitized downloader root-cause lines, and aggregation attaches them to missing-product errors instead of reporting only that `product-processing.json` is absent. A follow-up audit found the log pipe captured stdout only while the downloader writes errors to stderr; the workflow now merges stderr into the tee log, with a regression test.
- [x] The updated downloader completed the replacement GOFF-033 product path in live run [#39524783921](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39524783921), including product validation, remote retention and cleanup. Its initial aggregation exposed the candidate-4 PR/UR stack bug, which is now fixed. This verifies the successful replacement-product path, but is not itself evidence that the separate full `resume_from_run_id` workflow has been exercised end-to-end.

## 6. Acceptance gates before processing all 33 products

- The two-product validation pilot passes and representative GUNW/GOFF product outputs match the source-ZIP baselines before cleanup.
- derived-only passes without a .science.h5 in the upload receipt and refuses cleanup for missing/wrong validation, exports or remote checksums.
- full-lossless remains independently supported with the raw/archive equivalence test.
- Aggregation handles archive-present/absent policies and measures Drive storage from verified receipts.
- Both troposphere outputs are regenerated and compared; every available required baseline is compared.
- Before a full-source run, every selected UR granule must pass the early exact-availability gate; then the full run must cover all 15 GUNW + 18 GOFF products, all required comparisons must pass, and all 33 product/cleanup receipts must verify before the final report can say PASS.

## 7. Change log

- [x] Re-open supplied source ZIP and map direct raw-HDF5 readers.
- [x] Confirm 15 GUNW + 18 GOFF baseline entries and inspect downstream outputs.
- [x] Re-read current streaming workflow and aggregate code.
- [x] Add this plan to the backend branch.
- [x] Add pre-cleanup per-product CSV/raster validation.
- [x] Add derived-only and full-lossless retention modes with policy-aware cleanup.
- [x] Add bounded network retries, exact ASF-catalog URL fallback, and a no-download source-probe mode.
- [x] Add a full-baseline UR availability gate before scheduling any product downloads.
- [x] Preserve sanitized downloader root-cause details in product diagnostic artifacts and aggregate failure reports.
- [x] Cover retry, UR routing/expiry, probe-only, workflow gating, and aggregation diagnostics with regression tests.
- [x] Update storage accounting and downstream parity, including both troposphere CSVs and candidate-4 floors.
- [x] CI on commit `dc6571d063c692759403b6278dc19879d7356814`: 145 passed, 1 skipped in the backend suite; 44 passed in the retention suite; workflow YAML and Python syntax checks passed.
- [x] Two-product live validation pilot passed (Run #39509946223); per-product baseline, remote-retention and cleanup gates passed.
- [x] Recover and validate the full baseline from existing verified artifacts in [artifact-only replay #39527193872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39527193872): 33/33 products, 33/33 cleanup evidence, storage accounting PASS, 12/12 committed downstream comparisons PASS, 0 field mismatches, and `BATCH_EQUIVALENCE_STATUS=PASS`. The replay did not download or reprocess raw HDF5.
- [ ] Independently exercise the full live `resume_from_run_id=39510497044` path once; this separate workflow mode is not claimed proven by artifact-only reassembly.


## 6. Run #39510497044: root cause and recovery

- Full baseline selected all 33 products and the exact ASF catalog preflight passed for all 3 UR granules. The actual source was discoverable; this was not an expired UR object or scientific mismatch.
- The first 32 product jobs passed per-product validation, Drive retention verification and cleanup receipts. GOFF-033 alone failed in the download step while rebuilding the Earthdata Login session. The captured error was a ConnectionError to urs.earthdata.nasa.gov/api/users/find_or_create_token, after the downloader's two in-process session attempts. Its exact UR granule had already passed the catalog availability probe.
- The aggregate deliberately failed closed: 15/15 GUNW rows, 17/18 GOFF rows, zero field mismatches for rows that existed, products_validated=32/33, cleanup receipts 32/33. No downstream replay was performed because one required GOFF baseline row was absent. Verified remote output accounting covered 32 products and 288 files (10,102,539 bytes).
- The updated workflow retries only marked transient Earthdata/network/selected HTTP failures in both UR preflight and the product download step (up to four attempts with bounded backoff); permanent HTTP 404 or local HDF5/validation failures stop promptly. Product download has a 90-minute step timeout. This addresses temporary outages without retrying known permanent errors indefinitely.
- Full-baseline execution also supports the resume_from_run_id input. Before skipping a product, it checks that both manifests agree on AOI, the pinned science commit, date window, retention profile, and the ordered product identities. Reuse additionally requires a PASS derived-output report, verified remote-retention receipt/folder, local stats/exports and provenance files, and a remotely verified cleanup receipt proving the raw runner copy was deleted. Failed or ambiguous checkpoints are scheduled again.
- The aggregation job merges artifacts from the failed run and the new attempt, and is designed not to replace a receipt-verified product checkpoint with a diagnostic-only artifact from a failed retry. Checkpoint artifacts are retained for 14 days.
- Recovery invocation for this failure: on the branch containing these changes, run full-source-baseline, keep the same 2025-01-01 to 2026-12-31 dates and derived-only retention, and set resume_from_run_id=39510497044. The expected plan is to reuse the 32 validated products and retry GOFF-033 only. The replacement GOFF-033 processing path subsequently completed in run [#39524783921](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39524783921). The corrected aggregation then passed all required report gates in artifact-only replay [#39527193872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/39527193872). The separate `resume_from_run_id` full live retry mode remains to be independently exercised.
