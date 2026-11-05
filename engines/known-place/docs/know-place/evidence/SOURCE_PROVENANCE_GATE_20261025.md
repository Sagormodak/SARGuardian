# Exact-author source-manifest and cleanup-receipt gate — 2026-10-25

## Decision and scope

**Gate status: PASS for pinned-manifest structure and retained cleanup-receipt consistency tests.** This adds a fail-closed check to the retained-derived artifact audit. It does not re-read deleted raw GOFF bytes, and it does not elevate the project's paper-reproduction or hazard-detection status.

The inspected Run #17 artifact is [workflow run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), artifact `know-place-author-exact-40170290176-1.zip`. The contained source manifest SHA-256 is `99fbc858116fa67e88c67ce6d33139a2df53bb56ca3a725780bb508c918d9a5b`; the cleanup receipt SHA-256 is `a2ed0bf06a564e3ba8b4cd2e0421656473fac297f08307c278b2c2e9dcc8bf49`.

## What the code now pins and checks

The checker requires all five expected source rows in chronological order, exact interval and source filename, exact CMR granule concept ID, exact `P05023` release, collection `C2854341702-ASF`, collection name `NISAR_L2_GOFF_PROVISIONAL_V1`, provisional maturity, and the expected granule stem. It rejects a historical `X05026` filename substitution.

Each row must contain the previously recorded byte count and SHA-256, with a unique 64-character lowercase hexadecimal SHA-256; download, HDF5-container, byte-count, content, grid, and identity validations must be PASS. The pinned grid contract is 4311 × 4230, EPSG:32645, x posting +80 m, y posting −80 m, the recorded x/y extent, HH polarization and `layer2`. Identity-check expected/actual fields must agree for filename, granule stem, release, both dates and EPSG.

The cleanup receipt must hash the exact source-manifest bytes, affirm that the manifest was verified, and tie each deletion row to that source row's exact filename, byte count and SHA-256. It must report five source hashes verified before deletion, five raw HDF5 files before deletion, five deleted, zero remaining, no raw-HDF5 upload, and PASS for remote derived-bundle and upload-receipt-copy verification.

These checks validate the **retained manifest/receipt chain**. They do not cryptographically re-hash the original raw payloads because those payloads were correctly removed after retention verification. The earlier acquisition run's source-byte hashes remain the acquisition evidence; the new regression gate ensures those pins cannot be silently replaced by mismatched manifest or delete-receipt rows.

## Adversarial regression coverage

The new fixture tests require audit failure for:
- missing or duplicated product SHA-256;
- wrong pair interval, source collection, grid-validation status or byte count;
- replacement of the expected `P05023` filename by an `X05026` filename;
- a modified source-manifest SHA in the cleanup receipt; and
- a modified per-product SHA in the deletion receipt.

Validation result: [run 40199955962](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40199955962), commit `27ecf27d290f3b0dd8c3c1a4da7df5f787924a94`: **276 tests passed in 4.80 seconds**, Python compilation passed, nine workflow YAML files plus the dispatcher parsed, and pinned actionlint v1.7.12 checksum and semantic workflow validation passed. Live ASF/CMR checks were metadata-only and downloaded zero raw payloads.

The matching consent gate [run 40199956018](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40199956018) succeeded, while `Validate inputs and analyse five exact GOFF pairs` was **SKIPPED** because this work did not supply the explicit `[run-know-place]` marker. No new raw product was downloaded.

## Scientific status remains separate

- Crown-mask retained-array/source-grid consistency: PASS; original author editable vector/golden-mask parity: **UNVERIFIED**.
- Displacement-null sampler parity: **UNVERIFIED**; do not tune independent reconstruction parameters to force the published percentile.
- Whole-paper reproduction: **PARTIAL**, not reproduced.
- Hazard detection: **NOT_EVALUATED**.
- Repository `main` remains at `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no merge or write to main.



## Real retained-artifact verification — 2026-10-25

- Actual retrospective audit [Run #40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570) completed **PASS** against the real Run #17 artifact plus the author archive with frozen byte count/SHA-256. The five product rows, source-manifest hash, five deletion-receipt rows and retention conditions are consistent.
- The derived-only artifact contains 0 raw HDF5 members in both outer and nested bundles. The audit's five-pair grid/mask checks and matching displacement/coherence counts passed. It did not re-read or re-hash deleted raw HDF5 bytes.
- Full report: `docs/know-place/evidence/RETAINED_RUN17_CROWN_AUDIT_20261025.md`; JSON output is stored as workflow artifact `know-place-real-retained-crown-audit` (ID 12601033322).
- Paper reproduction remains partial, the original editable author-vector/golden-mask match remains unverified, displacement-null sampler parity remains unverified, and hazard detection remains `NOT_EVALUATED`.
