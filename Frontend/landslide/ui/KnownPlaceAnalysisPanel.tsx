import { useCallback, useEffect, useState } from 'react';
import { KnownPlacePolygonEditor } from './KnownPlacePolygonEditor';
import { parsePolygonWkt } from '../engine/investigation';
import type { User } from 'firebase/auth';
import {
  getKnownPlaceAnalysisStatus,
  getKnownPlacePaperReproductionStatus,
  startKnownPlaceAnalysis,
  startKnownPlacePaperReproduction,
  type KnownPlaceAnalysisMode,
  type KnownPlaceAnalysisRun,
  type KnownPlaceHazardMode,
} from '../../src/api/knownPlace';

type StoredRun = KnownPlaceAnalysisRun & { execute_downloads: boolean };

type CandidateTransfer = {
  schemaVersion: 'sarguardian-known-place-candidate/1.0';
  measurementWkt: string;
  candidate: {
    candidateId: string; productType: 'GOFF'; metric: string; evidenceClass: string; status: string;
    supportPairs: number; pixelCount: number; approximateAreaM2: number; productIds: string[];
    pairIntervals: Array<Record<string, unknown>>; geometryOriginalVertices: number; geometrySuggestedVertices: number;
    geometrySimplified: boolean; interpretation: string;
  };
};

function consumeCandidateTransfer(): CandidateTransfer | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem('sarguardian.knownPlaceCandidate.v1');
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<CandidateTransfer>;
    if (value.schemaVersion !== 'sarguardian-known-place-candidate/1.0') return null;
    if (typeof value.measurementWkt !== 'string' || !value.measurementWkt.startsWith('POLYGON')) return null;
    if (!value.candidate || value.candidate.productType !== 'GOFF' || typeof value.candidate.candidateId !== 'string') return null;
    return value as CandidateTransfer;
  } catch { return null; }
}

type Props = {
  user: User;
  aoiWkt: string | null;
  startDate: string;
  endDate: string;
  placeName: string | null;
  aoiAreaKm2: number;
  onBack: () => void;
};

const hazardModes: { value: KnownPlaceHazardMode; label: string }[] = [
  { value: 'landslide', label: 'Landslide' },
  { value: 'glacier_collapse', label: 'Glacier collapse' },
  { value: 'ice_rock_avalanche', label: 'Ice–rock avalanche' },
  { value: 'mixed', label: 'Mixed / uncertain' },
];

const analysisModes: { value: KnownPlaceAnalysisMode; label: string }[] = [
  { value: 'exploratory', label: 'Exploratory measurement' },
  { value: 'retrospective_validation', label: 'Retrospective validation' },
];

function storageKey(uid: string): string {
  return `sarguardian.knownPlaceAnalysis.v1:${uid}`;
}

function paperReproductionStorageKey(uid: string): string {
  return `sarguardian.knownPlacePaperReproduction.v1:${uid}`;
}

function loadPaperReproductionRun(uid: string): StoredRun | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(paperReproductionStorageKey(uid));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredRun>;
    if (typeof parsed.request_id !== 'string' || !/^[0-9a-f-]{36}$/i.test(parsed.request_id)) return null;
    if (!['dispatching', 'queued', 'in_progress', 'completed'].includes(String(parsed.status))) return null;
    return { ...parsed, execute_downloads: true } as StoredRun;
  } catch {
    return null;
  }
}

function geometryDraftKey(uid: string): string {
  return `sarguardian.knownPlaceGeometry.v1:${uid}`;
}

type GeometryDraft = { measurementWkt: string; referenceWkt: string };

function loadGeometryDraft(uid: string): GeometryDraft {
  if (typeof window === 'undefined') return { measurementWkt: '', referenceWkt: '' };
  try {
    const raw = window.sessionStorage.getItem(geometryDraftKey(uid));
    if (!raw) return { measurementWkt: '', referenceWkt: '' };
    const parsed = JSON.parse(raw) as Partial<GeometryDraft>;
    return {
      measurementWkt: typeof parsed.measurementWkt === 'string' ? parsed.measurementWkt : '',
      referenceWkt: typeof parsed.referenceWkt === 'string' ? parsed.referenceWkt : '',
    };
  } catch {
    return { measurementWkt: '', referenceWkt: '' };
  }
}

function samePolygonGeometry(firstWkt: string, secondWkt: string): boolean {
  try {
    const first = parsePolygonWkt(firstWkt);
    const second = parsePolygonWkt(secondWkt);
    return first.length === second.length && first.every((point, index) =>
      Math.abs(point[0] - second[index][0]) <= 1e-9
      && Math.abs(point[1] - second[index][1]) <= 1e-9,
    );
  } catch {
    return false;
  }
}


function loadStoredRun(uid: string): StoredRun | null {
  if (typeof window === 'undefined') return null;
  try {
    const value = sessionStorage.getItem(storageKey(uid));
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<StoredRun>;
    if (typeof parsed.request_id !== 'string' || !/^[0-9a-f-]{36}$/i.test(parsed.request_id)) return null;
    if (typeof parsed.execute_downloads !== 'boolean') return null;
    if (!['dispatching', 'queued', 'in_progress', 'completed'].includes(String(parsed.status))) return null;
    return parsed as StoredRun;
  } catch {
    return null;
  }
}

function resultLabel(run: StoredRun): string {
  if (run.status !== 'completed') return run.status === 'dispatching' ? 'Starting' : 'Running';
  if (run.conclusion === 'success') return 'Workflow completed';
  if (run.conclusion === 'cancelled') return 'Cancelled';
  return 'Workflow failed';
}

export function KnownPlaceAnalysisPanel({ user, aoiWkt, startDate, endDate, placeName, aoiAreaKm2, onBack }: Props) {
  const [hazardMode, setHazardMode] = useState<KnownPlaceHazardMode>('mixed');
  const [analysisMode, setAnalysisMode] = useState<KnownPlaceAnalysisMode>('exploratory');
  const [polarization, setPolarization] = useState<'HH' | 'HV' | 'VV' | 'VH'>('HH');
  const [track, setTrack] = useState('ANY');
  const [direction, setDirection] = useState<'ANY' | 'A' | 'D'>('ANY');
  const [coherenceNeighbours, setCoherenceNeighbours] = useState<'1' | '5' | '10' | '15' | '20' | '25'>('1');
  const [allowedReleaseIds, setAllowedReleaseIds] = useState('');
  const [candidateTransfer] = useState<CandidateTransfer | null>(() => consumeCandidateTransfer());
  const [geometryDraft] = useState<GeometryDraft>(() => loadGeometryDraft(user.uid));
  const [measurementWkt, setMeasurementWkt] = useState(() => candidateTransfer?.measurementWkt || geometryDraft.measurementWkt || '');
  const [referenceWkt, setReferenceWkt] = useState(() => geometryDraft.referenceWkt);
  const [polygonValidation, setPolygonValidation] = useState({ valid: false, message: 'Draw and close both analysis polygons.' });
  const [geometryHeight, setGeometryHeight] = useState('');
  const [confirmRawDownloads, setConfirmRawDownloads] = useState(false);
  const [paperRawConsent, setPaperRawConsent] = useState(false);
  const [paperPending, setPaperPending] = useState(false);
  const [paperRun, setPaperRun] = useState<StoredRun | null>(() => loadPaperReproductionRun(user.uid));
  const [paperError, setPaperError] = useState('');
  const [paperPollError, setPaperPollError] = useState('');
  const [pendingAction, setPendingAction] = useState<'dry-run' | 'analysis' | null>(null);
  const [run, setRun] = useState<StoredRun | null>(() => loadStoredRun(user.uid));
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const handleMeasurementChange = useCallback((wkt: string) => setMeasurementWkt(wkt), []);
  const handleReferenceChange = useCallback((wkt: string) => setReferenceWkt(wkt), []);
  const handlePolygonValidation = useCallback((result: { valid: boolean; message: string }) => setPolygonValidation(result), []);
  const canSubmitGeometry = Boolean(aoiWkt && measurementWkt && referenceWkt && polygonValidation.valid);

  useEffect(() => {
    try {
      if (!measurementWkt && !referenceWkt) {
        sessionStorage.removeItem(geometryDraftKey(user.uid));
      } else {
        sessionStorage.setItem(geometryDraftKey(user.uid), JSON.stringify({ measurementWkt, referenceWkt }));
      }
    } catch { /* session storage is optional; current component state remains authoritative */ }
  }, [measurementWkt, referenceWkt, user.uid]);

  useEffect(() => {
    if (!run) {
      try { sessionStorage.removeItem(storageKey(user.uid)); } catch { /* session storage is optional */ }
      return;
    }
    try { sessionStorage.setItem(storageKey(user.uid), JSON.stringify(run)); } catch { /* session storage is optional */ }
  }, [run, user.uid]);

  useEffect(() => {
    if (!paperRun) {
      try { sessionStorage.removeItem(paperReproductionStorageKey(user.uid)); } catch { /* session storage is optional */ }
      return;
    }
    try { sessionStorage.setItem(paperReproductionStorageKey(user.uid), JSON.stringify(paperRun)); } catch { /* session storage is optional */ }
  }, [paperRun, user.uid]);

  const paperRunRequestId = paperRun?.request_id ?? null;
  const paperRunStatus = paperRun?.status ?? null;

  useEffect(() => {
    const requestId = paperRunRequestId;
    if (!requestId || paperRunStatus === 'completed') return undefined;
    let active = true;
    let timeoutId: number | undefined;
    const poll = async () => {
      try {
        const next = await getKnownPlacePaperReproductionStatus(requestId, user);
        if (!active) return;
        setPaperPollError('');
        setPaperRun((current) => current && current.request_id === next.request_id
          ? { ...current, ...next, execute_downloads: true }
          : current);
        if (next.status !== 'completed' && active) timeoutId = window.setTimeout(poll, 3500);
      } catch (statusError) {
        if (!active) return;
        setPaperPollError(statusError instanceof Error ? statusError.message : 'Could not refresh paper-reproduction status yet.');
        timeoutId = window.setTimeout(poll, 8000);
      }
    };
    timeoutId = window.setTimeout(poll, 1200);
    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [paperRunRequestId, paperRunStatus, user]);

  const runRequestId = run?.request_id ?? null;
  const runStatus = run?.status ?? null;

  useEffect(() => {
    const requestId = runRequestId;
    if (!requestId || runStatus === 'completed') return undefined;
    let active = true;
    let timeoutId: number | undefined;
    const poll = async () => {
      try {
        const next = await getKnownPlaceAnalysisStatus(requestId, user);
        if (!active) return;
        setPollError('');
        setRun((current) => current && current.request_id === next.request_id
          ? { ...current, ...next, execute_downloads: current.execute_downloads }
          : current);
        if (next.status !== 'completed' && active) timeoutId = window.setTimeout(poll, 3500);
      } catch (statusError) {
        if (!active) return;
        setPollError(statusError instanceof Error ? statusError.message : 'Could not refresh this run yet.');
        timeoutId = window.setTimeout(poll, 8000);
      }
    };
    timeoutId = window.setTimeout(poll, 1200);
    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [runRequestId, runStatus, user]);

  const submit = async (executeDownloads: boolean) => {
    if (!aoiWkt || !startDate || !endDate) {
      setError('Return to the AOI map and create a valid outer AOI and date window first.');
      return;
    }
    if (!measurementWkt || !referenceWkt || !polygonValidation.valid) {
      setError(polygonValidation.message || 'Draw and validate both the Measurement and Reference polygons before submitting.');
      return;
    }
    if (executeDownloads && !confirmRawDownloads) {
      setError('Confirm raw-data download permission before starting the GOFF measurement run.');
      return;
    }
    if (track.trim().toUpperCase() !== 'ANY' && !/^\d{3}$/.test(track.trim())) {
      setError('Track must be ANY or an exact three-digit value such as 098.');
      return;
    }
    const height = geometryHeight.trim() ? Number(geometryHeight) : null;
    if (height !== null && (!Number.isFinite(height) || height < -500 || height > 100000)) {
      setError('Enter a finite ellipsoidal height between −500 and 100,000 metres, or leave it blank.');
      return;
    }
    setPendingAction(executeDownloads ? 'analysis' : 'dry-run');
    setError('');
    setPollError('');
    try {
      const submitted = await startKnownPlaceAnalysis({
        aoi_wkt: measurementWkt,
        scope_aoi_wkt: aoiWkt,
        start_date: startDate,
        end_date: endDate,
        hazard_mode: hazardMode,
        analysis_mode: analysisMode,
        polarization,
        track: track.trim().toUpperCase(),
        direction,
        coherence_neighbours: coherenceNeighbours,
        allowed_release_ids: allowedReleaseIds.trim(),
        reference_wkt: referenceWkt,
        candidate_context: candidateTransfer ? {
          source: 'FIND_DISPLACEMENTS',
          candidate_id: candidateTransfer.candidate.candidateId,
          product_type: 'GOFF',
          metric: candidateTransfer.candidate.metric,
          evidence_class: candidateTransfer.candidate.evidenceClass,
          status: candidateTransfer.candidate.status,
          support_pairs: candidateTransfer.candidate.supportPairs,
          pixel_count: candidateTransfer.candidate.pixelCount,
          approx_area_m2: candidateTransfer.candidate.approximateAreaM2,
          product_ids: candidateTransfer.candidate.productIds,
          pair_intervals: candidateTransfer.candidate.pairIntervals,
          geometry_original_vertices: candidateTransfer.candidate.geometryOriginalVertices,
          geometry_suggested_vertices: candidateTransfer.candidate.geometrySuggestedVertices,
          geometry_simplified: candidateTransfer.candidate.geometrySimplified,
          geometry_edited: !samePolygonGeometry(measurementWkt, candidateTransfer.measurementWkt),
          interpretation: candidateTransfer.candidate.interpretation,
        } : null,
        geometry_height_m: height,
        execute_downloads: executeDownloads,
        confirm_raw_downloads: executeDownloads && confirmRawDownloads,
      }, user);
      setRun({ ...submitted, execute_downloads: executeDownloads });
      try {
        sessionStorage.removeItem('sarguardian.knownPlaceCandidate.v1');
        sessionStorage.removeItem(geometryDraftKey(user.uid));
      } catch { /* accepted workflow request remains authoritative */ }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Could not submit Known Place Analysis.');
    } finally {
      setPendingAction(null);
    }
  };

  const submitPaperReproduction = async () => {
    if (!paperRawConsent) {
      setPaperError('Explicitly authorize the fixed five-pair P05023 raw-source replay before continuing.');
      return;
    }
    setPaperPending(true);
    setPaperError('');
    setPaperPollError('');
    try {
      const submitted = await startKnownPlacePaperReproduction({ confirm_raw_downloads: true }, user);
      setPaperRun({ ...submitted, execute_downloads: true });
    } catch (submitError) {
      setPaperError(submitError instanceof Error ? submitError.message : 'Could not submit the author-exact paper reproduction.');
    } finally {
      setPaperPending(false);
    }
  };

  const paperRunTerminal = paperRun?.status === 'completed';
  const paperRunSucceeded = paperRunTerminal && paperRun?.conclusion === 'success';
  const paperRunFailed = paperRunTerminal && !paperRunSucceeded;

  const runTerminal = run?.status === 'completed';
  const runSucceeded = runTerminal && run?.conclusion === 'success';
  const runFailed = runTerminal && !runSucceeded;

  return (
    <main className="nisar-results-main displacement-preparation known-place-analysis">
      <section className="nisar-results-summary">
        <span className="result-kicker">KNOWN PLACE · TWO DISTINCT SCIENCE PATHS</span>
        <h1>Known Place Analysis</h1>
        <p>Use the fixed Bhote Koshi author-exact benchmark to reproduce the research workflow, or use the custom two-polygon path for a separate generic GOFF measurement. Neither path is merged into target-free Find Displacements.</p>
        <div className="catalog-stats">
          <div><span>Known place</span><strong>{placeName || 'AOI only — no named place'}</strong></div>
          <div><span>AOI area</span><strong>{Number.isFinite(aoiAreaKm2) && aoiAreaKm2 > 0 ? `${aoiAreaKm2.toFixed(2)} km²` : 'Not validated'}</strong></div>
          <div><span>Start date</span><strong>{startDate || 'Not selected'}</strong></div>
          <div><span>End date</span><strong>{endDate || 'Not selected'}</strong></div>
        </div>
        <p className="catalog-notice">The original map AOI is retained as an outer selection boundary. The Measurement Polygon is the area whose pairwise motion is summarized; the separate Reference Polygon supplies background comparison. A selected reference area is not assumed to be stable ground.</p>
        {!aoiWkt && <p className="catalog-error" role="alert">A valid outer AOI is required. Go back to the map and draw your polygon.</p>}
        <section className="known-place-paper-reproduction" aria-labelledby="known-place-paper-title">
          <div className="known-place-paper-heading">
            <span className="result-kicker">FIXED RESEARCH BENCHMARK · AUTHOR-EXACT P05023</span>
            <h2 id="known-place-paper-title">Bhote Koshi 2026 paper reproduction</h2>
            <p>Replays the five author-specified ascending T098 HH GOFF pairs from 20 June–31 August 2026 using the separately pinned P05023 source path, author terrain inputs, numerical parity checks and derived-only retention.</p>
          </div>
          <div className="known-place-paper-facts">
            <div><span>Author release</span><strong>P05023 only</strong></div>
            <div><span>Study site</span><strong>Bhote Koshi, Nepal</strong></div>
            <div><span>Five intervals</span><strong>20 Jun → 31 Aug 2026</strong></div>
            <div><span>Output retention</span><strong>Derived-only + Drive receipt</strong></div>
          </div>
          <p className="catalog-notice">Scientific claim boundary: the backend's current whole-paper status is PARTIAL. A successful raw replay is not by itself full-paper parity; the original crown vector/golden mask, displacement-null draw history, RGI 6.0 overlay and terrain provenance remain separate evidence gates. Hazard detection remains NOT_EVALUATED.</p>
          <div className="known-place-paper-consent">
            <label>
              <input type="checkbox" checked={paperRawConsent} onChange={(event) => setPaperRawConsent(event.target.checked)} />
              <span><b>I explicitly authorize a new author-exact raw-data replay.</b> This requests the five pinned P05023 GOFF products. Earthdata and Google Drive credentials are checked before acquisition; raw HDF5 stays temporary and derived results/receipts are retained.</span>
            </label>
            <button type="button" className="investigate-button" disabled={!paperRawConsent || paperPending} onClick={() => void submitPaperReproduction()}>
              {paperPending ? 'Submitting paper reproduction…' : 'Run Bhote Koshi author-exact replay'}
            </button>
          </div>
          {paperError && <p className="catalog-error" role="alert">{paperError}</p>}
          {paperRun && (
            <div className="known-place-paper-run" aria-live="polite">
              <div className="known-place-run-heading">
                <span className="result-kicker">AUTHOR-EXACT RUN STATUS</span>
                <strong>{resultLabel(paperRun)}</strong>
              </div>
              <p><b>Request ID:</b> <code>{paperRun.request_id}</code></p>
              {paperRun.github_run_id && <p><b>GitHub Actions run:</b> <code>{paperRun.github_run_id}</code></p>}
              {paperRun.conclusion && <p><b>Conclusion:</b> {paperRun.conclusion}</p>}
              {paperRun.notice && <p className="catalog-notice">{paperRun.notice}</p>}
              {paperPollError && !paperRunTerminal && <p className="action-hint" role="status">{paperPollError} Automatic status checks will retry.</p>}
              {paperRun.github_run_url && <a className="known-place-run-link" href={paperRun.github_run_url} target="_blank" rel="noreferrer">Open author-exact GitHub run and result bundle</a>}
              {paperRunSucceeded && <p className="catalog-notice">The workflow completed. Inspect the actual P05023 hashes, comparison counts, remaining PARITY status and Drive receipt before describing the paper as reproduced.</p>}
              {paperRunFailed && <p className="catalog-error">The author-exact workflow ended with {paperRun.conclusion || 'an error'}. Open the run link to inspect the credential gate or failed scientific stage.</p>}
            </div>
          )}
        </section>
        <section className="known-place-custom-measurement" aria-labelledby="known-place-custom-title">
          <span className="result-kicker">CUSTOM MEASUREMENT · GENERIC GOFF METHOD</span>
          <h2 id="known-place-custom-title">Two-polygon known-place measurement</h2>
          <p>This separate path measures a user-drawn target polygon relative to a disjoint user-drawn background polygon on the selected AOI/date window. It is not the author-exact paper method and reports PAPER_REPRODUCTION_STATUS=NOT_EVALUATED_GENERIC_AOI.</p>
        {candidateTransfer && <div className="catalog-notice known-place-candidate-handoff" role="status">
          <strong>Suggested Measurement Polygon imported from Find Displacements</strong>
          <span>{candidateTransfer.candidate.candidateId} · GOFF offset-anomaly candidate · {candidateTransfer.candidate.supportPairs} supporting pair(s) · {candidateTransfer.candidate.pixelCount} pixels</span>
          <span>{candidateTransfer.candidate.geometrySimplified ? `Boundary simplified from ${candidateTransfer.candidate.geometryOriginalVertices} to ${candidateTransfer.candidate.geometrySuggestedVertices} vertices; inspect and edit it before measurement.` : `${candidateTransfer.candidate.geometrySuggestedVertices} boundary vertices transferred; inspect and edit before measurement.`}</span>
          <span>Candidate evidence is not measured ground motion or a confirmed landslide. Draw the separate reference polygon and verify the proposed measurement area.</span>
        </div>}
        <KnownPlacePolygonEditor
          outerAoiWkt={aoiWkt}
          initialMeasurementWkt={measurementWkt || null}
          initialReferenceWkt={referenceWkt || null}
          onMeasurementChange={handleMeasurementChange}
          onReferenceChange={handleReferenceChange}
          onValidationChange={handlePolygonValidation}
        />
        <div className="known-place-form-grid">
          <label className="aoi-job-label">
            <span>Hazard context</span>
            <select value={hazardMode} onChange={(event) => setHazardMode(event.target.value as KnownPlaceHazardMode)}>
              {hazardModes.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="aoi-job-label">
            <span>Analysis mode</span>
            <select value={analysisMode} onChange={(event) => setAnalysisMode(event.target.value as KnownPlaceAnalysisMode)}>
              {analysisModes.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label className="aoi-job-label">
            <span>Polarization</span>
            <select value={polarization} onChange={(event) => setPolarization(event.target.value as 'HH' | 'HV' | 'VV' | 'VH')}>
              {(['HH', 'HV', 'VV', 'VH'] as const).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label className="aoi-job-label">
            <span>Track</span>
            <input value={track} onChange={(event) => setTrack(event.target.value)} maxLength={3} placeholder="ANY or 098" autoComplete="off" />
          </label>
          <label className="aoi-job-label">
            <span>Flight direction</span>
            <select value={direction} onChange={(event) => setDirection(event.target.value as 'ANY' | 'A' | 'D')}>
              <option value="ANY">Any — keep orbit chains separate</option>
              <option value="A">Ascending</option>
              <option value="D">Descending</option>
            </select>
          </label>
          <label className="aoi-job-label">
            <span>Minimum valid coherence neighbours</span>
            <select value={coherenceNeighbours} onChange={(event) => setCoherenceNeighbours(event.target.value as typeof coherenceNeighbours)}>
              {(['1', '5', '10', '15', '20', '25'] as const).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="aoi-job-label known-place-wide">
            <span>Exact release IDs (optional, comma-separated)</span>
            <input value={allowedReleaseIds} onChange={(event) => setAllowedReleaseIds(event.target.value)} placeholder="Leave blank to retain valid candidates; conflicts fail safe" autoComplete="off" />
          </label>
          <label className="aoi-job-label">
            <span>Constant ellipsoidal height in metres (optional sensitivity only)</span>
            <input type="number" value={geometryHeight} onChange={(event) => setGeometryHeight(event.target.value)} min={-500} max={100000} step="any" placeholder="Blank = documented approximation" />
          </label>
        </div>

        <section className="known-place-run-options" aria-label="Known Place run options">
          <h2>Choose how to run</h2>
          <p className="catalog-notice"><b>Catalog-only dry run:</b> checks the request, product availability and series plan. It does not download raw NISAR products.</p>
          <button type="button" className="demo-button" disabled={!canSubmitGeometry || pendingAction !== null} onClick={() => void submit(false)}>
            {pendingAction === 'dry-run' ? 'Submitting dry run…' : 'Run catalog-only dry run'}
          </button>
          <div className="known-place-consent">
            <label>
              <input type="checkbox" checked={confirmRawDownloads} onChange={(event) => setConfirmRawDownloads(event.target.checked)} />
              <span><b>I explicitly authorize raw NISAR GOFF downloads for this request.</b> The workflow checks Earthdata/Drive credentials before downloading, processes selected products one at a time, and retains derived results and receipts.</span>
            </label>
            <button type="button" className="investigate-button" disabled={!canSubmitGeometry || !confirmRawDownloads || pendingAction !== null} onClick={() => void submit(true)}>
              {pendingAction === 'analysis' ? 'Starting GOFF analysis…' : 'Run Known Place Analysis'}
            </button>
          </div>
          {error && <p className="catalog-error" role="alert">{error}</p>}
        </section>

        {run && (
          <section className="known-place-run-status" aria-live="polite">
            <div className="known-place-run-heading">
              <span className="result-kicker">RUN STATUS</span>
              <strong>{resultLabel(run)}</strong>
            </div>
            <p><b>Request ID:</b> <code>{run.request_id}</code></p>
            {run.github_run_id && <p><b>GitHub Actions run:</b> <code>{run.github_run_id}</code></p>}
            <p><b>Mode:</b> {run.execute_downloads ? 'GOFF measurement with raw-data download opt-in' : 'Catalog-only dry run — no raw download'}</p>
            {run.conclusion && <p><b>Conclusion:</b> {run.conclusion}</p>}
            {run.notice && <p className="catalog-notice">{run.notice}</p>}
            {pollError && !runTerminal && <p className="action-hint" role="status">{pollError} Automatic status checks will retry.</p>}
            {run.github_run_url && <a className="known-place-run-link" href={run.github_run_url} target="_blank" rel="noreferrer">Open GitHub run and view the result bundle</a>}
            {runSucceeded && <p className="catalog-notice">Workflow succeeded. Inspect the measurement, uncertainty and reference-method reports in the run artifact; a completed run is not independent hazard-detection validation.</p>}
            {runFailed && <p className="catalog-error">Workflow ended with {run.conclusion || 'an error'}. Open the run link above to see the failing stage and safe error summary.</p>}
          </section>
        )}
        </section>
        <button type="button" className="workspace-nav-link known-place-back" onClick={onBack}>← Back to AOI map</button>
      </section>
    </main>
  );
}
