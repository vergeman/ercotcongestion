import { useState } from "react";
import type { MapView, MapDataMode } from "../../api/types";
import { currentTheme, toggleTheme, type Theme } from "../../lib/theme";
import HeaderNav from "./HeaderNav";
import Tooltip from "../ui/Tooltip";

const VIEWS: { key: MapView; label: string }[] = [
  { key: "forecast", label: "Forecast" },
  { key: "market", label: "Market" },
  { key: "compare", label: "Compare" },
  { key: "error", label: "Error" },
];

const DATA_MODES: { key: MapDataMode; label: string }[] = [
  { key: "congestion", label: "Congestion" },
  { key: "lmp", label: "Price (LMP)" },
];

interface Props {
  activeWorkspace?: "map" | "matrix";
  onNavigate?: (workspace: "map" | "matrix") => void;
  // The two orthogonal axes (0130): `view` picks the layout — Forecast | Market
  // (single maps), Compare (the prediction | ERCOT split), Error (P50 forecast −
  // realized congestion); `dataMode` picks the ERCOT quantity a single/compare
  // pane colors by. `marketAvailable` gates Market/Compare/Error — they need
  // settled data in the loaded window and grey out as one contiguous span with a
  // tooltip when it's missing. Error forces `dataMode` to congestion (both sides
  // share the market λ, so price error ≡ congestion error) — the LMP chip
  // disables with its own tooltip while Error is active.
  view: MapView;
  onView: (v: MapView) => void;
  dataMode: MapDataMode;
  onDataMode: (v: MapDataMode) => void;
  marketAvailable: boolean;
  lastUpdated: Date | null;
  connectionState: "ok" | "error" | "loading";
  mobileDrawerOpen?: boolean;
  onToggleMobileDrawer?: () => void;
}

export default function Header({
  activeWorkspace = "map",
  onNavigate,
  view,
  onView,
  dataMode,
  onDataMode,
  marketAvailable,
  lastUpdated,
  connectionState,
  mobileDrawerOpen = false,
  onToggleMobileDrawer,
}: Props) {
  // Seeded from the attribute the index.html bootstrap already resolved, so the
  // button label is correct on first paint.
  const [theme, setTheme] = useState<Theme>(() => currentTheme());

  return (
    <header className={`header header--${activeWorkspace}`}>
      <HeaderNav active={activeWorkspace} onNavigate={onNavigate} />

      {activeWorkspace === "map" && <div className="header__controls">
        <div className="view-toggle" role="group" aria-label="Map view">
          <span className="label" style={{ marginRight: 6 }}>
            View
          </span>
          {VIEWS.map(({ key, label }) => {
            const disabled = key !== "forecast" && !marketAvailable;
            return (
              <Tooltip
                key={key}
                as="button"
                type="button"
                placement="bottom"
                tip={disabled ? "Available after market posts" : undefined}
                aria-disabled={disabled || undefined}
                className={`${view === key ? "active" : ""}${
                  disabled ? " is-disabled" : ""
                }`}
                onClick={() => {
                  if (!disabled) onView(key);
                }}
              >
                {label}
              </Tooltip>
            );
          })}
        </div>

        <div className="view-toggle" role="group" aria-label="Map data">
          <span className="label" style={{ marginRight: 6 }}>
            Data
          </span>
          {DATA_MODES.map(({ key, label }) => {
            const disabled = view === "error" && key === "lmp";
            return (
              <Tooltip
                key={key}
                as="button"
                type="button"
                placement="bottom"
                tip={
                  disabled
                    ? "Error is congestion-only — both sides share the market λ, so price error ≡ congestion error"
                    : undefined
                }
                aria-disabled={disabled || undefined}
                className={`${dataMode === key ? "active" : ""}${
                  disabled ? " is-disabled" : ""
                }`}
                onClick={() => {
                  if (!disabled) onDataMode(key);
                }}
              >
                {label}
              </Tooltip>
            );
          })}
        </div>
      </div>}

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
        .view-toggle button.is-disabled {
          opacity: 0.4;
          cursor: not-allowed;
        }
        .view-toggle button.is-disabled:hover {
          background: var(--bg-surface);
          border-color: var(--border);
        }
        .header__status {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .header--matrix .header__status { margin-left: auto; }
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
