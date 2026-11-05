# Displacement-null Table S4 reconstruction — 2026-10-26

## Execution and inputs

- Workflow: [derived-only audit run #40233222258](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258) — success.
- Artifact: [`know-place-displacement-null-archive-replay`, ID 12613704622](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40233222258/artifacts/12613704622).
- Author dataset: Zenodo DOI [10.5281/zenodo.22730419](https://doi.org/10.5281/zenodo.22730419); archive 183,389,034 bytes; SHA-256 `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`.
- This audit reads only the author-deposited derived `fields/offsets_*.tif` rasters and JSON tables. It did not download or read NISAR raw GOFF HDF5.

## Results

The frozen, separately named source-inspired reconstruction matches all five deposited crown medians, null medians, and percentiles **at the table's published precision (15/15 numeric fields, 5/5 rows)**.

| Acquisition pair | Computed crown median (m) | Published (m) | Computed null median (m) | Published (m) | Computed percentile | Published | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| 2026-06-20 → 2026-07-02 | 0.99496 | 0.99 | 0.17211 | 0.17 | 94.9458% | 94.9% | PASS |
| 2026-07-02 → 2026-07-14 | 0.53907 | 0.54 | 0.20961 | 0.21 | 87.5297% | 87.5% | PASS |
| 2026-07-14 → 2026-07-26 | 0.29555 | 0.30 | 0.13958 | 0.14 | 80.9579% | 81.0% | PASS |
| 2026-07-26 → 2026-08-19 | 0.96451 | 0.96 | 0.14060 | 0.14 | 94.7491% | 94.7% | PASS |
| 2026-08-19 → 2026-08-31 | 0.32783 | 0.33 | 0.09204 | 0.09 | 81.3333% | 81.3% | PASS |

Policy recorded in the JSON report: NumPy `default_rng`/PCG64, seed `20260907`, one shared sequential stream, up to 1,200 finite-magnitude candidate centres sampled without replacement, pixel-index disk sized to the valid crown-displacement count, minimum 60% valid support, and strict fraction of accepted null medians below the observed crown median.

## Required caveat

- The reviewed archive contains the rounded `tables/displacement_null.json` values but **does not contain the original displacement-null generator, draw-level samples, or rejection history**.
- Therefore this is a declared source-inspired reconstruction with numeric output agreement, not proof of original source-code parity or original random-draw sequence identity. Do not attribute the reconstructed accepted/rejected counts or draw hashes to the authors.
- Output status remains `PASS_AT_PUBLISHED_TABLE_PRECISION`; `author_draw_sequence_identity=UNVERIFIED_NO_ORIGINAL_DRAW_OR_REJECTION_HISTORY`.
- Overall `paper_reproduction_status=PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED`.
- `hazard_detection_status=NOT_EVALUATED`: the percentile is not an event-detection probability, a warning threshold, or validated early-warning evidence.

The exact JSON output is kept in the Actions artifact above. It records each field raster's SHA-256, schema/CRS, sampling policy, result, limitations, and per-row numeric comparisons.
