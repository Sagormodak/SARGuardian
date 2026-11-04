# RiverShift scientific validation, overlap QA and release plan

**Scope:** RiverShift only. This plan does not change Landslide, Known Place Analysis or Find Displacements.

## 1. Output contract

RiverShift produces evidence-screening candidates, not automatically confirmed geomorphic events. Every successful worker run remains `PROVISIONAL` until independent reference evidence has been reviewed and a signed verification record is attached.

Keep these products separate:

- **Observed-date open-water extent:** water-screening mask for one actual NISAR acquisition date.
- **New-water candidate:** baseline non-water -> first comparison-date water. It is relative to the selected date pair, not automatically a flood extent.
- **Persistent erosion candidate:** baseline land -> water in both later morphology observations.
- **Persistent deposition candidate:** baseline water -> land in both later morphology observations.
- **Exposed bar / char candidate:** future class requiring stage-aware sediment/bar evidence. It must not be aliased to deposition.
- **Persistent char:** future object-level class requiring repeat observations and preferably optical or field confirmation.

An acquisition date is an actual observation. Never create daily synthetic observations or infer a missing event date.

## 2. Mandatory data gates

Before pixel-wise analysis:

1. Keep one GCOV maturity, frequency, diagonal covariance term, polarization configuration, compatible orbit direction/relative orbit, frame and acquisition mode.
2. Verify exact source granule identity, download receipt, HDF5 inventory and SHA-256 provenance.
3. Require the output COG sidecar to match the actual raster checksum.
4. Require the same CRS, dimensions and affine transform for pixel-wise comparison. Reprojection must be explicit and recorded.
5. Distinguish catalogue footprint coverage from valid raster coverage and from common temporal support.
6. Record per-date valid-pixel fraction and multi-date common-valid-pixel fraction. A catalogue footprint percentage is not a substitute for either.
7. For same-date multi-granule mosaics, record pairwise overlapping valid pixels and linear-gamma0-to-dB differences after nearest-neighbour alignment to the final mosaic grid. This is a diagnostic, not a universal pass/fail dB threshold.

If a provenance or exact-grid requirement fails, stop the affected comparison. Do not treat missing or invalid pixels as zero or non-water.

## 3. Candidate overlap audit

The full-resolution binary masks are authoritative. The worker writes:

`outputs/qa/candidate_overlap_audit.json`

It records:

- Per-class positive pixel count, valid support and source-mask SHA-256.
- Pairwise intersection, union, Jaccard and overlap fraction of the smaller class.
- Shared valid support for each pair.
- Triple intersection on common valid support.
- The selected temporal basis for each class.

Erosion and deposition are mutually exclusive by construction for one morphology comparison. Any full-resolution overlap between these two classes on shared valid support is a processing-contract failure and stops publication.

New-water may overlap with erosion or deposition because it is derived from a different date comparison. That overlap is not automatically an error; it must be interpreted with its acquisition dates.

The map preview is a lower-resolution display representation. The current preview uses average occupancy and retains any positive occupancy. It can expand sparse patches and create apparent cross-class overlap. The combined preview metadata now records pairwise geometry intersection areas, Jaccard and intersection fraction of the smaller preview class in the projected analysis CRS. Compare those preview-scale statistics with the full-resolution mask overlap report to identify overlap introduced by generalisation. Never calculate area, displacement or validation metrics from preview GeoJSON.

## 4. Water classification validation

The baseline classifier is low-backscatter screening:

`water_candidate = valid AND gamma0_dB <= threshold_dB`

For linear GCOV power:

`gamma0_dB = 10 * log10(gamma0_power)`

This is an open-water screen, not a universal water classifier. Known failure modes include smooth bare soil, radar shadow, speckle, flooded vegetation and double-bounce scattering.

The threshold must be selected and evaluated against independent references. Compare at least:

- Combined-date Otsu (exploratory baseline).
- Fixed site-specific threshold calibrated on a training subset.
- An adaptive/edge-informed or seasonally constrained threshold candidate.

Keep spatially separated reaches and acquisition dates for held-out evaluation. Do not tune and evaluate on the same reference pixels. Report threshold sensitivity separately from statistical uncertainty.

For every independent reference mask, report TP/TN/FP/FN, precision, recall, specificity, F1, IoU, Cohen's kappa, water-area bias, valid sample count and spatial-block uncertainty where enough independent blocks exist. Include the reference source, acquisition date, cloud/shadow filtering, classification method and reviewer assessment. Sentinel-2 is an independent sensor reference, not automatically ground truth.

## 5. Morphology and bankline validation

A persistent land/water transition is a candidate zone, not proof of erosion, deposition or flood causality.

- Compare observations at similar hydrological stages where possible.
- Keep channel thread, outer active-channel belt, exposed bar and persistent char concepts separate.
- Report the symmetric boundary-distance proxy as unsigned boundary difference only.
- A signed bank migration rate requires independently prepared dated banklines and oriented transects, with positional uncertainty and a clear sign convention.
- A char claim requires multi-date object tracking and evidence that separates persistent accretion from temporary exposure caused by falling water level.
- Consider bank protection, dredging, sand mining, embankments and seasonal stage before causal interpretation.

Use field GPS/RTK, UAV, authoritative gauge/cross-section records or high-resolution independent imagery where available. A reference date should be as close as practical to the NISAR acquisition and represent the same hydrological condition.

## 6. Release states

- `STRUCTURAL_PASS`: provenance, product compatibility, raster geometry and processing contracts passed.
- `VALIDATION_METRICS_COMPUTED_REVIEW_REQUIRED`: independent comparison metrics were computed, but independence/reference quality still requires review.
- `SCIENTIFICALLY_VALIDATED`: an independent reference, sampling design, quantitative metrics and uncertainty have been accepted by a named reviewer.
- `HUMAN_REVIEWED`: the complete interpretation, provenance and evidence package has a valid review record.

A successful Action, checksum match or non-empty map preview never changes `PROVISIONAL` to `SCIENTIFICALLY_VALIDATED`.

## 7. Overlay interaction contract

The map must allow independent visibility controls for:

- Erosion candidate
- Deposition candidate
- New-water candidate
- All available candidate classes
- Observed-date open-water extent

The future exposed-bar/char control remains disabled until that class has an implemented method and output contract. Do not silently map char to deposition.

Each candidate feature should retain its class identity. A popup/legend should show date basis, source observations, display-only status and the warning that preview geometry is not a measurement. Overlay selection changes display only; it must not modify source masks, reports or metrics.

## 8. Acceptance gates for future classes

A new class is not production-ready until it has:

1. A documented physical definition and explicit temporal basis.
2. A method suitable for NISAR's available resolution and observation geometry.
3. Independent reference data and a documented sampling protocol.
4. Per-class confusion metrics and uncertainty on held-out reaches/dates.
5. Sensitivity tests for water level, threshold, registration and minimum mapping unit.
6. Source provenance, full-resolution raster/vector outputs, checksums and map-preview parity tests.
7. An explicit provisional/validated status in reports and UI.

## 9. Research and product references

- [ASF / NASA NISAR GCOV guide](https://nisar-docs.asf.alaska.edu/gcov/)
- [NISAR data format guide](https://nisar-docs.asf.alaska.edu/data-format/)
- [NASA CMR Search API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html)
- [ASF Search documentation](https://docs.asf.alaska.edu/asf_search/searching/)
- [Copernicus Sentinel-2 collection](https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-2)
- [Dynamic threshold SAR flood mapping in northeastern Bangladesh, IEEE JSTARS (2025)](https://doi.org/10.1109/JSTARS.2025.3647843)
- [Sandbar mapping with Sentinel-2 and water-gauge data, ISPRS Archives (2026)](https://doi.org/10.5194/isprs-archives-XLIX-B3-2026-839-2026)
- [USGS: measuring channel planform change and uncertainty](https://www.usgs.gov/publications/measuring-channel-planform-change-image-time-series-a-generalizable-spatially)

These references guide method design; none provides an accuracy score for SARGuardian/RiverShift itself.
