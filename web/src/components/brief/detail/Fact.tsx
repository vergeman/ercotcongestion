import type { ReactNode } from "react";

// One label→value row of the evidence table (a dt/dd pair). `tone` colors node
// dollars by sign the way the tables do; a missing value renders an em dash.
export function Fact({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="bdp-kv__row">
      <span className="bdp-kv__label">{label}</span>
      <span
        className={
          tone === "positive"
            ? "bdp-kv__value bdp-kv__value--pos"
            : tone === "negative"
            ? "bdp-kv__value bdp-kv__value--neg"
            : "bdp-kv__value"
        }
      >
        {value}
      </span>
    </div>
  );
}
