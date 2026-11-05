# Latest live CMR artifact integrity audit

**Checked:** 2026-10-24 UTC  
**Branch:** `feat/know-place-analysis`  
**CI run:** [40112528293](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112528293)  
**Code/test/workflow/docs commit under test:** `cce3052af83d39aa6988301ea5b96b6fd776c82a`

## Validation outcome

- 217 tests passed in 4.85 seconds.
- All eight Know Place workflow YAML files parsed successfully.
- Pinned `actionlint` v1.7.12 checksum and semantic workflow validation passed.
- Both validation jobs completed successfully.

## Artifact independently checked

| Field | Value |
|---|---|
| Artifact | `know-place-author-exact-live-cmr-access-evidence` |
| Artifact ID | `12566734581` |
| ZIP size | 4,117 bytes |
| Independently computed SHA-256 | `ab1dc5ce3e237649b9c5e404d4c92e6b87c3dae3bf1565dde28e55f66dfe9a49` |
| GitHub artifact digest | `sha256:ab1dc5ce3e237649b9c5e404d4c92e6b87c3dae3bf1565dde28e55f66dfe9a49` |
| ZIP integrity | Passed |
| Inner manifest | `author-exact-catalog-manifest.json`, 127,977 bytes |

The ZIP SHA-256 independently calculated from the downloaded artifact matches GitHub's digest. The inner manifest reports `status=PASS`, five exact CMR identities, five direct HDF5 data URLs, zero blocking products and zero source payload downloads. All five products are `NOT_DOWNLOADED`; byte counts and SHA-256 values are null (0/5 source hashes).

This proves catalog identity and catalog-supplied access URLs, **not** successful source transfer or source-byte identity.

## Raw run and scientific status

- Dedicated exact-author run [40109347847](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40109347847): the consent gate passed, but acquisition was skipped because `[run-know-place]` was absent.
- Legacy raw replay [40112528294](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40112528294): decision job passed; five-pair analysis skipped for the same reason.
- Raw source payload downloads in these runs: 0.
- `PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`.
- `HAZARD_DETECTION_STATUS=NOT_EVALUATED`.
- `main` remains unchanged at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.

Per-product CMR identities and URLs are documented in `docs/know-place/evidence/CMR_AUTHOR_P05023_EXACT_CATALOG_RESOLUTION_20261024.md`.
