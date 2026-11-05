# Author reference data for Know Place Analysis

## Attribution and licence

Meena, Sansar Raj (2026), **"NISAR offsets measure pre-failure motion but do not single out the Bhote Koshi avalanche source."** Research Square, posted 22 September 2026. Article DOI: https://doi.org/10.21203/rs.3.rs-11022365/v1.

The author identifies Supplementary Data 1 (the 101-zone inventory) and all supplementary items other than Supplementary Figure 1 and Supplementary Table 5 as CC BY 4.0. The exceptions are third-party CC BY-NC 4.0 material and are not copied into this directory.

The original user-uploaded CSV SHA-256 is `b800d90bd6e7322ef2f8548370de0fb922ef057cbdce2d0c2caa681ae76a42a8`. The Zenodo code/output archive at https://doi.org/10.5281/zenodo.22730419 was uploaded by the user and byte-verified on 2026-10-24. Archive checksums and manifest results are recorded in `author_archive_golden_v1.json` and `docs/know-place/evidence/ZENODO_AUTHOR_ARCHIVE_AUDIT_20261024.md`. The ZIP contains processed site fields and benchmark tables, but not original GOFF HDF5 granules or full-footprint per-pair offset rasters; raw replay and author-method parity remain blocked.

## Files

- `author_validated_zones_supplementary_data_1.csv`: the supplied author inventory of 101 validated zones (93 intersect RGI 6.0; 8 do not).
- `author_benchmark_v1.json`: transcribed article/supplement values, exact crown/reference bounds, exact five source granule identifiers, the per-pair site-series table and key footprint-screen values.

## Scientific boundaries

- This is a **source-derived reference dataset**, not an independent blind holdout set. The source zone is identified by the article after the event and must not be used to claim prospective detection skill.
- Supplementary Table 1 specifies `P05023` for all five GOFF granules. The earlier historical raw replay used `X05026` for 20 June-2 July. That previous replay remains historical/checksum-verified, but it is not an exact reproduction of the author's five-input series.
- The article reports that no pre-event pair reaches the 95th percentile on displacement or directional coherence and that no acceleration is resolved. Do not reinterpret the 101-zone screen as an operational hazard detector.
- Preserve the published distinction between the site-series crown-local geometry and per-pixel GLO-90 geometry in the footprint-wide screen. The author code is now inspected. Site-series geometry uses a crown-local radarGrid sample median over its height axis; the current branch's per-pixel sample at a configured height is not equivalent. Exact source/mask and calculation parity remains a blocking item.

## Manuscript-version and catalog caveat

The existing `docs/KNOW_PLACE_ANALYSIS_BLUEPRINT.md` cites a differently titled EGUsphere preprint (DOI `10.5194/egusphere-2026-5462`). It has not been established here whether that source is the same revision as the user-supplied Research Square article. The benchmark values in this folder are transcribed only from the supplied Research Square PDF and its Supplementary Information; source IDs or measurements must not be silently merged across those records.

A live ASF query in [validation run 40035193088](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40035193088) confirmed four of the five P05023 author IDs by trusted collection URL. The exact 20 June–2 July P05023 ID was not found, while the historical lookup reports X05026 for that interval. The check downloaded zero raw granules. A `NOT_FOUND` catalog result is not proof that the author's archive lacks the file; exact-input reproduction remains blocked.


## Zenodo archive audit (2026-10-24)

- Uploaded ZIP MD5: `b07b7eb3b3178d3f69d5bca009cb0db4`; SHA-256: `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`.
- The ZIP passes integrity validation, and all 90 manifest-listed payload files contained in it match the declared sizes and MD5 hashes.
- The archive's TableS7 inventory is byte-identical to the user-supplied 101-zone CSV.
- See the audit for the README versus GeoTIFF profile discrepancy, author-vs-current-branch method mismatches, and remaining raw-source/full-footprint blockers.

## Processed-field verification

The source archive's five field rasters were recomputed against `nisar_pot_series.json`, `polygon_null.json`, `displacement_null.json` (table-to-table only) and `TableS4_site_series.json`. See [`AUTHOR_PROCESSED_FIELD_TABLE_PARITY_20261024.md`](../evidence/AUTHOR_PROCESSED_FIELD_TABLE_PARITY_20261024.md). This validates consistency among exported products and tables, not raw GOFF source reproduction or hazard detection.
