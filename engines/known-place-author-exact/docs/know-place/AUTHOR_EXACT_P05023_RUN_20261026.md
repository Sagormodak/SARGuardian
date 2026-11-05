# Authorized exact-author P05023 replay request — 2026-10-26

**Authorization:** The user explicitly supplied `[run-know-place]` and authorized the necessary downloads for a real Bhote Koshi displacement measurement.

**Scope:** Run only the exact five author-published NISAR L2 PR GOFF products whose release identifier is `P05023`, ascending track 098, L-SAR HH, for intervals covering 2026-06-20 through 2026-08-31. Do not silently substitute the historical `X05026` variant.

**Geometry and exploratory parameters:** Reference box WKT and published-bounds crown rectangle are defined in the versioned workflow/reference manifest. The crown is explicitly a bounding-box approximation, not an exact author-editable polygon. Use geometry height 5151 m, 1000 deterministic control draws, seed 260826, and the workflow's source identity, grid, quality, Drive-retention and raw-cleanup gates.

**Required outputs:** Exact source granule identities and SHA-256 hashes for all five products; per-pair exploratory displacement metrics; raw quality/support counts; report and provenance; interactive dashboard/map if emitted by the author workflow; successful private Google Drive upload and remote receipt verification; raw-file cleanup only after those checks.

**Claims boundary:** This run is exploratory measurement, not a calibrated landslide/glacier-collapse detector. Keep paper-reproduction status blocked unless the remaining exact-crown and method-parity gates are proven, and keep hazard detection `NOT_EVALUATED` unless an independent validation protocol is completed.

**Execution note:** The first bridge attempt was fail-closed and performed no download because the reusable child saw the caller's push event. The consent bridge now passes a dedicated `bridge_authorized: true` input after verifying the commit marker and request-file path; the child workflow still independently requires the exact `[run-know-place]` token. This retrigger is for the same authorized P05023 run only.

**Retry after dependency correction (2026-10-26):** The runtime now has one authoritative `asf_search==13.0.1` pin; `tools/requirements-retention.txt` no longer pins the ASF client. Isolated validation [Run 40232340013](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40232340013) passed all tests, workflow semantic validation, and live no-download catalog gates. Rerun the same exact-author P05023 scope; do not invoke the historical mixed-release replay.

**Revalidated execution request (2026-10-28):** Continue the same already-authorized exact P05023 replay through `.github/workflows/know-place-author-exact-consent-bridge.yml`. This update does not authorize the historical X05026 mixed-release workflow, does not change `main`, and does not broaden the five-product scope.
