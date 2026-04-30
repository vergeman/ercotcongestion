import { useState, useEffect, useRef, useCallback } from 'react';
import { format } from 'date-fns';

interface Props {
  timestamps: Date[];
  currentIndex: number;
  onIndexChange: (i: number) => void;
  loading: boolean;
}

export default function PlaybackScrubber({ timestamps, currentIndex, onIndexChange, loading }: Props) {
  const [playing, setPlaying] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const current = timestamps[currentIndex];

  const step = useCallback(
    (dir: 1 | -1) => {
      onIndexChange(Math.max(0, Math.min(timestamps.length - 1, currentIndex + dir)));
    },
    [currentIndex, timestamps.length, onIndexChange]
  );

  useEffect(() => {
    if (!playing) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }
    intervalRef.current = setInterval(() => {
      onIndexChange(Math.min(currentIndex + 1, timestamps.length - 1));
      if (currentIndex + 1 >= timestamps.length) setPlaying(false);
    }, 400);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [playing, timestamps.length, onIndexChange]);

  if (!timestamps.length) return (
    <div className="scrubber scrubber--empty">
      <span className="label">no data loaded</span>
    </div>
  );

  return (
    <div className="scrubber">
      <div className="scrubber__controls">
        <button onClick={() => step(-1)} disabled={currentIndex === 0}>‹</button>

        <button
          className={playing ? 'active' : ''}
          onClick={() => setPlaying((p) => !p)}
          style={{ width: 64, fontFamily: 'var(--text-mono)', letterSpacing: '0.05em' }}
        >
          {playing ? '⏸ PAUSE' : '▶ PLAY'}
        </button>

        <button onClick={() => step(1)} disabled={currentIndex >= timestamps.length - 1}>›</button>

        <div className="scrubber__ts mono">
          {current ? format(current, 'MMM d, yyyy HH:mm') + ' UTC' : '—'}
        </div>

        {loading && <div className="scrubber__loading">
          <span className="label">loading…</span>
        </div>}
      </div>

      <div className="scrubber__track">
        <input
          type="range"
          min={0}
          max={timestamps.length - 1}
          value={currentIndex}
          onChange={(e) => onIndexChange(Number(e.target.value))}
        />
        <div className="scrubber__range-labels">
          <span className="label">{timestamps[0] ? format(timestamps[0], 'MMM d HH:mm') : ''}</span>
          <span className="label">{timestamps[timestamps.length - 1] ? format(timestamps[timestamps.length - 1], 'MMM d HH:mm') : ''}</span>
        </div>
      </div>

      <style>{`
        .scrubber {
          height: var(--scrubber-h);
          background: var(--bg-panel);
          border-top: 1px solid var(--border);
          padding: 10px 16px 14px;
          display: flex;
          flex-direction: column;
          gap: 6px;
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
