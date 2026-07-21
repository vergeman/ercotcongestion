import { useState } from "react";
import type { Palette, ViewMode } from "../../api/types";
import { currentTheme, toggleTheme, type Theme } from "../../lib/theme";

interface Props {
  // The two orthogonal axes: `viewMode` picks forecast-error vs dual compare;
  // `palette` picks the ERCOT quantity the dual panes color by. The palette control
  // is shown only in dual — forecast error is congestion-based regardless of palette.
  viewMode: ViewMode;
  onViewMode: (v: ViewMode) => void;
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
  viewMode,
  onViewMode,
  palette,
  onPalette,
  lastUpdated,
  connectionState,
  showConstraints,
  onToggleConstraints,
}: Props) {
  // Seeded from the attribute the index.html bootstrap already resolved, so the
  // button label is correct on first paint.
  const [theme, setTheme] = useState<Theme>(() => currentTheme());

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
            View
          </span>
          <button
            className={viewMode === "forecastError" ? "active" : ""}
            onClick={() => onViewMode("forecastError")}
          >
            Forecast Error
          </button>
          <button
            className={viewMode === "dual" ? "active" : ""}
            onClick={() => onViewMode("dual")}
          >
            Dual
          </button>
        </div>

        {/* Palette only bites in dual — forecast error is congestion-based regardless. */}
        {viewMode === "dual" && (
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
        )}

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
        <button
          className="theme-toggle"
          onClick={() => setTheme(toggleTheme())}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="4.2" />
              <path d="M12 2.6v2.8M12 18.6v2.8M2.6 12h2.8M18.6 12h2.8M5.4 5.4l2 2M16.6 16.6l2 2M18.6 5.4l-2 2M7.4 16.6l-2 2" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M20 14.2A8.2 8.2 0 1 1 9.8 4a6.6 6.6 0 0 0 10.2 10.2z" />
            </svg>
          )}
        </button>
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
        .header__logo { font-size: var(--fs-xl); }
        .header__title {
          font-family: var(--font-label);
          font-weight: 700;
          font-size: var(--fs-xl);
          letter-spacing: var(--track-title);
          text-transform: uppercase;
          color: var(--accent);
        }
        .header__sub { color: var(--text-muted); margin-left: 4px; }
        .header__controls {
          margin-left: auto;
          display: flex;
          align-items: center;
          gap: 16px;
        }
        .view-toggle { display: flex; align-items: center; gap: 4px; }
        .header__status {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .theme-toggle {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 26px;
          height: 26px;
          padding: 0;
          color: var(--text-secondary);
        }
        .theme-toggle:hover { color: var(--accent); }
        .theme-toggle svg {
          width: 15px;
          height: 15px;
          fill: none;
          stroke: currentColor;
          stroke-width: 1.7;
          stroke-linecap: round;
          stroke-linejoin: round;
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
