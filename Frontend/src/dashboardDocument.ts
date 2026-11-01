export type DashboardView = 'public' | 'evidence' | 'science';

const dashboardViews = new Set<DashboardView>(['public', 'evidence', 'science']);

export function parseDashboardView(value: string | null | undefined): DashboardView {
  return dashboardViews.has(value as DashboardView) ? value as DashboardView : 'public';
}

export function buildDashboardRouteUrl(origin: string, jobId: string, view: DashboardView): string {
  const url = new URL('/dashboard', origin);
  url.searchParams.set('jobId', jobId);
  url.searchParams.set('view', view);
  return url.toString();
}

/**
 * Keep the dashboard on a first-party, refreshable URL while preserving
 * relative asset resolution and the Google Maps website-key referrer.
 */
export function withDashboardPreferredView(html: string, view: DashboardView, origin: string): string {
  const safeOrigin = new URL(origin).origin;
  const headPattern = /<head\b[^>]*>/i;
  const headMatch = html.match(headPattern);
  if (!headMatch) throw new Error('The saved dashboard document has no HTML head section.');

  const withoutExistingBase = html.replace(/<base\b[^>]*>/gi, '');
  const withBrowserContext = withoutExistingBase.replace(
    headPattern,
    \`\${headMatch[0]}<base href="\${safeOrigin}/"><meta name="referrer" content="origin">\`,
  );
  const script = \`<script id="sarguardian-preferred-dashboard-view">
(function () {
  var preferredView = \${JSON.stringify(view)};
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
</script>\`;
  return /<\\/body>/i.test(withBrowserContext)
    ? withBrowserContext.replace(/<\\/body>/i, \`\${script}</body>\`)
    : \`\${withBrowserContext}\${script}\`;
}

export function writeDashboardDocument(target: Pick<Document, 'open' | 'write' | 'close'>, html: string): void {
  target.open();
  target.write(html);
  target.close();
}
