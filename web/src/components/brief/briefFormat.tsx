// Formatting helpers and the two trailing-history glyphs shared by the Brief
// page tables and the detail panel (plan/0135). Extracted so the panel renders
// the same μ / dollar / rank text and the same 30-day whisker + bars as the row
// it opened from, without a second copy drifting out of sync. The whisker/bars
// CSS lives in BriefPage's page-level <style> (both surfaces mount under it).

export const usd = (value: number, fractionDigits = 0) =>
  `${value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })}`;

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
  if (low == null || high == null || mark == null)
    return <span className="an-table__missing">—</span>;
  const min = Math.min(low, mark, 0);
  const max = Math.max(high, mark, 0);
  const span = Math.max(max - min, 1);
  const left = `${Math.min(100, ((low - min) / span) * 100)}%`;
  const width = `${Math.max(2, ((high - low) / span) * 100)}%`;
  const boxLeft =
    q25 == null ? undefined : `${Math.min(100, ((q25 - min) / span) * 100)}%`;
  const boxWidth =
    q25 == null || q75 == null
      ? undefined
      : `${Math.max(2, ((q75 - q25) / span) * 100)}%`;
  return (
    <span
      className="an-history-whisker"
      title={`30-day settled p10 ${usd(low, 2)} · p25 ${
        q25 == null ? "—" : usd(q25, 2)
      } · median ${median == null ? "—" : usd(median, 2)} · p75 ${
        q75 == null ? "—" : usd(q75, 2)
      } · p90 ${usd(high, 2)} · today ${usd(mark, 2)}`}
    >
      <i style={{ left, width }} />
      {boxLeft && boxWidth && <em style={{ left: boxLeft, width: boxWidth }} />}
      {median != null && (
        <strong
          style={{ left: `${Math.min(100, ((median - min) / span) * 100)}%` }}
        />
      )}
      <b style={{ left: `${Math.min(100, ((mark - min) / span) * 100)}%` }} />
    </span>
  );
}

export function HistoryBars({ values }: { values: number[] }) {
  if (!values.length) return <span className="an-table__missing">—</span>;
  const max = Math.max(...values, 1);
  return (
    <span className="an-history-bars" title="Σμ on each prior settled day">
      {values.map((value, index) => (
        <i
          key={index}
          style={{ height: `${Math.max(2, (value / max) * 100)}%` }}
        />
      ))}
    </span>
  );
}
