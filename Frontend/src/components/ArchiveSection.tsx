import { useEffect, useState } from 'react';
import type { User } from 'firebase/auth';
import { listDisplacementJobs, type DisplacementJob } from '../api/catalog';
import { ScientificResults, hasScientificResultOutputs } from '../../landslide/ui/ScientificResults';

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Date not available'
    : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}


export function ArchiveJobCard({ job, user, onOpenWorkspace }: {
  job: DisplacementJob;
  user: User;
  onOpenWorkspace: () => void;
}) {
  const isActive = ['queued', 'dispatching', 'running'].includes(job.state);
  const hasResults = job.state === 'succeeded' && hasScientificResultOutputs(job);

  return (
    <article className="archive-item">
      <div className="archive-item-main">
        <div className="archive-item-topline">
          <span className={`archive-state archive-state-${job.state}`}>{job.state.replace(/_/g, ' ')}</span>
          <span className="archive-job-id">Job {job.id.slice(0, 8)}</span>
        </div>
        <h3>{job.place_name || 'AOI-wide displacement analysis'}</h3>
        <p>{formatDate(job.start_date)} – {formatDate(job.end_date)}</p>
        <small>Updated {formatDate(job.updated_at)} · {job.stage}</small>
      </div>
      <div className="archive-item-actions">
        {isActive && (
          <button className="section-action secondary" type="button" onClick={onOpenWorkspace}>Open processing</button>
        )}
        {hasResults && <span className="archive-result-ready">Verified outputs ready</span>}
        {job.state === 'succeeded' && !hasResults && (
          <span className="archive-result-unavailable">No verified result bundle</span>
        )}
      </div>
      {hasResults && (
        <details className="archive-item-results">
          <summary className="archive-results-summary">
            <span className="archive-results-summary-copy">
              <strong>Explore saved results</strong>
              <small>Choose a presentation view or download the complete result package.</small>
            </span>
            <span className="archive-results-chevron" aria-hidden="true">⌄</span>
          </summary>
          <div className="archive-item-results-content">
            <ScientificResults job={job} user={user} />
          </div>
        </details>
      )}
    </article>
  );
}

export function ArchiveSection({ user, onSignIn, onOpenWorkspace }: {
  user: User | null;
  onSignIn: () => void;
  onOpenWorkspace: () => void;
}) {
  const [jobs, setJobs] = useState<DisplacementJob[]>([]);
  const [state, setState] = useState<'signed-out' | 'loading' | 'ready' | 'error'>(
    user ? 'loading' : 'signed-out',
  );
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    if (!user) {
      setJobs([]);
      setState('signed-out');
      setError('');
      return () => { active = false; };
    }

    setState('loading');
    setError('');
    void listDisplacementJobs(user)
      .then((items) => {
        if (!active) return;
        setJobs([...items].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)));
        setState('ready');
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : 'The account archive could not be loaded.');
        setState('error');
      });

    return () => { active = false; };
  }, [user]);

  return (
    <section className="home-section archive-section" aria-labelledby="archive-title">
      <div className="home-section-heading">
        <div>
          <p className="section-eyebrow">YOUR WORKSPACE</p>
          <h2 id="archive-title">Analysis archive</h2>
          <p>Previous tasks are loaded from your signed-in account. No sample jobs are inserted into this list.</p>
        </div>
        {user && <button className="text-link-button" type="button" onClick={onOpenWorkspace}>Open analysis workspace</button>}
      </div>

      {state === 'signed-out' && (
        <div className="archive-empty">
          <strong>Sign in to view your analysis history.</strong>
          <p>Only jobs belonging to your account are shown here.</p>
          <button className="section-action" type="button" onClick={onSignIn}>Sign in</button>
        </div>
      )}
      {state === 'loading' && <p className="section-status" role="status">Loading account analysis history…</p>}
      {state === 'error' && (
        <div className="archive-empty" role="alert">
          <strong>Archive unavailable</strong>
          <p>{error}</p>
        </div>
      )}
      {state === 'ready' && jobs.length === 0 && (
        <div className="archive-empty">
          <strong>No analysis jobs in this account yet.</strong>
          <p>When you submit a processing task, its current status and verified outputs will appear here.</p>
          <button className="section-action" type="button" onClick={onOpenWorkspace}>Start an analysis</button>
        </div>
      )}
      {state === 'ready' && jobs.length > 0 && (
        <div className="archive-list">
          {jobs.slice(0, 5).map((job) => (
            <ArchiveJobCard key={job.id} job={job} user={user!} onOpenWorkspace={onOpenWorkspace} />
          ))}
        </div>
      )}
    </section>
  );
}
