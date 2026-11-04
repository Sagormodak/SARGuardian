import { describe, expect, it } from 'vitest';
import {
  countRiverShiftCandidateLayers,
  filterRiverShiftCandidateGeoJSON,
  getRiverShiftEventObservationNote,
  getRiverShiftOverlapAuditAvailability,
  type RiverShiftGeoJSON,
} from './manifest';

const data: RiverShiftGeoJSON = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', properties: { river_shift_layer: 'erosion' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { river_shift_layer: 'deposition' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { class: 'newly_water_covered' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { class: 'open_water_candidate' }, geometry: { type: 'Polygon', coordinates: [] } },
    { type: 'Feature', properties: { context_layer: 'aoi_boundary' }, geometry: { type: 'Polygon', coordinates: [] } },
  ],
};

describe('RiverShift candidate overlay filters', () => {
  it('counts candidate classes, observed water and unknown context separately', () => {
    expect(countRiverShiftCandidateLayers(data)).toEqual({
      erosion: 1,
      deposition: 1,
      newWater: 1,
      observedWater: 1,
      unclassified: 1,
    });
  });

  it('shows only the selected candidate class when observed water is off', () => {
    const filtered = filterRiverShiftCandidateGeoJSON(data, {
      erosion: false,
      deposition: false,
      newWater: true,
      observedWater: false,
    });

    expect(filtered.features.map((feature) => feature.properties?.class || feature.properties?.river_shift_layer || feature.properties?.context_layer))
      .toEqual(['newly_water_covered', 'aoi_boundary']);
    expect(data.features).toHaveLength(5);
  });

  it('shows observed-date open water only through its own visibility switch', () => {
    const hidden = filterRiverShiftCandidateGeoJSON(data, {
      erosion: false, deposition: false, newWater: false, observedWater: false,
    });
    const visible = filterRiverShiftCandidateGeoJSON(data, {
      erosion: false, deposition: false, newWater: false, observedWater: true,
    });

    expect(hidden.features.some((feature) => feature.properties?.class === 'open_water_candidate')).toBe(false);
    expect(visible.features.map((feature) => feature.properties?.class || feature.properties?.context_layer))
      .toEqual(['open_water_candidate', 'aoi_boundary']);
  });

  it('keeps every implemented candidate class when all class switches are enabled', () => {
    const filtered = filterRiverShiftCandidateGeoJSON(data, {
      erosion: true,
      deposition: true,
      newWater: true,
      observedWater: false,
    });
    expect(filtered.features.map((feature) => (
      feature.properties?.river_shift_layer
      || feature.properties?.class
      || feature.properties?.context_layer
    ))).toEqual(['erosion', 'deposition', 'newly_water_covered', 'aoi_boundary']);
  });
});

describe('RiverShift audit and event-timing disclosure', () => {
  it('distinguishes missing spatial diagnostics from zero overlap', () => {
    expect(getRiverShiftOverlapAuditAvailability({})).toEqual({
      sourceMask: false,
      previewGeometry: false,
    });
    expect(getRiverShiftOverlapAuditAvailability({
      candidate_overlap_audit: { pairwise: {} },
    })).toEqual({ sourceMask: true, previewGeometry: false });
  });

  it('recognizes both audit reports only when each has pairwise results', () => {
    expect(getRiverShiftOverlapAuditAvailability({
      candidate_overlap_audit: { pairwise: { erosion__deposition: {} } },
      preview_geometry_overlap: { pairwise: { erosion__deposition: {} } },
    })).toEqual({ sourceMask: true, previewGeometry: true });
  });

  it('reports the first actual post-event acquisition without calling it peak-stage data', () => {
    expect(getRiverShiftEventObservationNote({
      event_date: '2026-07-28',
      first_post_event_observation: '2026-08-17',
      offset_days: 20,
    })).toContain('20 days after the supplied event date');
    expect(getRiverShiftEventObservationNote({
      event_date: '2026-07-28',
      first_post_event_observation: '2026-08-17',
      offset_days: 20,
    })).toContain('not a measured event-peak');
  });

  it('rejects invalid or incomplete event timing metadata', () => {
    expect(getRiverShiftEventObservationNote(null)).toBeNull();
    expect(getRiverShiftEventObservationNote({
      event_date: '2026-07-28', first_post_event_observation: '2026-08-17', offset_days: 0,
    })).toBeNull();
  });
});
