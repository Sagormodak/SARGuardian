# Responsive browser QA — retained Bhote Koshi P05023 interactive map

Date: 2026-10-26  
Branch: `feat/know-place-analysis`  
Renderer/workflow commit: `a6c5a4ed696e3066bf770ed5634339a9b655073d`

## Evidence links

- Successful map-render and retention workflow: https://github.com/moshiour0/SARGuardian-backend/actions/runs/40240016012
- Artifact ID: 12616437285
- Original measurement run reused, not repeated: https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596
- Isolated validation for the same code commit: https://github.com/moshiour0/SARGuardian-backend/actions/runs/40240016149

## Browser assertions

Headless Chromium passed all 16 existing desktop assertions with zero page errors. Four responsive viewport emulations passed, each with five layout assertions:

| Viewport | Result | Document/body width | Map element | Pair selector |
|---|---|---:|---:|---:|
| 360×800 mobile | PASS | 360 px | 306×440 px | 306 px |
| 390×844 mobile | PASS | 390 px | 336×464 px | 336 px |
| 768×1024 tablet | PASS | 768 px | 714×563 px | 714 px |
| 844×390 landscape | PASS | 844 px | 790×340 px | 790 px |

For each viewport, no horizontal overflow, a viewport-fitting map, usable map height, a visible pair selector and availability of the 2026-07-26 → 2026-08-19 interval all passed. The generated `browser-smoke.json` contains detailed layout measurements, media-query state, selected pair and checks.

## Defect and correction

The first mobile smoke runs exposed horizontal overflow and layout viewport expansion from 360 px to over 600 px. The source hash was a 64-character unbroken string. A local Chromium isolation test reproduced viewport expansion when that string was unwrapped and confirmed it disappears when `#source-hash` uses `overflow-wrap:anywhere; word-break:break-word`. The selector option was also shortened to date range + release, while full measurement status remains visible in the selected-pair panel. The latest GitHub Actions screenshots confirm the fix.

## Retention and scientific boundary

- The workflow reused only the verified derived-only artifact from measurement run #40232441596; `raw_hdf5_read_or_downloaded=false`.
- Private Drive remote verification passed for `author-map-rendered-evidence.zip` (1,052,241 bytes; SHA-256 `710835c48a477848335d74b688f1a371669a7da747288b2454c4d896ab09a0e8`) and the receipt copy. The evidence ZIP had no `.h5` or `.hdf5` members.
- The map preview is downsampled/warped presentation output, not a native-grid science raster or new measurement. The crown is still a published-bounds rectangle approximation, not the exact editable author crown vector.
- Paper reproduction remains **PARTIAL**; original null-generator/draw identity and some crown/RGI/terrain provenance gates remain unresolved.
- `HAZARD_DETECTION_STATUS=NOT_EVALUATED`; operational warning remains `NOT_IMPLEMENTED`. This does not validate landslide/glacier-collapse warning performance.
- Automated mobile emulation is not a physical-device test. A browser test against a generic arbitrary-AOI measurement bundle remains pending; no new arbitrary-AOI raw measurement was run.

## Artifact integrity

GitHub Actions outer artifact digest: `sha256:54c69d01ecd94602a04624c1521c3fccb2381e649f76db2b6738bdd439535b7e`.

Within the downloaded Actions artifact:
- `interactive-map.html` SHA-256: `4bf42d6a5f56ddbb394fdd7096f3854be654991f462a6fdb33856a324c478f8a`
- `browser-smoke.json` SHA-256: `ca5aeb8c959aae3baace6da9c399b915cc240710b8c27a9d1c7dbd6fdd2653f2`
- `browser-smoke-mobile.png` SHA-256: `882dc0013cc8fb3294e8e010e814ea428ab3cb8a790122ea22476d8c7115fd4f`
- `browser-smoke-tablet.png` SHA-256: `0e1123bf0998af580136c04de5ddd4cfc9c9be73631fe9d098ed678a05b5d7a4`


### Source AOI geometry note clarification

The deposited author code defines the rectangular AOI extent as 85.5245–85.5400° E, 28.2847–28.2970° N (`code/make_pot_figure.py:45`) and uses an index crop for crown time-series statistics (`code/make_fig_timeseries.py:53–58`). The map now reports those exact author-script bounds; native-grid pixel-mask edge-inclusion parity is still explicitly unverified. This is a code-archive observation, not a completed mask-equivalence result.
