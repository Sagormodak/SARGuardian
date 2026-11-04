# NASA Space Apps 2026 — Project Page Draft

> Copy-ready draft for the team’s official NASA Space Apps project page. Replace every square-bracketed field with truthful team information before submission. Do not claim external validation or team participation that has not happened.

## Project title

**RiverShift — Reading River Change with NISAR**

## Challenge

**Dancing with the SARs**

**Category:** Earth Science *(confirm the exact label shown in the team's official submission form before submitting).*

## One-sentence pitch

RiverShift turns real NASA–ISRO NISAR radar observations into an interactive, date-by-date map of where river water coverage and persistent land–water transitions changed inside a user-drawn area.

## Short description

RiverShift is an interactive river-change screening application built around NASA–ISRO NISAR Level-2 GCOV data. A user draws an area of interest and selects a date window; RiverShift discovers the actual compatible NISAR acquisitions available for that area, runs reproducible water and persistent land–water change screens, and displays the resulting candidate footprints on a Google Maps Satellite basemap.

The map separates three classes: newly water-covered/open-water candidates (blue), persistent erosion candidates (red), and persistent deposition candidates (green). Users can step or play through the actual acquisition dates and inspect the corresponding area and data-coverage metrics. Each displayed output is linked to source product identifiers and SHA-256 checksums.

The goal is to make radar observations understandable to both researchers and the public while preserving scientific limits: candidates are not field-confirmed findings, map previews are display-only, and the playback never invents daily observations.

## The problem

River channels, banks and floodwater coverage can change over short periods, affecting farms, settlements, roads and river infrastructure. Optical observations are often limited by cloud and illumination. SAR can observe Earth's surface through clouds and at night, but interpreting radar products and comparing acquisitions can be difficult for non-specialists.

RiverShift addresses the discovery and communication gap: the user identifies the study area, while the application screens where within that AOI the radar-derived change candidates occur.

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

**Primary analysis data:** NASA–ISRO NISAR Level-2 GCOV radar observations. The radar-derived GCOV values and valid-data masks drive the screening results.

**Product access and provenance:** NASA Earthdata / Alaska Satellite Facility Distributed Active Archive Center (ASF DAAC). Exact granule names, observation dates and checksums are retained with the outputs.

**Independent radar cross-check attempt:** NASA/JPL OPERA DSWx-S1 V1, derived from Sentinel-1 C-band SAR. RiverShift searches the same AOI for a water classification that can be compared to the retained NISAR water mask. Only OPERA WTR class 0 (not water) and class 1 (open water) can be labelled; inundated vegetation, masked and unknown pixels are NoData. The score gate requires an acquisition within ±3 days and at least 80% common valid support.

**Run #36 outcome:** the AOI inventory returned 307 OPERA DSWx-S1 granules across the collection history, but none was an eligible WTR scene within the configured ±30-day discovery window around the 2026-08-17 NISAR observation. The diagnostic OPERA RTC-S1 inventory's nearest acquisition was 2026-06-26, 52 days earlier; RTC-S1 is backscatter, not water labels. No reference GeoTIFF or accuracy metrics were produced. This is a documented NO_MATCH_NO_SCORE outcome, not an independent validation claim.

**Hydrological context:** FFWC/BWDB station SW49 (Serajganj, Jamuna) is a potential source for river-stage context. It was not used as an input to Run #36's classification or area metrics; station water level is point context, not a pixel-wise validation mask.

**Legacy optical tool:** a standalone Copernicus Sentinel-2 L2A CLI remains available for scenes with adequate cloud-free common support, but it is not the monsoon reference strategy. The 2026-08-18 candidate for this AOI had 97.957% reported cloud cover and only 0.1554% common valid support; no metrics were published.

**Open map-data impact context:** The optional AOI-bounded Overpass request reads OpenStreetMap building features and selected public-facility amenities. It supplies mapped feature locations only, not population counts or damage labels. Results are counted against candidate preview polygons, not authoritative full-resolution masks. Attribute **© OpenStreetMap contributors** under ODbL; the OSM snapshot timestamp is shown when returned.

**Third-party visual context:** Google Maps Satellite imagery provides geographic orientation in the result map. It is not used in the NISAR classification and is not an independent validation dataset.

Do not add Copernicus DEM, GPM IMERG, gauge values, field survey, or population/exposure data to claims unless the submitted build actually processed the source and retained its identity, timestamp and method. The OSM panel is a mapped building/facility context screen, not a complete asset inventory, census, damage assessment, or independent validation dataset. Its separate gold map markers are sampled for display only (up to 2,000); the local intersection counts use the full loaded point layer. Gauge readings must not be described as spatial water-mask validation.

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

The separate [OPERA DSWx-S1 replay #41900559056](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41900559056) reused retained artifacts and did not rerun NISAR processing. It found no eligible OPERA WTR scene in the ±30-day discovery window, so the correct result was **NO_MATCH_NO_SCORE**. The validation workflow remained red by design rather than showing a green status without metrics. The report/status/private receipt were uploaded to private Drive with remote checksum verification.

## What makes it useful and different

- **Target-free discovery:** the user selects an AOI, not a pre-known erosion point; the workflow screens candidate locations inside the AOI.
- **Radar-first:** NISAR GCOV is the measurement input, not just a decorative image on a map.
- **Evidence before interpretation:** source products, observation dates, comparable-product checks, checksums and warning states remain visible.
- **Time-series honesty:** each frame is an actual acquisition; unavailable dates are not filled with invented observations.
- **Accessible communication:** a quick-start sequence, distinct acquisition-date preflight, independent candidate-layer controls, validation-readiness panel and source-attributed local exposure context help non-specialists explore the evidence.

## Limitations and next steps

The current automatic output is provisional. Persistent water/land transitions are candidates rather than independently confirmed erosion/deposition. OSM building/facility counts are optional mapped exposure context only; OpenStreetMap is not a complete asset register and the preview polygons are approximate display geometry. The automatic workflow does not calculate signed channel migration from a centreline, sediment volume, water depth or flood causality. Those claims require independently dated banklines, appropriately oriented transects and/or field measurements.

The Run #36 OPERA DSWx-S1 search found no eligible WTR scene in the same AOI within ±30 days of the 2026-08-17 NISAR date; the nearest RTC-S1 burst was 52 days earlier and cannot satisfy the strict ±3-day score gate. No OPERA reference mask or agreement metrics exist for this run. The Sentinel-2 candidate was heavily clouded (97.957% reported cloud cover; 0.1554% common support) and is not corroboration.

An appropriate next validation is a date-matched, independently reviewed water reference for the same AOI with a documented class protocol, source checksums and at least 80% common valid support. FFWC/BWDB gauge data can provide river-stage context when exact station/date readings are attached, but it cannot replace a spatial water reference. Signed bankline movement should only be reported where dated banklines and independently oriented transects are available.

## Demo

**Live application:** https://sar-guardian-dynamic-lilac.vercel.app

**Suggested on-screen demo sequence:** draw the AOI; check the distinct-acquisition preflight; run the actual NISAR workflow; review observed dates and independent candidate toggles; run the one-shot OSM building/facility context query; show its snapshot date and the explicit “mapped exposure context, not damage” caveat; finish with the NO_SCORE validation status.

**Two-minute demo video:** [PASTE VIDEO URL]

**Backend science repository:** https://github.com/moshiour0/SARGuardian-backend

**Interactive application repository:** https://github.com/moshiour0/SARGuardian_Dynamic

**Judge guide:** https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/NASA_SPACE_APPS_2026_JUDGE_GUIDE.md

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
