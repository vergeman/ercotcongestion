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
  /** Mobile shows Forecast; desktop shows the selected view. */
  renderedView: MapView;
  showConstraints: boolean;
  setShowConstraints: (show: boolean) => void;
  handleView: (v: MapView) => void;
  handleDataMode: (d: MapDataMode) => void;
}

/** View, data-mode, and overlay transitions. */
export function useMapViewControls({
  view, setView, dataMode, setDataMode, isMobile,
}: MapViewControlsOptions): MapViewControls {
  const renderedView: MapView = isMobile ? "forecast" : view;
  const prevDataModeRef = useRef<MapDataMode>("congestion");
  const [showConstraints, setShowConstraints] = useState(
    isMobile || view === "forecast" || view === "error"
  );

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
    if (view === "error") return;
    setDataMode(d);
  }, [view, setDataMode]);

  return { renderedView, showConstraints, setShowConstraints, handleView, handleDataMode };
}
