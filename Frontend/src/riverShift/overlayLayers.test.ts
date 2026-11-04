import { describe, expect, it } from 'vitest';
import {
  countRiverShiftCandidateLayers,
  filterRiverShiftCandidateGeoJSON,
  type RiverShiftGeoJSON,
} from './manifest';

const data: RiverShiftGeoJSON = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { river_shift_layer: 'erosion' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { river_shift_layer: 'deposition' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { class: 'newly_water_covered' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { class: 'open_water_candidate' }, geometry: { type: 'Polygon', coordinates: [] } },
  ],
};

describe('RiverShift candidate overlay filters', () => {
  it('counts only the three implemented candidate classes', () => {
    expect(countRiverShiftCandidateLayers(data)).toEqual({
      erosion: 1,
      deposition: 1,
      newWater: 1,
      unclassified: 1,
    });
  });

  it('can show one candidate class without mutating the retained GeoJSON', () => {
    const filtered = filterRiverShiftCandidateGeoJSON(data, {
      erosion: false,
      deposition: false,
      newWater: true,
    });

    expect(filtered.features).toHaveLength(2);
    expect(filtered.features[0].properties?.class).toBe('newly_water_covered');
    expect(filtered.features[1].properties?.class).toBe('open_water_candidate');
    expect(data.features).toHaveLength(4);
  });

  it('keeps every available candidate class when all switches are enabled', () => {
    const filtered = filterRiverShiftCandidateGeoJSON(data, {
      erosion: true,
      deposition: true,
      newWater: true,
    });
    expect(filtered.features).toHaveLength(4);
  });
});
