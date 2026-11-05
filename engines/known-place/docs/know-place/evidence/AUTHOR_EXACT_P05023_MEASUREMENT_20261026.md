# Author-exact P05023 Bhote Koshi measurement — 2026-10-26

## Execution provenance

- Workflow: [Know Place Author-Exact P05023 Run #40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596)
- Backend commit: `8063e9fa699a5f53e835da2f93d22d3a2a07f3a0` on `feat/know-place-analysis`.
- Scientific status: `SCIENTIFIC_METRICS_COMPUTED`; structural status `PASS`.
- Scope: five ascending track 098, HH NISAR L2 PR GOFF granules for 2026-06-20 through 2026-08-31; exact author release `P05023`; no `X05026) substitute.
- Source grid: all five downloaded payloads passed HDF5 identity/byte-count/SHA-256 validation and grid checks at 4311 × 4230, EPSG:32645, 80 m posting.
- Five source hashes and bytes:

| Pair | Bytes | SHA-256 |
|---|---:|---|
| 2026-06-20 → 2026-07-02 | 1,090,519,040 | `d3670f0504576feac52f75a7e8f0ff12f5f5c2ef676a0329a16f66cb91300f05` |
| 2026-07-02 → 2026-07-14 | 1,090,519,040 | `8a947f7fa4458afb564431514f36950a89e004d79e6f0e6bfb7461f7e867123c` |
| 2026-07-14 → 2026-07-26 | 1,092,616,192 | `ac3eb50eb5c35cb70769b44492398d6b212e880b70558d4d7d2376c5d8e49313` |
| 2026-07-26 → 2026-08-19 | 1,101,004,800 | `45e4641da04f235941b1e88262961e9e62ca05ce3ceb35fdac452649b13e416f` |
| 2026-08-19 → 2026-08-31 | 1,098,907,648 | `4dbe3d82c2e03422abf9fc3ead2ad70c0734a80ec52cad87cd6659716fce5371` |

## Exploratory metrics

These use the configured horizontal dE/dN projection, SNR ≥ 5, projected horizontal magnitude ≤ 10 m, component-wise median reference correction, and the WGS84 published-bounds **crown rectangle approximation**.

| Pair | Valid crown displacement pixels | Median horizontal magnitude (m) | Median rate (cm/day) | Mean vector magnitude (m) | Mean azimuth clockwise from north | Median directional coherence R |
|---|---:|---:|---:|---:|---:|---:|
| 2026-06-20 → 2026-07-02 | 283 | 0.9943 | 8.2859 | 0.9148 | 293.82° | 0.7347 |
| 2026-07-02 → 2026-07-14 | 294 | 0.5411 | 4.5092 | 0.6838 | 279.70° | 0.5858 |
| 2026-07-14 → 2026-07-26 | 296 | 0.2953 | 2.4608 | 0.7458 | 274.00° | 0.5863 |
| 2026-07-26 → 2026-08-19 | 292 | 0.9661 | 4.0253 | 1.7222 | 277.79° | 0.8529 |
| 2026-08-19 → 2026-08-31 | 195 | 0.3278 | 2.7320 | 0.6932 | 276.84° | 0.4894 |

The author-compatible site-series path independently reports the critical 2026-07-26 → 2026-08-19 pair as median 0.96451 m, median rate 4.01879 cm/day, mean-resultant coherence R 0.87107 against background R 0.68651; its published site-series and P2 comparison gates passed at archive precision (65/65 and 15/15 checks).

## Footprint and retention gates

- Author-compatible site-series table: 65/65 at archived rounding.
- Author P2 table: 15/15 at archived rounding.
- Full-footprint aggregate rasters: 3/3; footprint inventory: 106/106 candidates; Table S7 validated zones: 101/101; score ranking/formula gates passed.
- Self-contained `dashboard.html` generated (81,214 bytes) and included in the derived-only bundle.
- Private Drive derived-bundle upload and remote verification: PASS. Post-upload hash/cleanup receipt verification: PASS.
- Temporary raw GOFF HDF5: 5/5 deleted only after verified derived retention; raw HDF5 uploaded to Drive: false; raw files remaining: 0.
- Full Actions artifact: [artifact 12613577460](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596/artifacts/12613577460). Main run summary: [#40232441596](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232441596).

## Scientific limitations — do not overstate

1. The crown WKT is a published-bound rectangle approximation, not an author-supplied editable crown polygon/vector. The headline pair comparison is `NOT_COMPARABLE_EXACT_CROWN_GEOMETRY_UNVERIFIED`; numerical closeness is not proof of exact mask identity.
2. The author-compatible P2 path uses prepared DEM heights against NISAR radar-grid height-above-ellipsoid geometry without a vertical-datum transformation; this is reported as a limitation, not silently corrected.
3. The displacement-null sampler was not present in the reviewed author ZIP. A separate source-inspired reconstruction subsequently matched its deposited rounded table values, but original generator code and draw/rejection sequence remain unverified (see [displacement-null reconstruction evidence](DISPLACEMENT_NULL_ARCHIVE_RECONSTRUCTION_20261026.md)).
4. `paper_reproduction_status=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`; `hazard_detection_status=NOT_EVALUATED`; `operational_warning_status=NOT_IMPLEMENTED`. This is a measured scientific case study, not a validated operational landslide/glacier-collapse alarm.
5. The user required the work to remain on `feat/know-place-analysis`. Main was left untouched at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.

## Reproducibility artifacts

The same workflow artifact includes source manifest, per-pair CSVs, author-compatible CSV/JSON/NPZ arrays, diagnostics, three footprint GeoTIFFs, dashboard, derived-only ZIP, Drive receipts, and post-delete cleanup receipt.
