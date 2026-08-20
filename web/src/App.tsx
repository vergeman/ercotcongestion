import { useCallback } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import Header from "./components/layout/Header";
import ExplorerScrubber from "./components/playback/ExplorerScrubber";
import { useSharedExplorer } from "./hooks/useSharedExplorer";
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
  const navigate = useCallback((next: "map" | "matrix", search = location.search) => {
    routerNavigate({ pathname: next === "map" ? "/map" : "/matrix", search });
  }, [location.search, routerNavigate]);
  // A workspace's selection search (matrixSearch / mapTargetSearch) carries only
  // its own keys and would otherwise clobber the shared time coordinate. Patch
  // in the coordinate (t / ws / we / span / run), the Map's view/data axes
  // (0131), and a still-unconsumed `autoPlay` request from the current URL —
  // but only where `selectionSearch` doesn't already have an opinion, so an
  // explicit view/data change (MapWorkspace's own view-sync effect) isn't
  // immediately overwritten by the value it's replacing. `autoPlay` matters
  // here specifically: the view-sync effect's own downgrade (no settled data
  // yet → forecast) fires a navigation through this same path exactly when a
  // hero `autoPlay=true` link lands pre-settlement, and without carrying it
  // forward that navigation would silently drop the request before the
  // transport ever gets to consume it — a real loss, not the one-shot
  // "consumed" contract `stripAutoPlay` implements deliberately elsewhere.
  const withCoord = useCallback(
    (selectionSearch: string) => {
      const out = new URLSearchParams(selectionSearch);
      const cur = new URLSearchParams(location.search);
      for (const k of ["t", "ws", "we", "span", "run", "view", "data", "autoPlay"]) {
        if (out.has(k)) continue;
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

  // `autoPlay=true` (0131) requests exactly one playback on arrival — the
  // Brief hero's "watch it move" link. The transport (mounted here, once,
  // shared by Map and Matrix) consumes the request once it can actually act
  // on it and reports back so the param is stripped with a replace nav — no
  // history entry, and nothing to replay on a later in-session navigation.
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

      <ExplorerScrubber
        session={session}
        autoPlay={autoPlayRequested}
        onAutoPlayConsumed={consumeAutoPlay}
      />
    </div>
  );
}
