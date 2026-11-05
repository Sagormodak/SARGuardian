# Retained Run 17 crown/source audit — real-artifact verification — 2026-10-25

## Gate result

**PASS — the current crown-mask/source-provenance auditor passed against the real retained Run #17 artifact, not only synthetic fixtures.** This is a retrospective audit of an existing derived-only artifact. It did not download or read raw NISAR GOFF HDF5.

- Audit workflow: [Run #40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570), commit `df63a16b0997e1f32b006ec183a672eeb62b6f6d).
- Original source artifact: Run [40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176), GitHub artifact ID `12589719900`, size 18,313,236 bytes, original artifact digest `sha256:a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682`.
- The Actions download extracted 41 retained artifact files and the workflow repacked those files for the ZIP auditor. Repacked audit input: 18,286,662 bytes, SHA-256 `9936740be69bc2268311fabbb26a8e0218ccbbb4cdcb13101d6606e54f70dc54`. This repacked ZIP digest is distinct from the original GitHub artifact digest by construction; the report states both identities separately.
- Raw HDF5 members in the extracted outer artifact: **0**. Raw HDF5 members in the nested derived bundle: **0**.
- Author source archive: 183,389,034 bytes, SHA-256 `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`, exactly matching the frozen author archive hash used by the audit.
- Output artifact: [`know-place-real-retained-crown-audit`](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570) (artifact ID `12601033322`, digest `sha256:f5aa5a397f49014d8eaf8cb62a34c0b785b57da61b51ec6b9b94c6f2a6db262e`). Machine-readable report name: `crown-mask-real-artifact-audit.json`.

## Actual five-pair results

All five intervals returned `status=PASS`. The common source-grid mask SHA-256 is `b07dc264dab6a36ea6133e8f64edee1421315864f3558eb3166fb334b6640c7c`; each pair has 323 crown cells and 323 diagnostic cells. Site-vs-geographic, site-vs-endpoint-crop, diagnostic-vs-geographic and site-vs-diagnostic global XOR counts are all zero for each pair.

| Interval | Displacement-valid cells / published `n` | Coherence-valid cells / published `n_px` |
|---|---:|---:|
| 20 Jun–2 Jul | 283 / 283 | 302 / 302 |
| 2–14 Jul | 294 / 294 | 299 / 299 |
| 14–26 Jul | 296 / 296 | 302 / 302 |
| 26 Jul–19 Aug | 292 / 292 | 298 / 298 |
| 19–31 Aug | 195 / 195 | 202 / 202 |

These are two separate estimands, not interchangeable counts. In particular, the target pair's 292 displacement-valid cells and 298 coherence-valid cells are both correct against their corresponding archived tables.

## Geometry-area consistency (supporting check, not a golden mask)

The rectangle defined by the paper's published bounds (85.5245–85.5400° E, 28.2847–28.2970° N) has WGS84 ellipsoidal geodesic area **2.072644 km²** and EPSG:32645 planar area **2.072046 km²**, both rounding to the stated **2.07 km²**. This supports the rectangle interpretation of the published coordinate bounds.

It does **not** independently prove byte-for-byte identity to an original author vector or a saved author golden mask. The author archive does not contain an editable original crown vector/golden source-grid mask; therefore that separate parity assertion stays **UNVERIFIED**.

## CI / safety status on this commit

Validation [Run #40200875500](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875500) passed **276 tests in 2.69 s**, parsed all ten Know Place workflow files plus the branch dispatcher, and passed the pinned actionlint v1.7.12 checksum and semantic validation. Live ASF/CMR checks were metadata-only.

The paired raw-replay gate [Run #40200875484](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875484) succeeded while `Validate inputs and analyse five exact GOFF pairs` was **SKIPPED**. No new raw GOFF payloads were downloaded.

## What this does and does not close

- Retained artifact structure and mask/source-grid consistency: **PASS**.
- Five exact source identities/byte hashes recorded by the previous consented acquisition and matched to manifest/delete receipts: **PASS as a provenance chain**. This audit does not re-hash deleted raw HDF5 bytes.
- Original author editable polygon/golden-mask parity: **UNVERIFIED**.
- Exact displacement-null sampler parity: **UNVERIFIED**; no result-driven tuning.
- Full-footprint runner numeric parity: still requires a raw exact-author replay with explicit `[run-know-place]` authorization.
- Whole-paper reproduction: **PARTIAL**, not complete.
- Hazard detection: **NOT_EVALUATED**. This paper itself reports a ranking rather than a calibrated pre-failure detection; these output numbers are not a probability of failure.

The branch remains `feat/know-place-analysis`; `main` stays at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.
