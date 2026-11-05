# SARGuardian — Raw Data Retention Audit & GitHub Actions Pilot (বাংলা)

এই bundle-এর উদ্দেশ্য হলো raw NISAR L2 HDF5 upload বা delete করার আগে **main science engine-এর প্রয়োজনীয় data dependency audit করা, lossless retained archive তৈরি করা, original reader দিয়ে ফল মিলিয়ে দেখা, তারপর curated archive Google Drive-এ resumable upload করা**। এই পর্যায়ে production deletion অনুমোদিত নয়।

## Bundle contents

- `docs/SARGuardian_RAW_DATA_RETENTION_AUDIT_BN.md` — main research report, reproduction instructions, source readers ও downstream analysis ধরে dataset dependency, existing backend-এর data-loss path, risks ও deletion gates।
- `docs/RAW_DATA_DEPENDENCY_MANIFEST_BN.json` — machine-readable GUNW/GOFF retained dataset patterns, non-HDF5 dependencies ও validation requirements।
- `tools/sarguardian_hdf5_archive.py` — HDF5 dataset inventory; same-path lossless compressed archive; dataset/source SHA-256, exact shapes/dtypes/values এবং attributes verification। কোনো raw file delete বা upload করে না।
- `tools/download_nisar_product.py` — Earthdata দিয়ে একটি exact GUNW/GOFF granule download, free-disk preflight, source SHA-256 ও download manifest।
- `tools/verify_reader_equivalence.py` — pinned main science reader-এ raw বনাম curated HDF5-এর arrays/scalars তুলনা করে; zero valid AOI pixels বা mismatch হলে fail করে।
- `tools/drive_resumable_upload.py` — explicitly allowlisted curated HDF5 ও sidecars Google Drive-এ 8 MiB resumable chunks-এ upload করে; existing-file conflicts, quota, remote size ও MD5 verify করে। Raw `.h5` upload নিষিদ্ধ।
- `.github/workflows/sarguardian-retention-pilot.yml` — এক run-এ একটি granule; archive, reader-equivalence ও Drive verification-সহ **non-destructive** pilot। কোনো explicit raw-deletion step নেই।
- `tests/` — synthetic HDF5 archive/integrity tests, actual uploaded main ZIP-এর `gunw_reader.py`/`goff_reader.py`-ভিত্তিক comparison test এবং helper tests।
- `SARGuardian-main-source.zip`, `SARGuardian-backend-source.zip` — audited source files-এর snapshot; কোনো raw NISAR `.h5/.hdf5` নেই।

## কী retention policy ব্যবহার করা হয়েছে?

ডিফল্ট `engine-ready` profile মূল scientific engine-এর বাস্তব HDF5 dependencies ধরে: GUNW-এর সব `unwrappedInterferogram` ও `pixelOffsets` array, GOFF-এর সব `pixelOffsets` layer/polarisation, সব scalar/1-D metadata এবং `geometry_merge.los_from_product`-এ সরাসরি পড়া radar-grid LOS geometry arrays রাখা হয়। Pinned `src/` code যেসব high-posting GUNW `wrappedInterferogram`-grid raster ও অন্য multidimensional metadata ব্যবহার করে না, compact profile সেগুলো বাদ দেয়; প্রতিটি বাদ দেওয়া dataset-এর path, shape, dtype ও attributes manifest-এ থাকে, পাশাপাশি পুরো source inventory ও source-file SHA-256 রাখা হয়।

আগের ১৭ মিনিটের খরচের মূল কারণ ছিল Python দিয়ে বড় array পড়া, নতুন chunk/compression layout-এ আবার লেখা, এবং একই source/archive-এর পূর্ণ verification scan একাধিকবার চালানো। এখন HDF5 native object copy source-এর exact values, chunking ও compression filter বজায় রাখে; logical data/checksum, metadata এবং dimension-scale links এখনও যাচাই হয়। `full-lossless` profile supported standard NISAR HDF5 hierarchy-এর সব dataset রাখে। `include_wrapped=true` উচ্চ-resolution wrapped grid-টিও রাখে; `derive_wrapped_phase=true` আলাদা optional phase-only radians output তৈরি করে—এটি spatial unwrapping নয়, complex amplitude-ও ধরে রাখে না।

## GitHub Actions pilot চালানোর ধাপ

1. `SARGuardian_GitHub_Actions_Retention_Pilot_Patch.zip`-এর contents `Sagormodak/SARGuardian-backend` repository-র root-এ **নতুন branch-এ** copy করো। Existing `main`-এ সরাসরি overwrite কোরো না।
2. Repository Secrets-এ বর্তমান secrets থাকতে হবে: `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`, `GOOGLE_DRIVE_OAUTH_CLIENT_JSON`, `GOOGLE_DRIVE_REFRESH_TOKEN`, `GOOGLE_DRIVE_PARENT_FOLDER_ID`। Token/password workflow input বা source code-এ রেখো না।
3. GitHub Actions-এ **SARGuardian Retention Pilot (single granule, non-destructive)** চালাও। প্রথমে AOI preflight দিয়ে যাচাই হবে product grid সত্যিই AOI-তে পড়ে কি না; না পড়লে ব্যয়বহুল archive তৈরির আগেই run fail করবে। Default `engine-ready`; unrestricted retention দরকার হলে `full-lossless` বেছে নাও। ASF metadata-তে size estimate না থাকলে `expected_source_bytes` পূরণ করো।
4. Drive-এর nested folder-এ curated HDF5, source inventory, retention manifest, download provenance, reader-equivalence report ও verification receipt পরীক্ষা করো। Source raw HDF5 Drive-এ upload হয় না।

এটি public multi-user queue নয় এবং complete multi-product GUNW+GOFF time-series pipeline নয়। এটি one-product-at-a-time retention validation।

## ASF granule naming validation

Workflow validation accepts real Level-2 identifiers such as `NISAR_L2_PR_GUNW_...` / `NISAR_L2_PR_GOFF_...` (and the `OD` processing type). The fixed workflow and downloader regex are covered by a regression test.

## Local checks

```bash
python -m pip install h5py numpy pytest requests
python -m pytest -q tests/
```

পূর্ণ audit bundle-এর `SARGuardian-main-source.zip`-সহ local retention suite-এ **২২টি test pass** করেছে। শুধু GitHub patch ZIP কপি করলে `pytest tests/`-এ **২১টি pass এবং ১টি skip** আশা করো; scientific-source ZIP-টি backend repo-তে commit করার দরকার নেই। আলাদা করে মূল SARGuardian science suite-এ **১৭৮টি test pass** করেছে, সঙ্গে undefined correlation-এর দুইটি NumPy warning। Workflow YAML ও Bash syntax-ও যাচাই করা হয়েছে।

**সীমাবদ্ধতা:** uploaded ZIP-এ বাস্তব raw HDF5 নেই, তাই real granule-এর schema, size reduction, Google Drive upload বা real-product raw-vs-curated science equality এখনও পরীক্ষা করা হয়নি। GitHub-hosted runner ephemeral—কাজ শেষে runner নিজেই local data discard করে; fail হলে retry-তে NASA থেকে raw product আবার download হবে। কোনো product archive, remote checksum ও science-equivalence verification pass না করা পর্যন্ত workflow কোনো deletion step চালায় না এবং production deletion অনুমোদিত নয়।
