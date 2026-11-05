# Know Place Analysis — consolidated finishing gate (2026-10-25)

## Decision

**Engineering / derived-only verification: PASS.**  
**Numeric reproduction of reported output fields: 95/95 at archived precision across direct/conditional author-site/P1/P2/core checks plus the source-inspired displacement-null output reconstruction.**  
**Full scientific method reproduction: PARTIAL, not complete.**  
**Hazard detection: NOT_EVALUATED.**

This report intentionally separates numerical agreement from source-code identity and actual detection skill.

## Verified evidence

| Gate | Result | Primary evidence |
|---|---|---|
| Exact author inputs and acquisition provenance | 5/5 exact P05023 source products; hashes/grid checked; raw files deleted after verified derived retention | [Run 40170290176](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40170290176); retained artifact digest SHA-256 a25bb86069585b2cb023f5fbe889e160ae1749b0b61172ce4f8d1d9953c76682 |
| Site-series and selected author site/polygon controls | 65/65 checks, 0 mismatches | Run 40170290176 |
| P2/local-mean table fields | 15/15, 0 mismatches at author table precision | Run 40170290176 |
| Full-footprint aggregate rasters | 3/3 pass: flagged-epoch raster exact across 18,235,530 cells; two aggregate float rasters have zero finite-mask/value mismatches over 4,008 finite cells | [Footprint parity report](FOOTPRINT_SCREEN_PARITY_RUN17_20261025.md) |
| Footprint candidate inventory / Table S7 | All 106 candidate rows and all 101 Table S7 numeric rows pass declared tolerances; 0 missing/extra rows, 0 numeric mismatches, 0 ranking inversions over 5,564 comparisons | Footprint parity report |
| Retained crown-mask/source-provenance audit | Five pairs; 323-cell reconstructed mask each; XOR=0 for saved-mask/grid/endpoint checks; exact author editable-vector identity remains unverified | [Run 40200875570](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40200875570); [crown audit](CROWN_MASK_AUDIT_20261025.md) |
| Displacement-null numeric output | 15/15 fields match at stored precision across five pairs: crown median, null median and percentile | [Run 40219393283](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283); [machine-readable artifact 12608431799](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283/artifacts/12608431799); [JSON summary](DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.json) |
| Latest isolated code/workflow validation | **281 passed**; all 11 Know Place workflows plus dispatcher parsed; pinned actionlint checksum and semantic validation passed | [Run 40221064296](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40221064296) |
| Latest five-pair raw replay authorization gate | Consent-check job passed; expensive science job **SKIPPED**; this gate downloaded zero raw HDF5 | [Run 40221064385](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40221064385) |
| Repository isolation | Main SHA remains 2218dfeb73353080d8d94bd733d9e7bd9a848886; no merge/write to main | Rechecked at finish |

## Scientific status boundary

### What the numeric evidence establishes

The five exact P05023 author input products were used in the previous explicitly authorized Run 40170290176. That run matched the selected site-series controls, all 15 P2 fields and the numeric full-footprint raster/inventory comparisons described above. A separate derived-only reconstruction of the five deposited displacement GeoTIFFs now matches the 15 displacement-null numeric fields at their published precision, using a fixed seeded disk/support policy. No source parameters were selected by repeatedly tuning toward individual published values.

### What is not established

1. **Original displacement-null source/draw identity:** the reviewed Zenodo archive contains tables/displacement_null.json and sibling coherence-null code, but no displacement-specific generator or original draw/rejection history. The reconstructed accepted counts and draw-vector hashes belong to our deterministic reconstruction; they are not claimed as the author's original draws. Numeric agreement is verified; exact source/draw identity is not.
2. **Crown source vector/golden mask identity:** the published crown rectangle maps consistently to a 323-cell mask on the retained native grid, but the author's original editable vector or golden raster mask was not supplied/verified.
3. **Glacier overlay:** exact RGI 6.0 polygon source assets/hashes are absent from the inspected author archive; glacier, RGIId, and d_glac_m attribution columns remain unverified.
4. **Terrain input byte provenance / vertical reference:** the prepared terrain and source processing path were replayed, but original terrain-tile byte identity and the DEM-to-radarGrid height-reference mismatch are not resolved. The analysis deliberately does not silently apply a datum correction to force numeric agreement.
5. **Independent detection skill:** no independent labelled event/control benchmark has been scored for event-wise precision/recall, false-alarm rate, lead time or prospective warning value. Hazard detection remains NOT_EVALUATED; operational warning remains NOT_IMPLEMENTED.

## Release criteria and next step

- The derived-only numeric benchmark and engineering CI are closed for the evidence stated in this report.
- Full scientific reproduction is **not** declared complete while original null-generator identity, original crown mask, exact RGI6 overlay and terrain provenance remain unresolved.
- Do not treat the candidate screen, ranking percentile or post-hoc source measurements as an operational landslide/glacier-collapse alarm.
- The source replay workflow remains fail-closed: without the explicit [run-know-place] authorization marker, GitHub Actions validates the gate and skips the expensive raw GOFF replay. The latest consent-gate result confirms that no new raw payloads were downloaded.
- Keep all work on feat/know-place-analysis; do not merge to main as part of finishing documentation.


## Branch-tip refresh — 2026-10-26 (Asia/Dhaka)

- Latest isolated validation: [Run 40221064296](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40221064296), 281 tests passed with all 11 workflows plus dispatcher parsed, pinned actionlint checksum verified and semantic validation passed.
- Latest raw-replay consent gate: [Run 40221064385](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40221064385), consent check passed and expensive analysis was skipped. No raw HDF5 payload was downloaded by the gate.
- Main SHA remains `2218dfeb73353080d8d94bd733d9e7bd9a848886`; no changes to main.
- Numeric Table S4 comparison is 95/95 at published precision when including the source-inspired displacement-null reconstruction. Original null-generator/draw identity, exact original crown mask, RGI 6.0 overlay and original terrain-byte provenance remain unverified. Full scientific reproduction is PARTIAL; hazard detection remains NOT_EVALUATED.
