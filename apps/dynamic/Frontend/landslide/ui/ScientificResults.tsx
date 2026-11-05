import { useState } from 'react';
import type { User } from 'firebase/auth';
import type { DisplacementJob } from '../../src/api/catalog';
import { downloadDisplacementArtifact } from '../../src/api/catalog';
import { buildDashboardRouteUrl, type DashboardView } from '../../src/dashboardDocument';

const dashboardViews: Array<{ id: DashboardView; title: string; audience: string; description: string }> = [
  {
    id: 'public',
    title: 'Public Discovery',
    audience: 'Communities and general users',
    description: 'A plain-language explanation of the observations, candidate evidence and limitations.',
  },
  {
    id: 'evidence',
    title: 'Explore the Evidence',
    audience: 'Analysts and decision teams',
    description: 'Interactive map layers, real acquisition pairs and observation playback.',
  },
  {
    id: 'science',
    title: 'Scientific Evidence',
    audience: 'Researchers and technical reviewers',
    description: 'Measurement diagnostics, quality gates, acquisition networks and provenance.',
  },
];

function dashboardAvailable(job: DisplacementJob): boolean {
  if (job.state !== 'succeeded' || !job.result_summary) return false;
  const dashboard = job.result_summary.web_dashboard;
  if (!dashboard || typeof dashboard !== 'object' || Array.isArray(dashboard)) return false;
  const record = dashboard as Record<string, unknown>;
  if (record.status !== 'PASS') return false;
  const artifacts = job.result_summary.artifacts;
  return Array.isArray(artifacts) && artifacts.some((item) =>
    !!item && typeof item === 'object' && !Array.isArray(item)
      && (item as Record<string, unknown>).path === 'aoi-derived-results.zip',
  );
}

function resultBundleArtifactIndex(job: DisplacementJob): number | undefined {
  if (job.state !== 'succeeded' || !job.result_summary) return undefined;
  const storage = job.result_summary.storage_verification;
  if (!storage || typeof storage !== 'object' || Array.isArray(storage)
      || (storage as Record<string, unknown>).status !== 'PASS') return undefined;
  const artifacts = job.result_summary.artifacts;
  if (!Array.isArray(artifacts)) return undefined;
  const index = artifacts.findIndex((item) =>
    !!item && typeof item === 'object' && !Array.isArray(item)
      && (item as Record<string, unknown>).path === 'aoi-derived-results.zip',
  );
  return index >= 0 ? index : undefined;
}

export function ScientificResults({ job, user }: { job: DisplacementJob; user: Pick<User, 'getIdToken'> }) {
  const bundleArtifactIndex = resultBundleArtifactIndex(job);
  const canDownloadBundle = bundleArtifactIndex !== undefined;
  const canOpenDashboard = dashboardAvailable(job);
  const [selectedView, setSelectedView] = useState<DashboardView>('public');
  const [dashboardError, setDashboardError] = useState('');
  const [downloadingBundle, setDownloadingBundle] = useState(false);
  const [bundleError, setBundleError] = useState('');
  const [bundleProgress, setBundleProgress] = useState('');

  function openDashboard(view: DashboardView) {
    setSelectedView(view);
    setDashboardError('');
    // Open a durable first-party route. The new tab restores Firebase auth,
    // retrieves the saved private bundle, and can recover after a refresh.
    const dashboardUrl = buildDashboardRouteUrl(window.location.origin, job.id, view);
    const dashboardTab = window.open(dashboardUrl, '_blank');
    if (!dashboardTab) {
      setDashboardError('The browser blocked the new tab. Allow pop-ups for SARGuardian and try again.');
      return;
    }
    try {
      dashboardTab.opener = null;
    } catch {
      // The route does not depend on its opener.
    }
  }

  async function downloadResultBundle() {
    if (bundleArtifactIndex === undefined) return;
    setBundleError('');
    setDownloadingBundle(true);
    try {
      // The Drive folder is intentionally private. Stream the retained ZIP via
      // the owner-authenticated API instead of sending the user to a private Drive URL.
      const blob = await downloadDisplacementArtifact(job.id, bundleArtifactIndex, user, setBundleProgress);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = `SARGuardian-${job.id}-aoi-derived-results.zip`;
      anchor.hidden = true;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    } catch (error: unknown) {
      setBundleError(error instanceof Error ? error.message : 'Could not download the archived result package.');
    } finally {
      setDownloadingBundle(false);
      setBundleProgress('');
    }
  }

  if (!canDownloadBundle && !canOpenDashboard) return null;
  return (
    <section className="scientific-results scientific-results-v2" aria-label="Scientific result outputs">
      {canOpenDashboard && (
        <div className="dashboard-selection">
          <div className="dashboard-selection-heading">
            <div>
              <span className="result-kicker">CHOOSE YOUR VIEW</span>
              <h3>How would you like to explore this result?</h3>
              <p>Open any view directly. All three use the same verified saved result bundle; only the presentation and level of detail change.</p>
            </div>
          </div>
          <div className="dashboard-view-options" role="group" aria-label="Dashboard audience view">
            {dashboardViews.map((view, index) => (
              <button
                className={`dashboard-view-option ${selectedView === view.id ? 'is-selected' : ''}`}
                type="button"
                key={view.id}
                aria-label={`Open ${view.title}`}
                aria-pressed={selectedView === view.id}
                onClick={() => void openDashboard(view.id)}
              >
                <span className="dashboard-option-number">0{index + 1}</span>
                <strong>{view.title}</strong>
                <small>{view.audience}</small>
                <span>{view.description}</span>
              </button>
            ))}
          </div>

        </div>
      )}
      {canDownloadBundle && (
        <div className="scientific-results-actions">
          <button
            className="investigate-button validated-output-link"
            type="button"
            onClick={() => void downloadResultBundle()}
            disabled={downloadingBundle}
          >
            {downloadingBundle ? 'Preparing secure download…' : 'Download complete result package'}
          </button>
        </div>
      )}
      {canDownloadBundle && (
        <p className="scientific-results-note">
          Results are kept in private storage and downloaded through your signed-in SARGuardian account.
          {job.retention_mode === 'derived-only'
            ? ' This package contains the retained AOI-derived products, maps and provenance; original full-granule HDF5 files are not retained in derived-only mode.'
            : ''}
        </p>
      )}
      {canDownloadBundle && !canOpenDashboard && (
        <p className="scientific-results-note" role="status">
          This job's result package is still retained and checksum-verified, but its interactive dashboard did not pass viewer validation. The three audience views are therefore unavailable for this run; the verified result package can still be downloaded.
        </p>
      )}
      {canOpenDashboard && <p className="scientific-results-note">A processing PASS confirms structural and provenance checks, not independent geophysical accuracy. Candidate patterns are not hazard confirmations; pairwise LOS is not automatically cumulative or 3-D movement.</p>}
      {bundleProgress && <p className="scientific-results-note" role="status">{bundleProgress}</p>}
      {bundleError && <p className="scientific-results-error" role="alert">{bundleError}</p>}
      {dashboardError && <p className="scientific-results-error" role="alert">{dashboardError}</p>}
    </section>
  );
}
