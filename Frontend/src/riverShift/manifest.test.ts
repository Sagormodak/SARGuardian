import { describe, expect, it } from 'vitest';
import { isRiverShiftGeoJSONApproved, isRiverShiftReportVerified, isRiverShiftTimeSeriesGeoJSONApproved, parseRiverShiftReport } from './manifest';

describe('RiverShift result manifest', () => {
  it('accepts a signed bankline migration result with provenance and QA status', () => {
    const result = parseRiverShiftReport({
      schema_version: 1,
      engine: 'RiverShift',
      analysis_type: 'bankline_migration',
      source: { mission: 'NISAR', product: 'GCOV', maturity: 'PROVISIONAL' },
      inputs: { positive_direction_label: 'toward_channel' },
      method: { measurement: 'signed_chainage_difference_along_user_supplied_transects' },
      metrics: {
        mean_signed_displacement_m: 12.5,
        mean_net_rate_m_per_year: 49.7,
        valid_transect_count: 4,
        invalid_transect_count: 1
      },
      quality: {
        status: 'TRANSECT_MEASURED_REQUIRES_BANKLINE_VALIDATION',
        warnings: ['Digitised banklines require independent review.']
      }
    });
    expect(result.analysis_type).toBe('bankline_migration');
    expect(result.metrics.mean_signed_displacement_m).toBe(12.5);
    expect(result.inputs?.positive_direction_label).toBe('toward_channel');
    expect(isRiverShiftReportVerified(result)).toBe(false);
  });

  it('accepts a provisional general river change scan without event attribution', () => {
    const result = parseRiverShiftReport({
      schema_version: 1,
      engine: 'RiverShift',
      analysis_type: 'river_change_scan',
      analysis_mode: 'general_scan',
      source: { mission: 'NISAR', product: 'GCOV', maturity: 'PROVISIONAL' },
      inputs: { comparison_basis: 'date-window comparison; no event date supplied or inferred' },
      method: { comparison_semantics: 'observed-date water coverage comparison; not an event attribution' },
      metrics: {
        baseline_water_area_km2: 10,
        comparison_one_water_area_km2: 12,
        comparison_two_water_area_km2: 11,
        newly_water_covered_area_km2: 2
      },
      quality: {
        status: 'SCREENING_NOT_INDEPENDENTLY_VALIDATED',
        release_status: 'PROVISIONAL',
        warnings: ['No event date was supplied or inferred.']
      }
    });
    expect(result.analysis_type).toBe('river_change_scan');
    expect(result.metrics.comparison_one_water_area_km2).toBe(12);
    expect(isRiverShiftReportVerified(result)).toBe(false);
  });

  it('requires review evidence and complete provenance before a result can be displayed', () => {
    const result = parseRiverShiftReport({
      schema_version: 1,
      engine: 'RiverShift',
      analysis_type: 'flood_inundation_screening',
      source: { mission: 'NISAR', product: 'GCOV' },
      outputs: { new_water_geojson_sha256: 'b'.repeat(64) },
      metrics: { newly_water_covered_area_km2: 4.2 },
      quality: {
        status: 'REVIEWED', release_status: 'VERIFIED', provenance_complete: true,
        verification: {
          reviewer_id: 'science-reviewer', reviewed_at_utc: '2026-11-02T00:00:00Z',
          evidence_reference: 'review/record-1.json', verification_record_sha256: 'a'.repeat(64)
        }
      }
    });
    expect(isRiverShiftReportVerified(result)).toBe(true);
    expect(isRiverShiftGeoJSONApproved(result, 'b'.repeat(64))).toBe(true);
    expect(isRiverShiftGeoJSONApproved(result, 'c'.repeat(64))).toBe(false);
  });

  it('rejects a report with a non-finite metric', () => {
    expect(() => parseRiverShiftReport({
      schema_version: 1,
      engine: 'RiverShift',
      analysis_type: 'bankline_migration',
      source: { mission: 'NISAR' },
      metrics: { mean_signed_displacement_m: Number.NaN },
      quality: { status: 'INVALID' }
    })).toThrow('not finite or null');
  });

  it('gates discrete water-time-series frames by verification, exact date, and checksum', () => {
    const result = parseRiverShiftReport({
      schema_version: 1,
      engine: 'RiverShift',
      analysis_type: 'water_timeseries_screening',
      source: { mission: 'NISAR', product: 'GCOV' },
      metrics: { observation_count: 2, maximum_observed_water_area_km2: 3.5 },
      quality: {
        status: 'REVIEWED', release_status: 'VERIFIED', provenance_complete: true,
        verification: {
          reviewer_id: 'reviewer', reviewed_at_utc: '2026-11-02T00:00:00Z',
          evidence_reference: 'review/record.json', verification_record_sha256: 'a'.repeat(64)
        }
      },
      time_series: [
        { date: '2026-06-18', water_area_km2: 2, valid_pixel_fraction: 0.98, water_geojson: 'water_2026-06-18.geojson', water_geojson_sha256: 'b'.repeat(64) },
        { date: '2026-06-30', water_area_km2: 3.5, valid_pixel_fraction: 0.96, water_geojson: 'water_2026-06-30.geojson', water_geojson_sha256: 'c'.repeat(64) }
      ]
    });
    expect(result.time_series).toHaveLength(2);
    expect(isRiverShiftTimeSeriesGeoJSONApproved(result, '2026-06-18', 'b'.repeat(64))).toBe(true);
    expect(isRiverShiftTimeSeriesGeoJSONApproved(result, '2026-06-18', 'c'.repeat(64))).toBe(false);
    expect(isRiverShiftTimeSeriesGeoJSONApproved(result, '2026-06-30', 'c'.repeat(64))).toBe(true);
  });

  it('rejects unordered or underspecified observation playback', () => {
    const base = {
      schema_version: 1, engine: 'RiverShift', analysis_type: 'water_timeseries_screening',
      source: { mission: 'NISAR' }, metrics: {}, quality: { status: 'PROVISIONAL' },
    };
    expect(() => parseRiverShiftReport({ ...base, time_series: [] })).toThrow('at least two');
    const frame = (date: string) => ({ date, water_area_km2: 1, valid_pixel_fraction: 1, water_geojson: `${date}.geojson`, water_geojson_sha256: 'd'.repeat(64) });
    expect(() => parseRiverShiftReport({ ...base, time_series: [frame('2026-06-30'), frame('2026-06-18')] })).toThrow('strictly increasing');
    expect(() => parseRiverShiftReport({ ...base, time_series: [frame('2026-06-30'), frame('2026-02-30')] })).toThrow('invalid date');
  });
});
