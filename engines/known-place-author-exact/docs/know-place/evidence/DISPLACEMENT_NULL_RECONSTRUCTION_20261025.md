# Independent displacement-null reconstruction — 2026-10-25

## Scope and provenance

This is the first computational reconstruction of the paper's size-matched displacement null using only the five processed-field GeoTIFFs in the supplied Zenodo archive (DOI 10.5281/zenodo.22730419). It did not read or download raw GOFF HDF5. The source archive was inspected for every member and its Python source was searched for the displacement-null generation path.

The archive contains tables/displacement_null.json as five aggregate rows but no displacement-null generator script, seed, draw-level samples, or rejection trail. code/polygon_null.py is not that generator: it estimates directional coherence R for spatial disks. The article describes compact regions with the crown's own valid-pixel count, random placement on valid ground in the fixed 6 km box, and rejection of regions with insufficient valid pixels; reported accepted samples are 857–996 per pair. It does not fully specify the missing displacement sampler in the supplied archive.

## Independent policy v1

The new module tools/know_place/displacement_null.py uses a deterministic, explicit reconstruction policy: displacement magnitude is hypot(dE,dN); observed statistic is the median over valid crown cells; null samples are median magnitudes in raster-index disks with area set by the crown's valid-pixel count; centres are sampled without replacement from finite east/north displacement cells inside the 6 km box; up to 1,200 centres are tested per pair; a region is accepted with at least 60% of the crown valid-cell count; percentile is 100 times the fraction of accepted medians strictly below the observed crown median. A single NumPy PCG64 generator, seed 20261025, is reused across pairs in chronological order. These shape, RNG and acceptance choices are declared independent assumptions, not recovered author settings.

All attempted centres, including rejected centres, and all accepted median values are retained in the JSON report. Input GeoTIFF sizes, SHA-256 hashes, CRS and transforms are recorded. The report version is method-derived-displacement-null/1.0.

## Archive run results

| Pair | Crown valid pixels | Accepted / tried | Independent null median | Independent percentile | Published percentile |
|---|---:|---:|---:|---:|---:|
| 20 Jun–2 Jul | 283 | 832 / 1,200 | 0.168 m | 95.1 | 94.9 |
| 2–14 Jul | 294 | 815 / 1,200 | 0.195 m | 88.6 | 87.5 |
| 14–26 Jul | 296 | 832 / 1,200 | 0.136 m | 82.8 | 81.0 |
| 26 Jul–19 Aug | 292 | 835 / 1,200 | 0.144 m | 92.2 | 94.7 |
| 19–31 Aug | 195 | 882 / 1,200 | 0.092 m | 82.8 | 81.3 |

The computed crown medians round to the published crown values at two decimals. Independent null medians are close to the aggregate table but some percentiles differ, including -2.5 percentage points on the 26 Jul–19 Aug pair. This is evidence that the chosen explicit policy does not reproduce the missing sampler exactly; it is not a failed code test and must not be “fixed” by tuning parameters to the answer.

## Acceptance status and next work

Status: INDEPENDENT_METHOD_DERIVED_NOT_AUTHOR_SAMPLER_PARITY. Exact author-code parity remains unverifiable from the supplied archive. The 94.7th percentile is a published ranking against a null distribution, not a calibrated hazard probability or proof of early-warning capability.

The source archive inventory confirms the reproducibility gap: `tables/displacement_null.json` is present, while the distributed `code/` directory has no displacement-null generator or saved draw-level sample/rejection history. `code/polygon_null.py` is for directional-coherence R and is not the displacement sampler. The published method does not state the exact region-shape, PRNG/seed, or full rejection policy needed to reproduce the percentile from the archive alone.

The next scientific iteration is to recover an author-supplied generator/draw file if available; otherwise preserve the independent reconstruction and policy sensitivity without tuning it to the published answer. Published-bounds rectangle/native-grid mask consistency is now verified on the retained artifact (five pairs; mask XOR=0), with area matching the paper's rounded 2.07 km². The original author editable vector/golden-mask comparison remains unverified. Run the separate terrain vertical-datum/source-level parity only when its required inputs and explicit authorization are available. Keep whole-paper status PARTIAL and hazard detection NOT_EVALUATED.

## Sensitivity diagnostic (not a search for a matching answer)

A 35-row grid varied minimum valid fraction across 0.4, 0.5, 0.6, 0.7, 0.8 at seed 20261025, and then tested seeds 20261026 and 20261027 at fraction 0.6. Candidate count stayed fixed at 1,200, region shape remained the default raster-index disk, and each setting was rerun across the five pairs with a new shared PCG64 stream. Full numerical results are archived in DISPLACEMENT_NULL_SENSITIVITY_20261025.csv.

For the target pair 26 Jul–19 Aug:

| Setting | Accepted draws | Null median (m) | Crown percentile |
|---|---:|---:|---:|
| fraction 0.4, seed 20261025 | 1,117 | 0.144 | 93.8 |
| fraction 0.5, seed 20261025 | 1,022 | 0.145 | 93.3 |
| fraction 0.6, seed 20261025 (default) | 835 | 0.144 | 92.2 |
| fraction 0.7, seed 20261025 | 685 | 0.144 | 91.4 |
| fraction 0.8, seed 20261025 | 443 | 0.127 | 92.6 |
| fraction 0.6, seed 20261026 | 838 | 0.139 | 92.7 |
| fraction 0.6, seed 20261027 | 846 | 0.137 | 93.5 |

The target-pair percentile varies by 2.4 points across the tested acceptance fractions and by 1.3 points across the tested seeds. None of these runs reaches 94.7, and no setting was selected based on proximity to the published figure. This confirms the reconstructed ranking is policy-dependent. Region-shape sensitivity, author-source recovery, exact crown mask parity, and a fully specified independent-label validation remain outstanding.

## Compact-region shape sensitivity (seed 20261025, valid fraction 0.6)

The same fixed candidate-centre policy was rerun with three equally disclosed raster-index footprints; all five pairs were processed in the same chronological RNG stream. These are sensitivity variants, not candidates from which to choose the best published match. Full 15-row results are in DISPLACEMENT_NULL_SHAPE_SENSITIVITY_20261025.csv.

| Region shape | Accepted draws | Null median (m) | Crown percentile |
|---|---:|---:|---:|
| Disk | 835 | 0.144 | 92.2 |
| Square | 807 | 0.144 | 91.8 |
| Diamond | 918 | 0.144 | 93.0 |

For the 26 Jul–19 Aug pair, the tested shape definitions yield 91.8–93.0 percentile. All remain below the published 94.7 in these runs. Since the author generator is missing, this spread illustrates a genuine unresolved policy choice; it does not identify which shape the author used.


## Source-inspired archive reconstruction — 2026-10-25

The follow-up replay documented in DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.md matches all five archived crown medians, five null medians and five percentiles at stored precision (15/15 numeric fields). The sibling code/polygon_null.py supplies the seeded random-disk/60%-support pattern, but it is a directional-coherence null, not the missing displacement-null generator. Since the displacement-specific source and original draw/rejection history are absent, this establishes output-level numeric agreement, not exact author-code or original draw-sequence identity. Keep the full-paper status PARTIAL and hazard detection NOT_EVALUATED.


The machine-readable repository summary is DISPLACEMENT_NULL_ARCHIVE_REPLAY_20261025.json. The full workflow JSON is artifact [12608431799 from Run 40219393283](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40219393283/artifacts/12608431799), which preserves each field profile and reconstructed-draw digest.
