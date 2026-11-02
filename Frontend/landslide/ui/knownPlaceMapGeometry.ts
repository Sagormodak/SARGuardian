export type MapLatLng = { lat: number; lng: number };
export type ProjectedPoint = [number, number];

export type KnownPlaceMapPreview = {
  width: number;
  height: number;
  epsg: number;
  values: Array<Array<number | null>>;
  east_values_m: Array<Array<number | null>>;
  north_values_m: Array<Array<number | null>>;
  min_x_m: number;
  max_y_m: number;
  pixel_size_x_m: number;
  pixel_size_y_m: number;
  stride_cells: number;
  aoi_ring_xy: ProjectedPoint[];
  reference_ring_xy?: ProjectedPoint[] | null;
};

export type KnownPlaceVectorSample = {
  row: number;
  col: number;
  position: MapLatLng;
  east_m: number;
  north_m: number;
  displacement_m: number;
  rate_m_per_day: number;
  azimuth_deg: number;
  flagged: boolean;
};

const WGS84_A = 6378137;
const WGS84_E2 = 0.0066943799901413165;
const UTM_K0 = 0.9996;
const RAD = Math.PI / 180;
const DEG = 180 / Math.PI;

/** Convert a WGS84 UTM (north or south) coordinate to geographic latitude/longitude. */
export function utmToLatLng(epsg: number, easting: number, northing: number): MapLatLng | null {
  if (!Number.isFinite(easting) || !Number.isFinite(northing)) return null;
  const isNorth = epsg >= 32601 && epsg <= 32660;
  const isSouth = epsg >= 32701 && epsg <= 32760;
  if (!isNorth && !isSouth) return null;

  const zone = isNorth ? epsg - 32600 : epsg - 32700;
  const e1sq = WGS84_E2 / (1 - WGS84_E2);
  const x = easting - 500000;
  const y = isNorth ? northing : northing - 10000000;
  const m = y / UTM_K0;
  const mu = m / (WGS84_A * (
    1 - WGS84_E2 / 4 - 3 * WGS84_E2 ** 2 / 64 - 5 * WGS84_E2 ** 3 / 256
  ));
  const e1 = (1 - Math.sqrt(1 - WGS84_E2)) / (1 + Math.sqrt(1 - WGS84_E2));
  const j1 = 3 * e1 / 2 - 27 * e1 ** 3 / 32;
  const j2 = 21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32;
  const j3 = 151 * e1 ** 3 / 96;
  const j4 = 1097 * e1 ** 4 / 512;
  const phi1 = mu
    + j1 * Math.sin(2 * mu)
    + j2 * Math.sin(4 * mu)
    + j3 * Math.sin(6 * mu)
    + j4 * Math.sin(8 * mu);
  const sinPhi1 = Math.sin(phi1);
  const cosPhi1 = Math.cos(phi1);
  const tanPhi1 = Math.tan(phi1);
  const n1 = WGS84_A / Math.sqrt(1 - WGS84_E2 * sinPhi1 ** 2);
  const t1 = tanPhi1 ** 2;
  const c1 = e1sq * cosPhi1 ** 2;
  const r1 = WGS84_A * (1 - WGS84_E2) / (1 - WGS84_E2 * sinPhi1 ** 2) ** 1.5;
  const d = x / (n1 * UTM_K0);
  const latitude = phi1 - (n1 * tanPhi1 / r1) * (
    d ** 2 / 2
    - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * e1sq) * d ** 4 / 24
    + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * e1sq - 3 * c1 ** 2) * d ** 6 / 720
  );
  const longitudeOrigin = ((zone - 1) * 6 - 180 + 3) * RAD;
  const longitude = longitudeOrigin + (
    d
    - (1 + 2 * t1 + c1) * d ** 3 / 6
    + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * e1sq + 24 * t1 ** 2) * d ** 5 / 120
  ) / cosPhi1;
  const result = { lat: latitude * DEG, lng: longitude * DEG };
  return Number.isFinite(result.lat) && Number.isFinite(result.lng) ? result : null;
}

export function pointInProjectedRing(point: ProjectedPoint, ring: ProjectedPoint[]): boolean {
  if (ring.length < 4) return false;
  const x = point[0];
  const y = point[1];
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const crosses = (yi > y) !== (yj > y)
      && x < ((xj - xi) * (y - yi)) / ((yj - yi) || Number.EPSILON) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
}

export function previewCellCorners(
  preview: KnownPlaceMapPreview,
  row: number,
  col: number,
): MapLatLng[] | null {
  const halfX = preview.pixel_size_x_m / 2;
  const halfY = preview.pixel_size_y_m / 2;
  const centerX = preview.min_x_m + col * preview.pixel_size_x_m;
  const centerY = preview.max_y_m - row * preview.pixel_size_y_m;
  const projected: ProjectedPoint[] = [
    [centerX - halfX, centerY + halfY],
    [centerX + halfX, centerY + halfY],
    [centerX + halfX, centerY - halfY],
    [centerX - halfX, centerY - halfY],
  ];
  const corners = projected.map(([x, y]) => utmToLatLng(preview.epsg, x, y));
  return corners.every((point): point is MapLatLng => point !== null) ? corners : null;
}

export function projectedRingToLatLng(preview: KnownPlaceMapPreview, ring: ProjectedPoint[]): MapLatLng[] {
  return ring.map(([x, y]) => utmToLatLng(preview.epsg, x, y))
    .filter((point): point is MapLatLng => point !== null);
}

function spreadSamples(
  samples: KnownPlaceVectorSample[],
  maximum: number,
): KnownPlaceVectorSample[] {
  if (samples.length <= maximum) return samples;
  const selected: KnownPlaceVectorSample[] = [
    samples.reduce((best, item) => item.displacement_m > best.displacement_m ? item : best),
  ];
  const available = new Set(samples.filter((item) => item !== selected[0]));
  while (selected.length < maximum && available.size > 0) {
    let next: KnownPlaceVectorSample | null = null;
    let bestDistance = -1;
    for (const item of available) {
      const nearest = Math.min(...selected.map((chosen) =>
        ((item.row - chosen.row) * (item.row - chosen.row))
        + ((item.col - chosen.col) * (item.col - chosen.col))
      ));
      if (nearest > bestDistance) {
        bestDistance = nearest;
        next = item;
      }
    }
    if (!next) break;
    selected.push(next);
    available.delete(next);
  }
  return selected;
}

/** Build representative, AOI-masked vector labels from the scientific preview grid. */
export function buildKnownPlaceVectorSamples(
  pair: {
    interval_days: number | null;
    high_magnitude_threshold_m: number | null;
    map_preview: KnownPlaceMapPreview | null;
  },
  maximum = 9,
): KnownPlaceVectorSample[] {
  const preview = pair.map_preview;
  const days = pair.interval_days;
  if (!preview || !Number.isFinite(days) || (days ?? 0) <= 0 || maximum < 1) return [];
  const samples: KnownPlaceVectorSample[] = [];
  for (let row = 0; row < preview.height; row += 1) {
    for (let col = 0; col < preview.width; col += 1) {
      const displacement = preview.values[row]?.[col];
      const east = preview.east_values_m[row]?.[col];
      const north = preview.north_values_m[row]?.[col];
      if (
        typeof displacement !== 'number' || !Number.isFinite(displacement)
        || typeof east !== 'number' || !Number.isFinite(east)
        || typeof north !== 'number' || !Number.isFinite(north)
        || !pointInProjectedRing(
          [preview.min_x_m + col * preview.pixel_size_x_m, preview.max_y_m - row * preview.pixel_size_y_m],
          preview.aoi_ring_xy,
        )
      ) continue;
      const vectorMagnitude = Math.hypot(east, north);
      if (vectorMagnitude < 0.001) continue;
      const position = utmToLatLng(
        preview.epsg,
        preview.min_x_m + col * preview.pixel_size_x_m,
        preview.max_y_m - row * preview.pixel_size_y_m,
      );
      if (!position) continue;
      const azimuth = (Math.atan2(east, north) * DEG + 360) % 360;
      samples.push({
        row,
        col,
        position,
        east_m: east,
        north_m: north,
        displacement_m: displacement,
        rate_m_per_day: displacement / (days as number),
        azimuth_deg: azimuth,
        flagged: pair.high_magnitude_threshold_m !== null
          && pair.high_magnitude_threshold_m !== undefined
          && displacement > pair.high_magnitude_threshold_m,
      });
    }
  }
  return spreadSamples(samples, maximum);
}
