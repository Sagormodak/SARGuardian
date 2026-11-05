# Multi-site Himalayan source-geometry audit — 2026-10-25

**Scope:** source-metadata only. No NISAR GOFF payload, ITS_LIVE raster, or glacier outline bytes were downloaded in this audit. No catalog query or velocity scoring was performed.

## What the published IIRS article actually pins

The IIRS Science Portal article “NISAR for Monitoring Glacier Motion” (13 October 2026; DOI [10.65456/iirs.2026.10.3.1](https://doi.org/10.65456/iirs.2026.10.3.1)) reports the Himalayan comparisons under the broad temporal label **January 2026**. It gives these ranges:

| Site | NISAR GOFF range (m/year) | ITS_LIVE range (m/year) |
|---|---:|---:|
| Samudra Tapu | 5.7–139.19 | 0.7–132.53 |
| Bara Shigri | 1.89–68.99 | 0.47–70.58 |

The reviewed public article text does not provide exact pair timestamps, NISAR granule identifiers, a polygon WKT/vector hash, or a pinned ITS_LIVE product/version. The reported ranges are comparison targets, not a pixelwise reference truth set: the article contrasts one NISAR pair against a multi-year/multi-sensor ITS_LIVE record. Do not derive a universal acceptance tolerance from the ranges alone. Source: [IIRS article](https://science.iirs.gov.in/nisar-for-monitoring-glacier-motion/).

## Inventory-outline leads — not the authors' AOI

The recommended RGI 7.0 outline dataset is published at [NSIDC DOI 10.5067/f6jmovy5navz](https://doi.org/10.5067/f6jmovy5navz). Samudra Tapu has a legacy RGI 6 identifier RGI60-14.15613 in a published Himalayan review ([DOI 10.3389/frwa.2022.909246](https://doi.org/10.3389/frwa.2022.909246)). Bara Shigri is identified as RGI60-14.15447 and RGI2000-v7.0-G-14-32495 in a 2026 Water Resources Research article ([DOI 10.1029/2025WR041259](https://doi.org/10.1029/2025WR041259)).

The Bara Shigri RGI 7 identifier is a literature lead; neither site's source polygon bytes, archive hash, or extracted canonical geometry hash has yet been verified here. Samudra Tapu's RGI 7 identifier remains unresolved and is deliberately null rather than guessed.

There is an important temporal caveat: RGI is an inventory snapshot targeted around year 2000. The [RGI 7.0 Region 14 notes](https://rgidata.org/user_guide/regions/rgi14.html) state that its prior outlines were replaced by GAMDAM/GGI18 outlines, with most scenes around 2002. Therefore, an RGI outline can support a **separately labelled independent inventory-outline ROI**, but cannot be silently treated as the IIRS authors' January 2026 mask or a date-matched ice margin.

## Fail-closed state

- Exact AOI WKT: null for both sites.
- Exact NISAR granule IDs and source SHA-256 values: empty for both sites.
- RGI 7 region package SHA-256 and canonical polygon hashes: missing until actual outline bytes are acquired and validated.
- Catalog query executed: false; NISAR raw payload downloaded: false; ITS_LIVE payload downloaded: false; event or velocity validation scored: false.

## Next required steps

1. Retrieve the official RGI 7.0 Region 14 archive or a verifiable mirror and record its byte count/SHA-256.
2. Resolve Samudra Tapu's RGI 7 ID from the official attributes/link table; do not guess from the RGI 6 identifier.
3. Extract and validate both outlines, record a canonical geometry hash and extraction code revision, and retain the source outline unchanged.
4. Keep these outlines labelled as independent inventory ROIs—not as the exact paper masks. Recover the exact NISAR pair metadata and ITS_LIVE product/version before scoring.

The machine-readable lead ledger is docs/know-place/reference/multi_site_source_geometry_leads_20261025.json. It is not a frozen result or a validation pass.
