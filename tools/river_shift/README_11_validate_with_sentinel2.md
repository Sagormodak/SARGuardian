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

Scene selection first groups eligible STAC items by the same Sentinel-2 platform, `s2:datatake_id`, acquisition date and processing baseline. It then ranks each datatake group by union footprint coverage, date proximity and mean cloud cover. Adjacent MGRS tiles from the winning group are mosaicked onto one B11 20 m grid expanded to the full NISAR mask extent. Duplicate records for one MGRS tile are reduced to the latest processing generation. The canonical STAC properties `processing:version` and `processing:datetime` are preferred; legacy Sentinel-2 aliases remain supported. No different date, platform, datatake or processing baseline is combined.

## Outputs

The script writes `sentinel2_cross_sensor_agreement.json` containing:
- exact STAC collection, all selected item IDs, datatake ID, processing baseline, MGRS tiles, per-tile generation time, platform, acquisition date/time and cloud cover;
- unsigned source B03/B11/SCL asset hrefs (temporary signed URLs are not retained);
- NISAR input filename and SHA-256;
- date offset, union footprint overlap, clear common support and per-tile clear-pixel contribution;
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
- A same-datatake mosaic can combine adjacent MGRS tiles, but it cannot remove clouds, shadow, snow or missing optical coverage. A mosaic may still fail the 80% common-support gate; do not weaken that gate or report metrics from only a small subset.
- Cross-sensor agreement does not prove sediment deposition, erosion causality, bankline movement or flood depth.
- Results remain provisional until a reviewer verifies scene suitability, co-registration, temporal comparability and reference quality.

## Retained-run mosaic replay evidence

Two retained-data comparisons were performed from source RiverShift run `41642281327`. The final tile-level replay is [GitHub Action run #41713046884](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41713046884). Each Sentinel-2 mosaic combines three MGRS tiles from one platform, acquisition date, datatake and processing baseline; the union of tile footprints covers **100% of the NISAR AOI footprint** in both comparisons.

### NISAR 2026-07-12 → Sentinel-2 2026-07-02

- Sentinel-2 datatake: `GS2B_20260702T043659_048679_N05.12`; processing baseline: `05.12`.
- MGRS tiles: `46RBP`, `45RZJ`, `45RYJ` (3 tiles; primary item `S2B_MSIL2A_20260702T043659_R033_T46RBP_20260702T082247`).
- Mean / maximum scene cloud cover: **73.31% / 73.89%**.
- Clear common support: **11.03%**.
- Non-overlapping clear common-support pixels contributed to the mosaic: `45RYJ` **290,688**; `45RZJ` **332**; `46RBP` **4,035**.

### NISAR 2026-09-10 → Sentinel-2 2026-09-15

- Sentinel-2 datatake: `GS2C_20260915T043701_010585_N05.12`; processing baseline: `05.12`.
- MGRS tiles: `45RYJ`, `45RZJ`, `46RBP` (3 tiles; primary item `S2C_MSIL2A_20260915T043701_R033_T45RYJ_20260915T074111`).
- Mean / maximum scene cloud cover: **49.35% / 55.54%**.
- Clear common support: **45.34%**.
- Non-overlapping clear common-support pixels contributed to the mosaic: `45RYJ` **1,245,168**; `45RZJ` **2,644**; `46RBP` **1,697**.

Both comparisons returned `INSUFFICIENT_OPTICAL_SPATIAL_SUPPORT`, below the unchanged **80%** threshold. F1, IoU and other agreement metrics were therefore **not calculated** for either date. The mosaics achieve full AOI footprint coverage, but clouds and local SCL validity limit the clear optical support. These are valid no-score outcomes, not zero agreement and not evidence that the NISAR classification is wrong. They do not corroborate erosion/deposition candidates or prove field conditions.

## Primary references

- Copernicus Sentinel-2 data collection: https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-2
- Microsoft Planetary Computer STAC API: https://planetarycomputer.microsoft.com/api/stac/v1/
- Planetary Computer SAS signing: https://planetarycomputer.microsoft.com/docs/concepts/sas/
- Sentinel-2 Level-2A processing / SCL: https://sentinels.copernicus.eu/web/sentinel/user-guides/sentinel-2-msi/product-types/level-2a
- NISAR GCOV product guide: https://nisar-docs.asf.alaska.edu/gcov/
## Replay an existing RiverShift run without downloading raw NISAR again

A manual GitHub Actions workflow is available at `.github/workflows/river-shift-sentinel2-retained-replay.yml`. It retrieves the small per-product AOI COG artifacts and prepared manifest from an earlier RiverShift worker run, verifies their worker receipts and SHA-256 values, rebuilds the original six-date water series with the exact recorded Otsu/manual threshold, then compares the chosen observation date against Sentinel-2.

To run it, open **Actions → RiverShift retained-run Sentinel-2 cross-sensor replay → Run workflow** in the backend repository. Supply:
- `source_run_id`: a completed run whose per-product artifacts have not expired (the example run is `41642281327`);
- `observation_date`: a date in that run's exact selected acquisition list (the example default is `2026-07-12`);
- the date offset, cloud ceiling, MNDWI threshold and minimum clear common-support fraction.

The workflow reads retained AOI COGs and receipts only. It does not download raw multi-gigabyte HDF5 NISAR granules, change the original run, or run as part of normal RiverShift processing. The summary exposes the selected Sentinel-2 item and comparison metrics only; the full report, water masks, AOI coordinates and asset URLs remain on the temporary Actions runner and are not uploaded as public artifacts.

A no-match or low-support result is a valid explicit outcome. No comparison score is invented, and the original NISAR run remains PROVISIONAL until independent human review.