import { SF_EXPORT_COLOR, SF_IMPORT_COLOR, congestionColor } from "../../lib/colors";
import type { MatrixValueMode } from "../../lib/matrix";

interface Props {
  mode: MatrixValueMode;
  maxAbs: number;
}

function label(value: number, mode: MatrixValueMode): string {
  return mode === "sf" ? value.toFixed(3) : `$${value.toFixed(2)}`;
}

// The Detail (Read) lens's legend. Occupies the same header slot and the same
// `.matrix-legend` footprint as MatrixLegend so toggling Detail↔SF never
// resizes the sub-header, but keys the import/export shift-factor role palette
// (magenta ↔ teal, docs/SF.md) the Read pane's reach lobes and driver column
// are coloured by — a different axis from the SF grid's blue↔red congestion
// scale, hence its own title/colours rather than reusing MatrixLegend.
export function MatrixReachLegend() {
  return (
    <div className="matrix-legend" aria-label="Shift-factor import/export legend">
      <div className="matrix-legend__title label">Grid reach</div>
      <div
        className="matrix-legend__bar"
        aria-hidden="true"
        style={{
          background: `linear-gradient(to right, ${SF_IMPORT_COLOR}, var(--bg-surface), ${SF_EXPORT_COLOR})`,
        }}
      />
      <div className="matrix-legend__ticks mono">
        <span>import</span>
        <span>0</span>
        <span>export</span>
      </div>
      <div className="matrix-legend__signs label">
        <span>SF &lt; 0 · price ↑</span>
        <span>SF &gt; 0 · price ↓</span>
      </div>
    </div>
  );
}

export default function MatrixLegend({ mode, maxAbs }: Props) {
  const unit = mode === "sf" ? "dimensionless implied SF" : "$/MWh contribution";
  return (
    <div className="matrix-legend" aria-label={`${unit} color legend`}>
      <div className="matrix-legend__title label">Implied SF</div>
      <div
        className="matrix-legend__bar"
        aria-hidden="true"
        style={{
          background: `linear-gradient(to right, ${congestionColor(-1)}, ${congestionColor(0)}, ${congestionColor(1)})`,
        }}
      />
      <div className="matrix-legend__ticks mono">
        <span>+{label(maxAbs, mode)}</span>
        <span>0</span>
        <span>−{label(maxAbs, mode)}</span>
      </div>
      <div className="matrix-legend__signs label">
        <span>Export / positive</span>
        <span>Import / negative</span>
      </div>
    </div>
  );
}
