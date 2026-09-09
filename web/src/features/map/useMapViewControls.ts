import { useCallback, useRef, useState } from "react";
import type { MapDataMode, MapView } from "../../api/types";

interface MapViewControlsOptions {
  view: MapView;
  setView: (v: MapView) => void;
  dataMode: MapDataMode;
  setDataMode: (d: MapDataMode) => void;
  isMobile: boolean;
}

export interface MapViewControls {
  /** The layout actually mounted: mobile is forced to Forecast, desktop honors `view`. */
  renderedView: MapView;
  showConstraints: boolean;
  setShowConstraints: (show: boolean) => void;
  handleView: (v: MapView) => void;
  handleDataMode: (d: MapDataMode) => void;
}

/**
 * Owns the view/data-mode transition rules: the constraint-overlay default per
 * view, and Error's congestion-only lock (remembering the prior data mode so
 * leaving Error restores it). Mobile always renders Forecast while keeping the
 * user's desktop choice in `view`.
 */
export function useMapViewControls({
  view, setView, dataMode, setDataMode, isMobile,
}: MapViewControlsOptions): MapViewControls {
  const renderedView: MapView = isMobile ? "forecast" : view;
  // Data selection held from before entering Error, so leaving it restores
  // rather than defaulting back to congestion.
  const prevDataModeRef = useRef<MapDataMode>("congestion");
  const [showConstraints, setShowConstraints] = useState(true);

  // Switch the view axis, applying that view's SF-overlay default: on in
  // Forecast and Error (the overlay is that view's own mechanism), off in
  // Compare (a per-pane explainer) and Market (no overlay). Entering Error locks
  // the data axis to congestion, remembering whatever was active so leaving it
  // restores rather than defaulting back.
  const handleView = useCallback((v: MapView) => {
    if (v === "error" && view !== "error") {
      prevDataModeRef.current = dataMode;
      setDataMode("congestion");
    } else if (v !== "error" && view === "error") {
      setDataMode(prevDataModeRef.current);
    }
    setView(v);
    setShowConstraints(v === "forecast" || v === "error");
  }, [view, dataMode, setView, setDataMode]);

  const handleDataMode = useCallback((d: MapDataMode) => {
    if (view === "error") return; // locked; the Header disables the chip too
    setDataMode(d);
  }, [view, setDataMode]);

  return { renderedView, showConstraints, setShowConstraints, handleView, handleDataMode };
}
