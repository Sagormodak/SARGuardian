# 02 · Download one exact NISAR GCOV product

## Purpose
Download exactly one NISAR GCOV HDF5 granule already present in a reviewed NASA CMR UMM-JSON manifest. The script never searches for a different granule. When the ASF response omits a direct URL, it may reconstruct the canonical ASF HTTPS path only from a strict official GCOV granule name and explicit BETA/PROVISIONAL collection maturity.

## NASA challenge relevance
The downloaded HDF5 file is the native NASA-ISRO NISAR observation used by the subsequent scientific scripts. Keeping the exact granule identifier and SHA-256 checksum provides traceability.

## Inputs
- Catalogue manifest produced by README_01_discover_gcov_products.md.
- Exact granule name copied from that manifest.
- Output directory.
- Earthdata authentication through EARTHDATA_TOKEN or a protected user ~/.netrc file.

## Method
1. Find exactly one matching product in the manifest.
2. Refuse ambiguous or missing granule names.
3. Use the exact ASF URL returned in the catalogue manifest. If it is absent, construct the canonical ASF HTTPS path only when the official collection maturity is explicitly known as BETA or PROVISIONAL and the granule name passes the official GCOV filename validator. Unknown maturity blocks URL construction and download.
4. Validate that the product URL uses HTTPS and a trusted ASF/NISAR Earthdata host.
5. Download the product as a streamed HDF5 file to a temporary .part path.
6. Compare received bytes with HTTP Content-Length when supplied.
7. Atomically rename the complete file and write a SHA-256 receipt.

## Reproduce
From tools/river_shift:

    export EARTHDATA_TOKEN="YOUR_EARTHDATA_TOKEN"
    python download_gcov_product.py --catalogue data-audit/jamuna_gcov.json --granule-name EXACT_GRANULE_NAME_FROM_MANIFEST --out-dir data/raw

On Windows PowerShell, set the token in the terminal session using $env:EARTHDATA_TOKEN. Never commit it, print it, place it in a VITE_ variable, or paste it into a GitHub issue.

## Outputs
- Original NISAR HDF5 product.
- JSON download receipt containing granule name, maturity, byte count, source host and SHA-256.

## Acceptance tests
- The granule name must match exactly one CMR manifest record.
- URL reconstruction is limited to exact official GCOV names with explicit BETA/PROVISIONAL maturity.
- Unknown maturity never triggers URL construction or download.
- URL reconstruction is permitted only for a strict official 18-token GCOV name with explicit BETA/PROVISIONAL collection maturity.
- An untrusted/non-HTTPS download host is rejected.
- Unknown maturity is never inferred from the CRID or filename.
- Empty or partial downloads are deleted.
- A received Content-Length mismatch fails.
- SHA-256 and byte count are recorded after successful download.
- Authentication failures explain the need for a valid Earthdata login without exposing credentials.

## Scientific limitations
- Download success says nothing about scientific suitability.
- Only use products with the intended maturity, frequency, polarization, orbit geometry and AOI coverage.
- Users must follow NASA Earthdata and ASF data access terms.

## AI reviewer checklist
- Verify the download is tied to one ASF manifest record.
- Verify there is no arbitrary URL input.
- Verify credentials never enter logs or output files.
- Verify partial files cannot be mistaken for complete HDF5 products.
- Verify checksum evidence is preserved.

## Primary references
- ASF downloading guide: https://docs.asf.alaska.edu/asf_search/downloading/
- NASA Earthdata Login: https://urs.earthdata.nasa.gov/
- NISAR HDF5 guide: https://nisar-docs.asf.alaska.edu/data-format/
