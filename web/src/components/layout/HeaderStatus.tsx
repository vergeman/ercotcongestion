// Shared theme toggle + connection-status indicator, rendered identically
// across every page's header row. Self-contained on theme (reads/writes the
// global data-theme attribute directly); connection state and the "last
// updated" timestamp are each page's own, since only Map/Matrix share a live
// session — Brief and Scoreboard track their own fetches.

import { useState } from "react";
import { currentTheme, toggleTheme, type Theme } from "../../lib/theme";
import type { ConnectionState } from "../../hooks/useExplorerSession";
import Tooltip from "../ui/Tooltip";

export default function HeaderStatus({
  connectionState,
  lastUpdated,
}: {
  connectionState: ConnectionState;
  lastUpdated: Date | null;
}) {
  // Seeded from the attribute the index.html bootstrap already resolved, so
  // the button label is correct on first paint.
  const [theme, setTheme] = useState<Theme>(() => currentTheme());

  return (
    <div className="header-status">
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
          ? `updated ${lastUpdated.toLocaleDateString()} ${lastUpdated.toLocaleTimeString()}`
          : "live"}
      </span>

      <style>{`
        .header-status {
          margin-left: auto;
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
        @media (max-width: 767px) {
          .header-status { gap: 6px; }
          .header-status > .label { display: none; }
          .theme-toggle { width: 30px; height: 30px; }
        }
      `}</style>
    </div>
  );
}
