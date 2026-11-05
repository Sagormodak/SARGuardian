# Crown-mask / source-grid consistency audit — 2026-10-25

**Scope:** retained derived-only Run #17 artifact plus the SHA-256-pinned author Zenodo archive. No raw NISAR HDF5 is read. The audit compares the published WGS84 crown with independent inverse-projection of native-grid cell centres, the saved endpoint/searchsorted crop, and the site and halo diagnostic arrays.

## Inputs and integrity
- Source run: [40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), artifact ZIP 18,313,236 bytes; SHA-256 a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682.
- Author archive: 183,389,034 bytes; SHA-256 002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3, matching the pinned archive.
- Outer and nested ZIP CRC checks pass; both contain zero raw HDF5 members. Source manifest pins five P05023 payloads, and cleanup/Drive receipts pass.
- Native grid: 4311 × 4230; EPSG:32645; affine (80, 0, 126720; 0, -80, 3347280); 80 m posting. Site crop is rows [2675,2748), columns [2827,2907), shape 73 × 80.

## Mask results
Published crown bounds: 85.5245–85.5400° E, 28.2847–28.2970° N. Reference box: 85.500–85.565° E, 28.265–28.318° N.

For every one of the five pairs, the site mask has 323 cells and the halo diagnostic mask has 323 cells. All are exact: site-vs-geographic XOR=0; site-vs-endpoint-crop XOR=0; diagnostic-vs-geographic XOR=0; site-vs-diagnostic global source-grid XOR=0.

| Interval | Displacement-valid n | Coherence-valid n_px |
|---|---:|---:|
| 2026-06-20 → 2026-07-02 | 283 | 302 |
| 2026-07-02 → 2026-07-14 | 294 | 299 |
| 2026-07-14 → 2026-07-26 | 296 | 302 |
| 2026-07-26 → 2026-08-19 | 292 | 298 |
| 2026-08-19 → 2026-08-31 | 195 | 202 |

The displacement counts match field n in tables/nisar_pot_series.json; the coherence counts match n_px in tables/polygon_null.json. They are distinct estimands, so 292 and 298 for 26 July–19 August are not a disagreement.

## Regression-fixture correction
The generic geometry test previously used smaller crown bounds 85.525000° E and 28.285000° N. On the pinned crop, that stale rectangle selects 306 rather than 323 cells and omits 17 western-edge cells (5.26%). The fixture was corrected to the published bounds. This does not alter historical runs or the pinned author-profile runtime constants.

## Interpretation
**Audit: PASS for retained-mask/source-grid self-consistency.** Three independent comparisons give zero mask differences, and both valid-pixel estimands match their relevant published rows.

**Original author-vector/mask parity remains UNVERIFIED.** The author archive lacks an editable original vector or golden pixel mask. The audit does not prove full-paper reproduction or hazard-detection skill. Paper status remains PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED; hazard detection remains NOT_EVALUATED.

Reproduce with tools/know_place/crown_mask_audit.py, the retained source artifact, and the pinned author archive. Machine-readable summary is in CROWN_MASK_AUDIT_20261025.json.


## Follow-up source-provenance gate — 2026-10-25

The source manifest and post-delete cleanup receipt now have a dedicated fail-closed regression gate. It pins the five exact P05023 source identities, expected source byte counts and SHA-256 values; checks HH/layer2/native-grid and identity-validation fields; and ties the receipt's manifest hash and five deletion rows to the manifest. Adversarial fixtures cover missing/duplicate hashes, incorrect interval/grid/collection/byte count, an X05026 filename substitution and receipt tampering. Validation [40199955962](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40199955962) passed **276 tests**.

Important scope limit: these are manifest/receipt consistency checks. The CI validation downloaded no raw HDF5 and does not re-hash bytes that were deleted after Drive-retention verification. Original author-vector/golden-mask parity remains unverified; paper reproduction remains partial; hazard detection remains not evaluated. Full evidence is recorded in [SOURCE_PROVENANCE_GATE_20261025.md](SOURCE_PROVENANCE_GATE_20261025.md).


## Real retained-artifact verification — 2026-10-25

The new CI workflow [Run #40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570) ran this auditor against the actual retained Run #17 artifact and the full SHA-256-pinned author archive. Result: **PASS**, five intervals, all mask XOR comparisons zero, all displacement/coherence valid-count checks match their corresponding published table fields, and zero raw HDF5 members in the outer or nested archive. Machine-readable report is preserved as workflow artifact `know-place-real-retained-crown-audit` (ID 12601033322). This is stronger than synthetic-only test coverage but remains a retained-array/source-grid consistency audit, not original author-vector/golden-mask identity. See [the full real-artifact evidence note](RETAINED_RUN17_CROWN_AUDIT_20261025.md).
