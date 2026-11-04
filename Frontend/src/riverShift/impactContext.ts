import type { RiverShiftGeoJSON } from './manifest';

export type ImpactPosition = [number, number];

export type ImpactExposurePointFeature = {
  type: 'Feature';
  id?: string | number;
  properties: Record<string, unknown>;
  geometry:
    | { type: 'Point'; coordinates: ImpactPosition }
    | { type: 'MultiPoint'; coordinates: ImpactPosition[] };
};

export type ImpactExposurePointCollection = {
  type: 'FeatureCollection';
  features: ImpactExposurePointFeature[];
};

export type ImpactClassSummary = {
  featureCount: number;
  populationValueSum: number | null;
  featuresMissingValue: number;
};

export type ImpactExposureSummary = {
  exposureFeatureCount: number;
  uniqueFeaturesInsideAnyCandidate: number;
  populationField: string | null;
  populationValueSum: number | null;
  featuresMissingPopulationValue: number;
  featuresMatchingMultipleClasses: number;
  candidatePolygonCount: number;
  sparseMarkerFeaturesExcluded: number;
  byClass: {
    erosion: ImpactClassSummary;
    deposition: ImpactClassSummary;
    newWater: ImpactClassSummary;
  };
};

const MAX_EXPOSURE_FEATURES = 100_000;
const MAX_POINTS_PER_FEATURE = 500;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function isPosition(value: unknown): value is ImpactPosition {
  return Array.isArray(value)
    && value.length >= 2
    && typeof value[0] === 'number'
    && Number.isFinite(value[0])
    && value[0] >= -180
    && value[0] <= 180
    && typeof value[1] === 'number'
    && Number.isFinite(value[1])
    && value[1] >= -90
    && value[1] <= 90;
}

function parsePointCoordinates(value: unknown, label: string): ImpactPosition[] {
  if (!Array.isArray(value)) throw new Error(label + ' has invalid coordinates.');
  if (value.length > MAX_POINTS_PER_FEATURE) throw new Error(label + ' contains too many points.');
  if (value.length === 2 && typeof value[0] === 'number') {
    if (!isPosition(value)) throw new Error(label + ' must use finite WGS84 longitude/latitude coordinates.');
    return [[value[0], value[1]]];
  }
  if (!value.length || !value.every(isPosition)) {
    throw new Error(label + ' must contain valid WGS84 point coordinates.');
  }
  return value.map((point) => [point[0], point[1]]);
}

/**
 * Accepts point/centroid features only. Polygon and line exposure datasets must
 * be converted to representative points before upload; this keeps the test
 * semantics explicit and avoids silently counting arbitrary geometry types.
 */
export function parseImpactExposureGeoJSON(value: unknown): ImpactExposurePointCollection {
  if (!isRecord(value) || value.type !== 'FeatureCollection' || !Array.isArray(value.features)) {
    throw new Error('Impact context must be a GeoJSON FeatureCollection.');
  }
  if (value.features.length === 0) throw new Error('Impact context GeoJSON contains no features.');
  if (value.features.length > MAX_EXPOSURE_FEATURES) {
    throw new Error('Impact context is limited to ' + MAX_EXPOSURE_FEATURES.toLocaleString() + ' features.');
  }

  const features: ImpactExposurePointFeature[] = value.features.map((raw, index) => {
    if (!isRecord(raw) || raw.type !== 'Feature' || !isRecord(raw.geometry)) {
      throw new Error('Impact feature ' + (index + 1) + ' is not a valid GeoJSON Feature.');
    }
    const geometry = raw.geometry;
    if (geometry.type !== 'Point' && geometry.type !== 'MultiPoint') {
      throw new Error('Impact feature ' + (index + 1) + ' must be Point or MultiPoint geometry.');
    }
    const positions = parsePointCoordinates(
      geometry.coordinates,
      'Impact feature ' + (index + 1),
    );
    if (geometry.type === 'Point' && positions.length !== 1) {
      throw new Error('Impact feature ' + (index + 1) + ' has malformed Point coordinates.');
    }
    const properties = isRecord(raw.properties) ? raw.properties : {};
    return {
      type: 'Feature',
      ...(typeof raw.id === 'string' || typeof raw.id === 'number' ? { id: raw.id } : {}),
      properties,
      geometry: geometry.type === 'Point'
        ? { type: 'Point', coordinates: positions[0] }
        : { type: 'MultiPoint', coordinates: positions },
    };
  });

  return { type: 'FeatureCollection', features };
}

type Ring = ImpactPosition[];
type PolygonRings = Ring[];
type CandidateClass = 'erosion' | 'deposition' | 'newWater';

function candidateClass(properties: Record<string, unknown> | undefined): CandidateClass | null {
  const value = properties?.river_shift_layer ?? properties?.class
    ?? properties?.change_type ?? properties?.candidate_type;
  if (typeof value !== 'string') return null;
  const normalized = value.toLowerCase().replace(/[\s-]+/g, '_');
  if (normalized.includes('erosion')) return 'erosion';
  if (normalized.includes('deposition') || normalized.includes('accretion')) return 'deposition';
  if (normalized.includes('new_water') || normalized.includes('newly_water')
    || normalized.includes('water_covered')) return 'newWater';
  return null;
}

function isPositionRing(value: unknown): value is Ring {
  return Array.isArray(value) && value.length >= 4 && value.every(isPosition);
}

function polygonFromCoordinates(value: unknown): PolygonRings | null {
  if (!Array.isArray(value) || value.length === 0 || !isPositionRing(value[0])) return null;
  const rings: PolygonRings = [];
  for (const rawRing of value) {
    if (!isPositionRing(rawRing)) return null;
    const ring = rawRing.map(([longitude, latitude]) => [longitude, latitude] as ImpactPosition);
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) ring.push([first[0], first[1]]);
    rings.push(ring);
  }
  return rings;
}

function polygonsFromFeature(feature: unknown): PolygonRings[] {
  if (!isRecord(feature) || !isRecord(feature.geometry)) return [];
  const geometry = feature.geometry;
  if (geometry.type === 'Polygon') {
    const polygon = polygonFromCoordinates(geometry.coordinates);
    return polygon ? [polygon] : [];
  }
  if (geometry.type === 'MultiPolygon' && Array.isArray(geometry.coordinates)) {
    return geometry.coordinates
      .map(polygonFromCoordinates)
      .filter((polygon): polygon is PolygonRings => polygon !== null);
  }
  return [];
}

function pointOnSegment(point: ImpactPosition, start: ImpactPosition, end: ImpactPosition): boolean {
  const cross = (point[1] - start[1]) * (end[0] - start[0])
    - (point[0] - start[0]) * (end[1] - start[1]);
  if (Math.abs(cross) > 1e-10) return false;
  const dot = (point[0] - start[0]) * (end[0] - start[0])
    + (point[1] - start[1]) * (end[1] - start[1]);
  if (dot < -1e-10) return false;
  const lengthSquared = (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2;
  return dot <= lengthSquared + 1e-10;
}

function pointInRing(point: ImpactPosition, ring: Ring): boolean {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const current = ring[index];
    const prior = ring[previous];
    if (pointOnSegment(point, prior, current)) return true;
    const crosses = (current[1] > point[1]) !== (prior[1] > point[1])
      && point[0] < ((prior[0] - current[0]) * (point[1] - current[1]))
        / (prior[1] - current[1]) + current[0];
    if (crosses) inside = !inside;
  }
  return inside;
}

function pointInPolygon(point: ImpactPosition, rings: PolygonRings): boolean {
  return pointInRing(point, rings[0])
    && !rings.slice(1).some((hole) => pointInRing(point, hole));
}

function featurePositions(feature: ImpactExposurePointFeature): ImpactPosition[] {
  return feature.geometry.type === 'Point'
    ? [feature.geometry.coordinates]
    : feature.geometry.coordinates;
}

function numericProperty(feature: ImpactExposurePointFeature, key: string | null): number | null {
  if (!key) return null;
  const value = feature.properties[key];
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null;
  return value;
}

/**
 * Counts representative points inside retained display-preview polygons.
 * These are potential exposure-context counts, not damaged assets or impact
 * estimates. Sparse preview markers are explicitly excluded from polygon math.
 */
export function summarizeImpactExposure(
  candidateLayers: RiverShiftGeoJSON[],
  exposure: ImpactExposurePointCollection,
  populationField?: string,
): ImpactExposureSummary {
  const field = populationField?.trim() || null;
  const classes: CandidateClass[] = ['erosion', 'deposition', 'newWater'];
  const polygons: Record<CandidateClass, PolygonRings[]> = {
    erosion: [],
    deposition: [],
    newWater: [],
  };
  let candidatePolygonCount = 0;
  let sparseMarkerFeaturesExcluded = 0;

  candidateLayers.forEach((layer) => {
    layer.features.forEach((feature) => {
      const category = candidateClass(feature.properties as Record<string, unknown> | undefined);
      if (!category) return;
      const geometryType = feature.geometry?.type;
      if (feature.properties?.preview_sparse_marker === true
        || geometryType === 'Point' || geometryType === 'MultiPoint') {
        sparseMarkerFeaturesExcluded += 1;
        return;
      }
      const featurePolygons = polygonsFromFeature(feature);
      if (featurePolygons.length) {
        polygons[category].push(...featurePolygons);
        candidatePolygonCount += featurePolygons.length;
      }
    });
  });

  const matched = {
    erosion: new Set<number>(),
    deposition: new Set<number>(),
    newWater: new Set<number>(),
  };
  const matchedAny = new Set<number>();
  const matchedMultipleClasses = new Set<number>();
  const sums: Record<CandidateClass, number> = { erosion: 0, deposition: 0, newWater: 0 };
  const missing: Record<CandidateClass, number> = { erosion: 0, deposition: 0, newWater: 0 };
  let uniquePopulationSum = 0;
  let uniqueFeaturesMissingValue = 0;

  exposure.features.forEach((feature, featureIndex) => {
    const positions = featurePositions(feature);
    const matchingClasses = classes.filter((category) => (
      polygons[category].some((polygon) => positions.some((point) => pointInPolygon(point, polygon)))
    ));
    if (!matchingClasses.length) return;

    matchedAny.add(featureIndex);
    if (matchingClasses.length > 1) matchedMultipleClasses.add(featureIndex);
    const value = numericProperty(feature, field);
    if (value === null) uniqueFeaturesMissingValue += 1;
    else uniquePopulationSum += value;

    matchingClasses.forEach((category) => {
      matched[category].add(featureIndex);
      if (value === null) missing[category] += 1;
      else sums[category] += value;
    });
  });

  const makeSummary = (category: CandidateClass): ImpactClassSummary => ({
    featureCount: matched[category].size,
    populationValueSum: field && polygons[category].length > 0 ? sums[category] : null,
    featuresMissingValue: field ? missing[category] : 0,
  });

  return {
    exposureFeatureCount: exposure.features.length,
    uniqueFeaturesInsideAnyCandidate: matchedAny.size,
    populationField: field,
    populationValueSum: field && candidatePolygonCount > 0 ? uniquePopulationSum : null,
    featuresMissingPopulationValue: field ? uniqueFeaturesMissingValue : 0,
    featuresMatchingMultipleClasses: matchedMultipleClasses.size,
    candidatePolygonCount,
    sparseMarkerFeaturesExcluded,
    byClass: {
      erosion: makeSummary('erosion'),
      deposition: makeSummary('deposition'),
      newWater: makeSummary('newWater'),
    },
  };
}
