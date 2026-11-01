import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { DisplacementJobStatus, DisplacementPreparation, JOB_STATUS_POLL_MS } from '../ui/DisplacementPreparation';
import { chooseAccountJob } from '../engine/displacementJobSelection';
import { ScientificResults } from '../ui/ScientificResults';
import { ArchiveJobCard } from '../../src/components/ArchiveSection';
import { countCatalogGranules, ELAPSED_TICK_MS, formatElapsed } from '../ui/processingStatus';
import { prepareInvestigation } from '../engine/investigation';
import { isDashboardRoute, isLandslideDisplacementRoute, LANDSLIDE_DISPLACEMENT_PATH, LANDSLIDE_PATH, LANDSLIDE_RESULTS_PATH, navigatePath } from '../../src/routing';
import { DEFAULT_DISPLACEMENT_OPTIONS } from '../../src/api/catalog';
import { buildDashboardRouteUrl, withDashboardPreferredView } from '../../src/dashboardDocument';

describe('dashboard opens in a new same-origin tab', () => {
  it('offers the new-tab dashboard action only for a verified successful result', () => {
    const job = {
      id: '736bd4e6-8963-43be-a916-bc62336c8557',
      state: 'succeeded',
      result_summary: {
        web_dashboard: { status: 'PASS' },
        artifacts: [{ path: 'aoi-derived-results.zip' }],
      },
    } as never;
    const html = renderToStaticMarkup(<ScientificResults job={job} user={{ getIdToken: vi.fn() } as never} />);
    expect(html).toContain('How would you like to explore this result?');
    expect(html).toContain('Public Discovery');
    expect(html).toContain('Explore the Evidence');
    expect(html).toContain('Scientific Evidence');
    expect(html).not.toContain('Load dashboard in Processing');
    expect(html).toContain('aria-label="Open Public Discovery"');
    expect(html).toContain('aria-label="Open Explore the Evidence"');
    expect(html).toContain('aria-label="Open Scientific Evidence"');
    expect(html).not.toContain('Open Public Discovery</button></div>');
    expect(html).not.toContain('<iframe');
  });
});


describe('saved result viewer readiness', () => {
  it('distinguishes a retained downloadable bundle from a dashboard that never passed validation', () => {
    const job = {
      id: '736bd4e6-8963-43be-a916-bc62336c8557',
      state: 'succeeded',
      retention_mode: 'derived-only',
      result_summary: {
        web_dashboard: { status: 'NOT_AVAILABLE' },
        storage_verification: { status: 'PASS' },
        artifacts: [{ path: 'aoi-derived-results.zip' }],
      },
    } as never;
    const html = renderToStaticMarkup(<ScientificResults job={job} user={{ getIdToken: vi.fn() } as never} />);
    expect(html).toContain('result package is still retained and checksum-verified');
    expect(html).toContain('interactive dashboard did not pass viewer validation');
    expect(html).toContain('Download complete result package');
    expect(html).not.toContain('Public Discovery');
  });
});

describe('archive result disclosure layout', () => {
  it('keeps each archived result selector collapsed until the user opens that job', () => {
    const job = {
      id: 'archive-job-1234',
      state: 'succeeded',
      stage: 'completed',
      place_name: 'Bhote Koshi AOI',
      start_date: '2026-07-07',
      end_date: '2026-09-12',
      updated_at: '2026-09-13T10:00:00Z',
      result_summary: {
        web_dashboard: { status: 'PASS' },
        storage_verification: { status: 'PASS', remote_folder_id: 'private-drive-folder-123' },
        artifacts: [{ path: 'aoi-derived-results.zip' }],
      },
    } as never;

    const html = renderToStaticMarkup(
      <ArchiveJobCard job={job} user={{ getIdToken: vi.fn() } as never} onOpenWorkspace={() => {}} />,
    );

    expect(html).toContain('<details class="archive-item-results">');
    expect(html).not.toContain('<details class="archive-item-results" open');
    expect(html).toContain('Explore saved results');
    expect(html).toContain('How would you like to explore this result?');
    expect(html).toContain('Download complete result package');
    expect(html).not.toContain('Open verified Drive archive');
    expect(html).not.toContain('https://drive.google.com/drive/folders/');
    expect(html).not.toContain('private-drive-folder-123');
  });
});

describe('refresh-safe saved dashboard route', () => {
  it('opens a durable dashboard URL containing the saved job and selected audience view', () => {
    const url = new URL(buildDashboardRouteUrl(
      'https://sar-guardian-dynamic-lilac.vercel.app/archive',
      '736bd4e6-8963-43be-a916-bc62336c8557',
      'evidence',
    ));
    expect(url.origin).toBe('https://sar-guardian-dynamic-lilac.vercel.app');
    expect(url.pathname).toBe('/dashboard');
    expect(url.searchParams.get('jobId')).toBe('736bd4e6-8963-43be-a916-bc62336c8557');
    expect(url.searchParams.get('view')).toBe('evidence');
    expect(isDashboardRoute(url.pathname)).toBe(true);
  });

  it('pins relative dashboard assets and the Maps referrer to the first-party origin', () => {
    const html = '<!doctype html><html><head><title>Dashboard</title></head><body><main>Evidence</main></body></html>';
    const prepared = withDashboardPreferredView(html, 'science', 'https://sar-guardian-dynamic-lilac.vercel.app/archive');
    expect(prepared).toContain('<base href="https://sar-guardian-dynamic-lilac.vercel.app/">');
    expect(prepared).toContain('<meta name="referrer" content="origin">');
    expect(prepared).toContain("var preferredView = \"science\";");
    expect(prepared).toContain("data-sg-mode");
  });
});

describe('displacement preparation route', () => {
  const user = { getIdToken: vi.fn() } as never;
  it('keeps the AOI payload out of the processing screen', () => {
    const preparation = prepareInvestigation({ coordinates: [[85, 27], [85.001, 27], [85, 27.001]], areaClosed: true, startDate: '2026-10-01', endDate: '2026-10-22', today: '2026-10-23' });
    const html = renderToStaticMarkup(<DisplacementPreparation preparation={preparation} onBack={() => {}} user={user} />);
    expect(html).not.toContain('POLYGON');
    expect(html).not.toContain('Copy WKT');
    expect(html).not.toContain('Copy Payload');
    expect(html).not.toContain('Start displacement processing');
    expect(html).not.toContain('Back to map');
  });
  it('does not render a second submission screen on an empty/direct visit', () => {
    const html = renderToStaticMarkup(<DisplacementPreparation preparation={{ valid: false, errors: ['Select an AOI.'] }} onBack={() => {}} user={user} />);
    expect(html).toBe('');
    expect(html).not.toContain('POLYGON');
    expect(html).not.toContain('Copy Payload');
  });
  it('does not reuse a completed displacement result for another selected place or target', () => {
    const coordinates = [[85, 27], [85.001, 27], [85, 27.001]] as const;
    const preparation = prepareInvestigation({
      coordinates: [...coordinates], areaClosed: true, startDate: '2026-10-01',
      endDate: '2026-10-22', today: '2026-10-23',
      place: { name: 'Test location', latitude: 27.0002, longitude: 85.0002 },
    });
    expect(preparation.valid).toBe(true);
    if (!preparation.valid) return;
    const base = {
      state: 'succeeded', stage: 'completed', aoi_wkt: preparation.payload.aoi_wkt,
      start_date: '2026-10-01', end_date: '2026-10-22',
      product_type: 'BOTH', acquisition_window: 'secondary-acquisition-in-window',
      retention_mode: 'derived-only', processing_profile: 'full-aoi',
      created_at: '2026-10-23T10:00:00Z', updated_at: '2026-10-23T10:10:00Z',
    };
    const oldPlace = {
      ...base, id: 'old-place-job', place_name: 'Nearby village',
      place_latitude: 27.0003, place_longitude: 85.0003,
      target_latitude: 27.0003, target_longitude: 85.0003,
    };
    const matching = {
      ...base, id: 'matching-place-job', place_name: 'Test location',
      place_latitude: 27.0002, place_longitude: 85.0002,
      target_latitude: 27.0002, target_longitude: 85.0002,
    };
    const options = DEFAULT_DISPLACEMENT_OPTIONS;
    expect(chooseAccountJob([oldPlace, matching] as never, preparation, options)?.id).toBe('matching-place-job');
    expect(chooseAccountJob([oldPlace] as never, preparation, options)).toBeNull();
  });

  it('uses existing navigation for both workflows and back, suppressing duplicate pushes', () => {
    const push = vi.fn();
    let path = navigatePath(LANDSLIDE_RESULTS_PATH, LANDSLIDE_PATH, push);
    expect(path).toBe('/landslide/results');
    path = navigatePath(LANDSLIDE_PATH, path, push);
    path = navigatePath(LANDSLIDE_DISPLACEMENT_PATH, path, push);
    expect(isLandslideDisplacementRoute(path)).toBe(true);
    navigatePath(path, path, push);
    expect(push).toHaveBeenCalledTimes(3);
    expect(navigatePath(LANDSLIDE_PATH, path, push)).toBe('/landslide');
  });
  it('does not expose a second submission control on the task status route', () => {
    const preparation = prepareInvestigation({ coordinates: [[85, 27], [85.001, 27], [85, 27.001]], areaClosed: true, startDate: '2026-10-01', endDate: '2026-10-22', today: '2026-10-23' });
    const html = renderToStaticMarkup(<DisplacementPreparation preparation={preparation} onBack={() => {}} user={user} />);
    expect(html).not.toContain('Start displacement processing');
    expect(html).not.toContain('Preparing displacement job');
  });
  it('keeps a one-second age tick and renders failed recovery actions with granule counts', () => {
    expect(ELAPSED_TICK_MS).toBe(1000);
    expect(JOB_STATUS_POLL_MS).toBe(2000);
    expect(DEFAULT_DISPLACEMENT_OPTIONS).toEqual({
      product_type: 'BOTH', acquisition_window: 'secondary-acquisition-in-window',
      retention_mode: 'derived-only', processing_profile: 'full-aoi',
    });
    expect(formatElapsed('2026-10-24T10:00:00Z', '2026-10-24T10:00:02Z', 'running', Date.parse('2026-10-24T10:00:03Z'))).toBe('0m 3s');
    expect(countCatalogGranules([
      { product_type: 'GUNW' }, { product_type: 'GOFF' }, { product_type: 'GUNW' },
    ] as never)).toEqual({ GUNW: 2, GOFF: 1, source: 'catalog-preflight' });
    const failedJob = {
      id: 'failed-job', state: 'failed', stage: 'failed', aoi_wkt: 'POLYGON((85 27, 85.01 27, 85 27.01, 85 27))',
      start_date: '2026-09-27', end_date: '2026-10-24', created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:01:05Z',
      error_message: 'Worker failed.',
    } as const;
    const html = renderToStaticMarkup(<DisplacementJobStatus job={failedJob} pendingAction={null} clock={Date.parse('2026-10-24T10:02:00Z')}
      granuleCounts={{ GUNW: 4, GOFF: 3, source: 'catalog-preflight' }} onCancel={() => {}} onRefresh={() => {}}
      onRetry={() => {}} onBack={() => {}} />);
    expect(html).toContain('Age:');
    expect(html).toContain('1m 5s');
    expect(html).toContain('GUNW granules');
    expect(html).toContain('>4<');
    expect(html).toContain('GOFF granules');
    expect(html).toContain('>3<');
    expect(html).toContain('Retry task');
    expect(html).toContain('Go to map');
    expect(html).toContain('Selected place:');
    expect(html).toContain('Measurement target:');
    expect(html).toContain('Not supplied inside the submitted AOI');
    expect(html).not.toContain('Start displacement processing');

    const targetedJob = {
      ...failedJob, place_name: 'Rasuwa foothill', place_latitude: 27.01, place_longitude: 85.01,
      target_latitude: 27.01, target_longitude: 85.01,
    } as const;
    const targetedHtml = renderToStaticMarkup(<DisplacementJobStatus job={targetedJob as never} pendingAction={null}
      clock={Date.parse('2026-10-24T10:02:00Z')} granuleCounts={null} onCancel={() => {}} onRefresh={() => {}}
      onRetry={() => {}} onBack={() => {}} />);
    expect(targetedHtml).toContain('Rasuwa foothill');
    expect(targetedHtml).toContain('27.01000, 85.01000');
    expect(targetedHtml).toContain('not a stable-ground reference');

    const runningWithWorkerCounts = { ...failedJob, state: 'running', stage: 'products_discovered',
      github_run_url: 'https://github.com/shourov-04/SARGuardian_Dynamic/actions/runs/123', result_summary: {
      catalog_granule_counts: { GUNW: 8, GOFF: 5 }, selected_granule_counts: { GUNW: 1, GOFF: 1 },
    } } as const;
    const runningHtml = renderToStaticMarkup(<DisplacementJobStatus job={runningWithWorkerCounts as never} pendingAction={null}
      clock={Date.parse('2026-10-24T10:02:00Z')} granuleCounts={null} onCancel={() => {}} onRefresh={() => {}}
      onRetry={() => {}} onBack={() => {}} />);
    expect(runningHtml).toContain('>8<');
    expect(runningHtml).toContain('>5<');
    expect(runningHtml).toContain('Worker discovery');
    expect(runningHtml).toContain('Refresh task');
    expect(runningHtml).not.toContain('View worker logs');
    expect(runningHtml).not.toContain('https://github.com/shourov-04/SARGuardian_Dynamic/actions/runs/123');

    const refreshingHtml = renderToStaticMarkup(<DisplacementJobStatus job={runningWithWorkerCounts as never} pendingAction="refresh"
      clock={Date.parse('2026-10-24T10:02:00Z')} granuleCounts={null} onCancel={() => {}} onRefresh={() => {}}
      onRetry={() => {}} onBack={() => {}} />);
    expect(refreshingHtml).toContain('Refreshing…');
    expect(refreshingHtml).toContain('Cancel task');
    expect(refreshingHtml).not.toContain('Cancelling…');
  });

  it('shows a secure authenticated result-package download after successful processing', () => {
    const succeededJob = {
      id: 'succeeded-job', state: 'succeeded', stage: 'completed', retention_mode: 'derived-only',
      aoi_wkt: 'POLYGON((85 27, 85.01 27, 85 27.01, 85 27))',
      start_date: '2026-09-27', end_date: '2026-10-24',
      created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:10:00Z',
      result_summary: {
        storage_verification: { status: 'PASS', remote_folder_id: 'private-drive-folder-123' },
        diagnostics: { pixel_stack: { status: 'PASS' } },
        products: [{ product_type: 'GUNW' }],
        artifacts: [{ path: 'aoi-derived-results.zip' }],
      },
    } as const;

    const html = renderToStaticMarkup(<ScientificResults job={succeededJob as never} />);

    expect(html).toContain('Download complete result package');
    expect(html).toContain('downloaded through your signed-in SARGuardian account');
    expect(html).toContain('original full-granule HDF5 files are not retained in derived-only mode');
    expect(html).not.toContain('https://drive.google.com/drive/folders/');
    expect(html).not.toContain('private-drive-folder-123');
    expect(html).not.toContain('Scientific diagnostics');
    expect(html).not.toContain('Input products');
    expect(html).not.toContain('Retained scientific outputs');
  });
});
