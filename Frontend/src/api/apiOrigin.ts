/** Resolve one backend origin for every Vite build target. */
export function resolveApiBaseUrl(configured: string | undefined, isDevelopment: boolean): string {
  const override = configured?.trim();
  const fallback = isDevelopment
    ? 'http://localhost:8000'
    : 'https://sarguardian-backend-api.vercel.app';
  return (override || fallback).replace(/\/+$/, '');
}
