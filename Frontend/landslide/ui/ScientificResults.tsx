import { useState } from 'react';
import type { User } from 'firebase/auth';
import type { DisplacementJob } from '../../src/api/catalog';
import { downloadDisplacementArtifact, getInteractiveDashboardHtml } from '../../src/api/catalog';
import { waitForDashboardPopupLoad, writeDashboardHtml } from './dashboardPopup';

type DashboardView = 'public' | 'evidence' | 'science';

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

function dashboardHtmlWithPreferredView(html: string, view: DashboardView): string {
  const script = `<script id="sarguardian-preferred-dashboard-view">
(function () {
  var preferredView = ${JSON.stringify(view)};
  function selectPreferredView() {
    var button = document.querySelector('[data-sg-mode="' + preferredView + '"]');
    if (!button) return false;
    if (button.getAttribute('aria-selected') !== 'true') button.click();
    return true;
  }
  function start() {
    if (selectPreferredView()) return;
    var observer = new MutationObserver(function () {
      if (selectPreferredView()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    window.setTimeout(function () { observer.disconnect(); }, 5000);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
</script>`;
  return /<\/body>/i.test(html) ? html.replace(/<\/body>/i, `${script}</body>`) : `${html}${script}`;
}

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

export function hasScientificResultOutputs(job: DisplacementJob): boolean {
  return dashboardAvailable(job) || resultBundleArtifactIndex(job) !== undefined;
}

export function ScientificResults({ job, user }: { job: DisplacementJob; user: Pick<User, 'getIdToken'> }) {
  const bundleArtifactIndex = resultBundleArtifactIndex(job);
  const canDownloadBundle = bundleArtifactIndex !== undefined;
  const canOpenDashboard = dashboardAvailable(job);
  const [opening, setOpening] = useState(false);
  const [selectedView, setSelectedView] = useState<DashboardView>('public');
  const [dashboardError, setDashboardError] = useState('');
  const [downloadingBundle, setDownloadingBundle] = useState(false);
  const [bundleError, setBundleError] = useState('');

  async function openDashboard() {
    setDashboardError('');
    // Open a real HTTPS URL on the AOI workspace origin, not about:blank.
    // This gives Google's browser-key referrer restrictions a stable site URL.
    const popupUrl = new URL('/', window.location.origin).toString();
    const popup = window.open(popupUrl, '_blank');
    if (!popup) {
      setDashboardError('The browser blocked the new tab. Allow pop-ups for SARGuardian and try again.');
      return;
    }

    try {
      popup.opener = null;
    } catch {
      // Continue safely if browser policy prevents updating opener.
    }

    setOpening(true);
    let popupReady = false;
    try {
      await waitForDashboardPopupLoad(popup, window.location.origin);
      popupReady = true;
      popup.document.title = 'SARGuardian · Interactive dashboard';
      popup.document.body.textContent = 'Verifying the private result bundle and preparing the selected dashboard view…';
      const html = await getInteractiveDashboardHtml(job.id, user);
      writeDashboardHtml(popup, dashboardHtmlWithPreferredView(html, selectedView));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Could not open the interactive dashboard.';
      setDashboardError(message);
      if (popupReady) {
        try {
          popup.document.open();
          popup.document.write('<!doctype html><html lang="en"><meta charset="utf-8"><title>SARGuardian dashboard unavailable</title><body style="font:16px system-ui;padding:24px"><h1>Dashboard unavailable</h1><p id="message"></p></body></html>');
          const messageNode = popup.document.getElementById('message');
          if (messageNode) messageNode.textContent = message;
          popup.document.close();
        } catch {
          // The in-app status below still reports the failure when the popup is not writable.
        }
      }
    } finally {
      setOpening(false);
    }
  }

  async function downloadResultBundle() {
    if (bundleArtifactIndex === undefined) return;
    setBundleError('');
    setDownloadingBundle(true);
    try {
      // The Drive folder is intentionally private. Stream the retained ZIP via
      // the owner-authenticated API instead of sending the user to a private Drive URL.
      const blob = await downloadDisplacementArtifact(job.id, bundleArtifactIndex, user);
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
              <p>All three views use the same verified result bundle. Only the presentation and level of detail change.</p>
            </div>
          </div>
          <div className="dashboard-view-options" role="group" aria-label="Dashboard audience view">
            {dashboardViews.map((view, index) => (
              <button
                className={`dashboard-view-option ${selectedView === view.id ? 'is-selected' : ''}`}
                type="button"
                key={view.id}
                aria-pressed={selectedView === view.id}
                onClick={() => setSelectedView(view.id)}
              >
                <span className="dashboard-option-number">0{index + 1}</span>
                <strong>{view.title}</strong>
                <small>{view.audience}</small>
                <span>{view.description}</span>
              </button>
            ))}
          </div>
          <div className="dashboard-selection-actions">
            <button className="investigate-button validated-output-link" type="button" onClick={() => void openDashboard()} disabled={opening}>
              {opening ? 'Opening selected view…' : `Open ${dashboardViews.find((view) => view.id === selectedView)?.title ?? 'dashboard'}`}
            </button>
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
      {canOpenDashboard && <p className="scientific-results-note">A processing PASS confirms structural and provenance checks, not independent geophysical accuracy. Candidate patterns are not hazard confirmations; pairwise LOS is not automatically cumulative or 3-D movement.</p>}
      {bundleError && <p className="scientific-results-error" role="alert">{bundleError}</p>}
      {dashboardError && <p className="scientific-results-error" role="alert">{dashboardError}</p>}
    </section>
  );
}
