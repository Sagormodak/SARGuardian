# Exact-author P05023 acquisition workflow audit — 2026-10-24

## Scope

This audit covers the direct NASA CMR HDF5 data-link resolver, exact-author acquisition runner, workflow consent gate, grid/receipt hardening, offline contract tests, CI validation and the boundary between metadata readiness and raw-source acquisition.

Repository: moshiour0/SARGuardian-backend
Branch: feat/know-place-analysis
Validated branch head at time of check: 2fddad5fbd3d66fc9ade40da41ce829bfabf7610
Main baseline: 2218dfeb73353080d8d94bd733d9e7bd9a848886 (unchanged)

## Validation evidence

- Isolated validation run: https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988024
- Result: 204 tests passed in 4.87 seconds.
- Seven workflow YAML files parsed, including know-place-author-exact-replay.yml.
- actionlint v1.7.12 release checksum verified and semantic workflow validation passed.
- Both validation jobs succeeded.

## Live CMR access evidence

The live non-downloading catalogue/access workflow logged:

- AUTHOR_CMR_CATALOG_GATE=PASS
- AUTHOR_EXACT_PRODUCTS_CONFIRMED=5/5
- AUTHOR_EXACT_CMR_DATA_URLS_CONFIRMED=5
- SOURCE_DOWNLOADS=0

The artifact know-place-author-exact-live-cmr-access-evidence is attached to the same validation run. Artifact SHA-256 digest recorded by GitHub: b81e1d2b1ba4c78a90753ed84fd1ff1da0ff72c886bf46f31ffdd99928a1c4e9.

Interpretation: there is a unique direct HDF5 data URL for each of the five expected author P05023 products under the pinned CMR collection, passing the trusted-host, exact path, exact file-name and one-link contract. A URL is not the payload. No raw HDF5 byte count or SHA-256 was acquired by this metadata-only step.

## Acquisition runner changes

1. Re-checks explicit consent before starting download-and-analyze mode.
2. Selects direct CMR HDF5 data links only when exact producer identity, P05023 release, collection concept ID, trusted ASF/earthdatacloud host and expected granule path all match.
3. Performs authenticated metadata-only preflight for all five products before downloading any payload.
4. Checks disk headroom before raw downloads.
5. Computes SHA-256 only after each downloaded file is a valid HDF5 container and its exact GOFF identity, dates, EPSG, 80 m posting, expected 4311 x 4230 dimensions and shared source coordinate axes pass validation.
6. Writes acquisition receipts to durable derived-output paths as work proceeds, so partial download/preflight failures leave inspectable evidence.
7. Records the source-manifest SHA-256 into configuration provenance.
8. Only marks scientific analysis complete if the child process exits zero, structural status is PASS, and analysis status is SCIENTIFIC_METRICS_COMPUTED. Partial or failed reports remain failures.
9. Keeps raw HDF5 outside the derived bundle. The workflow uploads the derived evidence bundle and verifies Drive receipts before removing temporary raw files.

These tests and gates validate software contracts; they do not establish source-byte identity until the actual workflow downloads the five files.

## Consent and workflow execution

The raw workflow is manual-dispatch-only and requires the exact consent_marker value [run-know-place]. It also fails before raw-source acquisition if Earthdata authentication or Google Drive retention secrets are absent.

Run 40058988016 registered and checked the new workflow but skipped the acquisition job because no exact marker was provided. The existing legacy workflow run 40058988057 also skipped its expensive analysis. Across these runs the source payload download count remains zero.

The connected GitHub tool available in this session exposes run/artifact inspection and branch content operations but not a workflow_dispatch action. Therefore a manual raw run was not started from this session. It must be initiated in the GitHub Actions UI with the exact consent input and configured Earthdata/Drive secrets.

## Scientific status

- Raw source payload count: 0/5.
- Raw source SHA-256 count: 0/5.
- Paper reproduction: BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED.
- Hazard detection: NOT_EVALUATED.
- No operational hazard alarm or validated prediction-skill claim is produced.
- No changes were written to main.

## Next operations

1. Manually dispatch know-place-author-exact-replay.yml with consent_marker set exactly to [run-know-place].
2. Retrieve the five HDF5 payloads through the exact CMR links and record actual byte counts/SHA-256 values.
3. Inspect identity, metadata, axis directions/units, grid bounds, incidence/LOS/along-track fields and the vertical-height-reference mismatch before interpreting dE/dN.
4. Run the scientific analysis and audit every output/status, then validate source-mask and metric parity against authoritative author data.
5. Verify the Google Drive artifact and receipt; only then can raw files be deleted from the ephemeral runner.
6. Keep paper reproduction blocked until source-byte and implementation parity have independent support.
