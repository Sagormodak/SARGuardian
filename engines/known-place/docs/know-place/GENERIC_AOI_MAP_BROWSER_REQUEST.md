# Generic-AOI map browser fixture request

Date created: 2026-10-26  
Branch: `feat/know-place-analysis`

Purpose: exercise the generic-AOI map rendering path in a real headless Chromium session using `tools/tests/fixtures/generic_aoi_map_report.json`.

**Data boundary:** the fixture is explicitly synthetic. All pixel values, statistics, SHA marker and AOI are invented for UI regression checks; no NISAR/GOFF source is read, no raw HDF5 is downloaded, no scientific measurement or hazard evaluation is performed. This workflow must not be cited as validating a real arbitrary-AOI measurement bundle.

Expected checks: one synthetic pair is selectable; synthetic data status remains visible; generic paper status remains `NOT_EVALUATED_GENERIC_AOI`; hazard status stays `NOT_EVALUATED`; no fake native-grid GeoTIFF link appears; long SHA wraps; no horizontal overflow at 360×800, 390×844, 768×1024, and 844×390; evidence ZIP passes CRC and contains no `.h5`/`.hdf5` members.

The real generic-AOI measurement-bundle browser test remains a distinct pending release gate. Do not trigger raw analysis without the explicit user marker `[run-know-place]`.
