// The two trailing-history glyphs shared by the Brief tables and detail panel
// (plan/0135). Their CSS (`.an-history-whisker`, `.an-history-bars`) lives in
// features/brief/brief.css, imported by both surfaces.
import { usd } from "../../lib/format";

export function HistoryWhisker({
  low,
  q25,
  median,
  q75,
  high,
  mark,
}: {
  low: number | null;
  q25?: number | null;
  median?: number | null;
  q75?: number | null;
  high: number | null;
  mark: number | null;
}) {
  // Today's mark is the only thing that must exist to draw the whisker. The
  // p10–p90 band is optional: an element with today's value but no settled
  // 30-day history still plots its mark (relative to 0), rather than vanishing.
  if (mark == null) return <span className="an-table__missing">—</span>;
  const hasBand = low != null && high != null;
  const min = Math.min(hasBand ? low : mark, mark, 0);
  const max = Math.max(hasBand ? high : mark, mark, 0);
  const span = Math.max(max - min, 1);
  const pos = (v: number) => `${Math.min(100, ((v - min) / span) * 100)}%`;
  const boxLeft =
    !hasBand || q25 == null ? undefined : pos(q25);
  const boxWidth =
    !hasBand || q25 == null || q75 == null
      ? undefined
      : `${Math.max(2, ((q75 - q25) / span) * 100)}%`;
  return (
    <span
      className="an-history-whisker"
      title={`30-day settled p10 ${low == null ? "—" : usd(low, 2)} · p25 ${
        q25 == null ? "—" : usd(q25, 2)
      } · median ${median == null ? "—" : usd(median, 2)} · p75 ${
        q75 == null ? "—" : usd(q75, 2)
      } · p90 ${high == null ? "—" : usd(high, 2)} · today ${usd(mark, 2)}`}
    >
      {hasBand && (
        <i
          style={{
            left: pos(low),
            width: `${Math.max(2, ((high - low) / span) * 100)}%`,
          }}
        />
      )}
      {boxLeft && boxWidth && <em style={{ left: boxLeft, width: boxWidth }} />}
      {hasBand && median != null && (
        <strong style={{ left: pos(median) }} />
      )}
      <b style={{ left: pos(mark) }} />
    </span>
  );
}

// A compact diverging bar chart of the prior settled days: each bar grows up
// (positive) or down (negative) from a zero baseline, so import nodes' negative
// days render as real bars instead of collapsing to the floor. (The panel uses
// its own larger SignedBars; this is the tiny inline table form.)
export function HistoryBars({ values }: { values: number[] }) {
  if (!values.length) return <span className="an-table__missing">—</span>;
  const maxV = Math.max(...values, 0);
  const minV = Math.min(...values, 0);
  const range = maxV - minV || 1;
  const zeroPct = (maxV / range) * 100; // % from the top where 0 sits
  return (
    <span
      className="an-history-bars"
      style={{ ["--zero" as string]: `${zeroPct}%` }}
      title="Each prior settled day — up = positive, down = negative"
    >
      {values.map((value, index) => (
        <span className="an-history-bars__col" key={index}>
          <i
            style={
              value >= 0
                ? {
                    bottom: "calc(100% - var(--zero))",
                    height: `${Math.max(1, (value / range) * 100)}%`,
                  }
                : {
                    top: "var(--zero)",
                    height: `${Math.max(1, (-value / range) * 100)}%`,
                  }
            }
          />
        </span>
      ))}
    </span>
  );
}
