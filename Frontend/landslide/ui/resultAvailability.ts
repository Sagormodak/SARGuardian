import type { DisplacementJob } from '../../src/api/catalog';

export function hasScientificResultOutputs(job: DisplacementJob): boolean {
  if (job.state !== 'succeeded' || !job.result_summary) return false;

  const artifacts = job.result_summary.artifacts;
  if (!Array.isArray(artifacts)) return false;

  const hasResultBundle = artifacts.some((item) =>
    !!item && typeof item === 'object' && !Array.isArray(item)
      && (item as Record<string, unknown>).path === 'aoi-derived-results.zip',
  );
  if (!hasResultBundle) return false;

  const dashboard = job.result_summary.web_dashboard;
  const dashboardPass = !!dashboard && typeof dashboard === 'object' && !Array.isArray(dashboard)
    && (dashboard as Record<string, unknown>).status === 'PASS';

  const storage = job.result_summary.storage_verification;
  const storagePass = !!storage && typeof storage === 'object' && !Array.isArray(storage)
    && (storage as Record<string, unknown>).status === 'PASS';

  return dashboardPass || storagePass;
}
