import { describe, expect, it } from 'vitest';
import { deriveGeneralChangeMarkers } from './generalChangeMarkers';
import type { RiverShiftGeoJSON } from './manifest';

const square = (west: number, south: number, east: number, north: number) => [[
  [west, south], [east, south], [east, north], [west, north], [west, south],
]];

function collection(features: RiverShiftGeoJSON['features']): RiverShiftGeoJSON {
  return { type: 'FeatureCollection', features };
}

describe('General River Change Scan map markers', () => {
  it('creates representative markers from actual erosion, deposition and new-water footprints', () => {
    const result = deriveGeneralChangeMarkers(collection([
      {
        type: 'Feature',
        properties: { class: 'erosion', river_shift_layer: 'erosion' },
        geometry: { type: 'Polygon', coordinates: square(89.6, 24.4, 89.8, 24.6) },
      },
      {
        type: 'Feature',
        properties: { river_shift_layer: 'deposition' },
        geometry: { type: 'Polygon', coordinates: square(89.8, 24.4, 90, 24.6) },
      },
      {
        type: 'Feature',
        properties: { river_shift_layer: 'new_water' },
        geometry: { type: 'Polygon', coordinates: square(90, 24.4, 90.2, 24.6) },
      },
    ]));

    expect(result.map((marker) => marker.changeType)).toEqual(['erosion', 'deposition', 'new_water']);
    expect(result[0].longitude).toBeCloseTo(89.7, 5);
    expect(result[0].latitude).toBeCloseTo(24.5, 5);
  });

  it('creates one marker for each disconnected MultiPolygon component', () => {
    const result = deriveGeneralChangeMarkers(collection([{
      type: 'Feature',
      properties: { river_shift_layer: 'new_water' },
      geometry: {
        type: 'MultiPolygon',
        coordinates: [
          square(89.6, 24.4, 89.7, 24.5),
          square(89.8, 24.6, 89.9, 24.7),
        ],
      },
    }]));

    expect(result).toHaveLength(2);
    expect(result[0].longitude).toBeCloseTo(89.65, 5);
    expect(result[1].longitude).toBeCloseTo(89.85, 5);
  });

  it('does not mark per-acquisition open-water masks as detected change classes', () => {
    const result = deriveGeneralChangeMarkers(collection([{
      type: 'Feature',
      properties: { class: 'open_water_candidate' },
      geometry: { type: 'Polygon', coordinates: square(89.6, 24.4, 89.8, 24.6) },
    }]));

    expect(result).toEqual([]);
  });

  it('limits dense preview layers per class without dropping other candidate classes', () => {
    const erosionFeatures = Array.from({ length: 30 }, (_, index) => ({
      type: 'Feature' as const,
      properties: { river_shift_layer: 'erosion' },
      geometry: {
        type: 'Polygon',
        coordinates: square(89 + index * 0.01, 24, 89.005 + index * 0.01, 24.005),
      },
    }));
    erosionFeatures.push({
      type: 'Feature',
      properties: { river_shift_layer: 'deposition' },
      geometry: { type: 'Polygon', coordinates: square(90, 24, 90.1, 24.1) },
    });

    const result = deriveGeneralChangeMarkers(collection(erosionFeatures), 5);
    expect(result.filter((marker) => marker.changeType === 'erosion')).toHaveLength(5);
    expect(result.filter((marker) => marker.changeType === 'deposition')).toHaveLength(1);
  });
});
