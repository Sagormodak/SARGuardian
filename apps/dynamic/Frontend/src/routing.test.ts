import { describe, expect, it, vi } from 'vitest';
import { ARCHIVE_PATH, LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH, LANDSLIDE_KNOWN_PLACE_SETUP_PATH, isArchiveRoute, isLandslideKnownPlaceAnalysisRoute, isLandslideKnownPlaceSetupAnalysisRoute, isLandslideKnownPlaceSetupRoute, isLandslideResultsRoute, isLandslideRoute, navigatePath, normalizePathname } from './routing';

describe('client-side route recognition', () => {
  it('recognizes Archive as its own page route, not a Home anchor', () => {
    expect(ARCHIVE_PATH).toBe('/archive');
    expect(isArchiveRoute('/archive')).toBe(true);
    expect(isArchiveRoute('/archive?state=ready')).toBe(true);
    expect(isArchiveRoute('/')).toBe(false);
    expect(isLandslideRoute('/archive')).toBe(false);
  });

  it('normalizes query strings and hashes without changing the route', () => {
    expect(normalizePathname('/landslide/results?from=map#summary')).toBe('/landslide/results');
    expect(normalizePathname('')).toBe('/');
  });

  it('recognizes the dedicated home-launched Known Place setup and two-polygon analysis routes', () => {
    expect(LANDSLIDE_KNOWN_PLACE_SETUP_PATH).toBe('/landslide/known-place-setup');
    expect(LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH).toBe('/landslide/known-place-setup/analysis');
    expect(isLandslideKnownPlaceSetupRoute('/landslide/known-place-setup')).toBe(true);
    expect(isLandslideKnownPlaceSetupRoute('/landslide/known-place-setup?source=home')).toBe(true);
    expect(isLandslideKnownPlaceSetupAnalysisRoute('/landslide/known-place-setup/analysis')).toBe(true);
    expect(isLandslideKnownPlaceAnalysisRoute('/landslide/known-place-setup/analysis')).toBe(true);
    expect(isLandslideKnownPlaceAnalysisRoute('/landslide/known-place-analysis')).toBe(true);
    expect(isLandslideKnownPlaceAnalysisRoute('/landslide/displacements')).toBe(false);
    expect(isLandslideRoute('/landslide/known-place-setup')).toBe(true);
    expect(isLandslideRoute('/landslide/known-place-setup/analysis')).toBe(true);
  });

  it('recognizes the map and results routes', () => {
    expect(isLandslideRoute('/landslide')).toBe(true);
    expect(isLandslideRoute('/landslide/results')).toBe(true);
    expect(isLandslideResultsRoute('/landslide/results')).toBe(true);
    expect(isLandslideResultsRoute('/landslide/results?from=map')).toBe(true);
    expect(isLandslideResultsRoute('/landslide')).toBe(false);
    expect(isLandslideRoute('/')).toBe(false);
  });

  it('pushes a route once and returns the normalized route for React state', () => {
    const pushState = vi.fn();
    expect(navigatePath('/landslide/results?from=map', '/landslide', pushState)).toBe('/landslide/results');
    expect(pushState).toHaveBeenCalledOnce();
    expect(pushState).toHaveBeenCalledWith({}, '', '/landslide/results');

    expect(navigatePath('/landslide/results', '/landslide/results', pushState)).toBe('/landslide/results');
    expect(pushState).toHaveBeenCalledOnce();
  });
});
