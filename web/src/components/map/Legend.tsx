import type { ViewMode } from "../../api/types";

interface Props {
  viewMode: ViewMode;
}

export default function Legend({ viewMode }: Props) {
  const isFragility = viewMode === "fragility";

  return (
    <div className="legend">
      <div className="legend__title label">
        {isFragility ? "Fragility" : "LMP ($/MWh)"}
      </div>
      <div className="legend__bar" />
      <div className="legend__labels">
        <span className="label mono">{isFragility ? "0" : "-$50"}</span>
        <span className="label mono">{isFragility ? "100" : "$500+"}</span>
      </div>

      <div className="legend__lines">
        <div className="legend__line-row">
          <span className="legend__swatch legend__swatch--binding" />
          <span className="label">binding</span>
        </div>
        <div className="legend__line-row">
          <span className="legend__swatch legend__swatch--contingency" />
          <span className="label">N-1 top 5</span>
        </div>
      </div>

      <style>{`
        .legend {
          position: absolute;
          bottom: 88px;
          left: 12px;
          background: rgba(15, 18, 23, 0.9);
          border: 1px solid var(--border);
          border-radius: 4px;
          padding: 8px 10px;
          width: 130px;
          backdrop-filter: blur(4px);
        }
        .legend__title {
          margin-bottom: 5px;
          color: var(--text-secondary);
        }
        .legend__bar {
          height: 8px;
          border-radius: 4px;
          background: ${
            isFragility
              ? "linear-gradient(to right, #22c55e, #eab308, #ef4444)"
              : "linear-gradient(to right, #3b82f6, #e2e8d0, #f97316)"
          };
          margin-bottom: 3px;
        }
        .legend__labels {
          display: flex;
          justify-content: space-between;
        }
        .legend__lines {
          margin-top: 8px;
          padding-top: 6px;
          border-top: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 3px;
        }
        .legend__line-row {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .legend__swatch {
          width: 18px;
          height: 2px;
          flex-shrink: 0;
        }
        .legend__swatch--binding { background: #f59e0b; }
        .legend__swatch--contingency {
          background: repeating-linear-gradient(
            to right, #ef4444 0, #ef4444 4px, transparent 4px, transparent 7px);
        }
      `}</style>
    </div>
  );
}
