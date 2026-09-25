import type { CSSProperties } from "react";

// A diverging bar chart for the trailing daily series: each bar grows up
// positive or down for negative from a zero baseline, so negative days render
// as real bars instead of collapsing to the
// floor. Today's value is appended as a highlighted final bar; the y-axis shows
// the true min/max and marks zero when the range crosses it.
export function SignedBars({
  values,
  today,
  fmt,
}: {
  values: number[];
  today: number | null;
  fmt: (n: number) => string;
}) {
  const series = [
    ...values.map((v) => ({ v, today: false })),
    ...(today != null ? [{ v: today, today: true }] : []),
  ];
  if (!series.length) return <span className="an-table__missing">—</span>;
  const nums = series.map((s) => s.v);
  const maxV = Math.max(...nums, 0);
  const minV = Math.min(...nums, 0);
  const range = maxV - minV || 1;
  const zeroPct = (maxV / range) * 100; // % from the top where 0 sits
  const crossesZero = minV < 0 && maxV > 0;
  return (
    <div className="bdp-sbars">
      <div className="bdp-sbars__axis" aria-hidden="true">
        <span className="bdp-sbars__ax bdp-sbars__ax--top">{fmt(maxV)}</span>
        {crossesZero && (
          <span
            className="bdp-sbars__ax bdp-sbars__ax--zero"
            style={{ top: `${zeroPct}%` }}
          >
            0
          </span>
        )}
        <span className="bdp-sbars__ax bdp-sbars__ax--bot">{fmt(minV)}</span>
      </div>
      <div
        className="bdp-sbars__plot"
        style={{ ["--zero" as string]: `${zeroPct}%` }}
      >
        <span className="bdp-sbars__zline" />
        {series.map((s, i) => {
          const barStyle: CSSProperties =
            s.v >= 0
              ? {
                  bottom: "calc(100% - var(--zero))",
                  height: `${Math.max(1.5, (s.v / range) * 100)}%`,
                }
              : {
                  top: "var(--zero)",
                  height: `${Math.max(1.5, (-s.v / range) * 100)}%`,
                };
          if (s.today)
            barStyle.background =
              s.v >= 0 ? "var(--danger, #d94444)" : "var(--accent)";
          return (
            <span key={i} className="bdp-sbars__col">
              <span
                className={
                  s.today ? "bdp-sbars__bar bdp-sbars__bar--today" : "bdp-sbars__bar"
                }
                style={barStyle}
              />
            </span>
          );
        })}
      </div>
    </div>
  );
}
