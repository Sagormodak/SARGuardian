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

## What we built

- A user-drawn AOI and date-window workflow.
- Discovery of real NISAR GCOV acquisitions through ASF DAAC.
- Product-comparability and spatial-coverage checks before pixel-wise analysis.
- Common-support open-water time-series screening.
- Newly water-covered area screening relative to a pre-event reference.
- Persistent land-to-water and water-to-land transition candidates.
- Red / green / blue change-map overlays on a third-party Google Satellite basemap.
- Discrete playback of actual NISAR acquisition dates, with no daily interpolation.
- Source granule, processing metadata, result hashes and private retention of full-resolution products.
- Separate tools for independent reference-mask validation, an optional Copernicus Sentinel-2 L2A cross-sensor agreement screen, and signed bankline movement along independently supplied transects.

## NASA and external data

**Primary analysis data:** NASA–ISRO NISAR Level-2 GCOV radar observations. The radar-derived GCOV values and valid-data masks drive the screening results.

**Product access and provenance:** NASA Earthdata / Alaska Satellite Facility Distributed Active Archive Center (ASF DAAC). Exact granule names and checksums are retained with the outputs.

**Third-party visual context:** Google Maps Satellite imagery provides geographic orientation in the result map. It is not used in the NISAR classification and is not an independent validation dataset.

**Optional cross-sensor comparison:** the backend includes a standalone Copernicus Sentinel-2 L2A tool. Retained-data replays were performed for NISAR observations on 2026-07-12 and 2026-09-10. Each optical scene was mosaicked from three same-datatake MGRS tiles, covering 100% of the AOI footprint. The 2026-07-02 scene (73.31% mean cloud cover) had 11.03% clear common support; the 2026-09-15 scene (49.35% mean cloud cover) had 45.34%. Both were below the 80% gate, so no F1/IoU or agreement scores were published. These are insufficient-support outcomes, not optical corroboration. The tool's output is cross-sensor agreement screening, not ground truth or field validation.

Do not add Copernicus DEM, GPM IMERG, rainfall gauge, river-stage, field-survey, or population datasets to this section unless the team's submitted build actually integrates and records them.

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

In one previously completed test run, RiverShift processed six actual observation dates from 30 June to 10 September 2026 and reported:

- 110.7812 km² newly water-covered candidate area;
- 4,073.9 ha persistent erosion candidate area;
- 3,176.0 ha persistent deposition candidate area.

These numbers are specific to that run's AOI, selected products, threshold and comparison window. They are provisional screening metrics, not independently field-validated measurements and not a general estimate for a river or region.

## What makes it useful and different

- **Target-free discovery:** the user selects an AOI, not a pre-known erosion point; the workflow screens candidate locations inside the AOI.
- **Radar-first:** NISAR GCOV is the measurement input, not just a decorative image on a map.
- **Evidence before interpretation:** source products, observation dates, comparable-product checks, checksums and warning states remain visible.
- **Time-series honesty:** each frame is an actual acquisition; unavailable dates are not filled with invented observations.
- **Accessible communication:** candidate layers, plain-language explanations and a satellite basemap help non-specialists explore the results.

## Limitations and next steps

The current automatic output is provisional. Persistent water/land transitions are candidates rather than independently confirmed erosion/deposition. The automatic workflow does not calculate signed channel migration from a centreline, sediment volume, water depth or flood causality. These require independent reference observations and/or field measurements.

An optional Sentinel-2 cross-sensor comparison has been run for two retained NISAR dates using three-tile same-datatake mosaics with full AOI footprint overlap. However, clear common support was only 11.03% and 45.34%, both below the 80% gate, so no agreement metrics were published. Formal validation still requires an independently reviewed, date-appropriate optical or field reference for the same AOI, along with a documented labeling protocol and uncertainty reporting. Signed bankline movement should only be reported where dated banklines and independently oriented transects are available.

## Demo

**Live application:** https://sar-guardian-dynamic-lilac.vercel.app

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
