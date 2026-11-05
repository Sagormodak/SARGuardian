# Author Footprint Geometry Builder Audit — 2026-10-24

## Scope and source identity

This audit records the isolated per-pixel geometry-coefficient builder and a material vertical-reference issue visible in the author's supplied terrain workflow. It does not claim that any raw GOFF geometry cube was opened or processed in this run: the supplied Zenodo archive does not contain the exact raw GOFF HDF5 granules.

Source code read directly from the user-supplied archive at https://doi.org/10.5281/zenodo.22730419:

| Archive file | SHA-256 |
|---|---|
| `code/geometry.py` | `0f056c46f2f5f9418dd1735b666edaa5c055514694fcd2c66490e09b6bb63004` |
| `code/prep_terrain.py` | `e3e3da8a03253935c762002b30d460018aaf961ab4475d35ca2d94c8e39ddb68` |
| `code/wide_screen.py` | `60e4238b9a10510f52a4673939a9708bf513d8bae460ba797d2dd27a1357d7c9` |

The source archive's main code/data is CC BY 4.0. The separate `extent_CC-BY-NC-4.0/` runout outline was not used or copied.

## Archived terrain and screening-grid facts

The archive contains `terrain/elev_m.tif`, SHA-256 `d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1`, MD5 `a5451bac63051bdf36ed2bde6acca7cc`, byte size 59,400,495. Rasterio inspection reports one Float32 band, 4,311 columns × 4,230 rows, EPSG:32645, 80 m pixels, affine transform `(80, 0, 126720; 0, -80, 3347280)`, and nodata metadata `-9999`. No stored pixel equals that sentinel; all 18,235,530 cells are finite. The archived raster values range from 77.5 m to 8,146.092 m, with median 4,674.589 m and p99 6,113.255 m.

The three archived screening outputs `rasters/n_epochs_flagged.tif`, `rasters/mean_anomaly_m.tif`, and `rasters/mean_coherence_R.tif` were read directly. All three share the same 4,311 × 4,230 shape, EPSG:32645, 80 m transform and extent:

- left 126,720 m; right 471,600 m;
- bottom 3,008,880 m; top 3,347,280 m.

This verifies that the archived DEM raster and final screening rasters share the same horizontal grid. It does not prove the DEM vertical datum is compatible with the GOFF radarGrid height axis, or that regenerated per-pixel coefficients match the author outputs.

The archived `code/prep_terrain.py` describes mosaicking 16 Copernicus GLO-90 tiles across approximately 83–87°E / 27–31°N, then bilinearly reprojecting the mosaic from EPSG:4326 to the screening raster's horizontal CRS and exact output transform. The archive's `terrain/elev_m.tif` appears to be that prepared output. The source script does not show a vertical datum transformation.

## Geometry interpolation implemented

The added `tools/know_place/footprint_geometry.py` is an array-only implementation of the archived interpolation recipe. It accepts the five radarGrid geometry cubes plus height/y/x axes, an already-warped DEM array, target and DEM affine transforms, explicit horizontal CRS identifiers and explicit vertical-reference labels. It:

1. requires finite, strictly monotonic axes and cube shapes consistent with `(height, y, x)`;
2. normalizes a descending y-axis with the corresponding cube arrays, matching the archived geometry script;
3. performs linear `RegularGridInterpolator((height, y, x), ...)` with `bounds_error=False, fill_value=None`, and reports how many target pixel centres are outside the radarGrid x/y interpolation domain;
4. replaces the declared DEM nodata value and all other nonfinite elevations with the median valid DEM height and reports the fill count;
5. clips elevations to the first/last height-axis values and reports how many cells were clipped;
6. computes `cE=alongTrackUnitVectorX`, `cN=alongTrackUnitVectorY`, `kE=-(losX/hypot(losX,losY))/sin(incidence)`, and the analogous `kN`;
7. records per-coefficient nonfinite-pixel counts, target extent/transform, source axis bounds, extrapolation count and the declared vertical-reference strings.

The builder fails closed on horizontal CRS mismatch, target/DEM affine mismatch, unsupported target rotation/shear, nonmonotonic axes, invalid DEM inputs and undeclared vertical-reference labels. It does not load or hash HDF5/DEM files, verify the original 16 source tile identities, or independently certify caller-supplied CRS/datum claims. The reference strings are compared case-insensitively as strings, not resolved by a geodetic datum database.

The current synthetic tests cover interpolation known answers, descending-Y normalization, DEM median fill/clipping, extrapolation accounting, block-size equivalence, invalid axes/CRS/transform, nonfinite coefficients, default vertical-mismatch refusal and the geometry → displacement projection → footprint-screen integration. This is array-kernel validation only; it does not process actual GOFF data.

## Critical unresolved vertical-reference caveat

The code-level comparison reveals a material potential vertical-reference mismatch:

- The Copernicus DEM product specification identifies standard GLO-90 elevation reference as the EGM2008 geoid (`EPSG:3855`): [Copernicus DEM collection specification](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) and [Copernicus DEM Product Handbook](https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf).
- The NISAR radarGrid dimension is `heightAboveEllipsoid`; the official metadata guide uses height-above-ellipsoid as the height axis, and the [NISAR modified Copernicus DEM guide](https://nisar-docs.asf.alaska.edu/nisar-dem/) says DEM elevations are re-referenced vertically from EGM2008 to the WGS84 ellipsoid for SAR processing. See also [NISAR metadata](https://nisar-docs.asf.alaska.edu/metadata/).
- The archived `prep_terrain.py` reprojects from EPSG:4326 to the target projected horizontal CRS; the archived `geometry.py` then feeds `elev_m.tif` directly into the interpolator's `heightAboveEllipsoid` axis after median fill and clipping. Neither function shows an EGM2008-to-ellipsoid vertical transformation.

Thus, unless the exact source tiles placed in the author's `AUX` directory were already vertically transformed upstream, the archived workflow appears to use orthometric EGM2008 DEM elevations directly against ellipsoidal GOFF height-axis values. The supplied archive does not include the 16 original source tiles plus enough source metadata to resolve that alternative. The effect on incidence angle, projected offsets and candidate pixels has not been quantified; no geoid-grid correction or sensitivity run has been calculated.

**Do not silently patch the author-reproduction path to insert a vertical correction.** The builder requires vertical-reference labels and rejects unequal labels by default. It has an explicit override to retain the archived direct-use behavior; that output is marked `MISMATCH_PASSED_THROUGH_FOR_EXPLICIT_SOURCE_REPRODUCTION`, records `vertical_transformation_applied=false`, and is not datum-corrected geometry. A corrected-datum sensitivity needs to be a separate versioned experiment with verified DEM source identity, geoid model/grid, sign convention, transformation software and a per-pixel impact report.

## CI and remaining blockers

Validation run [40050020868](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020868), testing commit `407828dcab3585810eadada4dd777b12008b5d1d`, passed **176 tests in 4.68 seconds**, all four workflow YAML parses and pinned actionlint v1.7.12 validation. The live ASF job downloaded zero source products. Raw replay [40050020872](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40050020872) skipped the five-pair job because `[run-know-place]` was absent.

Outstanding blockers:

- The exact five raw source GOFF HDF5 granules and the 16 original DEM input tiles are absent from the supplied archive.
- The first exact author P05023 pair remains `NOT_FOUND / UNRESOLVED`; do not substitute X05026.
- Geometry coefficients have not been generated from actual, checksum-verified GOFF HDF5/DEM sources in this task.
- The five full-footprint offset rasters, every pixelwise author screen product, vector/GIS exports and downstream downslope analysis have not been regenerated or parity-tested.
- The vertical-reference relationship in the author terrain preparation remains a material unresolved scientific risk.

Status remains `PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED` and `HAZARD_DETECTION_STATUS=NOT_EVALUATED`. Raw-source replay has not been run; the exact `[run-know-place]` consent marker is still required.
