import type { ScoreboardWeekly } from "../../api/types";
import { METRICS, type MetricKey } from "./scoreboardControlsState";
import { SERIES } from "./seriesMeta";

const SPLIT_LABELS: Record<string, string> = {
  all: "All record",
  pre_rtc_b: "Pre-RTC+B",
  post_rtc_b: "Post-RTC+B",
};

// Pooled pre/post-RTC+B split table.
export function SplitTable({
  weekly,
  metric,
}: {
  weekly: ScoreboardWeekly;
  metric: MetricKey;
}) {
  const meta = METRICS[metric];
  const val = (label: string, source: string): number | null => {
    const sp = weekly.splits
      .find((s) => s.label === label)
      ?.sources.find((x) => x.series_id === source);
    const v = sp ? (sp[metric] as number | null) : null;
    return v == null ? null : v;
  };
  return (
    <div className="sb-splits">
      <div className="sb-split-grid">
        <span className="sb-h" />
        {SERIES.map((s) => (
          <span key={s.seriesId} className="sb-h" style={{ color: s.color }}>
            {weekly.sources.find((source) => source.series_id === s.seriesId)?.label ?? s.seriesId}
          </span>
        ))}

        {weekly.splits.map((sp) => {
          const m = val(sp.label, "model");
          const p = val(sp.label, "persistence");
          const modelLeads =
            m != null && p != null && m !== p && (meta.higher ? m > p : m < p);
          const persistLeads = m != null && p != null && m !== p && !modelLeads;
          return (
            <div
              key={sp.label}
              className="sb-split-row"
              style={{ display: "contents" }}
            >
              <span className="sb-cat label">
                {SPLIT_LABELS[sp.label] ?? sp.label} · {sp.n_weeks}w
                {sp.n_days > 0 ? ` + ${sp.n_days}d` : ""}
              </span>
              <span className="sb-v" data-lead={modelLeads}>
                {m == null ? "—" : meta.fmt(m)}
              </span>
              <span className="sb-v" data-lead={persistLeads}>
                {p == null ? "—" : meta.fmt(p)}
              </span>
              <span className="sb-v">
                {(() => {
                  const v = val(sp.label, "climatology");
                  return v == null ? "—" : meta.fmt(v);
                })()}
              </span>
              <span className="sb-v sb-v--ceiling">
                {(() => {
                  const v = val(sp.label, "oracle");
                  return v == null ? "—" : meta.fmt(v);
                })()}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
