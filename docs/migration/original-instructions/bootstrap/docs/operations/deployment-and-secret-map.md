# Deployment and secret migration constraints

**Purpose:** map configuration requirements without copying secret values.

## Deployment ownership

- Current web/API hosting is Vercel according to the project handoff.
- Do not treat historical `render.yaml` in backend source as proof that Render is still used.
- Dynamic has separate frontend and API Vercel configuration. Verify project Root Directory, build command, output directory, function settings, environment scopes, and production branch before changing paths.
- Keep production alias and callback destinations unchanged until preview passes.
- RiverShift map search uses Google Places autocomplete; verify Places API (New) is enabled for the Google Cloud project associated with the browser key.

## Configuration categories

Secret values must remain in GitHub/Vercel secret stores and must never be committed here.

| Category | Examples | Handling |
|---|---|---|
| Frontend public config | Firebase web config, Google Maps browser key, backend URL | Vite-prefixed public variables only when intended for browser exposure |
| API identity | Firebase Admin service-account JSON | Server-side only; never place in Vite env |
| Supabase | Project URL, service-role key | Service-role key server-side only; preserve RLS and persistence |
| GitHub Actions | Fine-grained token, dispatch repository/workflow/ref | Minimum required repository and Actions permissions |
| Callbacks | Displacement and RiverShift callback URLs/secrets | Preserve auth contracts; never log secret values |
| ASF/Drive | ASF catalogue and Drive credentials | Server/Actions only; verify cleanup and remote receipt semantics |

## Exact-name compatibility

Preserve existing variable names until every consumer is mapped. In particular, backend Actions has an existing variable named `Google drive parent folder id`. Do not silently replace it with `GOOGLE_DRIVE_FOLDER_ID` or introduce a second parent-folder variable.

Never place service-account JSON, Firebase Admin JSON, PATs, API keys, Supabase service-role keys, callback secrets, or signed URLs in Git commits, sample files, Actions logs, PR descriptions, artifacts, or issue comments.

## Required pre-cutover evidence

- Current Vercel project IDs and root directories are recorded.
- Frontend/API variable names are mapped by Development/Preview/Production.
- Workflow secrets/variables are mapped by source repository and consumer.
- No secret value was copied or exposed in the monorepo.
- Supabase project ID, schema ownership, RLS, retention, and migration history are verified.
- Callback URLs and signatures are exercised in preview/mock mode.
- Rollback to current Vercel deployment and old workflow dispatchers is tested.
