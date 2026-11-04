import type { RiverShiftGeoJSON } from './manifest';

export type GeneralChangeType = 'erosion' | 'deposition' | 'new_water';

export type GeneralChangeMarker = {
  id: string;
  changeType: GeneralChangeType;
  longitude: number;
  latitude: number;
};

type Position = [number, number];
type Ring = Position[];
type PolygonRings = Ring[];

type Centroid = {
  longitude: number;
  latitude: number;
  area: number;
};

const DEFAULT_MARKERS_PER_CLASS = 24;

function isPosition(value: unknown): value is Position {
  return Array.isArray(value)
    && value.length >= 2
    && typeof value[0] === 'number' && Number.isFinite(value[0])
    && typeof value[1] === 'number' && Number.isFinite(value[1])
    && value[0] >= -180 && value[0] <= 180
    && value[1] >= -90 && value[1] <= 90;
}

function normalizeRings(value: unknown): PolygonRings | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const rings: PolygonRings = [];
  for (const rawRing of value) {
    if (!Array.isArray(rawRing) || rawRing.length < 4 || !rawRing.every(isPosition)) return null;
    const ring = rawRing.map(([longitude, latitude]) => [longitude, latitude] as Position);
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) ring.push([...first]);
    if (ring.length < 4) return null;
    rings.push(ring);
  }
  return rings;
}

function ringCentroid(ring: Ring): Centroid | null {
  let twiceArea = 0;
  let longitudeNumerator = 0;
  let latitudeNumerator = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const current = ring[index];
    const next = ring[(index + 1) % ring.length];
    const cross = current[0] * next[1] - next[0] * current[1];
    twiceArea += cross;
    longitudeNumerator += (current[0] + next[0]) * cross;
    latitudeNumerator += (current[1] + next[1]) * cross;
  }
  if (Math.abs(twiceArea) < 1e-14) return null;
  return {
    longitude: longitudeNumerator / (3 * twiceArea),
    latitude: latitudeNumerator / (3 * twiceArea),
    area: Math.abs(twiceArea) / 2,
  };
}

function pointInRing(point: Position, ring: Ring): boolean {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const [x, y] = ring[index];
    const [previousX, previousY] = ring[previous];
    const crosses = (y > point[1]) !== (previousY > point[1])
      && point[0] < ((previousX - x) * (point[1] - y)) / (previousY - y) + x;
    if (crosses) inside = !inside;
  }
  return inside;
}

function pointInPolygon(point: Position, rings: PolygonRings): boolean {
  return pointInRing(point, rings[0]) && !rings.slice(1).some((hole) => pointInRing(point, hole));
}

function distanceToRing(point: Position, ring: Ring, longitudeScale: number): number {
  let minimum = Number.POSITIVE_INFINITY;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const start = ring[index];
    const end = ring[index + 1];
    const px = point[0] * longitudeScale;
    const py = point[1];
    const ax = start[0] * longitudeScale;
    const ay = start[1];
    const bx = end[0] * longitudeScale;
    const by = end[1];
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    const fraction = lengthSquared > 0
      ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared))
      : 0;
    const nearestX = ax + fraction * dx;
    const nearestY = ay + fraction * dy;
    minimum = Math.min(minimum, Math.hypot(px - nearestX, py - nearestY));
  }
  return minimum;
}

function findInteriorPoint(rings: PolygonRings): Position | null {
  const outer = rings[0];
  const longitudes = outer.map(([longitude]) => longitude);
  const latitudes = outer.map(([, latitude]) => latitude);
  const minLongitude = Math.min(...longitudes);
  const maxLongitude = Math.max(...longitudes);
  const minLatitude = Math.min(...latitudes);
  const maxLatitude = Math.max(...latitudes);
  if (maxLongitude <= minLongitude || maxLatitude <= minLatitude) return null;

  const meanLatitude = (minLatitude + maxLatitude) / 2;
  const longitudeScale = Math.max(0.1, Math.cos((meanLatitude * Math.PI) / 180));
  let bestPoint: Position | null = null;
  let bestClearance = -1;
  const divisions = 32;
  for (let x = 0; x < divisions; x += 1) {
    for (let y = 0; y < divisions; y += 1) {
      const point: Position = [
        minLongitude + ((x + 0.5) / divisions) * (maxLongitude - minLongitude),
        minLatitude + ((y + 0.5) / divisions) * (maxLatitude - minLatitude),
      ];
      if (!pointInPolygon(point, rings)) continue;
      const clearance = Math.min(...rings.map((ring) => distanceToRing(point, ring, longitudeScale)));
      if (clearance > bestClearance) {
        bestClearance = clearance;
        bestPoint = point;
      }
    }
  }
  return bestPoint;
}

function polygonRepresentativePoint(rings: PolygonRings): Centroid | null {
  const outer = ringCentroid(rings[0]);
  if (!outer) return null;
  const holes = rings.slice(1).map(ringCentroid).filter((item): item is Centroid => Boolean(item));
  const polygonArea = outer.area - holes.reduce((sum, hole) => sum + hole.area, 0);
  let point: Position = [outer.longitude, outer.latitude];

  if (polygonArea > 1e-14) {
    point = [
      (outer.longitude * outer.area - holes.reduce((sum, hole) => sum + hole.longitude * hole.area, 0)) / polygonArea,
      (outer.latitude * outer.area - holes.reduce((sum, hole) => sum + hole.latitude * hole.area, 0)) / polygonArea,
    ];
  }

  if (!Number.isFinite(point[0]) || !Number.isFinite(point[1]) || !pointInPolygon(point, rings)) {
    const interior = findInteriorPoint(rings);
    if (!interior) return null;
    point = interior;
  }

  return { longitude: point[0], latitude: point[1], area: Math.max(0, polygonArea) };
}

function changeTypeFromProperties(properties: Record<string, unknown> | undefined): GeneralChangeType | null {
  const value = properties?.river_shift_layer ?? properties?.class ?? properties?.change_type;
  if (typeof value !== 'string') return null;
  const normalized = value.toLowerCase().replace(/[\s-]+/g, '_');
  if (normalized.includes('erosion')) return 'erosion';
  if (normalized.includes('deposition')) return 'deposition';
  if (normalized.includes('new_water') || normalized.includes('newly_water')) return 'new_water';
  return null;
}

/**
 * Derive display-only point markers from the retained General Scan candidate
 * footprints. Markers are representative points for connected polygon parts;
 * they are not independent measurements or date-specific observations.
 */
export function deriveGeneralChangeMarkers(
  data: RiverShiftGeoJSON,
  maxPerClass = DEFAULT_MARKERS_PER_CLASS,
): GeneralChangeMarker[] {
  if (!Number.isInteger(maxPerClass) || maxPerClass < 1) return [];
  const candidates: Array<GeneralChangeMarker & { area: number }> = [];

  data.features.forEach((feature, featureIndex) => {
    const changeType = changeTypeFromProperties(feature.properties);
    if (!changeType) return;

    const geometryType = feature.geometry.type;
    const coordinates = feature.geometry.coordinates;
    const polygons = geometryType === 'Polygon'
      ? [normalizeRings(coordinates)].filter((rings): rings is PolygonRings => Boolean(rings))
      : geometryType === 'MultiPolygon' && Array.isArray(coordinates)
        ? coordinates.map(normalizeRings).filter((rings): rings is PolygonRings => Boolean(rings))
        : [];

    polygons.forEach((rings, polygonIndex) => {
      const representative = polygonRepresentativePoint(rings);
      if (!representative) return;
      candidates.push({
        id: `feature-${featureIndex}-part-${polygonIndex}-${changeType}`,
        changeType,
        longitude: representative.longitude,
        latitude: representative.latitude,
        area: representative.area,
      });
    });
  });

  const counts: Record<GeneralChangeType, number> = { erosion: 0, deposition: 0, new_water: 0 };
  const selected: Array<GeneralChangeMarker & { area: number }> = [];
  for (const candidate of candidates.sort((left, right) => right.area - left.area)) {
    if (counts[candidate.changeType] >= maxPerClass) continue;
    counts[candidate.changeType] += 1;
    selected.push(candidate);
  }
  return selected.map((candidate) => ({
    id: candidate.id,
    changeType: candidate.changeType,
    longitude: candidate.longitude,
    latitude: candidate.latitude,
  }));
}
