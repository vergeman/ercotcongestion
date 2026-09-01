import { useEffect, useState } from "react";
import { fetchMapSummary } from "../api/map";
import type { MapOverview } from "../api/types";
import type { ConnectionState } from "./useExplorerSession";

/** Loads map-wide, refit-stable resources independently from playback frames. */
export function useMapBootstrap(setConnectionState: (state: ConnectionState) => void) {
  const [topology, setTopology] = useState<unknown | null>(null);
  const [topologyReady, setTopologyReady] = useState(false);
  const [overview, setOverview] = useState<MapOverview | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchMapSummary(controller.signal)
      .then((summary) => {
        if (controller.signal.aborted) return;
        setTopology(summary.topology);
        setOverview(summary.overview);
        setConnectionState("ok");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !(error instanceof DOMException && error.name === "AbortError")) setConnectionState("error");
      })
      .finally(() => { if (!controller.signal.aborted) setTopologyReady(true); });
    return () => controller.abort();
  }, [setConnectionState]);

  return { topology, topologyReady, overview };
}
