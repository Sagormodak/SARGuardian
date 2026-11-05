# SARGuardian — standalone frontend

Existing React + TypeScript + Vite frontend extracted from SARGuardian.
The UI source and existing authentication behavior are preserved.

## Run locally

Install Node.js 22 or newer, then open a terminal in this folder:

```sh
npm ci
npm run dev
```

Open http://localhost:5173. The home page loads without configuration.

For Google login and the map, copy `.env.example` to `.env.local` and fill in
your own Firebase and Google Maps project values. Set `VITE_SARGUARDIAN_API_URL`
to the deployed metadata API URL (or leave `http://localhost:8000` for local
development). All variables in this file are public browser configuration:
`VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_APP_ID`, `VITE_FIREBASE_AUTH_DOMAIN`,
`VITE_FIREBASE_MEASUREMENT_ID`, `VITE_FIREBASE_MESSAGING_SENDER_ID`,
`VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_STORAGE_BUCKET`,
`VITE_GOOGLE_MAPS_API_KEY`, and `VITE_SARGUARDIAN_API_URL`. Never put Supabase
server keys, Firebase Admin JSON, NASA Earthdata passwords, or tokens in any `VITE_*` variable.
Restart after changing them. The original
account configuration is not bundled in this standalone copy.

The Landslide page keeps the original Google sign-in requirement. Configure
Google sign-in and the authorized domain in your Firebase project. External
map, image, and search services require an internet connection. The map still
requires a Google Maps API key; check that provider's current billing and quota
conditions before publishing a public demo.

## Run with the metadata API

Start the backend from `SARGuardian_Dynamic/Backend` (see its README), then
set `VITE_SARGUARDIAN_API_URL=http://localhost:8000`. The API searches ASF
metadata only and returns candidate granules plus the sum of reported full-file
sizes. It does not download or process satellite data.

## Build

```sh
npm run build
npm run preview
```

Production output is generated in `dist/`. Preview runs at http://localhost:4173.
For Vercel, set the project root to `Frontend/`, use the Vite preset, build command
`npm run build`, and output directory `dist`. Set the public frontend environment variables
before building. The backend is a separate Vercel project rooted at `Backend/`; set its
server-side variables in that project only. The included SPA rewrite supports opening `/landslide` directly.

## Included files:

- `src/`: home page, navigation, components, styles, Firebase configuration.
- `landslide/ui/`: Landslide investigation screen and its styles.
- `landslide/engine/`: browser-side types, validation, and fixture adapter
  required by that screen.
- `landslide/fixtures/` and the existing TypeScript tests.
- Vite, TypeScript, ESLint, package manifest, and dependency lockfile.

## RiverShift workspace

RiverShift is a separate, available NISAR L-band GCOV workflow in this frontend. A signed-in user selects a WGS84 river-reach AOI and observation window; the app discovers compatible catalogue acquisitions and dispatches the scientific processing job to the RiverShift worker in `moshiour0/SARGuardian-backend`. The workflow is designed for eligible river reaches across the mission's global L-band land-observation footprint. Its current request envelope is one valid Polygon up to 1,000 km² and a date window up to 366 days, with at least four distinct acquisition dates and 90% catalogue-footprint coverage per selected date. The worker performs additional product and valid-raster checks. Results use actual acquisition dates and remain provisional until independently reviewed.

The older `Check NISAR archive` and `Reference demo` descriptions below refer only to the separate Landslide workspace: the archive action is a lightweight metadata preflight, while the reference action uses a precomputed fixture rather than live Landslide processing. They do not describe RiverShift.

For the judge-facing global applicability, evidence map and current scientific interpretation, see the [RiverShift Judge Brief](https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/NASA_SPACE_APPS_2026_JUDGE_BRIEF.md) and [full Judge Guide](https://github.com/moshiour0/SARGuardian-backend/blob/main/tools/river_shift/NASA_SPACE_APPS_2026_JUDGE_GUIDE.md).

## বাংলা নির্দেশনা:

এটি আগের frontend-এর আলাদা কপি। ZIP extract করে এই ফোল্ডারে terminal খুলুন,
তারপর `npm ci` এবং `npm run dev` চালান। Browser-এ `http://localhost:5173`
খুললে Home page পাবেন। Google login ও map চালাতে `.env.example` দেখে
নিজের configuration দিয়ে `.env.local` তৈরি করতে হবে। Landslide-এর ফলাফল
বর্তমানে demo fixture থেকে আসে, live NISAR analysis থেকে নয়।
