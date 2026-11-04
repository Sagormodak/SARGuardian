export type RiverShiftReport = {
  schema_version: number;
  engine: string;
  analysis_type: string;
  source: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  reference?: Record<string, unknown>;
  method?: Record<string, unknown>;
  confusion_matrix?: Record<string, unknown>;
  uncertainty?: Record<string, unknown>;
  metrics: Record<string, number | null>;
  quality: {
    status: string;
    warnings?: string[];
    [key: string]: unknown;
  };
  outputs?: Record<string, unknown>;
  time_series?: RiverShiftTimeSeriesFrame[];
};

export type RiverShiftGeoJSON = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    properties?: Record<string, unknown>;
    geometry: {
      type: string;
      coordinates: unknown;
    };
  }>;
};

export type RiverShiftTimeSeriesFrame = {
  date: string;
  granule_name?: string | null;
  water_area_km2: number;
  valid_pixel_fraction: number;
  water_geojson: string;
  water_geojson_sha256: string;
};

export function isRiverShiftReportVerified(report: RiverShiftReport): boolean {
  const quality = report.quality as Record<string, unknown>;
  const verification = quality.verification;
  if (!verification || typeof verification !== 'object') return false;
  const record = verification as Record<string, unknown>;
  return quality.release_status === 'VERIFIED'
    && quality.provenance_complete === true
    && typeof record.reviewer_id === 'string' && record.reviewer_id.trim().length > 0
    && typeof record.reviewed_at_utc === 'string' && Number.isFinite(Date.parse(record.reviewed_at_utc))
    && typeof record.evidence_reference === 'string' && record.evidence_reference.trim().length > 0
    && typeof record.verification_record_sha256 === 'string'
    && /^[0-9a-f]{64}$/i.test(record.verification_record_sha256);
}

export function isRiverShiftGeoJSONApproved(report: RiverShiftReport, sha256: string): boolean {
  if (!isRiverShiftReportVerified(report) || !/^[0-9a-f]{64}$/i.test(sha256)) return false;
  const approvedDigests = Object.entries(report.outputs || {})
    .filter(([key, value]) => key.endsWith('_geojson_sha256') && typeof value === 'string')
    .map(([, value]) => String(value).toLowerCase());
  return approvedDigests.includes(sha256.toLowerCase());
}

export function isRiverShiftTimeSeriesGeoJSONApproved(
  report: RiverShiftReport,
  date: string,
  sha256: string,
): boolean {
  if (!isRiverShiftReportVerified(report) || !/^[0-9a-f]{64}$/i.test(sha256)) return false;
  return (report.time_series || []).some((frame) => frame.date === date
    && frame.water_geojson_sha256.toLowerCase() === sha256.toLowerCase());
}

export type RiverShiftCandidateVisibility = {
  erosion: boolean;
  deposition: boolean;
  newWater: boolean;
  observedWater: boolean;
};

export type RiverShiftCandidateCounts = {
  erosion: number;
  deposition: number;
  newWater: number;
  observedWater: number;
  unclassified: number;
};

function riverShiftCandidateType(properties?: Record<string, unknown>): keyof RiverShiftCandidateVisibility | null {
  if (!properties) return null;
  const labels = [
    properties.river_shift_layer,
    properties.class,
    properties.change_type,
    properties.candidate_type,
  ].filter((value): value is string => typeof value === 'string');
  const label = labels.map((value) => value.toLowerCase().replace(/[\s-]+/g, '_')).join('_');
  if (label.includes('erosion')) return 'erosion';
  if (label.includes('deposition') || label.includes('accretion')) return 'deposition';
  if (label.includes('new_water') || label.includes('newly_water') || label.includes('water_covered')) return 'newWater';
  return null;
}

function isObservedOpenWaterFeature(properties?: Record<string, unknown>): boolean {
  if (!properties) return false;
  const labels = [
    properties.river_shift_layer,
    properties.class,
    properties.change_type,
    properties.candidate_type,
  ].filter((value): value is string => typeof value === 'string');
  const label = labels.map((value) => value.toLowerCase().replace(/[\\s-]+/g, '_')).join('_');
  return label.includes('open_water') && !label.includes('new');
}

/** Count candidate classes, observed open-water context, and unknown features separately. */
export function countRiverShiftCandidateLayers(data: RiverShiftGeoJSON): RiverShiftCandidateCounts {
  const counts: RiverShiftCandidateCounts = {
    erosion: 0, deposition: 0, newWater: 0, observedWater: 0, unclassified: 0,
  };
  for (const feature of data.features) {
    const type = riverShiftCandidateType(feature.properties);
    if (type) counts[type] += 1;
    else if (isObservedOpenWaterFeature(feature.properties)) counts.observedWater += 1;
    else counts.unclassified += 1;
  }
  return counts;
}

/** Filter each implemented candidate and observed-water context layer independently. */
export function filterRiverShiftCandidateGeoJSON(
  data: RiverShiftGeoJSON,
  visibility: RiverShiftCandidateVisibility,
): RiverShiftGeoJSON {
  return {
    ...data,
    features: data.features.filter((feature) => {
      const type = riverShiftCandidateType(feature.properties);
      if (type) return visibility[type];
      if (isObservedOpenWaterFeature(feature.properties)) return visibility.observedWater;
      // Preserve genuinely unclassified/context features; never let them masquerade as a
      // candidate class or as observed open water.
      return true;
    }),
  };
}

export function parseRiverShiftReport(value: unknown): RiverShiftReport {
  if (!value || typeof value !== 'object') {
    throw new Error('Result JSON must be an object.');
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.schema_version !== 1 || candidate.engine !== 'RiverShift') {
    throw new Error('Unsupported result. Expected schema_version 1 and engine RiverShift.');
  }
  const validTypes = [
    'flood_inundation_screening',
    'river_change_scan',
    'river_morphology_screening',
    'classification_validation',
    'bankline_migration',
    'water_timeseries_screening',
  ];
  if (typeof candidate.analysis_type !== 'string' || !validTypes.includes(candidate.analysis_type)) {
    throw new Error('Unsupported RiverShift analysis type.');
  }
  if (!candidate.source || typeof candidate.source !== 'object') {
    throw new Error('Result is missing its satellite source provenance.');
  }
  if (!candidate.metrics || typeof candidate.metrics !== 'object') {
    throw new Error('Result is missing its metrics object.');
  }
  if (!candidate.quality || typeof candidate.quality !== 'object') {
    throw new Error('Result is missing its quality status.');
  }
  const quality = candidate.quality as Record<string, unknown>;
  if (typeof quality.status !== 'string' || !quality.status.trim()) {
    throw new Error('Result quality.status is required.');
  }
  const timeSeries = candidate.time_series;
  if (timeSeries !== undefined && !Array.isArray(timeSeries)) {
    throw new Error('Result time_series must be an array.');
  }
  const parsedTimeSeries = (timeSeries || []).map((raw, index) => {
    if (!raw || typeof raw !== 'object') throw new Error(`Time-series frame ${index + 1} is invalid.`);
    const frame = raw as Record<string, unknown>;
    const parsedDate = typeof frame.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(frame.date)
      ? new Date(`${frame.date}T00:00:00Z`)
      : null;
    if (typeof frame.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(frame.date)
      || !parsedDate || !Number.isFinite(parsedDate.getTime()) || parsedDate.toISOString().slice(0, 10) !== frame.date
      || typeof frame.water_geojson !== 'string' || !frame.water_geojson.trim()
      || typeof frame.water_geojson_sha256 !== 'string' || !/^[0-9a-f]{64}$/i.test(frame.water_geojson_sha256)
      || typeof frame.water_area_km2 !== 'number' || !Number.isFinite(frame.water_area_km2)
      || typeof frame.valid_pixel_fraction !== 'number' || !Number.isFinite(frame.valid_pixel_fraction)
      || frame.valid_pixel_fraction < 0 || frame.valid_pixel_fraction > 1) {
      throw new Error(`Time-series frame ${index + 1} has invalid date, metrics, or output checksum.`);
    }
    return frame as unknown as RiverShiftTimeSeriesFrame;
  });
  for (let index = 1; index < parsedTimeSeries.length; index += 1) {
    if (parsedTimeSeries[index - 1].date >= parsedTimeSeries[index].date) {
      throw new Error('Time-series dates must be strictly increasing.');
    }
  }
  if (candidate.analysis_type === 'water_timeseries_screening' && parsedTimeSeries.length < 2) {
    throw new Error('Water time-series reports must contain at least two observed acquisition dates.');
  }
  const metrics: Record<string, number | null> = {};
  for (const [key, raw] of Object.entries(candidate.metrics as Record<string, unknown>)) {
    if (raw === null) metrics[key] = null;
    else if (typeof raw === 'number' && Number.isFinite(raw)) metrics[key] = raw;
    else throw new Error('Metric ' + key + ' is not finite or null.');
  }

  return {
    schema_version: 1,
    engine: 'RiverShift',
    analysis_type: candidate.analysis_type,
    source: candidate.source as Record<string, unknown>,
    inputs: candidate.inputs as Record<string, unknown> | undefined,
    reference: candidate.reference as Record<string, unknown> | undefined,
    method: candidate.method as Record<string, unknown> | undefined,
    confusion_matrix: candidate.confusion_matrix as Record<string, unknown> | undefined,
    uncertainty: candidate.uncertainty as Record<string, unknown> | undefined,
    metrics,
    quality: quality as RiverShiftReport['quality'],
    outputs: candidate.outputs as Record<string, unknown> | undefined,
    time_series: parsedTimeSeries,
  };
}

export function parseRiverShiftGeoJSON(value: unknown): RiverShiftGeoJSON {
  if (!value || typeof value !== 'object') throw new Error('GeoJSON must be an object.');
  const candidate = value as Record<string, unknown>;
  if (candidate.type !== 'FeatureCollection' || !Array.isArray(candidate.features)) {
    throw new Error('Expected a GeoJSON FeatureCollection.');
  }
  for (const feature of candidate.features) {
    if (!feature || typeof feature !== 'object') throw new Error('Invalid GeoJSON feature.');
    const item = feature as Record<string, unknown>;
    if (item.type !== 'Feature' || !item.geometry || typeof item.geometry !== 'object') {
      throw new Error('Every GeoJSON item must have a geometry and Feature type.');
    }
  }
  return candidate as RiverShiftGeoJSON;
}
