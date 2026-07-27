import { type ReactNode, useState, useEffect, useRef, useCallback } from "react";
import TimelineSparkline, { type SparkPoint } from "./TimelineSparkline";
import Tooltip from "../ui/Tooltip";
import { formatCT } from "../../lib/time";

interface Props {
  timestamps: Date[];
  currentIndex: number;
  onIndexChange: (i: number | ((prev: number) => number)) => void;
  loading: boolean;
  sparkSeries: SparkPoint[];
  eventLabel?: string | null;
  // Rendered in the left column above the transport controls — App passes the
  // Load Window picker here so the button sits over the play/step buttons.
  leftSlot?: ReactNode;
}

export default function PlaybackScrubber({
  timestamps,
  currentIndex,
  onIndexChange,
  loading,
  sparkSeries,
  eventLabel,
  leftSlot,
}: Props) {
  const [playing, setPlaying] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const current = timestamps[currentIndex];

  const step = useCallback(
    (dir: 1 | -1) => {
      onIndexChange((prev) =>
        Math.max(0, Math.min(timestamps.length - 1, prev + dir))
      );
    },
    [timestamps.length, onIndexChange]
  );

  useEffect(() => {
    if (!playing) return;

    intervalRef.current = setInterval(() => {
      onIndexChange((prev) => {
        const next = prev + 1;
        if (next >= timestamps.length) {
          setPlaying(false);
          return prev;
        }
        return next;
      });
    }, 400);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [playing, timestamps.length, onIndexChange]);

  // Render the full scrubber even before data lands — just unpopulated — so the
  // first paint reserves its final height and the initial load never drops the
  // page layout (the "—" timestamp + empty sparkline stand in until data arrives).
  const hasData = timestamps.length > 0;

  return (
    <div className="scrubber">
      <div className="scrubber__left">
        {leftSlot}
        <div className="scrubber__controls">
          <button onClick={() => step(-1)} disabled={currentIndex === 0}>
            ‹
          </button>

          <button
            className={`playbtn${playing ? " active" : ""}`}
            disabled={!hasData}
            onClick={() => {
              if (!playing && currentIndex >= timestamps.length - 1) {
                onIndexChange(0); // rewind
              }
              setPlaying((p) => !p);
            }}
          >
            <span className="playbtn__icon">{playing ? "⏸" : "▶"}</span>
            <span className="playbtn__label">{playing ? "Pause" : "Play"}</span>
          </button>

          <button
            onClick={() => step(1)}
            disabled={currentIndex >= timestamps.length - 1}
          >
            ›
          </button>
        </div>
      </div>

      <div className="scrubber__main">
        <div className="scrubber__meta">
          {/* The label names what the cursor moves through, and is part of the
              timestamp rather than a separate chip — both panes are keyed on the
              hour power is priced FOR, which is the thing easiest to misread
              while scrubbing. */}
          <span className="scrubber__ts mono">
            <Tooltip
              className="scrubber__axis"
              tip={
                <>
                  The hourly settlement price power is priced <b>for</b>.
                </>
              }
            >
              Delivery hour
            </Tooltip>
            : {current ? formatCT(current, "MMM d, yyyy HH:mm") + " CT" : "—"}
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
        </div>

        <div className="scrubber__track">
          <TimelineSparkline
            series={sparkSeries}
            currentIndex={currentIndex}
            onSeek={(i) => onIndexChange(i)}
          />
          <input
            type="range"
            min={0}
            max={Math.max(0, timestamps.length - 1)}
            value={currentIndex}
            disabled={!hasData}
            onChange={(e) => onIndexChange(Number(e.target.value))}
          />
          <div className="scrubber__range-labels">
            <span className="label">
              {timestamps[0] ? formatCT(timestamps[0], "MMM d HH:mm") : ""}
            </span>
            <span className="label">
              {timestamps[timestamps.length - 1]
                ? formatCT(timestamps[timestamps.length - 1], "MMM d HH:mm") +
                  " CT"
                : ""}
            </span>
          </div>
        </div>
      </div>

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
        /* Left column: Load Window (top) over the transport buttons (bottom). */
        .scrubber__left {
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          gap: 6px;
          flex-shrink: 0;
          padding-right: 16px;
          border-right: 1px solid var(--border);
        }
        .scrubber__controls {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        /* ‹ › steppers: small, equal-size, centered — align-items:center on the
           row keeps them vertically centered against the taller play button. */
        .scrubber__controls button {
          height: 30px;
          min-width: 32px;
          padding: 0 10px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          line-height: 1;
        }
        /* The play/pause button owns the vertical space: taller, icon stacked
           over the label. Fixed size so it never shifts between the two states. */
        .scrubber__controls .playbtn {
          flex-direction: column;
          gap: 6px;
          height: 46px;
          width: 60px;
          padding: 4px 8px;
        }
        .playbtn__icon { font-size: 12px; line-height: 1; }
        .playbtn__label { font-size: 11px; line-height: 1; }
        /* Load Window fills the left column, so it spans the ‹ play › cluster
           below it; the column's width is set by that (wider) cluster. */
        .scrubber__left > .drp { width: 100%; }
        .scrubber__left > .drp > button {
          width: 100%;
          text-align: center;
        }
        .scrubber__main {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .scrubber__meta {
          display: flex;
          align-items: center;
          gap: 8px;
          min-height: 18px;
        }
        .scrubber__ts {
          font-size: 14px;
          color: var(--accent);
          letter-spacing: normal;
        }
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
        .scrubber__event-sep {
          color: var(--text-muted);
        }
        /* Inherits the timestamp's face, size and color — it reads as one string,
           not a chip beside one. Dotted underline marks the hoverable term. */
        .scrubber__axis {
          border-bottom: 1px dotted currentColor;
          cursor: help;
        }
        .scrubber__loading {
          margin-left: auto;
          opacity: 0.6;
        }
        .scrubber__track { display: flex; flex-direction: column; gap: 2px; }
        .scrubber__range-labels {
          display: flex;
          justify-content: space-between;
          opacity: 0.5;
        }
        @media (max-width: 767px) {
          .scrubber {
            flex-direction: column;
            gap: 6px;
            padding: 6px max(12px, env(safe-area-inset-right)) max(8px, env(safe-area-inset-bottom)) max(12px, env(safe-area-inset-left));
          }
          .scrubber__left { display: contents; }
          .scrubber__left > .drp { display: none; }
          .scrubber__controls {
            order: 2;
            justify-content: center;
            gap: 10px;
          }
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
          .scrubber__meta { justify-content: center; min-height: 16px; }
          .scrubber__ts { font-size: 13px; }
          .scrubber__event { display: none; }
          .scrubber__track .sparkline,
          .scrubber__range-labels { display: none; }
          input[type='range'] { height: 6px; }
          input[type='range']::-webkit-slider-thumb { width: 20px; height: 20px; }
        }
      `}</style>
    </div>
  );
}
