import { describe, expect, it } from 'vitest';
import { formatWktPolygon, parseWktPolygon } from './aoi';

describe('RiverShift AOI WKT', () => {
  it('closes a drawn polygon and preserves longitude-latitude order', () => {
    const wkt = formatWktPolygon([[89.62, 24.43], [89.78, 24.43], [89.78, 24.68]]);
    expect(wkt).toBe('POLYGON ((89.62 24.43, 89.78 24.43, 89.78 24.68, 89.62 24.43))');
    expect(parseWktPolygon(wkt)).toHaveLength(4);
  });

  it('rejects open rings, duplicate-only vertices, and out-of-range points', () => {
    expect(() => parseWktPolygon('POLYGON ((89 24, 90 24, 90 25))')).toThrow('closing coordinate');
    expect(() => formatWktPolygon([[89, 24], [89, 24], [89, 24]])).toThrow('3 distinct vertices');
    expect(() => formatWktPolygon([[181, 24], [90, 24], [90, 25]])).toThrow('outside WGS84');
  });

  it('rejects zero-area and self-crossing AOIs', () => {
    expect(() => formatWktPolygon([[89, 24], [90, 24], [91, 24]])).toThrow('zero area');
    expect(() => formatWktPolygon([[89, 24], [91, 26], [89, 26], [91, 24]])).toThrow('self-intersects');
  });
});
