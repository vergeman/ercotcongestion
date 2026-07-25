import { congestionColor } from "../../lib/colors";
import type { MatrixValueMode } from "../../lib/matrix";

interface Props {
  mode: MatrixValueMode;
  maxAbs: number;
}

function label(value: number, mode: MatrixValueMode): string {
  return mode === "sf" ? value.toFixed(3) : `$${value.toFixed(2)}`;
}

export default function MatrixLegend({ mode, maxAbs }: Props) {
  const unit = mode === "sf" ? "dimensionless implied SF" : "$/MWh contribution";
  return (
    <div className="matrix-legend" aria-label={`${unit} color legend`}>
      <div className="matrix-legend__title label">{unit}</div>
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
