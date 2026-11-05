# SARGuardian Retention Audit — Validation Results (বাংলা)

**তারিখ:** ২০ অক্টোবর ২০২৬
**অবস্থা:** Native HDF5-copy and engine-ready profile implementation is under regression validation. Previous real GUNW run completed archive creation but failed equivalence because the selected product grid did not intersect `AOI=source`. A fail-fast grid preflight and known intersecting GUNW/GOFF live validation workflow are added; final live results are pending.

## Local validation

- The last completed pre-profile regression run passed **23 tests**, Python `compileall`, and JSON manifest validation. The engine-ready profile, explicit per-dataset exclusion reasons, AOI-preflight tests and live workflow have been added afterwards; their updated regression run must pass before merge.
- Main SARGuardian scientific-engine tests: **178 passed**, with two known NumPy warnings in the test covering undefined correlation (`tests/test_troposphere.py`).
- GitHub Actions workflow: YAML parsed; 13 steps, 9 embedded Bash run blocks; all 9 passed `bash -n`.
- Machine-readable manifest JSON: parsed successfully.
- The provided main/backend ZIP SHA-256 values match the input snapshots copied into this bundle.
- Four critical scientific-source Git blob hashes (`gunw_reader.py`, `goff_reader.py`, `timeseries.py`, `paths.py`) match the pinned public science commit used by the workflow.

## Not yet validated

- A real GUNW pilot downloaded **2,403,336,192 bytes** and inventoried **219 datasets / 45 groups**. The original generic-retention archive was **1,635,198,499 bytes (68.04% of source)** because it retained the large multidimensional wrapped-grid companions and generated a 1.20 GB logical phase derivative. Archive/scale checks passed, but equivalence failed: both raw and archive reader reported zero valid pixels for the chosen source AOI because the product did not overlap that AOI. No Drive upload or remote checksum was reached.
- The updated profile uses HDF5 native object-copy rather than Python-level read/rewrite/recompression; `engine-ready` retains the pinned current readers' arrays plus the downstream LOS fields, whereas `full-lossless` retains all supported source datasets. In the old inventory, source physical-storage sizes suggest about 229 MB for engine-ready arrays, versus about 2.37 GB for full-lossless; this is a **manifest-based estimate, not a new measured archive**. The new preflight rejects non-overlapping products before the costly archive stage.
- Google Drive remote-size/MD5 verification still needs the new live GUNW and GOFF validation run to complete successfully.
- The workflow was not dispatched on GitHub from this environment.
- The current workflow is a single-granule retention pilot, not the complete public user queue or the full multi-product GUNW+GOFF processing service.

## Data safety policy

- The archive builder never deletes the input file.
- The workflow has **no explicit raw-file delete step**. GitHub-hosted runner storage is ephemeral, so raw files are discarded by the host at job end; if the job fails, the next run must download the original product again.
- The `engine-ready` profile excludes multidimensional high-posting GUNW wrapped-grid arrays and other multidimensional fields not consumed by the pinned current code paths. It keeps all scalar/1-D metadata, every GUNW `unwrappedInterferogram` and `pixelOffsets` dataset, every GOFF `pixelOffsets` dataset, and the direct LOS geometry arrays needed by `geometry_merge.los_from_product`. Each exclusion has a dataset-specific reason in the manifest and remains present in the full source inventory.
- Use `full-lossless` to preserve every dataset in supported standard NISAR HDF5 structures, or `include_wrapped=true` in engine-ready mode to keep the complete high-posting wrapped grid. `derive_wrapped_phase=true` is a separate opt-in; it is phase-only, not spatial unwrapping, and loses complex amplitude.
- **No automatic production deletion is authorized.** Real GUNW and GOFF pilots, whole-stack regression, output comparison, remote archive verification and scientific review are required before designing a deletion step.
