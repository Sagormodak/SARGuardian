# RiverShift — NASA Space Apps 2026 Judge Guide

**Challenge:** Dancing with the SARs  
**Category:** Earth Science  
**Project:** RiverShift — NISAR-powered river and surface-change observatory  
**Status:** Research-screening prototype; outputs are provisional unless an independently documented review is attached.

## One-minute overview

RiverShift lets a user draw an area of interest (AOI), choose an event/date window and inspect the actual NISAR acquisitions available for that area. It then screens comparable NASA–ISRO NISAR Level-2 GCOV observations for changes in radar-derived open-water coverage and persistent land/water transitions. The results are displayed as checksum-checked, colour-coded footprints on a Google Maps Satellite basemap, with a discrete playback across the observed acquisition dates.

The product is designed to answer four questions:

1. Where did the observed radar water classification change?
2. Which persistent land-to-water transitions are erosion candidates?
3. Which persistent water-to-land transitions are deposition candidates?
4. Which actual NISAR acquisition dates and source products support each map frame?

RiverShift is an evidence-screening and communication tool, not an operational flood-warning service or a substitute for field surveying.

## Why this matters

Riverbank erosion, channel migration and floodwater changes can threaten settlements, agricultural land, transport routes and river infrastructure. Optical imagery can be limited by cloud, haze and illumination; SAR provides an all-weather, day/night observation capability. NISAR's L-band radar observations provide a new, repeatable data source for studying these changes.

RiverShift focuses on making those observations easier to explore: users select the area, while the application discovers where within that area the radar-derived change candidates occur. The user does not have to know the exact target pixel or river segment in advance.

## Data sources and how each is used

| Source | Role in RiverShift | Important boundary |
|---|---|---|
| **NASA–ISRO NISAR Level-2 GCOV** | Primary measurement input. RiverShift discovers actual GCOV acquisitions, validates comparable metadata and screens radar-derived open-water and persistent land/water transitions on valid common support. | This is a radar-derived screening classification, not direct bathymetry, sediment volume, surveyed bankline or proof of flood causality. |
| **ASF DAAC / NASA Earthdata** | Catalogue discovery and exact-granule access for NISAR. Source granule identifiers, acquisition metadata and checksums are retained. | Catalogue footprint intersection does not guarantee valid raster coverage. |
| **NASA/JPL OPERA DSWx-S1 V1 (Sentinel-1 C-band)** | Separate retained-run cross-sensor reference workflow. It searches the same AOI and creates a conservative WTR reference when an eligible scene exists. Only WTR class 0 (not water) and class 1 (open water) can enter agreement analysis. | It is not field truth. OPERA is a 30 m product with limitations for narrow channels and small bank changes. In Run #36's AOI no WTR scene was found within the ±30-day discovery window, so no reference GeoTIFF, common-support score, F1 or IoU was produced. |
| **NASA/JPL OPERA RTC-S1 V1 (Sentinel-1 C-band)** | Diagnostic acquisition inventory used when no DSWx WTR scene is available. It records burst dates and VV/VH/MASK availability. | RTC-S1 is gamma0 backscatter, not water/non-water labels. The inventory did not generate a reference mask or agreement metrics. |
| **FFWC / BWDB river gauge data** | Potential ancillary hydrological-stage context for the Jamuna/Sirajganj reach (e.g. gauge SW49). | Not used in Run #36's classification, thresholds or reported areas. A point gauge is not a spatial water-mask reference and must not be described as validation unless exact dated observations are retained and explicitly linked to the AOI. |
| **Google Maps Satellite (Google Maps Platform)** | Third-party visual basemap for geographic orientation and communication of AOI/result footprints. | Basemap imagery is not an analysis input or independent validation dataset. Required imagery-provider attribution remains visible. |
| **Copernicus Sentinel-2 L2A (legacy optional tool)** | A standalone CLI can compare a supplied NISAR mask with clear-support SCL and B03/B11 MNDWI. | It is not the primary monsoon reference pathway and is not part of the default worker. The 2026-08-18 scene for the Run #36 AOI had 97.957% reported cloud cover and only 0.1554% common valid support; no optical agreement metrics were published. Do not present it as corroboration. |

**Why the validation design is radar-first:** monsoon cloud cover makes a cloud-free optical reference an unreliable requirement for a Bangladesh river event. OPERA DSWx-S1 is therefore the first cross-sensor search, but no eligible WTR scene was found for this particular AOI/date. Absence of a suitable reference means **NO_SCORE**, not a zero score and not proof that the NISAR output is wrong.

Official product references: [OPERA DSWx-S1 V1 at PO.DAAC](https://podaac.jpl.nasa.gov/dataset/OPERA_L3_DSWX-S1_V1) · [OPERA DSWx-S1 product specification](https://www.earthdata.nasa.gov/data/catalog/podaac-opera-l3-dswx-s1-v1-1)

## Reproducible workflow

1. **AOI and dates:** User draws a WGS84 AOI and selects a date window and event date.
2. **Catalogue discovery:** The worker discovers real NISAR GCOV granules from ASF DAAC and applies a comparability/coverage audit.
3. **Exact product selection:** It pins the selected granule names, maturity, orbit/frame, frequency/polarization term, acquisition dates and source provenance.
4. **Download and extraction:** Product workers download exact granules, verify HDF5 structure and export AOI-clipped rasters.
5. **Water time series:** The workflow classifies open-water candidates on a common valid spatial support for each actual acquisition date.
6. **Flood-period screen:** Newly water-covered pixels are screened relative to the pre-event reference.
7. **Persistent morphology screen:** Persistent land-to-water and water-to-land transitions are identified across the configured post-event observations.
8. **Map and playback:** Each display frame is generated from its own binary raster mask, tied to the source mask by SHA-256, and shown as a discrete actual observation.
9. **Private retention:** Full-resolution products and scientific outputs are retained in the configured private Google Drive job folder; the public repository contains code and tests, not private user data or raw multi-gigabyte NISAR granules.

## What the current classes mean

- **Red — erosion candidate:** Land in the pre-event mask that is classified as water in both configured post-event observations.
- **Green — deposition candidate:** Water in the pre-event mask that is classified as land in both configured post-event observations.
- **Blue — newly water-covered / observed open-water candidate:** Water detected where the comparison reference did not classify water.

These are candidate classes. The red/green persistence rule reduces transient one-date changes, but it does not independently prove bank erosion, sediment deposition, sediment thickness, or the physical cause of the transition.

The morphology script reports an unsigned symmetric boundary-distance proxy. It does not infer a signed bank-migration direction or a river-centreline shift. Signed movement requires dated banklines and independently oriented transects; the standalone transect tool rejects ambiguous intersections and uses the declared transect direction for the sign.

## Time-series semantics

The playback is a sequence of **actual NISAR acquisition dates**. It is not daily data. No temporal interpolation, forecast, or synthetic intermediate state is presented as a satellite observation. If a requested period has insufficient comparable acquisitions, the workflow should report insufficient support rather than invent a continuous animation.

## Display previews versus measurements

The map-preview GeoJSON is a display-only footprint built from a lower-resolution fractional-occupancy representation of the full-resolution binary mask. A positive source pixel that overlaps a preview cell is retained as a visible footprint. Preview geometry is not a survey-grade boundary and must not be used to recalculate area or displacement.

The full-resolution masks, full-resolution scientific GeoJSON, analysis reports, source granule receipts and SHA-256 values remain the authoritative retained outputs. The preview file records its source-mask SHA-256, source and preview dimensions, source candidate-pixel count and method. A non-empty source mask that produces an empty preview is a processing failure; an empty preview is accepted only when the source mask contains no candidate pixels.

## Example run — provisional screening output

The latest retained RiverShift processing example is [Run #36](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41803576163). It used six actual NISAR GCOV observation dates from **2026-06-30 to 2026-09-10**, for an event date of **2026-07-28** and an event-proximal observation on **2026-08-17**.

The worker reported these provisional screening candidates:

| Run #36 output | Reported value |
|---|---:|
| Newly water-covered candidate area | **17.6721 km²** |
| Persistent erosion candidate area | **1,244.230 ha** |
| Persistent deposition candidate area | **5,078.140 ha** |
| Actual NISAR observation dates | **6** |

These values describe that specific AOI, selected products, threshold and comparison window. They are **not independently field-validated**, and they do not establish sediment volume, signed bankline movement, flood causality or exposed-population counts. An older draft contained different values from an earlier run; those older values must not be attributed to Run #36.

The retained processing log records successful source provenance checks, the six-date time series, candidate-mask generation, preview generation and 51 validated output files at package assembly. Private Drive upload receipts and remote checksum checks passed. The result remained **PROVISIONAL**. **Historical-run limitation:** Run #36 predates backend PR #151, which integrated the full-resolution candidate-mask overlap audit into the live worker. Its retained artifact manifest does not contain `candidate_mask_overlap_audit.json`, and its summary has no source-mask pairwise overlap metrics. We have not retroactively computed those values from its private masks; do not claim that Run #36 passed the full-resolution overlap audit. New jobs on main now retain `outputs/quality-assurance/candidate_mask_overlap_audit.json` and return both source-mask and preview-overlap diagnostics. A fresh RiverShift run is still required to populate the dashboard overlap panel.

### Independent reference outcome for Run #36

The separate [OPERA DSWx-S1 replay #41900559056](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41900559056) reused the retained NISAR mask and exact prepared manifest; it did not rerun NISAR processing. NASA CMR returned 307 OPERA DSWx-S1 granules intersecting the AOI across the collection history. After local sensing-date filtering over **2026-07-18 to 2026-09-16**, 287 WTR assets were outside the discovery window, 20 returned granules were not WTR assets, and **no eligible WTR scene remained inside the 30-day discovery window**.

The diagnostic OPERA RTC-S1 inventory returned 2,093 AOI granules and 2,020 VV burst groups, but its nearest acquisition was **2026-06-26 (52 days before 2026-08-17)**. That is outside both the ±30-day discovery window and the strict ±3-day scoring gate; RTC-S1 is backscatter, not a water label. Consequently, no OPERA reference GeoTIFF or agreement metrics were created. The correct scientific outcome is **NO_MATCH_NO_SCORE / PROVISIONAL**, not 0% accuracy and not independent validation.

The replay successfully uploaded its diagnostic report, validation status and private Drive receipt with remote checksum verification. The GitHub Action is deliberately red because the independent-reference metrics gate did not pass; this prevents a no-score result from appearing green.

## Independent validation pathway

RiverShift keeps three kinds of evidence separate:

1. **Primary measurement:** actual NISAR GCOV observations and the resulting radar-derived water/change candidates.
2. **Cross-sensor SAR comparison:** an eligible OPERA DSWx-S1 WTR mask may be compared to the retained NISAR water mask on the exact same grid. The score is permitted only when sensing dates are within **±3 days** and at least **80% of NISAR-valid pixels** have valid OPERA labels. Only WTR classes 0 and 1 are labelled; inundated vegetation, masked and unknown classes remain NoData.
3. **Hydrological or field context:** FFWC/BWDB stage observations, dated banklines, field surveys or other sources may support interpretation only when the source, exact timestamp, station/location, datum and method are documented. A river gauge is point context, not a pixel-wise water classification reference.

For Run #36, the OPERA WTR search had no eligible scene within ±30 days and the nearest RTC-S1 acquisition was 52 days before the target NISAR date. Therefore **no independent water-mask agreement score is available**. The optional Sentinel-2 tool also did not provide a usable reference: its 2026-08-18 candidate had 97.957% cloud cover and only 0.1554% common valid support. Neither dataset is presented as validation.

A formal validation pack for a future event should include:
- a separately prepared, independently reviewed water/non-water reference for the same AOI and a date within the declared scoring gate;
- a documented labeling/class interpretation protocol, source IDs and checksums;
- common-support fraction and NoData accounting before confusion metrics;
- confusion matrix, precision, recall, F1, IoU, area bias and uncertainty/sensitivity where the gate passes;
- dated, independently interpreted banklines and oriented transects before signed migration is claimed;
- gauge/rainfall records only as ancillary temporal context, not as substitutes for a spatial reference mask.

The standalone signed-bankline tool requires independently prepared dated banklines and oriented transects. A user must specify the positive transect direction. RiverShift must not infer a signed direction from the symmetric morphology metric.

**No-score policy:** missing or temporally mismatched reference data is `NO_MATCH_NO_SCORE` / `BLOCKED_NO_SCORE`, never a zero accuracy score. The release remains `PROVISIONAL` and review-required until an appropriate independent review exists.

The legacy `validate_with_sentinel2.py` tool and retained-run workflow remain available for contexts where optical clear support is genuinely adequate, but they are not the monsoon validation strategy for this Run #36.

## Known limitations

- NISAR acquisition dates are discrete; time-series availability depends on product maturity, acquisition geometry and valid raster coverage.
- A catalogue footprint intersecting an AOI does not guarantee every pixel is valid after processing.
- Water classification depends on the chosen frequency, diagonal covariance term, thresholding method and valid-data mask.
- Newly water-covered and persistent land/water transitions are candidate classes, not independently confirmed flood, erosion or deposition.
- The current automatic workflow does not establish signed bankline migration, sediment thickness/volume, water depth or flood causality.
- OPERA DSWx-S1 V1 did not provide an eligible WTR scene for Run #36 within the ±30-day discovery window. RTC-S1's nearest AOI acquisition was 52 days earlier and cannot be promoted into a ±3-day water reference.
- The August 2026 Sentinel-2 scene was too cloudy (97.957% reported cloud cover; 0.1554% common support) to produce comparison metrics. It is not corroboration.
- FFWC gauge SW49 is a possible stage-context source, but a dated gauge value was not included in Run #36 and would not be a spatial water-mask reference.
- Google Satellite is a visual context layer only, not a measurement source.
- All Run #36 area values and the current project output remain **PROVISIONAL**; absence of validation does not mean zero change.

## Public code and evidence

- Live application: https://sar-guardian-dynamic-lilac.vercel.app
- Backend science worker: https://github.com/moshiour0/SARGuardian-backend
- Interactive application: https://github.com/moshiour0/SARGuardian_Dynamic
- RiverShift processing source: https://github.com/moshiour0/SARGuardian-backend/tree/main/tools/river_shift
- Optional Sentinel-2 cross-sensor tool: https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/validate_with_sentinel2.py
- Sentinel-2 cross-sensor tool guide: https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/README_11_validate_with_sentinel2.md
- Retained Run #36 processing evidence: https://github.com/moshiour0/SARGuardian-backend/actions/runs/41803576163
- OPERA DSWx-S1 no-match diagnostic replay: https://github.com/moshiour0/SARGuardian-backend/actions/runs/41900559056
- NASA Space Apps 2026 challenge: https://www.spaceappschallenge.org/2026/

## Demo storyboard (about 2 minutes)

1. Start on the RiverShift page and explain that NISAR GCOV—not the basemap—is the analysis input.
2. Draw a small AOI around a river reach and choose a date range.
3. Show the ASF DAAC catalogue and explain exact acquisition comparability and why insufficient support stops analysis.
4. Show the real NISAR observation dates and play the time series. Point out that each frame is an actual acquisition.
5. Turn attention to red, green and blue layers; explain each as a candidate, not ground truth.
6. Open the Run #36 metrics and provenance; show the source granule IDs, checksums and that the areas are candidate-only.
7. Show the OPERA DSWx-S1 replay report. Explain that no eligible reference existed within the date window, so the system correctly published NO_MATCH_NO_SCORE rather than inventing an accuracy score. End with the need for a date-appropriate independent water reference and field/bankline evidence before a VERIFIED claim.

## Score-sheet evidence checklist

| Criterion | Evidence to present | Remaining human action / risk |
|---|---|---|
| Impact | Riverbank / flood-change use case, AOI-specific candidate maps and bounded area metrics. | Add a sourced local impact story and independently sourced exposure only if available; do not imply lives/assets saved. |
| Creativity | User-drawn AOI, target-free change discovery, discrete radar time series, explainable classes and private provenance. | A polished end-to-end demo is still needed. |
| Validity | Product comparability checks, common-valid support, source hashes, synthetic raster/mosaic/replay tests, retained-artifact checksum checks, and provisional release status. Backend main at 93d2f746: 249 RiverShift tests passed; 585 repository regression tests passed (1 skipped); 180 maintained science-engine tests passed; AOI/static parser checks passed. | OPERA DSWx-S1 and RTC-S1 inventory found no eligible reference near 2026-08-17; Sentinel-2 was too cloudy. Independent same-AOI water reference and field/bankline validation remain the main scientific gap. Signed transect measurement still requires independently digitized banklines. |
| Relevance | NISAR Level-2 GCOV is the primary measurement input; challenge name is explicit. | Explain what radar contributes and why NISAR observations are central. |
| Presentation | Google Satellite result map, red/green/blue classes, observed-date playback, report and this judge guide. | Record a clear two-minute demo and finish project-page text. |
| Teamwork | Actual commits, issue/PR history and documented roles. | Team must supply truthful member names, roles and evidence of collaboration. |
| User experience | Draw-AOI workflow, discovery/processing distinction, map legend, source date and warnings. | Do a first-time-user test and remove unresolved setup friction. |
| NASA data usage | NISAR GCOV is the primary analysis source; ASF DAAC provides exact product access/provenance; Copernicus Sentinel-2 L2A was used in two three-tile same-datatake mosaics; Google Satellite is contextual basemap only. | NISAR remains the central measurement source. The retained Run #36 OPERA cross-check correctly returned NO_MATCH_NO_SCORE; the cloudy Sentinel-2 candidate also had no metrics. Keep all source roles and limitations visible. |
| Challenge category | “Dancing with the SARs” / Earth Science identified in the UI and project text. | Verify the exact category label shown in the team's official project form. |
| Repository access | Public backend and Dynamic GitHub repositories. | Verify links in a signed-out browser before final submission. |
| Project page | This guide and a ready-to-copy project-page draft. | Team must fill required fields and click Submit during the NASA submission window. |

### Team participation and rubric notes

The public NASA Space Apps 2026 information checked on **4 November 2026** confirms the challenge schedule and team cap, but does not publish a global judging score sheet or a women-participation **+5%** bonus on the public event page. Do not present that bonus as an official NASA global rule. If a Local Event or organiser supplies a separate scoring rubric containing such a bonus, cite that exact local document and label it **local-event-specific**; do not transfer it to Global Judging without official confirmation.

The team page should list only real members and their actual contributions. The official event page is https://www.spaceappschallenge.org/2026/.

