import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

// The one time coordinate the whole app shares, lifted into the URL so every
// page reads the same "when" and a shared link restores it. `t` is an absolute
// delivery hour (ISO UTC); `run` optionally scopes it to a forecast run — the
// Analysis dimension the Explorer cursor lacks (t+1 vs t+2 share a wall-clock
// hour); `span=day` marks the whole-day view, where the hour is intentionally
// unset. Page-owned selection state (a selected SP/pair) lives in the same query
// string and is preserved across every cursor change.
export interface TimeCursor {
  t: Date | null;
  run: string | null;
  wholeDay: boolean;
  // The explorer's loaded window [ws, we] — so a Map → Analysis → Map round-trip
  // restores the whole range you were looking at, not just the cursor hour.
  ws: Date | null;
  we: Date | null;
  // `t` is the representative/selected hour and `span=day` is the view; they are
  // independent, so the whole-day view can still carry the day's peak hour in
  // `t` for a clean hand-off to a scan surface. `replace` avoids a history entry
  // (used when mirroring the live scrubber into the URL).
  setT: (t: Date | null, opts?: { replace?: boolean }) => void;
  setRun: (run: string | null) => void;
  setWholeDay: (v: boolean) => void;
  // One patch for the explorer mirror: cursor hour + window bounds together, so
  // scrubbing writes a single history-less URL update.
  setCoord: (
    next: { t?: Date | null; ws?: Date | null; we?: Date | null },
    opts?: { replace?: boolean }
  ) => void;
}

const parseDate = (raw: string | null): Date | null => {
  if (!raw) return null;
  // Compact hour coordinates keep shared links legible. JavaScript's Date
  // parser requires minutes, so expand our URL form before parsing it.
  const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}Z$/.test(raw)
    ? `${raw.slice(0, -1)}:00Z`
    : raw;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
};

// Time-series data is hourly, so URL coordinates need no minute, second, or
// millisecond fields. Keep the explicit Z: a zone-less ISO value is interpreted
// as local browser time by Date, rather than UTC.
const formatCoordinate = (value: Date) => `${value.toISOString().slice(0, 13)}Z`;

// Nearest frame to an absolute instant — the projection every page runs to map
// the shared cursor onto its own (possibly sparse) domain. This is the seam:
// the cursor is continuous, each page's frames are whatever it can render.
// Returns -1 only for an empty domain. Mirrors the reduce the explorer session
// already uses to place a cursor in its window (useExplorerSession.ts:55).
export function snapToFrames(t: Date | null, frames: Date[]): number {
  if (frames.length === 0) return -1;
  if (!t) return 0;
  const target = t.getTime();
  return frames.reduce(
    (best, frame, i) =>
      Math.abs(frame.getTime() - target) <
      Math.abs(frames[best].getTime() - target)
        ? i
        : best,
    0
  );
}

export function useTimeCursor(): TimeCursor {
  const [params, setParams] = useSearchParams();

  const t = useMemo(() => parseDate(params.get("t")), [params]);
  const ws = useMemo(() => parseDate(params.get("ws")), [params]);
  const we = useMemo(() => parseDate(params.get("we")), [params]);

  const run = params.get("run");
  const wholeDay = params.get("span") === "day";

  // Merge into the live params (functional update) so nothing page-owned is
  // dropped when only the time changes.
  const patch = useCallback(
    (mut: (p: URLSearchParams) => void, replace = false) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          mut(next);
          return next;
        },
        { replace }
      );
    },
    [setParams]
  );

  const setT = useCallback(
    (next: Date | null, opts?: { replace?: boolean }) =>
      patch((p) => {
        if (next) p.set("t", formatCoordinate(next));
        else p.delete("t");
      }, opts?.replace),
    [patch]
  );

  const setRun = useCallback(
    (next: string | null) =>
      patch((p) => (next ? p.set("run", next) : p.delete("run"))),
    [patch]
  );

  const setWholeDay = useCallback(
    (v: boolean) => patch((p) => (v ? p.set("span", "day") : p.delete("span"))),
    [patch]
  );

  const setCoord = useCallback(
    (
      next: { t?: Date | null; ws?: Date | null; we?: Date | null },
      opts?: { replace?: boolean }
    ) =>
      patch((p) => {
        const apply = (k: "t" | "ws" | "we", v: Date | null | undefined) => {
          if (v === undefined) return; // key omitted → leave as-is
          if (v) p.set(k, formatCoordinate(v));
          else p.delete(k);
        };
        apply("t", next.t);
        apply("ws", next.ws);
        apply("we", next.we);
      }, opts?.replace),
    [patch]
  );

  return { t, run, wholeDay, ws, we, setT, setRun, setWholeDay, setCoord };
}
