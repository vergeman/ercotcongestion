import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MapDataMode, MapView } from "../../api/types";
import {
  type MapTarget,
  parseMapTarget,
  parseMapViewState,
} from "../../lib/mapLinks";

interface MapRouteStateOptions {
  search: string;
  onChange: (search: string) => void;
}

/**
 * Adapts the Map's URL contract to local presentation state.  Writes start from
 * the current search string so shared cursor coordinates and autoPlay survive
 * view, data, and selection changes.
 */
export function useMapRouteState({ search, onChange }: MapRouteStateOptions) {
  const initial = useMemo(() => parseMapViewState(search), [search]);
  const [view, setView] = useState<MapView>(initial.view);
  const [dataMode, setDataMode] = useState<MapDataMode>(initial.data);
  const target = useMemo(() => parseMapTarget(search), [search]);
  const lastWrittenSearch = useRef<string | null>(null);
  const observedSearch = useRef(search);

  const write = useCallback((patch: Record<string, string | null>) => {
    const params = new URLSearchParams(search);
    for (const [key, value] of Object.entries(patch)) {
      if (value == null) params.delete(key);
      else params.set(key, value);
    }
    const next = `?${params.toString()}`;
    if (next !== search) {
      lastWrittenSearch.current = next;
      onChange(next);
    }
  }, [search, onChange]);

  const selectTarget = useCallback((next: MapTarget) => {
    write({
      constraint: next.kind === "constraint" ? next.value : null,
      sp: next.kind === "sp" ? next.value : null,
    });
  }, [write]);

  // The Map stays mounted across workspace navigation. Apply a genuinely
  // incoming deep link without treating the URL echo from our own write as a
  // competing source of truth.
  useEffect(() => {
    if (observedSearch.current === search) return;
    observedSearch.current = search;
    if (lastWrittenSearch.current === search) {
      lastWrittenSearch.current = null;
      return;
    }
    const incoming = parseMapViewState(search);
    setView(incoming.view);
    setDataMode(incoming.data);
  }, [search]);

  useEffect(() => {
    const parsed = parseMapViewState(search);
    if (parsed.view !== view || parsed.data !== dataMode) {
      write({ view, data: dataMode });
    }
  }, [view, dataMode, search, write]);

  return { view, setView, dataMode, setDataMode, target, selectTarget };
}
