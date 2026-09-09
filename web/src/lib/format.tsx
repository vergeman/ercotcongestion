/* eslint-disable react-refresh/only-export-components -- shared format lib, not a fast-refresh boundary */
// The app's shared formatting helpers plus the two trailing-history glyphs used
// by the Brief tables and detail panel (plan/0135). One copy so every surface
// renders the same dollar / rank text and the same 30-day whisker + bars. The
// whisker/bars CSS lives in BriefPage's page-level <style> (both mount under it).

export const usd = (value: number, fractionDigits = 0) =>
  `${value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })}`;

// A market value with its per-MWh unit, e.g. "$3.20/MWh". Null → "—".
export const marketValue = (value: number | null | undefined): string =>
  value == null ? "—" : `${usd(value, 2)}/MWh`;

// Signed magnitude, 2 decimals, no unit — for a column whose header already
// states the unit, so it isn't repeated on every row. e.g. "+3.20" / "−1.05".
export const fmtDollars = (v: number): string =>
  `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;

// Compact contribution magnitude: 1.2k / 3.4M so the figure stays one glance wide.
export const fmtMag = (v: number): string => {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}k`;
  return v.toFixed(0);
};

// Compact currency for axis/scale labels: $1.1k when large, decimals when small,
// so a value never runs wider than its tick.
export const compactMoney = (v: number): string => {
  const a = Math.abs(v);
  const s = v < 0 ? "−" : "";
  if (a >= 1000) return `${s}$${(a / 1000).toFixed(1)}k`;
  if (a >= 100) return `${s}$${Math.round(a)}`;
  return `${s}$${a < 10 ? a.toFixed(1) : Math.round(a)}`;
};

// $1.1k when ≥ $1000, else whole dollars — the Legend's rounded scale labels.
export const formatDollar = (v: number): string => {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
};

// Exact dollars to the cent, for the Legend's alarm thresholds.
export const formatExactDollar = (v: number): string => `$${v.toFixed(2)}`;

export const percent = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value * 100)}%`;

export const constraintName = (key: string | null) => key?.split("|")[0] ?? "—";

export const zoneLabel = (zone: string | null) =>
  zone == null ? "—" : `${zone[0].toUpperCase()}${zone.slice(1)}`;

export const rankMovement = (
  forecastRank: number | null,
  settledRank: number | null
) => {
  if (settledRank == null) return "—";
  if (forecastRank == null) return `new ${settledRank}`;
  const movement = settledRank - forecastRank;
  return `${movement < 0 ? "↑" : movement > 0 ? "↓" : "="} ${settledRank}`;
};

// Grouped number, up to `decimals` places (trailing zeros dropped). Null → "—".
export const fmt = (v: number | null, decimals = 1): string =>
  v == null
    ? "—"
    : v.toLocaleString("en-US", { maximumFractionDigits: decimals });

// Grouped number, always `decimals` places. Null → "—".
export const fmtNum = (v: number | null, decimals = 1): string =>
  v == null
    ? "—"
    : v.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });

// Shift factor: unitless and often small, so 3 places keeps 0.03 legible.
// Signed, e.g. "+0.031" / "−0.004". Null → "—".
export const fmtSf = (v: number | null): string =>
  v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(3)}`;

// Signed congestion with unit, e.g. "+$3.20/MWh" / "−$1.05/MWh". Null → null,
// so the caller can drop the row rather than render a dash.
export const fmtCong = (v: number | null | undefined): string | null =>
  v == null ? null : `${v >= 0 ? "+" : "−"}$${fmt(Math.abs(v), 2)}/MWh`;

// A score to 2 places (hit-rates and correlations all sit near [0,1]). Null → "—".
export const fmtScore = (v: number | null | undefined): string =>
  v == null ? "—" : v.toFixed(2);

// A "× persistence" multiple to 2 places, e.g. "1.42×". Null → "—".
export const multiple = (v: number | null | undefined): string =>
  v == null ? "—" : `${v.toFixed(2)}×`;

// Pull a finite number out of a loosely-typed slot; anything else → null.
export const numeric = (
  slot: Record<string, unknown> | undefined,
  key: string
): number | null => {
  const value = slot?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

// Megawatts rendered as gigawatts to 1 place, e.g. "12.3 GW".
export const gw = (value: number): string =>
  `${(value / 1000).toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} GW`;

// Whether the model matched or beat its comparator (both must be present).
export const beats = (
  model: number | null | undefined,
  comparator: number | null | undefined
): boolean => model != null && comparator != null && model >= comparator;

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
