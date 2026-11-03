import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { User } from 'firebase/auth';
import { importLibrary, setOptions } from '@googlemaps/js-api-loader';
import { createRiverShiftJob, downloadRiverShiftArtifact, getRiverShiftJob, listRiverShiftJobs, type RiverShiftJob } from '../api/catalog';
import type { RiverShiftGeoJSON, RiverShiftReport, RiverShiftTimeSeriesFrame } from '../riverShift/manifest';
import { isRiverShiftGeoJSONApproved, isRiverShiftReportVerified, isRiverShiftTimeSeriesGeoJSONApproved, parseRiverShiftGeoJSON, parseRiverShiftReport } from '../riverShift/manifest';
import { formatWktPolygon, parseWktPolygon, type Wgs84Point } from '../riverShift/aoi';
import './river-shift.css';

type Props = {
  onHome: () => void;
  user: User | null;
  firebaseConfigured: boolean;
  authState: 'idle' | 'loading' | 'ready' | 'error';
  onSignIn: () => Promise<void>;
  onSignOut: () => Promise<void>;
};

type CatalogueProduct = {
  granule_name: string;
  product_type: 'GCOV';
  processing_type?: string | null;
  crid?: string | null;
  maturity: 'BETA' | 'PROVISIONAL' | 'UNKNOWN';
  download_url?: string | null;
  start_time_utc?: string | null;
  stop_time_utc?: string | null;
  flight_direction?: string | null;
  relative_orbit?: string | null;
  cycle?: string | null;
  frame?: string | null;
  bandwidth_mode?: string | null;
  polarization_code?: string | null;
  main_band_polarization?: string | null;
  frame_coverage?: string | null;
  size_mb?: number | null;
};

type CatalogueResponse = {
  mode: 'catalogue_only';
  status: 'ready' | 'no_data' | 'upstream_error';
  message: string;
  data_downloaded: false;
  scientific_analysis_performed: false;
  product_count: number;
  products: CatalogueProduct[];
  warnings: string[];
  query: Record<string, unknown>;
};

type LoadedGeoJSON = { fileName: string; sha256: string; data: RiverShiftGeoJSON };
type LoadedJobPreview = { jobId: string; changeLayer: LoadedGeoJSON | null; report: RiverShiftReport | null; error: string };
type LoadedJobFrame = { jobId: string; date: string; data: RiverShiftGeoJSON };

const API_BASE = ((import.meta.env.VITE_SARGUARDIAN_API_URL as string | undefined) || 'http://localhost:8000')
  .trim()
  .replace(/\/+$/, '');
const GOOGLE_MAPS_KEY = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined) || '';
let mapsConfigured = false;

function formatDate(value?: string | null): string {
  if (!value) return 'Not supplied';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().slice(0, 10);
}

function metricLabel(key: string): string {
  const names: Record<string, string> = {
    baseline_water_area_km2: 'Baseline water area',
    peak_water_area_km2: 'Peak water area',
    post_event_water_area_km2: 'Post-event water area',
    newly_water_covered_area_km2: 'New water coverage',
    water_area_change_percent: 'Water-area change',
    persistent_erosion_candidate_area_ha: 'Erosion candidates',
    persistent_deposition_candidate_area_ha: 'Deposition candidates',
    net_candidate_land_change_ha: 'Net candidate land change',
    symmetric_boundary_distance_mean_m: 'Mean boundary distance',
    symmetric_boundary_distance_p95_m: 'P95 boundary distance',
    accuracy: 'Accuracy',
    precision_user_accuracy: 'Precision',
    recall_producer_accuracy: 'Recall',
    f1_score: 'F1 score',
    intersection_over_union: 'Intersection over Union',
    cohen_kappa: 'Cohen’s kappa',
    area_bias_percent: 'Area bias',
    mean_signed_displacement_m: 'Mean signed bank displacement',
    median_signed_displacement_m: 'Median signed bank displacement',
    p95_absolute_displacement_m: 'P95 absolute displacement',
    mean_net_rate_m_per_year: 'Mean net movement rate',
    channelward_count: 'Channelward transects',
    landward_count: 'Landward transects',
    unchanged_count: 'Unchanged transects',
    valid_transect_count: 'Valid transects',
    invalid_transect_count: 'Invalid transects',
    transect_count: 'Total transects',
  };
  return names[key] || key.replace(/_/g, ' ');
}

function metricUnit(key: string): string {
  if (key.includes('km2')) return 'km²';
  if (key.includes('_ha')) return 'ha';
  if (key.endsWith('_m_per_year')) return 'm/year';
  if (key.endsWith('_m')) return 'm';
  if (key.includes('percent')) return '%';
  return '';
}

function metricText(key: string, value: number | null): string {
  if (value === null) return 'Unavailable';
  const digits = key.includes('percent') ? 1 : key.includes('area') || key.endsWith('_ha') || key.includes('km2') ? 3 : 3;
  return value.toFixed(digits);
}

function ReportPanel({ report }: { report: RiverShiftReport }) {
  const verified = isRiverShiftReportVerified(report);
  const verification = report.quality.verification;
  const verificationRecord = verification && typeof verification === 'object'
    ? verification as Record<string, unknown>
    : null;
  const warnings = report.quality.warnings || [];
  const title = report.analysis_type === 'flood_inundation_screening'
    ? 'Flood inundation screening'
    : report.analysis_type === 'river_morphology_screening'
      ? 'River morphology screening'
      : report.analysis_type === 'water_timeseries_screening'
        ? 'Observed-date water time series'
      : report.analysis_type === 'classification_validation'
        ? 'Classification validation'
        : 'Bankline migration measurement';
  const source = report.source;
  return (
    <section className="rs-panel">
      <div className="rs-section-heading">
        <div><p className="rs-kicker">RIVER SHIFT SCIENTIFIC RESULT</p><h2>{title}</h2></div>
        <span className="rs-quality">{report.quality.status.replace(/_/g, ' ')}</span>
      </div>
      <div className="rs-provenance">
        <span>Mission: <strong>{String(source.mission || 'Not stated')}</strong></span>
        <span>Product: <strong>{String(source.product || 'Not stated')}</strong></span>
        <span>Maturity: <strong>{String(source.maturity || 'Not stated')}</strong></span>
        <span>Frequency: <strong>{String(source.frequency || 'Not stated')}</strong></span>
        <span>Term: <strong>{String(source.covariance_term || 'Not stated')}</strong></span>
      </div>
      <div className="rs-warning-inline" role="status">
        Release status: <strong>{String(report.quality.release_status || 'PROVISIONAL')}</strong>
        {!verified && <span> · The metrics and map are provisional evidence, not independently validated findings.</span>}
      </div>
      <div className="rs-metric-grid">
        {Object.entries(report.metrics).map(([key, value]) => (
          <article className="rs-metric" key={key}>
            <span>{metricLabel(key)}</span>
            <strong>{metricText(key, value)} <small>{metricUnit(key)}</small></strong>
          </article>
        ))}
      </div>
      {verified && verificationRecord && (
        <div className="rs-reference">
          Review record: <strong>{String(verificationRecord.reviewer_id)}</strong>
          <span>{String(verificationRecord.reviewed_at_utc)}</span>
          <p>Evidence: {String(verificationRecord.evidence_reference)}</p>
        </div>
      )}
      <div className="rs-warning-list">
        <strong>Input provenance</strong>
        <p>Granules: {Array.isArray(source.granule_names) && source.granule_names.length ? source.granule_names.join(', ') : 'No NISAR granule IDs recorded'}</p>
        <p>Source checksums: {Array.isArray(source.source_granule_sha256) && source.source_granule_sha256.length ? source.source_granule_sha256.join(', ') : 'No source product checksums recorded'}</p>
        {report.inputs && <p>Input checksums: {JSON.stringify(report.inputs.input_sha256 || 'Not recorded')}</p>}
      </div>
      {report.reference && (
        <div className="rs-reference">
          Reference: <strong>{String(report.reference.source || 'Not stated')}</strong>
          <span>{String(report.reference.date || 'Date not stated')}</span>
          <p>{String(report.reference.method || 'Reference method not stated')}</p>
        </div>
      )}
      {report.uncertainty && (
        <details className="rs-reference">
          <summary>Uncertainty and sensitivity details</summary>
          <pre>{JSON.stringify(report.uncertainty, null, 2)}</pre>
        </details>
      )}
      {warnings.length > 0 && (
        <div className="rs-warning-list">
          <strong>Scientific interpretation and limitations</strong>
          {warnings.map((warning, index) => <p key={index}>• {warning}</p>)}
        </div>
      )}
    </section>
  );
}

export function RiverShiftPage({ onHome, user, firebaseConfigured, authState, onSignIn, onSignOut }: Props) {
  const [aoiWkt, setAoiWkt] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [maturity, setMaturity] = useState<'BETA' | 'PROVISIONAL' | 'ALL'>('PROVISIONAL');
  const [polarization, setPolarization] = useState('');
  const [direction, setDirection] = useState('');
  const [frameCoverage, setFrameCoverage] = useState<'ALL' | 'FULL' | 'PARTIAL'>('ALL');
  const [catalogue, setCatalogue] = useState<CatalogueResponse | null>(null);
  const [catalogueBusy, setCatalogueBusy] = useState(false);
  const [catalogueError, setCatalogueError] = useState('');
  const [report, setReport] = useState<RiverShiftReport | null>(null);
  const [reportError, setReportError] = useState('');
  const [geoJSONFiles, setGeoJSONFiles] = useState<LoadedGeoJSON[]>([]);
  const [geoJSONError, setGeoJSONError] = useState('');
  const [mapError, setMapError] = useState('');
  const [mapReady, setMapReady] = useState(false);
  const [drawingAoi, setDrawingAoi] = useState(false);
  const [aoiVertices, setAoiVertices] = useState<Wgs84Point[]>([]);
  const [aoiError, setAoiError] = useState('');
  const [timeSeriesIndex, setTimeSeriesIndex] = useState(0);
  const [timeSeriesPlaying, setTimeSeriesPlaying] = useState(false);
  const [eventDate, setEventDate] = useState('');
  const [scienceFrequency, setScienceFrequency] = useState<'frequencyA' | 'frequencyB'>('frequencyA');
  const [covarianceTerm, setCovarianceTerm] = useState('HHHH');
  const [thresholdMethod, setThresholdMethod] = useState<'otsu' | 'manual'>('otsu');
  const [thresholdDb, setThresholdDb] = useState('');
  const [riverJob, setRiverJob] = useState<RiverShiftJob | null>(null);
  const [riverJobBusy, setRiverJobBusy] = useState(false);
  const [riverJobError, setRiverJobError] = useState('');
  const [jobPreview, setJobPreview] = useState<LoadedJobPreview | null>(null);
  const [jobFrame, setJobFrame] = useState<LoadedJobFrame | null>(null);
  const [jobTimeSeriesIndex, setJobTimeSeriesIndex] = useState(0);
  const [jobTimeSeriesPlaying, setJobTimeSeriesPlaying] = useState(false);
  const aoiMapElement = useRef<HTMLDivElement>(null);
  const resultMapElement = useRef<HTMLDivElement>(null);
  const aoiMapInstance = useRef<google.maps.Map | null>(null);
  const resultMapInstance = useRef<google.maps.Map | null>(null);
  const aoiPolygon = useRef<google.maps.Polygon | null>(null);
  const aoiPreviewLine = useRef<google.maps.Polyline | null>(null);
  const timeSeriesFrames = useMemo(() => (report?.time_series || []).flatMap((frame) => {
    const loaded = geoJSONFiles.find((file) => file.fileName === frame.water_geojson
      && file.sha256.toLowerCase() === frame.water_geojson_sha256.toLowerCase());
    return loaded && isRiverShiftTimeSeriesGeoJSONApproved(report!, frame.date, loaded.sha256)
      ? [{ ...frame, data: loaded.data }]
      : [];
  }), [report, geoJSONFiles]);
  const playbackFrames = report?.analysis_type === 'water_timeseries_screening'
    && report.time_series?.length === timeSeriesFrames.length ? timeSeriesFrames : [];
  const currentTimeSeriesFrame = playbackFrames[timeSeriesIndex];
  const jobTimeSeriesFrames: RiverShiftTimeSeriesFrame[] = jobPreview && riverJob && jobPreview.jobId === riverJob.id
    && jobPreview.report?.analysis_type === 'water_timeseries_screening'
    ? jobPreview.report.time_series || [] : [];
  const currentJobFrameMetadata = jobTimeSeriesFrames[jobTimeSeriesIndex];
  const riverJobId = riverJob?.id;
  const riverJobArtifactManifest = riverJob?.artifact_manifest;
  const currentJobFrameDate = currentJobFrameMetadata?.date;
  const currentJobFrameGeoJSON = currentJobFrameMetadata?.water_geojson;
  const currentJobFrameSHA256 = currentJobFrameMetadata?.water_geojson_sha256;
  const jobFrameJobId = jobFrame?.jobId;
  const jobFrameDate = jobFrame?.date;
  const currentJobFrame = currentJobFrameMetadata && riverJobId && jobFrame && jobFrame.jobId === riverJobId
    && jobFrame.date === currentJobFrameMetadata.date ? jobFrame.data : null;
  const hasJobPreviewOverlay = Boolean(jobPreview && riverJobId && jobPreview.jobId === riverJobId
    && (jobPreview.changeLayer || currentJobFrame));
  const verifiedGeoJSONFiles = useMemo(() => {
    if (!report || report.analysis_type === 'water_timeseries_screening') return [];
    return geoJSONFiles.filter((file) => isRiverShiftGeoJSONApproved(report, file.sha256));
  }, [report, geoJSONFiles]);
  const hasVerifiedOverlay = Boolean(!hasJobPreviewOverlay && (currentTimeSeriesFrame || verifiedGeoJSONFiles.length));

  useEffect(() => {
    if (!user) {
      setRiverJob(null);
      return undefined;
    }
    let cancelled = false;
    void listRiverShiftJobs(user, 10).then((jobs) => {
      if (!cancelled && jobs.length) {
        setRiverJob((current) => current ?? jobs[0]);
      }
    }).catch((error: unknown) => {
      if (!cancelled) {
        setRiverJobError(error instanceof Error ? error.message : 'Could not restore the last River Shift job.');
      }
    });
    return () => { cancelled = true; };
  }, [user]);

  useEffect(() => {
    if (!user || !riverJob || !['queued', 'dispatching', 'running'].includes(riverJob.state)) return undefined;
    const timer = window.setInterval(() => {
      void getRiverShiftJob(riverJob.id, user).then(setRiverJob).catch((error: unknown) => {
        setRiverJobError(error instanceof Error ? error.message : 'Could not refresh processing status.');
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [riverJob, user]);

  useEffect(() => {
    if (!user || riverJob?.state !== 'succeeded' || !riverJob.artifact_manifest?.length) {
      setJobPreview(null);
      setJobFrame(null);
      setJobTimeSeriesIndex(0);
      setJobTimeSeriesPlaying(false);
      return undefined;
    }
    let cancelled = false;
    const loadPreview = async () => {
      const artifacts = riverJob.artifact_manifest || [];
      let changeLayer: LoadedGeoJSON | null = null;
      let timeseriesReport: RiverShiftReport | null = null;
      let failure = '';
      const changeIndex = artifacts.findIndex((item) => item.name === 'river_change_candidates_preview.geojson' && item.bytes <= 4_000_000);
      const reportIndex = artifacts.findIndex((item) => item.name === 'river_shift_timeseries_preview.json' && item.bytes <= 4_000_000);
      if (changeIndex >= 0) {
        try {
          const artifact = artifacts[changeIndex];
          const blob = await downloadRiverShiftArtifact(riverJob.id, changeIndex, user);
          const bytes = await blob.arrayBuffer();
          const digest = await crypto.subtle.digest('SHA-256', bytes);
          const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
          if (sha256.toLowerCase() !== artifact.sha256.toLowerCase()) throw new Error('Map preview checksum did not match its private result receipt.');
          changeLayer = {
            fileName: artifact.name,
            sha256,
            data: parseRiverShiftGeoJSON(JSON.parse(new TextDecoder().decode(bytes)) as unknown),
          };
        } catch (error) {
          failure = error instanceof Error ? error.message : 'Could not load the provisional map preview.';
        }
      }
      if (reportIndex >= 0) {
        try {
          const artifact = artifacts[reportIndex];
          const blob = await downloadRiverShiftArtifact(riverJob.id, reportIndex, user);
          const bytes = await blob.arrayBuffer();
          const digest = await crypto.subtle.digest('SHA-256', bytes);
          const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
          if (sha256.toLowerCase() !== artifact.sha256.toLowerCase()) throw new Error('Time-series report checksum did not match its private result receipt.');
          timeseriesReport = parseRiverShiftReport(JSON.parse(new TextDecoder().decode(bytes)) as unknown);
        } catch (error) {
          failure = failure || (error instanceof Error ? error.message : 'Could not load the observed-date time series.');
        }
      }
      if (!cancelled) {
        setJobPreview({ jobId: riverJob.id, changeLayer, report: timeseriesReport, error: failure });
        setJobTimeSeriesIndex(0);
      }
    };
    void loadPreview();
    return () => { cancelled = true; };
  }, [riverJob?.id, riverJob?.state, riverJob?.artifact_manifest, user]);

  useEffect(() => {
    if (!user || !riverJobId || !currentJobFrameDate || !currentJobFrameGeoJSON || !currentJobFrameSHA256
      || (jobFrameJobId === riverJobId && jobFrameDate === currentJobFrameDate)) return undefined;
    const artifacts = riverJobArtifactManifest || [];
    const artifactIndex = artifacts.findIndex((item) => item.name === currentJobFrameGeoJSON && item.bytes <= 4_000_000);
    if (artifactIndex < 0) return undefined;
    let cancelled = false;
    const loadFrame = async () => {
      try {
        const artifact = artifacts[artifactIndex];
        const blob = await downloadRiverShiftArtifact(riverJobId, artifactIndex, user);
        const bytes = await blob.arrayBuffer();
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
        if (sha256.toLowerCase() !== artifact.sha256.toLowerCase()
          || sha256.toLowerCase() !== currentJobFrameSHA256.toLowerCase()) {
          throw new Error('Observed-date preview checksum did not match the report and private result receipt.');
        }
        const data = parseRiverShiftGeoJSON(JSON.parse(new TextDecoder().decode(bytes)) as unknown);
        if (!cancelled) setJobFrame({ jobId: riverJobId, date: currentJobFrameDate, data });
      } catch (error) {
        if (!cancelled) setJobPreview((current) => current?.jobId === riverJobId
          ? { ...current, error: error instanceof Error ? error.message : 'Could not load this observed-date preview.' }
          : current);
      }
    };
    void loadFrame();
    return () => { cancelled = true; };
  }, [riverJobId, riverJobArtifactManifest, user, currentJobFrameDate, currentJobFrameGeoJSON, currentJobFrameSHA256, jobFrameJobId, jobFrameDate]);

  const startLiveProcessing = async () => {
    setRiverJobError('');
    if (!user) {
      setRiverJobError('Sign in with Google before starting live processing.');
      return;
    }
    if (!eventDate) {
      setRiverJobError('Add the event date from your independent event record before processing.');
      return;
    }
    if (maturity === 'ALL') {
      setRiverJobError('Choose one maturity. BETA and PROVISIONAL products cannot be mixed in a scientific time series.');
      return;
    }
    if (thresholdMethod === 'manual') {
      const manualThreshold = Number(thresholdDb);
      if (!thresholdDb.trim() || !Number.isFinite(manualThreshold) || manualThreshold < -60 || manualThreshold > 0) {
        setRiverJobError('Enter one manual threshold between -60 and 0 dB, or choose Otsu.');
        return;
      }
    }
    setRiverJobBusy(true);
    setJobPreview(null);
    setJobFrame(null);
    setJobTimeSeriesIndex(0);
    setJobTimeSeriesPlaying(false);
    try {
      const job = await createRiverShiftJob({
        aoiWkt, startDate, endDate, eventDate, maturity,
        frequency: scienceFrequency, covarianceTerm, thresholdMethod,
        ...(thresholdMethod === 'manual' ? { thresholdDb: Number(thresholdDb) } : {}),
        idempotencyKey: crypto.randomUUID().replace(/-/g, ''),
      }, user);
      setRiverJob(job);
    } catch (error) {
      setRiverJobError(error instanceof Error ? error.message : 'Could not start live RiverShift processing.');
    } finally {
      setRiverJobBusy(false);
    }
  };

  const saveRiverArtifact = async (artifactIndex: number, fileName: string) => {
    if (!riverJob || !user) return;
    setRiverJobError('');
    try {
      const blob = await downloadRiverShiftArtifact(riverJob.id, artifactIndex, user);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setRiverJobError(error instanceof Error ? error.message : 'Could not download this private result.');
    }
  };

  const searchCatalogue = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCatalogueError('');
    setCatalogue(null);
    setCatalogueBusy(true);
    try {
      const coordinates = parseWktPolygon(aoiWkt);
      const response = await fetch(API_BASE + '/api/river-shift/catalog/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          coordinates,
          start_date: startDate,
          end_date: endDate,
          maturity,
          main_band_polarization: polarization || null,
          flight_direction: direction || null,
          frame_coverage: frameCoverage,
          max_results: 100,
        }),
      });
      const payload = await response.json() as CatalogueResponse | { detail?: string };
      if (!response.ok) {
        const detail = 'detail' in payload && payload.detail ? payload.detail : 'Catalogue request failed (' + response.status + ').';
        throw new Error(detail);
      }
      setCatalogue(payload as CatalogueResponse);
    } catch (error) {
      setCatalogueError(error instanceof Error ? error.message : 'Could not search the ASF catalogue.');
    } finally {
      setCatalogueBusy(false);
    }
  };

  const loadReport = async (file?: File) => {
    if (!file) return;
    setReportError('');
    setReport(null);
    setGeoJSONFiles([]);
    setTimeSeriesIndex(0);
    setTimeSeriesPlaying(false);
    try {
      const payload = JSON.parse(await file.text()) as unknown;
      setReport(parseRiverShiftReport(payload));
    } catch (error) {
      setReportError(error instanceof Error ? error.message : 'Could not read the result JSON.');
    }
  };

  const loadGeoJSONFiles = async (files?: FileList | File[]) => {
    if (!files || !files.length) return;
    setGeoJSONError('');
    try {
      const loaded = await Promise.all(Array.from(files).map(async (file) => {
        const bytes = await file.arrayBuffer();
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        const sha256 = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
        const payload = JSON.parse(new TextDecoder().decode(bytes)) as unknown;
        return { fileName: file.name, sha256, data: parseRiverShiftGeoJSON(payload) };
      }));
      setGeoJSONFiles(loaded);
      setTimeSeriesIndex(0);
      setTimeSeriesPlaying(false);
    } catch (error) {
      setGeoJSONError(error instanceof Error ? error.message : 'Could not read the GeoJSON.');
    }
  };

  const finishAoiDrawing = () => {
    try {
      setAoiWkt(formatWktPolygon(aoiVertices));
      setAoiError('');
      setDrawingAoi(false);
      setAoiVertices([]);
    } catch (error) {
      setAoiError(error instanceof Error ? error.message : 'Could not finish the AOI polygon.');
    }
  };

  useEffect(() => {
    if (!GOOGLE_MAPS_KEY) {
      setMapError('Google Maps API key is not configured. Add it to Frontend/.env.local and restart Vite to enable AOI drawing and map overlays.');
      return;
    }
    let cancelled = false;
    if (!mapsConfigured) {
      setOptions({ key: GOOGLE_MAPS_KEY, v: 'weekly' });
      mapsConfigured = true;
    }
    importLibrary('maps').then((mapsLibrary) => {
      if (cancelled) return;
      const maps = mapsLibrary as google.maps.MapsLibrary;
      const mapOptions: google.maps.MapOptions = {
        center: { lat: 24.6, lng: 89.65 },
        zoom: 8,
        mapTypeId: 'satellite',
        streetViewControl: false,
        mapTypeControl: true,
        fullscreenControl: true,
      };
      if (aoiMapElement.current && !aoiMapInstance.current) {
        aoiMapInstance.current = new maps.Map(aoiMapElement.current, mapOptions);
      }
      if (resultMapElement.current && !resultMapInstance.current) {
        resultMapInstance.current = new maps.Map(resultMapElement.current, mapOptions);
      }
      if (aoiMapInstance.current && resultMapInstance.current) setMapReady(true);
    }).catch((error: unknown) => {
      if (!cancelled) setMapError(error instanceof Error ? error.message : 'Google Maps could not be loaded.');
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const map = aoiMapInstance.current;
    if (!mapReady || !map || !drawingAoi) return;
    const listener = map.addListener('click', (event: google.maps.MapMouseEvent) => {
      if (event.latLng) setAoiVertices((vertices) => [...vertices, [event.latLng!.lng(), event.latLng!.lat()]]);
    });
    return () => listener.remove();
  }, [mapReady, drawingAoi]);

  useEffect(() => {
    if (!mapReady) return;
    const map = aoiMapInstance.current;
    if (!map) return;
    if (aoiPolygon.current) aoiPolygon.current.setMap(null);
    aoiPolygon.current = null;
    let points: Wgs84Point[] = [];
    try {
      points = drawingAoi ? aoiVertices : parseWktPolygon(aoiWkt).slice(0, -1);
    } catch {
      points = drawingAoi ? aoiVertices : [];
    }
    if (points.length >= 3) {
      if (aoiPreviewLine.current) aoiPreviewLine.current.setMap(null);
      aoiPolygon.current = new google.maps.Polygon({
        paths: points.map(([lng, lat]) => ({ lng, lat })),
        strokeColor: '#70eee0',
        strokeOpacity: 0.95,
        strokeWeight: 3,
        fillColor: '#51d9cc',
        fillOpacity: 0.16,
        clickable: false,
      });
      aoiPolygon.current.setMap(map);
    } else if (points.length > 0) {
      if (!aoiPreviewLine.current) aoiPreviewLine.current = new google.maps.Polyline({
        strokeColor: '#70eee0', strokeOpacity: 0.95, strokeWeight: 3,
      });
      aoiPreviewLine.current.setPath(points.map(([lng, lat]) => ({ lng, lat })));
      aoiPreviewLine.current.setMap(map);
    } else if (aoiPreviewLine.current) {
      aoiPreviewLine.current.setMap(null);
    }
    if (aoiWkt && !drawingAoi) {
      const bounds = new google.maps.LatLngBounds();
      points.forEach(([lng, lat]) => bounds.extend({ lng, lat }));
      if (!bounds.isEmpty()) map.fitBounds(bounds);
    }
  }, [mapReady, drawingAoi, aoiVertices, aoiWkt]);

  useEffect(() => {
    if (!mapReady) return;
    const map = resultMapInstance.current;
    if (!map) return;
    map.data.forEach((feature) => map.data.remove(feature));
    const displayLayers = hasJobPreviewOverlay && jobPreview && riverJobId && jobPreview.jobId === riverJobId
      ? [jobPreview.changeLayer?.data, currentJobFrame].filter((layer): layer is RiverShiftGeoJSON => Boolean(layer))
      : currentTimeSeriesFrame
        ? [currentTimeSeriesFrame.data]
        : verifiedGeoJSONFiles.map((file) => file.data);
    displayLayers.forEach((layer) => map.data.addGeoJson(layer as unknown as object));
    map.data.setStyle((feature) => {
      const name = String(feature.getProperty('class') || feature.getProperty('change_type') || '').toLowerCase();
      const colour = name.includes('erosion') ? '#f07462'
        : name.includes('deposition') ? '#5fd7a5'
          : '#53b9f4';
      return { fillColor: colour, strokeColor: colour, fillOpacity: 0.34, strokeWeight: 2 };
    });
    const bounds = new google.maps.LatLngBounds();
    map.data.forEach((feature) => {
      const geometry = feature.getGeometry();
      if (geometry) geometry.forEachLatLng((point) => bounds.extend(point));
    });
    if (!bounds.isEmpty()) map.fitBounds(bounds);
  }, [mapReady, currentTimeSeriesFrame, verifiedGeoJSONFiles, jobPreview, currentJobFrame, riverJobId, hasJobPreviewOverlay]);

  useEffect(() => {
    if (!timeSeriesPlaying || playbackFrames.length < 2) return;
    const timer = window.setInterval(() => {
      setTimeSeriesIndex((index) => (index + 1) % playbackFrames.length);
    }, 1100);
    return () => window.clearInterval(timer);
  }, [timeSeriesPlaying, playbackFrames.length]);

  useEffect(() => {
    if (!jobTimeSeriesPlaying || jobTimeSeriesFrames.length < 2) return;
    const timer = window.setInterval(() => {
      setJobTimeSeriesIndex((index) => (index + 1) % jobTimeSeriesFrames.length);
    }, 1100);
    return () => window.clearInterval(timer);
  }, [jobTimeSeriesPlaying, jobTimeSeriesFrames.length]);

  const resultType = useMemo(() => report ? report.analysis_type.replace(/_/g, ' ') : 'No result imported', [report]);

  return (
    <main className="river-shift-page">
      <header className="rs-header">
        <button className="rs-back" onClick={onHome} type="button">← SARGuardian</button>
        <div className="rs-brand">
          <span className="rs-brand-mark">RS</span>
          <div><strong>RiverShift</strong><small>FLOOD & RIVER CHANGE INTELLIGENCE</small></div>
        </div>
        <div className="rs-header-actions">
          <span className="rs-challenge-tag">NASA SPACE APPS 2026 · DANCING WITH THE SARS</span>
          {user
            ? <button className="rs-secondary-button" type="button" onClick={() => void onSignOut()}>{user.displayName || 'Account'} · Sign out</button>
            : <button className="rs-secondary-button" type="button" disabled={!firebaseConfigured || authState === 'loading'} onClick={() => void onSignIn()}>{firebaseConfigured ? 'Sign in to process' : 'Sign-in setup required'}</button>}
        </div>
      </header>

      <section className="rs-hero">
        <div>
          <p className="rs-kicker">NISAR-POWERED SURFACE CHANGE MONITORING</p>
          <h1>Track the river.<br /><em>Measure the change.</em></h1>
          <p className="rs-intro">
            Discover real NISAR GCOV acquisitions, inspect reproducible RiverShift analysis reports,
            and compare observed floodwater and persistent river-change candidates.
          </p>
          <div className="rs-hero-tags">
            <span>NASA-ISRO NISAR</span><span>GCOV · L-BAND</span><span>ASF DAAC</span>
          </div>
        </div>
        <div className="rs-hero-visual" aria-hidden="true">
          <div className="rs-river-contour rs-contour-one" />
          <div className="rs-river-contour rs-contour-two" />
          <div className="rs-river-contour rs-contour-three" />
          <div className="rs-river-dot rs-dot-one" /><div className="rs-river-dot rs-dot-two" /><div className="rs-river-dot rs-dot-three" />
          <span>RIVER SYSTEM<br />CHANGE OBSERVATORY</span>
        </div>
      </section>

      <section className="rs-workspace-grid">
        <div className="rs-panel">
          <div className="rs-section-heading">
            <div><p className="rs-kicker">01 · DATA DISCOVERY</p><h2>Find NISAR GCOV acquisitions</h2></div>
            <span className="rs-chip">LIVE ASF CATALOGUE</span>
          </div>
          <p className="rs-muted">
            Search metadata from the ASF DAAC archive. This action does not download products or run scientific analysis.
          </p>
          <form onSubmit={searchCatalogue} className="rs-form">
            <section className="rs-aoi-draw" aria-label="Draw study area on the map">
              <div className="rs-section-heading">
                <div><p className="rs-kicker">STUDY AREA</p><h3>Draw AOI on satellite map</h3></div>
              </div>
              <p className="rs-muted">Click the map to add boundary vertices in order, then finish the polygon. The same WGS84 AOI is used for catalogue search.</p>
              <div className="rs-map rs-aoi-map" ref={aoiMapElement} role="application" aria-label="Click-to-draw AOI map" />
              {mapError && <p className="rs-warning-inline" role="status">{mapError}</p>}
              <div className="rs-aoi-controls">
                <button className="rs-secondary-button" type="button" disabled={!GOOGLE_MAPS_KEY || !mapReady || drawingAoi}
                  onClick={() => { setAoiError(''); setAoiVertices([]); setDrawingAoi(true); }}>
                  {drawingAoi ? 'Drawing… click the map' : 'Start drawing'}
                </button>
                <button className="rs-secondary-button" type="button" disabled={!drawingAoi || aoiVertices.length < 3} onClick={finishAoiDrawing}>Finish AOI</button>
                <button className="rs-secondary-button" type="button" onClick={() => { setDrawingAoi(false); setAoiVertices([]); setAoiWkt(''); setAoiError(''); }}>Clear</button>
                <span>{drawingAoi ? `${aoiVertices.length} vertex/vertices added` : 'Click “Start drawing” to place vertices'}</span>
              </div>
              {aoiError && <p className="rs-error" role="alert">{aoiError}</p>}
              {!GOOGLE_MAPS_KEY && <p className="rs-warning-inline">Set VITE_GOOGLE_MAPS_API_KEY in Frontend/.env.local and restart the frontend to enable the map.</p>}
            </section>
            <label className="rs-field rs-field-full">
              <span>Study area · WGS84 Polygon WKT</span>
              <textarea value={aoiWkt} onChange={(event) => setAoiWkt(event.target.value)}
                placeholder="Paste a closed POLYGON ((longitude latitude, ...)) from ASF Vertex."
                rows={4} required />
              <small>Coordinates are longitude, latitude. Use the exact same AOI for every selected acquisition.</small>
            </label>
            <div className="rs-fields-two">
              <label className="rs-field"><span>Start date</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required /></label>
              <label className="rs-field"><span>End date</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} required /></label>
              <label className="rs-field"><span>Event date · from independent record</span><input type="date" value={eventDate} onChange={(event) => setEventDate(event.target.value)} min={startDate} max={endDate} /></label>
              <label className="rs-field"><span>Processing maturity</span>
                <select value={maturity} onChange={(event) => setMaturity(event.target.value as typeof maturity)}>
                  <option value="PROVISIONAL">PROVISIONAL</option><option value="BETA">BETA</option><option value="ALL">ALL (audit only)</option>
                </select>
              </label>
              <label className="rs-field"><span>Frequency A polarization</span>
                <select value={polarization} onChange={(event) => setPolarization(event.target.value)}>
                  <option value="">Any</option><option value="VV">VV</option><option value="VV+VH">VV + VH</option>
                  <option value="HH">HH</option><option value="HH+HV">HH + HV</option><option value="HH+VV">HH + VV</option>
                  <option value="HH+HV+VH+VV">Full quad-pol</option><option value="LH+LV">LH + LV</option><option value="RH+RV">RH + RV</option>
                </select>
              </label>
              <label className="rs-field rs-field-full"><span>Orbit direction</span>
                <select value={direction} onChange={(event) => setDirection(event.target.value)}>
                  <option value="">Any direction</option><option value="ASCENDING">Ascending</option><option value="DESCENDING">Descending</option>
                </select>
              </label>
              <label className="rs-field rs-field-full"><span>NISAR frame coverage</span>
                <select value={frameCoverage} onChange={(event) => setFrameCoverage(event.target.value as typeof frameCoverage)}>
                  <option value="ALL">All footprints (recommended for discovery)</option>
                  <option value="FULL">Full frames only</option>
                  <option value="PARTIAL">Partial frames only</option>
                </select>
                <small>FULL/PARTIAL refers to NISAR frame coverage, not the percentage of your AOI covered. That must be checked separately.</small>
              </label>
              <label className="rs-field"><span>Science frequency</span>
                <select value={scienceFrequency} onChange={(event) => setScienceFrequency(event.target.value as typeof scienceFrequency)}>
                  <option value="frequencyA">Frequency A</option><option value="frequencyB">Frequency B</option>
                </select>
              </label>
              <label className="rs-field"><span>Diagonal covariance term</span>
                <select value={covarianceTerm} onChange={(event) => setCovarianceTerm(event.target.value)}>
                  <option>HHHH</option><option>HVHV</option><option>VVVV</option><option>VHVH</option><option>RHRH</option><option>RVRV</option>
                </select>
              </label>
              <label className="rs-field"><span>Common water threshold method</span>
                <select value={thresholdMethod} onChange={(event) => setThresholdMethod(event.target.value as typeof thresholdMethod)}>
                  <option value="otsu">Common Otsu · exploratory</option><option value="manual">Manual dB threshold</option>
                </select>
              </label>
              {thresholdMethod === 'manual' && <label className="rs-field"><span>Common threshold (dB)</span><input type="number" min="-60" max="0" step="0.1" required value={thresholdDb} onChange={(event) => setThresholdDb(event.target.value)} /></label>}
            </div>
            <button className="rs-primary-button" type="submit" disabled={catalogueBusy}>
              {catalogueBusy ? 'Searching ASF…' : 'Search GCOV archive'}
            </button>
            <button className="rs-secondary-button" type="button" disabled={riverJobBusy || catalogue?.status !== 'ready' || !aoiWkt || !eventDate || !user || maturity === 'ALL'} onClick={() => void startLiveProcessing()}>
              {riverJobBusy ? 'Submitting job…' : 'Download NISAR data & process'}
            </button>
            {!user && <p className="rs-muted">Live processing requires account sign-in so job status and private results stay owner-protected.</p>}
            {eventDate && <p className="rs-warning-inline">The event date is user supplied. Until official gauge/event evidence is attached, results remain provisional.</p>}
            {catalogueError && <p className="rs-error" role="alert">{catalogueError}</p>}
          </form>
          {catalogue && (
            <div className="rs-catalogue-result">
              <div className="rs-result-summary"><strong>{catalogue.product_count} product(s)</strong><span>{catalogue.message}</span></div>
              <div className="rs-info-banner">Catalogue discovery only · Data downloaded: No · Scientific analysis: Not performed</div>
              {catalogue.warnings.map((warning, index) => <p className="rs-warning-inline" key={index}>{warning}</p>)}
              {catalogue.products.length > 0 && (
                <div className="rs-table-wrap">
                  <table className="rs-table">
                    <thead><tr><th>Acquisition</th><th>Track / frame</th><th>Mode / pol.</th><th>Coverage</th><th>Maturity</th><th>Product</th></tr></thead>
                    <tbody>
                      {catalogue.products.map((product) => (
                        <tr key={product.granule_name}>
                          <td>{formatDate(product.start_time_utc)}</td>
                          <td>{product.flight_direction || '—'}<small>R{product.relative_orbit || '—'} · F{product.frame || '—'}</small></td>
                          <td>{product.bandwidth_mode || '—'}<small>{product.main_band_polarization || product.polarization_code || '—'}</small></td>
                          <td>{product.frame_coverage || 'Unknown'}</td>
                          <td><span className={'rs-maturity rs-' + product.maturity.toLowerCase()}>{product.maturity}</span></td>
                          <td>{product.download_url
                            ? <a href={product.download_url} target="_blank" rel="noreferrer">Open ASF product ↗</a>
                            : <span>URL unavailable</span>}
                            <small>{product.processing_type || 'Processing type unknown'} · {product.crid || 'CRID unknown'}</small><small>{product.granule_name}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        <aside className="rs-panel rs-pipeline-panel">
          <p className="rs-kicker">02 · SCIENTIFIC WORKFLOW</p>
          <h2>From radar to evidence</h2>
          <ol className="rs-pipeline">
            <li><b>Discover</b><span>Find actual NISAR GCOV products in ASF DAAC.</span></li>
            <li><b>Prepare</b><span>Inspect HDF5, check maturity, extract the same diagonal term and clip the same AOI.</span></li>
            <li><b>Detect</b><span>Screen open water on comparable pre-event, flood-period and post-event observations.</span></li>
            <li><b>Measure</b><span>Quantify water coverage and persistent land/water transitions.</span></li>
            <li><b>Validate</b><span>Compare against an independent reference and report F1/IoU.</span></li>
          </ol>
          <a className="rs-doc-link" href="https://nisar-docs.asf.alaska.edu/gcov/" target="_blank" rel="noreferrer">NISAR GCOV product guide ↗</a>
          <a className="rs-doc-link" href="https://docs.asf.alaska.edu/api/keywords/" target="_blank" rel="noreferrer">ASF Search API documentation ↗</a>
          <a className="rs-doc-link" href="https://nisar-docs.asf.alaska.edu/availability-overview/" target="_blank" rel="noreferrer">NISAR data availability & maturity ↗</a>
        </aside>
      </section>

      {riverJobBusy && (
        <section className="rs-panel rs-job-feedback" role="status" aria-live="polite">
          <div className="rs-info-banner">
            <strong>Submitting RiverShift job…</strong>{' '}
            The API is validating the AOI and confirming the NASA CMR acquisition manifest before dispatch.
            No NISAR product download starts until this step succeeds.
          </div>
        </section>
      )}
      {riverJobError && (
        <section className="rs-panel rs-job-feedback" aria-live="assertive">
          <p className="rs-error" role="alert">{riverJobError}</p>
        </section>
      )}
      {riverJob && <section className="rs-panel rs-job-panel" aria-live="polite">
        <div className="rs-section-heading"><div><p className="rs-kicker">LIVE SCIENCE JOB</p><h2>{riverJob.state.replace(/_/g, ' ')} · {riverJob.stage.replace(/_/g, ' ')}</h2></div>
          <span className="rs-chip">{riverJob.maturity} · {riverJob.frequency} / {riverJob.covariance_term}</span></div>
        <p className="rs-muted">Job ID {riverJob.id} · {riverJob.start_date} to {riverJob.end_date}</p>
        {riverJob.github_run_url && <p><a href={riverJob.github_run_url} target="_blank" rel="noreferrer">Open processing run logs ↗</a></p>}
        {riverJob.error_message && <p className="rs-error" role="alert">{riverJob.error_message}</p>}
        {riverJob.state === 'succeeded' && <div className="rs-warning-inline"><strong>Processing complete · PROVISIONAL.</strong> Independent validation and authoritative event confirmation are pending. The map below can show a checksum-checked display preview; its measurements are not verified.</div>}
        {jobPreview?.jobId === riverJob.id && jobPreview.report && jobTimeSeriesFrames.length > 0 && (
          <section className="rs-timeseries" aria-label="Provisional observed acquisition playback">
            <div className="rs-section-heading"><div><p className="rs-kicker">OBSERVED ACQUISITIONS</p><h3>River change playback</h3></div>
              <span className="rs-chip">PROVISIONAL · NO DAILY INTERPOLATION</span></div>
            <p className="rs-warning-inline">Each step is an actual NISAR acquisition date. The blue layer shows open-water candidates; the red and green layers show persistent erosion and deposition candidates. These are radar screening results, not field-confirmed change.</p>
            <div className="rs-playback-controls">
              <button className="rs-secondary-button" type="button" onClick={() => setJobTimeSeriesIndex((index) => (index - 1 + jobTimeSeriesFrames.length) % jobTimeSeriesFrames.length)}>Previous</button>
              <button className="rs-primary-button" type="button" disabled={jobTimeSeriesFrames.length < 2} onClick={() => setJobTimeSeriesPlaying((value) => !value)}>{jobTimeSeriesPlaying ? 'Pause' : 'Play'}</button>
              <button className="rs-secondary-button" type="button" onClick={() => setJobTimeSeriesIndex((index) => (index + 1) % jobTimeSeriesFrames.length)}>Next</button>
              <label className="rs-date-slider"><span>Observed date</span>
                <input type="range" min={0} max={jobTimeSeriesFrames.length - 1} value={jobTimeSeriesIndex}
                  onChange={(event) => { setJobTimeSeriesPlaying(false); setJobTimeSeriesIndex(Number(event.target.value)); }} />
              </label>
            </div>
            {currentJobFrameMetadata && <p className="rs-info-banner">Observed {currentJobFrameMetadata.date} · open-water candidate area {currentJobFrameMetadata.water_area_km2.toFixed(3)} km² · valid samples {(currentJobFrameMetadata.valid_pixel_fraction * 100).toFixed(1)}%{!currentJobFrame ? ' · loading map layer…' : ''}</p>}
          </section>
        )}
        {jobPreview?.jobId === riverJob.id && jobPreview.error && <p className="rs-warning-inline" role="status">{jobPreview.error}</p>}
        {!!riverJob.artifact_manifest?.length && <div className="rs-artifact-list"><strong>Private result files · checksum verified</strong>{riverJob.artifact_manifest.map((artifact, index) => artifact.bytes <= 4_000_000
          ? <button className="rs-secondary-button" key={`${artifact.path}-${index}`} type="button" onClick={() => void saveRiverArtifact(index, artifact.name)}>{artifact.name} · {(artifact.bytes / 1_000_000).toFixed(2)} MB</button>
          : <span className="rs-muted" key={`${artifact.path}-${index}`}>{artifact.name} · {(artifact.bytes / 1_000_000).toFixed(2)} MB · stored privately; too large for in-app download</span>)}</div>}
      </section>}

      <section className="rs-panel rs-results-panel">
        <div className="rs-section-heading">
          <div><p className="rs-kicker">03 · RESULTS EXPLORER</p><h2>Inspect reproducible outputs</h2></div>
          <span className="rs-chip">NO SYNTHETIC METRICS</span>
        </div>
        <p className="rs-muted">
          Run the documented CLI scripts in tools/river_shift, then import their result JSON and GeoJSON here.
          Catalogue rows are never presented as measured flood or erosion results.
        </p>
        <div className="rs-upload-grid">
          <label className="rs-upload"><span>Import result JSON</span><small>Flood, morphology or validation report</small>
            <input type="file" accept=".json,application/json" onChange={(event) => void loadReport(event.target.files?.[0])} />
          </label>
          <label className="rs-upload"><span>Import change GeoJSON layer(s)</span><small>For playback, select every `water_YYYY-MM-DD.geojson` named in the report</small>
            <input type="file" multiple accept=".geojson,.json,application/geo+json,application/json" onChange={(event) => void loadGeoJSONFiles(event.target.files || undefined)} />
          </label>
        </div>
        {reportError && <p className="rs-error" role="alert">{reportError}</p>}
        {geoJSONError && <p className="rs-error" role="alert">{geoJSONError}</p>}
        {report && <ReportPanel report={report} />}
        {report?.analysis_type === 'water_timeseries_screening' && (
          <section className="rs-timeseries" aria-label="Observed acquisition playback">
            <div className="rs-section-heading"><div><p className="rs-kicker">OBSERVED ACQUISITIONS</p><h3>Water change playback</h3></div>
              <span className="rs-chip">NO DAILY INTERPOLATION</span></div>
            {report.quality.release_status !== 'VERIFIED'
              ? <p className="rs-warning-inline">Playback and map layers stay hidden until the report is independently reviewed and marked VERIFIED.</p>
              : playbackFrames.length !== (report.time_series || []).length
                ? <p className="rs-warning-inline">Import every report-listed GeoJSON file in one selection. Each filename and SHA-256 must match before playback starts.</p>
                : playbackFrames.length < 2
                  ? <p className="rs-warning-inline">At least two verified observation frames are required to play this time series.</p>
                  : <>
                    <div className="rs-playback-controls">
                      <button className="rs-secondary-button" type="button" onClick={() => setTimeSeriesIndex((index) => (index - 1 + playbackFrames.length) % playbackFrames.length)}>Previous</button>
                      <button className="rs-primary-button" type="button" onClick={() => setTimeSeriesPlaying((value) => !value)}>{timeSeriesPlaying ? 'Pause' : 'Play'}</button>
                      <button className="rs-secondary-button" type="button" onClick={() => setTimeSeriesIndex((index) => (index + 1) % playbackFrames.length)}>Next</button>
                      <label className="rs-date-slider"><span>Acquisition date</span>
                        <input type="range" min={0} max={playbackFrames.length - 1} value={timeSeriesIndex}
                          onChange={(event) => { setTimeSeriesPlaying(false); setTimeSeriesIndex(Number(event.target.value)); }} />
                      </label>
                    </div>
                    {currentTimeSeriesFrame && <p className="rs-info-banner">Observed {currentTimeSeriesFrame.date} · candidate open-water area {currentTimeSeriesFrame.water_area_km2.toFixed(3)} km² · valid samples {(currentTimeSeriesFrame.valid_pixel_fraction * 100).toFixed(1)}%</p>}
                  </>}
          </section>
        )}
        <section className="rs-map-section">
          <div className="rs-section-heading"><div><p className="rs-kicker">GEOSPATIAL OUTPUT</p><h3>Change map</h3></div></div>
          {mapError && <p className="rs-warning-inline">{mapError}</p>}
          <div className="rs-map" ref={resultMapElement} role="img" aria-label="Google satellite basemap with checksum-checked RiverShift result overlays" />
          <div className="rs-legend"><span><i className="rs-swatch rs-erosion" />Erosion candidate</span><span><i className="rs-swatch rs-deposition" />Deposition candidate</span><span><i className="rs-swatch rs-water" />New water / observed water candidate</span></div>
          {hasVerifiedOverlay && <p className="rs-muted">Verified layer(s) are drawn; each GeoJSON SHA-256 matches the loaded report. Candidate classes require scientific interpretation and are not field-confirmed land change.</p>}
          {hasJobPreviewOverlay && !hasVerifiedOverlay && <p className="rs-warning-inline">Provisional job preview is drawn. The full-resolution science reports remain PROVISIONAL; map geometries are simplified for display and small patches may be omitted.</p>}
          {report && geoJSONFiles.length > 0 && !hasVerifiedOverlay && <p className="rs-warning-inline" role="status">Loaded GeoJSON is not drawn: the report is not VERIFIED, the checksum does not match, or the complete time-series layer set is missing.</p>}
        </section>
        {!report && <div className="rs-empty-state"><strong>{resultType}</strong><p>No scientific result is loaded. Run a script and import its JSON report; no demo measurement is shown here.</p></div>}
      </section>

      <footer className="rs-footer">
        <span>SARGuardian · RiverShift</span><span>Open science · Reproducible processing · Evidence before claims</span>
      </footer>
    </main>
  );
}
