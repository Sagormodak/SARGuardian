export type Wgs84Point = [longitude: number, latitude: number];

function orientation(a: Wgs84Point, b: Wgs84Point, c: Wgs84Point): number {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function segmentsIntersect(a: Wgs84Point, b: Wgs84Point, c: Wgs84Point, d: Wgs84Point): boolean {
  const epsilon = 1e-12;
  const abC = orientation(a, b, c);
  const abD = orientation(a, b, d);
  const cdA = orientation(c, d, a);
  const cdB = orientation(c, d, b);
  if (abC * abD < -epsilon && cdA * cdB < -epsilon) return true;
  const onSegment = (p: Wgs84Point, q: Wgs84Point, r: Wgs84Point, area: number) =>
    Math.abs(area) <= epsilon
    && q[0] >= Math.min(p[0], r[0]) - epsilon && q[0] <= Math.max(p[0], r[0]) + epsilon
    && q[1] >= Math.min(p[1], r[1]) - epsilon && q[1] <= Math.max(p[1], r[1]) + epsilon;
  return onSegment(a, c, b, abC) || onSegment(a, d, b, abD)
    || onSegment(c, a, d, cdA) || onSegment(c, b, d, cdB);
}

function validateRing(points: Wgs84Point[]): void {
  const vertices = points.slice(0, -1);
  if (new Set(vertices.map(([longitude, latitude]) => `${longitude},${latitude}`)).size < 3) {
    throw new Error('AOI needs at least 3 distinct vertices.');
  }
  const doubledArea = vertices.reduce((sum, point, index) => {
    const next = vertices[(index + 1) % vertices.length];
    return sum + point[0] * next[1] - next[0] * point[1];
  }, 0);
  for (let first = 0; first < vertices.length; first += 1) {
    const firstNext = (first + 1) % vertices.length;
    for (let second = first + 1; second < vertices.length; second += 1) {
      const secondNext = (second + 1) % vertices.length;
      if (first === second || firstNext === second || secondNext === first) continue;
      if (segmentsIntersect(vertices[first], vertices[firstNext], vertices[second], vertices[secondNext])) {
        throw new Error('AOI polygon self-intersects. Redraw the boundary without crossing edges.');
      }
    }
  }
  if (Math.abs(doubledArea) < 1e-12) throw new Error('AOI polygon has zero area.');
}

export function parseWktPolygon(wkt: string): Wgs84Point[] {
  const normalized = wkt.trim();
  if (!/^POLYGON\s*\(\(/i.test(normalized) || !/\)\)\s*$/.test(normalized)) {
    throw new Error('AOI must be a single-ring POLYGON WKT.');
  }
  const body = normalized.replace(/^POLYGON\s*\(\(/i, '').replace(/\)\)\s*$/, '');
  const points = body.split(',').map((pair) => {
    const values = pair.trim().split(/\s+/).map(Number);
    if (values.length !== 2 || !Number.isFinite(values[0]) || !Number.isFinite(values[1])) {
      throw new Error('AOI has an invalid longitude/latitude pair.');
    }
    if (values[0] < -180 || values[0] > 180 || values[1] < -90 || values[1] > 90) {
      throw new Error('AOI coordinate is outside WGS84 longitude/latitude limits.');
    }
    return [values[0], values[1]] as Wgs84Point;
  });
  if (points.length < 4) throw new Error('AOI needs 3 vertices plus a closing coordinate.');
  const first = points[0];
  const last = points[points.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) {
    throw new Error('AOI polygon must repeat its first coordinate at the end.');
  }
  validateRing(points);
  return points;
}

export function formatWktPolygon(vertices: Wgs84Point[]): string {
  if (vertices.length < 3) throw new Error('Draw at least 3 AOI vertices.');
  const rounded = vertices.map(([longitude, latitude]) => {
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)
      || longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
      throw new Error('AOI coordinate is outside WGS84 longitude/latitude limits.');
    }
    return [Number(longitude.toFixed(6)), Number(latitude.toFixed(6))] as Wgs84Point;
  });
  const first = rounded[0];
  const last = rounded[rounded.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) rounded.push([...first]);
  validateRing(rounded);
  const wkt = `POLYGON ((${rounded.map(([longitude, latitude]) => `${longitude} ${latitude}`).join(', ')}))`;
  parseWktPolygon(wkt);
  return wkt;
}
