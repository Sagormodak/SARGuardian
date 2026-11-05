# Render interactive map from the retained Bhote Koshi P05023 measurement

Request date: 2026-10-26

Use the already successful author-exact measurement from GitHub Actions run [#40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596), attempt 1, artifact `know-place-author-exact-40232441596-1`.

This request authorizes **rendering only from the existing derived-only artifact**. Do not re-download or read raw GOFF HDF5, do not re-run measurement, and do not alter/merge `main`.

Expected checks: five exact `P05023` intervals, source SHA alignment, preview bounds derived from native EPSG:32645 coordinate axes, explicit published-bounds crown-rectangle approximation note, no native-grid GeoTIFF link unless an actual such file is included, Chromium pair-selection smoke test for 26 July–19 August 2026, hazard status `NOT_EVALUATED`, and private Drive remote verification of the rendered map and receipts.

The map is a presentation layer: its preview is downsampled/warped and must not be treated as a remeasurement or operational warning.

## Re-render after verified display refinements — 2026-10-26

Use the latest validated map renderer from the feature branch. Check visible label "Valid crown-mask pixels", readable partial paper-reproduction status, null high-motion count shown as an em dash, source grid terminology, crown-rectangle approximation note, and no native-grid GeoTIFF link unless a real file exists. Reuse source run #40232441596, attempt 1. No raw HDF5 download or measurement rerun.

## Crown-mask overlay correction rerender — 2026-10-26

Latest isolated CI [40237084749](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40237084749) passed after changing the author-map preview so valid surrounding-scene pixels outside the crown mask are transparent. Render the exact same retained measurement artifact #40232441596 and require the browser smoke to confirm the visible transparency note says the preview is crown-mask only. No raw HDF5 downloads or measurement rerun.


## Responsive-browser QA rerender — 2026-10-26

Re-render from the existing retained derived-only artifact from run #40232441596 using the responsive smoke-gate revision. In addition to the desktop assertions, test 360×800 and 390×844 mobile-emulated viewports, 768×1024 tablet, and 844×390 landscape. Each viewport must have no horizontal document/body overflow, a visible pair selector, a usable map size, and the 26 July–19 August pair available. Preserve mobile and tablet screenshots in the evidence ZIP. Recheck private Drive remote byte verification. This request is presentation QA only: no raw GOFF HDF5 download, no new measurement, no changes/merge to main, and no claim of physical-device verification.


## Mobile intrinsic-width regression fix — 2026-10-26

The first responsive browser smoke exposed a real small-screen overflow: at 360 px and 390 px emulated mobile widths, the acquisition-pair select imposed an intrinsic minimum width of 589 px, expanding the layout viewport to 618/619 CSS px. The tablet and landscape probes passed. The interactive map CSS now explicitly constrains controls and field grid items with `min-width:0` and `max-width:100%`; a regression test checks this contract. Re-run the same four-viewports smoke and retain screenshots. This remains presentation QA only; no new raw HDF5 access or measurement is allowed.


## Second mobile layout correction — 2026-10-26

The next browser run confirmed the 360 px / 390 px overflow persisted despite input-level max-width: the grid/container intrinsic sizing still allowed a 589 px controls column. Constrain the outer map grid and panel, explicitly set the controls/field width to 100%, and use `minmax(0,1fr)` for the narrow-screen grid track. The viewport smoke report should additionally retain the measured grid/control widths to make any remaining failure diagnosable. No raw input download or measurement rerun.


## Mobile viewport-expansion root-cause correction — 2026-10-26

The previous mobile screenshots showed the source SHA-256 rendered as a single unbroken 64-character string in the controls panel; that text can expand the mobile layout viewport. The map now wraps the provenance hash safely, and the acquisition selector omits the already-displayed redundant status token so its option labels stay concise. The browser report also records viewport, grid, controls, field, selector and hash widths plus media-query state to diagnose any future overflow. Re-run the same four viewports and retain mobile/tablet screenshots; do not declare mobile QA complete until all gates pass.
