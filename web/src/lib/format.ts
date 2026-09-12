// The app's shared, framework-agnostic formatting helpers.

// ── Money & currency ────────────────────────────────────────────────────────

// Signed dollars with grouping, e.g. "$1,234" / "−$5". `fractionDigits` places.
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

// ── Numbers & percentages ───────────────────────────────────────────────────

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

// A fraction as a whole percent, e.g. "42%". Null → "—".
export const percent = (value: number | null | undefined) =>
  value == null ? "—" : `${Math.round(value * 100)}%`;

// Megawatts rendered as gigawatts to 1 place, e.g. "12.3 GW".
export const gw = (value: number): string =>
  `${(value / 1000).toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })} GW`;

// ── Labels & text ───────────────────────────────────────────────────────────

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

// ── Values & comparisons ────────────────────────────────────────────────────

// Pull a finite number out of a loosely-typed slot; anything else → null.
export const numeric = (
  slot: Record<string, unknown> | undefined,
  key: string
): number | null => {
  const value = slot?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

// Whether the model matched or beat its comparator (both must be present).
export const beats = (
  model: number | null | undefined,
  comparator: number | null | undefined
): boolean => model != null && comparator != null && model >= comparator;
