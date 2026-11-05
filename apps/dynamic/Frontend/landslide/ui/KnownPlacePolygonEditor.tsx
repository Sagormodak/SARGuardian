import { useEffect, useMemo, useRef, useState } from 'react';
import { importLibrary } from '@googlemaps/js-api-loader';
import { configureGoogleMaps } from '../../src/googleMapsLoader';
import { calculateGeodesicAreaKm2 } from '../engine/validation';
import { isPointInsidePolygon, parsePolygonWkt, polygonToWkt } from '../engine/investigation';
import type { Coordinate } from '../engine/types';

type PolygonRole = 'measurement' | 'reference';
type ValidationResult = { valid: boolean; message: string };

type Props = {
  outerAoiWkt: string | null;
  initialMeasurementWkt?: string | null;
  initialReferenceWkt?: string | null;
  onMeasurementChange: (wkt: string) => void;
  onReferenceChange: (wkt: string) => void;
  onValidationChange: (result: ValidationResult) => void;
};

const ROLE_LABELS: Record<PolygonRole, string> = {
  measurement: 'Measurement polygon',
  reference: 'Reference/background polygon',
};

const ROLE_STYLES: Record<PolygonRole, { strokeColor: string; fillColor: string }> = {
  measurement: { strokeColor: '#f7c66b', fillColor: '#f7c66b' },
  reference: { strokeColor: '#38bdf8', fillColor: '#38bdf8' },
};

function sameCoordinates(first: Coordinate[], second: Coordinate[]): boolean {
  return first.length === second.length
    && first.every(([lng, lat], index) => lng === second[index][0] && lat === second[index][1]);
}

function orientation(a: Coordinate, b: Coordinate, c: Coordinate): number {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function onSegment(a: Coordinate, b: Coordinate, p: Coordinate): boolean {
  return p[0] >= Math.min(a[0], b[0]) - 1e-10
    && p[0] <= Math.max(a[0], b[0]) + 1e-10
    && p[1] >= Math.min(a[1], b[1]) - 1e-10
    && p[1] <= Math.max(a[1], b[1]) + 1e-10;
}

function segmentsIntersect(a: Coordinate, b: Coordinate, c: Coordinate, d: Coordinate): boolean {
  const o1 = orientation(a, b, c);
  const o2 = orientation(a, b, d);
  const o3 = orientation(c, d, a);
  const o4 = orientation(c, d, b);
  const crosses = ((o1 > 1e-10 && o2 < -1e-10) || (o1 < -1e-10 && o2 > 1e-10))
    && ((o3 > 1e-10 && o4 < -1e-10) || (o3 < -1e-10 && o4 > 1e-10));
  return crosses
    || (Math.abs(o1) <= 1e-10 && onSegment(a, c, b))
    || (Math.abs(o2) <= 1e-10 && onSegment(a, d, b))
    || (Math.abs(o3) <= 1e-10 && onSegment(c, a, d))
    || (Math.abs(o4) <= 1e-10 && onSegment(c, b, d));
}

function hasSelfIntersection(points: Coordinate[]): boolean {
  if (points.length < 3) return true;
  for (let i = 0; i < points.length; i += 1) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    for (let j = i + 1; j < points.length; j += 1) {
      if (j === i || j === i + 1 || (i === 0 && j === points.length - 1)) continue;
      const c = points[j];
      const d = points[(j + 1) % points.length];
      if (segmentsIntersect(a, b, c, d)) return true;
    }
  }
  return false;
}

function polygonInsideOuter(inner: Coordinate[], outer: Coordinate[]): boolean {
  if (inner.length < 3 || outer.length < 3) return false;
  for (let i = 0; i < inner.length; i += 1) {
    const start = inner[i];
    const end = inner[(i + 1) % inner.length];
    // Check intermediate points too: vertices alone do not prove that an edge
    // remains inside a concave outer AOI.
    const steps = Math.max(2, Math.ceil(Math.max(
      Math.abs(end[0] - start[0]),
      Math.abs(end[1] - start[1]),
    ) * 200));
    for (let step = 0; step <= steps; step += 1) {
      const fraction = step / steps;
      const point: Coordinate = [
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
      ];
      if (!isPointInsidePolygon(point[0], point[1], outer)) return false;
    }
    // The backend requires both inner polygons to remain strictly inside the
    // outer boundary; touching or crossing an AOI edge is not accepted.
    for (let j = 0; j < outer.length; j += 1) {
      if (segmentsIntersect(start, end, outer[j], outer[(j + 1) % outer.length])) return false;
    }
  }
  return true;
}

function polygonsOverlapOrTouch(first: Coordinate[], second: Coordinate[]): boolean {
  if (first.some(([lng, lat]) => isPointInsidePolygon(lng, lat, second))
    || second.some(([lng, lat]) => isPointInsidePolygon(lng, lat, first))) return true;
  for (let i = 0; i < first.length; i += 1) {
    const a = first[i];
    const b = first[(i + 1) % first.length];
    for (let j = 0; j < second.length; j += 1) {
      const c = second[j];
      const d = second[(j + 1) % second.length];
      if (segmentsIntersect(a, b, c, d)) return true;
    }
  }
  return false;
}

function validatePolygonPair(
  outer: Coordinate[] | null,
  measurement: Coordinate[],
  reference: Coordinate[],
  measurementClosed: boolean,
  referenceClosed: boolean,
): ValidationResult {
  if (!outer || outer.length < 3) return { valid: false, message: 'The outer AOI boundary is unavailable or invalid.' };
  if (!measurementClosed || measurement.length < 3) {
    return { valid: false, message: 'Draw and close the Measurement Polygon first.' };
  }
  if (!referenceClosed || reference.length < 3) {
    return { valid: false, message: 'Draw and close the Reference Polygon.' };
  }
  if (hasSelfIntersection(measurement)) return { valid: false, message: 'The Measurement Polygon crosses itself. Edit its vertices.' };
  if (hasSelfIntersection(reference)) return { valid: false, message: 'The Reference Polygon crosses itself. Edit its vertices.' };
  if (!polygonInsideOuter(measurement, outer)) {
    return { valid: false, message: 'Every part of the Measurement Polygon must remain inside the outer AOI.' };
  }
  if (!polygonInsideOuter(reference, outer)) {
    return { valid: false, message: 'Every part of the Reference Polygon must remain inside the outer AOI.' };
  }
  const measurementInsideReference = polygonInsideOuter(measurement, reference);
  if (polygonsOverlapOrTouch(measurement, reference) && !measurementInsideReference) {
    return { valid: false, message: 'The polygons may be disjoint or the Reference Polygon may enclose the Measurement Polygon. Partial overlap, reverse containment, and boundary-touch are not allowed.' };
  }
  if (measurementInsideReference) {
    return {
      valid: true,
      message: 'The Reference Polygon encloses the Measurement Polygon. Background statistics will exclude all Measurement Polygon cells; reference-ground stability is not independently verified.',
    };
  }
  return { valid: true, message: 'The disjoint Measurement and Reference Polygons are valid. Reference-ground stability is not independently verified.' };
}

export function KnownPlacePolygonEditor({
  outerAoiWkt,
  initialMeasurementWkt,
  initialReferenceWkt,
  onMeasurementChange,
  onReferenceChange,
  onValidationChange,
}: Props) {
  const mapElementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const outerOverlayRef = useRef<google.maps.Polygon | null>(null);
  const overlaysRef = useRef<Record<PolygonRole, google.maps.Polygon | null>>({
    measurement: null,
    reference: null,
  });
  const pathListenersRef = useRef<Record<PolygonRole, google.maps.MapsEventListener[]>>({
    measurement: [],
    reference: [],
  });
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState('');
  const [activeRole, setActiveRole] = useState<PolygonRole>('measurement');
  const [drawingRole, setDrawingRole] = useState<PolygonRole | null>(null);
  const drawingRoleRef = useRef<PolygonRole | null>(null);
  const [measurement, setMeasurement] = useState<Coordinate[]>([]);
  const [reference, setReference] = useState<Coordinate[]>([]);
  const [measurementClosed, setMeasurementClosed] = useState(false);
  const [referenceClosed, setReferenceClosed] = useState(false);
  const [measurementText, setMeasurementText] = useState('');
  const [referenceText, setReferenceText] = useState('');
  const [measurementWktDirty, setMeasurementWktDirty] = useState(false);
  const [referenceWktDirty, setReferenceWktDirty] = useState(false);
  const [geometryError, setGeometryError] = useState('');
  const initialMeasurementAppliedRef = useRef(false);
  const initialReferenceAppliedRef = useRef(false);

  drawingRoleRef.current = drawingRole;

  const outerCoordinates = useMemo(() => {
    if (!outerAoiWkt) return null;
    try { return parsePolygonWkt(outerAoiWkt); } catch { return null; }
  }, [outerAoiWkt]);

  const geometryValidation = useMemo(
    () => validatePolygonPair(outerCoordinates, measurement, reference, measurementClosed, referenceClosed),
    [outerCoordinates, measurement, reference, measurementClosed, referenceClosed],
  );
  const validation = useMemo(() => {
    if (measurementWktDirty) return { valid: false, message: 'The Measurement WKT draft has not been applied. Apply it or redraw the polygon before submitting.' };
    if (referenceWktDirty) return { valid: false, message: 'The Reference WKT draft has not been applied. Apply it or redraw the polygon before submitting.' };
    return geometryValidation;
  }, [geometryValidation, measurementWktDirty, referenceWktDirty]);

  const measurementArea = measurementClosed ? calculateGeodesicAreaKm2(measurement) : 0;
  const referenceArea = referenceClosed ? calculateGeodesicAreaKm2(reference) : 0;

  useEffect(() => {
    onValidationChange(validation);
  }, [onValidationChange, validation]);

  useEffect(() => {
    if (!initialMeasurementWkt || initialMeasurementAppliedRef.current) return;
    initialMeasurementAppliedRef.current = true;
    try {
      const points = parsePolygonWkt(initialMeasurementWkt);
      if (points.length > 500) throw new Error('The suggested candidate outline is too detailed to edit safely. Draw a smaller measurement polygon.');
      if (hasSelfIntersection(points)) throw new Error('The suggested candidate outline needs editing because its simplified boundary crosses itself.');
      setMeasurement(points);
      setMeasurementClosed(true);
      setMeasurementText(initialMeasurementWkt);
      setMeasurementWktDirty(false);
      setActiveRole('measurement');
      setGeometryError('A candidate-derived Suggested Measurement Polygon was loaded. Review and edit its boundary before running measurement.');
    } catch (error) {
      setGeometryError(error instanceof Error ? error.message : 'The suggested candidate polygon could not be loaded.');
    }
  }, [initialMeasurementWkt]);

  useEffect(() => {
    if (!initialReferenceWkt || initialReferenceAppliedRef.current) return;
    initialReferenceAppliedRef.current = true;
    try {
      const points = parsePolygonWkt(initialReferenceWkt);
      if (points.length > 500) throw new Error('The saved reference polygon is too detailed to edit safely. Draw a simpler background polygon.');
      if (hasSelfIntersection(points)) throw new Error('The saved reference polygon crosses itself.');
      setReference(points);
      setReferenceClosed(true);
      setReferenceText(initialReferenceWkt);
      setReferenceWktDirty(false);
    } catch (error) {
      setGeometryError(error instanceof Error ? error.message : 'The saved reference polygon could not be loaded.');
    }
  }, [initialReferenceWkt]);

  useEffect(() => {
    try {
      const wkt = measurementClosed && measurement.length >= 3 ? polygonToWkt(measurement) : '';
      setMeasurementText(wkt);
      setMeasurementWktDirty(false);
      onMeasurementChange(wkt);
    } catch {
      setMeasurementText('');
      onMeasurementChange('');
    }
  }, [measurement, measurementClosed, onMeasurementChange]);

  useEffect(() => {
    try {
      const wkt = referenceClosed && reference.length >= 3 ? polygonToWkt(reference) : '';
      setReferenceText(wkt);
      setReferenceWktDirty(false);
      onReferenceChange(wkt);
    } catch {
      setReferenceText('');
      onReferenceChange('');
    }
  }, [reference, referenceClosed, onReferenceChange]);

  useEffect(() => {
    let mounted = true;
    const pathListeners = pathListenersRef.current;
    const overlays = overlaysRef.current;
    if (!outerCoordinates || !mapElementRef.current) {
      setMapError('Return to the AOI map and create a valid closed outer polygon.');
      return undefined;
    }
    const apiKey = (import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined)?.trim();
    if (!apiKey) {
      setMapError('Google Maps is not configured. Use the WKT fields below or configure VITE_GOOGLE_MAPS_API_KEY.');
      return undefined;
    }
    try {
      configureGoogleMaps(apiKey);
    } catch {
      setMapError('Google Maps was already initialized with a different API key. Use the WKT fields below or check the application configuration.');
      return undefined;
    }
    void importLibrary('maps')
      .then(({ Map }) => {
        if (!mounted || !mapElementRef.current) return;
        const map = new Map(mapElementRef.current, {
          center: { lat: outerCoordinates[0][1], lng: outerCoordinates[0][0] },
          zoom: 11,
          mapTypeId: 'hybrid',
          fullscreenControl: true,
          streetViewControl: false,
          mapTypeControl: true,
          clickableIcons: false,
          gestureHandling: 'greedy',
        });
        const outer = new google.maps.Polygon({
          paths: outerCoordinates.map(([lng, lat]) => ({ lng, lat })),
          strokeColor: '#f8fbff',
          strokeOpacity: 0.95,
          strokeWeight: 3,
          fillColor: '#ffffff',
          fillOpacity: 0.025,
          clickable: false,
          editable: false,
          zIndex: 1,
        });
        outer.setMap(map);
        const bounds = new google.maps.LatLngBounds();
        outerCoordinates.forEach(([lng, lat]) => bounds.extend({ lng, lat }));
        map.fitBounds(bounds, 56);
        mapRef.current = map;
        outerOverlayRef.current = outer;
        setMapError('');
        setMapReady(true);
      })
      .catch(() => {
        if (mounted) setMapError('Google Maps could not load. Use the WKT fields below or check the Maps JavaScript API configuration.');
      });
    return () => {
      mounted = false;
      Object.values(pathListeners).flat().forEach((listener) => listener.remove());
      Object.values(overlays).forEach((overlay) => overlay?.setMap(null));
      outerOverlayRef.current?.setMap(null);
      mapRef.current = null;
      setMapReady(false);
    };
  }, [outerCoordinates]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return undefined;
    const listener = map.addListener('click', (event: google.maps.MapMouseEvent) => {
      const role = drawingRoleRef.current;
      if (!role || !event.latLng) return;
      const point: Coordinate = [
        Number(event.latLng.lng().toFixed(7)),
        Number(event.latLng.lat().toFixed(7)),
      ];
      const current = role === 'measurement' ? measurement : reference;
      if (current.length >= 500) {
        setGeometryError('A polygon is limited to 500 vertices.');
        return;
      }
      if (current.some(([lng, lat]) => Math.abs(lng - point[0]) < 1e-9 && Math.abs(lat - point[1]) < 1e-9)) {
        setGeometryError('That vertex already exists in this polygon.');
        return;
      }
      setGeometryError('');
      if (role === 'measurement') {
        setMeasurement((points) => [...points, point]);
        setMeasurementClosed(false);
      } else {
        setReference((points) => [...points, point]);
        setReferenceClosed(false);
      }
    });
    return () => listener.remove();
  }, [mapReady, measurement, reference]);

  useEffect(() => {
    if (!mapReady) return;
    const map = mapRef.current;
    if (!map) return;

    const syncRole = (role: PolygonRole, coordinates: Coordinate[], closed: boolean) => {
      const style = ROLE_STYLES[role];
      let overlay = overlaysRef.current[role];
      if (!coordinates.length) {
        pathListenersRef.current[role].forEach((listener) => listener.remove());
        pathListenersRef.current[role] = [];
        overlay?.setMap(null);
        overlaysRef.current[role] = null;
        return;
      }
      const path = coordinates.map(([lng, lat]) => ({ lng, lat }));
      if (!overlay) {
        overlay = new google.maps.Polygon({
          paths: path,
          strokeColor: style.strokeColor,
          strokeOpacity: 1,
          strokeWeight: 3,
          fillColor: style.fillColor,
          fillOpacity: closed ? 0.18 : 0.06,
          editable: closed && activeRole === role && !drawingRole,
          draggable: false,
          clickable: true,
          zIndex: role === 'measurement' ? 3 : 2,
        });
        overlay.setMap(map);
        overlaysRef.current[role] = overlay;
      } else {
        const current = overlay.getPath().getArray().map((point) => [
          Number(point.lng().toFixed(7)), Number(point.lat().toFixed(7)),
        ] as Coordinate);
        if (!sameCoordinates(current, coordinates)) {
          pathListenersRef.current[role].forEach((listener) => listener.remove());
          pathListenersRef.current[role] = [];
          overlay.setPath(path);
        }
        overlay.setOptions({
          editable: closed && activeRole === role && !drawingRole,
          fillOpacity: closed ? 0.18 : 0.06,
        });
      }

      const currentPath = overlay.getPath();
      if (pathListenersRef.current[role].length === 0 && closed) {
        const syncFromOverlay = () => {
          const next = currentPath.getArray().map((point) => [
            Number(point.lng().toFixed(7)), Number(point.lat().toFixed(7)),
          ] as Coordinate);
          if (role === 'measurement') setMeasurement(next);
          else setReference(next);
        };
        pathListenersRef.current[role] = [
          currentPath.addListener('set_at', syncFromOverlay),
          currentPath.addListener('insert_at', syncFromOverlay),
          currentPath.addListener('remove_at', syncFromOverlay),
        ];
      }
    };

    syncRole('measurement', measurement, measurementClosed);
    syncRole('reference', reference, referenceClosed);
  }, [mapReady, measurement, reference, measurementClosed, referenceClosed, activeRole, drawingRole]);

  const beginDrawing = (role: PolygonRole) => {
    setActiveRole(role);
    setDrawingRole(role);
    setGeometryError('');
    if (role === 'measurement') {
      setMeasurement([]);
      setMeasurementClosed(false);
      setMeasurementText('');
      setMeasurementWktDirty(false);
      onMeasurementChange('');
    } else {
      setReference([]);
      setReferenceClosed(false);
      setReferenceText('');
      setReferenceWktDirty(false);
      onReferenceChange('');
    }
  };

  const finishDrawing = () => {
    if (!drawingRole) return;
    const current = drawingRole === 'measurement' ? measurement : reference;
    if (current.length < 3) {
      setGeometryError('At least three vertices are required to close a polygon.');
      return;
    }
    if (hasSelfIntersection(current)) {
      setGeometryError('The polygon crosses itself. Move or undo the crossing vertices before closing it.');
      return;
    }
    if (drawingRole === 'measurement') setMeasurementClosed(true);
    else setReferenceClosed(true);
    setActiveRole(drawingRole);
    setDrawingRole(null);
    setGeometryError('');
  };

  const undoVertex = () => {
    if (drawingRole === 'measurement') setMeasurement((points) => points.slice(0, -1));
    if (drawingRole === 'reference') setReference((points) => points.slice(0, -1));
    setGeometryError('');
  };

  const clearSelected = () => {
    if (activeRole === 'measurement') {
      setMeasurement([]);
      setMeasurementClosed(false);
      setMeasurementText('');
      setMeasurementWktDirty(false);
      onMeasurementChange('');
    } else {
      setReference([]);
      setReferenceClosed(false);
      setReferenceText('');
      setReferenceWktDirty(false);
      onReferenceChange('');
    }
    setDrawingRole(null);
    setGeometryError('');
  };

  const readWkt = (role: PolygonRole, value: string) => {
    try {
      const points = parsePolygonWkt(value);
      if (points.length > 500) throw new Error('A polygon is limited to 500 vertices.');
      if (hasSelfIntersection(points)) throw new Error('This polygon crosses itself.');
      setGeometryError('');
      setActiveRole(role);
      if (role === 'measurement') {
        setMeasurement(points);
        setMeasurementClosed(true);
        setMeasurementWktDirty(false);
      } else {
        setReference(points);
        setReferenceClosed(true);
        setReferenceWktDirty(false);
      }
    } catch (error) {
      // Keep the user's pasted text intact so it can be edited and applied again.
      // An invalid WKT draft must not erase the last valid polygon already on the map.
      setGeometryError(error instanceof Error ? error.message : 'Invalid polygon WKT.');
    }
  };

  return (
    <section className="known-place-polygon-editor" aria-label="Known Place measurement geometry">
      <div className="known-place-geometry-heading">
        <div>
          <span className="result-kicker">GEOMETRY INPUT · WGS84 / EPSG:4326</span>
          <h2>Draw the two analysis polygons</h2>
          <p>The white boundary is the outer AOI. Draw one measurement area and a separate background/reference area inside it.</p>
        </div>
        <span className="known-place-outer-aoi-status">{outerCoordinates ? 'Outer AOI loaded' : 'Outer AOI missing'}</span>
      </div>
      <div className="known-place-map-editor-wrap">
        <div ref={mapElementRef} className="known-place-polygon-map" aria-label="Map to draw measurement and reference polygons" />
        {mapError && <div className="known-place-map-error" role="status">{mapError}</div>}
        {drawingRole && (
          <div className="known-place-map-instruction" role="status">
            Drawing {ROLE_LABELS[drawingRole]}. Tap the map to add vertices, then close the polygon.
          </div>
        )}
      </div>
      <div className="known-place-geometry-tools">
        <button type="button" className={activeRole === 'measurement' ? 'active' : ''} onClick={() => beginDrawing('measurement')}>Draw / replace measurement</button>
        <button type="button" className={activeRole === 'reference' ? 'active' : ''} onClick={() => beginDrawing('reference')}>Draw / replace reference</button>
        <button type="button" className="confirm-button" disabled={!drawingRole || (drawingRole === 'measurement' ? measurement.length : reference.length) < 3} onClick={finishDrawing}>Close polygon</button>
        <button type="button" disabled={!drawingRole || (drawingRole === 'measurement' ? measurement.length : reference.length) === 0} onClick={undoVertex}>Undo vertex</button>
        <button type="button" disabled={drawingRole !== null && drawingRole !== activeRole} onClick={clearSelected}>Clear selected</button>
      </div>
      <div className="known-place-polygon-summaries">
        <button type="button" className={activeRole === 'measurement' ? 'selected' : ''} aria-pressed={activeRole === 'measurement'} onClick={() => setActiveRole('measurement')}>
          <span className="polygon-role-dot measurement-dot" />
          <span><strong>Measurement Polygon</strong><small>{measurement.length} vertices · {measurementClosed ? `${measurementArea.toFixed(3)} km²` : 'not closed'}</small></span>
          <span>{measurementClosed ? 'Ready' : 'Draw required'}</span>
        </button>
        <button type="button" className={activeRole === 'reference' ? 'selected' : ''} aria-pressed={activeRole === 'reference'} onClick={() => setActiveRole('reference')}>
          <span className="polygon-role-dot reference-dot" />
          <span><strong>Reference / Background Polygon</strong><small>{reference.length} vertices · {referenceClosed ? `${referenceArea.toFixed(3)} km²` : 'not closed'}</small></span>
          <span>{referenceClosed ? 'Ready' : 'Draw required'}</span>
        </button>
      </div>
      <div className="known-place-geometry-fields">
        <label className="aoi-job-label">
          <span>Measurement Polygon WKT</span>
          <textarea rows={2} value={measurementText} onChange={(event) => { setMeasurementText(event.target.value); setMeasurementWktDirty(true); }} spellCheck={false} placeholder="Draw on the map or paste a closed WGS84 POLYGON WKT" />
          <button type="button" className="known-place-apply-wkt" onClick={() => readWkt('measurement', measurementText)}>Apply measurement WKT</button>
        </label>
        <label className="aoi-job-label">
          <span>Reference Polygon WKT</span>
          <textarea rows={2} value={referenceText} onChange={(event) => { setReferenceText(event.target.value); setReferenceWktDirty(true); }} spellCheck={false} placeholder="Draw on the map or paste a separate closed WGS84 POLYGON WKT" />
          <button type="button" className="known-place-apply-wkt" onClick={() => readWkt('reference', referenceText)}>Apply reference WKT</button>
        </label>
      </div>
      {geometryError && <p className="catalog-error" role="alert">{geometryError}</p>}
      <p className={validation.valid ? 'known-place-geometry-valid' : 'known-place-geometry-warning'} role="status">
        {validation.message}
      </p>
      <p className="catalog-notice">A reference polygon is only a user-selected comparison area. It is not certified stable ground. The backend also checks polygon separation against the native GOFF grid.</p>
    </section>
  );
}
