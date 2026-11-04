import { describe, expect, it } from 'vitest';
import type { RiverShiftGeoJSON } from './manifest';
import { parseImpactExposureGeoJSON, summarizeImpactExposure } from './impactContext';

const candidateLayer = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { river_shift_layer: 'erosion_candidate' },
      geometry: {
        type: 'Polygon',
        coordinates: [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
      },
    },
    {
      type: 'Feature',
      properties: { river_shift_layer: 'deposition_candidate' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [[2, 2], [6, 2], [6, 6], [2, 6], [2, 2]],
          [[3, 3], [5, 3], [5, 5], [3, 5], [3, 3]],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { river_shift_layer: 'new_water_candidate', preview_sparse_marker: true },
      geometry: { type: 'MultiPoint', coordinates: [[1, 1], [8, 8]] },
    },
  ],
} as unknown as RiverShiftGeoJSON;

describe('RiverShift impact-context point screening', () => {
  it('counts representative points per candidate class and once in the union', () => {
    const exposure = parseImpactExposureGeoJSON({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: { population: 100 }, geometry: { type: 'Point', coordinates: [1, 1] } },
        { type: 'Feature', properties: { population: 50 }, geometry: { type: 'Point', coordinates: [5, 5] } },
        { type: 'Feature', properties: { population: 25 }, geometry: { type: 'Point', coordinates: [3, 2] } },
        { type: 'Feature', properties: { population: 10 }, geometry: { type: 'Point', coordinates: [7, 7] } },
      ],
    });

    const summary = summarizeImpactExposure([candidateLayer], exposure, 'population');

    expect(summary.exposureFeatureCount).toBe(4);
    expect(summary.uniqueFeaturesInsideAnyCandidate).toBe(2);
    expect(summary.populationValueSum).toBe(125);
    expect(summary.byClass.erosion.featureCount).toBe(2);
    expect(summary.byClass.erosion.populationValueSum).toBe(125);
    expect(summary.byClass.deposition.featureCount).toBe(1);
    expect(summary.byClass.deposition.populationValueSum).toBe(25);
    expect(summary.featuresMatchingMultipleClasses).toBe(1);
    expect(summary.sparseMarkerFeaturesExcluded).toBe(1);
  });

  it('excludes polygon holes and includes points on the outer boundary', () => {
    const exposure = parseImpactExposureGeoJSON({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [4, 4] } },
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [3, 4] } },
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [0, 2] } },
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [2, 4] } },
      ],
    });
    const summary = summarizeImpactExposure([candidateLayer], exposure);

    expect(summary.byClass.deposition.featureCount).toBe(1);
    expect(summary.byClass.erosion.featureCount).toBe(4);
  });

  it('accepts MultiPoint exposure features as one feature and does not double-count it', () => {
    const exposure = parseImpactExposureGeoJSON({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: { population: 12 }, geometry: { type: 'MultiPoint', coordinates: [[1, 1], [2, 2]] } },
      ],
    });
    const summary = summarizeImpactExposure([candidateLayer], exposure, 'population');
    expect(summary.uniqueFeaturesInsideAnyCandidate).toBe(1);
    expect(summary.byClass.erosion.featureCount).toBe(1);
    expect(summary.populationValueSum).toBe(12);
  });

  it('requires point or centroid GeoJSON and rejects invalid coordinates', () => {
    expect(() => parseImpactExposureGeoJSON({ type: 'FeatureCollection', features: [] }))
      .toThrow('contains no features');
    expect(() => parseImpactExposureGeoJSON({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] } }],
    })).toThrow('Point or MultiPoint');
    expect(() => parseImpactExposureGeoJSON({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [190, 1] } }],
    })).toThrow('WGS84');
  });

  it('does not turn an empty candidate layer into zero impact evidence', () => {
    const exposure = parseImpactExposureGeoJSON({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: { population: 4 }, geometry: { type: 'Point', coordinates: [1, 1] } }],
    });
    const summary = summarizeImpactExposure([], exposure, 'population');
    expect(summary.uniqueFeaturesInsideAnyCandidate).toBe(0);
    expect(summary.populationValueSum).toBeNull();
    expect(summary.candidatePolygonCount).toBe(0);
  });
});
