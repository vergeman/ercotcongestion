import type { Palette } from "../../api/types";

interface Props {
  palette: Palette;
  onPalette: (v: Palette) => void;
  lastUpdated: Date | null;
  connectionState: "ok" | "error" | "loading";
  // Constraint overlay toggle. Absent handler → the control is hidden (e.g.
  // before the overlay has loaded).
  showConstraints?: boolean;
  onToggleConstraints?: (v: boolean) => void;
}

export default function Header({
  palette,
  onPalette,
  lastUpdated,
  connectionState,
  showConstraints,
  onToggleConstraints,
}: Props) {
  return (
    <header className="header">
      <div className="header__brand">
        <span className="header__logo">⚡</span>
        <span className="header__title">ERCOT Stress</span>
        <span className="header__sub label">
          settlement points · realized ERCOT
        </span>
      </div>

      <div className="header__controls">
        <div className="view-toggle">
          <span className="label" style={{ marginRight: 6 }}>
            Palette
          </span>
          <button
            className={palette === "congestion" ? "active" : ""}
            onClick={() => onPalette("congestion")}
          >
            Congestion
          </button>
          <button
            className={palette === "lmp" ? "active" : ""}
            onClick={() => onPalette("lmp")}
          >
            LMP
          </button>
          <button
            className={palette === "off" ? "active" : ""}
            onClick={() => onPalette("off")}
          >
            Off
          </button>
        </div>

        {onToggleConstraints && (
          <div className="view-toggle">
            <span className="label" style={{ marginRight: 6 }}>
              Overlay
            </span>
            <button
              className={showConstraints ? "active" : ""}
              onClick={() => onToggleConstraints(!showConstraints)}
            >
              Constraints
            </button>
          </div>
        )}
      </div>

      <div className="header__status">
        <div className={`status-dot status-dot--${connectionState}`} />
        <span className="label" style={{ color: "var(--text-secondary)" }}>
          {connectionState === "loading"
            ? "connecting…"
            : connectionState === "error"
            ? "api error"
            : lastUpdated
            ? `updated ${lastUpdated.toLocaleTimeString()}`
            : "live"}
        </span>
      </div>

      <style>{`
        .header {
          height: var(--header-h);
          background: var(--bg-panel);
          border-bottom: 1px solid var(--border);
          display: flex;
          align-items: center;
          padding: 0 16px;
          gap: 20px;
          flex-shrink: 0;
        }
        .header__brand {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .header__logo { font-size: 16px; }
        .header__title {
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 700;
          font-size: 16px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--accent);
        }
        .header__sub { color: var(--text-muted); margin-left: 4px; }
        .header__controls { margin-left: auto; }
        .view-toggle { display: flex; align-items: center; gap: 4px; }
        .header__status {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .status-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .status-dot--ok { background: var(--ok); }
        .status-dot--error { background: var(--danger); }
        .status-dot--loading {
          background: var(--warn);
          animation: pulse 1s ease-in-out infinite;
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </header>
  );
}
