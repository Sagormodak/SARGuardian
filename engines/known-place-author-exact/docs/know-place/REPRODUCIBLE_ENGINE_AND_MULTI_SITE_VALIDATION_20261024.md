# Reproducible Know Place engine and multi-site validation plan

**Status date:** 2026-10-24  
**Working branch:** \`feat/know-place-analysis\`  
**Benchmark registry:** \`docs/know-place/reference/multi_site_benchmark_v1.json\`  
**Run Workflow entry point:** \`.github/workflows/sarguardian-aoi-wkt-dispatcher.yml\` (feature-branch copy; default-branch dispatcher is not changed)

## Goal

Build one reproducible NISAR displacement-measurement engine that can accept an AOI polygon and inclusive UTC date range, discover eligible NISAR L2 GOFF granules, preserve exact product identity and source hashes, compute and export measurements, and support independent evaluation against published or external reference evidence.

This has two separate scientific goals:

1. **Movement measurement:** can the engine recover a coherent displacement field / rate when independent evidence says surface motion occurred?
2. **Hazard discrimination:** does the motion distinguish an impending failure from ordinary glacier motion or a site with no measurable precursor?

A positive answer to goal 1 does not establish goal 2. A successful measurement run is not a hazard detection, a prediction, or an operational alert.

## Use GitHub Actions — Run workflow

1. Open the repository's **Actions** tab.
2. Select **SARGuardian AOI WKT E2E (safe branch dispatcher)**.
3. In the branch selector next to **Run workflow**, select \`feat/know-place-analysis\`. This branch contains a Know Place implementation at the same dispatcher path as the existing default-branch workflow. The existing \`main\` dispatcher is left untouched.
4. Choose one run profile:
   - **\`author-exact-p05023\`**: retrieves and processes the five author-pinned Bhote Koshi pairs. Enter the exact consent marker \`[run-know-place]\`. Defaults are geometry height 5151 m, 1000 control draws and seed 260826. The height is an exploratory constant, not a DEM-derived or datum-corrected geometry value.
   - **\`generic-aoi-date\`**: submit a single-ring WGS84 \`POLYGON ((longitude latitude, ...))\` and inclusive start/end dates. With \`execute_downloads=false\`, this is a catalog/series-plan dry run and downloads no GOFF payloads. Set it to true only when ready to download, enter \`[run-know-place]\`, and verify Earthdata plus Google Drive credentials are configured.
5. Read the resulting run's source manifest, selected pair plan, hashes, measurement status, limitation notes, and Drive receipt. Keep the full workflow run URL with the final report.

The launcher checks the consent marker before calling any child pipeline that downloads data. The child workflows repeat the guard. Missing marker or missing credentials must fail closed before raw GOFF acquisition. A catalog-only dry run never downloads GOFF files.

### Expected author-exact run evidence

The author-exact path must, before reporting a complete measurement run:

- Resolve the five exact P05023 granule names from the frozen author benchmark. The first pair is confirmed through NASA CMR; do not substitute the historical X05026 variant.
- Perform authenticated size preflight before download and record the route host plus byte-size evidence.
- Download each source into a temporary private runner directory; verify completed bytes, HDF5 readability, exact group identity, release, polarization, orbit identity, expected EPSG/grid size (4311 × 4230 at 80 m) and grid alignment across pairs.
- Record a separate source SHA-256 and byte count for each HDF5. A catalog identity or URL is not a source-byte hash.
- Freeze hashes of the exact source manifest, normalized input configuration, benchmark fixture and software revisions.
- Preserve failure receipts even if one source, geometry check, pair, or analysis stage fails. Partial metrics cannot pass the full measurement gate.
- Produce derived-only result bundle, pair table, map/GeoTIFF or arrays where supported, dashboard, run manifest and status files. Verify the remote Drive upload and upload receipt before deleting temporary raw HDF5.
- Keep these scientific statuses separate: catalog identity, byte-level source identity, measurement completion, paper/method parity, and hazard detection.

The exact-source path remains explicitly **not paper-reproduced** until source bytes and the author method (geometry, masks, grids, screen and statistics) pass direct parity checks. It must not output a hazard alarm.

## Generic AOI/date engine contract

Request inputs are:

- AOI as one exterior-ring WGS84 WKT polygon, longitude then latitude.
- Inclusive start and end dates.
- Polarization, track and direction selection. Different orbits/grid chains must remain separate unless a verified lattice-compatible series plan allows them to be linked.
- Optional reference polygon and explicit reference policy.
- Explicit coherence-neighbour setting and optional constant geometry height for sensitivity work.
- An explicit dry-run vs download choice.

The engine should return:

- Request and request SHA-256, software commit/environment and normalized processing configuration.
- Catalog candidates plus explicit eligible/excluded/selected decisions, exact acquisition times and pair/chain plan.
- Per-product size/hash/HDF5/group/grid receipts and reason-coded failures.
- Valid pixel count and fraction for each AOI/pair; per-pair east/north/horizontal-magnitude measurements, exact interval duration and interval-average rates; coherence and reference/background diagnostics.
- Native-grid GeoTIFFs and/or compressed diagnostic arrays, pairwise time series, motion-feature table, dashboard, output manifest and checksums.
- \`measurement_status\`, \`paper_reproduction_status\`, and \`hazard_detection_status\` as separate fields.

A rate computed over a pair is an interval-average displacement rate, not instantaneous velocity. The horizontal projection assumes zero vertical motion. Reference-region correction assumes the selected reference pixels are stable; its mask, support and sensitivity must be inspectable.

### Geometry readiness gate

The generic AOI measurement engine currently uses an explicit constant HAE or a geometry-axis median approximation when a DEM-backed per-pixel height is not supplied. It is an exploratory measurement path, not operational-ready processing. The footprint geometry code and archived terrain preparation are separate audit components, not yet a complete end-to-end per-pixel DEM integration in every AOI path.

Before a stronger geometry claim, the engine must:

1. Integrate the per-pixel geometry coefficient builder into the AOI measurement loop on the exact NISAR coordinate lattice.
2. Establish the DEM's horizontal CRS, cell transform, nodata/fill behavior, elevation units and vertical datum.
3. Resolve EGM2008-geoid versus WGS84-ellipsoid height differences with a named geoid model, transformation software/version and sign convention; retain the uncorrected source-faithful variant and quantify sensitivity.
4. Validate offsets, height-axis clipping/extrapolation and common-grid assumptions against actual downloaded HDF5 metadata.
5. Compare outputs from constant-height, median geometry height, and DEM-backed per-pixel geometry without quietly selecting whichever produces the expected result.

The known vertical-reference concern must remain visible. Do not call a constant-height run a DEM-corrected run.

## Multi-site validation registry

The machine-readable registry is \`docs/know-place/reference/multi_site_benchmark_v1.json\`. Its current six sites are pre-registered as follows.

| Site | Role | Reference / expected behaviour | Status |
|---|---|---|---|
| Bhote Koshi, Nepal, 26 Aug 2026 | Author-reproduction target; measurable pre-event motion; hazard-discrimination challenge | The 26 Jul–19 Aug pair reports 0.96 m median crown displacement over 24 days, approximately 4 cm/day. It did **not** clear the 95th-percentile displacement null, and the article does not support a resolved acceleration claim. | Exact P05023 catalog identity 5/5; raw hashes and replay pending |
| Samudra Tapu, India, Jan 2026 | Independent glacier-flow positive | IIRS reports NISAR GOFF 5.7–139.19 m/year vs ITS_LIVE 0.7–132.53 m/year. | AOI, exact acquisition IDs, raster/reference provenance pending |
| Bara Shigri, India, Jan 2026 | Independent glacier-flow positive | IIRS reports NISAR GOFF 1.89–68.99 m/year vs ITS_LIVE 0.47–70.58 m/year. | AOI, exact acquisition IDs, raster/reference provenance pending |
| Hubbard Glacier, Alaska, Oct 2025 | High-speed flow / speckle sensitivity challenge | IIRS reports NISAR GOFF 2.42–2585.09 m/year vs ITS_LIVE 0.29–3247.55 m/year, with an approximately 20% residual difference after the cited correction. | Exact AOI and products pending; do not tune only for agreement |
| Malaspina Glacier, Alaska, Oct 2025 | High-speed flow / speckle sensitivity positive | IIRS reports NISAR GOFF 3.4–1728.31 m/year vs ITS_LIVE 0.02–1690.82 m/year; cited corrected peak values converge to roughly 2%. | Exact AOI and products pending; retain before/after correction results |
| Budhi Gandaki / Ungilung Khola, Nepal, 11 Oct 2026 | No-precursor challenge; cross-product negative control | A separate study reports NISAR L-band GUNW LOS measurements around ±2 cm through 7 Oct and no unusual hanging-glacier motion in the pair ending 9.5 hours pre-event. | **Not directly scoreable by GOFF engine.** A versioned GUNW adapter and matched protocol are required first. |

The IIRS glacier-flow reference is Malviya et al. (2026), “NISAR for Monitoring Glacier Motion”, DOI [10.65456/iirs.2026.10.3.1](https://doi.org/10.65456/iirs.2026.10.3.1). The Budhi Gandaki reference is a preprint by Ajay Kumar Sah, DOI [10.31223/X5QJ8G](https://doi.org/10.31223/X5QJ8G). Bhote Koshi uses the user-supplied Research Square paper, DOI [10.21203/rs.3.rs-11022365/v1](https://doi.org/10.21203/rs.3.rs-11022365/v1), and data/code archive DOI [10.5281/zenodo.22730419](https://doi.org/10.5281/zenodo.22730419).

No other site is scored until its AOI, exact NISAR input identities/hashes, independent reference data and temporal/measurement compatibility have been frozen. Publication-level ranges are not a substitute for a pixelwise reference raster.

## Analysis protocol and proof standard

1. **Source integrity first.** Freeze exact source products, hash them, record every excluded candidate and failure reason, and preserve immutable configuration and environment IDs.
2. **Reproduce the author series.** Run only the five exact P05023 products. Compare each pair to the author archive/published quantities using matched masks and comparable estimands. Recompute the archive's site-field and footprint-screen outputs where inputs permit. Keep pixelwise mask/grid parity separate from approximate scalar agreement.
3. **Verify measurement generalization.** Apply the frozen engine to Samudra Tapu and Bara Shigri first, then separately to Hubbard and Malaspina. Compare the same physical quantity, units, projection, acquisition interval and valid-area support with ITS_LIVE. Treat ITS_LIVE's multi-year/multi-sensor temporal support as different from a single NISAR pair.
4. **Test negative/ambiguous cases.** Bhote Koshi demonstrates why measurable movement may fail to distinguish a future source from background; it is not evidence of successful warning. Budhi Gandaki remains a separate GUNW test until compatible processing exists.
5. **Freeze thresholds before blind evaluation.** Use separate development sites, independently held-out events and non-events, uncertainty intervals, valid-pixel-support gates, site-level train/test split, and explicit false-positive/false-negative reporting. Do not tune on the final holdout or use the post-event 101-zone inventory as a prospective validation set.
6. **Hazard model is a later milestone.** Only after a sufficiently diverse, labeled multi-site set and calibrated false-alarm evaluation may a distinct event classifier be considered. It must have a separate versioned output and gate; measurement scores alone are not hazard probabilities.

## Current acceptance gates

- **Catalog identity:** five exact author P05023 identities resolved.
- **Source bytes:** pending five actual downloads and SHA-256 pins.
- **Author method parity:** blocked.
- **Generic AOI measurement:** implemented exploratory; now exposes geometry/coherence settings as versioned request inputs.
- **Per-pixel DEM/vertical-reference integration:** incomplete in the generic AOI loop.
- **Independent glacier-flow tests:** registered but exact AOI/product/reference datasets pending.
- **Budhi Gandaki test:** registered as a distinct GUNW cross-product test; no GOFF score permissible yet.
- **Hazard detection/operational monitoring:** not evaluated / blocked.

All Know Place changes stay on \`feat/know-place-analysis\`. No edit or merge to \`main\` is part of this plan.
