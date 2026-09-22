import {
  type ReactNode,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import TimelineSparkline, {
  TimelineSparklineLegend,
  type SparkPoint,
} from "./TimelineSparkline";
import Tooltip from "../ui/Tooltip";
import { formatCT } from "../../lib/time";

// Shared playback controls. Each page supplies its own frames and labels.
interface Props {
  frames: Date[];
  index: number;
  onSeek: (i: number | ((prev: number) => number)) => void;

  frameLabel: (t: Date) => string;
  rangeLabel?: (t: Date) => string;
  axisLabel?: ReactNode;
  axisTip?: ReactNode;

  canPlay?: boolean;
  playIntervalMs?: number;
  stepUnit?: string;

  sparkSeries?: SparkPoint[];
  loading?: boolean;
  eventLabel?: string | null;
  leftSlot?: ReactNode;
  rightSlot?: ReactNode;

  autoPlay?: boolean;
  onAutoPlayConsumed?: () => void;
}

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

export default function TimeTransport({
  frames,
  index,
  onSeek,
  frameLabel,
  rangeLabel,
  axisLabel = "Time",
  axisTip,
  canPlay = true,
  playIntervalMs = 400,
  stepUnit = "step",
  sparkSeries = [],
  loading = false,
  eventLabel,
  leftSlot,
  rightSlot,
  autoPlay = false,
  onAutoPlayConsumed,
}: Props) {
  const [playing, setPlaying] = useState(false);

  const hasData = frames.length > 0;
  const current = frames[index];
  const endCap = rangeLabel ?? frameLabel;
  // Mark Central-time delivery-day boundaries.
  const dayMarkers = useMemo(
    () =>
      frames.flatMap((frame, i) =>
        // day indicators: set daily marker (e.g 'Jan 30' no time)
        // as timeline label unless it's the last day: avoids last label bleeding into
        // start/end date range markers (with hours)
        i > 0 &&
        i < frames.length - 1 &&
        formatCT(frame, "yyyy-MM-dd") !== formatCT(frames[i - 1], "yyyy-MM-dd")
          ? [{ index: i, label: formatCT(frame, "MMM d") }]
          : []
      ),
    [frames]
  );

  const step = useCallback(
    (dir: 1 | -1) => {
      onSeek((prev) => Math.max(0, Math.min(frames.length - 1, prev + dir)));
    },
    [frames.length, onSeek]
  );

  // Use animation frames so slow renders do not queue playback steps.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      if (now - last >= playIntervalMs) {
        last = now;
        onSeek((prev) => {
          const next = prev + 1;
          if (next >= frames.length) {
            setPlaying(false);
            return prev;
          }
          return next;
        });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, frames.length, onSeek, playIntervalMs]);

  useEffect(() => {
    if (!canPlay && playing) queueMicrotask(() => setPlaying(false));
  }, [canPlay, playing]);

  useEffect(() => {
    if (!autoPlay || !canPlay || !hasData) return;
    onAutoPlayConsumed?.();
    if (prefersReducedMotion()) return;
    if (index >= frames.length - 1) onSeek(0);
    queueMicrotask(() => setPlaying(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPlay, canPlay, hasData, onAutoPlayConsumed]);

  return (
    <div className="scrubber">
      <div className="scrubber__left">
        {leftSlot}
        <div className="scrubber__controls">
          <button
            onClick={() => step(-1)}
            disabled={index <= 0}
            aria-label={`Previous ${stepUnit}`}
          >
            ‹
          </button>

          {canPlay && (
            <button
              className={`playbtn${playing ? " active" : ""}`}
              disabled={!hasData}
              onClick={() => {
                if (!playing && index >= frames.length - 1) onSeek(0); // rewind
                setPlaying((p) => !p);
              }}
            >
              <span className="playbtn__icon">{playing ? "⏸" : "▶"}</span>
              <span className="playbtn__label">
                {playing ? "Pause" : "Play"}
              </span>
            </button>
          )}

          <button
            onClick={() => step(1)}
            disabled={index < 0 || index >= frames.length - 1}
            aria-label={`Next ${stepUnit}`}
          >
            ›
          </button>
        </div>
      </div>

      <div className="scrubber__main">
        <div className="scrubber__meta">
          <span className="scrubber__ts mono">
            {axisTip ? (
              <Tooltip className="scrubber__axis" tip={axisTip}>
                {axisLabel}
              </Tooltip>
            ) : (
              axisLabel
            )}
            : {current ? frameLabel(current) : "—"}
          </span>

          {eventLabel && (
            <span className="scrubber__event">
              <span className="scrubber__event-sep">·</span>
              <span className="scrubber__event-label">{eventLabel}</span>
            </span>
          )}

          {loading && (
            <span className="scrubber__loading">
              <span className="label">loading…</span>
            </span>
          )}

          <TimelineSparklineLegend />
        </div>

        <div className="scrubber__track">
          <TimelineSparkline
            series={sparkSeries}
            currentIndex={index}
            onSeek={(i) => onSeek(i)}
          />
          <input
            type="range"
            min={0}
            max={Math.max(0, frames.length - 1)}
            value={Math.max(0, index)}
            disabled={!hasData}
            onChange={(e) => onSeek(Number(e.target.value))}
          />
          <div className="scrubber__range-labels">
            <span className="label">{frames[0] ? endCap(frames[0]) : ""}</span>
            {dayMarkers.map(({ index: dayIndex, label }) => (
              <span
                key={dayIndex}
                className="scrubber__day-marker label"
                style={{ left: `${(dayIndex / (frames.length - 1)) * 100}%` }}
              >
                {label}
              </span>
            ))}
            <span className="label">
              {frames.length ? endCap(frames[frames.length - 1]) : ""}
            </span>
          </div>
        </div>
      </div>

      {rightSlot && <div className="scrubber__right">{rightSlot}</div>}

      <style>{`
        .scrubber {
          background: var(--bg-panel);
          border-top: 1px solid var(--border);
          padding: 6px 16px 8px;
          display: flex;
          flex-direction: row;
          align-items: stretch;
          gap: 16px;
          flex-shrink: 0;
        }
        .scrubber__left {
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          gap: 6px;
          flex-shrink: 0;
          padding-right: 16px;
          border-right: 1px solid var(--border);
        }
        .scrubber__controls { display: flex; align-items: center; gap: 6px; }
        .scrubber__controls button {
          height: 30px;
          min-width: 32px;
          padding: 0 10px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          line-height: 1;
        }
        .scrubber__controls .playbtn {
          flex-direction: column;
          gap: 6px;
          height: 46px;
          width: 60px;
          padding: 4px 8px;
        }
        .playbtn__icon { font-size: 12px; line-height: 1; }
        .playbtn__label { font-size: 11px; line-height: 1; }
        .scrubber__left > .drp { width: 100%; }
        .scrubber__left > .drp > button { width: 100%; text-align: center; }
        .scrubber__main { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: space-between; gap: 2px; }
        .scrubber__meta { display: flex; align-items: center; gap: 8px; min-height: 18px; }
        .scrubber__ts { font-size: 14px; color: var(--accent); letter-spacing: normal; }
        .scrubber__event {
          display: flex;
          align-items: center;
          gap: 6px;
          font-family: var(--font-label);
          font-weight: var(--fw-label);
          font-size: 13px;
          letter-spacing: var(--track-label);
          color: var(--text-secondary);
        }
        .scrubber__event-sep { color: var(--text-muted); }
        .scrubber__axis { border-bottom: 1px dotted currentColor; cursor: help; }
        .scrubber__loading { margin-left: auto; opacity: 0.6; }
        .sparkline { position: relative; width: 100%; flex-shrink: 0; }
        .sparkline--empty { opacity: 0.2; }
        .sparkline__legend {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          flex-wrap: wrap;
          margin-left: auto;
          font-size: var(--fs-body);
          color: var(--text-muted);
          font-family: var(--font-sans);
          line-height: 1;
        }
        .sparkline__sw {
          display: inline-block;
          width: 12px;
          height: 2px;
          vertical-align: middle;
          margin-right: 4px;
        }
        .scrubber__track { display: flex; flex-direction: column; gap: 2px; }
        .scrubber__range-labels { position: relative; display: flex; justify-content: space-between; opacity: 0.5; }
        .scrubber__day-marker { position: absolute; transform: translateX(-50%); white-space: nowrap; }
        /* Right column mirrors the left: a page-owned control (e.g. whole-day). */
        .scrubber__right {
          display: flex;
          align-items: center;
          flex-shrink: 0;
          padding-left: 16px;
          border-left: 1px solid var(--border);
        }
        @media (max-width: 767px) {
          .scrubber {
            flex-direction: column;
            gap: 6px;
            padding: 6px max(12px, env(safe-area-inset-right)) max(8px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left));
          }
          .scrubber__left { display: contents; }
          .scrubber__left > .drp { display: none; }
          .scrubber__controls { order: 2; justify-content: center; gap: 10px; }
          .scrubber__controls button { min-width: 40px; height: 36px; }
          .scrubber__controls .playbtn {
            flex-direction: row;
            gap: 7px;
            width: auto;
            min-width: 82px;
            height: 36px;
            padding: 4px 12px;
          }
          .scrubber__main { order: 1; }
          .scrubber__right { order: 3; border-left: none; padding-left: 0; justify-content: center; }
          .scrubber__meta { justify-content: center; min-height: 16px; }
          .scrubber__ts { font-size: 13px; }
          .scrubber__event { display: none; }
          .sparkline__legend { display: none; }
          .scrubber__track .sparkline,
          .scrubber__range-labels { display: none; }
          input[type='range'] { height: 6px; }
          input[type='range']::-webkit-slider-thumb { width: 20px; height: 20px; }
        }
      `}</style>
    </div>
  );
}
