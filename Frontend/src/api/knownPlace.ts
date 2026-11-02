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
  geometry_edited: boolean;
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

export type KnownPlacePaperReproductionInput = {
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

export async function startKnownPlacePaperReproduction(
  input: KnownPlacePaperReproductionInput,
  user: Pick<User, 'getIdToken'> | null,
): Promise<KnownPlaceAnalysisRun> {
  const token = await firebaseToken(user);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/known-place-paper-reproduction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(input),
      cache: 'no-store',
    });
  } catch {
    throw new Error('Could not reach the processing service. Check your connection and retry.');
  }
  return readPayload<KnownPlaceAnalysisRun>(response, 'Could not submit the author-exact paper reproduction');
}

export async function getKnownPlacePaperReproductionStatus(
  requestId: string,
  user: Pick<User, 'getIdToken'> | null,
): Promise<KnownPlaceAnalysisRun> {
  if (!/^[0-9a-f-]{36}$/i.test(requestId)) throw new Error('Invalid paper-reproduction request ID.');
  const token = await firebaseToken(user);
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/known-place-paper-reproduction/requests/${encodeURIComponent(requestId)}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
  } catch {
    throw new Error('Could not reach the processing service to refresh paper-reproduction status.');
  }
  return readPayload<KnownPlaceAnalysisRun>(response, 'Could not refresh paper-reproduction status');
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


export type KnownPlacePairResult = {
  reference_date: string;
  secondary_date: string;
  interval_days: number | null;
  chain_id: string;
  track: string | null;
  direction: string | null;
  polarization: string | null;
  release_id: string | null;
  catalog_maturity: string | null;
  status: string | null;
  valid_aoi_pixels: number | null;
  aoi_total_grid_cells: number | null;
  valid_aoi_fraction: number | null;
  high_magnitude_flagged_pixels: number | null;
  high_magnitude_flagged_fraction: number | null;
  high_magnitude_threshold_m: number | null;
  median_horizontal_displacement_rate_m_per_day: number | null;
  mean_vector_magnitude_rate_m_per_day: number | null;
  mean_vector_east_rate_m_per_day: number | null;
  mean_vector_north_rate_m_per_day: number | null;
  mean_vector_azimuth_deg_clockwise_from_north: number | null;
  median_directional_coherence_R: number | null;
  crosses_registered_instrument_gap: boolean;
  grid_lattice_compatible_with_previous: boolean | null;
  vector_rate_change_eligible: boolean;
  vector_rate_change_magnitude_m_per_day: number | null;
  vector_rate_acceleration_m_per_day_squared: number | null;
  rate_change_block_reason: string | null;
  spatial_uncertainty_status: string | null;
  risk_score: number | null;
  risk_score_status: string;
  detection_status: string;
  quality_gate_counts: Record<string, number> | null;
  interval_coverage_warning: string | null;
};

export type KnownPlaceChain = {
  chain_id: string;
  track: string | null;
  direction: string | null;
  polarization: string | null;
  release_id: string | null;
  maturity: string | null;
  pair_count: number | null;
  continuous_chain_eligible: boolean | null;
  cumulative_displacement_status: string | null;
  grid_lattice_compatible: boolean | null;
  pairs: Array<{
    reference_date: string;
    secondary_date: string;
    interval_days: number | null;
    relation_to_previous: string | null;
    crosses_registered_instrument_gap: boolean;
    gap_count: number;
    interval_coverage_warning: string | null;
  }>;
};

export type KnownPlaceAnalysisResults = {
  request_id: string;
  run: {
    id: number;
    status: string;
    conclusion: string;
    html_url: string;
    created_at: string | null;
    updated_at: string | null;
    head_sha: string | null;
  };
  result: {
    schema_version: string;
    engine_version: string;
    created_at_utc: string;
    status: string;
    structural_status: string;
    measurement_status: string;
    paper_reproduction_status: string;
    hazard_detection_status: string;
    pair_measurement_counts: { requested: number; metrics_computed: number; insufficient_data: number };
    grid_compatibility_status: string;
    grid_mismatch_pair_count: number;
    motion_dynamics: {
      status: string;
      measured_feature_count: number;
      unmeasured_feature_count: number;
      risk_score: number | null;
      hazard_detection_status: string;
      interpretation: string;
      limitations: string[];
    };
    pairwise_series_plan: {
      status: string;
      chain_count: number;
      continuous_chain_eligible: boolean;
      cumulative_displacement_status: string;
      pair_count: number;
      pairwise_metrics_are_not_cumulative: boolean;
      warnings: string[];
      known_nisar_data_gaps_intersecting_requested_pairs: unknown;
      chains: KnownPlaceChain[];
    };
    pairs: KnownPlacePairResult[];
    request: {
      measurement_wkt: string | null;
      outer_scope_wkt: string | null;
      reference_wkt: string | null;
      date_range: { start: string; end: string; inclusive?: boolean; timezone?: string };
      hazard_mode: string;
      analysis_mode: string;
      source_adapters: string[];
      polarization: string;
      product_selection: Record<string, unknown>;
      geometry_policy: Record<string, unknown>;
      quality_policy: Record<string, unknown>;
      coherence_policy: Record<string, unknown>;
      reference_policy: string;
      reference_buffer_m: number | null;
    };
    source_evidence: Array<{
      granule_name: string;
      release_id: string;
      maturity: string;
      source_sha256: string;
      source_bytes: number;
      cache_status: string;
    }>;
    limitations: string[];
    output_files: Array<string | Record<string, unknown>>;
  };
  storage: {
    status: string;
    action?: string;
    bundle_bytes?: number;
    remote_bytes_verified: boolean;
    hash_verified: boolean;
    raw_h5_included?: boolean;
    bundled_file_count?: number | null;
  };
  dashboard_html: string;
  interactive_map_html: string;
};

export async function getKnownPlaceAnalysisResults(
  requestId: string,
  user: Pick<User, 'getIdToken'> | null,
): Promise<KnownPlaceAnalysisResults> {
  if (!/^[0-9a-f-]{36}$/i.test(requestId)) throw new Error('Invalid Known Place request ID.');
  const token = await firebaseToken(user);
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/known-place-analysis/requests/${encodeURIComponent(requestId)}/results`,
      { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
  } catch {
    throw new Error('Could not reach the processing service to retrieve the Known Place result.');
  }
  return readPayload<KnownPlaceAnalysisResults>(response, 'Could not retrieve the Known Place result');
}

export async function downloadKnownPlaceAnalysisBundle(
  requestId: string,
  user: Pick<User, 'getIdToken'> | null,
): Promise<Blob> {
  if (!/^[0-9a-f-]{36}$/i.test(requestId)) throw new Error('Invalid Known Place request ID.');
  const token = await firebaseToken(user);
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/known-place-analysis/requests/${encodeURIComponent(requestId)}/bundle`,
      { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' },
    );
  } catch {
    throw new Error('Could not reach the processing service to download the Known Place result package.');
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string; message?: string };
    throw new Error(payload.detail || payload.message || `Could not download the Known Place result package (${response.status}).`);
  }
  return response.blob();
}
