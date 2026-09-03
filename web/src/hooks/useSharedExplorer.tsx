import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { Outlet } from "react-router-dom";
import { useExplorerSession } from "./useExplorerSession";
import { useTimeCursor, snapToFrames } from "./useTimeCursor";

type Explorer = {
  session: ReturnType<typeof useExplorerSession>;
  cursor: ReturnType<typeof useTimeCursor>;
};

const ExplorerContext = createContext<Explorer | null>(null);

// Over the ~400ms play interval, so a URL write never lands mid-playback — it
// settles once scrubbing/playing stops.
const MIRROR_DEBOUNCE_MS = 500;

// One explorer instance, mounted once by ExplorerLayout above the Map / Matrix /
// Analysis routes. Because a layout route element stays mounted while you
// navigate among its child routes, the live session — window, timestamps,
// cursor — SURVIVES the hop between pages: no refetch, no wiped data, no loading
// flash. (Scoreboard is a sibling route, deliberately outside this provider.)
// It also binds the session to the URL time coordinate with two-way sync.
export function ExplorerProvider({ children }: { children: ReactNode }) {
  const cursor = useTimeCursor();
  const session = useExplorerSession({
    initialCursor: cursor.t,
    initialWindow:
      cursor.ws && cursor.we ? { start: cursor.ws, end: cursor.we } : null,
  });
  const { timestamps, currentIndex, setCurrentIndex } = session;

  const cursorRef = useRef(cursor);
  cursorRef.current = cursor;

  // index → URL: scrubbing (or a fresh window) mirrors the cursor hour + window
  // bounds into the URL, so the coordinate travels across pages. Debounced: each
  // index change reschedules the write, so continuous playback (a tick every
  // ~400ms) never lands one mid-play — it fires once motion settles. Writing a
  // router navigation every frame double-rendered the tree and starved the
  // playback timer, making the scrubber hang then catch up.
  useEffect(() => {
    if (!timestamps.length) return;
    const t = timestamps[currentIndex];
    const ws = timestamps[0];
    const we = timestamps[timestamps.length - 1];
    const timer = window.setTimeout(() => {
      const c = cursorRef.current;
      const same =
        c.t?.toISOString() === t?.toISOString() &&
        c.ws?.toISOString() === ws?.toISOString() &&
        c.we?.toISOString() === we?.toISOString();
      if (!same) c.setCoord({ t, ws, we }, { replace: true });
    }, MIRROR_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [timestamps, currentIndex]);

  // URL → index: when a page control moves ?t (e.g. the Analysis peak buttons),
  // snap the scrubber to match. Not keyed on currentIndex, so it never tugs
  // against the mirror; snapping the mirror's own output is a fixed point.
  const tKey = cursor.t ? cursor.t.getTime() : null;
  useEffect(() => {
    if (!timestamps.length || tKey == null) return;
    const i = snapToFrames(new Date(tKey), timestamps);
    if (i >= 0 && i !== currentIndex) setCurrentIndex(i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tKey, timestamps]);

  const value = useMemo(() => ({ session, cursor }), [session, cursor]);
  return (
    <ExplorerContext.Provider value={value}>{children}</ExplorerContext.Provider>
  );
}

// The layout element: provides the shared explorer, renders the active route.
export function ExplorerLayout() {
  return (
    <ExplorerProvider>
      <Outlet />
    </ExplorerProvider>
  );
}

export function useSharedExplorer(): Explorer {
  const ctx = useContext(ExplorerContext);
  if (!ctx)
    throw new Error("useSharedExplorer must be used within ExplorerProvider");
  return ctx;
}
