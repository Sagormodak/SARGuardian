"""Author-exact Bhote Koshi evidence dashboard for Know Place Analysis.

Scientific maps are generated from this run's derived NISAR arrays/GeoTIFFs.
External optical imagery is contextual only, linked to its publisher, and never
feeds a displacement statistic. No remote JavaScript or CSS libraries are used.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import math
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling

TARGET_PAIR = "2026-07-26->2026-08-19"
REFERENCE_BOX_WKT = "POLYGON ((85.500 28.265, 85.565 28.265, 85.565 28.318, 85.500 28.318, 85.500 28.265))"
CROWN_BOX_WKT = "POLYGON ((85.5245 28.2847, 85.5400 28.2847, 85.5400 28.2970, 85.5245 28.2970, 85.5245 28.2847))"
SATELLITE_CONTEXT = (
    {
        "title": "Before the event: optical satellite context",
        "date": "24 August 2026 · described as Sentinel-2 by the publisher",
        "image": "https://www.tbsnews.net/sites/default/files/styles/infograph/public/images/2026/08/28/screenshot_2026-08-28_083549.png",
        "url": "https://www.tbsnews.net/explainer/how-glacier-collapse-triggered-deadly-landslide-and-flooding-along-nepal-china-border",
        "publisher": "The Business Standard",
        "note": "Contextual published imagery only. It is not the NISAR input, and it is not registered to the crown mask in this dashboard.",
    },
    {
        "title": "After the event: corrected stereo elevation-change context",
        "date": "27 August 2026 · corrected WorldView-3 stereo analysis (published 1 Sep 2026)",
        "image": "https://geopera.com/blogs/bhotekoshi-dsm-dh.webp",
        "url": "https://geopera.com/blog/bhote-koshi-stereo-elevation-model",
        "publisher": "Geopera",
        "note": "Corrected external stereo-elevation-change context, not a NISAR displacement output. Geopera retracted the earlier parallax sediment map after finding its viewing-geometry assumption was wrong; this thumbnail is from the corrected follow-up, not the retracted map.",
    },
)
PALETTE_MAG = [(30, 55, 95), (23, 125, 165), (59, 190, 164), (249, 210, 91), (212, 64, 45)]
PALETTE_R = [(72, 42, 120), (47, 111, 164), (37, 171, 151), (218, 223, 90)]


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    except OSError:
        return []


def number(value: Any, digits: int = 3, suffix: str = "") -> str:
    try:
        result = float(value)
        if math.isfinite(result):
            return f"{result:.{digits}f}{suffix}"
    except (TypeError, ValueError):
        pass
    return "—"


def pair_key(value: str) -> str:
    return value.replace(" ", "").replace("→", "->")


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_uri(rgba: np.ndarray) -> str:
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise ValueError("PNG_INPUT_MUST_BE_UINT8_RGBA")
    height, width, _ = rgba.shape
    scanlines = b"".join(b"\x00" + np.ascontiguousarray(row).tobytes() for row in rgba)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    payload += png_chunk(b"IDAT", zlib.compress(scanlines, 6))
    payload += png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def colorize(values: np.ndarray, valid: np.ndarray, low: float, high: float,
             palette: list[tuple[int, int, int]]) -> np.ndarray:
    h, w = values.shape
    image = np.zeros((h, w, 4), dtype=np.uint8)
    image[..., :3] = (12, 23, 38)
    image[..., 3] = 255
    high = max(float(high), low + 1e-8)
    raw = (values.astype(np.float64) - low) / (high - low)
    q = np.clip(np.nan_to_num(raw, nan=0.0, posinf=1.0, neginf=0.0), 0, 1)
    position = q * (len(palette) - 1)
    index = np.minimum(position.astype(np.int32), len(palette) - 2)
    fraction = (position - index)[..., None]
    colors = np.asarray(palette, dtype=np.float64)
    rgb = colors[index] * (1.0 - fraction) + colors[index + 1] * fraction
    image[..., :3][valid] = np.clip(rgb[valid], 0, 255).astype(np.uint8)
    return image


def draw_line(image: np.ndarray, x0: int, y0: int, x1: int, y1: int,
              color: tuple[int, int, int], thickness: int = 1) -> None:
    h, w, _ = image.shape
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        for yy in range(y0 - thickness // 2, y0 + thickness // 2 + 1):
            for xx in range(x0 - thickness // 2, x0 + thickness // 2 + 1):
                if 0 <= yy < h and 0 <= xx < w:
                    image[yy, xx, :3] = color
        if x0 == x1 and y0 == y1:
            break
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


def outline_mask(image: np.ndarray, mask: np.ndarray) -> None:
    if mask.ndim != 2 or not mask.any():
        return
    edge = mask & ~(
        np.roll(mask, 1, 0) & np.roll(mask, -1, 0)
        & np.roll(mask, 1, 1) & np.roll(mask, -1, 1)
    )
    ys, xs = np.where(edge)
    sy, sx = image.shape[0] / mask.shape[0], image.shape[1] / mask.shape[1]
    for y, x in zip(ys, xs):
        yy, xx = int((y + 0.5) * sy), int((x + 0.5) * sx)
        if 0 <= yy < image.shape[0] and 0 <= xx < image.shape[1]:
            image[yy, xx, :3] = (255, 241, 118)


def site_preview(path: Path, mode: str) -> str | None:
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            east = np.asarray(data["east_m"], dtype=np.float32)
            north = np.asarray(data["north_m"], dtype=np.float32)
            valid = np.isfinite(east) & np.isfinite(north)
            if "valid_mask" in data:
                valid &= np.asarray(data["valid_mask"], dtype=bool)
            crown = np.asarray(data["crown_mask"], dtype=bool)
            if mode == "magnitude":
                values = np.hypot(east, north)
                high = float(np.nanpercentile(values[valid], 98)) if valid.any() else 1.0
                base = colorize(values, valid, 0, max(high, 0.1), PALETTE_MAG)
                scale = 6
                image = np.repeat(np.repeat(base, scale, 0), scale, 1)
                # Fixed-length arrows encode orientation only, not speed or magnitude.
                for y in range(2, east.shape[0], 7):
                    for x in range(2, east.shape[1], 7):
                        if not valid[y, x]:
                            continue
                        norm = math.hypot(float(east[y, x]), float(north[y, x]))
                        if norm < 1e-8:
                            continue
                        x0, y0 = int((x + 0.5) * scale), int((y + 0.5) * scale)
                        x1 = int(x0 + 4 * float(east[y, x]) / norm)
                        y1 = int(y0 - 4 * float(north[y, x]) / norm)
                        draw_line(image, x0, y0, x1, y1, (245, 248, 255))
                outline_mask(image, crown)
                return png_uri(image)
            values = np.asarray(data["directional_coherence_R"], dtype=np.float32)
            valid_r = np.isfinite(values) & valid
            base = colorize(values, valid_r, 0.4, 1.0, PALETTE_R)
            image = np.repeat(np.repeat(base, 6, 0), 6, 1)
            outline_mask(image, crown)
            return png_uri(image)
    except (OSError, ValueError, KeyError, EOFError):
        return None


def wkt_ring(wkt: str) -> list[tuple[float, float]]:
    try:
        body = wkt[wkt.index("((") + 2:wkt.rindex("))")]
        return [tuple(map(float, point.strip().split()[:2])) for point in body.split(",")]
    except (ValueError, IndexError):
        return []


def outline_polygon(image: np.ndarray, points: list[tuple[float, float]], transform: Any,
                    raster_width: int, raster_height: int) -> None:
    if len(points) < 2:
        return
    try:
        from pyproj import Transformer
        converter = Transformer.from_crs("EPSG:4326", "EPSG:32645", always_xy=True)
        pixels = []
        for lon, lat in points:
            x, y = converter.transform(lon, lat)
            col, row = (~transform) @ (x, y)
            pixels.append((int(col / raster_width * image.shape[1]), int(row / raster_height * image.shape[0])))
        for first, second in zip(pixels[:-1], pixels[1:]):
            draw_line(image, *first, *second, (65, 215, 165), 2)
        # Crown outline is yellow, visually distinct from the wider reference box.
        crown_pixels = []
        for lon, lat in wkt_ring(CROWN_BOX_WKT):
            x, y = converter.transform(lon, lat)
            col, row = (~transform) @ (x, y)
            crown_pixels.append((int(col / raster_width * image.shape[1]), int(row / raster_height * image.shape[0])))
        for first, second in zip(crown_pixels[:-1], crown_pixels[1:]):
            draw_line(image, *first, *second, (255, 241, 118), 2)
    except Exception:
        return


def footprint_preview(path: Path, mode: str) -> str | None:
    if not path.is_file():
        return None
    try:
        with rasterio.open(path) as src:
            max_w, max_h = 620, 520
            factor = min(max_w / src.width, max_h / src.height, 1.0)
            out_w, out_h = max(1, round(src.width * factor)), max(1, round(src.height * factor))
            values = src.read(1, out_shape=(out_h, out_w), resampling=Resampling.nearest).astype(np.float32)
            valid = src.read_masks(1, out_shape=(out_h, out_w), resampling=Resampling.nearest) > 0
            if src.nodata is not None:
                valid &= values != src.nodata
            valid &= np.isfinite(values)
            if mode == "epochs":
                palette = np.asarray([(12, 23, 38), (42, 92, 146), (37, 151, 171),
                                      (119, 199, 135), (251, 191, 80), (211, 63, 51)], dtype=np.uint8)
                image = np.zeros((out_h, out_w, 4), dtype=np.uint8)
                image[..., :3] = palette[np.clip(np.rint(np.nan_to_num(values)), 0, 5).astype(np.int32)]
                image[..., 3] = 255
                image[~valid, :3] = (5, 10, 18)
            elif mode == "coherence":
                image = colorize(values, valid, 0.75, 1.0, PALETTE_R)
            else:
                hi = float(np.nanpercentile(values[valid], 98)) if valid.any() else 1.0
                image = colorize(values, valid, 0.5, max(hi, 0.51), PALETTE_MAG)
            outline_polygon(image, wkt_ring(REFERENCE_BOX_WKT), src.transform, src.width, src.height)
            return png_uri(image)
    except (OSError, ValueError, rasterio.errors.RasterioError):
        return None


def mean_vector(npz_path: Path) -> tuple[str, str]:
    if not npz_path.is_file():
        return "—", "—"
    try:
        with np.load(npz_path, allow_pickle=False) as data:
            east, north = np.asarray(data["east_m"], dtype=float), np.asarray(data["north_m"], dtype=float)
            mask = np.isfinite(east) & np.isfinite(north) & np.asarray(data["crown_mask"], dtype=bool)
            if "valid_mask" in data:
                mask &= np.asarray(data["valid_mask"], dtype=bool)
            if not mask.any():
                return "—", "—"
            mean_e, mean_n = float(np.mean(east[mask])), float(np.mean(north[mask]))
            magnitude = math.hypot(mean_e, mean_n)
            azimuth = math.degrees(math.atan2(mean_e, mean_n)) % 360.0
            return number(magnitude, 3, " m"), number(azimuth, 1, "° clockwise from north")
    except (OSError, ValueError, KeyError):
        return "—", "—"


def bar_chart(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "<p class='muted'>Pair table not present in this result package.</p>"
    vals = []
    for row in rows:
        try:
            value = float(row.get("crown_median_displacement_m", "nan"))
        except ValueError:
            value = float("nan")
        vals.append(value)
    ymax = max(1.1, max((v for v in vals if math.isfinite(v) and v >= 0), default=1) * 1.15)
    width, height, left, right, top, bottom = 900, 280, 58, 16, 24, 64
    plot_w, plot_h = width - left - right, height - top - bottom
    slot, bar_w = plot_w / len(rows), (plot_w / len(rows)) * 0.52
    out = [f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Pairwise crown median horizontal displacement'>"]
    for i in range(5):
        y = top + plot_h * (1 - i / 4)
        out.append(f"<line x1='{left}' y1='{y:.1f}' x2='{width-right}' y2='{y:.1f}' stroke='#29384c'/>")
        out.append(f"<text x='{left-8}' y='{y+4:.1f}' fill='#a9b8ca' font-size='12' text-anchor='end'>{ymax*i/4:.2f}</text>")
    for i, (row, value) in enumerate(zip(rows, vals)):
        x = left + i * slot + (slot - bar_w) / 2
        bh = plot_h * max(value, 0) / ymax if math.isfinite(value) else 0
        y = top + plot_h - bh
        color = "#f6d365" if pair_key(row.get("pair", "")) == TARGET_PAIR else "#38b2ac"
        out.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{bh:.1f}' rx='5' fill='{color}'/>")
        out.append(f"<text x='{x+bar_w/2:.1f}' y='{max(15,y-7):.1f}' fill='#edf3fa' font-size='11' text-anchor='middle'>{number(value,2)} m</text>")
        label = row.get("pair", "").replace("2026-", "").replace("->", " → ")
        out.append(f"<text x='{x+bar_w/2:.1f}' y='{height-bottom+18}' fill='#a9b8ca' font-size='10' text-anchor='middle'>{esc(label)}</text>")
    out.append("<text x='58' y='13' fill='#a9b8ca' font-size='11'>Metres · individual pair displacement; not cumulative movement</text></svg>")
    return "".join(out)


def image_panel(title: str, subtitle: str, src: str | None, note: str, legend: str = "") -> str:
    if not src:
        return f"<article class='panel'><h3>{esc(title)}</h3><p class='muted'>This preview is unavailable in the saved run output.</p><p>{esc(note)}</p></article>"
    legend_html = f"<p class='muted'>{esc(legend)}</p>" if legend else ""
    return (f"<article class='panel'><h3>{esc(title)}</h3><p class='muted'>{esc(subtitle)}</p>"
            f"<img src='{src}' alt='{esc(title)}' loading='lazy'/>{legend_html}<p>{esc(note)}</p></article>")


def build_dashboard(result_root: str | Path) -> str:
    root = Path(result_root)
    status = read_json(root / "author-exact-analysis-status.json")
    site = read_json(root / "author-raw-site-series-report.json")
    report = read_json(root / "know-place-analysis-report.json")
    source = read_json(root / "author-exact-source-manifest.json")
    footprint = read_json(root / "footprint" / "author-footprint-replay-report.json")
    rows = read_csv(root / "author-raw-site-series.csv")
    row = next((x for x in rows if pair_key(x.get("pair", "")) == TARGET_PAIR), {})
    products = source.get("products", []) if isinstance(source.get("products", []), list) else []
    npz = root / "20260726__20260819_author_site_series_arrays.npz"

    mag = number(row.get("crown_median_displacement_m"), 3, " m")
    rate = number(row.get("crown_median_rate_cm_per_day"), 2, " cm/day")
    vec, azimuth = mean_vector(npz)
    p1 = f"{number(row.get('bulk_reference_crown_R'), 3)} / {number(row.get('bulk_reference_background_R'), 3)}"
    p2 = f"{number(row.get('P2_R_crown'), 3)} / {number(row.get('P2_R_background'), 3)}"
    paper = str(status.get("paper_reproduction_status") or report.get("paper_reproduction_status") or "NOT_EVALUATED")
    hazard = str(status.get("hazard_detection_status") or "NOT_EVALUATED")
    run_tag = str(source.get("drive_version_tag", ""))
    tag = run_tag.split("-")
    run_id = tag[0] if tag and tag[0].isdigit() else ""
    attempt = tag[1] if len(tag) > 1 and tag[1].isdigit() else ""
    run_url = f"https://github.com/moshiour0/SARGuardian-backend/actions/runs/{run_id}" if run_id else ""
    run_link = f"<a href='{run_url}' target='_blank' rel='noopener noreferrer'>GitHub Actions run {esc(run_id)} · attempt {esc(attempt or '1')}</a>" if run_id else "Run ID not included in manifest"
    commit = str(source.get("repository_commit", "not recorded"))
    site_compare = site.get("author_site_series_table_comparison", {})
    p2_compare = site.get("author_p2_table_comparison", {})
    raster_compare = footprint.get("author_aggregate_raster_comparison", {})
    inventory_compare = footprint.get("author_inventory_comparison", {})
    zone_compare = footprint.get("author_validated_zone_table_comparison", {})
    footprint_status = str(status.get("footprint_screen_parity_status") or footprint.get("footprint_screen_parity_status") or "NOT_VERIFIED")
    product_hashes = []
    for p in products:
        product_hashes.append(
            "<tr><td>" + esc(p.get("reference_date", p.get("interval", ""))) + "</td><td><code>" +
            esc(p.get("source_filename", p.get("granule_name", ""))) + "</code></td><td><code>" +
            esc(p.get("source_sha256", "")) + "</code></td><td>" +
            esc(p.get("download_status", "UNKNOWN")) + " / " +
            esc(p.get("grid_validation_status", "UNKNOWN")) + "</td></tr>"
        )
    if not product_hashes:
        product_hashes.append("<tr><td colspan='4'>Source manifest is missing.</td></tr>")

    satellite_cards = []
    for image in SATELLITE_CONTEXT:
        satellite_cards.append(
            "<article class='panel'><h3>" + esc(image["title"]) + "</h3><p class='muted'>" + esc(image["date"]) + "</p>"
            + "<a href='" + esc(image["url"]) + "' target='_blank' rel='noopener noreferrer'>"
            + "<img src='" + esc(image["image"]) + "' alt='" + esc(image["title"]) + "' loading='lazy' referrerpolicy='no-referrer'/></a>"
            + "<p>" + esc(image["note"]) + "</p><p class='muted'>Source: <a href='" + esc(image["url"]) + "' target='_blank' rel='noopener noreferrer'>"
            + esc(image["publisher"]) + "</a>. Copyright remains with the publisher/provider.</p></article>"
        )

    site_mag = site_preview(npz, "magnitude")
    site_r = site_preview(npz, "coherence")
    anomaly = footprint_preview(root / "footprint" / "mean_anomaly_m.tif", "anomaly")
    coherence = footprint_preview(root / "footprint" / "mean_coherence_R.tif", "coherence")
    epochs = footprint_preview(root / "footprint" / "n_epochs_flagged.tif", "epochs")
    raster_count = raster_compare.get("rasters_passed", "—") if isinstance(raster_compare, dict) else "—"
    candidate_count = inventory_compare.get("matched_centroid_count", "—") if isinstance(inventory_compare, dict) else "—"
    zone_count = zone_compare.get("matched_centroid_count", "—") if isinstance(zone_compare, dict) else "—"

    pairs = []
    for item in rows:
        pairs.append("<tr>" + "".join([
            "<td>" + esc(item.get("pair", "")) + "</td>",
            "<td>" + esc(item.get("valid_crown_displacement_pixels", "—")) + "</td>",
            "<td>" + number(item.get("crown_median_displacement_m"), 3, " m") + "</td>",
            "<td>" + number(item.get("crown_median_rate_cm_per_day"), 2, " cm/day") + "</td>",
            "<td>" + number(item.get("bulk_reference_crown_R"), 3) + "</td>",
            "<td>" + number(item.get("bulk_reference_background_R"), 3) + "</td>",
            "<td>" + number(item.get("P2_R_crown"), 3) + "</td>",
            "<td>" + number(item.get("P2_R_background"), 3) + "</td>",
            "<td>" + esc(item.get("P2_resolved", "—")) + "</td>",
            "<td>" + esc(item.get("archive_checks_passed", "—")) + "/" + esc(item.get("archive_checks_total", "—")) + "</td>",
        ]) + "</tr>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SARGuardian · Bhote Koshi reproduction evidence</title>
<style>
:root{{--bg:#08111f;--panel:#101d2e;--line:#263950;--text:#edf3fa;--muted:#a9b8ca;--teal:#38b2ac;--gold:#f6d365;--red:#ef6b63;--green:#55d6a8}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 10% -10%,#18364c 0,transparent 35%),var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}a{{color:#88d9e2}}
header{{padding:36px max(18px,calc((100vw - 1220px)/2)) 26px;border-bottom:1px solid var(--line)}}main{{max-width:1220px;margin:auto;padding:24px 18px 52px}}h1{{font-size:clamp(30px,5vw,46px);line-height:1.08;max-width:960px;margin:10px 0}}h2{{font-size:23px;margin:0 0 12px}}h3{{font-size:17px;margin:0 0 8px}}p{{margin:8px 0}}.muted,small{{color:var(--muted)}}.eyebrow{{color:var(--teal);letter-spacing:.14em;text-transform:uppercase;font-weight:700;font-size:12px}}.subtitle{{color:var(--muted);font-size:17px;max-width:930px}}
.section{{margin-top:30px}}.status-row{{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}}.pill{{border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12px;font-weight:700}}.pill.partial{{border-color:#a98a3f;color:#ffe39a}}.pill.unverified{{border-color:#92524e;color:#ffb8b3}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}}.metric,.panel{{border:1px solid var(--line);background:linear-gradient(160deg,#122239,var(--panel));border-radius:15px;padding:16px;min-width:0}}.metric span{{display:block;color:var(--muted);font-size:12px}}.metric strong{{display:block;font-size:clamp(19px,2vw,26px);margin:7px 0;overflow-wrap:anywhere}}.two-col{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.three-col{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
img{{width:100%;height:auto;display:block;border-radius:9px;border:1px solid #2b425b;background:#050a12}}svg{{width:100%;height:auto;display:block}}.muted.small{{font-size:12px}}.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:12px}}table{{border-collapse:collapse;width:100%;font-size:12px;min-width:920px}}th,td{{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:#b8ccdf;background:#0b1727}}td code{{overflow-wrap:anywhere}}.callout{{border-left:3px solid var(--gold);padding:13px 15px;background:#172234;border-radius:0 10px 10px 0}}.callout.good{{border-left-color:var(--green)}}.callout.warn{{border-left-color:var(--red)}}details{{border:1px solid var(--line);border-radius:12px;padding:13px 15px;background:#0d1929}}summary{{cursor:pointer;font-weight:650}}footer{{border-top:1px solid var(--line);margin-top:32px;padding-top:16px;color:var(--muted);font-size:12px}}.footnote{{font-size:12px;color:var(--muted)}}.legend{{font-size:12px;color:var(--muted)}}
@media(max-width:900px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.three-col{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:620px){{header{{padding:28px 15px 20px}}main{{padding:16px 12px 34px}}.two-col,.three-col{{grid-template-columns:1fr}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style></head><body>
<header><div class="eyebrow">SARGuardian · Know Place Analysis</div><h1>What did NISAR measure before the Bhote Koshi avalanche?</h1>
<p class="subtitle">An evidence-first replay of the five author-selected P05023 GOFF pairs. Compare the measured movement, source quality, spatial screen, and unresolved limits without turning a measurement into an alarm.</p>
<div class="status-row"><span class="pill">Structural: {esc(status.get('structural_status','UNKNOWN'))}</span><span class="pill partial">Paper reproduction: {esc(paper)}</span><span class="pill unverified">Hazard detection: {esc(hazard)}</span></div>
<p class="footnote">{run_link} · Feature-branch commit <code>{esc(commit)}</code>. This is a retrospective scientific result, not a real-time warning.</p></header>
<main>
<section class="section"><h2>At a glance</h2><div class="metrics">
<div class="metric"><span>26 Jul–19 Aug 2026 · 24-day pair</span><strong>{esc(mag)}</strong><small>Author-compatible median horizontal displacement within the crown bounding box</small></div>
<div class="metric"><span>Interval-average rate</span><strong>{esc(rate)}</strong><small>Pairwise median displacement ÷ 24 days; not instantaneous velocity</small></div>
<div class="metric"><span>Valid crown displacement pixels</span><strong>{esc(row.get('valid_crown_displacement_pixels','—'))}</strong><small>Valid cells after the declared measurement gates</small></div>
<div class="metric"><span>Mean-vector magnitude / azimuth</span><strong>{esc(vec)}</strong><small>{esc(azimuth)} · calculated from the author-compatible derived vector field</small></div>
</div><div class="two-col" style="margin-top:14px">
<article class="panel"><h3>Directional organisation · P1 bulk reference</h3><p>Crown R / background R: <strong>{p1}</strong>.</p><p class="muted">The R values matched the deposited author site-series table at its stored precision. This is not the missing displacement-null test.</p></article>
<article class="panel"><h3>Local-mean sensitivity · P2</h3><p>Crown R / background R: <strong>{p2}</strong>.</p><p class="muted">P2 resolved: <strong>{esc(row.get('P2_resolved','NOT_AVAILABLE'))}</strong>. P2 is a separate estimator from P1; the two must not be merged.</p></article></div></section>
<section class="section"><h2>Real-world satellite context</h2><p class="muted">These publisher-linked optical images help explain the event to non-specialists. They are not NISAR inputs and their footprints are not registered to the analysis masks here. Images may require an internet connection.</p><div class="two-col">{''.join(satellite_cards)}</div></section>
<section class="section"><h2>What the five-pair record shows</h2><article class="panel"><p class="muted">Individual pairwise crown median displacement. Bars are not cumulative displacement. The rate is an interval average, so it cannot identify exactly when motion happened within the interval.</p>{bar_chart(rows)}</article>
<div class="panel" style="margin-top:14px"><h3>Pair-level evidence table</h3><div class="table-wrap"><table><thead><tr><th>Acquisition interval</th><th>Valid crown pixels</th><th>Median displacement</th><th>Interval-average rate</th><th>P1 crown R</th><th>P1 background R</th><th>P2 crown R</th><th>P2 background R</th><th>P2 resolved?</th><th>Selected archive checks</th></tr></thead><tbody>{''.join(pairs) if pairs else '<tr><td colspan="10">No pair CSV was found.</td></tr>'}</tbody></table></div>
<p class="footnote">P1 uses the author-compatible bulk reference. P2 uses a local-mean reference with a 22-pixel context halo. The polygon-null percentile is a separate post-hoc coherence analysis; it is not the displacement-null percentile reported in the paper.</p></div></section>
<section class="section"><h2>Scientific imagery · derived from this run</h2><p class="muted">These thumbnails are rendered from saved NISAR-derived arrays and 80 m source-grid GeoTIFFs. Previews are downsampled; use the GeoTIFFs and manifests for GIS or pixel-level review.</p>
<div class="two-col">
{image_panel('Crown-window horizontal displacement','Author-compatible site-series · 26 Jul → 19 Aug',site_mag,'Colour represents horizontal displacement magnitude. Fixed-length arrows show vector orientation only. Yellow outline is a crown rectangle transcribed from the published bounds, not a verified editable author polygon.','Magnitude colour ramp · arrows are orientation-only · yellow outline = crown bounding-box approximation')}
{image_panel('Crown-window directional coherence R','5 × 5 direction-coherence estimator · same pair',site_r,'R describes local organisation among valid offset vectors. It is not a failure probability or a universal alert score.','Higher R = more aligned offset directions · yellow outline = crown bounding-box approximation')}
</div><div class="three-col" style="margin-top:14px">
{image_panel('Persistent magnitude anomalies','Mean anomaly over flagged intervals',anomaly,'Footprint-wide 80 m EPSG:32645 overview. The map highlights candidate motion surfaces, not verified landslide sources.','Magnitude anomaly in metres · dark = nodata')}
{image_panel('Residual directional coherence','Mean residual coherence on flagged cells',coherence,'The author-derived screen highlights coherent moving surfaces. It does not classify a collapse or estimate event probability.','R scale 0.75–1.00 · dark = nodata')}
{image_panel('Screen hit count','Number of intervals in which cells passed the candidate screen',epochs,'Candidates are screened over five intervals and grouped into connected zones. The final candidate inventory uses a separate zonal post-processing step.','0–5 intervals · dark = nodata')}
</div><p class="footnote">Green outline = wider reference-box boundary; yellow outline = crown rectangle approximation. Footprint imagery is derived from radar offsets, not optical satellite imagery.</p></section>
<section class="section"><h2>সহজ ব্যাখ্যা · In plain language</h2><article class="panel"><p>এই পুনরুৎপাদনে ২৬ জুলাই–১৯ আগস্ট ২০২৬-এর ২৪ দিনের interval-এ নির্দিষ্ট author-compatible পদ্ধতিতে crown অঞ্চলের median horizontal displacement প্রায় <strong>{esc(mag)}</strong> পাওয়া গেছে; interval-average rate প্রায় <strong>{esc(rate)}</strong>। এটি ওই পুরো interval-এর গড়, ঘটনার ঠিক আগে গতি বেড়েছিল—এমন প্রমাণ নয়।</p><p>The radar measured motion, but the displacement-null calculation needed to reproduce the paper's exact source-versus-background statistical test is still unavailable from the supplied archive. Therefore this is partial paper reproduction—not proof that the avalanche could have been predicted before it happened.</p></article></section>
<section class="section"><h2>What is supported—and what remains open</h2><div class="two-col">
<article class="panel callout good"><h3>Supported by this run</h3><p>Five exact P05023 source files were downloaded, SHA-256 pinned, HDF5 identity-checked and grid-validated. The author-compatible site-series path passed {esc(site_compare.get('checks_passed','—'))}/{esc(site_compare.get('checks_total','—'))} selected comparisons; P2 passed {esc(p2_compare.get('checks_passed','—'))}/{esc(p2_compare.get('checks_total','—'))}. The footprint comparison reports {esc(raster_count)}/3 aggregate rasters, {esc(candidate_count)}/106 candidate rows, and {esc(zone_count)}/101 Table S7 rows matched.</p><p>This is meaningful method-reproduction progress, not a complete paper reproduction.</p></article>
<article class="panel callout warn"><h3>Still not established</h3><p>The exact author crown vector and source-grid pixel-mask parity are unverified. The terrain code path retains the source's EGM2008/ellipsoidal-height mismatch without a vertical correction. The displacement-null draw-level generator is absent from the supplied archive, so its published approximately 94.7th-percentile statistic is not independently reproduced.</p><p>Whole-paper reproduction remains <strong>PARTIAL</strong>; hazard detection remains <strong>NOT EVALUATED</strong>.</p></article>
</div><article class="panel" style="margin-top:14px"><h3>Scientific interpretation</h3><p>The paper's central caution is that measurable motion did not statistically isolate the eventual avalanche source from its surroundings under the reported test. A single retrospective event is a reproduction target, not an independent test of forecasting skill. Do not describe the displacement estimate as proof that the collapse was predictably detectable.</p></article></section>
<section class="section"><h2>Provenance and source audit</h2><div class="two-col">
<article class="panel"><h3>Run results</h3><p>Source payloads downloaded and grid-valid: <strong>{esc(source.get('source_products_grid_validated',0))}/5</strong></p><p>Source SHA-256 values recorded: <strong>{esc(source.get('author_exact_source_sha256_count',0))}/5</strong></p><p>Structural gate: <strong>{esc(status.get('structural_status','UNKNOWN'))}</strong></p><p>Footprint screen: <strong>{esc(footprint_status)}</strong></p><p>Candidate-score chain audit: <strong>{esc((inventory_compare.get('score_formula_audit') or {}).get('status','NOT_AVAILABLE') if isinstance(inventory_compare,dict) else 'NOT_AVAILABLE')}</strong></p></article>
<article class="panel"><h3>Processing contract</h3><p>NISAR L-SAR HH · ascending track 098 · P05023 PROVISIONAL · GOFF layer 2 · 80 m posting · EPSG:32645.</p><p>The horizontal projection assumes zero vertical motion. P1 uses median geometry components over the height axis at the nearest crown radarGrid sample. P2 uses a separately declared per-pixel DEM geometry path, with a vertical-reference mismatch disclosed rather than silently corrected.</p><p>Paper reproduction: <strong>{esc(paper)}</strong><br>Hazard detection: <strong>{esc(hazard)}</strong></p></article></div>
<details style="margin-top:14px"><summary>Exact source products and SHA-256 values</summary><div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Pair / interval</th><th>Source filename</th><th>Source SHA-256</th><th>Download / grid check</th></tr></thead><tbody>{''.join(product_hashes)}</tbody></table></div><p class="footnote">Source manifest SHA-256: <code>{esc(status.get('source_manifest_sha256','not recorded'))}</code></p></details>
<details style="margin-top:12px"><summary>AOI definition and license notes</summary><p><strong>Reference box WKT:</strong> <code>{esc(REFERENCE_BOX_WKT)}</code></p><p><strong>Crown region used in previews:</strong> <code>{esc(CROWN_BOX_WKT)}</code></p><p>The crown geometry shown here is a bounding-box approximation from published coordinates; the exact author editable vector was not supplied. The Zenodo archive's relevant code/data are CC BY 4.0. The separate CC BY-NC 4.0 runout-extent outline is not included or redistributed by this dashboard.</p><p>Archive DOI: <a href="https://doi.org/10.5281/zenodo.22730419">10.5281/zenodo.22730419</a> · Research Square benchmark: <a href="https://doi.org/10.21203/rs.3.rs-11022365/v1">10.21203/rs.3.rs-11022365/v1</a>.</p></details></section>
<footer>Generated from this workflow's derived outputs. Satellite-context thumbnails are externally hosted; scientific previews are embedded in this HTML. No operational alert, forecast or safety assessment is issued. All ongoing work remains on the isolated feature branch until a separate end-to-end acceptance review.</footer>
</main></body></html>"""


def write_dashboard(result_root: str | Path, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_dashboard(result_root), encoding="utf-8")
    if destination.stat().st_size < 4000 or "<html" not in destination.read_text(encoding="utf-8").lower():
        raise RuntimeError("AUTHOR_DASHBOARD_OUTPUT_INCOMPLETE")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-root", required=True, help="Directory containing derived author-exact reports and rasters")
    parser.add_argument("--output", required=True, help="Output HTML path")
    args = parser.parse_args(argv)
    output = write_dashboard(args.result_root, args.output)
    print("AUTHOR_DASHBOARD_STATUS=PASS")
    print(f"AUTHOR_DASHBOARD_BYTES={output.stat().st_size}")
    print(f"AUTHOR_DASHBOARD={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
