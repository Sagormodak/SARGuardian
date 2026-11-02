import { useEffect, useRef, useState } from 'react';
import { importLibrary } from '@googlemaps/js-api-loader';
import type { KnownPlacePairResult } from '../../src/api/knownPlace';
import {
  buildKnownPlaceVectorSamples,
  pointInProjectedRing,
  previewCellCorners,
  projectedRingToLatLng,
  type KnownPlaceMapPreview,
  type KnownPlaceVectorSample,
  type MapLatLng,
} from './knownPlaceMapGeometry';
import { configureGoogleMaps } from '../../src/googleMapsLoader';

type RasterOverlayHandle = google.maps.OverlayView & { redraw: () => void };

function makeRasterOverlay(map: google.maps.Map, pair: KnownPlacePairResult): RasterOverlayHandle | null {
  const rawPreview = pair.map_preview;
  if (!rawPreview) return null;
  const preview: KnownPlaceMapPreview = rawPreview;

  const values = preview.values.flat().filter((value): value is number =>
    typeof value === 'number' && Number.isFinite(value),
  );
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const lower = sorted[Math.floor((sorted.length - 1) * 0.05)];
  const upper = sorted[Math.floor((sorted.length - 1) * 0.95)];
  const min = Number.isFinite(lower) ? lower : 0;
  const max = Number.isFinite(upper) ? Math.max(upper, min + 0.001) : min + 0.001;

  class GoFFRasterOverlay extends google.maps.OverlayView {
    private canvas: HTMLCanvasElement | null = null;

    onAdd(): void {
      this.canvas = document.createElement('canvas');
      this.canvas.setAttribute('aria-label', 'Georeferenced GOFF horizontal displacement magnitude preview');
      this.canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
      this.getPanes()?.overlayLayer.appendChild(this.canvas);
    }

    draw(): void {
      const canvas = this.canvas;
      const div = map.getDiv();
      const projection = this.getProjection();
      if (!canvas || !projection || !div.clientWidth || !div.clientHeight) return;
      const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      const width = div.clientWidth;
      const height = div.clientHeight;
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      const context = canvas.getContext('2d');
      if (!context) return;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);

      for (let row = 0; row < preview.height; row += 1) {
        for (let col = 0; col < preview.width; col += 1) {
          const value = preview.values[row]?.[col];
          if (typeof value !== 'number' || !Number.isFinite(value)) continue;
          const centerX = preview.min_x_m + col * preview.pixel_size_x_m;
          const centerY = preview.max_y_m - row * preview.pixel_size_y_m;
          if (!pointInProjectedRing([centerX, centerY], preview.aoi_ring_xy)) continue;
          const corners = previewCellCorners(preview, row, col);
          if (!corners) continue;
          const points = corners.map((point) => projection.fromLatLngToDivPixel(point));
          if (points.some((point) => point === null)) continue;
          const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
          const red = Math.round(30 + 225 * t);
          const green = Math.round(190 - 115 * t);
          const blue = Math.round(235 - 190 * t);
          context.beginPath();
          points.forEach((point, index) => {
            if (!point) return;
            if (index === 0) context.moveTo(point.x, point.y);
            else context.lineTo(point.x, point.y);
          });
          context.closePath();
          context.fillStyle = 'rgba(' + red + ',' + green + ',' + blue + ',0.68)';
          context.fill();
          context.strokeStyle = 'rgba(8,25,38,0.13)';
          context.lineWidth = 0.45;
          context.stroke();
        }
      }
    }

    onRemove(): void {
      this.canvas?.remove();
      this.canvas = null;
    }

    redraw(): void {
      this.draw();
    }
  }

  return new GoFFRasterOverlay() as RasterOverlayHandle;
}

function ringCenter(points: MapLatLng[]): MapLatLng {
  const open = points.length > 1 ? points.slice(0, -1) : points;
  if (!open.length) return { lat: 28.3, lng: 85.5 };
  return {
    lat: open.reduce((sum, point) => sum + point.lat, 0) / open.length,
    lng: open.reduce((sum, point) => sum + point.lng, 0) / open.length,
  };
}

function markerLabel(sample: KnownPlaceVectorSample): string {
  return sample.displacement_m.toFixed(1) + ' m · ' + sample.rate_m_per_day.toFixed(2) + ' m/day';
}

export function KnownPlaceGoogleMap({ pair }: { pair: KnownPlacePairResult }) {
  const mapElement = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<google.maps.Map | null>(null);
  const [mapError, setMapError] = useState('');
  const [layerStatus, setLayerStatus] = useState('Preparing the selected pair layer…');
  const preview = pair.map_preview;

  useEffect(() => {
    let active = true;
    const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
    if (!apiKey) {
      setMapError('Google Maps is not configured in this frontend production build.');
      return () => { active = false; };
    }
    try {
      configureGoogleMaps(apiKey);
    } catch {
      setMapError('Google Maps loader has an incompatible API-key configuration.');
      return () => { active = false; };
    }

    void importLibrary('maps').then((library) => {
      if (!active || !mapElement.current) return;
      const maps = library as google.maps.MapsLibrary;
      const instance = new maps.Map(mapElement.current, {
        center: { lat: 28.3, lng: 85.5 },
        zoom: 12,
        mapTypeId: 'terrain',
        mapTypeControl: true,
        fullscreenControl: true,
        streetViewControl: false,
        clickableIcons: false,
        gestureHandling: 'greedy',
      });
      setMap(instance);
      setMapError('');
    }).catch(() => {
      if (active) setMapError('Google Maps could not load. Check the API-key restrictions and allowed website referrers.');
    });

    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!map || !preview) {
      setLayerStatus('This pair has no georeferenced raster preview; inspect its native-grid GeoTIFF in the result package.');
      return;
    }
    const measurementRing = projectedRingToLatLng(preview, preview.aoi_ring_xy);
    const referenceRing = preview.reference_ring_xy?.length
      ? projectedRingToLatLng(preview, preview.reference_ring_xy)
      : [];
    const samples = buildKnownPlaceVectorSamples(pair, 9);
    const raster = makeRasterOverlay(map, pair);
    raster?.setMap(map);

    const measurementPolygon = measurementRing.length >= 4
      ? new google.maps.Polygon({
          map,
          paths: measurementRing,
          strokeColor: '#f8fdff',
          strokeOpacity: 0.98,
          strokeWeight: 2.5,
          fillColor: '#4bd5d0',
          fillOpacity: 0.035,
          clickable: false,
          zIndex: 12,
        })
      : null;
    const referencePolygon = referenceRing.length >= 4
      ? new google.maps.Polygon({
          map,
          paths: referenceRing,
          strokeColor: '#f7c56d',
          strokeOpacity: 0.95,
          strokeWeight: 2,
          fillOpacity: 0,
          clickable: false,
          zIndex: 11,
        })
      : null;

    const info = new google.maps.InfoWindow();
    const markers: google.maps.Marker[] = [];
    const listeners: google.maps.MapsEventListener[] = [];
    samples.forEach((sample) => {
      const color = sample.flagged ? '#ff9a68' : '#e9fff9';
      const marker = new google.maps.Marker({
        map,
        position: sample.position,
        zIndex: sample.flagged ? 90 : 80,
        icon: {
          path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
          scale: 4.8,
          rotation: sample.azimuth_deg,
          fillColor: sample.flagged ? '#ff8d54' : '#48e1d4',
          fillOpacity: 0.98,
          strokeColor: '#092131',
          strokeWeight: 1.5,
        },
        label: {
          text: markerLabel(sample),
          color,
          fontSize: '10px',
          fontWeight: '700',
          className: sample.flagged ? 'known-place-map-label is-flagged' : 'known-place-map-label',
        },
        title: sample.flagged ? 'High-magnitude review flag — open for details' : 'Open measured displacement details',
        optimized: true,
      });
      markers.push(marker);
      listeners.push(marker.addListener('click', () => {
        const direction = sample.azimuth_deg.toFixed(1) + '° clockwise from north';
        info.setContent(
          '<div style="font:13px/1.5 Arial,sans-serif;color:#142b3b;min-width:185px">' +
          '<b>Measured GOFF cell</b><br>' +
          'Horizontal displacement: <b>' + sample.displacement_m.toFixed(3) + ' m</b><br>' +
          'Interval-average rate: <b>' + sample.rate_m_per_day.toFixed(4) + ' m/day</b><br>' +
          'Mean vector direction: <b>' + direction + '</b><br>' +
          (sample.flagged ? '<span style="color:#a34b22"><b>Preview-cell median exceeds the configured magnitude threshold (review cue only)</b></span><br>' : '') +
          '<small>Arrow orientation uses the block mean east/north vector. Arrow length is symbolic.</small></div>',
        );
        info.open({ map, anchor: marker });
      }));
    });

    const bounds = new google.maps.LatLngBounds();
    [...measurementRing, ...referenceRing, ...samples.map((sample) => sample.position)].forEach((point) => bounds.extend(point));
    if (!bounds.isEmpty()) map.fitBounds(bounds, 48);
    else map.setCenter(ringCenter(measurementRing));
    setLayerStatus(
      preview.width + ' × ' + preview.height + ' georeferenced preview cells · ' +
      samples.length + ' vector labels · arrows show mean east/north direction',
    );

    return () => {
      info.close();
      listeners.forEach((listener) => listener.remove());
      markers.forEach((marker) => marker.setMap(null));
      measurementPolygon?.setMap(null);
      referencePolygon?.setMap(null);
      raster?.setMap(null);
    };
  }, [map, pair, preview]);

  return (
    <div className="known-place-google-map-shell">
      <div className="known-place-google-map-toolbar">
        <div>
          <strong>{pair.reference_date} → {pair.secondary_date}</strong>
          <span>Track {pair.track ?? 'unknown'} · {pair.direction === 'A' ? 'Ascending' : pair.direction === 'D' ? 'Descending' : 'Unknown direction'} · {pair.polarization ?? '—'} · {pair.release_id ?? 'Release not reported'}</span>
        </div>
        <div className="known-place-map-basemap-status">Google Maps · georeferenced GOFF layer</div>
      </div>
      <div className="known-place-google-map" ref={mapElement} role="application" aria-label="Google Map with GOFF displacement raster and vector annotations" />
      {mapError ? (
        <div className="known-place-google-map-message is-error" role="alert">{mapError}</div>
      ) : !preview ? (
        <div className="known-place-google-map-message" role="status">{layerStatus}</div>
      ) : (
        <>
          <div className="known-place-map-legend" aria-label="Map legend">
            <span><i className="is-magnitude" /> Horizontal displacement magnitude</span>
            <span><i className="is-arrow" /> Mean direction arrow</span>
            <span><i className="is-reference" /> Reference polygon</span>
            <span><i className="is-flag" /> Preview median above threshold</span>
          </div>
          <div className="known-place-google-map-message" role="status">{layerStatus}</div>
        </>
      )}
      <p className="known-place-map-science-note">
        Raster colours show median horizontal displacement magnitude per preview cell; arrows show the mean east/north direction per block and are symbolic in length. Labels show interval-average displacement-derived rates, not instantaneous or forecast velocity. The downsampled map preview is for orientation; original native-grid GeoTIFFs are authoritative. Reference-ground stability is not independently verified.
      </p>
    </div>
  );
}
