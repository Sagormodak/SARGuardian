import { beforeEach, describe, expect, it, vi } from 'vitest';

const { setOptionsMock } = vi.hoisted(() => ({ setOptionsMock: vi.fn() }));

vi.mock('@googlemaps/js-api-loader', () => ({ setOptions: setOptionsMock }));

describe('shared Google Maps loader configuration', () => {
  beforeEach(() => {
    vi.resetModules();
    setOptionsMock.mockReset();
  });

  it('configures the loader exactly once when both AOI and Known Place maps use the same key', async () => {
    const { configureGoogleMaps } = await import('./googleMapsLoader');
    configureGoogleMaps('test-google-maps-key');
    configureGoogleMaps('test-google-maps-key');
    expect(setOptionsMock).toHaveBeenCalledOnce();
    expect(setOptionsMock).toHaveBeenCalledWith({ key: 'test-google-maps-key', v: 'weekly' });
  });

  it('rejects a key change after the shared loader has initialized', async () => {
    const { configureGoogleMaps } = await import('./googleMapsLoader');
    configureGoogleMaps('first-key');
    expect(() => configureGoogleMaps('different-key')).toThrow('GOOGLE_MAPS_API_KEY_CHANGED_AFTER_INITIALIZATION');
    expect(setOptionsMock).toHaveBeenCalledOnce();
  });

  it('rejects an empty key without calling the Maps loader', async () => {
    const { configureGoogleMaps } = await import('./googleMapsLoader');
    expect(() => configureGoogleMaps('  ')).toThrow('GOOGLE_MAPS_API_KEY_REQUIRED');
    expect(setOptionsMock).not.toHaveBeenCalled();
  });
});
