import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { DashboardPage } from './DashboardPage';

describe('refresh-safe saved dashboard page', () => {
  const jobId = '736bd4e6-8963-43be-a916-bc62336c8557';

  it('waits for Firebase auth restoration before requesting a private saved dashboard', () => {
    const html = renderToStaticMarkup(
      <DashboardPage jobId={jobId} view="public" user={null} authState="loading" authError={null} onSignIn={vi.fn()} />,
    );
    expect(html).toContain('Restoring your account session');
    expect(html).toContain('Checking your existing SARGuardian sign-in');
  });

  it('offers sign-in without discarding the dashboard route when no session exists', () => {
    const html = renderToStaticMarkup(
      <DashboardPage jobId={jobId} view="science" user={null} authState="idle" authError={null} onSignIn={vi.fn()} />,
    );
    expect(html).toContain('Sign in to open this dashboard');
    expect(html).toContain('Back to Archive');
  });

  it('rejects an incomplete dashboard URL instead of falling back to Home', () => {
    const html = renderToStaticMarkup(
      <DashboardPage jobId="" view="public" user={null} authState="idle" authError={null} onSignIn={vi.fn()} />,
    );
    expect(html).toContain('Dashboard link is incomplete');
    expect(html).toContain('Back to Archive');
  });
});
