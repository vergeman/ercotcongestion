import { useCallback } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import Header from "./components/layout/Header";
import ExplorerScrubber from "./components/playback/ExplorerScrubber";
import { useSharedExplorer } from "./hooks/sharedExplorerContext";
import { hasAutoPlayRequest, stripAutoPlay } from "./lib/mapLinks";
import MapWorkspace from "./workspaces/MapWorkspace";
import MatrixWorkspace from "./workspaces/MatrixWorkspace";

/** Persistent route shell shared by the Brief, Map, and Matrix pages. */
export default function App() {
  return <Outlet />;
}

/** Persistent live-data shell shared by the Map and Matrix workspaces. */
export function ExplorerApp() {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const workspace = location.pathname.startsWith("/matrix") ? "matrix" : "map";
  const navigate = useCallback(
    (next: "map" | "matrix", search = location.search) => {
      routerNavigate({ pathname: next === "map" ? "/map" : "/matrix", search });
    },
    [location.search, routerNavigate]
  );

  const withCoord = useCallback(
    (selectionSearch: string) => {
      const out = new URLSearchParams(selectionSearch);
      const cur = new URLSearchParams(location.search);
      for (const k of [
        "t",
        "ws",
        "we",
        "span",
        "run",
        "view",
        "data",
        "autoPlay",
      ]) {
        if (out.has(k)) continue;
        const v = cur.get(k);
        if (v) out.set(k, v);
      }
      return out.toString();
    },
    [location.search]
  );

  const { session } = useSharedExplorer();
  const { timestamps, currentIndex, connectionState, lastUpdated } = session;
  const autoPlayRequested = hasAutoPlayRequest(location.search);
  const consumeAutoPlay = useCallback(() => {
    routerNavigate(
      { pathname: location.pathname, search: stripAutoPlay(location.search) },
      { replace: true }
    );
  }, [location.pathname, location.search, routerNavigate]);

  return (
    <div className="app-shell">
      {/* Keep MapWorkspace alive across route changes: its map-only state and
          one-time map requests survive a visit to Matrix. */}
      <div style={{ display: workspace === "map" ? "contents" : "none" }}>
        <MapWorkspace
          session={session}
          onNavigate={navigate}
          routeSearch={location.search}
          onSelectionRouteChange={(search) =>
            navigate("map", withCoord(search))
          }
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
            lastUpdated={lastUpdated}
            connectionState={connectionState}
          />
          <MatrixWorkspace
            timestamp={timestamps[currentIndex] ?? null}
            routeSearch={location.search}
            onSelectionRouteChange={(search) =>
              navigate("matrix", withCoord(search))
            }
            onNavigateToMap={(search) => navigate("map", withCoord(search))}
          />
        </>
      )}

      <ExplorerScrubber
        session={session}
        autoPlay={autoPlayRequested}
        onAutoPlayConsumed={consumeAutoPlay}
      />
    </div>
  );
}
