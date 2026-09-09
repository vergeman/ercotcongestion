import type { ReactNode } from "react";

// One row of the compact facts table: label and value share two columns;
// numeric values right-align. `tone` colors dollars by sign.
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
    <div className="mrd-kv__row">
      <span className="mrd-kv__label">{label}</span>
      <span
        className={`mrd-kv__value${tone ? ` mrd-kv__value--${tone}` : ""}${
          numeric ? " mrd-kv__value--numeric" : ""
        }`}
      >
        {value}
      </span>
    </div>
  );
}
