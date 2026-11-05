import { setOptions } from '@googlemaps/js-api-loader';

let configuredApiKey: string | null = null;

/** Configure the shared Google Maps JS loader once for the application. */
export function configureGoogleMaps(apiKey: string): void {
  const key = apiKey.trim();
  if (!key) throw new Error('GOOGLE_MAPS_API_KEY_REQUIRED');
  if (configuredApiKey === key) return;
  if (configuredApiKey !== null && configuredApiKey !== key) {
    throw new Error('GOOGLE_MAPS_API_KEY_CHANGED_AFTER_INITIALIZATION');
  }
  setOptions({ key, v: 'weekly' });
  configuredApiKey = key;
}
