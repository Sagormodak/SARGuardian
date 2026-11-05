# Author footprint-wide candidate-screen kernel audit — 2026-10-24

## Scope and source identity

This audit extracts the footprint-wide candidate screen into an isolated, array-level module. It is a different estimator from the crown/site-series calculation in tools/know_place/paper_method.py. It does not run raw GOFF data and does not establish full paper reproduction.

Author-supplied Zenodo archive: https://doi.org/10.5281/zenodo.22730419. The ZIP and manifest-listed payloads were integrity-audited separately. Source files inspected:

| Source | SHA-256 |
|---|---|
| code/wide_screen.py | 60e4238b9a10510f52a4673939a9708bf513d8bae460ba797d2dd27a1357d7c9 |
| code/geometry.py | 0f056c46f2f5f9418dd1735b666edaa5c055514694fcd2c66490e09b6bb63004 |
| tables/TableS6_screen_params.json | 85743e828c4d684046acf43bdb0bfbc8b8c194626aacad8fd58e154e925d8e76 |

The source archive main code/data is CC BY 4.0. The separate extent_CC-BY-NC-4.0 runout outline was not used or copied.

## Author-source behavior transcribed

The new tools/know_place/footprint_screen.py isolates the numerical screen and enforces the ordered five-pair date sequence.

1. **Projection and first quality gate.** Author wide_screen.project calculates dE = AT*cE + SR*kE and dN = AT*cN + SR*kN from per-pixel coefficients delivered by geometry.load(). It retains only finite projected magnitudes with SNR >= 5 and magnitude <= 10 m. The screen function requires a structured result from `tools/know_place/footprint_screen.py`'s per-pixel projection helper. A separate array-only coefficient builder now lives in `tools/know_place/footprint_geometry.py`; it reproduces the interpolation recipe on supplied arrays but does not read or verify the original HDF5/DEM files. Its vertical-reference caveat is documented in `AUTHOR_FOOTPRINT_GEOMETRY_BUILDER_AUDIT_20261024.md`.
2. **Local mean.** lmean(a, w) is reproduced as float32 nan_to_num, finite-value support, scipy.ndimage.uniform_filter with default reflected edges, and output only where support fraction is strictly greater than 0.15.
3. **Magnitude anomaly.** The anomaly is mag - lmean(mag, 41). Its scale is the local mean of the absolute anomaly using the same 41-pixel window; the divisor floor is 0.05 m. This is a local scale statistic, not a conventional median absolute deviation.
4. **Residual vector coherence.** Subtract the local 41-pixel mean independently from dE and dN, normalize residual vectors, and estimate R in a 5x5 window. A window is retained only if finite-direction support fraction is strictly greater than 0.5.
5. **Within-pair candidate rule.** A cell is flagged only when all conditions hold in the same pair: z >= 4, magnitude anomaly >= 0.50 m, finite residual R, and residual R >= 0.75.
6. **Persistence.** The same grid cell must flag in at least 2 of the exact ordered pairs: 20 Jun–2 Jul, 2–14 Jul, 14–26 Jul, 26 Jul–19 Aug, and 19–31 Aug 2026. Mean anomaly and residual R are averaged only over intervals that flagged that cell.
7. **Candidate components.** scipy.ndimage.label default 2-D connectivity is retained (four-connected components), and components smaller than 10 pixels are excluded. Ten pixels at 80 m posting correspond to 0.064 km². The module returns component masks/labels; it does not recreate author GeoPackage/shapefile/CSV polygonization or centroid-ranking outputs.

The parameter inventory is in tables/TableS6_screen_params.json. The downslope-angle check is a later, separate analysis in candidate_attributes.py; topography is not used in wide_screen.py itself.

## Implementation added

- tools/know_place/footprint_screen.py: per-pixel AT/SR projection with mandatory 2-D coefficient rasters; quality gates; author-formula local mean; residual R; per-pair threshold screen; exactly-five-pair persistence; four-connected minimum-component filter.
- tools/know_place/footprint_geometry.py: array-level coefficient builder for caller-supplied radarGrid cubes and DEM array. It now checks horizontal CRS/affine and explicit vertical references; it does not read/hash the actual source files. Full boundary, data inventory and vertical-datum risk are documented separately.
- tools/tests/test_know_place_footprint_screen.py: tests for parameter constants; edge/support behavior; projection and quality gates; mandatory per-pixel geometry; diagnostic-map parity against a separately written reference of archived formulas on deterministic synthetic arrays; invalid-mask and interval rejection; five-pair persistence; default component connectivity and size threshold.
- Each result deliberately contains hazard_detection_status=NOT_EVALUATED. Its output is a movement candidate to inspect, not an operational alert.

## What the tests establish and do not establish

The tests compare the isolated equations with an independent test-local transcription of relevant archived formulas; they are synthetic known-answer tests, not execution of the original archive script. They can catch implementation drift in the extracted kernel but are not raw-input parity. Validation [run 40050020868](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020868) passed 176 tests, including geometry-builder synthetic tests and geometry-to-screen integration, plus four workflow YAML parses and actionlint. No raw GOFF products were downloaded; [run 40050020872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020872) skipped the raw replay because `[run-know-place]` was absent.

The workflow does not yet read and SHA-256-pin exact author GOFF HDF5 inputs or the 16 original terrain source tiles; pass those verified inputs through the geometry builder and screen together; compare the coefficient maps against archived geometry caches; regenerate per-pair footprint maps and candidate GeoTIFF/GPKG/shapefile/CSV/centroid ordering outputs; run post-hoc topographic downslope validation; or establish detection skill, recall, precision, false-alarm rate, lead time or operational value. The archived final screening rasters share the intended native grid, and the supplied prepared DEM shares its horizontal grid, but that alone is not input or method parity.

The archive includes three footprint screening rasters and a post-event 101-zone source-derived inventory, but not the five raw source GOFF HDF5 granules or five full-footprint per-pair offset rasters. The first author-exact P05023 pair remains unresolved in the live ASF identity gate; do not silently substitute X05026.

## Scientific interpretation

The source says the screen finds coherent moving surfaces, and active glaciers dominate its candidate set. It is not a prospectively validated event detector. The Bhote Koshi site-series analysis reporting no pre-event comparison above the 95th percentile is a separate result; do not infer that the footprint screen validates or contradicts it.

Current status:

- PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED
- HAZARD_DETECTION_STATUS=NOT_EVALUATED
- Operational warning / alert: not implemented.

Raw-source replay was not run. A branch push alone is not authorization; the exact [run-know-place] consent marker remains required.


## Implementation follow-up — 2026-10-25

The audit above records the state of the array-only kernels as of 2026-10-24. Since then, branch `feat/know-place-analysis` has gained the end-to-end *runner and gated workflow integration*:

- `tools/know_place/author_footprint_replay.py` connects exact-source manifest/hash verification, the strict GOFF reader, author per-pixel geometry coefficient builder, five ordered footprint screen passes, 2-of-5 persistence, 4-connected component filtering, hit-field observations, terrain-direction attribution and archive comparisons.
- Before running the footprint pass, `.github/workflows/know-place-author-exact-replay.yml` downloads the author Zenodo ZIP with the pinned SHA-256, validates ZIP CRC, extracts only the three required terrain rasters with individual SHA-256 checks, and runs the screen against the already downloaded five raw P05023 granules. It does not re-download the GOFF products in the footprint step.
- After the five-pair screen, the workflow requires all three derived footprint rasters to match their archived golden rasters and the computed directional candidate inventory to match all 101 source-derived zones, with 106 components before directional filtering and 101 directional passes. A mismatch fails the overall workflow after producing and retaining the available evidence; the raw HDF5 retention/deletion contract remains separate.
- The new helper's unit tests and archive-inventory logic passed in isolated validation [run 40133358388](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40133358388): **238 tests passed**, eight workflow YAML files parsed, pinned actionlint validation passed, and live ASF identity checks passed without raw downloads. Shell continuation errors found by actionlint were corrected in the following branch commit.

**Important boundary:** this is implementation plus synthetic/contract validation, not yet a full-footprint numerical replay. The latest push-triggered author workflows were consent-gated and skipped raw acquisition. A fresh manual workflow dispatch with exact `[run-know-place]` authorization is still required to run P2 and footprint-wide source processing. Until its artifacts show 3/3 raster parity and 101/101 candidate inventory parity, do not claim that the published full-footprint screen has been reproduced.

Even after successful screen parity, displacement-null reproduction remains blocked because the supplied archive lacks the exact draw-level generator/script. Hazard-detection precision, recall, false-alarm rate, lead time and operational warning skill remain `NOT_EVALUATED`. Main remains unchanged; all integration work is isolated on `feat/know-place-analysis`.
