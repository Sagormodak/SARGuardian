# Copernicus GLO-90 source-tile acquisition and archived-terrain replay

**Date:** 2026-10-24  
**Repository branch:** `feat/know-place-analysis`  
**Scope:** Public source terrain tiles only. This workflow did **not** download raw NISAR GOFF HDF5.

## Acquisition receipt

- Acquisition run: [40052506016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40052506016).
- Workflow: [know-place-dem-source-acquisition.yml](https://github.com/moshiour0/SARGuardian-backend/blob/feat/know-place-analysis/.github/workflows/know-place-dem-source-acquisition.yml).
- Downloaded artifact: `know-place-copernicus-glo90-source-tiles-40052506016-1`, artifact ID `12543902856`.
- Artifact ZIP size: 75,725,718 bytes.
- Artifact ZIP SHA-256: `0499832696ccf4dbda584a848f6373771c498b168232b3acc486576c2bda26f8`.
- 16 one-degree COG GeoTIFFs, total payload bytes: 76,504,193.
- Each source tile was downloaded in one attempt, hashed with SHA-256, opened with Rasterio, and checked for one-band geographic raster and expected one-degree bounds. All 16 passed; each was 1200 × 1200 Float32 EPSG:4326.
- Full file-by-file hash ledger: [`reference/copernicus_glo90_current_manifest_20261024.json`](../reference/copernicus_glo90_current_manifest_20261024.json).

The bucket is the public AWS mirror of Copernicus DEM GLO-90. Official documentation identifies the products as cloud-optimized GeoTIFFs and describes public access to the GLO-90 bucket ([bucket documentation](https://copernicus-dem-90m.s3.amazonaws.com/readme.html), [AWS Open Data Registry](https://registry.opendata.aws/copernicus-dem/)). Copernicus DEM citation and licence instructions are maintained by the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM); cite DOI [10.5270/ESA-c5d3d65](https://doi.org/10.5270/ESA-c5d3d65).

## Archived `terrain/elev_m.tif` reconstruction

I extracted the author's archived `terrain/elev_m.tif` from the user-supplied Zenodo code/data ZIP and replayed the archived `code/prep_terrain.py` terrain method using the downloaded current public tiles:

1. Sort the sixteen `*.tif` source names lexically.
2. Mosaic with `rasterio.merge.merge`.
3. Cast to Float32 and set elevations below −1000 m to NaN.
4. Reproject from EPSG:4326 to the exact archived target affine/grid with bilinear resampling and NaN nodata, matching the visible author script.

Archived DEM source-file SHA-256: `d593f74142d930fb3f1f4a320950019f318842f933f4da64139ea4e214ecd8a1`; bytes: 59,400,495. Its grid is 4311 columns × 4230 rows, EPSG:32645, 80 m posting, affine `(80, 0, 126720; 0, -80, 3347280)`.

| Check | Result |
|---|---:|
| Archived finite cells | 18,235,530 |
| Reconstructed finite cells | 18,235,530 |
| Finite-mask equality | PASS — every cell |
| Bitwise-equal Float32 cell values | 18,235,529 / 18,235,530 |
| Maximum absolute elevation difference | 0.000244140625 m |
| Difference RMSE | 0.0000000571716672 m |
| Reconstructed cells within 1 mm | 100% |

The maximum difference is one Float32-scale rounding step; median, P01, P99, minimum and maximum match at Float32 precision. This is compelling **raster-value/grid replay evidence** that current public GLO-90 elevation values, processed with the archived mosaic/warp recipe, reproduce the archived prepared DEM. It is not evidence of byte-for-byte identity of the original sixteen source files, because the author did not publish source-tile hashes or original tile files.

## Scientific interpretation and unresolved datum risk

The terrain-preparation script visibly performs horizontal CRS reprojection and raster resampling, but does not show a vertical datum transformation. Copernicus DEM documentation identifies the GLO-90 vertical reference as EGM2008; NISAR's radarGrid `heightAboveEllipsoid` is an ellipsoidal-height axis. The new source-tile replay strengthens the evidence that the archived prepared DEM holds the public GLO-90 elevation values, rather than a visibly corrected ellipsoidal-height surface.

**No geoid shift was applied or quantified in this comparison.** The exact author GOFF HDF5 geometry cube remains absent, so the change to the `cE/cN/kE/kN` coefficient maps cannot yet be computed. The direct-use author path must not be silently modified; a corrected vertical-reference sensitivity should be versioned separately and run against exact metadata/source bytes.

Useful authoritative references:
- [Copernicus DEM dataset and licence documentation](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)
- [NISAR DEM documentation](https://nisar-docs.asf.alaska.edu/nisar-dem/)
- [NGA EGM2008 model description and grid resources](https://earth-info.nga.mil/)

## Gate status

- Terrain source tile acquisition and archived raster-value replay: **PASS**.
- Original terrain input byte identity: **UNVERIFIED**.
- EGM2008-to-ellipsoidal height compatibility: **UNRESOLVED; no correction applied**.
- Exact five author P05023 GOFF byte identity: **BLOCKED**, with first pair still `NOT_FOUND / UNRESOLVED`.
- Paper reproduction: `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`.
- Hazard detection: `NOT_EVALUATED`.
- `main` was not modified or merged.
