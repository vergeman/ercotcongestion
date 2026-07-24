import { useCallback, useEffect, useState } from "react";

export type ExplorerWorkspace = "map" | "matrix";

function workspaceForPath(pathname: string): ExplorerWorkspace {
  return pathname.startsWith("/matrix") ? "matrix" : "map";
}

/**
 * Small client-side router for the two explorer workspaces. It deliberately
 * keeps the query string untouched: later explorer views can own their own
 * deep-link parameters without the shell needing to understand them.
 */
export function useExplorerRoute() {
  const [workspace, setWorkspace] = useState<ExplorerWorkspace>(() =>
    workspaceForPath(window.location.pathname)
  );

  useEffect(() => {
    const onPopState = () => setWorkspace(workspaceForPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((next: ExplorerWorkspace) => {
    const pathname = next === "map" ? "/map" : "/matrix";
    if (window.location.pathname !== pathname) {
      window.history.pushState(null, "", pathname + window.location.search + window.location.hash);
    }
    setWorkspace(next);
  }, []);

  return { workspace, navigate };
}
