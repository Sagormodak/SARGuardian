# Independent recheck of the author-exact replay artifact — 2026-10-25

## Scope and provenance

This note records a read-only inspection of GitHub Actions artifact `know-place-author-exact-40114703362-1`, artifact ID `12567509703`, from run [40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362). The artifact was downloaded again and its SHA-256 independently recomputed as:

- Artifact archive SHA-256: `d49b6aa10da27138de6b8b8f2af6a4b5d3ffd86a8ccb87cef7765e3c597a0b59`
- Archive size: 830,510 bytes
- This matches the digest advertised by GitHub Actions for that artifact.
- No raw `.h5` or `.hdf5` file is present in the artifact, or inside `author-exact-derived-results.zip`.

## Source-byte integrity

The included `author-exact-source-manifest.json` records five exact author release `P05023` GOFF granules, each with `download_status=PASS`, a 64-character SHA-256, `grid_validation_status=PASS`, and HDF5 identity checks passed. All five grids are 4311 × 4230, EPSG:32645, 80 m posting.

| Interval | Source bytes | SHA-256 |
|---|---:|---|
| 2026-06-20 → 2026-07-02 | 1,090,519,040 | `d3670f0504576feac52f75a7e8f0ff12f5f5c2ef676a0329a16f66cb91300f05` |
| 2026-07-02 → 2026-07-14 | 1,090,519,040 | `8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c` |
| 2026-07-14 → 2026-07-26 | 1,092,616,192 | `ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313` |
| 2026-07-26 → 2026-08-19 | 1,101,004,800 | `45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f` |
| 2026-08-19 → 2026-08-31 | 1,098,907,648 | `4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371` |

Total raw source bytes recorded: **5,473,566,720**. All five source hashes are distinct. This validates the historical run's manifest claims; it does not mean those raw files are present in the artifact now.

## Derived-output integrity and retention evidence

- Derived bundle SHA-256: `c82f68a11ff00f22aa5cb280116c319948c14a17bf07c8d7d3795c0f2c9aa28e`
- Derived bundle size: 414,897 bytes.
- Both included Drive receipts report `remote_verification=PASS` and `raw_product_uploaded=false`.
- Both historical receipts also report `raw_source_deleted=false`. They are pre-cleanup upload receipts and must **not** be presented as proof that deletion was durably attested.
- The current branch's later cleanup hardening is designed to re-hash the five raw files, verify the remote derived bundle and receipt copy, delete the exact five raw files, confirm none remain, then upload and verify `author-exact-raw-cleanup-receipt.json`. That new post-cleanup receipt path has not yet been exercised by a fresh explicitly consented run.

## Scientific result and limits

The archived report reports the target interval 2026-07-26 → 2026-08-19 as:
- 292 valid crown pixels under this run's bounding-box crown approximation;
- median horizontal magnitude 0.9660632427 m;
- mean-vector magnitude 1.7222463853 m;
- mean-vector azimuth 277.793386° clockwise from north;
- median magnitude rate 0.0402526351 m/day;
- median directional coherence R=0.8528504684.

The report explicitly labels this comparison `NOT_COMPARABLE_EXACT_CROWN_GEOMETRY_UNVERIFIED`. These values are numerically close to selected paper-reported values but are **not proof of paper reproduction**: exact crown geometry, control sampling, author-method parity, terrain vertical datum, and golden-output parity remain unresolved. The artifact's analysis-status file still carries the earlier generic label `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; treat this artifact as immutable historical evidence, not as the current corrected status receipt.

- Paper reproduction: `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED` as the current code/documentation gate; the old artifact's status label is stale.
- Hazard detection: `NOT_EVALUATED`. No operational hazard alarm was produced.

## Latest workflow checks

- Latest isolated validation [40121243012](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40121243012), branch commit `56ef9f52977a7ac6a0c314b8560bfe4ff27743b0`: **224 tests passed in 2.58 s**, all eight Know Place workflows plus the branch dispatcher parsed as YAML, pinned actionlint v1.7.12 checksum and semantic validation passed.
- Its live CMR checks confirmed exact-author CMR/data-link identity for 5/5 while recording `SOURCE_DOWNLOADS=0`; this was a metadata/catalog check, not a raw-data run.
- Latest legacy replay run [40121243034](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40121243034) completed its consent gate and skipped the acquisition job. It downloaded no raw products.
- Main remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no merge or write to main.

## Next steps

1. Manually dispatch `.github/workflows/know-place-author-exact-replay.yml` on `feat/know-place-analysis` with the exact consent input `[run-know-place]` and valid Earthdata + Google Drive secrets to exercise the post-cleanup receipt path. Do not infer consent from an earlier request or push.
2. Independently inspect the new post-cleanup receipt and remote Drive verification.
3. Resolve exact author crown geometry and control sampling; run golden-output and full-footprint screen parity tests.
4. Resolve the DEM/geometry vertical-reference provenance before claiming exact geometry parity.
5. Keep hazard detection marked `NOT_EVALUATED` until separately validated detection evidence exists.
