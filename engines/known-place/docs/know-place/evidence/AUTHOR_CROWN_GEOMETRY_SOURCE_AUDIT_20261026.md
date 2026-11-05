# Deposited source code audit — Bhote Koshi crown AOI

Date: 2026-10-26  
Project branch: `feat/know-place-analysis`

## Direct code evidence

The deposited author source archive `bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip` was inspected locally. It contains 91 ZIP members; `ZipFile.testzip()` returned no corrupt member, and it contains zero `.h5`/`.hdf5` files. Source paths below are from this archive, not a repository mirror.

- `code/make_pot_figure.py:45`: `AOI = (85.5245, 28.2847, 85.5400, 28.2970)` with comment “source AOI used by the project”. This is an axis-aligned rectangular geographic window.
- `code/nhess_content.py:150–152`: manuscript text describes the same values as the crown polygon, 85.5245–85.5400° E and 28.2847–28.2970° N.
- `code/make_fig_timeseries.py:53–58`: `crown_slice(mag, ext)` derives longitude and latitude axes from the raster extent, then uses `numpy.searchsorted` to select rectangular row/column slices bounded by that AOI. The crown series is therefore a rectangle-crop implementation in the deposited script.
- The archive contains `inventory/candidates_attributed.gpkg` and related candidate polygons, but these are footprint-wide candidate zones rather than an editable source-crown AOI vector.
- The separate `extent_CC-BY-NC-4.0/flow_extent.shp` is the flow/runout extent and carries its own CC BY-NC 4.0 licence. Do not use it as the crown mask or redistribute it outside that licence.

## What this establishes—and what it does not

**Established:** the reference script’s stated AOI bounds and its rectangular crop semantics. The interactive map now shows the author-defined bounds and avoids claiming that the geometry itself is wholly unknown.

**Not established:** exact native-grid pixel inclusion parity. The rectangle’s geographic bounds alone do not prove identical row/column indices, treatment of edge cells, validity support, or equivalence of all five pair statistics. The author crop uses `searchsorted` against a grid extent; a mask derived through a projected rasterization path may differ at boundary cells. A dedicated golden-mask comparison on the same source geolocation arrays/grid is still required.

The result of this audit is not evidence of hazard-detection performance. Whole-paper reproduction remains PARTIAL; `HAZARD_DETECTION_STATUS=NOT_EVALUATED`.
