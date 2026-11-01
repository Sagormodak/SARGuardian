import type { User } from 'firebase/auth';

export type KnownPlaceHazardMode = 'landslide' | 'glacier_collapse' | 'ice_rock_avalanche' | 'mixed';
export type KnownPlaceAnalysisMode = 'exploratory' | 'retrospective_validation';
export type KnownPlaceRunState = 'dispatching' | 'queued' | 'in_progress' | 'completed';

export type KnownPlaceCandidateContext = {
  source: 'FIND_DISPLACEMENTS';
  candidate_id: string;
  product_type: 'GOFF';
  metric: string;
  evidence_class: string;
  status: string;
  support_pairs: number;
  pixel_count: number;
  approx_area_m2: number;
  product_ids: string[];
  pair_intervals: Array<Record<string, unknown>>;
  geometry_original_vertices: number;
  geometry_suggested_vertices: number;
  geometry_simplified: boolean;
  interpretation: string;
};

export type KnownPlaceAnalysisInput = {
  candidate_context?: KnownPlaceCandidateContext | null;
  /** Inner Measurement Polygon; the original map AOI is carried separately. */
  aoi_wkt: string;
  scope_aoi_wkt: string;
  start_date: string;
  end_date: string;
  hazard_mode: KnownPlaceHazardMode;
  analysis_mode: KnownPlaceAnalysisMode;
  polarization: 'HH' | 'HV' | 'VV' | 'VH';
  track: string;
  direction: 'ANY' | 'A' | 'D';
  coherence_neighbours: '1' | '5' | '10' | '15' | '20' | '25';
  allowed_release_ids: string;
  reference_wkt: string;
  geometry_height_m: number | null;
  execute_downloads: boolean;
  confirm_raw_downloads: boolean;
};

export type KnownPlaceAnalysisRun = {
  request_id: string;
  status: KnownPlaceRunState;
  github_run_id: string | null;
  github_run_url: string;
  conclusion: string | null;
  created_at: string | null;
  updated_at: string | null;
  execute_downloads: boolean | null;
  notice: string;
};

const configuredApiUrl = (import.meta.env.VITE_SARGUARDIAN_API_URL as string | undefined)?.trim();
const API_BASE = (configuredApiUrl || 'http://localhost:8000').replace(/\/+$/, '');

async function firebaseToken(user: Pick<User, 'getIdToken'> | null): Promise<string> {
  if (!user) throw new Error('Sign in before starting Known Place Analysis.');
  try {
    const token = await user.getIdToken();
    if (!token) throw new Error('empty token');
    return token;
  } catch {
    throw new Error('Could not obtain your sign-in token. Sign in again and retry.');
  }
}

async function readPayload<T>(response: Response, fallback: string): Promise<T> {
  const payload = await response.json().catch(() => ({})) as { detail?: string; message?: string };
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `${fallback} (${response.status}).`);
  }
  return payload as T;
}

export async function startKnownPlaceAnalysis(
  input: KnownPlaceAnalysisInput,
  user: Pick<User, 'getIdToken'> | null,
): Promise<KnownPlaceAnalysisRun> {
  const token = await firebaseToken(user);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/known-place-analysis`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(input),
      cache: 'no-store',
    });
  } catch {
    throw new Error('Could not reach the processing service. Check your connection and retry.');
  }
  return readPayload<KnownPlaceAnalysisRun>(response, 'Could not submit Known Place Analysis');
}

export async function getKnownPlaceAnalysisStatus(
  requestId: string,
  user: Pick<User, 'getIdToken'> | null,
): Promise<KnownPlaceAnalysisRun> {
  if (!/^[0-9a-f-]{36}$/i.test(requestId)) throw new Error('Invalid Known Place Analysis request ID.');
  const token = await firebaseToken(user);
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/known-place-analysis/requests/${encodeURIComponent(requestId)}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
  } catch {
    throw new Error('Could not reach the processing service to refresh the analysis status.');
  }
  return readPayload<KnownPlaceAnalysisRun>(response, 'Could not refresh Known Place Analysis status');
}
