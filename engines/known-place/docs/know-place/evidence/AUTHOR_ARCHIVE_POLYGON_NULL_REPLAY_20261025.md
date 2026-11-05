# Independent replay of the author-archive polygon null — 2026-10-25

## Result

**PASS at the precision stored in the archive: 45/45 rounded metric comparisons matched across all five pairs.**

This check re-executed the archived `code/polygon_null.py` algorithm over the five small, processed site-field GeoTIFFs in the user-supplied Zenodo archive, then compared the results with `tables/polygon_null.json`. It used the exported east/north displacement bands and recomputed directional coherence from those bands; it did not trust the stored R band as the calculation input.

- Archive: `bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip`
- Archive SHA-256: `002c2ba173a03693431b79578ca28d6b11e1ec00423d7533e82198871576c5e3`
- Author code: `code/polygon_null.py`, `code/make_fig_timeseries.py`, `code/make_pot_figure.py`, `code/reconcile_scale.py`
- Inputs: `fields/offsets_YYYYMMDD_YYYYMMDD.tif` for all five intervals
- Reference output: `tables/polygon_null.json`
- Reproduction environment used for this independent check: Python, NumPy, Rasterio, SciPy; no NISAR HDF5 products were downloaded.

## Method mirrored

1. Read the exported east and north displacement bands from each processed field GeoTIFF.
2. Recompute 5 × 5 directional coherence using finite displacement vectors normalised to unit vectors, `scipy.ndimage.uniform_filter` default reflected edges, and the author's strict finite-support fraction `> 0.5`.
3. Apply the archived crown crop convention to each raster extent: linear coordinate axes across the stored extent and the bounds in `AOI = (85.5245, 28.2847, 85.5400, 28.2970)`.
4. Keep one shared `numpy.random.default_rng(20260907)` sequence across the pair order. Select up to 1,200 candidate centres without replacement from finite-R cells.
5. Draw a compact disk with radius `sqrt(n_px / pi)`; accept a draw only when at least 60% of the target valid-crown-cell count remains valid.
6. Compare controls to the box median with strict inequalities: `draws > box` and `draws < crown`. Compare against the archived rounded values, including accepted-draw counts and 5th/95th percentiles.

## Pair-level results

| Interval | Valid crown R cells | Crown R | Box R | Crown − box | Controls above box | Crown percentile | Accepted draws | Null p5 | Null p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 Jun–2 Jul | 302 | 0.739 | 0.641 | +0.097 | 47.5% | 77.2% | 857 | 0.460 | 0.863 |
| 2–14 Jul | 299 | 0.583 | 0.719 | −0.136 | 37.7% | 23.3% | 887 | 0.485 | 0.891 |
| 14–26 Jul | 302 | 0.594 | 0.757 | −0.163 | 37.2% | 39.8% | 920 | 0.481 | 0.965 |
| 26 Jul–19 Aug | 298 | 0.848 | 0.687 | +0.161 | 46.7% | 85.2% | 916 | 0.413 | 0.896 |
| 19–31 Aug | 202 | 0.511 | 0.592 | −0.081 | 50.2% | 29.1% | 996 | 0.412 | 0.814 |

All nine fields per row (`n_px`, crown, box, difference, controls-above-box fraction, crown percentile, accepted-draw count, p5 and p95) matched `tables/polygon_null.json` exactly at the archive's stored rounding: **45 comparisons, zero mismatches**.

## Interpretation boundary

This establishes reproducibility of the archive's *post-hoc polygon-null analysis over its exported processed fields*. The script itself describes this as an additional null analysis; it is not a published-paper metric, and a match to this table must not be relabelled as reproduction of the paper's full method.

The five GeoTIFFs are cropped processed fields (80 × 73 pixels, EPSG:4326); they contain already projected east/north displacement, not the original 4,230 × 4,311 GOFF source-grid arrays or geometry cubes. Therefore this result does **not** establish original-source pixel-mask parity, raw-GOFF-to-field parity, author full-footprint screen parity, or validated hazard detection. Keep:

- Paper reproduction: `BLOCKED_AUTHOR_CROWN_GEOMETRY_AND_METHOD_PARITY_UNVERIFIED`
- Hazard detection: `NOT_EVALUATED`

The separate author-exact run [40114703362](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40114703362) previously recorded byte hashes and grid checks for all five P05023 HDF5 inputs. Its result does not remove the outstanding geometry/method and full-footprint parity gates. No raw products were downloaded for this offline check. No `CC BY-NC 4.0` runout-extent material was used.

## Reproduction recipe

From a checkout of `feat/know-place-analysis`, use the same source archive and run the repository's archive verifier:

```bash
python -m tools.know_place.verify_author_fields /path/to/bhotekoshi2026_nisar_data-and-code_CC-BY-4.0.zip --output author-field-verification.json
```

The verification report includes archive integrity and processed-field/table parity checks. This command reads the supplied archive only; it does not fetch raw NISAR data.
