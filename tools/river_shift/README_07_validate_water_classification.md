# 07 · Validate binary water classification

## Purpose
Compare RiverShift's predicted water mask against a separately produced, independently reviewed reference mask and calculate classification metrics.

## NASA challenge relevance
Scientific validity is a major NASA Space Apps score criterion. This script creates transparent quantitative evidence rather than relying on visually convincing map layers or self-reported accuracy.

## Inputs
- Prediction GeoTIFF: 1=water, 0=non-water, NoData excluded.
- Independent reference GeoTIFF on the exact same grid.
- Reference source, reference date and reference production method.
- Both rasters must use the same projected metre-based CRS, affine transform and dimensions.

## Method
1. Validate the reference provenance fields.
2. Require exact grid alignment and projected metre units.
3. Exclude pixels invalid in either raster.
4. Compute TP, TN, FP and FN.
5. Calculate accuracy, precision, recall, specificity, F1, IoU, Cohen's kappa and water-area bias.
6. Resample spatial blocks with replacement and calculate percentile intervals for the classification metrics when at least 20 blocks contain valid pixels.
7. Match the prediction checksum to a binary-mask output in the adjacent RiverShift report and carry forward the source granule IDs/checksums; otherwise mark validation provenance incomplete.
8. Save the full confusion matrix, input hashes, reference metadata and uncertainty interpretation.

Definitions:
    Precision = TP / (TP + FP)
    Recall = TP / (TP + FN)
    F1 = 2 * Precision * Recall / (Precision + Recall)
    IoU = TP / (TP + FP + FN)

## Reproduce
    python validate_water_classification.py --prediction results/flood/during_water_mask.tif --reference validation/sentinel2_reference_mask.tif --reference-source "Sentinel-2 SR supervised reference" --reference-date 2026-07-02 --reference-method "Cloud-screened Sentinel-2 water index with manual polygon review" --block-size-pixels 64 --bootstrap-replicates 500 --random-seed 42 --out results/validation/water_validation.json

The reference method is illustrative. Document how the actual mask was generated, including cloud filtering, class rules, manual edits and date mismatch.

## Outputs
- JSON confusion matrix.
- Accuracy, precision, recall, specificity, F1, IoU, kappa and area-bias statistics.
- Provenance fields for the reference source and date.
- Spatial block-bootstrap 95% intervals, or an explicit too-few-blocks status below 20 blocks.

## Acceptance tests
- Missing reference provenance fails.
- Non-binary prediction or reference values fail.
- Empty overlap or mismatched grid fails.
- Confusion-matrix counts sum to the valid sample count.
- Metrics match the confusion matrix.
- Accuracy is never claimed as a substitute for F1/IoU under class imbalance.

## Related optional comparison

For a separate, automated Copernicus Sentinel-2 L2A cross-sensor screen that searches scenes and compares SCL/MNDWI classifications without requiring a manually prepared exact-grid reference, see [README_11_validate_with_sentinel2.md](README_11_validate_with_sentinel2.md) and `validate_with_sentinel2.py`. This does **not** replace the independent reference-mask workflow above and does not by itself establish ground truth.

## Scientific limitations
- Sentinel-2 is an independent reference source, not automatically ground truth.
- Optical reference masks may have cloud, shadow, water-index and acquisition-date errors.
- Reference and NISAR acquisition dates should be as close as possible to the same hydrological condition.
- Report the reference method and sampling design, including class balance and uncertainty.
- Bootstrap intervals quantify variation among the chosen spatial blocks only; they do not cover reference error, sensor error, geolocation or temporal mismatch. Fewer than 20 valid blocks yields no interval.
- Computed metrics remain PROVISIONAL until a reviewer verifies reference independence and quality.
- A random pixel split can overstate generalization because nearby pixels are spatially autocorrelated. Prefer spatially separated validation samples.

## AI reviewer checklist
- Verify reference independence and metadata.
- Verify the confusion matrix is present.
- Verify F1 and IoU are reported in addition to accuracy.
- Verify no accuracy percentage is invented or hardcoded.
- Verify validation date and method accompany reported metrics.

## Primary references
- NISAR GCOV guide: https://nisar-docs.asf.alaska.edu/gcov/
- Sentinel-2 data: https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-2
- Google Dynamic World: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1
