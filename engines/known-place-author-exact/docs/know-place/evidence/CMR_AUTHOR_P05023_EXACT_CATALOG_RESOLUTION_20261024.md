# Exact author P05023 products resolved in NASA CMR catalog

**Checked:** 2026-10-24 UTC  
**Branch:** `feat/know-place-analysis`  
**Latest isolated validation:** [run 40093352981](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40093352981) — 204 tests passed in 4.73 s; seven workflow YAML files parsed and actionlint v1.7.12 plus semantic validation passed.  
**Live exact-CMR artifact:** ID `12559877337`, name `know-place-author-exact-live-cmr-access-evidence`, 4,118 bytes, ZIP SHA-256 `20929525a6d20e4011563d23ddde16d1144b5f4afbad44505b54c220c42e8897`. The ZIP was downloaded and independently integrity/hash checked against the GitHub artifact digest.

## Exact catalog resolution

The isolated runner queried NASA CMR collection `C2854341702-ASF` for the five exact producer-granule IDs pinned in the author's benchmark. For each product, both `producer_granule_id[]` and `readable_granule_name[]` returned HTTP 200 with exactly one result. Each record supplies exactly one accepted HDF5 data link on `nisar.asf.earthdatacloud.nasa.gov`, under `NISAR_L2_GOFF_PROVISIONAL_V1`, with the exact producer ID in the path and filename.

| Author interval | CMR granule concept ID | Release identity | Exact HDF5 data link |
|---|---|---|---|
| 2026-06-20 → 2026-07-02 | `G4248299988-ASF` | `P05023` | [Open P05023 HDF5](https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_P05023_N_F_J_001/NISAR_L2_PR_GOFF_023_098_A_016_024_4000_SH_20260620T233921_20260620T233956_20260702T233920_20260702T233955_P05023_N_F_J_001.h5) |
| 2026-07-02 → 2026-07-14 | `G4261120661-ASF` | `P05023` | [Open P05023 HDF5](https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001/NISAR_L2_PR_GOFF_024_098_A_016_025_4000_SH_20260702T233920_20260702T233955_20260714T233920_20260714T233954_P05023_F_F_J_001.h5) |
| 2026-07-14 → 2026-07-26 | `G4264302811-ASF` | `P05023` | [Open P05023 HDF5](https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001/NISAR_L2_PR_GOFF_025_098_A_016_026_4000_SH_20260714T233920_20260714T233954_20260726T233919_20260726T233954_P05023_N_F_J_001.h5) |
| 2026-07-26 → 2026-08-19 | `G4286855543-ASF` | `P05023` | [Open P05023 HDF5](https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001/NISAR_L2_PR_GOFF_026_098_A_016_028_4000_SH_20260726T233919_20260726T233954_20260819T233918_20260819T233953_P05023_N_F_J_001.h5) |
| 2026-08-19 → 2026-08-31 | `G4296814366-ASF` | `P05023` | [Open P05023 HDF5](https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GOFF_PROVISIONAL_V1/NISAR_L2_PR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233918_20260831T233952_P05023_N_F_J_001/NISAR_L2_PR_GOFF_028_098_A_016_029_4000_SH_20260819T233918_20260819T233953_20260831T233952_P05023_N_F_J_001.h5) |

## Interpretation boundary

Live manifest results: catalog identities 5/5, exact data URLs 5/5, blocking products 0, source payload downloads 0, source SHA-256 pins 0/5. `RAW_SOURCE_BYTE_IDENTITY=UNVERIFIED`. Paper reproduction remains `BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED`; hazard detection remains `NOT_EVALUATED`.

The earlier ASF-only search missed the first P05023 and surfaced X05026 as a same-interval variant. The later collection-scoped CMR queries resolve that catalog identity discrepancy. Do not substitute X05026. A catalog link is not proof of authenticated download, byte hash, HDF5 validity, grid parity or paper reproduction.

References: [CMR Search API documentation](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html), [official CMR collection/date listing](https://cmr.earthdata.nasa.gov/virtual-directory/collections/C2854341702-ASF/temporal/2026/06/20).

## Raw replay remains separately gated

Legacy raw-replay run [40093380207](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40093380207) completed its decision job but skipped the five-pair analysis. Dedicated author-exact workflow run [40058988016](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40058988016) also skipped because the exact manual input `[run-know-place]` was absent. No raw GOFF payloads were downloaded. `main` remains unchanged at `2218dfeb73353080d8d94bd733d9e7bd9a848886`.
