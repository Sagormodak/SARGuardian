import { describe, expect, it } from 'vitest';
import type { KnownPlaceAnalysisInput } from '../../src/api/knownPlace';
import {
  hasMatchingKnownPlaceCatalogPreflight,
  knownPlaceRequestFingerprint,
  type StoredKnownPlaceRun,
} from './knownPlacePreflight';

const baseInput: KnownPlaceAnalysisInput = {
  aoi_wkt: 'POLYGON ((85.52 28.28, 85.54 28.28, 85.54 28.30, 85.52 28.30, 85.52 28.28))',
  scope_aoi_wkt: 'POLYGON ((85.50 28.26, 85.56 28.26, 85.56 28.32, 85.50 28.32, 85.50 28.26))',
  start_date: '2026-06-20',
  end_date: '2026-09-18',
  hazard_mode: 'ice_rock_avalanche',
  analysis_mode: 'exploratory',
  polarization: 'HH',
  track: 'ANY',
  direction: 'ANY',
  coherence_neighbours: '1',
  allowed_release_ids: '',
  reference_wkt: 'POLYGON ((85.50 28.265, 85.565 28.265, 85.565 28.318, 85.50 28.318, 85.50 28.265))',
  geometry_height_m: null,
  execute_downloads: false,
  confirm_raw_downloads: false,
};

function successfulDryRun(fingerprint: string): StoredKnownPlaceRun {
  return {
    request_id: 'c2604677-480b-43fa-8819-f9b11cf7579b',
    status: 'completed',
    github_run_id: '41409972359',
    github_run_url: 'https://github.com/moshiour0/SARGuardian-backend/actions',
    conclusion: 'success',
    created_at: null,
    updated_at: null,
    execute_downloads: false,
    request_fingerprint: fingerprint,
    notice: 'Catalog-only dry run completed.',
  };
}

describe('Known Place catalog preflight gate', () => {
  it('allows raw analysis only after a successful dry run for identical science inputs', () => {
    const fingerprint = knownPlaceRequestFingerprint(baseInput);
    expect(hasMatchingKnownPlaceCatalogPreflight(successfulDryRun(fingerprint), fingerprint)).toBe(true);
  });

  it('invalidates preflight when the release allowlist changes', () => {
    const fingerprint = knownPlaceRequestFingerprint(baseInput);
    const changed = {
      ...baseInput,
      allowed_release_ids: 'P05023',
    };
    expect(
      hasMatchingKnownPlaceCatalogPreflight(
        successfulDryRun(fingerprint),
        knownPlaceRequestFingerprint(changed),
      ),
    ).toBe(false);
  });

  it('invalidates preflight when geometry or date window changes', () => {
    const fingerprint = knownPlaceRequestFingerprint(baseInput);
    const changedGeometry = { ...baseInput, aoi_wkt: 'POLYGON ((85.52 28.28, 85.53 28.28, 85.53 28.29, 85.52 28.29, 85.52 28.28))' };
    const changedDates = { ...baseInput, end_date: '2026-08-31' };
    expect(hasMatchingKnownPlaceCatalogPreflight(successfulDryRun(fingerprint), knownPlaceRequestFingerprint(changedGeometry))).toBe(false);
    expect(hasMatchingKnownPlaceCatalogPreflight(successfulDryRun(fingerprint), knownPlaceRequestFingerprint(changedDates))).toBe(false);
  });

  it('rejects failed, in-progress, and raw runs as preflight evidence', () => {
    const fingerprint = knownPlaceRequestFingerprint(baseInput);
    const success = successfulDryRun(fingerprint);
    expect(hasMatchingKnownPlaceCatalogPreflight({ ...success, conclusion: 'failure' }, fingerprint)).toBe(false);
    expect(hasMatchingKnownPlaceCatalogPreflight({ ...success, status: 'in_progress' }, fingerprint)).toBe(false);
    expect(hasMatchingKnownPlaceCatalogPreflight({ ...success, execute_downloads: true }, fingerprint)).toBe(false);
  });
});
