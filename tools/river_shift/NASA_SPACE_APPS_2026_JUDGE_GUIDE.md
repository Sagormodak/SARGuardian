# RiverShift — NASA Space Apps 2026 Judge Guide

**Challenge:** Dancing with the SARs  
**Category:** Earth Science  
**Project:** RiverShift — NISAR-powered river and surface-change observatory  
**Status:** Global, AOI-driven NISAR river-change screening workflow. Each result carries its own source provenance, quality checks and scientific review state.

## One-minute overview

RiverShift is a global, AOI-driven river-change screening application powered by NASA–ISRO NISAR L-band GCOV observations. A user selects a river reach anywhere in the mission's global land-observation footprint, chooses a date window, and the system discovers the compatible GCOV acquisitions actually available for that geometry. It screens radar-derived open-water coverage and persistent land/water transitions, then displays checksum-linked candidate layers and discrete playback across real acquisition dates. The Jamuna–Chowhali run is the demonstration case; the input and discovery workflow is not country-specific.

The product is designed to answer five questions:

1. Where did the observed radar water classification change?
2. Which persistent land-to-water transitions are erosion candidates?
3. Which persistent water-to-land transitions are deposition candidates?
4. Which mapped buildings and selected public facilities coincide with those candidate preview zones?
5. Which actual NISAR acquisition dates, source products and independent-validation gaps support interpretation?

RiverShift is an evidence-screening and communication tool, not an operational flood-warning service or a substitute for field surveying.

## Global applicability — one workflow, many river systems

RiverShift is **geographically reusable, not Bangladesh-specific**. A user supplies the WGS84 area of interest and observation window; the backend sends that geometry and time range to NASA's Common Metadata Repository (CMR) for NISAR L-band GCOV discovery. The worker then selects compatible acquisitions for that AOI. There is no country allow-list and no fixed Jamuna polygon in the RiverShift discovery request.

This design follows the NISAR mission's global land-observation programme. NASA describes NISAR coverage as global with L-band global acquisitions and a nominal 12-day exact repeat cycle. ASF's availability guide reports L-band collection over nearly all global landmasses since August 2025; PROVISIONAL L-band products are available for acquisitions from 17 June 2026 onward as processing is released. The exact acquisition catalogue—not a presumed daily schedule—determines what can be processed for a selected location.

**Current RiverShift operating envelope**

- One valid, single-ring WGS84 Polygon AOI, up to **1,000 km²**.
- An observation window no longer than **366 days**.
- At least **four distinct NISAR GCOV acquisition dates** in the requested window.
- At least **90% catalogue-footprint coverage** of the AOI for each selected acquisition date, followed by worker-side checks of compatible orbit/frame, product maturity, frequency/covariance term, native HDF5 layers and valid raster support.
- The worker uses actual acquisition dates (up to 12 selected dates and up to four same-date granules per date); it does not synthesize daily observations.

This means the same workflow can be applied to a selected river reach in any country within the NISAR L-band observation footprint when the requested window contains sufficient compatible GCOV data. A broad region or an entire country is not submitted as one job; the user selects a manageable AOI. The Jamuna–Chowhali result is a concrete demonstration case, not the geographical boundary of the product.

Global applicability describes the reusable input and processing architecture. Scientific interpretation and any independent validation evidence remain tied to the actual acquisitions and reference data available for each AOI.

**Primary mission/data references:** [NASA NISAR Mission Overview](https://science.nasa.gov/mission/nisar/mission-overview/) · [ASF NISAR Data Availability](https://nisar-docs.asf.alaska.edu/availability-overview/) · [ASF/NISAR Reference Observation Plan — interactive global acquisition map](https://experience.arcgis.com/experience/6052a864cd01459393884a7f751558e3) · [ASF PROVISIONAL L-band Data Search](https://search.asf.alaska.edu/) · [NASA NISAR Observation Strategy](https://science.nasa.gov/mission/nisar/observation-strategy/).

## Why this matters

Riverbank erosion, channel migration and floodwater changes can threaten settlements, agricultural land, transport routes and river infrastructure. Optical imagery can be limited by cloud, haze and illumination; SAR provides an all-weather, day/night observation capability. NISAR's L-band radar observations provide a new, repeatable data source for studying these changes.

RiverShift focuses on making those observations easier to explore: users select the area, while the application discovers where within that area the radar-derived change candidates occur. The user does not have to know the exact target pixel or river segment in advance.

### Dated regional impact context — Chowhali and the Jamuna

Public reporting from Chowhali/Sirajganj shows why river-change screening has a real community context:

- **11 July 2026:** *The Daily Star* reported that 78 houses and one mosque had been lost to Jamuna erosion over the preceding two weeks along an approximately 1.5 km stretch from Jotpara Mor to Char Salimabad Bhuter Mor. The report also described cropland damage and nearby schools/market at risk, citing the upazila Project Implementation Office. [Source: The Daily Star, 11 July 2026](https://online92.thedailystar.net/news/environment/climate-crisis/natural-disaster/news/jamuna-devours-78-houses-two-weeks-4220946).
- **9 August 2026:** *The Daily Star* reported that the Jamuna had risen since 3 August, with six-day rises of 76 cm at Kazipur and 83 cm at the Sirajganj hard point. A local schoolteacher reported that more than 100 homesteads and extensive croplands around Chowhali had been inundated; the same report quoted Water Development Board officials saying there was no immediate danger-level flood risk at that time. [Source: The Daily Star, 9 August 2026](https://online.thedailystar.net/news/bangladesh/news/jamuna-swells-sirajganj-low-lying-areas-inundated-4243436).

The 9 August report was 12 days after Run #36's user-supplied 28 July event date and 8 days before its 17 August event-proximal NISAR acquisition. This timing provides regional context for the observation window; it does **not** independently confirm the user-supplied event date or prove that any reported home, crop field, school or mosque intersects a Run #36 candidate polygon. The reporting is not a pixel-wise validation mask, an asset inventory, a damage attribution, or proof that RiverShift detected the reported losses. Use it to explain the human and agricultural stakes, while keeping the NISAR output provisional.

## Data sources and how each is used

| Source | Role in RiverShift | Important boundary |
|---|---|---|
| **NASA–ISRO NISAR Level-2 GCOV** | Primary measurement input. RiverShift discovers actual GCOV acquisitions, validates comparable metadata and screens radar-derived open-water and persistent land/water transitions on valid common support. | This is a radar-derived screening classification, not direct bathymetry, sediment volume, surveyed bankline or proof of flood causality. |
| **ASF DAAC / NASA Earthdata** | Catalogue discovery and exact-granule access for NISAR. Source granule identifiers, acquisition metadata and checksums are retained. | Catalogue footprint intersection does not guarantee valid raster coverage. |
| **NASA/JPL OPERA DSWx-S1 V1 (Sentinel-1 C-band)** | Separate retained-run cross-sensor reference workflow. It searches the same AOI and creates a conservative WTR reference when an eligible scene exists. Only WTR class 0 (not water) and class 1 (open water) can enter agreement analysis. Classes 3 (inundated vegetation), 250 (HAND mask), 251 (layover/shadow), 254 (ocean mask) and 255 (fill) remain NoData. | It is not field truth. OPERA is a 30 m product with limitations for narrow channels and small bank changes. In Run #36's AOI no WTR scene was found within the ±30-day discovery window, so no reference GeoTIFF, common-support score, F1 or IoU was produced. |
| **NASA/JPL OPERA RTC-S1 V1 (Sentinel-1 C-band)** | Diagnostic acquisition inventory used when no DSWx WTR scene is available. It records burst dates and VV/VH/MASK availability. | RTC-S1 is gamma0 backscatter, not water/non-water labels. The inventory did not generate a reference mask or agreement metrics. |
| **FFWC / BWDB river gauge data** | Potential ancillary hydrological-stage context for the Jamuna/Sirajganj reach (e.g. gauge SW49). | Not used in Run #36's classification, thresholds or reported areas. A point gauge is not a spatial water-mask reference and must not be described as validation unless exact dated observations are retained and explicitly linked to the AOI. |
| **Google Maps Satellite (Google Maps Platform)** | Third-party visual basemap for geographic orientation and communication of AOI/result footprints. | Basemap imagery is not an analysis input or independent validation dataset. Required imagery-provider attribution remains visible. |
| **Copernicus Sentinel-2 L2A (optional cross-sensor tool)** | A separate CLI can compare a supplied NISAR water mask with clear-support SCL and B03/B11 MNDWI when a suitable scene is available. | This is an optional comparison pathway, not a default analysis input or ground-truth source. Any agreement metric must pass the documented date and common-support gates. |

**Why the validation design is radar-first:** SAR provides repeatable day/night observations through cloud, making it suitable for dynamic river environments. Independent optical or cross-sensor references remain valuable when their acquisition dates and valid spatial support are appropriate for the selected AOI. RiverShift only reports agreement metrics after those checks pass.

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

The map preview is now deliberately conservative and separated from measurements:

- All three change classes use the same fixed reduced grid (maximum dimension 384) and the same cell partition. A mismatch in preview width, height or metric cell size fails closed.
- Only reduced cells with **more than 50% candidate occupancy** become polygons. Polygon simplification is disabled so separately generated class boundaries remain on the same grid partition.
- Positive cells with **50% or less occupancy** become small MultiPoint markers at approximate preview-cell centres rather than being expanded into full coarse polygons. These are location cues, not candidate centroids or boundaries.
- Sparse markers are deterministically capped at 8,000 rendered points per class. Total sparse cells, rendered points and omitted points are recorded separately. The full-resolution source candidate-pixel count and raster are unchanged.
- Preview polygon intersection/Jaccard excludes sparse markers. Marker counts are separate diagnostics; neither polygon nor marker preview is used to calculate measured area.

The preview files retain their source-mask SHA-256, dimensions, occupancy threshold, shared-grid metadata and method. The full-resolution binary masks, scientific GeoJSON, area metrics, analysis reports, source granule receipts and SHA-256 values remain authoritative. The preview remains display-only; no map geometry is a survey-grade boundary or displacement measurement.

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

A separate checksum-bound retrospective replay checked all six retained source COGs against their SHA-256 sidecars and reproduced the three reported candidate areas exactly. The replay also recorded full-resolution mask-overlap QA, with **zero erosion/deposition overlap**, and separate shared-grid preview geometry QA. These replay diagnostics are identified as retrospective evidence; new jobs on main record the corresponding QA natively.

### Independent-reference review — retained Jamuna case

The retained [Run #36 cross-sensor review](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41900559056) searched the same AOI for a date-appropriate OPERA DSWx-S1 water reference. No eligible WTR observation was available for that comparison window, so the correct result is **NO_MATCH_NO_SCORE / PROVISIONAL**. The processing outputs and their reproducibility evidence remain available; no accuracy metric is inferred from the absence of a suitable reference.

This is an AOI- and date-specific review outcome. It does not limit the global processing architecture, and it does not transfer to another region: each new AOI receives its own catalogue, compatibility and reference-availability checks.

## Optional impact-context screen — mapped exposure context

RiverShift can add an optional, separately attributed OpenStreetMap context layer for mapped buildings and selected public facilities inside the selected AOI. Users can also import a source-attributed point/centroid GeoJSON layer, including population-grid points with a supplied numeric attribute. The context points appear in a separate gold map layer and are not mixed into NISAR change classes or area calculations.

Counts are point-in-preview-polygon context only. They help describe mapped features around candidate zones; they are not damage labels, confirmed affected assets, a complete building inventory or an independently validated population estimate. OpenStreetMap is credited as **© OpenStreetMap contributors** under the ODbL. Imported files are processed locally in the browser and are not uploaded to SARGuardian's backend.


## Independent validation pathway

RiverShift keeps three kinds of evidence separate:

1. **Primary measurement:** actual NISAR GCOV observations and the resulting radar-derived water/change candidates.
2. **Cross-sensor SAR comparison:** an eligible OPERA DSWx-S1 WTR mask may be compared to the retained NISAR water mask on the exact same grid. The score is permitted only when sensing dates are within **±3 days** and at least **80% of NISAR-valid pixels** have valid OPERA labels. Only WTR classes 0 and 1 are labelled; class 3 (inundated vegetation), 250 (HAND mask), 251 (layover/shadow), 254 (ocean mask), 255 (fill) and unknown classes remain NoData.
3. **Hydrological or field context:** FFWC/BWDB stage observations, dated banklines, field surveys or other sources may support interpretation only when the source, exact timestamp, station/location, datum and method are documented. A river gauge is point context, not a pixel-wise water classification reference.

For the retained Jamuna Run #36, the reference review returned **NO_MATCH_NO_SCORE / PROVISIONAL** because no eligible, date-appropriate OPERA DSWx-S1 WTR reference was available. No F1, IoU or other accuracy metric is reported for that run. This status is specific to that AOI and observation window.

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

## Scientific interpretation guardrails

- Blue, red and green map classes are radar-derived change candidates interpreted against actual NISAR observations; they are not automatically field-confirmed flood, erosion or deposition labels.
- Source granule identity, acquisition dates, compatibility checks, SHA-256 provenance and full-resolution measurements are retained separately from simplified map previews.
- A catalogue match is only the discovery stage. The worker also checks spatial coverage, product configuration, native layers and valid raster support before processing.
- The current automatic workflow does not infer sediment volume, water depth, flood causality or signed bankline migration. Signed migration is handled as a separate analysis using independently dated banklines and oriented transects.
- Optional building/facility overlays provide mapped exposure context only. They are not damage labels or a complete population/asset inventory.
- Independent accuracy metrics are published only when a suitable reference and the required temporal/common-support gates are available. The retained Jamuna Run #36 therefore remains **PROVISIONAL / NO_MATCH_NO_SCORE**; this is not a zero score.


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

1. Start with the world-centred AOI map. State that RiverShift accepts eligible river reaches across the global NISAR L-band land-observation footprint; the Jamuna is one demonstration case, not a fixed target.
2. Pan/zoom to the Jamuna–Chowhali reach, draw a small WGS84 AOI and choose the observation window.
3. Show the live ASF DAAC discovery and explain how the same AOI/date workflow is driven by the user's selected region and the actual compatible acquisitions returned.
4. Show the real NISAR observation dates and play the time series. Point out that each frame is an actual acquisition.
5. Turn attention to red, green and blue layers; explain each as a candidate, not ground truth.
6. In the impact-context panel, run the AOI-bounded OpenStreetMap query. Show the OSM snapshot timestamp, gold mapped points, the independent marker toggle, unique mapped-feature count and class matches; state explicitly that this is mapped exposure context, not damage or population.
7. Open the Run #36 metrics and provenance; show the source granule IDs, checksums and that the areas are candidate-only.
8. Show the OPERA DSWx-S1 replay report. Explain that no eligible reference existed within the date window, so the system correctly published NO_MATCH_NO_SCORE rather than inventing an accuracy score. End with the need for a date-appropriate independent water reference and field/bankline evidence before a VERIFIED claim.

## Score-sheet evidence checklist

| Criterion | Demonstrable evidence | Judge-facing interpretation |
|---|---|---|
| Impact | A location-independent workflow for river reaches across NISAR's global L-band land-observation footprint; a concrete Jamuna–Chowhali case study; optional source-attributed mapped building/facility context. | The Jamuna is the demonstration story, not a country restriction. Explain how the same AOI/date request can be used for another eligible river reach. |
| Creativity | User-defined AOI, target-free discovery inside that AOI, actual-date radar time series, explainable water/land-transition classes and private source provenance. | The system discovers candidate locations within a user-selected region instead of requiring a pre-known target point. |
| Validity | Backend main `2e59d0f`: 259 RiverShift worker tests passed; Run #36 retrospective replay reproduced all three reported areas after six retained source-COG checksums matched; full-resolution mask-overlap and shared-grid preview QA are recorded separately. Dynamic main `9245de7f`: type-check/build/lint and 155 frontend tests passed. | Separate reproducibility and structural QA from geophysical validation. Run #36 remains PROVISIONAL because an eligible independent water reference was not available; no unsupported F1/IoU or field-accuracy claim is made. |
| Relevance | NISAR Level-2 GCOV is the primary measurement input; ASF DAAC supplies the observation catalogue and exact granules; the NASA Space Apps challenge is named in the app and project materials. | NISAR is the analysis source—not a decorative basemap layer. |
| Presentation | Global-first map entry, world-scale AOI selection, distinct candidate overlays, actual-date playback, source-linked reports, overlap QA and validation-readiness panels; a focused Jamuna case study grounds the public-impact story. | Tell the story from global need → reusable workflow → real Jamuna example → evidence and interpretation. |
| Teamwork | Actual commits, issue/PR history and documented roles. | List only actual team members and verified contributions. |
| User experience | Three-step quick-start, world-centred map, clear WGS84 AOI instructions, visible four-date preflight, independent data layers, exposure-context toggle and validation-readiness panel. | Emphasise that users select a region and time window; the app discovers the compatible NISAR acquisitions. |
| NASA data usage | NISAR GCOV is the primary analysis source; ASF DAAC provides exact product access/provenance; Google Satellite is contextual basemap only. | Explain the role of NISAR data and preserve source attribution. |
| Challenge category | “Dancing with the SARs” / Earth Science identified in the UI and project text. | Use the exact challenge/category wording in the official project submission. |
| Repository access | Public backend and Dynamic GitHub repositories. | Point judges to the evidence index, judge guide and source repositories. |
| Project page | Copy-ready project-page draft, judge brief and technical guide. | Replace only team-specific/video fields with verified information. |

### Team participation and rubric notes

The public NASA Space Apps 2026 information checked on **4 November 2026** confirms the challenge schedule and team cap, but does not publish a global judging score sheet or a women-participation **+5%** bonus on the public event page. Do not present that bonus as an official NASA global rule. If a Local Event or organiser supplies a separate scoring rubric containing such a bonus, cite that exact local document and label it **local-event-specific**; do not transfer it to Global Judging without official confirmation.

The team page should list only real members and their actual contributions. The official event page is https://www.spaceappschallenge.org/2026/.

