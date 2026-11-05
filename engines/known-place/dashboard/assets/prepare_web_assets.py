#!/usr/bin/env python3
"""Build georeferenced display previews and a pair-aware interactive dashboard."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from matplotlib import colormaps
from PIL import Image
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject

SCHEMA = "sarguardian-web-dashboard/1.0"
WEB_CRS = "EPSG:4326"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Required dashboard input missing: {path.name}")
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return result


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def parse_wkt(value: str) -> list[list[float]]:
    match = re.fullmatch(r"\s*POLYGON\s*\(\(\s*(.*?)\s*\)\)\s*", value, flags=re.I)
    if not match:
        raise ValueError("Dashboard requires an already-validated single-ring WKT POLYGON")
    ring = []
    for token in match.group(1).split(","):
        xy = token.strip().split()
        if len(xy) != 2:
            raise ValueError("Malformed AOI WKT coordinate")
        x, y = float(xy[0]), float(xy[1])
        if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
            raise ValueError("AOI coordinate outside WGS84 limits")
        ring.append([x, y])
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise ValueError("AOI WKT ring must be closed")
    return ring


def reproject_band(path: Path, band: int) -> tuple[np.ndarray, tuple[float, float, float, float], dict[str, Any]]:
    with rasterio.open(path) as src:
        if src.crs is None or band < 1 or band > src.count:
            raise ValueError(f"Missing CRS or invalid band in {path.name}")
        source = src.read(band).astype("float32", copy=False)
        if src.nodata is not None:
            source = source.copy()
            source[source == src.nodata] = np.nan
        source[~np.isfinite(source)] = np.nan
        source_valid = int(np.isfinite(source).sum())
        transform, width, height = calculate_default_transform(
            src.crs, WEB_CRS, src.width, src.height, *src.bounds
        )
        if width < 1 or height < 1 or width * height > 16_000_000:
            raise ValueError(f"Invalid preview raster dimensions for {path.name}")
        out = np.full((height, width), np.nan, dtype="float32")
        reproject(
            source=source, destination=out,
            src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
            dst_transform=transform, dst_crs=WEB_CRS, dst_nodata=np.nan,
            resampling=Resampling.nearest, init_dest_nodata=True,
        )
        west, south, east, north = array_bounds(height, width, transform)
        if not all(math.isfinite(v) for v in (west, south, east, north)) or west >= east or south >= north:
            raise ValueError(f"Invalid WGS84 bounds for {path.name}")
        description = (src.descriptions[band - 1] if src.descriptions else None) or f"Band {band}"
        unit = (src.units[band - 1] if src.units else None) or ""
        if not unit:
            found = re.search(r"\(([^()]*)\)\s*$", description)
            unit = found.group(1).strip() if found else ("dimensionless" if "coherence" in description.lower() else "source units not declared")
        return out, (float(west), float(south), float(east), float(north)), {
            "description": description.strip(), "units": unit, "source_crs": src.crs.to_string(),
            "source_transform": [float(v) for v in src.transform[:6]],
            "source_width": src.width, "source_height": src.height, "source_valid_pixels": source_valid,
            "data_type": src.dtypes[band - 1], "source_nodata": float(src.nodata) if src.nodata is not None and math.isfinite(float(src.nodata)) else None,
            "preview_crs": WEB_CRS, "preview_transform": [float(v) for v in transform[:6]],
            "preview_width": width, "preview_height": height,
        }


def write_rgba(values: np.ndarray, lo: float, hi: float, kind: str, path: Path) -> tuple[int, float | None, float | None]:
    valid = np.isfinite(values)
    count = int(valid.sum())
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if count:
        normalized = np.clip((np.where(valid, values, lo) - lo) / (hi - lo), 0.0, 1.0)
        palette = "viridis" if kind == "coherence" else "RdBu_r"
        rgba[..., :3] = (colormaps[palette](normalized)[..., :3] * 255).astype(np.uint8)
        rgba[..., 3] = np.where(valid, 220, 0).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", optimize=True)
    return count, (float(np.nanmin(values)) if count else None), (float(np.nanmax(values)) if count else None)


def write_viewer(path: Path) -> None:
    page = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SARGuardian · Interactive Science Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.css">
<style>
:root{color-scheme:dark;--bg:#07121c;--panel:#0e1e2a;--edge:#254050;--ink:#edf7fb;--muted:#a5bec8;--aqua:#66e2d3;--amber:#f7c76b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#123444,#07121c 55%);color:var(--ink);font:14px/1.45 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:22px}header{display:flex;gap:18px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;border-bottom:1px solid var(--edge);padding-bottom:16px}h1{font-size:clamp(25px,3vw,38px);line-height:1.05;letter-spacing:-.035em;margin:7px 0}.kicker{color:var(--aqua);font-size:10px;font-weight:800;letter-spacing:.17em;text-transform:uppercase}.muted{color:var(--muted)}button,select,input{font:inherit;color:inherit;background:#102a39;border:1px solid #396071;border-radius:7px;padding:8px}button{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--aqua);outline-offset:2px}.warn{margin:14px 0;padding:12px 14px;border:1px solid #8e6b35;background:#322816;color:#ffe7b6;border-radius:10px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}.card,.panel{background:linear-gradient(145deg,#112b39,#0c1a25);border:1px solid var(--edge);border-radius:12px;padding:13px;min-width:0}.label{color:var(--muted);font-size:10px;letter-spacing:.08em;text-transform:uppercase}.big{font-size:26px;font-weight:750;margin-top:3px;overflow-wrap:anywhere}.layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(290px,.8fr);gap:12px}.maphead{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.mapbox{position:relative;height:min(65vh,640px);min-height:340px;border:1px solid var(--edge);border-radius:10px;overflow:hidden;background:#0a1720}.mapbox #map{position:absolute;inset:0}.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.timeline{margin-top:12px;display:grid;grid-template-columns:auto minmax(100px,1fr) auto;gap:9px;align-items:center}.timeline input{width:100%;padding:0;accent-color:var(--aqua)}.timeline small{font-variant-numeric:tabular-nums;color:var(--muted)}.metriclist{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}.metricitem{padding:10px;background:#091721;border:1px solid var(--edge);border-radius:8px;min-width:0}.metricitem strong{display:block;margin-top:4px;overflow-wrap:anywhere}.chart{width:100%;height:170px;display:block}.chart text{fill:var(--muted);font-size:10px}.product-list{display:grid;gap:6px;max-height:250px;overflow:auto}.product-row{width:100%;display:flex;justify-content:space-between;align-items:center;text-align:left;gap:9px;background:#091721}.product-row[aria-current=true]{border-color:var(--aqua);background:#153746}.product-row span{display:block}.product-row small{display:block;color:var(--muted)}details{margin-top:10px;border-top:1px solid var(--edge);padding-top:10px}summary{cursor:pointer}.foot{margin-top:15px;font-size:11px;color:var(--muted)}.legend{font-size:11px;color:var(--muted);margin:7px 0}.legendbar{height:8px;border-radius:4px;background:linear-gradient(90deg,#053061,#f7f7f7,#67001f);margin-top:5px}.hidden{display:none!important}@media(max-width:850px){main{padding:12px}.layout{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.mapbox{height:48vh;min-height:300px}}@media(max-width:450px){.cards{grid-template-columns:1fr 1fr}.big{font-size:21px}.timeline{grid-template-columns:1fr}.timeline input{grid-row:2}}
</style></head><body><main>
<header><div><div class="kicker">SARGuardian · Earth in sight</div><h1>Interactive Science Dashboard</h1><p class="muted">AOI-clipped NISAR observations · pair-aware map playback · reproducible evidence</p></div><div class="controls"><button id="presentation">Presentation mode</button><a href="../index.html" style="color:var(--aqua);padding:9px">Processing report ↗</a></div></header>
<div class="warn"><strong>Scientific interpretation:</strong> a processing PASS confirms structural/provenance checks, not independent geophysical accuracy. Pairwise LOS measurements are not automatically cumulative or 3-D motion. Playback switches actual observations; it does not interpolate or forecast.</div>
<div class="cards" id="summaryCards"></div>
<div class="layout"><section class="panel"><div class="maphead"><div><div class="kicker">Geospatial workspace</div><strong id="mapTitle">Loading map layers…</strong></div><div class="controls"><label>Band <select id="bandSelect" aria-label="Select raster band"></select></label><label>Opacity <input id="opacity" type="range" min="0" max="100" value="80" aria-label="Raster opacity"></label><label>Speed <select id="speed"><option value="2500">0.5×</option><option value="1500" selected>1×</option><option value="750">2×</option></select></label></div></div><div class="mapbox"><div id="map"></div><div id="mapFallback" class="hidden" style="padding:20px"><strong>Interactive map unavailable.</strong><p>The processing report and georeferenced assets remain in this bundle; the basemap/MapLibre library requires an internet connection.</p></div></div><div id="legend" class="legend"></div><div class="timeline"><div class="controls"><button id="previous" aria-label="Previous observation">◀</button><button id="play">Play</button><button id="next" aria-label="Next observation">▶</button></div><input id="timeline" type="range" min="0" max="0" value="0" step="1" aria-label="Observation pair timeline"><small id="dateLabel">—</small></div><p class="muted" id="timelineNote">Each point is a real acquisition pair. No synthetic intermediate observations are created.</p></section>
<aside class="panel"><div class="kicker">Selected observation</div><h2 id="productTitle">—</h2><p class="muted" id="productDescription">—</p><div class="metriclist" id="productMetrics"></div><label>Jump to pair <select id="productSelect"></select></label><div class="kicker" style="margin-top:18px">Quality / support by product</div><svg id="supportChart" class="chart" role="img" aria-label="Bar chart of valid pixels by product"></svg><p class="muted" style="font-size:11px">Bars show per-product valid-pixel counts; they are not a movement trend.</p><div class="kicker" style="margin-top:12px">Observation list</div><div class="product-list" id="productList"></div><details><summary>Provenance and limitations</summary><div id="provenance" class="muted" style="font-size:11px;overflow-wrap:anywhere"></div></details></aside></div>
<footer class="foot">Map data attribution: © OpenStreetMap contributors. Raster preview is reprojected from the validated clipped GeoTIFF; native raster and per-product records remain the scientific source assets. This is a research viewer, not a hazard-alert service.</footer>
</main><script src="./dashboard-data.js"></script><script src="https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.js"></script><script>
(function(){const $=id=>document.getElementById(id);const manifest=window.SARGUARDIAN_DASHBOARD;let M=null,selected=0,playing=false,timer=null,activeLayer=null;const esc=s=>String(s==null?'—':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));if(!manifest){$('mapTitle').textContent='Manifest is missing';$('mapFallback').classList.remove('hidden');return}const obs=manifest.observations||[],layers=manifest.layers||[],aoi=manifest.aoi&&manifest.aoi.geometry,n=obs.length;
$('timeline').max=String(Math.max(0,n-1));$('timeline').disabled=n<2;$('productSelect').innerHTML=obs.map((p,i)=>'<option value="'+i+'">'+esc(p.secondary_date)+' · '+esc(p.id)+'</option>').join('');
const cards=[['Products',n],['GUNW',obs.filter(p=>p.product_type==='GUNW').length],['GOFF',obs.filter(p=>p.product_type==='GOFF').length],['Visual assets',manifest.validation.visual_assets_status||'—']];$('summaryCards').innerHTML=cards.map(x=>'<div class="card"><div class="label">'+esc(x[0])+'</div><div class="big">'+esc(x[1])+'</div></div>').join('');
function addFallback(){ $('mapFallback').classList.remove('hidden'); }
if(window.maplibregl){try{M=new maplibregl.Map({container:'map',style:{version:8,sources:{osm:{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}},layers:[{id:'osm',type:'raster',source:'osm'}]},center:[0,0],zoom:2});M.addControl(new maplibregl.NavigationControl(),'top-right');M.on('load',function(){if(aoi){M.addSource('aoi',{type:'geojson',data:manifest.aoi});M.addLayer({id:'aoi-fill',type:'fill',source:'aoi',paint:{'fill-color':'#66e2d3','fill-opacity':0.09}});M.addLayer({id:'aoi-outline',type:'line',source:'aoi',paint:{'line-color':'#66e2d3','line-width':2,'line-dasharray':[2,1]}});const coords=aoi.coordinates[0]||[];if(coords.length){let west=Infinity,south=Infinity,east=-Infinity,north=-Infinity;coords.forEach(c=>{west=Math.min(west,c[0]);south=Math.min(south,c[1]);east=Math.max(east,c[0]);north=Math.max(north,c[1]);});M.fitBounds([[west,south],[east,north]],{padding:55,maxZoom:14});}}layers.forEach(function(l){const source='src-'+l.id;M.addSource(source,{type:'image',url:(window.SARGUARDIAN_LAYER_DATA||{})[l.id]||l.preview_asset,coordinates:l.corners});M.addLayer({id:'raster-'+l.id,type:'raster',source:source,layout:{visibility:'none'},paint:{'raster-opacity':Number($('opacity').value)/100,'raster-resampling':'nearest'}});});if(n)renderProduct();});}catch(e){addFallback();}}else addFallback();
function current(){return obs[selected]||null;}function obsLayers(p){return layers.filter(l=>l.observation_id===p.id);}function hideLayers(){if(!M)return;layers.forEach(l=>{const id='raster-'+l.id;if(M.getLayer(id))M.setLayoutProperty(id,'visibility','none');});activeLayer=null;}
function renderLegend(l){if(!l){$('legend').textContent='No renderable raster overlay for this product.';return;}const d=l.display_scale||{};$('legend').innerHTML='<strong>'+esc(l.description)+'</strong> · '+esc(l.units)+' · preview-valid pixels '+esc(l.valid_pixels)+'<br>Scale '+esc(d.min)+' to '+esc(d.max)+' '+esc(l.units)+' ('+esc(d.method)+')<div class="legendbar"></div>';}
function renderProduct(){const p=current();if(!p)return;const pl=obsLayers(p);$('timeline').value=String(selected);$('productSelect').value=String(selected);$('dateLabel').textContent=(p.reference_date||'—')+' → '+(p.secondary_date||'—');$('mapTitle').textContent=p.id+' · '+p.product_type+' · '+(p.track||'track unavailable');$('productTitle').textContent=p.id+' · '+p.product_type;$('productDescription').textContent=(p.reference_date||'—')+' reference → '+(p.secondary_date||'—')+' secondary · '+(p.maturity||'maturity not reported')+' · '+(p.look_direction||'view geometry in metadata');
const priorBand=$('bandSelect').value;$('bandSelect').innerHTML=pl.map(l=>'<option value="'+esc(l.id)+'">Band '+esc(l.band)+': '+esc(l.description)+'</option>').join('');if(pl.some(l=>l.id===priorBand))$('bandSelect').value=priorBand;$('bandSelect').disabled=!pl.length;const layer=pl.find(l=>l.id===$('bandSelect').value)||pl[0]||null;hideLayers();if(layer&&M&&M.getLayer('raster-'+layer.id)){M.setLayoutProperty('raster-'+layer.id,'visibility','visible');M.setPaintProperty('raster-'+layer.id,'raster-opacity',Number($('opacity').value)/100);activeLayer=layer.id;}renderLegend(layer);
const m=p.metrics||{};const items=[['Reference date',p.reference_date],['Secondary date',p.secondary_date],['Track / look',p.track||'Not reported'],['Maturity',p.maturity],['Valid pixels',p.valid_pixels],['Reader median',m.reader_median==null?'Not reported':String(m.reader_median)+' '+(m.reader_median_units||'(source units)')],['Mean coherence',m.mean_coherence==null?'Not reported':m.mean_coherence],['CRID',p.crid]];$('productMetrics').innerHTML=items.map(x=>'<div class="metricitem"><div class="label">'+esc(x[0])+'</div><strong>'+esc(x[1])+'</strong></div>').join('');$('provenance').innerHTML='<p>Run: '+esc(manifest.run.github_run_id)+'</p><p>AOI SHA-256: '+esc(manifest.run.aoi_wkt_sha256)+'</p><p>Science commit: '+esc(manifest.run.science_commit)+'</p><p>Orchestration commit: '+esc(manifest.run.orchestration_commit)+'</p><p>Source hash: '+esc(p.source_sha256)+'</p><p>'+esc(p.validation_scope||'Structural/provenance only; independent geophysical validation not performed.')+'</p><p>'+(p.warnings||[]).map(esc).join('<br>')+'</p>';document.querySelectorAll('.product-row').forEach(row=>row.setAttribute('aria-current',row.dataset.idx===String(selected)?'true':'false'));}
function renderList(){$('productList').innerHTML=obs.map((p,i)=>'<button class="product-row" data-idx="'+i+'" aria-current="'+(i===selected?'true':'false')+'"><span><strong>'+esc(p.id)+' · '+esc(p.product_type)+'</strong><small>'+esc(p.reference_date)+' → '+esc(p.secondary_date)+' · '+esc(p.track||'track N/A')+'</small></span><span>'+esc(p.valid_pixels)+' px</span></button>').join('');document.querySelectorAll('.product-row').forEach(b=>b.addEventListener('click',()=>select(Number(b.dataset.idx))));}
function renderChart(){const svg=$('supportChart'),w=480,h=170;svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.replaceChildren();const max=Math.max(1,...obs.map(p=>Number(p.valid_pixels)||0)),pad=25,bw=Math.max(4,(w-pad*2)/Math.max(1,obs.length)*.62),step=(w-pad*2)/Math.max(1,obs.length);obs.forEach((p,i)=>{const value=Math.max(0,Number(p.valid_pixels)||0),bar=Math.max(1,value/max*105),x=pad+i*step+(step-bw)/2;const r=document.createElementNS('http://www.w3.org/2000/svg','rect');r.setAttribute('x',x);r.setAttribute('y',125-bar);r.setAttribute('width',bw);r.setAttribute('height',bar);r.setAttribute('rx',2);r.setAttribute('fill',p.product_type==='GUNW'?'#66e2d3':'#f7c76b');const t=document.createElementNS('http://www.w3.org/2000/svg','title');t.textContent=p.id+': '+value+' valid pixels';r.append(t);svg.append(r);if(obs.length<=16){const tx=document.createElementNS('http://www.w3.org/2000/svg','text');tx.setAttribute('x',x+bw/2);tx.setAttribute('y',143);tx.setAttribute('text-anchor','middle');tx.textContent=p.id.replace('GUNW-','').replace('GOFF-','');svg.append(tx);}});const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x',pad);t.setAttribute('y',12);t.textContent='Valid pixels in each product (not unique across pairs)';svg.append(t);}
function select(i){if(!n)return;selected=(i+n)%n;renderProduct();}function stop(){playing=false;if(timer)clearInterval(timer);timer=null;$('play').textContent='Play';}function play(){if(!n)return;if(playing){stop();return;}playing=true;$('play').textContent='Pause';timer=setInterval(()=>select((selected+1)%n),Number($('speed').value||1500));}
$('timeline').addEventListener('input',e=>{stop();select(Number(e.target.value));});$('productSelect').addEventListener('change',e=>{stop();select(Number(e.target.value));});$('previous').addEventListener('click',()=>{stop();select(selected-1);});$('next').addEventListener('click',()=>{stop();select(selected+1);});$('play').addEventListener('click',play);$('speed').addEventListener('change',()=>{if(playing){stop();play();}});$('bandSelect').addEventListener('change',renderProduct);$('opacity').addEventListener('input',()=>{if(M&&activeLayer&&M.getLayer('raster-'+activeLayer))M.setPaintProperty('raster-'+activeLayer,'raster-opacity',Number($('opacity').value)/100);});$('presentation').addEventListener('click',async()=>{try{if(!document.fullscreenElement)await document.documentElement.requestFullscreen();else await document.exitFullscreen();}catch(e){$('presentation').textContent='Fullscreen unavailable';}});window.addEventListener('beforeunload',stop);renderList();renderChart();if(n)renderProduct();else $('mapTitle').textContent='No observations available';})();
</script></body></html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")


def prepare_web_dashboard(root: Path) -> dict[str, Any]:
    root = root.resolve()
    summary_path = root / "aoi-run-summary.json"
    report_path = root / "aoi-processing-report.json"
    summary = read_json(summary_path)
    report = read_json(report_path, required=False)
    products = report.get("products")
    if not isinstance(products, list):
        products = [read_json(p) for p in sorted((root / "product-data").glob("*/product-record.json"))]
    if len(products) != int(summary.get("products_expected", len(products))):
        raise ValueError("Dashboard product count does not match processing summary")
    ring = parse_wkt(str(summary.get("aoi_wkt") or ""))
    geometry = {"type": "Polygon", "coordinates": [ring]}
    feature = {"type": "Feature", "properties": {"name": summary.get("aoi_name", "custom"), "aoi_wkt_sha256": summary.get("aoi_wkt_sha256")}, "geometry": geometry}
    bbox = [min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring)]

    pending = []
    groups: dict[tuple[str, str, str], list[np.ndarray]] = {}
    ordered = sorted(products, key=lambda p: (str(p.get("secondary_date") or "9999"), str(p.get("reference_date") or "9999"), str(p.get("id") or "")))
    for product in ordered:
        pid = str(product.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", pid):
            raise ValueError("Invalid product ID in processing report")
        exports = product.get("exports") or []
        if not exports:
            exports = [{"relative_path": next((p.relative_to(root).as_posix() for p in (root / "product-data" / pid).glob("*.tif")), "")}]
        for export_index, export in enumerate(exports):
            relative = str(export.get("relative_path") or "")
            if not relative:
                continue
            raster_path = safe_path(root, relative)
            if not raster_path.is_file() or raster_path.suffix.lower() not in {".tif", ".tiff"}:
                raise ValueError(f"Validated GeoTIFF not found: {pid}/{relative}")
            original_hash = sha256(raster_path)
            with rasterio.open(raster_path) as ds:
                band_count = ds.count
            for band in range(1, band_count + 1):
                values, bounds, meta = reproject_band(raster_path, band)
                overlaps = bounds[0] <= bbox[2] and bounds[2] >= bbox[0] and bounds[1] <= bbox[3] and bounds[3] >= bbox[1]
                if not overlaps:
                    raise ValueError(f"Preview does not intersect AOI: {pid}/{raster_path.name}")
                valid = values[np.isfinite(values)]
                if band == 1 and product.get("valid_pixels") is not None:
                    try:
                        expected_valid = int(product["valid_pixels"])
                    except (TypeError, ValueError):
                        expected_valid = -1
                    if expected_valid >= 0 and expected_valid != meta["source_valid_pixels"]:
                        raise ValueError(f"Source raster valid-pixel mismatch for {pid}: record={expected_valid}, raster={meta['source_valid_pixels']}")
                if not valid.size:
                    continue
                track = str((product.get("stats") or {}).get("track") or product.get("track") or "geometry-unclassified")
                kind = "coherence" if "coherence" in meta["description"].lower() else "continuous"
                group_key = (str(product.get("product_type") or "UNKNOWN"), track, meta["description"])
                groups.setdefault(group_key, []).append(valid.astype("float32", copy=False))
                layer_id = f"{pid}-e{export_index+1}-band-{band}"
                pending.append({
                    "id": layer_id, "observation_id": pid, "product_type": product.get("product_type"),
                    "export_name": raster_path.name, "band": band, "description": meta["description"], "units": meta["units"],
                    "kind": kind, "source_sha256": original_hash, "source_asset": relative,
                    "source_crs": meta["source_crs"], "source_transform": meta["source_transform"],
                    "source_width": meta["source_width"], "source_height": meta["source_height"],
                    "source_valid_pixels": meta["source_valid_pixels"], "data_type": meta["data_type"],
                    "preview_crs": WEB_CRS, "preview_transform": meta["preview_transform"],
                    "preview_width": meta["preview_width"], "preview_height": meta["preview_height"],
                    "bounds_wgs84": list(bounds),
                    "corners": [[bounds[0], bounds[3]], [bounds[2], bounds[3]], [bounds[2], bounds[1]], [bounds[0], bounds[1]]],
                    "valid_pixels": int(valid.size), "value_min": float(np.min(valid)), "value_max": float(np.max(valid)),
                    "values": values, "group_key": group_key,
                })
            if sha256(raster_path) != original_hash:
                raise RuntimeError(f"Source GeoTIFF unexpectedly changed: {raster_path.name}")

    webroot = root / "web-dashboard"
    public_layers = []
    for layer in pending:
        values = layer.pop("values")
        group_key = layer.pop("group_key")
        if layer["kind"] == "coherence":
            lo, hi, method = 0.0, 1.0, "fixed_coherence_0_to_1"
        else:
            joined = np.concatenate(groups[group_key])
            limit = float(np.percentile(np.abs(joined[np.isfinite(joined)]), 98))
            if not math.isfinite(limit) or limit <= 0:
                limit = max(float(np.max(np.abs(joined[np.isfinite(joined)]))), 1.0)
            lo, hi, method = -limit, limit, "track_group_symmetric_98th_percentile"
        rel = f"layers/{layer['id']}.png"
        image_path = webroot / rel
        count, min_value, max_value = write_rgba(values, lo, hi, layer["kind"], image_path)
        if count != layer["valid_pixels"] or image_path.stat().st_size <= 0:
            raise ValueError(f"Preview integrity check failed: {layer['id']}")
        layer.update({"preview_asset": rel, "preview_sha256": sha256(image_path), "preview_bytes": image_path.stat().st_size,
                      "display_scale": {"min": lo, "max": hi, "method": method, "clipping_percentile": 98 if layer["kind"] != "coherence" else None},
                      "value_min": min_value, "value_max": max_value})
        public_layers.append(layer)

    observations = []
    for product in ordered:
        stats = product.get("stats") or {}
        product_layers = [layer for layer in public_layers if layer["observation_id"] == product.get("id")]
        band1 = next((layer for layer in product_layers if layer["band"] == 1), None)
        observations.append({
            "id": product.get("id"), "product_type": product.get("product_type"), "granule_name": product.get("granule_name"),
            "reference_date": product.get("reference_date"), "secondary_date": product.get("secondary_date"),
            "track": stats.get("track") or product.get("track"),
            "look_direction": (str(stats.get("track") or "").split() or [None])[0],
            "maturity": product.get("maturity"), "crid": product.get("crid") or stats.get("crid"),
            "status": product.get("status"), "valid_pixels": product.get("valid_pixels"),
            "grid_pixels_inside_aoi": product.get("grid_pixels_inside_aoi"), "source_sha256": product.get("source_sha256"),
            "warnings": product.get("warnings") or [], "validation_scope": product.get("validation_scope") or "structural_and_provenance_not_independent_geophysical_validation",
            "native_assets": [item.get("relative_path") for item in product.get("exports", []) if item.get("relative_path")],
            "quicklook": product.get("quicklook"), "layers": [layer["id"] for layer in product_layers],
            "metrics": {"reader_median": product.get("metric_value"), "reader_median_name": product.get("metric_name"),
                        "reader_median_units": band1.get("units") if band1 else None, "mean_coherence": stats.get("mean_coherence")},
        })
    limitations = [
        "Structural/provenance PASS is not independent geophysical validation.",
        "Pairwise LOS displacement is not automatically cumulative, vertical, or 3-D ground motion.",
        "Playback shows actual acquisition pairs and does not interpolate missing observations or forecast movement.",
    ]
    diagnostics = summary.get("science_diagnostics") or {}
    stack = diagnostics.get("pixel_stack") or {}
    if stack:
        limitations.append(f"Pixel-stack status: {stack.get('status')}; inspect saved logs and diagnostics before interpreting a trend.")
    candidate = diagnostics.get("candidate_checks") or {}
    if str(candidate.get("status", "")).startswith("SKIPPED"):
        limitations.append("Candidate screening was skipped for this arbitrary WKT AOI because the current candidate checker does not support it.")
    manifest = {
        "schema_version": SCHEMA, "run": {
            "github_run_id": summary.get("run_id"), "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "aoi_wkt_sha256": summary.get("aoi_wkt_sha256"), "science_commit": summary.get("science_commit"),
            "orchestration_commit": summary.get("orchestration_sha"), "workflow_commit": summary.get("dispatcher_workflow_sha"),
        },
        "validation": {"processing_status": summary.get("status", "UNKNOWN"), "visual_assets_status": "PASS",
                       "independent_geophysical_validation": "NOT_PERFORMED", "products_expected": summary.get("products_expected"),
                       "products_validated": summary.get("products_validated")},
        "aoi": feature, "aoi_bbox": bbox,
        "time_window": {"start_date": summary.get("date_start"), "end_date": summary.get("date_end"),
                        "date_basis": summary.get("date_basis"), "date_filter_mode": summary.get("date_filter_mode")},
        "observations": observations, "layers": public_layers, "science_limitations": limitations,
        "display_policy": "Actual pair selection only. No interpolation, trend fitting, or hazard inference is added by the visualization layer.",
    }
    webroot.mkdir(parents=True, exist_ok=True)
    (webroot / "aoi.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}, indent=2) + "\n", encoding="utf-8")
    (webroot / "timeline.json").write_text(json.dumps({"schema_version": SCHEMA, "observations": [
        {key: obs.get(key) for key in ("id", "product_type", "reference_date", "secondary_date", "track", "look_direction", "maturity", "valid_pixels", "layers")} for obs in observations
    ], "policy": "pair-aware; no synthetic intermediate observations"}, indent=2) + "\n", encoding="utf-8")
    (webroot / "metrics.json").write_text(json.dumps({"schema_version": SCHEMA, "products": [
        {"id": obs["id"], "product_type": obs["product_type"], "track": obs["track"], "secondary_date": obs["secondary_date"],
         "valid_pixels": obs["valid_pixels"], "metrics": obs["metrics"]} for obs in observations
    ], "limitations": limitations}, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (webroot / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    image_data = {}
    for layer in public_layers:
        image = safe_path(webroot, layer["preview_asset"])
        image_data[layer["id"]] = "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
    manifest_blob = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    manifest_blob = manifest_blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    (webroot / "dashboard-data.js").write_text(
        "window.SARGUARDIAN_DASHBOARD=" + manifest_blob + ";\nwindow.SARGUARDIAN_LAYER_DATA=" +
        json.dumps(image_data, separators=(",", ":"), allow_nan=False) + ";\n", encoding="utf-8"
    )

    stac_root = webroot / "stac"
    stac_items = stac_root / "items"
    stac_items.mkdir(parents=True, exist_ok=True)
    item_links = []
    for obs in observations:
        product = next(p for p in products if p.get("id") == obs["id"])
        date = str(obs.get("secondary_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"Invalid secondary date for STAC item {obs['id']}")
        assets = {}
        exports = product.get("exports") or []
        if exports and exports[0].get("relative_path"):
            assets["native_raster"] = {"href": "../../../" + str(exports[0]["relative_path"]), "type": "image/tiff; application=geotiff", "roles": ["data"]}
        for idx, layer in enumerate(l for l in public_layers if l["observation_id"] == obs["id"]):
            assets["preview_band_" + str(layer["band"]) + "_" + str(idx + 1)] = {"href": "../../" + layer["preview_asset"], "type": "image/png", "roles": ["overview"]}
        if obs.get("quicklook"):
            assets["quicklook"] = {"href": "../../../" + str(obs["quicklook"]), "type": "image/png", "roles": ["overview"]}
        item = {
            "stac_version": "1.1.0", "type": "Feature", "id": str(obs["id"]), "geometry": geometry, "bbox": bbox,
            "properties": {"datetime": date + "T00:00:00Z", "start_datetime": str(obs.get("reference_date")) + "T00:00:00Z",
                           "end_datetime": date + "T00:00:00Z", "platform": "NISAR", "instruments": ["L-SAR"],
                           "sarguardian:product_type": obs.get("product_type"), "sarguardian:track": obs.get("track"),
                           "sarguardian:crid": obs.get("crid"), "sarguardian:maturity": obs.get("maturity"),
                           "sarguardian:source_sha256": obs.get("source_sha256"), "sarguardian:validation_scope": obs.get("validation_scope")},
            "links": [{"rel": "self", "href": str(obs["id"]) + ".json"}, {"rel": "parent", "href": "../collection.json"}, {"rel": "root", "href": "../catalog.json"}],
            "assets": assets,
        }
        (stac_items / (str(obs["id"]) + ".json")).write_text(json.dumps(item, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        item_links.append({"rel": "item", "href": "items/" + str(obs["id"]) + ".json", "type": "application/geo+json"})
    dates = [str(o.get("secondary_date")) for o in observations if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(o.get("secondary_date") or ""))]
    date_start = str(summary.get("date_start") or (min(dates) if dates else "2026-01-01"))
    date_end = str(summary.get("date_end") or (max(dates) if dates else "2026-12-31"))
    collection = {"stac_version": "1.1.0", "type": "Collection", "id": "sarguardian-" + str(summary.get("run_id", "run")),
                  "description": "AOI-clipped NISAR acquisition-pair exports; pairwise values are not automatically a common-reference time series.",
                  "license": "proprietary", "extent": {"spatial": {"bbox": [bbox]}, "temporal": {"interval": [[date_start + "T00:00:00Z", date_end + "T23:59:59Z"]]}},
                  "links": [{"rel": "self", "href": "collection.json"}, {"rel": "root", "href": "catalog.json"}, {"rel": "items", "href": "items/"}] + item_links}
    (stac_root / "collection.json").write_text(json.dumps(collection, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    catalog = {"stac_version": "1.1.0", "type": "Catalog", "id": "sarguardian-" + str(summary.get("run_id", "run")),
               "description": "SARGuardian AOI-scoped NISAR products and derived previews.",
               "links": [{"rel": "self", "href": "catalog.json"}, {"rel": "child", "href": "collection.json", "type": "application/json"}]}
    (stac_root / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    write_viewer(webroot / "index.html")
    report_html = root / "index.html"
    if report_html.is_file():
        content = report_html.read_text(encoding="utf-8")
        if "web-dashboard/index.html" not in content:
            link = '<p class="interactive-dashboard-link"><a href="web-dashboard/index.html">Open interactive geospatial map &amp; observation timeline ↗</a></p>'
            content = re.sub(r"(<main(?:\s[^>]*)?>)", lambda m: m.group(1) + link, content, count=1, flags=re.I)
            report_html.write_text(content, encoding="utf-8")

    receipt = {"schema_version": SCHEMA, "status": "PASS", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
               "manifest": "web-dashboard/manifest.json", "viewer": "web-dashboard/index.html",
               "viewer_data": "web-dashboard/dashboard-data.js", "aoi_geojson": "web-dashboard/aoi.geojson",
               "timeline": "web-dashboard/timeline.json", "metrics": "web-dashboard/metrics.json",
               "stac_catalog": "web-dashboard/stac/catalog.json", "observations": len(observations),
               "layers": len(public_layers), "source_geotiffs_unchanged": True}
    (root / "web-dashboard-build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard-root", required=True, type=Path)
    result = prepare_web_dashboard(parser.parse_args().dashboard_root)
    print("WEB_DASHBOARD_STATUS=" + result["status"])
    print("WEB_DASHBOARD_OBSERVATIONS=" + str(result["observations"]))
    print("WEB_DASHBOARD_LAYERS=" + str(result["layers"]))
    print("WEB_DASHBOARD_VIEWER=" + result["viewer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
