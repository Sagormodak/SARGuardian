# RiverShift scientific tools

RiverShift is a separate NISAR GCOV processing engine. Its authenticated UI/API and owner-scoped job records live in moshiour0/SARGuardian_Dynamic; this folder contains only the isolated scientific processing worker in moshiour0/SARGuardian-backend.

## Development scope
This folder provides a first local scientific workflow:
1. Discover NISAR GCOV products in ASF DAAC.
2. Download an exact selected HDF5 granule.
3. Inspect its native diagonal covariance terms.
4. Export one consistently selected AOI-clipped gamma0 layer per acquisition.
5. Screen flood-period new water coverage.
6. Screen persistent erosion/deposition candidates.
7. Validate a binary water mask against an independently prepared reference raster.
8. Measure signed bankline displacement along independently digitised transects.
9. Audit whether at least three compatible GCOV dates cover the AOI sufficiently.
10. Export an observed-date water time series for discrete, evidence-preserving dashboard playback.

The separate GitHub Actions worker in `process_gcov_job.py` runs the selected AOI/date request through catalogue review, exact-product downloads, HDF5 validation, raster extraction, flood and persistent-change screening, observed-date playback and private result storage. It uses the AOI and date window supplied by the signed job request; no Bangladesh study polygon is substituted. A result remains provisional until independent review evidence is recorded.

Processing is limited by NISAR coverage, the AOI's available comparable acquisitions, the backend's 1,000 km² AOI ceiling and the worker resource limits. The API and worker require at least four distinct matching acquisition dates; the compatibility audit also requires at least 90% catalogue footprint coverage per selected date. The worker then selects up to twelve actual dates and at most twenty-four granules. These are acquisition dates, not daily measurements. A location with insufficient NISAR observations returns a no-result explanation instead of a simulated layer.

See `docs/RIVERSHIFT_PROCESSING_SETUP.md` for the GitHub and backend settings required before live job dispatch can run.

## Environment
- Python 3.13, as pinned by environment.yml.
- GDAL 3.13.0 or newer with HDF5 support.
- Rasterio compatible with the installed GDAL runtime.
- Earthdata Login/ASF access for product downloads.
- A projected metric output CRS; NISAR GCOV is normally provided in UTM for its footprint.

Install Python dependencies from this folder:

    python -m pip install -r requirements.txt

GDAL is a native system dependency. Install and verify it independently:

    gdalinfo --version

The inspection script refuses GDAL versions older than 3.13.0 because the NISAR HDF5 structure uses CF conventions supported by recent GDAL releases.

## Suggested project layout
    data/
      raw/
      processed/
      reference/
    data-audit/
      candidate_sirajganj_jamuna_aoi.geojson
      gcov-catalogue-manifest.json
      gcov-time-series-audit.json
    results/
      flood/
      morphology/
      validation/
      bankline-migration/

Keep raw multi-gigabyte products outside Git. Commit scripts, small test fixtures, README files, output manifests and selected small GeoJSON previews only. Never commit Earthdata credentials or private user data.

## Execution order
Read these task-specific documents before each script:
- README_01_discover_gcov_products.md
- README_02_download_gcov_product.md
- README_03_inspect_gcov_product.md
- README_04_export_gcov_layer.md
- README_05_run_flood_analysis.md
- README_06_run_morphology_analysis.md
- README_07_validate_water_classification.md
- README_08_measure_bankline_migration.md
- README_09_audit_gcov_acquisitions.md
- README_10_observed_date_playback.md

## Bankline transect measurement
For signed bankline movement, supply two dated banklines and user-oriented transects as standard WGS84 GeoJSON. The tool reprojects those inputs into the declared projected metre `--analysis-crs` before measuring. Each transect must intersect each bankline exactly once; ambiguous braided-channel intersections are rejected. The sign convention is start-to-end along the transect and must be declared in `--positive-direction-label`.

See `README_08_measure_bankline_migration.md` and `river_shift/README_06_transects.md` before running it.

### GCOV time-series feasibility audit
Run `audit_gcov_acquisitions.py` against the NASA CMR UMM-G 1.6.7 catalogue manifest before downloading or analysing products. It requires at least three dates matching maturity, direction, relative orbit, frame, bandwidth, polarization, processing type, observation source, CRID, orbit accuracy, frame coverage and center; the requested frequency/diagonal term must be encoded as available. Each date must meet the AOI footprint threshold. This is only a product-level review gate; HDF5 layers, valid masks and exact grids remain to be checked. The default minimum is 90%.

The GitHub Actions workflow `.github/workflows/river-shift-gcov-audit.yml` runs public catalogue discovery and footprint feasibility without downloading imagery. It is launched manually with the user-selected AOI/date window. The processing workflow `.github/workflows/river-shift-gcov-process.yml` runs only after an authenticated user submits a RiverShift job.

The archived live catalogue evidence is linked from the root README and judge guide. Catalogue footprint coverage is not valid raster coverage. The selected public product links redirect to Earthdata Login, so current HDF5 compatibility remains blocked pending an authenticated download. The exporter requires the exact-granule `.download.json` receipt, checks its maturity and source host, and binds the output COG to the sidecar with SHA-256 before analysis.

## Data-comparability gate
Before pixel-wise comparison, verify:
- Same NISAR instrument/frequency and acquisition mode.
- Same diagonal covariance term and compatible polarimetric configuration.
- Same maturity (do not mix BETA and PROVISIONAL).
- Compatible orbit direction, relative orbit/track, frame and viewing geometry.
- Same CRS, dimensions and affine transform after reprojection/resampling.
- Dates correspond to a documented hydrological event and recovery condition.

A failed comparability check means stop and reselect/reproject the data. Do not force a pixel-wise overlay.

## Core formulas
For GCOV linear gamma0 power:
    gamma0_dB = 10 * log10(gamma0_power)

For newly water-covered area:
    new_water = water_during AND NOT water_before

For persistent erosion candidate:
    erosion = land_before AND water_post_1 AND water_post_2

For persistent deposition candidate:
    deposition = water_before AND land_post_1 AND land_post_2

The erosion and deposition terms are candidate indicators. They do not establish flood causality or legal/field-confirmed land loss.

For independently digitised banklines and oriented transects:
    signed_displacement_m = after_chainage_m - before_chainage_m
    mean_net_rate_m_per_year = signed_displacement_m / (elapsed_days / 365.25)

Each transect must intersect each bankline exactly once. The transect start-to-end orientation determines the sign; ambiguous intersections are invalid.

## Reproducibility and provenance
Every JSON result should retain:
- Mission and product.
- Exact granule names and checksums (download manifest).
- Per-date AOI footprint coverage and the compatibility-group signature.
- Observation dates.
- Maturity, frequency and polarization term.
- AOI.
- Input units and threshold method/value.
- Grid/CRS assumptions.
- Software versions.
- Validation status and warnings.

Do not display sample values as measurements. The RiverShift dashboard may display checksum-verified private worker outputs as PROVISIONAL evidence, with warnings that the result is not independently validated. It must not label those outputs VERIFIED. User-imported reports/GeoJSON remain subject to the separate human-review gate: VERIFIED release status, complete provenance, reviewer identity/time, evidence reference and verification-record checksum. Live worker previews are drawn only after the private artifact receipt and report-linked SHA-256 checks pass.

## Test suite
From this folder:

    python -m pip install -r requirements.txt
    python -m pip install pytest
    python -m pytest -q

The tests use small synthetic rasters. They verify contracts and algorithms, not real-world model accuracy. Real scientific validation must use independent observations over the selected study area.

## Scientific references
- NISAR GCOV guide: https://nisar-docs.asf.alaska.edu/gcov/
- NISAR data maturity: https://nisar-docs.asf.alaska.edu/availability-overview/
- NISAR HDF5 guide: https://nisar-docs.asf.alaska.edu/data-format/
- NASA CMR Search API: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html
- ASF search and product delivery: https://docs.asf.alaska.edu/asf_search/searching/
- Jamuna riverbank erosion study: https://nhess.copernicus.org/articles/23/1749/2023/
