import { useState } from "react";
import type { Palette, ViewMode } from "../../api/types";
import { currentTheme, toggleTheme, type Theme } from "../../lib/theme";
import HeaderNav from "./HeaderNav";
import Tooltip from "../ui/Tooltip";

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
  mobileDrawerOpen?: boolean;
  onToggleMobileDrawer?: () => void;
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
  mobileDrawerOpen = false,
  onToggleMobileDrawer,
}: Props) {
  // Seeded from the attribute the index.html bootstrap already resolved, so the
  // button label is correct on first paint.
  const [theme, setTheme] = useState<Theme>(() => currentTheme());

  return (
    <header className="header">
      <HeaderNav active="map" />

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
        {onToggleMobileDrawer && (
          <button
            className="mobile-menu-button"
            onClick={onToggleMobileDrawer}
            aria-label={mobileDrawerOpen ? "Close map menu" : "Open map menu"}
            aria-expanded={mobileDrawerOpen}
          >
            ☰
          </button>
        )}
        <Tooltip
          as="button"
          placement="bottom"
          className="theme-toggle"
          onClick={() => setTheme(toggleTheme())}
          tip={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
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
        </Tooltip>
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
        .mobile-menu-button { display: none; }
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
        @media (max-width: 767px) {
          .header {
            height: var(--mobile-header-h);
            padding: 0 max(12px, env(safe-area-inset-right)) 0 max(12px, env(safe-area-inset-left));
            gap: 10px;
          }
          .header__controls { display: none; }
          .header__status { margin-left: auto; gap: 6px; }
          .header__status > .label { display: none; }
          .mobile-menu-button {
            display: inline-flex;
            width: 30px;
            height: 30px;
            align-items: center;
            justify-content: center;
            padding: 0;
            border: none;
            background: none;
            color: var(--text-secondary);
            font-size: 18px;
          }
          .mobile-menu-button:hover { color: var(--accent); }
          .theme-toggle { width: 30px; height: 30px; }
        }
      `}</style>
    </header>
  );
}
