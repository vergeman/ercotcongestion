import { useEffect, useState } from "react";
import { subDays, subHours } from "date-fns";
import type { CuratedEvent } from "../../lib/events";
import { ctInputToUtc, utcToCTInputString } from "../../lib/time";

interface Props {
  onLoad?: (start: Date, end: Date) => void;
  // The Brief uses the same popover and curated-event list, but a delivery day
  // is one CT calendar date rather than a rolling range.
  singleDate?: boolean;
  onLoadDate?: (date: string) => void;
  selectedDate?: string | null;
  onSelectEvent?: (event: CuratedEvent) => void;
  events?: CuratedEvent[];
  activeEventId?: string | null;
  loading: boolean;
  inline?: boolean;
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
  singleDate = false,
  onLoadDate,
  selectedDate,
  onSelectEvent,
  events,
  activeEventId,
  loading,
  inline = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const [startStr, setStartStr] = useState(() =>
    utcToCTInputString(subDays(new Date(), 1))
  );
  const [endStr, setEndStr] = useState(() => utcToCTInputString(new Date()));
  const [dateStr, setDateStr] = useState(() => utcToCTInputString(new Date()).slice(0, 10));

  // The Brief's selected delivery day is URL-owned. Keep its date field in
  // step when navigation or a curated event changes that coordinate elsewhere.
  useEffect(() => {
    if (singleDate && selectedDate) setDateStr(selectedDate);
  }, [singleDate, selectedDate]);

  const handlePreset = (start: () => Date, end: () => Date) => {
    const s = start();
    const e = end();
    setStartStr(utcToCTInputString(s));
    setEndStr(utcToCTInputString(e));
    onLoad?.(s, e);
    setOpen(false);
  };

  const handleCustomLoad = () => {
    onLoad?.(ctInputToUtc(startStr), ctInputToUtc(endStr));
    setOpen(false);
  };

  const handleDateLoad = () => {
    onLoadDate?.(dateStr);
    setOpen(false);
  };

  const handleEventClick = (ev: CuratedEvent) => {
    onSelectEvent?.(ev);
    setOpen(false);
  };

  return (
    <div className={`drp${inline ? " drp--inline" : ""}${singleDate ? " drp--date" : ""}`}>
      {!inline && <button onClick={() => setOpen((o) => !o)}>📅 Load {singleDate ? "Date" : "Window"}</button>}

      {(inline || open) && (
        <div className="drp__dropdown">
          {!inline && (
            <button
              className="drp__close"
              onClick={() => setOpen(false)}
              aria-label="Close"
            >
              ✕
            </button>
          )}
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

          {!singleDate && <>
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
          </>}

          <div className="label drp__section-label">{singleDate ? "Date (CT)" : "Custom range (CT)"}</div>
          <div className="drp__custom">
            {singleDate ? (
              <div className="drp__row">
                <span className="label">Delivery date (CT)</span>
                <input type="date" value={dateStr} onChange={(e) => setDateStr(e.target.value)} />
              </div>
            ) : <>
              <div className="drp__row">
                <span className="label">Start (CT)</span>
                <input type="datetime-local" value={startStr} onChange={(e) => setStartStr(e.target.value)} />
              </div>
              <div className="drp__row">
                <span className="label">End (CT)</span>
                <input type="datetime-local" value={endStr} onChange={(e) => setEndStr(e.target.value)} />
              </div>
            </>}
            <button
              onClick={singleDate ? handleDateLoad : handleCustomLoad}
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
          max-height: 90vh;
          overflow-y: auto;
        }
        .drp--date .drp__dropdown { top: 100%; bottom: auto; margin: 4px 0 0; }
        .drp__close {
          position: absolute;
          top: 6px;
          right: 6px;
          width: 20px;
          height: 20px;
          padding: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          background: none;
          border: none;
          border-radius: 3px;
          color: var(--text-muted);
          font-size: 12px;
          line-height: 1;
          cursor: pointer;
        }
        .drp__close:hover {
          color: var(--text-primary);
          background: var(--bg-hover);
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
          font-size: 13px;
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
          font-family: var(--font-label);
          font-weight: 600;
          font-size: 13px;
          letter-spacing: normal;
          color: var(--text-primary);
        }
        .drp__event.active .drp__event-label { color: var(--accent); }
        .drp__event-desc {
          font-size: 11px;
          color: var(--text-secondary);
          margin-top: 2px;
          font-weight: 400;
          font-family: var(--font-sans);
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
          font-size: 12px;
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
        .drp--inline .drp__dropdown {
          position: static;
          width: 100%;
          max-height: none;
          margin: 0;
          padding: 0;
          border: 0;
          box-shadow: none;
          overflow: visible;
        }
      `}</style>
    </div>
  );
}
