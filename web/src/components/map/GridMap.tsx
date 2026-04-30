import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { BusState, SnapshotMeta, ViewMode } from '../../api/types';
import { fragilityColor, lmpColor, normalizeFragility } from '../../lib/colors';

interface Props {
  topology: unknown | null;
  buses: BusState[];
  meta: SnapshotMeta | null;
  viewMode: ViewMode;
  onBusHover: (busId: string | null, props: Record<string, unknown> | null) => void;
}

export default function GridMap({ topology, buses, meta, viewMode, onBusHover }: Props) {
  const prevBindingRef = useRef<Set<string>>(new Set());
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Track tooltip overlay
  const tooltipRef = useRef<maplibregl.Popup | null>(null);

  // Initialize map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [],
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      },
      center: [-99.5, 31.5], // Texas center
      zoom: 5.5,
      minZoom: 4,
      maxZoom: 14,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

    mapRef.current = map;
    tooltipRef.current = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: 'grid-tooltip',
      offset: 8,
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Load topology as sources + base layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !topology) return;

    const topo = topology as { buses: object; lines: object };

    const onLoad = () => {
      if (!map.getSource('buses')) {
        map.addSource('buses', { type: 'geojson', data: topo.buses as GeoJSON.FeatureCollection,
                                 promoteId: 'bus_id' });
      }
      if (!map.getSource('lines')) {
          map.addSource('lines', { type: 'geojson', data: topo.lines as GeoJSON.FeatureCollection,
                                   promoteId: 'line_id'});
      }

      // Lines layer
      if (!map.getLayer('lines')) {
        map.addLayer({
          id: 'lines',
          type: 'line',
          source: 'lines',
          paint: {
            'line-color': [
                'case',
                ['boolean', ['feature-state', 'binding'], false],
                '#f59e0b',
                '#1e2d3e',
            ],
            'line-width': [
                'interpolate', ['linear'], ['zoom'],
                4, ['case', ['boolean', ['feature-state', 'binding'], false], 1.5, 0.6],
                8, ['case', ['boolean', ['feature-state', 'binding'], false], 3.0, 1.2],
                12, ['case', ['boolean', ['feature-state', 'binding'], false], 5.0, 2.0],
            ],
            'line-opacity': [
                'case',
                ['boolean', ['feature-state', 'binding'], false],
                0.95,
                0.5,
            ],
          },
        });
      }

      // Buses layer (circles, colored by fragility via feature-state)
      if (!map.getLayer('buses')) {
        map.addLayer({
          id: 'buses',
          type: 'circle',
          source: 'buses',
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 2, 8, 4, 12, 7],
            'circle-color': [
              'case',
              ['!=', ['feature-state', 'color'], null],
              ['feature-state', 'color'],
              '#1a4731',
            ],
            'circle-opacity': 0.85,
            'circle-stroke-width': [
              'case',
              ['boolean', ['feature-state', 'hovered'], false],
              2,
              0,
            ],
            'circle-stroke-color': '#ffffff',
          },
        });
      }

      // Hover interactions
      map.on('mousemove', 'buses', (e) => {
        if (!e.features?.length) return;
        map.getCanvas().style.cursor = 'crosshair';
        const feat = e.features[0];
        const props = feat.properties as Record<string, unknown>;
        onBusHover(props.bus_id as string, props);

        tooltipRef.current
          ?.setLngLat(e.lngLat)
          .setHTML(
            `<div class="tip-id">${props.bus_id}</div>
             <div class="tip-zone">${props.load_zone ?? '—'}</div>`
          )
          .addTo(map);
      });

      map.on('mouseleave', 'buses', () => {
        map.getCanvas().style.cursor = '';
        onBusHover(null, null);
        tooltipRef.current?.remove();
      });
    };

    if (map.isStyleLoaded()) {
      onLoad();
    } else {
      map.once('load', onLoad);
    }
  }, [topology, onBusHover]);


    // Update binding-line highlights when meta changes
    useEffect(() => {
        const map = mapRef.current;
        if (!map || !map.getSource('lines')) return;

        const nextBinding = new Set(meta?.binding_lines?.map((bl) => bl.line) ?? []);

        // Clear previously-binding lines that aren't in the new set
        for (const lineId of prevBindingRef.current) {
            if (!nextBinding.has(lineId)) {
                map.setFeatureState({ source: 'lines', id: lineId }, { binding: false });
            }
        }
        // Mark current binding lines
        for (const lineId of nextBinding) {
            map.setFeatureState({ source: 'lines', id: lineId }, { binding: true });
        }
        prevBindingRef.current = nextBinding;
    }, [meta]);


  // Update bus colors when buses/viewMode changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !buses.length || !map.getSource('buses')) return;

    const normMap = normalizeFragility(buses);

    // Build LMP norm too
    const lmpVals = buses.map((b) => b.lmp ?? 0);
    const lmpMin = Math.min(...lmpVals);
    const lmpMax = Math.max(...lmpVals);
    const lmpRange = lmpMax - lmpMin || 1;

    for (const bus of buses) {
      let color: string;
      if (viewMode === 'fragility') {
        color = fragilityColor(normMap.get(bus.bus_id) ?? 0);
      } else {
        const normLmp = ((bus.lmp ?? 0) - lmpMin) / lmpRange;
        color = lmpColor(normLmp);
      }
      map.setFeatureState(
        { source: 'buses', id: bus.bus_id },
        { color }
      );
    }
  }, [buses, viewMode]);

  return (
    <>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      <canvas ref={canvasRef} style={{ display: 'none' }} />
      <style>{`
        .maplibregl-ctrl-group {
          background: #0f1217 !important;
          border: 1px solid #252d3a !important;
        }
        .maplibregl-ctrl-group button {
          background: transparent !important;
          border: none !important;
          padding: 0 !important;
        }
        .maplibregl-ctrl-zoom-in .maplibregl-ctrl-icon,
        .maplibregl-ctrl-zoom-out .maplibregl-ctrl-icon {
          filter: invert(1) opacity(0.6);
        }
        .grid-tooltip .maplibregl-popup-content {
          background: #0f1217;
          border: 1px solid #252d3a;
          border-radius: 4px;
          padding: 6px 10px;
          color: #e2e8f0;
          font-family: 'Space Mono', monospace;
          font-size: 11px;
          pointer-events: none;
        }
        .grid-tooltip .maplibregl-popup-tip { display: none; }
        .tip-id { color: #38bdf8; font-size: 11px; }
        .tip-zone { color: #8899aa; font-size: 10px; margin-top: 2px; }
      `}</style>
    </>
  );
}
