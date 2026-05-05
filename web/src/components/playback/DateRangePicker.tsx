import { useState } from "react";
import { format, subDays, subHours } from "date-fns";
import type { CuratedEvent } from "../../lib/events";

interface Props {
  onLoad: (start: Date, end: Date) => void;
  onSelectEvent?: (event: CuratedEvent) => void;
  events?: CuratedEvent[];
  activeEventId?: string | null;
  loading: boolean;
}

const PRESETS = [
  {
    label: "Last 6h",
    start: () => subHours(new Date(), 6),
    end: () => new Date(),
  },
  {
    label: "Last 24h",
    start: () => subDays(new Date(), 1),
    end: () => new Date(),
  },
  {
    label: "Last 3d",
    start: () => subDays(new Date(), 3),
    end: () => new Date(),
  },
  {
    label: "Last 7d",
    start: () => subDays(new Date(), 7),
    end: () => new Date(),
  },
];

export default function DateRangePicker({
  onLoad,
  onSelectEvent,
  events,
  activeEventId,
  loading,
}: Props) {
  const [open, setOpen] = useState(false);
  const [startStr, setStartStr] = useState(() =>
    format(subDays(new Date(), 1), "yyyy-MM-dd'T'HH:mm")
  );
  const [endStr, setEndStr] = useState(() =>
    format(new Date(), "yyyy-MM-dd'T'HH:mm")
  );

  const handlePreset = (start: () => Date, end: () => Date) => {
    const s = start();
    const e = end();
    setStartStr(format(s, "yyyy-MM-dd'T'HH:mm"));
    setEndStr(format(e, "yyyy-MM-dd'T'HH:mm"));
    onLoad(s, e);
    setOpen(false);
  };

  const handleCustomLoad = () => {
    onLoad(new Date(startStr), new Date(endStr));
    setOpen(false);
  };

  const handleEventClick = (ev: CuratedEvent) => {
    onSelectEvent?.(ev);
    setOpen(false);
  };

  return (
    <div className="drp">
      <button
        onClick={() => setOpen((o) => !o)}
        style={{ fontFamily: "var(--text-mono)", fontSize: 11 }}
      >
        📅 Load Window
      </button>

      {open && (
        <div className="drp__dropdown">
          {events && events.length > 0 && (
            <div className="drp__events">
              <div className="label drp__section-label">Curated events</div>
              <div className="drp__event-list">
                {events.map((ev) => (
                  <button
                    key={ev.id}
                    className={`drp__event ${
                      activeEventId === ev.id ? "active" : ""
                    }`}
                    onClick={() => handleEventClick(ev)}
                    disabled={loading}
                  >
                    <div className="drp__event-label">{ev.label}</div>
                    <div className="drp__event-desc">{ev.description}</div>
                  </button>
                ))}
              </div>
              <div className="drp__divider" />
            </div>
          )}

          <div className="label drp__section-label">Recent</div>
          <div className="drp__presets">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => handlePreset(p.start, p.end)}
                disabled={loading}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div className="label drp__section-label">Custom range</div>
          <div className="drp__custom">
            <div className="drp__row">
              <span className="label">Start</span>
              <input
                type="datetime-local"
                value={startStr}
                onChange={(e) => setStartStr(e.target.value)}
              />
            </div>
            <div className="drp__row">
              <span className="label">End</span>
              <input
                type="datetime-local"
                value={endStr}
                onChange={(e) => setEndStr(e.target.value)}
              />
            </div>
            <button
              onClick={handleCustomLoad}
              disabled={loading}
              className="drp__load-btn"
            >
              {loading ? "Loading…" : "Load"}
            </button>
          </div>
        </div>
      )}

      <style>{`
        .drp { position: relative; }
        .drp__dropdown {
          position: absolute;
          bottom: 100%;
          left: 0;
          margin-bottom: 4px;
          background: var(--bg-panel);
          border: 1px solid var(--border-bright);
          border-radius: 4px;
          padding: 10px;
          width: 280px;
          z-index: 100;
          box-shadow: 0 4px 20px rgba(0,0,0,0.5);
          max-height: 70vh;
          overflow-y: auto;
        }
        .drp__section-label {
          color: var(--text-muted);
          margin-bottom: 6px;
          display: block;
        }
        .drp__events { margin-bottom: 8px; }
        .drp__event-list {
          display: flex;
          flex-direction: column;
          gap: 3px;
        }
        .drp__event {
          /* Override the base button styles: full-width, left-aligned, multi-line. */
          display: block;
          width: 100%;
          text-align: left;
          padding: 6px 8px;
          font-size: 12px;
          line-height: 1.3;
          border: 1px solid transparent;
          background: var(--bg-surface);
        }
        .drp__event:hover:not(:disabled) {
          background: var(--bg-hover);
          border-color: var(--border-bright);
        }
        .drp__event.active {
          background: var(--accent-dim);
          border-color: var(--accent);
        }
        .drp__event-label {
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 600;
          font-size: 12px;
          letter-spacing: 0.04em;
          color: var(--text-primary);
        }
        .drp__event.active .drp__event-label { color: var(--accent); }
        .drp__event-desc {
          font-size: 10px;
          color: var(--text-secondary);
          margin-top: 2px;
          font-weight: 400;
          font-family: 'Barlow', sans-serif;
          letter-spacing: 0;
          text-transform: none;
        }
        .drp__divider {
          height: 1px;
          background: var(--border);
          margin: 10px 0;
        }
        .drp__presets {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          margin-bottom: 10px;
        }
        .drp__custom { display: flex; flex-direction: column; gap: 6px; }
        .drp__row { display: flex; flex-direction: column; gap: 2px; }
        .drp__row input {
          background: var(--bg-surface);
          border: 1px solid var(--border);
          color: var(--text-primary);
          font-size: 11px;
          font-family: var(--text-mono);
          padding: 4px 6px;
          border-radius: 3px;
          width: 100%;
        }
        .drp__load-btn {
          margin-top: 4px;
          background: var(--accent-dim);
          border-color: var(--accent);
          color: var(--accent);
          font-weight: 600;
        }
      `}</style>
    </div>
  );
}
