# SARGuardian — Raw HDF5 Data-Dependency Audit ও Retention Contract

**Version:** Phase 1.3 — code/report audit + conservative lossless archiver prototype
**Audit date:** 19 October 2026
**উদ্দেশ্য:** বড় NISAR Level-2 GUNW/GOFF HDF5 পণ্য একবার করে process করে, current main engine পুনরায় চালাতে প্রয়োজনীয় scientific arrays ও metadata একটি সংগঠিত archive-এ রাখা; তারপরই temporary raw product মুছে ফেলার অনুমতি দেওয়া।

> **গুরুত্বপূর্ণ সিদ্ধান্ত:** এই পর্যায়ে কোনো raw HDF5 delete করার অনুমতি নেই। দেওয়া `SARGuardian-main.zip` ও `SARGuardian-backend-main.zip`-এর মধ্যে কোনো `.h5`/`.hdf5` source product নেই। তাই source code থেকে dependency trace করা ও synthetic HDF5 দিয়ে compatibility পরীক্ষা করা গেছে; কিন্তু real granule-এর dataset inventory, attribute layout, array sizes, compression ratio, Drive upload এবং remote verification এখনো চালানো হয়নি। এই report-কে raw-data deletion approval মনে করা যাবে না।

---

## 1. Audit-এ কী পড়া হয়েছে

প্রধান source archive `SARGuardian-main.zip`-এর report, reproduction steps, technical notes, scientific readers, analysis modules, acquisition/organisation code, outputs schema এবং tests পরীক্ষা করা হয়েছে। ZIP-এর SHA-256: `e04ae237ff735866c0e728527321bcf0606fa0e5ac0f45da20b7c30ee7231339`। Backend archive `SARGuardian-backend-main.zip`-এর SHA-256: `1a84bfb417b2b01ae414ce6818a981cd9a14465d7b69785b31e20ced0eda18a1`।

মূল ZIP-এর `src/gunw_reader.py`, `src/goff_reader.py`, `src/timeseries.py`, এবং `src/paths.py`-এর Git blob SHA-1 চারটিই GitHub-এর pinned science commit `77cc9646cfa46d3aff3669d351912f984cf67aa3`-এর সঙ্গে মিলে গেছে। Pilot workflow এই commit-ই checkout করে, যাতে raw-vs-retained comparison অচেনা/latest source version দিয়ে নীরবে না চলে।

মূল README/`REPRODUCE_RESULTS.md` বলছে, NISAR source products local archive-এর অংশ নয়; সব derived measurements `outputs/`-এ committed, আর পূর্ণ source set প্রায় 51 GB পর্যন্ত হতে পারে। Reproduction instructions-এ Result 4-এর routine GOFF subset প্রায় 17 GB (16 products), এবং GUNW export উদাহরণে তিনটি winter product-এর 6.6 GB raw থেকে 488 KB AOI-clipped output-এর কথা বলা হয়েছে। এই ছোট output কেবল নির্দিষ্ট export/result-এর জন্য যথেষ্ট—পূর্ণ per-pixel source archive-এর বিকল্প নয়।

### Verification status

- Original main-engine tests: **178 passed**, `src/troposphere.py`-এর undefined-correlation test থেকে দুটি NumPy warning রয়েছে.
- Retention prototype suite: **21 passed**—archive/integrity, helper, এবং 1টি integration test, যা uploaded main ZIP-এর exact `gunw_reader.py`/`goff_reader.py` import করে.
- Synthetic GUNW test AOI clipping ও automatic-reference mode চালিয়ে source বনাম curated HDF5-এর displacement/quality arrays তুলনা করে এবং valid pixels আছে তা নিশ্চিত করে.
- Synthetic GOFF test `layer="best"` দিয়ে সব available layer/polarisation, AOI clipping, auto-reference ও deramp চালিয়ে source বনাম curated measurement/quality/coordinate arrays element-wise তুলনা করে এবং valid pixels আছে তা নিশ্চিত করে.
- **এগুলো real NISAR product test নয়।** Actual HDF5 schema, reference metadata and complete real-product results equivalence এখনও বাকি.

### Audit-এ ধরা existing reader edge case

`src/goff_reader.py`-এর deramp branch-এ `clip_aoi=False` এবং `deramp=True` একসঙ্গে দিলে `aoi_mask is None` অবস্থায় `~aoi_mask` expression `TypeError` ঘটাতে পারে (line near the deramp RMS diagnostic). বর্তমান normal/default AOI-enabled worker path এভাবে configure করা উচিত নয়। এই audit patch মূল science engine-কে পরিবর্তন করে না; production workflow-এর আগে এই edge case আলাদা bugfix + regression test হিসেবে ঠিক করতে হবে বা নিশ্চিত করতে হবে যে worker কখনো ওই argument combination দেয় না।


## 2. Existing backend worker-এ raw data কোথায় হারাচ্ছে

Uploaded `SARGuardian-backend-main/scripts/sarguardian_worker.py`-এর `run_full()` path code ধরে দেখা হয়েছে। Current behaviour:

1. প্রতিটি GOFF product আলাদা করে Earthdata থেকে download করা হয়—এখানে full 31-product stack একসঙ্গে download হয় না।
2. `read_goff(raw_path, layer="layer2", clip_aoi=True, auto_ref=True, deramp=True)` চালানো হয়। Reader বহু internal arrays return করলেও worker `layer2` থেকে `range_m`, `valid`, `xs/ys`, `correlation` এবং projection নিয়ে AOI fixed lattice তৈরি করে।
3. Worker `lattices[id(pair)]`-এ range-offset lattice রাখে, `pair.n_px` ও scalar mean correlation লেখে; তারপর `goff_result` delete করে এবং raw `.h5` মুছে দেয়।
4. সব product পড়ার পর in-memory lattice-গুলোর ওপর common-reference ও time-series inversion চালানো হয়।
5. `finally`-তেও raw temp files unlink করা হয়—তাই analysis বা package তৈরিতে exception হলেও original temporary HDF5 retention নেই।

এর ফলে current result package-এ selected product ID, timings, summary rows, time series ইত্যাদি থাকলেও raw granule-এর all-layer/polarisation arrays, pixel-level along-track offsets, pixel-level correlation/SNR, variance arrays এবং unused-but-useful metadata পুনরায় analysis করার মতো অবস্থায় রাখা হয় না। Benchmark mode-তেও একই ধরণের immediate cleanup আছে।

Existing `app/science/result_package.py` এবং `scripts/upload_goff_result_to_drive.py` ইচ্ছাকৃতভাবে raw `.h5/.hdf5` package-এর মধ্যে থাকলে reject করে; তারা শুধু compact result files upload করার জন্য বানানো। `app/storage/drive_client.py:upload_file()` এবং upload helper `path.read_bytes()` দিয়ে পুরো upload file RAM-এ নেয়—তাই বড় curated HDF5-এর জন্য এই uploader যথেষ্ট নয়। Retention archive upload-এর জন্য আলাদা resumable/chunked uploader, remote size/checksum verification এবং explicit retention state লাগবে।

**Required change:** existing raw `unlink()`-এর আগে HDF5 inventory → curated archive → local reader-equivalence checks → Drive resumable upload → remote size/checksum verification → manifest commit—সব বাধ্যতামূলক। কোনো gate ব্যর্থ হলে raw `.h5` রেখে run-টিকে `RETENTION_FAILED`/retryable state-এ থামাতে হবে। `finally` block-এ blind deletion রাখা যাবে না।

---

## 3. Current science engine raw HDF5 থেকে ঠিক কী পড়ে

### A. GUNW — অবশ্যই রাখতে হবে

| Dataset/path pattern | কেন লাগে | Retention সিদ্ধান্ত |
|---|---|---|
| `*/unwrappedInterferogram/*/unwrappedPhase` | মূল phase → LOS displacement: `d_los = -(wavelength / 4π) × phase` | সব available frequency/polarisation group-এর full native grid রাখবে। |
| একই grid-এর `coherenceMagnitude` (বা fallback `coherence`) | Coherence threshold, valid pixel mask, stable reference block নির্বাচন, quality statistics, output-এর coherence band | Full array; dtype ও numeric values অপরিবর্তিত। |
| একই grid-এর `connectedComponents` | Invalid/unreliable unwrapped-phase pixel বাতিল এবং একই phase component-এর মধ্যে reference নিশ্চিত করা | থাকলে full array রাখতে হবে। |
| একই grid-এর `mask` / `layoverShadowMask` | Reference ও secondary acquisition-এর subswath validity এবং water flag decode করা | থাকলে full array রাখতে হবে। Mask-কে ভুল করে generic layover/shadow mask ধরে ফেললে valid pixels উল্টোভাবে বাদ পড়তে পারে। |
| একই grid-এর `ionospherePhaseScreen` | Default processing-এ phase screen subtract করা হয়; RMS diagnostic-ও হয় | থাকলে full array রাখতে হবে। |
| একই product-এ co-gridded ionosphere uncertainty বা অনুরূপ QA arrays | বর্তমানে পুরোনো reader সবগুলো ব্যবহার করে না, কিন্তু scientific uncertainty/QA analysis-এর জন্য প্রাসঙ্গিক | Unwrapped-grid group-এর সব arrays রাখার নীতিতে অন্তর্ভুক্ত। |
| `xCoordinates`, `yCoordinates` | Pixel index-কে প্রকৃত spatial coordinate-এ ম্যাপ; AOI clip/reference window | Exact original vector values ও dtype রাখতে হবে। |
| `projection` dataset এবং `epsg_code` attribute | CRS/EPSG ও spatial export transform | Dataset value এবং attribute রাখতে হবে। |
| `centerFrequency`, `center_frequency`, `radarCenterFrequency` | Product-এ থাকলে actual wavelength নির্ণয় | সব scalar/1-D metadata dataset global retention-এ থাকবে। |
| `*/metadata/radarGrid/*` | `geometry_merge.py`-এ বাস্তব line-of-sight geometry বের করা | সম্পূর্ণ metadata/radarGrid spatial arrays রাখতে হবে; AOI crop নয়। |
| `/science/LSAR/identification/lookDirection` | Product-এর প্রকৃত look direction যাচাই | Scalar/string dataset রাখতে হবে। |
| HDF5 root, group এবং dataset attributes | Units, EPSG, product/version, processing context ও future interpretation | সব group attributes copy, retained dataset attributes copy; excluded dataset-এর attributes sidecar manifest-এ record হবে। |

`gunw_reader.py`-এর `find()` frequencyA, HH/VV ইত্যাদি নাম ধরে product layout অনুসন্ধান করে। এজন্য একটিমাত্র hard-coded HH path রেখে বাকিগুলো drop করা ঠিক নয়। Archive policy সব matching `unwrappedInterferogram` group-এর arrays রাখে।

### B. GUNW geometry — সাধারণ AOI export-এর বাইরে কেন data লাগে

`src/geometry_merge.py: los_from_product()` `/science/LSAR/GUNW/metadata/radarGrid/` থেকে `xCoordinates`, `yCoordinates`, `projection`, `losUnitVectorX`, `losUnitVectorY`, `incidenceAngle` পড়ে; এরপর product-এর `lookDirection` নেয়। Current function একটি chosen target-এর কাছাকাছি full spatial arrays sample করে geometry বের করে। শুধুমাত্র target-কে কেন্দ্র করে কয়েকটি pixel রেখে দিলে ভবিষ্যতে অন্য candidate/target-এর geometry পুনরুদ্ধার করা যাবে না।

### C. GOFF — অবশ্যই রাখতে হবে

| Dataset/path pattern | কেন লাগে | Retention সিদ্ধান্ত |
|---|---|---|
| `*/pixelOffsets/*/layer*/slantRangeOffset` | Primary line-of-sight/range offset measurement | সব layer, সব available polarisation-এর full arrays রাখতে হবে। শুধু `layer2/HH` নয়। |
| `*/pixelOffsets/*/layer*/alongTrackOffset` | Flight-direction offset; বর্তমান export-এ রাখা হয় এবং ভবিষ্যতের component analysis-এ দরকার হতে পারে | Full arrays রাখতে হবে। |
| `*/pixelOffsets/*/layer*/correlationSurfacePeak` | Offset matching quality gate | Full arrays রাখতে হবে। |
| `*/pixelOffsets/*/layer*/snr` | Signal-to-noise quality gate | Full arrays রাখতে হবে। |
| `*/pixelOffsets/*/layer*/slantRangeOffsetVariance` | Source product uncertainty/variance; GOFF reader এটি optionalভাবে পড়ে | Full arrays রাখতে হবে। |
| `*/pixelOffsets/*/layer*/alongTrackOffsetVariance` এবং pixelOffsets group-এর অন্য co-gridded arrays | পুরোনো reader সবগুলো ব্যবহার না করলেও future uncertainty/method comparison-এর জন্য | Retention policy pixelOffsets subtree-এর সব datasets রাখে। |
| Layer/polarisation-এর `xCoordinates`, `yCoordinates`, `projection`, projection attributes | AOI mask, georeferencing, raster export এবং common grid | Exact values/metadata রাখতে হবে। |
| HDF5 scalar/1-D datasets এবং root/group/dataset attributes | Acquisition/product/units/projection/schema/provenance metadata | Global retention; কোনো metadata silently বাদ নয়। |

`goff_reader.py`-তে `layer="best"` থাকলে সব discovered layers বিবেচনা হতে পারে; `layer1` ও `layer2`-এর আলাদা correlation-window behaviour নিয়ে report-এ আলোচনা আছে। তাই বর্তমান ফলাফলে layer2 বেশি ব্যবহৃত হলেও archive-এ শুধু layer2 রাখলে ভবিষ্যৎ layer comparison বন্ধ হয়ে যাবে।

### D. Full grid কেন রাখতে হবে — AOI-only clip করলে কোন কাজ ভেঙে যায়

এই audit-এর সবচেয়ে গুরুত্বপূর্ণ সিদ্ধান্তগুলোর একটি হলো: **HDF5 signal arrays-কে AOI polygon-এ crop করে রাখা বর্তমান engine-এর সঙ্গে numerical equivalence বজায় রাখবে—এমন নিশ্চয়তা নেই।**

- GUNW auto-reference coherence, connected component, valid-pixel coverage এবং AOI-এর বাইরে থাকা candidate stable blocks পরীক্ষা করে।
- GOFF auto-reference এবং residual-ramp/deramp fit-এর জন্য AOI-এর বাইরের quality-valid pixels ব্যবহার করে; code-এ fit region 5,000 pixels-এর বেশি হলে plane fit হয়।
- `timeseries.py` common-reference একই geometry/track-এর সব pair-এ উপস্থিত stable pixels খোঁজে, target থেকে buffer দূরে রাখে, তারপর series invert করে।
- GUNW/GOFF export-এর fixed spatial lattice অন্য pair-এর output difference/stack করার জন্য গুরুত্বপূর্ণ।

সুতরাং v1 retention package-এ selected scientific groups-এর **পুরো মূল spatial extent** রাখা হবে; AOI crop কেবল পরে derived preview/export বানানোর সময় হবে। এটাই source-product-এর তুলনায় storage কমানোর নিরাপদ উপায়—প্রতিটি source pixel-এর প্রয়োজন বুঝে তারপর।

---

## 4. Default retention policy: শুধু wrapped complex raster-টি বাদ

“wrappedInterferogram group”-এর সবকিছু বাদ দেওয়া নিরাপদ নয়। NISAR-এর official GUNW description অনুযায়ী product-এ high-posting wrapped complex interferogram, আলাদা high-posting coherence data, 80 m unwrapped phase, connected-component/mask, ionosphere screen/uncertainty এবং sub-pixel offset layers থাকতে পারে. Wrapped complex raster-এর nominal posting unwrapped phase-এর চেয়ে অনেক সূক্ষ্ম; তাই storage delta গুরুত্বপূর্ণ, কিন্তু এর পাশের coherence/offset datasets-ও গবেষণার জন্য কাজে লাগতে পারে. [NASA Open Data — GUNW](https://data.nasa.gov/dataset/nisar-beta-geocoded-unwrapped-interferogram-product-version-1) · [NISAR Product Specifications](https://nisar-docs.asf.alaska.edu/product-specification/).

এজন্য default archive policy: **raw HDF5-এর প্রত্যেক dataset রাখা হবে—শুধু GUNW-তে leaf name `wrappedInterferogram`-সহ multidimensional complex raster বাদ থাকবে।** ওই গ্রুপের `coherenceMagnitude`, offsets, scalar/1-D coordinates, masks, অন্য grids, unknown auxiliary arrays এবং metadata বাদ দেওয়া হবে না। GOFF-এর সব layer/polarisation-ও থাকবে। `--include-wrapped` দিলে ওই actual complex raster-ও retain হবে।

`src/gunw_reader.py`-এর current LOS processing `unwrappedPhase`, co-gridded quality arrays ও ionosphere screen ব্যবহার করে; বর্তমান executable path-এ actual wrapped complex raster পড়া পাওয়া যায়নি। তাই ওই নির্দিষ্ট raster-এর default exclusion একটি **explicit research trade-off**, ভবিষ্যতের সব পদ্ধতির নিশ্চয়তা নয়। নতুন phase-unwrapping/wrapped-phase diagnostics দরকার হলে `--include-wrapped` দিয়ে archive করতে হবে।

এই conservative policy-তে storage saving ছোট curated subset-এর চেয়ে কম হতে পারে—বিশেষ করে GOFF-এর সব layers/polarisations ও unknown auxiliary grids রাখা হচ্ছে বলে। **বাস্তব GUNW/GOFF inventory ও archive-size benchmark ছাড়া Drive free storage-এ পুরো dataset set ধরবে কি না বলা যাবে না।** প্রতিটি exclusion manifest-এ path, shape, dtype, attributes ও estimated bytes-সহ থাকবে।

---

## 5. HDF5-এর বাইরের input-গুলিও সংরক্ষণ করতে হবে

Raw HDF5 archive একা report-এর সব result পুনরুৎপাদনের জন্য যথেষ্ট নয়। নিচের source-গুলোও pipeline-এর dependency:

### Sentinel-2 L2A (scar mapping)

`src/scar_map.py` Element84 Earth Search STAC query করে এবং `sentinel-cogs` থেকে `green`, `swir16`, `scl` asset পড়ে। বর্তমান analysis fixed `602 × 457` common grid, EPSG:32645-এ resample করে NDSI change/composite/candidate cluster তৈরি করে। Reproduce করতে প্রতিটি নির্বাচিত scene-এর STAC JSON/feature ID, timestamps, assets href, pre-event scene choice, post-event clear-pixel compositing order, exact resampled `green`/`swir16`/`scl` arrays, masks, transform, CRS, NoData এবং code version রাখতে হবে। শুধু candidate CSV রাখলে নতুন threshold/grid analysis করা যাবে না। Exact AOI/grid-analysis-এর জন্য resampled arrays যথেষ্ট; অন্য AOI বা resampling পুনরায় করতে original COG লাগবে।

### SRTM / OpenTopoData DEM

`src/geometry_merge.py`, `src/impoundment.py`, `src/troposphere.py` SRTM elevation samples নেয়। `troposphere.py` `outputs/dem_cache/*.npy`-তে grid-specific cached DEM রাখে, কিন্তু শুধু `.npy` যথেষ্ট নয়—এর সঙ্গে lat/lon axes, grid origin/shape/step, CRS/transform, NoData rules, source endpoint এবং retrieval timestamp রাখতে হবে। Derived slope/aspect/impoundment site CSV রাখলেও exact elevation surface ছাড়া future stencil/grid analysis সীমিত হয়ে যাবে।

### Simulation ও external scientific assumptions

`detectability.py`-এর Monte Carlo results raw NISAR HDF5 থেকে আসে না; code version, seed, revisit/noise/wavelength/gate parameters সংরক্ষণ করতে হবে। `inverse_velocity.py`-এর event cutoff, per-pair floor inputs এবং time-series source manifest রাখতে হবে। Report-এ উদ্ধৃত অন্য দলের Sentinel-1 precursor rate-এর মতো external scientific input-এর citation/source version-ও per result provenance-এ থাকা উচিত।

**Documentation inconsistency:** `docs/TECHNICAL_NOTES.md`-এর একটি summary table Sentinel-1/2-কে “referenced but not implemented” বলে, কিন্তু `src/scar_map.py` এবং `REPRODUCE_RESULTS.md`-এ Sentinel-2 scar-mapping code বাস্তবে আছে। Dependency inventory-তে runnable source code ও reproduction commands-কে priority দেওয়া হয়েছে; এই stale table-টি পরে ঠিক করা উচিত।

### Official product documents checked

- [NASA Open Data — GUNW Beta product](https://data.nasa.gov/dataset/nisar-beta-geocoded-unwrapped-interferogram-product-version-1): GUNW documents wrapped complex interferogram, unwrapped phase, coherence, masks/connected components, ionosphere screen/uncertainty and sub-pixel offsets; this supports retaining companion high-posting datasets instead of excluding the entire `wrappedInterferogram` group.
- [NISAR Data User Guide — Product specifications](https://nisar-docs.asf.alaska.edu/product-specification/): official GUNW/GOFF specification index.
- [NISAR Data User Guide — GOFF](https://nisar-docs.asf.alaska.edu/goff/): GOFF carries geocoded offset layers and associated quality data, and raw offsets may contain outliers.

---

## 6. Archive format ও manifest

নতুন `tools/sarguardian_hdf5_archive.py` HDF5 hierarchy/path-preserving, lossless compressed archive তৈরি করে। Default-এ সব datasets রাখা হয়; কেবল GUNW-এর multidimensional `wrappedInterferogram` complex raster বাদ থাকে (`--include-wrapped` দিলে সেটিও থাকে)। `gzip level 4` এবং numeric arrays-এ `shuffle` ব্যবহার করা হয়; retained arrays-এর dtype/shape/values পরিবর্তন করা হয় না। `maxshape` ও `fillvalue` preserve/verify করা হয়; original chunk/compression properties manifest-এ রেকর্ড হয়, কিন্তু space-saving-এর জন্য physical chunk/filter layout বদলাতে পারে। Scalar/1-D datasets, all other multidimensional arrays, and ordinary group/dataset attributes রাখা হয়; `DIMENSION_LIST`/`REFERENCE_LIST`-এর HDF5 internal links নতুন ফাইলে dimension-scale relationships হিসেবে পুনর্গঠন করা হয়। Unknown reference attributes, attribute copy failure বা dimension-scale reconstruction failure হলে archive abort হয়। Local manifest-এ থাকে:

- original source filename, byte-size, whole-file SHA-256;
- archive filename, byte-size, SHA-256 ও estimated compression ratio;
- প্রতিটি dataset-এর original path, shape, dtype, storage/logical size estimate, attributes, maxshape/fillvalue এবং original physical compression/chunk properties;
- প্রতিটি retained dataset-এর logical data SHA-256;
- retained/excluded status ও exclusion reason;
- local verification status এবং পুনর্গঠন করা HDF5-internal dimension-reference bookkeeping-এর audit log।

HDF5-এর `DIMENSION_LIST`/`REFERENCE_LIST` attributes-এ original file-local object references সরাসরি copy করা যায় না। Script coordinate datasets ও ordinary attrs কপি করে এবং dimension labels/scales নতুন ফাইলে পুনর্গঠন করে। Unknown reference-valued attributes, reference datasets, noncanonical links/aliases বা scale rebuilding/attribute-copy failure দেখা গেলে builder fail-closed করে—এমন archive তৈরি করে না যার metadata/coordinate semantics বদলে গেছে। Synthetic dimension-scale test pass করেছে, কিন্তু এই behaviour real NISAR product-এ validate করা বাকি।

### Local use

```bash
# আগে real product-এর সম্পূর্ণ dataset/schema inventory তৈরি করো
python tools/sarguardian_hdf5_archive.py inventory \
  --input /path/to/NISAR_L2_PR_GUNW_....h5 \
  --out /tmp/GUNW.inventory.json

# GUNW compact science archive (raw file মুছে ফেলা হয় না)
python tools/sarguardian_hdf5_archive.py archive \
  --input /path/to/NISAR_L2_PR_GUNW_....h5 \
  --out /tmp/product.science.h5 \
  --manifest /tmp/product.manifest.json

# wrapped-interferogram future analysis প্রয়োজন হলে option চালিয়ে storage delta মাপো
python tools/sarguardian_hdf5_archive.py archive \
  --input /path/to/NISAR_L2_PR_GUNW_....h5 \
  --out /tmp/product.extended.h5 \
  --manifest /tmp/product.extended.manifest.json \
  --include-wrapped

# Remote upload-এর আগে local integrity check
python tools/sarguardian_hdf5_archive.py verify \
  --input /path/to/NISAR_L2_PR_GUNW_....h5 \
  --archive /tmp/product.science.h5 \
  --manifest /tmp/product.manifest.json
```

GOFF-এর জন্য একই command; tool filename/dataset path থেকে type auto-detect করতে পারে, কিন্তু first production pilot-এ `--product-type GUNW` বা `GOFF` explicit দেওয়া ভালো। Output file/manifest আগে থেকে থাকলে overwrite না করে error দেয়। **Tool raw source delete করে না।**

---

## 7. GitHub Actions-এ cleanup অনুমোদনের জন্য বাধ্যতামূলক gates

প্রতিটি product-এ নিচের সব ধাপ pass না হলে raw local HDF5 রাখতে হবে এবং job ব্যর্থ করতে হবে:

1. ASF granule identity, product family, processing maturity, acquisition dates, full source byte-size এবং download integrity check।
2. Real HDF5-এর complete dataset inventory তৈরি; expected GUNW/GOFF core datasets না থাকলে stop।
3. Curated HDF5 + JSON manifest বানানো; retained datasets-এর source ও archive logical checksums মিলানো।
4. Original `gunw_reader.py`/`goff_reader.py` একই options-এ raw এবং curated products চালানো; displacement/range arrays, quality mask, summary stats ও export raster transform/value-এর exact বা explicitly explained tolerance-based comparison করা। Scientific output mismatch হলে delete নিষিদ্ধ।
5. Archive, manifest ও per-product log Google Drive-এ upload; Google Drive API-র returned size এবং MD5/checksum local archive-এর সঙ্গে মেলানো। শুধু HTTP upload response পাওয়া যথেষ্ট নয়।
6. Archive file ID, SHA-256/MD5, source granule identity, extractor/version hash, dataset inventory, verification results ও parent job ID durable manifest/job database-এ commit।
7. Drive object downloadable/available ও metadata verified হয়েছে—এটি confirmation-এর পরে কেবল temporary local raw file remove করা যাবে।
8. Failure/timeout/cancel/callback error হলে cleanup fail-closed হবে: raw file রেখে job failed/needs-retry mark করবে।

### Queue + retry

Job-কে `DISCOVERED → DOWNLOADED → INVENTORIED → ARCHIVED_LOCAL → LOCAL_VERIFIED → UPLOADED_REMOTE → REMOTE_VERIFIED → SCIENCE_EQUIVALENCE_PASS → RAW_CLEANED → COMPLETE` state machine-এ চালাতে হবে। প্রতিটি transition idempotent হতে হবে। Upload বা callback ব্যর্থ হলে previous remote/source state খুঁজে retry করতে হবে, নতুন duplicate archive তৈরি করে storage নষ্ট করা যাবে না।

---

## 8. বাস্তব limits ও next evidence required

**GitHub-hosted runner-এর local disk ephemeral।** Pilot workflow কোনো `rm`/delete command চালায় না; তবে workflow শেষ হলে GitHub host runner filesystem নিজেই discard করে। কোনো gate fail হলে product archive Drive-এ complete/verified হিসেবে mark হবে না; retry-তে NASA থেকে product আবার download করতে হবে। Failure-এর সময় raw file-টি job শেষের পরেও বাঁচিয়ে রাখা দরকার হলে persistent self-hosted runner লাগবে—এটি বর্তমান no-server/free-hosting design-এর বাইরে।

- Uploaded ZIP-এ real HDF5 নেই; তাই exact real-product schema, array cardinality, `DIMENSION_LIST` layout, retained bytes, compression ratio এবং extraction speed জানা নেই।
- Google Drive free allowance-এর তুলনায় curated archive set কত বড় হবে, এক product-এর measured size থেকে estimate করার আগে বলা যাবে না। GOFF-এর সব layers/polarisations রাখায় archive নিজেও বড় হতে পারে।
- এই curated subset current engine-এর discovered dependencies রাখার জন্য তৈরি; unknown future methods-এর জন্য full raw HDF5-এর universal substitute নয়। `wrappedInterferogram` এবং manifest-এ থাকা অন্য excluded grids হচ্ছে explicit research trade-offs।
- Next practical test: **একটি real GUNW এবং একটি real GOFF product**—প্রথমে inventory, তারপর compact archive, তারপর `--include-wrapped` GUNW-র storage difference, তারপর raw-vs-curated numeric-equivalence; সব result manifest-এ লিখতে হবে। এরপরই multi-product retention capacity/free storage estimate করা যাবে।

**কোনো raw file এখনই delete করবে না।** এই Phase 1 deliverable হলো dependency manifest, report, এবং no-delete extraction tool। Production workflow-তে Drive upload/checksum verify ও science-equivalence gates যুক্ত না হওয়া পর্যন্ত destructive cleanup চালু করা যাবে না।


## 10. Non-destructive GitHub Actions pilot

Bundle-এ `.github/workflows/sarguardian-retention-pilot.yml` আছে। এটি একবারে ঠিক একটি named GUNW/GOFF granule download করে, full HDF5 inventory, curated path-preserving archive, local archive verification, exact main-reader output equivalence এবং Drive resumable upload/remote size+MD5 verification চালায়। `include_wrapped` pilot input-এর default `false`, যাতে প্রথম GUNW run-টি compact current-engine archive দিয়ে storage savings মাপে। Archiver CLI-এর compact default `false`: current executable paths-এ multidimensional complex `wrappedInterferogram` raster পড়ার প্রমাণ পাওয়া যায়নি; তবে একই group-এর coherence, offsets, axes এবং সব unknown auxiliary datasets retained হয়। `false` দিলে শুধু ওই নির্দিষ্ট wrapped complex raster বাদ যাবে; এই choice future wrapped-phase/unwrapping methods-এর জন্য তথ্য হারায়। Raw deletion বিবেচনার আগে actual product inventory, archive size, science equivalence ও future-method scope review করতে হবে।

**এই pilot-এ raw source deletion নেই।** Uploaded ZIP-এ real NASA HDF5 নেই, তাই actual product schema, compression savings, Drive quota feasibility এবং source-vs-archive reader equality যাচাই না করা পর্যন্ত deletion code লেখা/চালানো যাবে না। এক বাস্তব GUNW ও এক বাস্তব GOFF pilot-এর ফল review করা আবশ্যক।
