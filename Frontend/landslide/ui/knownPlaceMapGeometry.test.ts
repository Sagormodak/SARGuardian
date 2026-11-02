import { describe, expect, it } from 'vitest';
import {
  buildKnownPlaceVectorSamples,
  pointInProjectedRing,
  utmToLatLng,
  type KnownPlaceMapPreview,
} from './knownPlaceMapGeometry';

describe('Known Place map geometry', () => {
  it('converts UTM zone 45N coordinates to WGS84 for the measured Nepal site', () => {
    const result = utmToLatLng(32645, 354600, 3131080);
    expect(result?.lat).toBeCloseTo(28.2977642, 6);
    expect(result?.lng).toBeCloseTo(85.5171889, 6);
  });

  it('supports southern UTM zones and rejects unknown projections', () => {
    const south = utmToLatLng(32756, 500000, 10000000);
    expect(south?.lat).toBeCloseTo(0, 7);
    expect(south?.lng).toBeCloseTo(153, 6);
    expect(utmToLatLng(4326, 85, 28)).toBeNull();
  });

  it('masks raster/vector samples to the Measurement Polygon, not the reference polygon', () => {
    const ring: Array<[number, number]> = [
      [500000, 3100000], [500160, 3100000], [500160, 3100160],
      [500000, 3100160], [500000, 3100000],
    ];
    const preview: KnownPlaceMapPreview = {
      width: 3,
      height: 3,
      epsg: 32645,
      min_x_m: 500040,
      max_y_m: 3100120,
      pixel_size_x_m: 80,
      pixel_size_y_m: 80,
      stride_cells: 1,
      values: [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
      east_values_m: [[1, 1, 1], [1, 1, 1], [1, 1, 1]],
      north_values_m: [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
      aoi_ring_xy: ring,
      reference_ring_xy: null,
    };
    const samples = buildKnownPlaceVectorSamples({
      interval_days: 10,
      high_magnitude_threshold_m: 6,
      map_preview: preview,
    }, 20);
    expect(samples).toHaveLength(4);
    expect(samples.every((sample) => sample.displacement_m <= 5)).toBe(true);
    expect(samples[0].rate_m_per_day).toBe(0.5);
    expect(samples[0].azimuth_deg).toBeCloseTo(90, 6);
  });

  it('limits annotation density while retaining the strongest spatially distributed cells', () => {
    const ring: Array<[number, number]> = [
      [499960, 3099240], [500760, 3099240], [500760, 3100040],
      [499960, 3100040], [499960, 3099240],
    ];
    const matrix = Array.from({ length: 10 }, (_row, row) =>
      Array.from({ length: 10 }, (_col, col) => row + col + 1));
    const preview: KnownPlaceMapPreview = {
      width: 10,
      height: 10,
      epsg: 32645,
      min_x_m: 500000,
      max_y_m: 3100000,
      pixel_size_x_m: 80,
      pixel_size_y_m: 80,
      stride_cells: 1,
      values: matrix,
      east_values_m: matrix.map((row) => row.map(() => 1)),
      north_values_m: matrix.map((row) => row.map(() => 1)),
      aoi_ring_xy: ring,
    };
    const samples = buildKnownPlaceVectorSamples({
      interval_days: 12,
      high_magnitude_threshold_m: 10,
      map_preview: preview,
    }, 9);
    expect(samples).toHaveLength(9);
    expect(samples[0].displacement_m).toBe(19);
    expect(samples.some((sample) => sample.flagged)).toBe(true);
  });

  it('treats interior and exterior points consistently', () => {
    const ring: Array<[number, number]> = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]];
    expect(pointInProjectedRing([5, 5], ring)).toBe(true);
    expect(pointInProjectedRing([15, 5], ring)).toBe(false);
  });
});
