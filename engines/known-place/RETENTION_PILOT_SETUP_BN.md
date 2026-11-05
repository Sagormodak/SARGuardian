# GitHub Actions Retention Pilot — setup checklist (বাংলা)

এই patch **এক granule-এর retention experiment**-এর জন্য। এটি complete multi-user worker/queue নয় এবং raw deletion চালায় না।

## কোন ফাইল কোথায় বসবে

ZIP-এর contents `Sagormodak/SARGuardian-backend` repository-র root-এ নতুন branch-এ merge/copy করতে হবে:

- `.github/workflows/sarguardian-retention-pilot.yml`
- `tools/sarguardian_hdf5_archive.py`
- `tools/download_nisar_product.py`
- `tools/verify_reader_equivalence.py`
- `tools/drive_resumable_upload.py`
- `tools/requirements-retention.txt`

Action মূল science code আলাদা করে exact pin `moshiour0/SARGuardian@77cc9646cfa46d3aff3669d351912f984cf67aa3` থেকে checkout করে। মূল scientific reader files-এর চারটি key blob hash uploaded `SARGuardian-main.zip`-এর সঙ্গে মিলিয়ে দেখা হয়েছে।

## Required repository secrets

আগের worker-এ ব্যবহৃত একই secret names দরকার:

- `EARTHDATA_USERNAME`
- `EARTHDATA_PASSWORD`
- `GOOGLE_DRIVE_OAUTH_CLIENT_JSON`
- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_DRIVE_PARENT_FOLDER_ID`

Google Drive OAuth client-এ Drive API-enabled credentials এবং যথেষ্ট Drive scope থাকতে হবে। কোনো secret workflow inputs, code, logs বা commit-এ রেখো না।

## প্রথম test কীভাবে চালাবে

1. আগে ASF catalogue থেকে **একটি exact GUNW granule** বাছাই করো, যা বেছে নেওয়া AOI (`source`, `langtang` বা `lhende`)-র সঙ্গে বাস্তবে intersect করে। Product size estimate পাওয়া গেলে byte হিসেবে লিখে রাখো। বাস্তব filename সাধারণত `NISAR_L2_PR_GUNW_...` / `NISAR_L2_PR_GOFF_...`; workflow `PR` (nominal) ও `OD` (on-demand) processing-type token দুটিই সমর্থন করে। `PR`-এর আগে/পরে অন্য text নিজে বানাবে না—ASF থেকে exact granule identifier কপি করবে।
2. GitHub → Actions → **SARGuardian Retention Pilot (single granule, non-destructive)** → Run workflow। Granule name, product family, maturity ও AOI নির্বাচন করো। Default `retention_profile=engine-ready` বর্তমান readers ও downstream LOS geometry-এর প্রয়োজনীয় arrays রাখে; `full-lossless` সব supported source datasets রাখে। `include_wrapped=true` engine-ready mode-এ পুরো high-posting wrapped grid-ও রাখে। `derive_wrapped_phase=true` আলাদা phase-only radians output তৈরি করে, কিন্তু spatially unwrap করে না এবং complex amplitude রাখে না।
3. তারপর আলাদা run-এ একটি GOFF product চালাও। GOFF run-এও AOI product coverage-এর ভেতরে হতে হবে।
4. Drive folder path হবে `SARGuardian-DataArchive/<GUNW|GOFF>/<PROVISIONAL|BETA>/<granule>/`। সেখানে curated `.science.h5`, source inventory, retention manifest, download manifest, raw-vs-curated reader-equivalence report এবং verification receipt থাকবে। **Raw source HDF5 Drive-এ upload হয় না।**
5. Remote Drive `size`/`md5Checksum`, retained dataset count, archive ratio, reader-equivalence status এবং failure logs review করো। `source-inventory.json` হলো আসল product schema ও array size মাপার প্রধান evidence।

## Push করার আগে local test

Patch ZIP extract করে backend repository root-এ files copy করার পর, Python 3.11+ environment-এ:

```powershell
python -m pip install -r tools/requirements-retention.txt pytest
python -m pytest -q tests/
```

Patch ZIP একা ব্যবহার করলে `21 passed, 1 skipped` স্বাভাবিক—optional reader-compatibility test-এর জন্য main-source ZIP ইচ্ছাকৃতভাবে patch-এ নেই। Full audit bundle-এ supplied `SARGuardian-main-source.zip` থাকলে 22টি test-ই চালানো যায়। Main-source ZIP-টি backend repository-তে commit কোরো না।

## Failure handling ও deletion safety

- AOI grid product-এর সঙ্গে না মিললে archive তৈরির আগেই fail হবে। Size estimate অজানা, disk budget অপর্যাপ্ত, HDF5-এ alias/external links/reference datasets, coordinate/dimension-scale metadata mismatch, archive verification mismatch, reader/LOS-geometry output mismatch, Drive quota অপর্যাপ্ত, OAuth failure বা remote checksum mismatch হলেও workflow fail করবে।
- Existing same-name Drive object-এর byte size/MD5 না মিললে overwrite না করে conflict হবে।
- Workflow-তে explicit raw delete step নেই। GitHub-hosted runner ephemeral বলে job শেষ হলে local raw copy host থেকে হারিয়ে যাবে; failed pilot পুনরায় চালালে NASA থেকে re-download লাগবে।
- **এখন production `rm/unlink` যুক্ত কোরো না।** একটি বাস্তব GUNW ও GOFF pilot, storage/retention review এবং existing multi-product time-series regression pass হওয়ার পর আলাদা reviewed change দরকার।

## বর্তমান scope boundary

এই pilot per-product archive ও per-product reader output equivalence যাচাই করে। এটি এখনও Firebase ID-token verification, durable FIFO public-user queue, rolling 72-hour quota, notifications বা complete multi-granule time-series worker implement করে না। এক granule-এর reader equality পাস করলেও multi-product common-reference/inversion result preservation আলাদাভাবে যাচাই করতে হবে।
