import type { ComparisonMode, ViewMode } from "../../api/types";

interface Props {
  viewMode: ViewMode;
  onViewMode: (v: ViewMode) => void;
  comparisonMode: ComparisonMode;
  onComparisonMode: (m: ComparisonMode) => void;
  lastUpdated: Date | null;
  connectionState: "ok" | "error" | "loading";
}

const COMPARISON_MODES: { id: ComparisonMode; label: string }[] = [
  { id: "split", label: "Split" },
  { id: "single", label: "Single" },
  { id: "diff", label: "Diff" },
];

export default function Header({
  viewMode,
  onViewMode,
  comparisonMode,
  onComparisonMode,
  lastUpdated,
  connectionState,
}: Props) {
  return (
    <header className="header">
      <div className="header__brand">
        <span className="header__logo">⚡</span>
        <span className="header__title">ERCOT Grid Stress</span>
        <span className="header__sub label">
          DC-OPF · 2751 buses · TAMU synthetic
        </span>
      </div>

      <div className="header__controls">
        <div className="view-toggle">
          <span className="label" style={{ marginRight: 6 }}>
            Mode
          </span>
          {COMPARISON_MODES.map((m) => (
            <button
              key={m.id}
              className={comparisonMode === m.id ? "active" : ""}
              onClick={() => onComparisonMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        {comparisonMode === "single" && (
          <div className="view-toggle" style={{ marginLeft: 12 }}>
            <span className="label" style={{ marginRight: 6 }}>
              Palette
            </span>
            <button
              className={viewMode === "lmp" ? "active" : ""}
              onClick={() => onViewMode("lmp")}
            >
              LMP
            </button>
            <button
              className={viewMode === "modeled_congestion" ? "active" : ""}
              onClick={() => onViewMode("modeled_congestion")}
            >
              Modeled Congestion
            </button>
            <button
              className={viewMode === "binding_proximity" ? "active" : ""}
              onClick={() => onViewMode("binding_proximity")}
            >
              Binding Proximity
            </button>
            <button
              className={viewMode === "congestion_vs_basis" ? "active" : ""}
              onClick={() => onViewMode("congestion_vs_basis")}
            >
              Congestion vs Basis
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
