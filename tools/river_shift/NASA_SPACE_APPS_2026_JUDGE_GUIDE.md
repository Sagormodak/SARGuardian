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
| **NASA–ISRO NISAR Level-2 GCOV** | Primary measurement input. The workflow reads the selected real-valued diagonal covariance term, applies the documented water-screening method, and compares compatible acquisition dates. | The output is a radar-derived screening classification, not direct bathymetry, sediment volume, surveyed bankline, or proof of flood causality. |
| **Alaska Satellite Facility (ASF) DAAC / NASA Earthdata** | Search, exact-granule access and distribution of the NISAR products used by the processing pipeline. Granule identifiers and checksums are retained. | Catalogue footprint coverage is not the same as valid raster coverage. |
| **Copernicus Sentinel-2 L2A (optional cross-sensor tool)** | A separate CLI compares a supplied NISAR water mask with clear-support SCL water and B03/B11 MNDWI. It mosaics adjacent MGRS tiles only when platform, datatake, acquisition date and processing baseline match; duplicate tile revisions are resolved by processing generation time. | It is not part of the default NISAR worker. Retained-data replays for the 2026-07-12 and 2026-09-10 NISAR observations returned 11.03% and 45.34% clear common support respectively, both below the 80% gate, so no agreement metrics were published. This is cross-sensor screening, not ground truth. |
| **Google Maps Satellite (Google Maps Platform)** | Third-party visual basemap for geographic orientation and communication of the AOI and result footprints. | Basemap imagery is not an input to the NISAR classification or a validation dataset. Google/imagery-provider attribution remains visible on the map. |

An optional standalone cross-sensor tool, `validate_with_sentinel2.py`, compares a supplied NISAR water mask with Copernicus Sentinel-2 L2A using SCL clear-class support and a separate B03/B11 MNDWI screen. It is **not automatically run** by the primary RiverShift job. Its selector groups adjacent MGRS tiles only within the same platform, datatake, acquisition date and processing baseline; canonical STAC `processing:version` / `processing:datetime` are preferred with legacy Sentinel-2 fallbacks. Retained-data replays selected Sentinel-2 2026-07-02 (73.31% scene cloud cover) for NISAR 2026-07-12 and Sentinel-2 2026-09-15 (49.35% scene cloud cover) for NISAR 2026-09-10. Clear common support was 11.03% and 45.34%, respectively. Both are below the 80% gate; neither produced F1/IoU or an agreement score. Do not treat either result as optical corroboration. Do not list Copernicus DEM, GPM IMERG, field survey or other datasets as integrated unless the run actually processed and recorded them.

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

The latest previously analysed example run is [RiverShift Action run #41642281327](https://github.com/moshiour0/SARGuardian-backend/actions/runs/41642281327). It used six actual observation dates from **2026-06-30 to 2026-09-10**.

Retained-data Sentinel-2 replay was performed for two source dates: 2026-07-12 and 2026-09-10. Their selected optical scenes were 2026-07-02 (73.31% scene cloud cover) and 2026-09-15 (49.35%). Clear common support was 11.03% and 45.34%, both below the 80% gate. No optical F1/IoU or agreement metrics were published; the primary NISAR metrics were unchanged. These are insufficient-support outcomes, not ground-truth validation.

The run's reported screening metrics were:
- New-water coverage: **110.7812 km²**
- Erosion candidate area: **4,073.9 ha**
- Deposition candidate area: **3,176.0 ha**

These figures describe that particular AOI, selected products, threshold and comparison window. They are **provisional, not independently field validated**, and should not be generalised to another river or event. The figures do not establish sediment volume, bankline direction, flood causality or exposed-population counts.

## Independent validation pathway

RiverShift includes two distinct comparison pathways. The rigorous reference-raster validator compares a NISAR-derived predicted mask to a separately prepared, independently reviewed reference mask on the exact same grid. The optional `validate_with_sentinel2.py` tool searches Copernicus Sentinel-2 L2A and compares the NISAR mask with two optical water classifications: SCL class 6 (using only SCL classes 4/5/6 as clear support) and MNDWI from B03/B11. It records scene date offset, cloud cover, STAC item identity, NISAR mask checksum, common spatial support, confusion metrics and area bias. The Sentinel-2 output is **cross-sensor agreement screening only**, not ground truth, field validation or an independent supervised accuracy assessment. Optical water indices and Sentinel SCL can themselves contain errors.

The standalone signed-bankline tool requires independently prepared dated banklines and oriented transects. A user must specify the positive transect direction. RiverShift must not infer a signed direction from the symmetric morphology metric.

A stronger validation pack should include, for the same AOI and relevant dates:
- independently interpreted optical water/land reference (e.g. a clear-sky Sentinel-2 L2A scene, when available), with manual review and a documented labeling protocol for formal reference validation;
- reference masks and a documented sampling/label protocol;
- confusion matrix, precision, recall, F1, IoU and uncertainty/sensitivity;
- a dated bankline pair and independently oriented transects where signed migration is claimed;
- rainfall, water-level or field observations only where a suitable independent source and temporal coverage exist.

Example optional Sentinel-2 command (run after obtaining the retained full-resolution NISAR water mask):

```bash
python tools/river_shift/validate_with_sentinel2.py \
  --nisar-water-mask results/time_series/water_2026-07-12_mask.tif \
  --observation-date 2026-07-12 \
  --output-dir results/validation/sentinel2-2026-07-12 \
  --max-day-offset 3 \
  --max-cloud-cover 40 \
  --mndwi-threshold 0.0
```

The script uses public Microsoft Planetary Computer STAC search and temporary SAS-signed Sentinel-2 COG access; it stores unsigned source asset identifiers, never temporary SAS tokens. If no eligible scene is found, the report records an explicit no-match status and `metrics: null`. Low cloud-free common support is also reported as insufficient rather than converted to a zero score. The tool is optional and is not part of the primary live worker's normal execution path.

Do not claim Sentinel-2 as an input to a particular result until the report and exact source metadata/checksum are retained alongside that result.

## Optional Sentinel-2 cross-sensor workflow

The standalone tool is documented in [README_11_validate_with_sentinel2.md](README_11_validate_with_sentinel2.md). Example:

```bash
python tools/river_shift/validate_with_sentinel2.py \
  --nisar-water-mask results/time_series/water_2026-07-12_mask.tif \
  --observation-date 2026-07-12 \
  --output-dir results/validation/sentinel2-2026-07-12 \
  --max-day-offset 3 --max-cloud-cover 40 --mndwi-threshold 0.0
```

The tool uses the public Planetary Computer STAC API and temporary signed COG access. It never retains the signed token. It mosaics eligible adjacent MGRS tiles from one platform/datatake/date/processing baseline, with the latest processing generation selected per tile. If the mosaic footprint or clear optical common support is inadequate, it reports an explicit no-result status. It is not part of the default worker and adds no cost to the main NISAR pipeline unless run manually.

A second manual workflow, [RiverShift retained-run Sentinel-2 cross-sensor replay](../../.github/workflows/river-shift-sentinel2-retained-replay.yml), can reconstruct the NISAR time-series mask from previously retained per-product COG artifacts and compare an exact actual acquisition date with Sentinel-2 without downloading raw NISAR HDF5 again. It verifies the COG receipts/checksums and uses the original run's recorded threshold. The workflow is optional; do not claim it has corroborated a result until a completed run produces a suitable scene and a report with non-null metrics. The replay is still cross-sensor agreement, not ground truth or field validation.

## Known limitations

- NISAR acquisition dates are discrete and the available time series depends on product maturity, coverage and comparable acquisition geometry.
- A catalogue footprint intersecting the AOI does not guarantee every pixel is valid after processing.
- Water classification depends on the chosen frequency, diagonal covariance term, thresholding method and valid-data mask.
- Flood-period new-water coverage is not, by itself, independent proof of flood inundation.
- Persistent land/water transitions are erosion/deposition candidates, not confirmed geomorphic causes.
- The current automatic workflow does not create a signed river-centreline migration rate or sediment volume.
- The example run is provisional and has no field validation. The July 2026 Sentinel-2 comparison returned insufficient optical support, so no cross-sensor agreement score is available.
- Google Satellite is a visual context layer only, not a measurement source.

## Public code and evidence

- Backend science worker: https://github.com/moshiour0/SARGuardian-backend
- Interactive application: https://github.com/moshiour0/SARGuardian_Dynamic
- RiverShift processing source: https://github.com/moshiour0/SARGuardian-backend/tree/main/tools/river_shift
- Optional Sentinel-2 cross-sensor tool: https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/validate_with_sentinel2.py
- Sentinel-2 cross-sensor tool guide: https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/README_11_validate_with_sentinel2.md
- Live example workflow: https://github.com/moshiour0/SARGuardian-backend/actions/runs/41642281327
- NASA Space Apps 2026 challenge: https://www.spaceappschallenge.org/2026/

## Demo storyboard (about 2 minutes)

1. Start on the RiverShift page and explain that NISAR GCOV—not the basemap—is the analysis input.
2. Draw a small AOI around a river reach and choose a date range.
3. Show the ASF DAAC catalogue and explain exact acquisition comparability and why insufficient support stops analysis.
4. Show the real NISAR observation dates and play the time series. Point out that each frame is an actual acquisition.
5. Turn attention to red, green and blue layers; explain each as a candidate, not ground truth.
6. Open the result metrics and provenance; show the source granule IDs, checksums and limitations.
7. Show the optional Sentinel-2 cross-sensor CLI as an additional evidence pathway, clearly distinguishing an agreement screen from ground truth. End with the requirement for independent review / field evidence before a VERIFIED claim.

## Score-sheet evidence checklist

| Criterion | Evidence to present | Remaining human action / risk |
|---|---|---|
| Impact | Riverbank / flood-change use case, AOI-specific candidate maps and bounded area metrics. | Add a sourced local impact story and independently sourced exposure only if available; do not imply lives/assets saved. |
| Creativity | User-drawn AOI, target-free change discovery, discrete radar time series, explainable classes and private provenance. | A polished end-to-end demo is still needed. |
| Validity | Product comparability checks, common-valid support, source hashes, synthetic raster/mosaic/replay tests, retained-artifact checksum checks, and provisional release status. | Optical comparisons for the example AOI were below the 80% support gate; independent same-AOI reference/field validation remains the main scientific gap. Signed transect measurement still requires independently digitized banklines. |
| Relevance | NISAR Level-2 GCOV is the primary measurement input; challenge name is explicit. | Explain what radar contributes and why NISAR observations are central. |
| Presentation | Google Satellite result map, red/green/blue classes, observed-date playback, report and this judge guide. | Record a clear two-minute demo and finish project-page text. |
| Teamwork | Actual commits, issue/PR history and documented roles. | Team must supply truthful member names, roles and evidence of collaboration. |
| User experience | Draw-AOI workflow, discovery/processing distinction, map legend, source date and warnings. | Do a first-time-user test and remove unresolved setup friction. |
| NASA data usage | NISAR GCOV is the primary analysis source; ASF DAAC provides exact product access/provenance; Copernicus Sentinel-2 L2A was used in two retained-mask screening attempts; Google Satellite is contextual basemap only. | Both Sentinel-2 attempts failed the 80% common-support gate and provide no corroboration score. Keep all source roles and limitations visible. |
| Challenge category | “Dancing with the SARs” / Earth Science identified in the UI and project text. | Verify the exact category label shown in the team's official project form. |
| Repository access | Public backend and Dynamic GitHub repositories. | Verify links in a signed-out browser before final submission. |
| Project page | This guide and a ready-to-copy project-page draft. | Team must fill required fields and click Submit during the NASA submission window. |

### Women participation bonus (+5%)

The score sheet applies a **5% bonus to the aggregate** when the team includes one or more women members. This must be supported by the real team roster and actual contributions. Add the relevant member(s) and role(s) to the NASA project page; do not claim the bonus until the team confirms the participation information.

