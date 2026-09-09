import type { ReactNode } from "react";
import "./detail.css";

// One label→value row of a detail evidence table, shared by the Brief detail
// drawer and the Matrix read pane. `numeric` right-aligns the value; `tone`
// colors dollars by sign; a missing value renders an em dash. Each surface skins
// the row/label layout via its own `.bdp-kv` / `.mrd-kv` container.
export function Fact({
  label,
  value,
  tone,
  numeric = false,
}: {
  label: string;
  value: ReactNode;
  tone?: "pos" | "neg";
  numeric?: boolean;
}) {
  return (
    <div className="kv__row">
      <span className="kv__label">{label}</span>
      <span
        className={`kv__value${tone ? ` kv__value--${tone}` : ""}${
          numeric ? " kv__value--numeric" : ""
        }`}
      >
        {value}
      </span>
    </div>
  );
}
