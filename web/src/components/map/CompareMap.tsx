interface Props {
  // Left pane — model side, colored per the active palette.
  main: React.ReactNode;
  // Right pane — ERCOT counterpart. Content varies by palette (SP-level
  // ERCOT congestion for MC, SP-level SPP for LMP).
  right: React.ReactNode;
}

// Layout-only wrapper for the model / ERCOT panes. Camera sync between
// the two maps lives in App so it can hook `onMapReady` callbacks without
// prop-drilling refs through this component.
export default function CompareMap({ main, right }: Props) {
  return (
    <div className="compare-container">
      <div className="compare-pane compare-pane--half">{main}</div>
      <div className="compare-divider" />
      <div className="compare-pane compare-pane--half">{right}</div>
      <style>{`
        .compare-container {
          width: 100%;
          height: 100%;
          display: flex;
        }
        .compare-pane {
          position: relative;
          min-width: 0;
        }
        .compare-pane--half { flex: 0 0 50%; }
        .compare-divider {
          width: 1px;
          background: var(--border);
          flex-shrink: 0;
        }
      `}</style>
    </div>
  );
}
