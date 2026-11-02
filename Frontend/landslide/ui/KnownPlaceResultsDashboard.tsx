import { useEffect, useMemo, useState } from 'react';
import type { User } from 'firebase/auth';
import {
  downloadKnownPlaceAnalysisBundle,
  getKnownPlaceAnalysisResults,
  type KnownPlaceAnalysisResults,
  type KnownPlacePairResult,
} from '../../src/api/knownPlace';
import './knownPlaceResults.css';

type AudienceView = 'public' | 'deep-dive' | 'scientific';
type TrackFilter = 'all' | '048-D' | '098-A';

const views: Array<{ id: AudienceView; title: string; audience: string; summary: string }> = [
  { id: 'public', title: 'Public Discovery', audience: 'For everyone', summary: 'What was measured, what needs caution, and what cannot be concluded.' },
  { id: 'deep-dive', title: 'Explore the Evidence', audience: 'Students and analysts', summary: 'Pair-by-pair observations, chain separation, map layers and quality support.' },
  { id: 'scientific', title: 'Scientific Evidence', audience: 'Researchers and reviewers', summary: 'Input geometry, source provenance, methods, claim gates and archived outputs.' },
];

function number(value: number | null | undefined, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'Not reported';
}

function percent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : 'Not reported';
}

function rate(pair: KnownPlacePairResult): number | null {
  const value = pair.median_horizontal_displacement_rate_m_per_day;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function trackLabel(pair: Pick<KnownPlacePairResult, 'track' | 'direction'>): string {
  const track = pair.track || 'Unknown';
  const direction = pair.direction === 'A' ? 'Ascending' : pair.direction === 'D' ? 'Descending' : 'Unknown direction';
  return `T${track} · ${direction}`;
}

function shortDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(parsed);
}

function intervalLabel(referenceDate: string, secondaryDate: string): string {
  return shortDate(referenceDate) + ' → ' + shortDate(secondaryDate);
}

function pairTitle(pair: KnownPlacePairResult): string {
  return intervalLabel(pair.reference_date, pair.secondary_date);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function supportLabel(pair: KnownPlacePairResult): string {
  if (pair.valid_aoi_pixels === null || pair.aoi_total_grid_cells === null) return 'Support not reported';
  return `${pair.valid_aoi_pixels}/${pair.aoi_total_grid_cells} valid cells`;
}

function flaggedCount(pairs: KnownPlacePairResult[]): number {
  return pairs.reduce((total, pair) => total + (pair.high_magnitude_flagged_pixels || 0), 0);
}

function downloadBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

export function KnownPlaceResultsDashboard({
  requestId,
  user,
}: {
  requestId: string;
  user: Pick<User, 'getIdToken'>;
}) {
  const [results, setResults] = useState<KnownPlaceAnalysisResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<AudienceView>('public');
  const [trackFilter, setTrackFilter] = useState<TrackFilter>('all');
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void getKnownPlaceAnalysisResults(requestId, user)
      .then((payload) => {
        if (active) setResults(payload);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : 'Could not retrieve the Known Place result bundle.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [requestId, user, attempt]);

  const result = results?.result;
  const allPairs = result?.pairs ?? [];
  const filteredPairs = useMemo(
    () => allPairs.filter((pair) => trackFilter === 'all' || `${pair.track}-${pair.direction}` === trackFilter),
    [allPairs, trackFilter],
  );
  const maximumRate = Math.max(0.1, ...allPairs.map((pair) => rate(pair) ?? 0));
  const peakPair = allPairs.reduce<KnownPlacePairResult | null>((best, pair) => {
    if (rate(pair) === null) return best;
    return !best || (rate(pair) ?? 0) > (rate(best) ?? 0) ? pair : best;
  }, null);
  const weakSupportPairs = allPairs.filter((pair) => (pair.valid_aoi_fraction ?? 0) < 0.3);
  const flaggedPairs = allPairs.filter((pair) => (pair.high_magnitude_flagged_pixels ?? 0) > 0);
  const rawRunUrl = results?.run.html_url;

  async function handleDownload(): Promise<void> {
    setDownloading(true);
    setDownloadError('');
    try {
      const blob = await downloadKnownPlaceAnalysisBundle(requestId, user);
      downloadBlob(blob, `SARGuardian-known-place-${requestId}.zip`);
    } catch (reason) {
      setDownloadError(reason instanceof Error ? reason.message : 'Could not download the Known Place result package.');
    } finally {
      setDownloading(false);
    }
  }

  return (
    <section className="known-place-results" aria-label="Known Place scientific results dashboard">
      <div className="known-place-results-heading">
        <div>
          <span className="result-kicker">MEASURED RESULT · GENERIC TWO-POLYGON ANALYSIS</span>
          <h2>What did the NISAR observations measure?</h2>
          <p>Three reading levels, one underlying result bundle. These views do not change or rerun the science workflow.</p>
        </div>
        {results && (
          <div className="known-place-result-actions">
            <a href={rawRunUrl} target="_blank" rel="noreferrer">Open GitHub run ↗</a>
            <button type="button" onClick={() => void handleDownload()} disabled={downloading}>
              {downloading ? 'Preparing package…' : 'Download result package'}
            </button>
          </div>
        )}
      </div>

      {loading && (
        <div className="known-place-results-message" role="status" aria-live="polite">
          <span className="known-place-results-spinner" />
          <strong>Retrieving and validating the saved measurement bundle…</strong>
          <p>No NISAR products are being downloaded again. This only reads the completed workflow artifact.</p>
        </div>
      )}
      {error && !loading && (
        <div className="known-place-results-message is-error" role="alert">
          <strong>Could not load the result dashboard</strong>
          <p>{error}</p>
          <button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry result retrieval</button>
        </div>
      )}
      {downloadError && <p className="known-place-results-error" role="alert">{downloadError}</p>}

      {results && result && !loading && (
        <>
          <div className="known-place-results-meta">
            <span><b>{result.pair_measurement_counts.metrics_computed}/{result.pair_measurement_counts.requested}</b> pair metrics computed</span>
            <span><b>{result.pairwise_series_plan.chain_count}</b> independent observation chains</span>
            <span><b>{result.request.date_range.start} – {result.request.date_range.end}</b> acquisition window</span>
            <span><b>{result.request.polarization}</b> polarization</span>
          </div>

          <nav className="known-place-audience-tabs" aria-label="Choose result detail level">
            {views.map((item) => (
              <button
                type="button"
                key={item.id}
                className={view === item.id ? 'is-active' : ''}
                aria-pressed={view === item.id}
                onClick={() => setView(item.id)}
              >
                <strong>{item.title}</strong>
                <small>{item.audience}</small>
              </button>
            ))}
          </nav>
          <p className="known-place-audience-description">{views.find((item) => item.id === view)?.summary}</p>

          {view === 'public' && (
            <div className="known-place-public-view">
              <div className="known-place-answer">
                <div>
                  <span className="result-kicker">DIRECT ANSWER</span>
                  <h3>Pairwise horizontal-displacement metrics were computed for every selected GOFF interval.</h3>
                  <p>
                    The selected area has observations from two separate satellite viewing geometries:
                    ascending track 098 and descending track 048. Their measurements are kept as separate
                    series, not added into one cumulative movement figure.
                  </p>
                </div>
                <div className="known-place-answer-status">
                  <span>Hazard determination</span>
                  <strong>Not evaluated</strong>
                  <small>This analysis measures offsets; it does not confirm a landslide or issue an alert.</small>
                </div>
              </div>

              <div className="known-place-public-stats">
                <article>
                  <span>Pairs with computed metrics</span>
                  <strong>{result.pair_measurement_counts.metrics_computed} of {result.pair_measurement_counts.requested}</strong>
                  <small>Structural status: {result.structural_status}</small>
                </article>
                <article>
                  <span>Separate observation chains</span>
                  <strong>{result.pairwise_series_plan.chain_count}</strong>
                  <small>Ascending and descending are not merged.</small>
                </article>
                <article>
                  <span>Pairs with high-magnitude flags</span>
                  <strong>{flaggedPairs.length} of {allPairs.length}</strong>
                  <small>{flaggedCount(allPairs)} pixel flags across the measured pairs.</small>
                </article>
                <article>
                  <span>Pairs with less than 30% valid support</span>
                  <strong>{weakSupportPairs.length}</strong>
                  <small>Low support makes their interval summary less representative.</small>
                </article>
              </div>

              <div className="known-place-chart-card">
                <div className="known-place-section-heading">
                  <div>
                    <span className="result-kicker">OBSERVED INTERVALS</span>
                    <h3>Median horizontal displacement rate</h3>
                  </div>
                  <span className="known-place-chart-unit">metres per day · interval average</span>
                </div>
                <p className="known-place-chart-note">
                  Each bar belongs to one acquisition pair. Bar lengths use a logarithmic visual scale so lower-rate intervals remain visible beside flagged high values.
                </p>
                <div className="known-place-rate-chart">
                  {allPairs.map((pair) => {
                    const value = rate(pair);
                    const barWidth = value === null ? 0 : Math.max(1, (Math.log1p(value) / Math.log1p(maximumRate)) * 100);
                    const caution = (pair.valid_aoi_fraction ?? 1) < 0.3 || (pair.high_magnitude_flagged_pixels ?? 0) > 0;
                    return (
                      <div className="known-place-rate-row" key={`${pair.chain_id}-${pair.reference_date}`}>
                        <div className="known-place-rate-label">
                          <strong>{pairTitle(pair)}</strong>
                          <small>{trackLabel(pair)}</small>
                        </div>
                        <div className="known-place-rate-track" role="img" aria-label={`${number(value, 3)} metres per day, ${supportLabel(pair)}`}>
                          <span className={caution ? 'is-caution' : ''} style={{ width: `${barWidth}%` }} />
                        </div>
                        <strong className="known-place-rate-value">{number(value, 3)}</strong>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="known-place-public-cautions">
                <span className="result-kicker">WHAT NEEDS CAREFUL REVIEW</span>
                {peakPair && (
                  <p>
                    The largest reported median rate is <b>{number(rate(peakPair), 2)} m/day</b> for {pairTitle(peakPair)}
                    {' '}({trackLabel(peakPair)}), but only {supportLabel(peakPair).toLowerCase()} support the AOI summary.
                    {' '}{peakPair.high_magnitude_flagged_pixels ?? 0} pixels were flagged by the configured magnitude review threshold.
                    Treat this as an outlier requiring review, not as a confirmed ground-motion speed.
                  </p>
                )}
                <p>
                  {weakSupportPairs.length} interval(s) have less than 30% valid AOI pixel support.
                  Pairwise rates summarize displacement across the acquisition interval; they are not continuous,
                  instantaneous or forecast velocities.
                </p>
                <p>
                  GOFF horizontal motion assumes zero vertical motion and does not measure 3-D displacement.
                  Reference-ground stability is not independently verified.
                </p>
              </div>
            </div>
          )}

          {view === 'deep-dive' && (
            <div className="known-place-deep-view">
              <div className="known-place-section-heading">
                <div>
                  <span className="result-kicker">INTERACTIVE SPATIAL EVIDENCE</span>
                  <h3>Explore the measured area</h3>
                  <p>Use the pair selector and layer controls in the generated map. The result map visualizes the archived per-pair raster outputs.</p>
                </div>
              </div>
              <div className="known-place-map-frame">
                <iframe
                  title="Interactive Known Place per-pair displacement map"
                  srcDoc={results.interactive_map_html}
                  sandbox="allow-scripts"
                  loading="lazy"
                  referrerPolicy="no-referrer"
                />
              </div>
              <div className="known-place-chain-grid">
                {result.pairwise_series_plan.chains.map((chain) => (
                  <article key={chain.chain_id}>
                    <span>{chain.direction === 'A' ? 'ASCENDING' : 'DESCENDING'} · TRACK {chain.track}</span>
                    <h4>{chain.pair_count} acquisition pairs</h4>
                    <p>{chain.release_id} · {chain.maturity} · {chain.polarization}</p>
                    <small>{chain.continuous_chain_eligible ? 'Contiguous within this track; cumulative output still requires separate review.' : 'Continuous chain eligibility not established.'}</small>
                  </article>
                ))}
              </div>

              <div className="known-place-pair-table-wrap">
                <div className="known-place-section-heading known-place-table-heading">
                  <div>
                    <span className="result-kicker">PAIRWISE MEASUREMENTS</span>
                    <h3>Compare acquisition intervals</h3>
                  </div>
                  <label>
                    <span>Observation chain</span>
                    <select value={trackFilter} onChange={(event) => setTrackFilter(event.target.value as TrackFilter)}>
                      <option value="all">All tracks</option>
                      <option value="048-D">Track 048 · Descending</option>
                      <option value="098-A">Track 098 · Ascending</option>
                    </select>
                  </label>
                </div>
                <div className="known-place-table-scroll">
                  <table>
                    <thead>
                      <tr><th>Acquisition pair</th><th>Median rate</th><th>Valid support</th><th>Flagged pixels</th><th>Coherence R</th><th>QC</th></tr>
                    </thead>
                    <tbody>
                      {filteredPairs.map((pair) => (
                        <tr key={`${pair.chain_id}-${pair.reference_date}`}>
                          <td><strong>{pairTitle(pair)}</strong><small>{trackLabel(pair)}</small></td>
                          <td>{number(rate(pair), 3)} m/day</td>
                          <td>{supportLabel(pair)} <small>({percent(pair.valid_aoi_fraction)})</small></td>
                          <td>{pair.high_magnitude_flagged_pixels ?? '—'}</td>
                          <td>{number(pair.median_directional_coherence_R, 3)}</td>
                          <td>
                            {(pair.crosses_registered_instrument_gap || (pair.valid_aoi_fraction ?? 1) < 0.3 || (pair.high_magnitude_flagged_pixels ?? 0) > 0)
                              ? <span className="known-place-qc-badge is-caution">Review</span>
                              : <span className="known-place-qc-badge">Measured</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {view === 'scientific' && (
            <div className="known-place-scientific-view">
              <div className="known-place-gate-grid">
                <article><span>Structural checks</span><strong>{result.structural_status}</strong><small>File and processing structure only; not geophysical validation.</small></article>
                <article><span>Measurement state</span><strong>{result.measurement_status}</strong><small>{result.pair_measurement_counts.metrics_computed} measured pair(s); {result.pair_measurement_counts.insufficient_data} insufficient-data pair(s).</small></article>
                <article><span>Paper reproduction</span><strong>{result.paper_reproduction_status}</strong><small>Generic AOI analysis is not the fixed author-exact benchmark.</small></article>
                <article><span>Hazard detection</span><strong>{result.hazard_detection_status}</strong><small>No calibrated hazard model or alert was evaluated.</small></article>
              </div>

              <div className="known-place-science-columns">
                <section>
                  <span className="result-kicker">REQUEST AND METHOD</span>
                  <h3>Processing configuration</h3>
                  <dl>
                    <dt>Date range (inclusive)</dt><dd>{result.request.date_range.start} – {result.request.date_range.end}</dd>
                    <dt>Input product</dt><dd>{result.request.source_adapters.join(', ')}</dd>
                    <dt>Release / maturity</dt><dd>{stringArray(result.request.product_selection.allowed_release_ids).join(', ') || 'Catalog selected'} · {stringArray(result.request.product_selection.allowed_maturities).join(', ') || 'Not reported'}</dd>
                    <dt>Polarization</dt><dd>{result.request.polarization}</dd>
                    <dt>Reference policy</dt><dd>{result.request.reference_policy}</dd>
                    <dt>Reference buffer</dt><dd>{number(result.request.reference_buffer_m, 0)} m</dd>
                    <dt>Height source</dt><dd>{String(result.request.geometry_policy.source || 'Not reported')}</dd>
                  </dl>
                  <pre>{JSON.stringify({
                    quality_policy: result.request.quality_policy,
                    coherence_policy: result.request.coherence_policy,
                  }, null, 2)}</pre>
                </section>
                <section>
                  <span className="result-kicker">SERIES INTEGRITY</span>
                  <h3>Orbit chains and time gaps</h3>
                  <p><b>{result.pairwise_series_plan.chain_count}</b> independent track/direction chains were generated. Cross-chain cumulative displacement is not computed.</p>
                  <p><b>{result.pairwise_series_plan.cumulative_displacement_status}</b></p>
                  <p>{result.pairwise_series_plan.pairwise_metrics_are_not_cumulative
                    ? 'Pairwise measurements are interval-specific; they are not a cumulative displacement series.'
                    : 'Review the source pair series before interpreting cumulative values.'}</p>
                  {result.pairwise_series_plan.chains.map((chain) => (
                    <div className="known-place-science-chain" key={chain.chain_id}>
                      <strong>{chain.chain_id}</strong>
                      <small>{chain.pair_count} pair(s) · grid compatible: {String(chain.grid_lattice_compatible)}</small>
                      {chain.pairs.filter((pair) => pair.crosses_registered_instrument_gap).map((pair) => (
                        <p key={pair.reference_date}><b>Instrument gap:</b> {intervalLabel(pair.reference_date, pair.secondary_date)}. {pair.interval_coverage_warning}</p>
                      ))}
                    </div>
                  ))}
                </section>
              </div>

              <div className="known-place-provenance">
                <div className="known-place-section-heading">
                  <div>
                    <span className="result-kicker">SOURCE PROVENANCE</span>
                    <h3>Granules and integrity hashes</h3>
                  </div>
                  <span>{result.source_evidence.length} source granules</span>
                </div>
                {result.source_evidence.map((source) => (
                  <details key={source.granule_name}>
                    <summary>{source.granule_name}</summary>
                    <p>{source.release_id} · {source.maturity} · {source.cache_status}</p>
                    <code>SHA-256: {source.source_sha256}</code>
                    <small>{(source.source_bytes / (1024 ** 3)).toFixed(2)} GiB source granule</small>
                  </details>
                ))}
              </div>

              <div className="known-place-limitations">
                <span className="result-kicker">SCIENTIFIC LIMITATIONS</span>
                <ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>

              <div className="known-place-storage-receipt">
                <span className="result-kicker">DERIVED-ONLY RETENTION</span>
                <strong>{results.storage.status} · {results.storage.remote_bytes_verified && results.storage.hash_verified ? 'Remote byte/hash verification passed' : 'Remote verification not confirmed'}</strong>
                <p>{results.storage.bundle_bytes ? `${(results.storage.bundle_bytes / 1024).toFixed(0)} KB archived` : 'Bundle size not reported'} · {results.storage.bundled_file_count ?? '—'} files · raw HDF5 included: {String(results.storage.raw_h5_included === true)}</p>
              </div>

              <details className="known-place-generated-report">
                <summary>Open generated science report (original workflow output)</summary>
                <iframe title="Generated Known Place science report" srcDoc={results.dashboard_html} sandbox="" loading="lazy" />
              </details>
            </div>
          )}
        </>
      )}
    </section>
  );
}
