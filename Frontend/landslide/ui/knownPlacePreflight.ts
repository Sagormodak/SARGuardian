import type { KnownPlaceAnalysisInput, KnownPlaceAnalysisRun } from '../../src/api/knownPlace';

export type StoredKnownPlaceRun = KnownPlaceAnalysisRun & {
  execute_downloads: boolean;
  request_fingerprint?: string;
};

/** Stable client-side identity for the exact catalog request a preflight checked. */
export function knownPlaceRequestFingerprint(input: KnownPlaceAnalysisInput): string {
  const scienceRequest: Partial<KnownPlaceAnalysisInput> = { ...input };
  delete scienceRequest.execute_downloads;
  delete scienceRequest.confirm_raw_downloads;
  return JSON.stringify(scienceRequest);
}

/**
 * A raw run may start only after a successful catalog-only run for exactly the
 * same scientific inputs. This is a UI guard; the backend still replans and
 * independently rejects ambiguous releases before any acquisition.
 */
export function hasMatchingKnownPlaceCatalogPreflight(
  run: StoredKnownPlaceRun | null,
  currentFingerprint: string,
): boolean {
  return Boolean(
    run
    && run.execute_downloads === false
    && run.status === 'completed'
    && run.conclusion === 'success'
    && typeof run.request_fingerprint === 'string'
    && run.request_fingerprint === currentFingerprint,
  );
}
