export const ARCHIVE_PATH = '/archive';
export const DASHBOARD_PATH = '/dashboard';
export const RIVER_SHIFT_PATH = '/river-shift';
export const LANDSLIDE_PATH = '/landslide';
export const LANDSLIDE_RESULTS_PATH = '/landslide/results';
export const LANDSLIDE_DISPLACEMENT_PATH = '/landslide/displacements';
export const LANDSLIDE_KNOWN_PLACE_PATH = '/landslide/known-place-analysis';
export const LANDSLIDE_KNOWN_PLACE_SETUP_PATH = '/landslide/known-place-setup';
export const LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH = '/landslide/known-place-setup/analysis';

export function isDashboardRoute(pathname: string): boolean {
  return normalizePathname(pathname) === DASHBOARD_PATH;
}

export function isRiverShiftRoute(pathname: string): boolean {
  return normalizePathname(pathname) === RIVER_SHIFT_PATH;
}

export function isArchiveRoute(pathname: string): boolean {
  return normalizePathname(pathname) === ARCHIVE_PATH;
}

export function isLandslideDisplacementRoute(pathname: string): boolean {
  return normalizePathname(pathname) === LANDSLIDE_DISPLACEMENT_PATH;
}

export function isLandslideKnownPlaceSetupRoute(pathname: string): boolean {
  return normalizePathname(pathname) === LANDSLIDE_KNOWN_PLACE_SETUP_PATH;
}

export function isLandslideKnownPlaceSetupAnalysisRoute(pathname: string): boolean {
  return normalizePathname(pathname) === LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH;
}

export function isLandslideKnownPlaceAnalysisRoute(pathname: string): boolean {
  const normalizedPath = normalizePathname(pathname);
  return normalizedPath === LANDSLIDE_KNOWN_PLACE_PATH
    || normalizedPath === LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH;
}

export function normalizePathname(pathname: string): string {
  const pathOnly = pathname.split(/[?#]/, 1)[0];
  return pathOnly || '/';
}

export function isLandslideRoute(pathname: string): boolean {
  const normalizedPathname = normalizePathname(pathname);
  return normalizedPathname === LANDSLIDE_PATH || normalizedPathname.startsWith(`${LANDSLIDE_PATH}/`);
}

export function isLandslideResultsRoute(pathname: string): boolean {
  return normalizePathname(pathname) === LANDSLIDE_RESULTS_PATH;
}

export function navigatePath(
  nextPath: string,
  currentPath: string,
  pushState: (state: unknown, unused: string, url?: string | URL | null) => void,
): string {
  const normalizedPath = normalizePathname(nextPath);
  if (normalizePathname(currentPath) !== normalizedPath) {
    pushState({}, '', normalizedPath);
  }
  return normalizedPath;
}
