import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Header from "./components/layout/Header";
import ExplorerScrubber from "./components/playback/ExplorerScrubber";
import { useSharedExplorer } from "./hooks/useSharedExplorer";
import MapWorkspace from "./workspaces/MapWorkspace";
import MatrixWorkspace from "./workspaces/MatrixWorkspace";

/** Persistent live-data shell shared by the Map and Matrix workspaces. */
export default function App() {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const workspace = location.pathname.startsWith("/matrix") ? "matrix" : "map";
  const navigate = useCallback((next: "map" | "matrix", search = location.search) => {
    routerNavigate({ pathname: next === "map" ? "/map" : "/matrix", search });
  }, [location.search, routerNavigate]);
  // A workspace's selection search (matrixSearch / mapTargetSearch) carries only
  // its own keys and would otherwise clobber the shared time coordinate. Merge
  // the coordinate (t / ws / we / span / run) from the current URL back on top
  // of any selection change before navigating.
  const withCoord = useCallback(
    (selectionSearch: string) => {
      const out = new URLSearchParams(selectionSearch);
      const cur = new URLSearchParams(location.search);
      for (const k of ["t", "ws", "we", "span", "run"]) {
        const v = cur.get(k);
        if (v) out.set(k, v);
      }
      return out.toString();
    },
    [location.search]
  );
  // Shared explorer: the live session bound to the URL time coordinate (mount
  // load + two-way scrubber↔URL sync). Map and Analysis use the same hook.
  const { session } = useSharedExplorer();
  const { timestamps, currentIndex, connectionState, lastUpdated } = session;

  return (
    <div className="app-shell">
      {/* Keep MapWorkspace alive across route changes: its map-only state and
          one-time map requests survive a visit to Matrix. */}
      <div style={{ display: workspace === "map" ? "contents" : "none" }}>
        <MapWorkspace
          session={session}
          onNavigate={navigate}
          routeSearch={location.search}
          onSelectionRouteChange={(search) => navigate("map", withCoord(search))}
        />
      </div>

      {workspace === "matrix" && (
        <>
          <Header
            activeWorkspace="matrix"
            onNavigate={navigate}
            view="forecast"
            onView={() => {}}
            dataMode="congestion"
            onDataMode={() => {}}
            marketAvailable={false}
            lastUpdated={lastUpdated}
            connectionState={connectionState}
          />
          <MatrixWorkspace
            timestamp={timestamps[currentIndex] ?? null}
            routeSearch={location.search}
            onSelectionRouteChange={(search) => navigate("matrix", withCoord(search))}
            onNavigateToMap={(search) => navigate("map", withCoord(search))}
          />
        </>
      )}

      <ExplorerScrubber session={session} />
    </div>
  );
}
