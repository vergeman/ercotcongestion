import {
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { Outlet } from "react-router-dom";
import { useExplorerSession } from "./useExplorerSession";
import { useTimeCursor, snapToFrames } from "./useTimeCursor";
import { ExplorerContext } from "./sharedExplorerContext";

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

  useEffect(() => {
    cursorRef.current = cursor;
  }, [cursor]);

  // index → URL: scrubbing (or a fresh window) mirrors the cursor hour + window
  // bounds into the URL, so the coordinate travels across pages. Written
  // immediately (not debounced): a lagged write can land a stale hour after the
  // index moved on, and the URL→index effect below then snaps the scrubber
  // backward — so the URL must always reflect the current index exactly, keeping
  // that effect the no-op fixed point its comment describes.
  useEffect(() => {
    if (!timestamps.length) return;
    const t = timestamps[currentIndex];
    const ws = timestamps[0];
    const we = timestamps[timestamps.length - 1];
    const c = cursorRef.current;
    const same =
      c.t?.toISOString() === t?.toISOString() &&
      c.ws?.toISOString() === ws?.toISOString() &&
      c.we?.toISOString() === we?.toISOString();
    if (!same) c.setCoord({ t, ws, we }, { replace: true });
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
