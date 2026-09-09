import type { ReactNode } from "react";

// Two evidence sections side by side: the selected hour and the daily /
// structural facts. Each side takes a set of <Fact> rows as children.
export function DetailSummary({
  hourly,
  structural,
}: {
  hourly: ReactNode;
  structural: ReactNode;
}) {
  return (
    <div className="mrd-summary">
      <section className="mrd-summary__section" aria-label="Selected hour">
        <span className="mrd-section-title">Selected hour</span>
        <div className="mrd-kv">{hourly}</div>
      </section>
      <section
        className="mrd-summary__section"
        aria-label="Daily and structural evidence"
      >
        <span className="mrd-section-title">Daily / structural</span>
        <div className="mrd-kv">{structural}</div>
      </section>
    </div>
  );
}
