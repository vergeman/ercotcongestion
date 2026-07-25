import { useCallback, useEffect, useState } from "react";

export type ExplorerWorkspace = "map" | "matrix";

interface ExplorerRoute {
  workspace: ExplorerWorkspace;
  search: string;
}

function workspaceForPath(pathname: string): ExplorerWorkspace {
  return pathname.startsWith("/matrix") ? "matrix" : "map";
}

/**
 * Small client-side router for the two explorer workspaces. Query strings stay
 * intact by default, while callers may deliberately supply a workspace-owned
 * deep-link selection.
 */
export function useExplorerRoute() {
  const readRoute = (): ExplorerRoute => ({
    workspace: workspaceForPath(window.location.pathname),
    search: window.location.search,
  });
  const [route, setRoute] = useState<ExplorerRoute>(readRoute);

  useEffect(() => {
    const onPopState = () => setRoute(readRoute());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((next: ExplorerWorkspace, search = window.location.search) => {
    const pathname = next === "map" ? "/map" : "/matrix";
    if (window.location.pathname !== pathname || window.location.search !== search) {
      window.history.pushState(null, "", pathname + search + window.location.hash);
    }
    setRoute({ workspace: next, search });
  }, []);

  return { ...route, navigate };
}
