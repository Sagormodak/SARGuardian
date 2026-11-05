# Render-এ SARGuardian deploy

এই repo থেকে **দুটি service** হবে: frontend Static Site এবং backend Python Web Service। Scientific processing আগের মতো GitHub Actions-এ চলে; Render API job তৈরি, dispatch, callback, dashboard এবং archive পরিবেশন করে।

বর্তমান handoff: code [migration PR #1](https://github.com/Sagormodak/SARGuardian/pull/1)-এ আছে। GitHub Actions account restriction-এর কারণে Linux CI start হয়নি। সেটি ঠিক করে CI rerun/review ও merge সম্পন্ন করুন। এই restriction থাকলে science processing job-ও start হবে না।

## ১. Code branch এবং service setup

Migration branch-এর CI ও migration report review করে code `main`-এ নেওয়ার পরে Render → New → Blueprint থেকে `Sagormodak/SARGuardian` বেছে নিন। Root-এর `render.yaml` ব্যবহার করুন। Blueprint এখানে শুধু প্রস্তুত করা হয়েছে; কোনো service তৈরি বা deploy করা হয়নি।

Manual setup করলেও একই settings ব্যবহার করবেন:

| Setting | Frontend | Backend/API |
|---|---|---|
| Service type | Static Site | Web Service / Python |
| Root Directory | `apps/dynamic/Frontend` | `apps/dynamic/Backend` |
| Build Command | `npm ci --no-audit --no-fund && npm run build` | `pip install -r requirements.txt` |
| Publish Directory | `dist` | প্রযোজ্য নয় |
| Start Command | প্রযোজ্য নয় | `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check | প্রযোজ্য নয় | `/health` |
| Runtime | Node `24.19.0` | Python `3.13.9` |

Frontend-এ SPA rewrite `/*` → `/index.html` রাখুন; Blueprint-এ দেওয়া আছে। API-তে সেই rewrite দেবেন না। Blueprint automatic deploy বন্ধ রাখে; প্রথম setup ও পরের update-এর সময় manual deploy করতে পারবেন। API-র `free` plan একটি প্রাথমিক configuration; dashboard bundle-এর আকার, memory এবং cold-start দেখে প্রয়োজনমতো plan বেছে নিন।

**`engines/backend/render.yaml` ব্যবহার করবেন না**—ওটি সংরক্ষিত পুরোনো API-র deployment file।

## ২. Backend-এর Render environment variables

নিজের URL দিন; নিচের example URL কোনো deploy হয়ে যাওয়া service নয়।

| Variable | কী দেবেন |
|---|---|
| `APP_ENV` | `production` |
| `CORS_ORIGINS` | frontend-এর পূর্ণ HTTPS origin; যেমন `https://your-web.onrender.com`; একাধিক হলে comma-separated; trailing slash নয় |
| `SUPABASE_URL` | আপনার Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | server-only Supabase secret/service-role key |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | একই Firebase project-এর সম্পূর্ণ Admin service-account JSON, Render secret হিসেবে |
| `GOOGLE_DRIVE_OAUTH_CLIENT_JSON` | private results ব্যবহারকারী Drive OAuth client JSON |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | ঐ Drive identity-র refresh token |
| `GOOGLE_DRIVE_FOLDER_ID` | worker-এর result folder-টির ID |
| `GITHUB_ACTIONS_TOKEN` | নতুন `Sagormodak/SARGuardian` repo-তে Actions read/write এবং Contents read অনুমতিসহ token |
| `GITHUB_ACTIONS_REPOSITORY` | `Sagormodak/SARGuardian` |
| `GITHUB_ACTIONS_WORKFLOW` | `sarguardian-displacement.yml` |
| `GITHUB_ACTIONS_REF` | `main` |
| `PUBLIC_API_URL` | backend service-এর পূর্ণ public HTTPS URL; `/api` বা callback path যোগ করবেন না |
| `DISPLACEMENT_CALLBACK_SECRET` | নিজের তৈরি দীর্ঘ random secret; Actions-এর একই নামের secret-এর সঙ্গে এক হতে হবে |
| `DISPLACEMENT_ACTIONS_ENABLED` | setup চলাকালে `false`; secrets/schema/token ঠিক হলে `true`; Known Place launcher-ও এই switch ব্যবহার করে |
| `KNOWN_PLACE_REPOSITORY` | `Sagormodak/SARGuardian` |
| `KNOWN_PLACE_REF` | `main` |
| `KNOWN_PLACE_PAPER_REPOSITORY` | `Sagormodak/SARGuardian` |
| `KNOWN_PLACE_PAPER_REF` | `main` |
| `RIVERSHIFT_GITHUB_ACTIONS_REPOSITORY` | `Sagormodak/SARGuardian` |
| `RIVERSHIFT_GITHUB_ACTIONS_WORKFLOW` | `river-shift-gcov-process.yml` |
| `RIVERSHIFT_GITHUB_ACTIONS_REF` | `main` |
| `RIVERSHIFT_CALLBACK_SECRET` | Actions-এর একই নামের secret-এর সঙ্গে এক হতে হবে |
| `RIVERSHIFT_ACTIONS_ENABLED` | setup-এ `false`; সব configuration যাচাইয়ের পরে `true` |

RiverShift সাধারণ `GITHUB_ACTIONS_TOKEN` এবং `PUBLIC_API_URL` fallback হিসেবে ব্যবহার করে। আলাদা দরকার হলেই `RIVERSHIFT_GITHUB_ACTIONS_TOKEN` ও `RIVERSHIFT_PUBLIC_API_URL` দিন। খালি override variable তৈরি করবেন না।

Render-এ `GOOGLE_APPLICATION_CREDENTIALS` হিসেবে আপনার Windows-এর local path দেবেন না। JSON variable যথেষ্ট। `PORT` Render দেয়। Firebase Admin JSON, Supabase server key, PAT, Drive credentials বা callback secret কোনো `VITE_*` variable-এ দেবেন না।

## ৩. Frontend-এর public build variables

Firebase Console-এর Web App config থেকে নিচেরগুলো দিন:

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_APP_ID`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_STORAGE_BUCKET`
- `VITE_FIREBASE_MEASUREMENT_ID` — Analytics না থাকলে optional
- `VITE_GOOGLE_MAPS_API_KEY` — browser key; frontend domain restriction-সহ
- `VITE_SARGUARDIAN_API_URL` — backend-এর public HTTPS base URL, যেমন `https://your-api.onrender.com`

এই variables build-এর সময় bundle-এ যায়। বদলালে frontend আবার build/deploy করুন। Backend URL ও CORS origin একে অন্যের সঠিক service নির্দেশ করছে কি না দেখুন।

Firebase Authentication-এ Google provider enable করুন এবং Authorized domains-এ final frontend hostname যোগ করুন। Maps JavaScript API এবং Places API (New) চালু করে browser key-তে final frontend URL-এর referrer restriction দিন। Firebase browser config এবং API Admin JSON একই project-এর হতে হবে।

## ৪. নতুন repo-র GitHub Actions secrets

GitHub → `Sagormodak/SARGuardian` → Settings → Secrets and variables → Actions-এ দিন:

| Secret | Consumer |
|---|---|
| `EARTHDATA_TOKEN` | satellite data download |
| `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` | Earthdata username/password fallback এবং delayed retry |
| `GOOGLE_DRIVE_OAUTH_CLIENT_JSON` | worker-এর private result upload |
| `GOOGLE_DRIVE_REFRESH_TOKEN` | একই Drive identity |
| `GOOGLE_DRIVE_PARENT_FOLDER_ID` | Known Place ও RiverShift-সহ workers-এর result folder |
| `GOOGLE_DRIVE_FOLDER_ID` | Dynamic displacement workflow compatibility; একই folder ID দিন |
| `DISPLACEMENT_CALLBACK_SECRET` | API-র একই নামের value |
| `RIVERSHIFT_CALLBACK_SECRET` | API-র একই নামের value |

Render-এর `GOOGLE_DRIVE_FOLDER_ID` এবং Actions-এর parent-folder ID একই private result folder নির্দেশ করবে। Source-এ দুটো variable name ব্যবহৃত হয়, তাই mapping স্পষ্ট রাখা হয়েছে। Render variables নিজে থেকে GitHub Actions-এ যায় না। GitHub Actions secrets-ও Render runtime-এ আসে না।

Workflow-এ `GITHUB_TOKEN` GitHub নিজে দেয়; আপনার API dispatch token সেটি নয়। API-র PAT Render-এ রাখুন। Actions চালু এবং reusable workflows চালানোর অনুমতি থাকতে হবে। Main-এ workflow file না থাকলে GitHub workflow dispatch কাজ নাও করতে পারে; migration review/merge আগে শেষ করুন।

## ৫. Supabase schema

নতুন Supabase project হলে `apps/dynamic/Backend/supabase/migrations/`-এর **সাতটি SQL file timestamp অনুযায়ী** apply করুন। বিদ্যমান project হলে আগে migration history/schema মিলিয়ে নিন; duplicate SQL চালাবেন না। বিশেষ করে শেষের RiverShift analysis-mode migration-ও প্রয়োজন। এই migration কাজের সময় কোনো Supabase project-এ SQL চালানো হয়নি।

Firebase user ownership active API যাচাই করে; legacy backend-এর SQLAlchemy tables/session API দিয়ে এই frontend চালাবেন না।

## ৬. Deploy-এর পর যাচাই

1. API `/health` খুলে response দেখুন। Health response একা Firebase/Supabase/Drive ঠিক থাকার প্রমাণ নয়।
2. Frontend-এ sign-in, map search, AOI drawing এবং direct page refresh পরীক্ষা করুন।
3. Catalogue preflight করুন; এটি metadata-only। তারপর নিজের account-এর job/archive list এবং authorization পরীক্ষা করুন।
4. GitHub/Render callback secrets মিলিয়ে processing switches enable করুন। Known Place dry-run দিয়ে dispatch/ref/permission যাচাই করা যায়।
5. সম্মত ছোট data window/AOI দিয়ে processing pilot চালিয়ে callback, failure reporting, private Drive result, dashboard, download ও retry পরীক্ষা করুন।

এখানে real satellite download, live processing, production data migration বা Render deployment করা হয়নি। GitHub Actions artifacts, Drive files, Supabase rows এবং secret values code repository transfer-এর অংশ নয়।

Rollback-এর জন্য পুরোনো repos ও deployments অপরিবর্তিত আছে। নতুন service-এ সমস্যা হলে dispatch switches `false` করুন এবং আগের reviewed deployment ব্যবহার করুন।

Render reference: [Blueprint specification](https://render.com/docs/blueprint-spec), [FastAPI deployment](https://render.com/docs/deploy-fastapi).
