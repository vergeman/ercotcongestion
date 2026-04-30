import type { ViewMode } from '../types';

interface Props {
  viewMode: ViewMode;
}

export default function Legend({ viewMode }: Props) {
  const isFragility = viewMode === 'fragility';

  return (
    <div className="legend">
      <div className="legend__title label">
        {isFragility ? 'Fragility' : 'LMP ($/MWh)'}
      </div>
      <div className="legend__bar" />
      <div className="legend__labels">
        <span className="label">Low</span>
        <span className="label">High</span>
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
          background: ${isFragility
            ? 'linear-gradient(to right, #22c55e, #eab308, #ef4444)'
            : 'linear-gradient(to right, #3b82f6, #e2e8d0, #f97316)'};
          margin-bottom: 3px;
        }
        .legend__labels {
          display: flex;
          justify-content: space-between;
        }
      `}</style>
    </div>
  );
}
