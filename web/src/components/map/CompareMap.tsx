import type { ComparisonMode } from "../../api/types";

interface Props {
  mode: ComparisonMode;
  // The primary GridMap. Mounted for every mode so its camera state (and
  // any pinned selection) survives mode switches. Colored per-mode by the
  // props the caller hands to the underlying GridMap.
  main: React.ReactNode;
  // Second GridMap, mounted only in `split`. Owns the ERCOT-side render.
  right: React.ReactNode;
}

// Layout-only wrapper for the model / ERCOT panes. Camera sync between
// the two maps lives in App so it can hook `onMapReady` callbacks without
// prop-drilling refs through this component.
export default function CompareMap({ mode, main, right }: Props) {
  const isSplit = mode === "split";
  return (
    <div className="compare-container">
      <div
        className={
          "compare-pane compare-pane--main" +
          (isSplit ? " compare-pane--half" : "")
        }
      >
        {main}
      </div>
      {isSplit && (
        <>
          <div className="compare-divider" />
          <div className="compare-pane compare-pane--half">{right}</div>
        </>
      )}
      <style>{`
        .compare-container {
          width: 100%;
          height: 100%;
          display: flex;
        }
        .compare-pane {
          flex: 1;
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
