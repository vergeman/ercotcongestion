import { useMemo } from "react";
import type { ScoreboardDaily, DailyPoint } from "../../api/types";
import { fmtDay } from "./format";

// "How did the latest served forecast do." The server selects the newest final
// grade and its comparator rows.

// The graded currencies foregrounded for the latest final day. All
const LIVE_METRICS: { name: keyof DailyPoint; label: string }[] = [
  { name: "rank_spearman", label: "Rank ρ" },
  { name: "sign_agree", label: "Sign Agreement" },
  { name: "topdecile_hit", label: "Top-Decile Hit" },
];

export function LiveGradePanel({ daily }: { daily: ScoreboardDaily }) {
  const selected = daily.selected_delivery_date ?? daily.points[0]?.delivery_date;
  const bySource = useMemo(() => {
    const m = new Map<string, DailyPoint>();
    for (const p of daily.points) {
      if (p.delivery_date === selected) m.set(p.series_id, p);
    }
    return m;
  }, [daily, selected]);

  const model = bySource.get("model");
  const persistence = bySource.get("persistence");
  const oracle = bySource.get("oracle");
  const val = (
    row: DailyPoint | undefined,
    name: keyof DailyPoint
  ): number | null => {
    const v = row ? (row[name] as number | null) : null;
    return v == null ? null : v;
  };

  return (
    <section className="sb-live">
      <div className="sb-section-h label">Live · latest final served grade</div>
      <div className="sb-live__head">
        <span className="sb-live__ctx label">
          Final served {selected ? fmtDay(selected) : "grade"}
        </span>
        <div className="sb-live__meta">
          <span className="sb-live__ctx label">
            {model?.n_nodes != null ? `${model.n_nodes} nodes` : ""}
          </span>
        </div>
      </div>

      <div className="sb-tiles">
        {LIVE_METRICS.map((mk) => {
          const m = val(model, mk.name);
          const p = val(persistence, mk.name);
          const o = val(oracle, mk.name);
          return (
            <div key={mk.name} className="sb-tile">
              <div className="label">{mk.label}</div>
              <div className="sb-tile__model">
                {m == null ? "—" : m.toFixed(2)}
              </div>
              <div className="sb-tile__cmp">
                <span className="sb-persistence">
                  Prior-day (Persistence) {p == null ? "—" : p.toFixed(2)}
                </span>
                <span className="sb-ceiling">
                  Settled-μ Benchmark (Oracle) {o == null ? "—" : o.toFixed(2)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
