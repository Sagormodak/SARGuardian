# 11 · Optional Copernicus Sentinel-2 cross-sensor agreement screen

## Purpose

Compare one retained NISAR-derived binary water mask with a nearby, clear-sky Copernicus Sentinel-2 Level-2A optical scene. The tool provides a second-sensor agreement screen and explicit common-support metrics. It is an optional research tool; it does not add work to every RiverShift NISAR job.

**Interpretation boundary:** this is cross-sensor agreement, not ground truth, field validation or a formal supervised accuracy assessment. Optical and radar sensors have different physical sensitivities, and the acquisition dates may differ.

## Inputs

- Full-resolution NISAR binary water-mask GeoTIFF: 1 = water, 0 = non-water, NoData excluded.
- The date of the NISAR observation represented by that mask.
- Internet access to the public Microsoft Planetary Computer STAC API and temporary signed Sentinel-2 COG assets.

No Planetary Computer account, API key or additional environment secret is required. The script obtains short-lived SAS-signed asset URLs at runtime and never writes or prints those tokens.

## Data source and assets

- **Copernicus Sentinel-2 L2A** from the public `sentinel-2-l2a` STAC collection.
- **B03** (green) and **B11** (short-wave infrared 1) for the Modified Normalized Difference Water Index: `MNDWI = (B03 - B11) / (B03 + B11)`.
- **SCL** scene classification layer; only classes 4 (vegetation), 5 (bare soil) and 6 (water) are accepted as clear comparison support. Water is SCL class 6. Cloud, cloud-shadow, cirrus, snow, defective, dark/unclassified and no-data classes are excluded.

The B11 20 m grid is the comparison grid. B03 is bilinearly aligned; NISAR categorical mask and SCL categorical values use nearest-neighbour resampling. The MNDWI threshold is configurable and should be sensitivity-checked for the river and hydrological condition.

## Reproduce

From this folder:

```bash
python validate_with_sentinel2.py \
  --nisar-water-mask results/time_series/water_2026-07-12_mask.tif \
  --observation-date 2026-07-12 \
  --output-dir results/validation/sentinel2-2026-07-12 \
  --max-day-offset 3 \
  --max-cloud-cover 40 \
  --mndwi-threshold 0.0
```

Options:
- `--max-day-offset`: permitted date difference in days (default 3; allowed 0–30).
- `--max-cloud-cover`: maximum scene cloud cover percentage (default 40).
- `--mndwi-threshold`: water when MNDWI is greater than this value (default 0.0).
- `--minimum-common-support`: minimum fraction of NISAR-valid pixels also valid in the optical clear-sky comparison grid (default 0.80).

Scene selection ranks AOI footprint overlap first, then date proximity and cloud cover. A single scene is selected. If that tile and clear SCL support do not cover the minimum fraction, the report says `INSUFFICIENT_OPTICAL_SPATIAL_SUPPORT`; it does not publish agreement metrics from a small sliver of the AOI.

## Outputs

The script writes `sentinel2_cross_sensor_agreement.json` containing:
- exact STAC collection, item ID, product URI, MGRS tile, platform, date/time and cloud cover;
- unsigned source B03/B11/SCL asset hrefs (temporary signed URLs are not retained);
- NISAR input filename and SHA-256;
- date offset, tile footprint overlap and cloud-free common support;
- separate confusion matrices and agreement, precision, recall, specificity, balanced accuracy, F1, IoU, Cohen's kappa and water-area bias for SCL water and MNDWI water;
- the optical threshold, resampling choices and quality warnings.

If no suitable scene exists, the tool writes `NO_MATCHING_SENTINEL2_SCENE_WITHIN_FILTER` with `metrics: null`. Missing optical evidence is never converted into zero agreement. If common support is too small, the status is `INSUFFICIENT_OPTICAL_SPATIAL_SUPPORT` and metrics remain null.

## Acceptance / failure gates

- NISAR input must contain only 0, 1 and NoData.
- Input grids must be projected in metre units; area metrics are not computed on geographic coordinates.
- The comparison window is bounded to protect memory.
- At least one valid common-support pixel is required.
- Cloud, shadow, snow and unclassified SCL pixels are excluded.
- A missing scene or insufficient common support is an explicit no-result state.
- The input NISAR SHA-256 and selected Sentinel-2 source identity are recorded.

## Scientific limitations

- Sentinel-2 L2A SCL and MNDWI are optical screening references, not error-free labels.
- Cloud cover percentage is scene-level metadata; the SCL common-support mask is also applied locally.
- A short date offset does not guarantee identical river stage, rainfall or channel condition.
- MNDWI threshold choice can alter water/non-water classification and must be reviewed.
- The tool selects one Sentinel-2 tile. AOIs spanning multiple MGRS tiles may not achieve sufficient coverage; split the AOI or implement a validated multi-tile mosaic rather than treating partial coverage as AOI-wide.
- Cross-sensor agreement does not prove sediment deposition, erosion causality, bankline movement or flood depth.
- Results remain provisional until a reviewer verifies scene suitability, co-registration, temporal comparability and reference quality.

## Primary references

- Copernicus Sentinel-2 data collection: https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-2
- Microsoft Planetary Computer STAC API: https://planetarycomputer.microsoft.com/api/stac/v1/
- Planetary Computer SAS signing: https://planetarycomputer.microsoft.com/docs/concepts/sas/
- Sentinel-2 Level-2A processing / SCL: https://sentinels.copernicus.eu/web/sentinel/user-guides/sentinel-2-msi/product-types/level-2a
- NISAR GCOV product guide: https://nisar-docs.asf.alaska.edu/gcov/