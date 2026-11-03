# 02 · Download one exact NISAR GCOV product

## Purpose
Download exactly one NISAR L2 GCOV HDF5 granule already selected from the reviewed NASA CMR UMM manifest. The downloader authenticates with NASA Earthdata through `earthaccess`, re-resolves the exact granule within its exact BETA or PROVISIONAL collection, and downloads only that CMR result. It does not broaden the AOI/date search or substitute another granule.

## Inputs
- Catalogue manifest produced by `README_01_discover_gcov_products.md`.
- Exact granule name copied from that manifest.
- One explicit maturity: `BETA` or `PROVISIONAL`.
- Output directory.
- Earthdata authentication through the Actions environment (`EARTHDATA_TOKEN`, or `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`).

## Method
1. Match the requested granule name against exactly one row in the accepted catalogue manifest.
2. Require the recorded maturity to be exactly `BETA` or `PROVISIONAL`; never infer or mix maturities.
3. Authenticate using `earthaccess.login(strategy="environment")`.
4. Query NASA CMR using the exact NISAR GCOV collection short name and exact `granule_name`.
5. Independently compare each returned UMM `GranuleUR` against the requested identifier and require exactly one exact match.
6. Download that one CMR DataGranule through `earthaccess.download` with one transfer thread into a private temporary directory.
7. Require one returned file, the exact requested filename, a non-empty file, and the official 8-byte HDF5 signature (including permitted HDF5 user-block offsets).
8. Move the validated HDF5 product into the raw working directory and write its byte count and SHA-256 receipt.
9. Remove the temporary download directory on both success and failure.

## Reproduce
From `tools/river_shift` in the pinned RiverShift environment:

```bash
python download_gcov_product.py \
  --catalogue data-audit/gcov-catalogue-manifest.json \
  --granule-name EXACT_GRANULE_NAME_FROM_MANIFEST \
  --out-dir data/raw
```

For local use, configure Earthdata credentials in the environment using the current NASA Earthdata Login guidance. Never commit tokens, print credentials, or expose them in browser-visible environment variables.

## Outputs
- Original NISAR HDF5 source file, stored only in the worker's temporary raw directory.
- JSON download receipt containing the exact granule name, collection maturity, collection short name, download method, byte count, source host (when present), and SHA-256.
- Secret-safe stage logs for Earthdata login, exact CMR match, and the download.

## Acceptance tests
- The requested granule matches exactly one accepted catalogue record.
- Only one known maturity is allowed; BETA and PROVISIONAL are never mixed.
- Earthdata authentication failure is reported without exposing credentials.
- CMR lookup includes the exact collection short name and exact granule name.
- A missing or ambiguous exact CMR result blocks download.
- Only the exact matched CMR DataGranule is passed to `earthaccess.download`.
- The worker uses one transfer thread per granule.
- Empty, mismatched-name, invalid-HDF5, and HTML/login responses fail closed.
- The temporary directory is removed after success or failure.
- No existing raw file is overwritten.
- SHA-256 and byte count are recorded after successful download.

## Scientific limitations
- A successful download is not evidence of scientific suitability or surface change.
- Product maturity, orbit, frequency, covariance term, AOI coverage, and temporal compatibility are checked by later RiverShift stages.
- The retained source receipt proves file identity and bytes; it does not validate the scientific interpretation.

## Primary references
- NISAR official Earthaccess guide: https://nisar-docs.asf.alaska.edu/earthaccess/
- NASA Earthdata Login: https://urs.earthdata.nasa.gov/
- Earthaccess API: https://earthaccess.readthedocs.io/en/latest/
- NISAR HDF5 data format: https://nisar-docs.asf.alaska.edu/data-format/
