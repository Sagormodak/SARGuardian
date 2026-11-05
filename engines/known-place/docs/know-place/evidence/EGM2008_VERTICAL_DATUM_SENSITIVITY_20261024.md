# EGM2008 vertical-datum sensitivity for the Bhote Koshi terrain grid

**Date:** 2026-10-24  
**Branch:** `feat/know-place-analysis`  
**Purpose:** quantify a versioned EGM2008-height to WGS 84 ellipsoidal-height sensitivity without changing the author/source-reproduction path.

## Download and verification receipts

- Public terrain inputs: sixteen Copernicus GLO-90 tiles from [acquisition run 40052506016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40052506016); 76,504,193 payload bytes total. Each tile's SHA-256 was rechecked against the source artifact manifest before processing.
- Official PROJ/NGA grid: `us_nga_egm08_25.tif`, downloaded once from `https://cdn.proj.org/us_nga_egm08_25.tif`; bytes **80,585,622**; SHA-256 **`4191d471eefebf24091b56dbc604353cb3b8cf8cc70e448bb9ae56a272bef17a`**. Profile: 8640 × 4321 Float32, global 2.5-arc-minute grid.
- Sensitivity workflow: [run 40053719232](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40053719232), code commit `ef3d88f3892aa2a3e6e9aa21009b94749826c410`.
- Downloadable result artifact: `know-place-egm2008-vertical-datum-sensitivity-40053719232-1`, artifact ID `12543419723`, 174,346,579 bytes, SHA-256 **`4defe3a608e8514ce76d22f948264fd9aa806fb286a7aa413ea384756d39a13c`**.

Official documentation states that Copernicus DEM uses EGM2008 vertical reference (EPSG:3855) and meter units; PROJ-data describes `us_nga_egm08_25.tif` as the global EGM2008 vertical grid; and ASF documents that the NISAR processing DEM is re-referenced from EGM2008 heights to the WGS84 ellipsoid. Sources: [Copernicus DEM documentation](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM), [PROJ datum-grid catalogue](https://github.com/OSGeo/PROJ-data/blob/master/us_nga/us_nga_README.txt), [PROJ grid CDN](https://cdn.proj.org/), [NISAR modified DEM documentation](https://nisar-docs.asf.alaska.edu/nisar-dem/).

## Replaying the archived prepared DEM

The current public tiles were processed with the archived `code/prep_terrain.py` recipe: lexical filename ordering, mosaic, Float32 cast, values below −1000 set to NaN, then bilinear reprojection to the archived target grid. The archived `terrain/elev_m.tif` has SHA-256 `d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1` (59,400,495 bytes).

| Check | Result |
|---|---:|
| Target grid | EPSG:32645, 4311 × 4230, 80 m, affine `(80, 0, 126720; 0, -80, 3347280)` |
| Finite cells in archived and replayed rasters | 18,235,530 each |
| Finite-mask equality | Exact — all cells |
| Float32 bitwise-equal elevation cells | 18,235,529 / 18,235,530 |
| Maximum absolute elevation difference | 0.000244140625 m |
| RMSE | 0.0000000571716672 m |

This strongly supports raster-value/grid replay: current public GLO-90 values, processed by the archived mosaic/warp recipe, reproduce the archived prepared elevation raster to Float32 rounding. It does **not** prove byte identity with the author's original sixteen input files; those original files/hashes were not present in the archive.

## Formal vertical-coordinate operation

The sensitivity uses the formal PROJ operation from **EPSG:9518 (WGS 84 + EGM2008 height)** to **EPSG:4979 (WGS 84 ellipsoidal height)**. It selects a named `us_nga_egm08_25.tif` grid operation and refuses ballpark/no-op conversion. The selected operation is `Inverse of WGS 84 to EGM2008 height (1) (with axis order normalized for visualization)`, declared accuracy 0.113 m, with pipeline `+proj=vgridshift +grids=us_nga_egm08_25.tif +multiplier=1`. No hand-chosen sign was used.

The signed offset is:

`ellipsoidal_height_m − EGM2008_orthometric_height_m`

| Statistic | All 18,235,530 valid target cells |
|---|---:|
| Minimum | −67.0417 m |
| P01 | −65.5165 m |
| P05 | −61.8444 m |
| Median | −30.1587 m |
| Mean | −36.4636 m |
| P95 | −26.0913 m |
| P99 | −24.8164 m |
| Maximum | −24.2041 m |

### Published crown rectangle

For the published WGS84 crown rectangle (85.5245–85.5400° E, 28.2847–28.2970° N), rasterized onto the 80 m target grid with `all_touched=false`, 323 valid cell centres were selected.

| Crown offset statistic | Value |
|---|---:|
| Minimum | −31.9634 m |
| P01 | −31.9422 m |
| Median | −31.7705 m |
| Mean | −31.7719 m |
| P95 | −31.6292 m |
| P99 | −31.5944 m |
| Maximum | −31.5728 m |

The formal transformation therefore gives a crown-area height-reference offset of approximately **−31.77 m**. This is a material input discrepancy, not a correction to apply silently. It writes separate `elev_m_hae_experimental.tif` and `ellipsoid_minus_egm2008_m.tif` outputs. The saved Float32 offset equals the saved ellipsoidal DEM minus the saved EGM2008 DEM on every valid pixel.

## Scientific interpretation and limitations

- Current public GLO-90 values replay the archived prepared DEM essentially exactly. Combined with the archived preparation script's visible horizontal reprojection but no vertical-coordinate operation, this strongly indicates the prepared DEM retained EGM2008-referenced values. Original tile-byte identity remains unverified, so this is not absolute provenance proof.
- NISAR's radarGrid `heightAboveEllipsoid` axis is ellipsoidal, whereas the Copernicus GLO-90 data's vertical reference is EGM2008. The mismatch is now quantified for the prepared terrain grid.
- The raw GOFF HDF5 geometry cube is still absent. It is therefore not possible to quantify how this height offset changes interpolated `cE`, `cN`, `kE`, `kN`, projected offsets, candidate screens or published results. Do not infer those effects from the DEM-only sensitivity.
- The experimental HAE DEM is **not** inserted into the author-reproduction path or used to update existing metrics. Any datum-corrected variant must remain separate and versioned.
- The first author-published P05023 GOFF pair (2026-06-20 → 2026-07-02) remains `NOT_FOUND / UNRESOLVED`; do not substitute historical X05026.

## Gate status

- Current public terrain-tile download, hashes and raster profiles: **PASS**.
- Archived prepared DEM grid/value replay: **PASS to Float32 rounding**.
- Formal EGM2008 grid-based sensitivity: **PASS as a separate experimental output**.
- Original author source-tile bytes and exact raw GOFF geometry cubes: **UNVERIFIED / BLOCKED**.
- Paper reproduction: `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`.
- Hazard detection: `NOT_EVALUATED`.
- Raw GOFF downloaded by this workflow: **0**.
- `main`: unchanged at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.
