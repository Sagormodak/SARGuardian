# Dispatcher consent-marker mismatch — failed run 40107037642

**Run:** [40107037642 — SARGuardian AOI WKT E2E](https://github.com/moshiour0/SARGuardian-backend/actions/runs/40107037642)
**Branch commit:** 01cbd214f268e17ea79072e8068774dbeef77b9b
**Date:** 2026-10-24 UTC

## Root cause

The workflow was dispatched with profile **author-exact-p05023**, which always requires explicit raw-source consent. The job log shows **CONSENT_MARKER=run-know-place**. The gate requires an exact literal match to **[run-know-place]**, including both square brackets. Since the values differ, the gate correctly exited with **EXPLICIT_RAW_DOWNLOAD_CONSENT_MARKER_REQUIRED**.

This is an input/authorization failure, not a HDF5 download or scientific-analysis failure. Both downstream jobs — the generic AOI/date measurement engine and the five-pair exact-author analysis — were skipped.

## Impact and next action

- Raw GOFF/HDF5 download started: **No**.
- Scientific analysis started: **No**.
- Google Drive upload started: **No**.
- No fallback release substitution occurred in this run.
- Do not weaken the consent check to accept the unbracketed text.
- Re-run Actions → SARGuardian AOI WKT E2E (safe branch dispatcher), select branch feat/know-place-analysis, choose author-exact-p05023, and enter **[run-know-place]** exactly. Confirm Earthdata and Google Drive secrets are configured before dispatching.

The dispatcher now emits an explicit ACTION_REQUIRED line and writes the exact expected value into the GitHub step summary when consent does not match. A regression test asserts that the gate remains strict and explains the bracket requirement.

## Scientific gate remains separate

Correct consent authorizes the raw acquisition attempt; it does not imply source-byte parity, paper reproduction, or hazard detection. The next run must still record five actual HDF5 sizes and SHA-256 hashes, validate HDF5 product identity and grid alignment, preserve derived outputs, and verify the Google Drive receipts. Until those checks and subsequent implementation comparisons pass, PAPER_REPRODUCTION_STATUS=BLOCKED_RAW_GOFF_BYTES_AND_IMPLEMENTATION_PARITY_UNVERIFIED and HAZARD_DETECTION_STATUS=NOT_EVALUATED remain unchanged.

The branch is feat/know-place-analysis; main remains at 2218dfeb73353080d8d94bd733d9e7bd9a848886 and was not changed.
