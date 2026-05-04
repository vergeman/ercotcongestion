import { useState, useEffect, useRef, useCallback } from "react";
import { format } from "date-fns";
import TimelineSparkline, { type SparkPoint } from "./TimelineSparkline";

interface Props {
  timestamps: Date[];
  currentIndex: number;
  onIndexChange: (i: number | ((prev: number) => number)) => void;
  loading: boolean;
  sparkSeries: SparkPoint[];
}

export default function PlaybackScrubber({
  timestamps,
  currentIndex,
  onIndexChange,
  loading,
  sparkSeries,
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

  if (!timestamps.length)
    return (
      <div className="scrubber scrubber--empty">
        <span className="label">no data loaded</span>
      </div>
    );

  return (
    <div className="scrubber">
      <div className="scrubber__controls">
        <button onClick={() => step(-1)} disabled={currentIndex === 0}>
          ‹
        </button>

        <button
          className={playing ? "active" : ""}
          onClick={() => {
            if (!playing && currentIndex >= timestamps.length - 1) {
              onIndexChange(0); // rewind
            }
            setPlaying((p) => !p);
          }}
          style={{
            width: 64,
            fontFamily: "var(--text-mono)",
            letterSpacing: "0.05em",
          }}
        >
          {playing ? "⏸ PAUSE" : "▶ PLAY"}
        </button>

        <button
          onClick={() => step(1)}
          disabled={currentIndex >= timestamps.length - 1}
        >
          ›
        </button>

        <div className="scrubber__ts mono">
          {current ? format(current, "MMM d, yyyy HH:mm") + " UTC" : "—"}
        </div>

        {loading && (
          <div className="scrubber__loading">
            <span className="label">loading…</span>
          </div>
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
          max={timestamps.length - 1}
          value={currentIndex}
          onChange={(e) => onIndexChange(Number(e.target.value))}
        />
        <div className="scrubber__range-labels">
          <span className="label">
            {timestamps[0] ? format(timestamps[0], "MMM d HH:mm") : ""}
          </span>
          <span className="label">
            {timestamps[timestamps.length - 1]
              ? format(timestamps[timestamps.length - 1], "MMM d HH:mm")
              : ""}
          </span>
        </div>
      </div>

      <style>{`
        .scrubber {
          background: var(--bg-panel);
          border-top: 1px solid var(--border);
          padding: 10px 16px 14px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          flex-shrink: 0;
        }
        .scrubber--empty {
          align-items: center;
          justify-content: center;
        }
        .scrubber__controls {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .scrubber__ts {
          font-size: 13px;
          color: var(--accent);
          margin-left: 8px;
          letter-spacing: 0.04em;
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
      `}</style>
    </div>
  );
}
