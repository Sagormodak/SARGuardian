# NASA Space Apps 2026 — Project Page Draft

> Copy-ready draft for the team’s official NASA Space Apps project page. Replace every square-bracketed field with truthful team information before submission. Do not claim external validation or team participation that has not happened.

## Project title

**RiverShift — Global River Change Intelligence with NISAR**

## Challenge

**Dancing with the SARs**

**Category:** Earth Science *(confirm the exact label shown in the team's official submission form before submitting).*

## One-sentence pitch

RiverShift turns NASA–ISRO NISAR L-band observations into a reusable, global river-change screening workflow: select a river reach within the mission's global land-observation footprint, choose a date window, and inspect the compatible GCOV acquisitions and observed water/land-transition candidates available for that AOI.

## Short description

RiverShift is an AOI-driven, location-independent application built around NASA–ISRO NISAR Level-2 GCOV data. It is designed for river reaches across the mission's global L-band land-observation footprint—not for one country or one pre-selected river. A user draws a WGS84 area of interest and chooses a date window; the system queries NASA's catalogue for that geometry and period, identifies compatible GCOV acquisitions, and runs the same reproducible water and persistent land–water change screens for the selected region.

The map separates three classes: newly water-covered/open-water candidates (blue), persistent erosion candidates (red), and persistent deposition candidates (green). Users can inspect the actual acquisition dates, source-linked outputs and coverage evidence. Each result is tied to source product identifiers and SHA-256 checksums. The Jamuna–Chowhali run is our concrete demonstration case; the processing request is not hard-coded to that location.

The application makes radar observations understandable while keeping measurement, preview and interpretation distinct. Playback uses real acquisition dates, not synthetic daily observations. Optional source-attributed building/facility points appear in a separate context layer and are not mixed into the NISAR change classes.

## Global applicability and data eligibility

NASA describes NISAR L-band data coverage as global, and ASF reports ongoing L-band data collection over nearly all global landmasses. PROVISIONAL L-band products have been released for acquisitions from 17 June 2026 onward as processing is completed. RiverShift uses the actual ASF/NASA CMR catalogue for each user-selected WGS84 polygon and date window; it does not assume that a scene exists or that every date has usable coverage.

The current live request supports one single-ring WGS84 Polygon of up to **1,000 km²**, with a date window of up to **366 days**. Processing requires at least **four distinct GCOV acquisition dates** and at least **90% catalogue-footprint coverage** of the AOI for each selected date. The worker then checks compatible orbit/frame, product maturity, frequency/covariance term, HDF5 layer availability and valid raster support before analysis. Up to 12 actual acquisition dates are selected; no daily interpolation is introduced.

For an independent visual check of the mission footprint and acquisition plan, consult the [ASF/NISAR Reference Observation Plan interactive map](https://experience.arcgis.com/experience/6052a864cd01459393884a7f751558e3) and the [ASF PROVISIONAL L-band data search](https://search.asf.alaska.edu/). The observation plan is not a guarantee that every location/date has released, compatible GCOV products; the live catalogue and worker gates decide actual eligibility.

These are region-selection and data-eligibility rules, not country restrictions. The same workflow is available for an eligible river reach in any country within the NISAR L-band observation footprint. Global geographic applicability is not a claim that every AOI has data in every date window or that every region has the same independent-validation evidence.

**Mission/data references:** [NASA NISAR Mission Overview](https://science.nasa.gov/mission/nisar/mission-overview/) · [ASF NISAR Data Availability](https://nisar-docs.asf.alaska.edu/availability-overview/) · [NASA NISAR Observation Strategy](https://science.nasa.gov/mission/nisar/observation-strategy/).

## The problem

River channels, banks and floodwater coverage change across continents, affecting farms, settlements, roads and river infrastructure. Optical observations can be limited by cloud and illumination. SAR provides day/night, all-weather observation capability, but radar products and multi-date comparisons can be difficult for non-specialists to interpret.

RiverShift addresses the discovery and communication gap: the user chooses a region, while the application discovers the compatible observations and screens where radar-derived change candidates occur inside that AOI.

### Why this matters in the Jamuna–Chowhali region

Two dated public reports illustrate the human and agricultural stakes around Chowhali:

- On **11 July 2026**, *The Daily Star* reported 78 houses and one mosque lost to Jamuna erosion over two weeks along an approximately 1.5 km stretch from Jotpara Mor to Char Salimabad Bhuter Mor, with cropland damage and nearby schools/market at risk. [Read the report](https://online92.thedailystar.net/news/environment/climate-crisis/natural-disaster/news/jamuna-devours-78-houses-two-weeks-4220946).
- On **9 August 2026**, *The Daily Star* reported more than 100 homesteads and extensive croplands around Chowhali inundated as the Jamuna rose. [Read the report](https://online.thedailystar.net/news/bangladesh/news/jamuna-swells-sirajganj-low-lying-areas-inundated-4243436).

These are regional context reports, not proof that the named assets are inside this demonstration AOI or overlap the Run #36 candidate polygons. The 9 August report was 12 days after the user-supplied 28 July event date and 8 days before the 17 August NISAR acquisition; it does not independently verify that event date or validate the radar classification.

## What we built

- A user-drawn AOI and date-window workflow.
- A first-run guide and an explicit catalogue preflight that counts distinct acquisition dates before the worker's stricter compatibility checks.
- Discovery of real NISAR GCOV acquisitions through ASF DAAC.
- Product-comparability and spatial-coverage checks before pixel-wise analysis.
- Common-support open-water time-series screening.
- Newly water-covered area screening relative to a pre-event reference.
- Persistent land-to-water and water-to-land transition candidates.
- Red / green / blue change-map overlays on a third-party Google Satellite basemap.
- Discrete playback of actual NISAR acquisition dates, with no daily interpolation.
- Source granule, processing metadata, result hashes and private retention of full-resolution products.
- Optional AOI-bounded OpenStreetMap buildings/public-facilities context, plus source-attributed point GeoJSON import; counts only mapped points inside candidate preview polygons.
- A separate OPERA DSWx-S1 Sentinel-1 C-band cross-sensor reference workflow with explicit NO_SCORE gates, plus signed-bankline tools that require independently supplied dated banklines and oriented transects.

## NASA and external data

**Primary measurement source — NASA–ISRO NISAR Level-2 GCOV:** actual L-band radar observations and valid-data masks drive RiverShift's water and persistent land–water change screening.

**Discovery and provenance — NASA Earthdata / ASF DAAC:** RiverShift searches the NASA catalogue for the user-selected AOI and date window, then retains exact granule identifiers, acquisition metadata and source checksums with the processed outputs.

**Independent cross-sensor reference — NASA/JPL OPERA DSWx-S1:** an eligible, date-matched Sentinel-1 water-classification product can be compared with the NISAR water screen when temporal and common-valid-support requirements pass. Independent agreement metrics are reported only when those conditions are met. The retained Jamuna example did not have an eligible reference for a score, so its result remains **PROVISIONAL** rather than receiving an unsupported accuracy value.

**Optional contextual sources:** source-attributed OpenStreetMap building/facility points can provide mapped exposure context; they are not damage or affected-population labels. FFWC/BWDB gauge observations may provide dated river-stage context when explicitly linked to a station and time. Copernicus Sentinel-2 L2A can be used as an optional clear-support comparison source where appropriate. Google Maps Satellite is a visual basemap only; it does not drive classification or validation.


## How the science works

1. Select compatible NISAR GCOV acquisitions with consistent product maturity, geometry and selected diagonal covariance term.
2. Extract AOI-clipped rasters and align them on a common valid grid.
3. Apply the documented water-screening threshold to each actual acquisition date.
4. Compare pre-event water classification with later observations.
5. Mark land-to-water transitions that persist across the configured post-event observations as erosion candidates.
6. Mark water-to-land transitions that persist across the configured post-event observations as deposition candidates.
7. Display new-water and open-water candidates separately from persistent morphology candidates.

The method reports radar-derived screening evidence. It does not measure sediment thickness or volume, prove the cause of a water transition, or produce a signed river-migration rate automatically.

## Example result

The retained RiverShift processing run [#36](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41803576163) used six actual NISAR GCOV acquisition dates from **2026-06-30 to 2026-09-10**. Its event date was 2026-07-28 and its event-proximal NISAR observation was 2026-08-17.

| Run #36 output | Reported value |
|---|---:|
| Newly water-covered candidate area | **17.6721 km²** |
| Persistent erosion candidate area | **1,244.230 ha** |
| Persistent deposition candidate area | **5,078.140 ha** |
| Actual observation dates | **6** |

These are AOI- and threshold-specific **provisional screening candidates**, not independently field-validated measurements. They do not establish sediment volume, signed bankline direction, flood causality or exposed-population counts. Do not substitute older figures from an earlier run.

The retained Jamuna example has no independent-reference accuracy score and remains **PROVISIONAL**. Its candidate areas are presented as reproducible radar-screening outputs, not field-confirmed impact measurements.

## What makes it useful and different

- **Target-free discovery:** the user selects an AOI, not a pre-known erosion point; the workflow screens candidate locations inside the AOI.
- **Radar-first:** NISAR GCOV is the measurement input, not just a decorative image on a map.
- **Evidence before interpretation:** source products, observation dates, comparable-product checks, checksums and warning states remain visible.
- **Time-series honesty:** each frame is an actual acquisition; unavailable dates are not filled with invented observations.
- **Accessible communication:** a quick-start sequence, distinct acquisition-date preflight, independent candidate-layer controls, validation-readiness panel and source-attributed local exposure context help non-specialists explore the evidence.

## Scientific interpretation and review status

RiverShift reports radar-derived change candidates, not automatic ground-truth labels. Full-resolution source masks and retained provenance underpin the measurements; map previews are for visual communication. The time series uses actual acquisition dates, and no daily observations are interpolated.

Independent-reference agreement metrics are reported only when a suitable date-matched reference and the required common valid support are available. For the retained Jamuna Run #36, the strict reference workflow correctly returned **NO_MATCH_NO_SCORE / PROVISIONAL** because no eligible OPERA DSWx-S1 water-reference observation was available for the comparison window. We do not replace missing reference data with an invented accuracy score.

Optional building/facility points provide mapped exposure context, not confirmed damage or affected-population counts. Signed bankline migration is a separate measurement requiring independently dated banklines and oriented transects.

## Demo

**Live application:** https://sar-guardian-dynamic-lilac.vercel.app

**Suggested on-screen demo sequence:** start with the world-centred map and state the global NISAR scope; draw the Jamuna demonstration AOI; check the acquisition preflight; run the NISAR workflow; review actual observation dates and separate candidate layers; show source provenance and the validation-readiness status; finish by explaining that Jamuna is one example of a reusable global AOI workflow.

**Two-minute demo video:** [PASTE VIDEO URL]

**Backend science repository:** https://github.com/moshiour0/SARGuardian-backend

**Interactive application repository:** https://github.com/moshiour0/SARGuardian_Dynamic

**Judge brief (recommended first read):** https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/NASA_SPACE_APPS_2026_JUDGE_BRIEF.md

**Judge guide (full technical evidence):** https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/NASA_SPACE_APPS_2026_JUDGE_GUIDE.md

**Optional Sentinel-2 cross-sensor tool:** https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/validate_with_sentinel2.py

**Example processing workflow:** https://github.com/moshiour0/SARGuardian-backend/actions/runs/41642281327

## Team

- [TEAM MEMBER 1] — [actual role and contribution]
- [TEAM MEMBER 2] — [actual role and contribution]
- [TEAM MEMBER 3] — [actual role and contribution]
- [Add only real team members and their actual contributions.]

## Acknowledgements

NASA and the NASA–ISRO NISAR mission; NASA Earthdata and ASF DAAC for NISAR data access; Google Maps Platform for the contextual satellite basemap. Include any additional source or tool only where it was actually used, and preserve its required attribution.

## Submission checklist

- [ ] Confirm the exact challenge title and category in the official project form.
- [ ] Replace the demo URL and video URL placeholders with verified, publicly accessible links.
- [ ] Add every real team member and contribution; do not invent collaboration.
- [ ] Confirm all repositories are public and open in a signed-out browser.
- [ ] Check all claims against the run manifest, source checksums and validation status.
- [ ] Verify imagery/data attribution.
- [ ] Fill every required NASA project-page field.
- [ ] Submit during the official submission window and confirm the submitted state.
