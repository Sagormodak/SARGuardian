"""Interactive geographic map for arbitrary AOI Know Place results.

This is a presentation layer, not a measurement engine. Native-grid GeoTIFFs
remain authoritative; the small browser overlay is approximate and downsampled.
"""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any

from .geometry import parse_polygon_wkt


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _safe_payload(value: Any) -> str:
    """Serialize JSON safely for inline script data."""
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _preview_bounds_wgs84(preview: dict[str, Any], epsg: Any) -> list[list[float]] | None:
    """Get an approximate WGS84 bbox for the displayed projected preview.

    Densified edges limit projection-bounds errors, but the output remains a
    geographic rectangle approximation, not a georeferenced replacement raster.
    """
    values = preview.get("values")
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        return None
    height, width = len(values), len(values[0])
    if width < 1 or height < 1 or width * height > 20_000:
        return None

    min_x = _finite_number(preview.get("min_x_m"))
    max_y = _finite_number(preview.get("max_y_m"))
    dx = _finite_number(preview.get("pixel_size_x_m"))
    dy = _finite_number(preview.get("pixel_size_y_m"))
    try:
        epsg_number = int(epsg)
    except (TypeError, ValueError, OverflowError):
        return None
    if min_x is None or max_y is None or dx is None or dy is None or dx <= 0 or dy <= 0 or epsg_number <= 0:
        return None

    # _preview reports coordinates of the first pixel centre and the downsampled
    # posting. Approximate the outside raster edges using half a pixel.
    x0, x1 = min_x - dx / 2, min_x + (width - 0.5) * dx
    y1, y0 = max_y + dy / 2, max_y - (height - 0.5) * dy
    segments = 32
    xs: list[float] = []
    ys: list[float] = []
    for i in range(segments + 1):
        t = i / segments
        xs.append(x0 + (x1 - x0) * t); ys.append(y1)
        xs.append(x1); ys.append(y1 + (y0 - y1) * t)
        xs.append(x1 - (x1 - x0) * t); ys.append(y0)
        xs.append(x0); ys.append(y0 + (y1 - y0) * t)
    try:
        from pyproj import Transformer
        transformer = Transformer.from_crs(f"EPSG:{epsg_number}", "EPSG:4326", always_xy=True)
        longitudes, latitudes = transformer.transform(xs, ys)
        finite = [
            (float(lon), float(lat))
            for lon, lat in zip(longitudes, latitudes)
            if math.isfinite(float(lon)) and math.isfinite(float(lat))
            and -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90
        ]
    except Exception:
        return None
    if len(finite) < 4:
        return None
    west, east = min(p[0] for p in finite), max(p[0] for p in finite)
    south, north = min(p[1] for p in finite), max(p[1] for p in finite)
    if not all(math.isfinite(v) for v in (south, west, north, east)) or south >= north or west >= east:
        return None
    return [[south, west], [north, east]]


def _map_payload(report: dict[str, Any]) -> dict[str, Any]:
    request = report.get("request", {}) if isinstance(report, dict) else {}
    aoi = request.get("aoi", {}) if isinstance(request, dict) else {}
    wkt = aoi.get("wkt", "") if isinstance(aoi, dict) else ""
    geometry_note_raw = str(aoi.get("geometry_note", ""))[:500] if isinstance(aoi, dict) else ""
    try:
        ring = [[float(lon), float(lat)] for lon, lat in parse_polygon_wkt(wkt)]
        aoi_error = None
    except Exception as exc:
        ring, aoi_error = [], f"AOI polygon could not be rendered ({type(exc).__name__})"

    reference = request.get("reference", {}) if isinstance(request, dict) else {}
    reference_wkt = reference.get("polygon_wkt", "") if isinstance(reference, dict) else ""
    reference_warning = str(reference.get("warning", ""))[:500] if isinstance(reference, dict) else ""
    try:
        reference_ring = (
            [[float(lon), float(lat)] for lon, lat in parse_polygon_wkt(reference_wkt)]
            if reference_wkt else []
        )
        reference_error = None
    except Exception as exc:
        reference_ring, reference_error = [], f"Reference polygon could not be rendered ({type(exc).__name__})"

    dates = request.get("date_range", {}) if isinstance(request, dict) else {}
    safe_pairs: list[dict[str, Any]] = []
    source_pairs = report.get("pairs", []) if isinstance(report, dict) else []
    if not isinstance(source_pairs, list):
        source_pairs = []
    for index, pair in enumerate(source_pairs):
        if not isinstance(pair, dict):
            continue
        preview = pair.get("map_preview")
        safe_preview = None
        if isinstance(preview, dict):
            values = preview.get("values")
            if (
                isinstance(values, list) and values
                and all(isinstance(row, list) for row in values)
                and 0 < len(values[0]) <= 160 and len(values) <= 160
                and all(len(row) == len(values[0]) for row in values)
                and len(values) * len(values[0]) <= 20_000
            ):
                safe_preview = {
                    "values": [[_finite_number(value) for value in row] for row in values],
                    "bounds": _preview_bounds_wgs84(preview, pair.get("epsg")),
                    "support_mask_label": str(preview.get("support_mask_label", ""))[:200],
                }
        geotiff = pair.get("geotiff_file")
        geotiff_href = None
        if isinstance(geotiff, str) and geotiff.startswith("maps/") and ".." not in Path(geotiff).parts:
            geotiff_href = "../" + geotiff
        stats = pair.get("statistics", {}) if isinstance(pair.get("statistics"), dict) else {}
        median = _finite_number(stats.get("aoi_median_horizontal_magnitude_m", stats.get("crown_median_horizontal_magnitude_m")))
        rate = _finite_number(stats.get("aoi_median_magnitude_rate_m_per_day", stats.get("crown_median_magnitude_rate_m_per_day")))
        valid_pixels, total_pixels = pair.get("valid_aoi_pixels"), pair.get("aoi_total_grid_cells")
        safe_pairs.append({
            "label": f"{pair.get('reference_date', '?')} → {pair.get('secondary_date', '?')} | {pair.get('release_id', 'release unknown')} | {pair.get('status', 'UNKNOWN')}",
            "reference_date": str(pair.get("reference_date", "")),
            "secondary_date": str(pair.get("secondary_date", "")),
            "release_id": str(pair.get("release_id", "")),
            "status": str(pair.get("status", "UNKNOWN")),
            "epsg": pair.get("epsg"),
            "valid_pixels": valid_pixels if isinstance(valid_pixels, (int, float)) else None,
            "total_pixels": total_pixels if isinstance(total_pixels, (int, float)) else None,
            "valid_fraction": _finite_number(pair.get("valid_aoi_fraction")),
            "support_region_label": str(pair.get("support_region_label", "Valid AOI pixels")),
            "median_magnitude_m": median,
            "median_rate_m_per_day": rate,
            "high_magnitude_flagged_pixels": pair.get("high_magnitude_flagged_pixels"),
            "source_sha256": str(pair.get("source_sha256", "not recorded")),
            "geotiff_href": geotiff_href,
            "preview": safe_preview,
        })
    return {
        "schema_version": "know-place-interactive-map/1.0",
        "aoi_ring_lon_lat": ring,
        "aoi_error": aoi_error,
        "aoi_geometry_note": geometry_note_raw,
        "reference_ring_lon_lat": reference_ring,
        "reference_error": reference_error,
        "reference_warning": reference_warning,
        "start_date": str(dates.get("start", "?")) if isinstance(dates, dict) else "?",
        "end_date": str(dates.get("end", "?")) if isinstance(dates, dict) else "?",
        "structural_status": str(report.get("structural_status", "UNKNOWN")),
        "measurement_status": str(report.get("measurement_status", report.get("status", "UNKNOWN"))),
        "paper_reproduction_status": str(report.get("paper_reproduction_status", "NOT_EVALUATED")),
        "hazard_detection_status": str(report.get("hazard_detection_status", "NOT_EVALUATED")),
        "pairs": safe_pairs,
    }


def build_interactive_map_html(report: dict[str, Any]) -> str:
    """Render a Leaflet/OSM map, quality metadata and pair selection controls."""
    data = _safe_payload(_map_payload(report))
    request = report.get("request", {}) if isinstance(report, dict) else {}
    dates = request.get("date_range", {}) if isinstance(request, dict) else {}
    aoi = request.get("aoi", {}) if isinstance(request, dict) else {}
    aoi_label = html.escape(str(aoi.get("wkt", "not provided"))[:220]) if isinstance(aoi, dict) else "not provided"
    geometry_note_raw = str(aoi.get("geometry_note", ""))[:500] if isinstance(aoi, dict) else ""
    geometry_note = html.escape(geometry_note_raw)
    geometry_note_class = "" if geometry_note_raw else "hidden"
    reference = request.get("reference", {}) if isinstance(request, dict) else {}
    reference_wkt = reference.get("polygon_wkt", "") if isinstance(reference, dict) else ""
    reference_warning_raw = str(reference.get("warning", ""))[:500] if isinstance(reference, dict) else ""
    reference_warning = html.escape(reference_warning_raw)
    start = html.escape(str(dates.get("start", "?"))) if isinstance(dates, dict) else "?"
    end = html.escape(str(dates.get("end", "?"))) if isinstance(dates, dict) else "?"
    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SARGuardian — Interactive AOI Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#111c2e;--line:#27364c;--text:#edf3fb;--muted:#9fb0c5;--accent:#7dd3fc;--warn:#fbbf24}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1440px;margin:auto;padding:20px}h1{margin:0;font-size:clamp(24px,4vw,36px)}h2{font-size:17px;margin:0 0 10px}p{color:var(--muted);margin:5px 0}.muted{color:var(--muted)}a{color:var(--accent)}#source-hash{overflow-wrap:anywhere;word-break:break-word}
header{display:flex;align-items:end;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:16px}.eyebrow{text-transform:uppercase;letter-spacing:.14em;color:var(--accent);font-size:12px;font-weight:700}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:14px;min-width:0;width:100%;max-width:100%}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;min-width:0;max-width:100%}
#map{height:min(72vh,760px);min-height:390px;border:1px solid var(--line);border-radius:8px;background:#dbe6ed}
.controls{display:grid;gap:12px;align-content:start;min-width:0;width:100%;max-width:100%}.field{display:grid;gap:5px;min-width:0;width:100%;max-width:100%}.field label{font-size:12px;color:var(--muted)}select,input[type=range]{display:block;width:100%;min-width:0;max-width:100%;box-sizing:border-box}select{background:#0b1220;color:var(--text);border:1px solid var(--line);padding:9px;border-radius:7px}
button{background:#17344c;color:var(--text);border:1px solid #315b79;border-radius:7px;padding:9px;cursor:pointer}button:hover{background:#214a68}.check{display:flex;gap:8px;align-items:center}.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}.status{border:1px solid var(--line);border-radius:8px;padding:8px;overflow-wrap:anywhere}.status small{display:block;color:var(--muted);font-size:11px}.status strong{font-size:12px}.warn{border-left:3px solid var(--warn);padding:8px 10px;margin-top:12px}.legendbar{height:10px;border-radius:99px;background:linear-gradient(90deg,#274c77,#38b2ac,#f6d365,#d73027);margin:6px 0}.hidden{display:none!important}
@media(max-width:920px){main{padding:12px}.layout{grid-template-columns:minmax(0,1fr);width:100%;max-width:100%}#map{height:55vh;min-height:340px}}
</style></head><body><main>
<header><div><div class="eyebrow">SARGuardian / Know Place Analysis</div><h1>Interactive measurement map</h1><p>Measurement polygon: <strong>__AOI__</strong></p><p class="muted __GEOMETRY_NOTE_CLASS__" id="geometry-note">__GEOMETRY_NOTE__</p><p id="reference-note" class="muted">Reference polygon: __REFERENCE_NOTE__</p><p>Inclusive UTC window: __START__ → __END__</p></div><div class="muted">Map preview is for presentation and quality review, not scientific remeasurement.</div></header>
<div class="status-grid">
<div class="status"><small>Structural status</small><strong id="structural-status"></strong></div>
<div class="status"><small>Measurement status</small><strong id="measurement-status"></strong></div>
<div class="status"><small>Paper reproduction</small><strong id="paper-status"></strong></div>
<div class="status"><small>Hazard detection</small><strong id="hazard-status"></strong></div></div>
<div class="layout"><section class="panel">
<div id="map" role="application" aria-label="Interactive basemap with AOI and displacement preview"></div>
<p id="map-message" class="warn">Loading interactive map…</p>
<p class="muted">Basemap © OpenStreetMap contributors. The coloured image is a downsampled preview warped to a geographic rectangle, for visual review only. A native-grid GeoTIFF is available only if a link is shown for the selected pair; otherwise this map contains the preview and its recorded summary metrics, not a downloadable native-grid raster.</p></section>
<aside class="panel controls">
<div class="field"><label for="pair-select">Acquisition pair</label><select id="pair-select"></select></div>
<div class="field"><label for="opacity">Displacement overlay opacity</label><input id="opacity" type="range" min="0" max="1" step="0.05" value="0.72"><span id="opacity-value" class="muted">72%</span></div>
<label class="check"><input id="show-aoi" type="checkbox" checked> Show measurement polygon</label><label class="check"><input id="show-reference" type="checkbox" checked> Show reference/background polygon</label><button id="fit-aoi" type="button">Zoom to both polygons</button>
<div><h2>Magnitude preview</h2><div class="legendbar"></div><div id="raster-range" class="muted">No raster selected</div><p id="transparency-note">Transparent pixels mean no preview value, not zero motion.</p></div>
<div><h2>Selected interval</h2><p id="pair-label">No pair selected</p><p id="pair-status" class="muted"></p><div class="status-grid">
<div class="status"><small id="valid-pixels-label">Valid AOI pixels</small><strong id="valid-pixels">—</strong></div>
<div class="status"><small>Median magnitude</small><strong id="median-magnitude">Unavailable</strong></div>
<div class="status"><small>Interval-average rate</small><strong id="median-rate">Unavailable</strong></div>
<div class="status"><small>High-motion review pixels</small><strong id="high-pixels">—</strong></div></div>
<p id="source-hash" class="muted"></p><p id="grid-epsg" class="muted"></p><a id="geotiff-link" class="hidden" href="#" download>Download native-grid GeoTIFF</a></div>
<div class="warn">Displacement measurement is not landslide/glacier-collapse detection or an operational warning. Hazard skill remains unevaluated unless independent event/non-event validation supports it.</div>
</aside></div>
<footer class="muted" style="padding:18px 0">AOI WKT: __AOI__<br>Missing product coverage or insufficient valid pixels must never be interpreted as evidence of safety.</footer>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const mapData = __MAP_DATA__;
const el = (id) => document.getElementById(id);
el("structural-status").textContent = mapData.structural_status;
el("measurement-status").textContent = mapData.measurement_status;
el("reference-note").textContent = mapData.reference_error || (mapData.reference_warning || (mapData.reference_ring_lon_lat.length ? "Reference polygon selected; its stability is not independently verified." : "No separate reference polygon supplied; local-context assumptions apply."));
const paperStatusDisplay = {
  "PARTIAL_AUTHOR_SITE_AND_FOOTPRINT_NUMERICS_MATCH_DISPLACEMENT_NULL_STILL_UNVERIFIED": "PARTIAL — numeric checks match; original null-generator identity unverified"
};
el("paper-status").textContent = paperStatusDisplay[mapData.paper_reproduction_status] || mapData.paper_reproduction_status;
el("hazard-status").textContent = mapData.hazard_detection_status;
el("map-message").textContent = mapData.aoi_error || "Choose an acquisition pair to inspect its preview.";

if (typeof L === "undefined") {
  el("map-message").textContent = "Leaflet could not load. This map needs internet access for Leaflet and map tiles. Use dashboard.html for the offline summary and previews.";
} else {
  const map = L.map("map", {worldCopyJump:true});
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom:19,
    attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  let aoiLayer = null;
  let referenceLayer = null;
  if (Array.isArray(mapData.aoi_ring_lon_lat) && mapData.aoi_ring_lon_lat.length >= 4) {
    aoiLayer = L.polygon(mapData.aoi_ring_lon_lat.map((point)=>[point[1],point[0]]), {
      color:"#ffcc66", weight:3, fillColor:"#ffcc66", fillOpacity:0.08
    }).addTo(map);
  }
  if (Array.isArray(mapData.reference_ring_lon_lat) && mapData.reference_ring_lon_lat.length >= 4) {
    referenceLayer = L.polygon(mapData.reference_ring_lon_lat.map((point)=>[point[1],point[0]]), {
      color:"#38bdf8", weight:3, dashArray:"7 5", fillColor:"#38bdf8", fillOpacity:0.05
    }).addTo(map);
  }
  const geometryLayers = [aoiLayer, referenceLayer].filter(Boolean);
  if (geometryLayers.length) map.fitBounds(L.featureGroup(geometryLayers).getBounds().pad(0.14));
  else map.setView([20,0],2);

  let rasterLayer = null;
  const pairSelect = el("pair-select");
  if (!mapData.pairs.length) {
    pairSelect.add(new Option("No measured pairs (catalog-only run)", ""));
    pairSelect.disabled = true;
  } else mapData.pairs.forEach((pair,index)=>{ const dates=(pair.reference_date||"?")+" → "+(pair.secondary_date||"?"); const conciseLabel=dates+" · "+(pair.release_id||"release unknown"); pairSelect.add(new Option(conciseLabel,String(index))); });

  function imageData(preview) {
    const rows = preview && preview.values;
    if (!Array.isArray(rows) || !rows.length || !Array.isArray(rows[0]) || !preview.bounds) return null;
    const width=rows[0].length, height=rows.length;
    if (!width || !height || width*height>20000 || !rows.every(row=>Array.isArray(row)&&row.length===width)) return null;
    const finite=rows.flat().filter(v=>typeof v==="number"&&Number.isFinite(v));
    if (!finite.length) return null;
    const lo=Math.min(...finite), hi=Math.max(...finite);
    const stops=[[39,76,119],[56,178,172],[246,211,101],[215,48,39]];
    const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;
    const ctx=canvas.getContext("2d"), image=ctx.createImageData(width,height);
    for(let row=0;row<height;row++) for(let col=0;col<width;col++) {
      const value=rows[row][col],offset=(row*width+col)*4;
      if(typeof value!=="number"||!Number.isFinite(value)){image.data[offset+3]=0;continue;}
      const z=((value-lo)/(hi-lo||1))*(stops.length-1);
      const ix=Math.min(stops.length-2,Math.floor(z)),fraction=Math.max(0,Math.min(1,z-ix));
      for(let channel=0;channel<3;channel++) image.data[offset+channel]=Math.round(stops[ix][channel]*(1-fraction)+stops[ix+1][channel]*fraction);
      image.data[offset+3]=255;
    }
    ctx.putImageData(image,0,0);
    return {url:canvas.toDataURL("image/png"),lo,hi};
  }
  function renderPair(index) {
    const pair=mapData.pairs[index];
    if(rasterLayer){map.removeLayer(rasterLayer);rasterLayer=null;}
    if(!pair)return;
    el("pair-label").textContent=pair.reference_date+" → "+pair.secondary_date;
    el("pair-status").textContent=pair.status+" | Release "+(pair.release_id||"unknown");
    const valid=pair.valid_pixels,total=pair.total_pixels,fraction=pair.valid_fraction;
    el("valid-pixels-label").textContent=pair.support_region_label || "Valid AOI pixels";
    el("valid-pixels").textContent=(valid===null?"—":String(valid))+" / "+(total===null?"—":String(total))+(typeof fraction==="number"?" ("+(fraction*100).toFixed(1)+"%)":"");
    el("median-magnitude").textContent=typeof pair.median_magnitude_m==="number"?pair.median_magnitude_m.toFixed(3)+" m":"Unavailable";
    el("median-rate").textContent=typeof pair.median_rate_m_per_day==="number"?pair.median_rate_m_per_day.toFixed(4)+" m/day":"Unavailable";
    el("high-pixels").textContent=pair.high_magnitude_flagged_pixels==null?"—":String(pair.high_magnitude_flagged_pixels);
    el("source-hash").textContent="Source SHA-256: "+pair.source_sha256;
    el("grid-epsg").textContent="Source measurement grid: "+(pair.epsg?"EPSG:"+pair.epsg:"unknown");
    const link=el("geotiff-link");
    if(pair.geotiff_href){link.href=pair.geotiff_href;link.classList.remove("hidden");}
    else{link.removeAttribute("href");link.classList.add("hidden");}
    const transparencyNote=el("transparency-note");
    transparencyNote.textContent=(pair.preview&&pair.preview.support_mask_label)||"Transparent pixels mean no preview value, not zero motion.";
    const image=imageData(pair.preview);
    if(image){
      rasterLayer=L.imageOverlay(image.url,pair.preview.bounds,{opacity:Number(el("opacity").value),interactive:false}).addTo(map);
      el("raster-range").textContent="Preview magnitude range: "+image.lo.toFixed(3)+"–"+image.hi.toFixed(3)+" m";
      el("map-message").textContent="Showing downsampled displacement magnitude for "+pair.reference_date+" → "+pair.secondary_date+".";
    }else{
      el("raster-range").textContent="No valid raster preview";
      el("map-message").textContent="AOI shown, but no preview raster is available for this interval. Check pair status and valid-pixel support.";
    }
  }
  pairSelect.addEventListener("change",()=>renderPair(Number(pairSelect.value)));
  el("opacity").addEventListener("input",()=>{
    el("opacity-value").textContent=Math.round(Number(el("opacity").value)*100)+"%";
    if(rasterLayer)rasterLayer.setOpacity(Number(el("opacity").value));
  });
  el("show-aoi").addEventListener("change",()=>{
    if(!aoiLayer)return;
    if(el("show-aoi").checked&&!map.hasLayer(aoiLayer))aoiLayer.addTo(map);
    else if(!el("show-aoi").checked&&map.hasLayer(aoiLayer))map.removeLayer(aoiLayer);
  });
  el("show-reference").addEventListener("change",()=>{
    if(!referenceLayer)return;
    if(el("show-reference").checked&&!map.hasLayer(referenceLayer))referenceLayer.addTo(map);
    else if(!el("show-reference").checked&&map.hasLayer(referenceLayer))map.removeLayer(referenceLayer);
  });
  el("fit-aoi").addEventListener("click",()=>{
    const visibleLayers=[aoiLayer,referenceLayer].filter((layer)=>layer&&map.hasLayer(layer));
    if(visibleLayers.length)map.fitBounds(L.featureGroup(visibleLayers).getBounds().pad(0.14));
    else map.setView([20,0],2);
  });
  if(mapData.pairs.length){pairSelect.value="0";renderPair(0);}
}
</script></body></html>"""
    replacements = {
        "__MAP_DATA__": data,
        "__AOI__": aoi_label,
        "__GEOMETRY_NOTE__": geometry_note,
        "__GEOMETRY_NOTE_CLASS__": geometry_note_class,
        "__REFERENCE_NOTE__": reference_warning or ("Separate reference polygon; stability not independently verified." if reference_wkt else "No separate reference polygon supplied."),
        "__START__": start,
        "__END__": end,
    }
    return re.sub(r"__(?:MAP_DATA|AOI|GEOMETRY_NOTE|GEOMETRY_NOTE_CLASS|REFERENCE_NOTE|START|END)__", lambda match: replacements[match.group(0)], template)


def write_interactive_map(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write interactive map HTML into the derived result bundle."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_interactive_map_html(report), encoding="utf-8")
    return path
