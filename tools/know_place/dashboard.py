"""Offline, self-contained HTML dashboard for Know Place result bundles."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any


def _number(value: Any, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    return f"{number:.{digits}f}" if math.isfinite(number) else "—"


def _safe_json(value: Any) -> str:
    # Avoid accidentally terminating a script tag when the request includes text.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def build_dashboard_html(report: dict[str, Any]) -> str:
    """Render summary charts and native-grid displacement previews without a CDN."""
    request = report.get("request", {})
    date_range = request.get("date_range", {})
    aoi = request.get("aoi", {})
    pairs = report.get("pairs", [])
    values = [
        p.get("statistics", {}).get(
            "aoi_median_horizontal_magnitude_m",
            p.get("statistics", {}).get("crown_median_horizontal_magnitude_m"),
        )
        for p in pairs
    ]
    finite_values = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if finite_values:
        ymin = min(0.0, min(finite_values))
        ymax = max(finite_values) * 1.1 or 1.0
    else:
        ymin, ymax = 0.0, 1.0

    width, height, left, right, top, bottom = 860, 300, 76, 28, 24, 58
    plot_w, plot_h = width - left - right, height - top - bottom
    points = []
    point_by_pair_index: dict[int, tuple[float, float]] = {}
    n = max(1, len(pairs))
    for i, pair in enumerate(pairs):
        stats = pair.get("statistics", {})
        val = stats.get("aoi_median_horizontal_magnitude_m", stats.get("crown_median_horizontal_magnitude_m"))
        if not isinstance(val, (int, float)) or not math.isfinite(float(val)):
            continue
        x = left + (plot_w / max(1, n - 1)) * i
        y = top + plot_h * (1 - (float(val) - ymin) / (ymax - ymin or 1))
        label = f"{pair.get('reference_date', '?')} → {pair.get('secondary_date', '?')}: AOI median {_number(val)} m"
        points.append((x, y, label, i))
        point_by_pair_index[i] = (x, y)
    line_segments = []
    for i in range(1, len(pairs)):
        prev_pair, pair = pairs[i - 1], pairs[i]
        same_chain = (
            prev_pair.get("chain_id") is not None
            and prev_pair.get("chain_id") == pair.get("chain_id")
        )
        contiguous = (
            pair.get("relation_to_previous") == "CONTIGUOUS"
            and pair.get("grid_lattice_compatible_with_previous") is True
        )
        if not (same_chain and contiguous and i - 1 in point_by_pair_index and i in point_by_pair_index):
            continue
        x1, y1 = point_by_pair_index[i - 1]
        x2, y2 = point_by_pair_index[i]
        line_segments.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" class="trend-segment"/>'
        )
    circles = "".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5"><title>{html.escape(label)}</title></circle>'
        for x, y, label, _ in points
    )
    tick_values = [ymin + (ymax - ymin) * k / 4 for k in range(5)]
    y_ticks = "".join(
        f'<text x="{left-12}" y="{top + plot_h*(1-k/4)+4:.2f}" text-anchor="end">{_number(tick_values[k],2)}</text>'
        f'<line x1="{left}" y1="{top + plot_h*(1-k/4):.2f}" x2="{width-right}" y2="{top + plot_h*(1-k/4):.2f}" class="grid"/>'
        for k in range(5)
    )
    x_labels = "".join(
        f'<text x="{left + (plot_w/max(1,n-1))*i:.2f}" y="{height-bottom+22}" text-anchor="middle">{html.escape(str(pair.get("secondary_date",""))[5:])}</text>'
        for i, pair in enumerate(pairs)
    )
    trend_svg = (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="AOI median displacement per product pair">'
        f'{y_ticks}{"".join(line_segments)}{circles}{x_labels}'
        f'<text x="18" y="{height/2:.0f}" transform="rotate(-90 18 {height/2:.0f})" text-anchor="middle">Median magnitude (m)</text>'
        f'<text x="{width/2}" y="{height-8}" text-anchor="middle">Pair end date (UTC)</text></svg>'
    )

    map_cards = []
    for i, pair in enumerate(pairs):
        preview = pair.get("map_preview")
        if not isinstance(preview, dict):
            preview = {}
        canvas_id = f"map-canvas-{i}"
        raster_path = str(pair.get("geotiff_file", ""))
        known_gaps = pair.get("known_instrument_data_gaps", [])
        coverage_text = (
            "; ".join(
                f"{gap.get('start_utc', '?')} to {gap.get('end_utc', '?')} — {gap.get('reason', 'known mission gap')}"
                for gap in known_gaps
            )
            if known_gaps else
            "No registered mission gap intersects this interval; pairwise offsets still do not observe continuous motion."
        )
        if raster_path.startswith("maps/"):
            dashboard_raster_path = "../" + raster_path
        else:
            dashboard_raster_path = raster_path
        map_cards.append(f"""
        <article class="map-card">
          <div class="map-heading"><div><h3>{html.escape(str(pair.get('reference_date','?')))} → {html.escape(str(pair.get('secondary_date','?')))}</h3>
          <p>{html.escape(str(pair.get('granule_name','')))}</p>
          <p>Valid AOI pixels: {html.escape(str(pair.get('valid_aoi_pixels','—')))}</p>
          <p>Known coverage gaps: {html.escape(coverage_text)}</p>
          <p>Grid lattice vs previous pair: {html.escape(str(pair.get('grid_lattice_compatible_with_previous','not applicable / not checked')))}</p>
          <p>Grid identity SHA-256: <code>{html.escape(str(pair.get('grid_identity_sha256','not recorded')))}</code></p>
          <p>Source SHA-256: <code>{html.escape(str(pair.get('source_sha256','not recorded')))}</code></p></div>
          <span class="status">{html.escape(str(pair.get('status','UNKNOWN')))}</span></div>
          <canvas id="{canvas_id}" width="420" height="280" aria-label="Horizontal displacement magnitude preview"></canvas>
          <div class="legend"><span>Lower magnitude</span><span class="gradient"></span><span>Higher magnitude</span><span>No data = grey</span><span>→ Arrow: mean direction; symbolic length</span></div>
          <p class="map-note">White outline: measurement polygon. Dashed blue outline: reference/background polygon. Downsampled preview only; native-grid GeoTIFF remains authoritative. CRS EPSG:{html.escape(str(pair.get('epsg','unknown')))}. Raster download: <a href="{html.escape(dashboard_raster_path, quote=True)}">{html.escape(str(pair.get('geotiff_file','not available')))}</a></p>
        </article>""")

    table_rows = []
    for pair in pairs:
        stats = pair.get("statistics", {})
        uncertainty = pair.get("spatial_block_bootstrap_uncertainty", {})
        uncertainty_stats = uncertainty.get("statistics", {})
        sensitivity = pair.get("spatial_block_bootstrap_sensitivity", {})
        sensitivity_rows = sensitivity.get("rows", []) if isinstance(sensitivity, dict) else []
        sensitivity_label_parts = []
        for sensitivity_row in sensitivity_rows:
            ci = sensitivity_row.get("median_horizontal_magnitude_95pct_interval_m")
            size = sensitivity_row.get("block_size_cells", "?")
            if isinstance(ci, list) and len(ci) == 2:
                sensitivity_label_parts.append(f"{size}-cell: {_number(ci[0])}–{_number(ci[1])} m")
            else:
                sensitivity_label_parts.append(f"{size}-cell: unavailable")
        sensitivity_label = "; ".join(sensitivity_label_parts) if sensitivity_label_parts else "NOT_REPORTED"
        rate = stats.get("aoi_median_magnitude_rate_m_per_day", stats.get("crown_median_magnitude_rate_m_per_day"))
        rate_label = f"{_number(rate,4)} m/day" if isinstance(rate, (int, float)) and math.isfinite(float(rate)) else "Unavailable"
        duration = pair.get("interval_days")
        duration_label = f"{_number(duration,3)} d" if isinstance(duration, (int, float)) and math.isfinite(float(duration)) else "Unknown"
        magnitude_ci = uncertainty_stats.get("median_horizontal_magnitude_95pct_interval_m")
        magnitude_ci_label = (
            f"{_number(magnitude_ci[0])}–{_number(magnitude_ci[1])} m"
            if isinstance(magnitude_ci, list) and len(magnitude_ci) == 2
            else f"Unavailable ({uncertainty.get('status', 'not reported')})"
        )
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(pair.get('reference_date','')))} → {html.escape(str(pair.get('secondary_date','')))}<small class=\"subline\">Midpoint separation: {html.escape(duration_label)}</small></td>"
            f"<td>{html.escape(str(pair.get('release_id','')))}</td>"
            f"<td>{html.escape(str(pair.get('chain_id','not assigned')))}</td>"
            f"<td>{html.escape(str(pair.get('valid_aoi_pixels','—')))} / {html.escape(str(pair.get('aoi_total_grid_cells','—')))} ({_number(100.0 * float(pair.get('valid_aoi_fraction',0.0)),1)}%)</td>"
            f"<td>{html.escape(str(pair.get('high_magnitude_flagged_pixels', '—')))}</td>"
            f"<td>{_number(stats.get('aoi_median_horizontal_magnitude_m', stats.get('crown_median_horizontal_magnitude_m')))} m</td>"
            f"<td>{html.escape(magnitude_ci_label)}</td>"
            f"<td>{_number(stats.get('aoi_mean_vector_magnitude_m', stats.get('crown_mean_vector_magnitude_m')))} m</td>"
            f"<td>{html.escape(rate_label)}</td>"
            f"<td>{_number(stats.get('aoi_mean_vector_azimuth_deg_clockwise_from_north', stats.get('crown_mean_vector_azimuth_deg_clockwise_from_north')),1)}°</td>"
            f"<td>{_number(stats.get('aoi_median_directional_coherence_R', stats.get('crown_median_directional_coherence_R')),2)}</td>"
            f"<td>{html.escape(sensitivity_label)}</td>"
            "</tr>"
        )
    pair_data = []
    for i, pair in enumerate(pairs):
        preview = pair.get("map_preview") or {}
        pair_data.append({
            "canvas": f"map-canvas-{i}",
            "preview": preview,
        })
    data_script = _safe_json(pair_data)

    motion_dynamics = report.get("motion_dynamics", {})
    motion_rows = []
    for feature in motion_dynamics.get("pairs", []) if isinstance(motion_dynamics, dict) else []:
        median_rate = feature.get("median_horizontal_displacement_rate_m_per_day")
        vector_rate = feature.get("mean_vector_magnitude_rate_m_per_day")
        acceleration = feature.get("vector_rate_acceleration_m_per_day_squared")
        median_rate_label = f"{_number(median_rate,4)} m/day" if isinstance(median_rate, (int, float)) else "Unavailable"
        vector_rate_label = f"{_number(vector_rate,4)} m/day" if isinstance(vector_rate, (int, float)) else "Unavailable"
        acceleration_label = f"{_number(acceleration,6)} m/day²" if isinstance(acceleration, (int, float)) else "Not computed"
        eligibility = "Eligible descriptive feature" if feature.get("vector_rate_change_eligible") else "Blocked / first pair"
        block_reason = feature.get("rate_change_block_reason") or "—"
        motion_rows.append(
            "<tr>"
            f"<td>{html.escape(str(feature.get('reference_date') or ''))} → {html.escape(str(feature.get('secondary_date') or ''))}</td>"
            f"<td>{html.escape(str(feature.get('chain_id') or 'not assigned'))}</td>"
            f"<td>{html.escape(median_rate_label)}</td>"
            f"<td>{html.escape(vector_rate_label)}</td>"
            f"<td>{html.escape(acceleration_label)}</td>"
            f"<td>{html.escape(eligibility)}</td>"
            f"<td>{html.escape(str(block_reason))}</td>"
            "</tr>"
        )
    motion_dynamics_status = html.escape(str(
        motion_dynamics.get("status", "NOT_COMPUTED") if isinstance(motion_dynamics, dict) else "NOT_COMPUTED"
    ))
    request_json = _safe_json(request)
    reproduction_status = html.escape(str(report.get("paper_reproduction_status", "NOT_EVALUATED")))
    detection_status = html.escape(str(report.get("hazard_detection_status", "NOT_EVALUATED")))
    measurement_status = html.escape(str(report.get("measurement_status", report.get("status", "NOT_EVALUATED"))))
    structural_status = html.escape(str(report.get("structural_status", "UNKNOWN")))
    alert_html = (
        '<div class="alert"><strong>Interpretation boundary</strong>'
        '<p>Movement measurement is not equivalent to landslide/glacier-collapse detection. This dashboard does not issue an operational alarm. Read the reference, quality support, spatial controls and status gates before interpreting any displacement.</p></div>'
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SARGuardian — Know Place Analysis</title>
<style>
:root{{color-scheme:dark;--bg:#0b1220;--panel:#111c2e;--line:#27364c;--text:#edf3fb;--muted:#9fb0c5;--accent:#7dd3fc;--warn:#fbbf24;--ok:#86efac}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1280px;margin:auto;padding:28px 22px 64px}}h1{{font-size:clamp(26px,4vw,38px);line-height:1.1;margin:0 0 8px}}h2{{font-size:21px;margin:0 0 14px}}h3{{font-size:16px;margin:0 0 4px}}p{{margin:6px 0;color:var(--muted)}}a{{color:var(--accent)}}.eyebrow{{text-transform:uppercase;letter-spacing:.14em;color:var(--accent);font-size:12px;font-weight:700}}
.hero{{display:flex;gap:20px;justify-content:space-between;align-items:end;flex-wrap:wrap;margin-bottom:22px}}.subhead{{max-width:780px}}.chips{{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}}.chip{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;font-size:12px;color:var(--muted)}}.chip strong{{color:var(--text);font-weight:650}}
.grid4{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}}.metric,.panel,.map-card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}}.metric span{{display:block;color:var(--muted);font-size:12px}}.metric strong{{display:block;font-size:14px;overflow-wrap:anywhere;margin-top:6px}}
.two-col{{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(260px,1fr);gap:14px;margin:16px 0}}.chart svg{{width:100%;height:auto;overflow:visible}}.chart text{{fill:var(--muted);font-size:12px}}.grid{{stroke:var(--line);stroke-width:1;stroke-dasharray:3 4}}.trend{{fill:none;stroke:var(--accent);stroke-width:3;stroke-linejoin:round;stroke-linecap:round}}.trend-segment{{stroke:var(--accent);stroke-width:3;stroke-linecap:round}}circle{{fill:var(--accent);stroke:var(--panel);stroke-width:2}}
.code{{font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;white-space:pre-wrap;color:#cbd5e1}}.alert{{border-left:3px solid var(--warn);padding:10px 16px;margin:18px 0;background:#2a2417;border-radius:0 10px 10px 0}}.alert p{{color:#f5dfae}}
.table-wrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px;min-width:760px}}th,td{{border-bottom:1px solid var(--line);padding:10px;text-align:left;white-space:nowrap}}th{{color:var(--muted);font-weight:650}}
.map-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.map-card canvas{{width:100%;height:auto;display:block;background:#0b1220;border:1px solid var(--line);border-radius:9px;margin-top:12px}}.map-heading{{display:flex;justify-content:space-between;gap:10px}}.map-heading p{{font-size:11px;overflow-wrap:anywhere}}.status{{color:var(--muted);font-size:11px;border:1px solid var(--line);border-radius:6px;padding:3px 6px;height:max-content;white-space:nowrap}}
.legend{{display:flex;align-items:center;gap:7px;font-size:10px;color:var(--muted);margin-top:8px;flex-wrap:wrap}}.gradient{{display:inline-block;width:86px;height:8px;border-radius:99px;background:linear-gradient(90deg,#274c77,#38b2ac,#f6d365,#d73027)}}.map-note{{font-size:11px}}.footer{{margin-top:28px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:18px}}
@media(max-width:850px){{.grid4{{grid-template-columns:repeat(2,minmax(0,1fr))}}.two-col,.map-grid{{grid-template-columns:1fr}}main{{padding:20px 13px 44px}}}}
</style></head>
<body><main>
<header class="hero"><div class="subhead"><div class="eyebrow">SARGuardian / Reproducible science</div><h1>Know Place Analysis</h1>
<p>AOI-specific displacement measurements, source provenance, quality support and reviewable uncertainty.</p>
<div class="chips"><span class="chip">AOI: <strong>{html.escape(str(aoi.get('wkt','not provided'))[:110])}</strong></span><span class="chip">Dates: <strong>{html.escape(str(date_range.get('start','?')))} → {html.escape(str(date_range.get('end','?')))}</strong></span></div></div></header>
{alert_html}
<section class="grid4">
<div class="metric"><span>Structural status</span><strong>{structural_status}</strong></div>
<div class="metric"><span>Measurement status</span><strong>{measurement_status}</strong></div>
<div class="metric"><span>Paper reproduction</span><strong>{reproduction_status}</strong></div>
<div class="metric"><span>Hazard detection</span><strong>{detection_status}</strong></div>
</section>
<section class="two-col">
<div class="panel chart"><h2>AOI displacement by product interval</h2><p>Each point is a pairwise median magnitude. Intervals are not summed into cumulative movement unless an independently reviewed continuous-chain policy permits it.</p>{trend_svg}</div>
<div class="panel"><h2>Run provenance</h2><p>Request SHA-256</p><div class="code">{html.escape(str(report.get('request_sha256','not recorded')))}</div><p>Engine version</p><div class="code">{html.escape(str(report.get('engine_version','not recorded')))}</div><p>Source adapter</p><div class="code">{html.escape(', '.join(report.get('source_adapters',[])))}</div><p>Reference policy</p><div class="code">{html.escape(str(report.get('reference_policy','not recorded')))}</div><p>Grid compatibility</p><div class="code">{html.escape(str(report.get('grid_compatibility_status','not evaluated')))} (mismatched pair links are not connected)</div><p>Output checksum policy</p><div class="code">Per-file SHA-256 values are listed in manifest.json; the manifest excludes itself to avoid circular checksums.</div></div>
</section>
<section class="panel"><h2>Interval results</h2><div class="table-wrap"><table><thead><tr><th>Acquisition interval</th><th>Release</th><th>Orbit chain</th><th>Valid / total AOI pixels</th><th>High-motion review pixels</th><th>Median AOI magnitude</th><th>Median 95% spatial-block interval</th><th>Mean-vector magnitude</th><th>Interval-average magnitude rate</th><th>Mean-vector azimuth</th><th>Median R</th><th>Block-size CI sensitivity</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div><p>Missing values indicate unavailable statistics, not zero movement. Interval-average rate is pairwise displacement divided by acquisition-midpoint separation; it is not instantaneous velocity and cannot locate motion onset within the interval. Spatial-block intervals represent exploratory spatial sampling variability under the recorded block policy; they exclude systematic geometry, orbit and reference-frame errors and are not event probabilities.</p></section>
<section class="panel"><h2>Descriptive motion dynamics — not a hazard score</h2><p>Status: {motion_dynamics_status}. Interval-average magnitude/vector rates are based on exact acquisition-midpoint separation. Vector-rate change is computed only within a contiguous, grid-compatible, gap-free processing chain. No calibrated risk score or alarm is emitted.</p><div class="table-wrap"><table><thead><tr><th>Interval</th><th>Processing chain</th><th>Median magnitude rate</th><th>Mean-vector rate magnitude</th><th>Vector-rate acceleration</th><th>Comparability</th><th>Reason / gate</th></tr></thead><tbody>{''.join(motion_rows) if motion_rows else '<tr><td colspan="7">Motion-dynamics features are unavailable for this report.</td></tr>'}</tbody></table></div><p>Acceleration is a descriptive feature in m/day²; it is not an instantaneous physical acceleration and it is not a calibrated probability of failure. Use the independent held-out validation gate before designing alerts.</p></section>
<section style="margin-top:18px"><h2>Spatial displacement previews</h2><p>Native projected grids downsampled for quick inspection. Use the linked GeoTIFF for full-resolution GIS analysis; the preview is not a substitute for pixel-level data.</p><div class="map-grid">{''.join(map_cards)}</div></section>
<section class="panel" style="margin-top:18px"><h2>Normalized request</h2><div class="code">{html.escape(json.dumps(request, ensure_ascii=False, indent=2))}</div></section>
<footer class="footer">Generated by SARGuardian Know Place Analysis. A successful processing run means calculations and provenance checks completed; it does not prove a hazard detection, prediction, or warning. Always inspect acquisition coverage, valid pixel support, control distributions and uncertainty.</footer>
</main>
<script>
const pairMaps = {data_script};
for (const item of pairMaps) {{
  const c = document.getElementById(item.canvas);
  if (!c) continue;
  const ctx = c.getContext('2d');
  const p = item.preview || {{}};
  const rows = p.values || [];
  const h = rows.length, w = h ? rows[0].length : 0;
  ctx.fillStyle = '#111c2e'; ctx.fillRect(0,0,c.width,c.height);
  if (!h || !w) {{ ctx.fillStyle='#9fb0c5'; ctx.fillText('No raster preview available',16,28); continue; }}
  let finite = [];
  for (const row of rows) for (const v of row) if (typeof v === 'number' && Number.isFinite(v)) finite.push(v);
  const lo = finite.length ? Math.min(...finite) : 0;
  const hi = finite.length ? Math.max(...finite) : 1;
  const scale = Math.min((c.width-36)/w,(c.height-36)/h);
  const ox=(c.width-w*scale)/2, oy=(c.height-h*scale)/2;
  function color(t) {{
    t=Math.max(0,Math.min(1,t));
    const stops=[[39,76,119],[56,178,172],[246,211,101],[215,48,39]];
    const z=t*(stops.length-1), i=Math.min(stops.length-2,Math.floor(z)), q=z-i;
    const a=stops[i], b=stops[i+1];
    return 'rgb('+a.map((v,k)=>Math.round(v*(1-q)+b[k]*q)).join(',')+')';
  }}
  for(let r=0;r<h;r++) for(let col=0;col<w;col++) {{
    const v=rows[r][col];
    ctx.fillStyle=(typeof v==='number'&&Number.isFinite(v))?color((v-lo)/(hi-lo||1)):'#414b5a';
    ctx.fillRect(ox+col*scale,oy+r*scale,Math.ceil(scale),Math.ceil(scale));
  }}
  const ring=p.aoi_ring_xy||[], referenceRing=p.reference_ring_xy||[], dx=Number(p.pixel_size_x_m)||1, dy=Number(p.pixel_size_y_m)||1;
  const es=p.east_values_m||[], ns=p.north_values_m||[];
  // Direction arrows are orientation-only, not scaled displacement vectors.
  // Draw sparsely so the raster remains visible on a mobile-sized canvas.
  ctx.strokeStyle='#ffffff'; ctx.fillStyle='#ffffff'; ctx.lineWidth=1.25;
  for(let r=1;r<h;r+=4) for(let col=1;col<w;col+=4) {{
    const e=es[r]?.[col], n=ns[r]?.[col];
    if(typeof e!=='number'||typeof n!=='number'||!Number.isFinite(e)||!Number.isFinite(n)) continue;
    const norm=Math.hypot(e,n);
    if(norm<1e-6) continue;
    const cx=ox+(col+0.5)*scale, cy=oy+(r+0.5)*scale;
    const length=Math.min(8,Math.max(3,scale*1.7));
    const x2=cx+length*e/norm, y2=cy-length*n/norm;
    ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(x2,y2);ctx.stroke();
    const angle=Math.atan2(y2-cy,x2-cx), head=2.5;
    ctx.beginPath();
    ctx.moveTo(x2,y2);
    ctx.lineTo(x2-head*Math.cos(angle-0.55),y2-head*Math.sin(angle-0.55));
    ctx.lineTo(x2-head*Math.cos(angle+0.55),y2-head*Math.sin(angle+0.55));
    ctx.closePath();ctx.fill();
  }}
  if(ring.length>2) {{
    ctx.strokeStyle='#ffffff'; ctx.lineWidth=2; ctx.beginPath();
    ring.forEach((pt,i)=>{{
      const x=ox+((pt[0]-p.min_x_m)/dx)*scale;
      const y=oy+((p.max_y_m-pt[1])/dy)*scale;
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    }});ctx.closePath();ctx.stroke();
  }}
  if(referenceRing.length>2) {{
    ctx.save(); ctx.strokeStyle='#38bdf8'; ctx.lineWidth=2; ctx.setLineDash([5,3]); ctx.beginPath();
    referenceRing.forEach((pt,i)=>{{
      const x=ox+((pt[0]-p.min_x_m)/dx)*scale;
      const y=oy+((p.max_y_m-pt[1])/dy)*scale;
      if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    }});ctx.closePath();ctx.stroke();ctx.restore();
  }}
  ctx.fillStyle='#edf3fb';ctx.font='11px system-ui';ctx.fillText('Range '+lo.toFixed(2)+'–'+hi.toFixed(2)+' m',8,14);
}}
</script></body></html>'''


def write_dashboard(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_dashboard_html(report), encoding="utf-8")
    return path
