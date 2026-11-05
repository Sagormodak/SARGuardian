import type { KnownPlaceAnalysisInput, KnownPlaceAnalysisRun } from '../../src/api/knownPlace';

export type StoredKnownPlaceRun = KnownPlaceAnalysisRun & {
  execute_downloads: boolean;
  request_fingerprint?: string;
};

/** A catalog preflight is only a short-lived snapshot of a changing ASF catalogue. */
export const KNOWN_PLACE_PREFLIGHT_MAX_AGE_MS = 15 * 60 * 1000;

/** Stable client-side identity for the exact catalog request a preflight checked. */
export function knownPlaceRequestFingerprint(input: KnownPlaceAnalysisInput): string {
  const scienceRequest: Partial<KnownPlaceAnalysisInput> = { ...input };
  delete scienceRequest.execute_downloads;
  delete scienceRequest.confirm_raw_downloads;
  return JSON.stringify(scienceRequest);
}

/**
 * A raw run may start only after a recent successful catalog-only run for
 * exactly the same scientific inputs. Old sessionStorage evidence must not
 * unlock a raw replay after deployment, backend-pin or catalogue changes.
 * The backend still replans and independently rejects ambiguous releases
 * before any acquisition.
 */
export function hasMatchingKnownPlaceCatalogPreflight(
  run: StoredKnownPlaceRun | null,
  currentFingerprint: string,
  nowMs = Date.now(),
): boolean {
  const completedAtMs = run?.created_at ? Date.parse(run.created_at) : Number.NaN;
  const preflightAgeMs = nowMs - completedAtMs;
  return Boolean(
    run
    && run.execute_downloads === false
    && run.status === 'completed'
    && run.conclusion === 'success'
    && typeof run.request_fingerprint === 'string'
    && run.request_fingerprint === currentFingerprint
    && Number.isFinite(completedAtMs)
    && preflightAgeMs >= 0
    && preflightAgeMs <= KNOWN_PLACE_PREFLIGHT_MAX_AGE_MS,
  );
}
