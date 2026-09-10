import type { StandoutRow, TopConstraintRow } from "../../../api/types";
import { rankMovement, usd, zoneLabel } from "../../../lib/format";
import {
  Dipole,
  MemberList,
  SfDipoleLegend,
} from "../../panels/ConstraintReach";
import {
  dipoleCounts,
  REACH_K,
  useConstraintReach,
} from "../../panels/constraintReachData";
import { Fact } from "../../detail/Fact";
import { HistoryBlock } from "./HistoryBlock";

const STANDOUT_CONSTRAINT_KIND: Record<string, string> = {
  forecast_elevated: "Forecast runs hot vs its own 30-day history",
  chronic_under_called: "Chronically binds but the forecast is quiet",
  settled_elevated: "Settled elevated — not flagged before the day",
};

export function ConstraintEvidence({
  row,
  settled,
  standout,
  t,
}: {
  // Both constraint schemas carry every field this reads; they differ only in
  // nullability, so the union widens the numeric cells to `number | null` — which
  // the em-dash guards below already handle.
  row: StandoutRow | TopConstraintRow;
  settled: boolean;
  standout: StandoutRow | null;
  // The Brief cursor's instant — selects the delivery day the reach describes.
  t?: Date;
}) {
  // The constraint's SF reach — the located member nodes it drives and the
  // import↔export dipole they form — is the same evidence the map's Constraints
  // sidebar shows; both read it through the shared reach hook/cache.
  const { reach, loading } = useConstraintReach(row.constraint_key, REACH_K, t);
  const { imp, exp } = dipoleCounts(reach);
  return (
    <>
      <div className="bdp-kv">
        <Fact label="Zone" value={zoneLabel(row.zone)} />
        <Fact label="kV" value={row.kv_max == null ? "—" : Math.round(row.kv_max)} />
        <Fact
          label="Forecast rank"
          value={row.forecast_rank ?? "—"}
        />
        <Fact
          label="Forecast μ peak"
          value={row.forecast_peak == null ? "—" : usd(row.forecast_peak, 2)}
        />
        <Fact
          label="Forecast Σμ $/MW"
          value={row.forecast_total == null ? "—" : usd(row.forecast_total, 2)}
        />
        <Fact label="Forecast hrs bind" value={row.forecast_hours ?? "—"} />
        {settled && (
          <>
            <Fact
              label="DAM rank"
              value={rankMovement(row.forecast_rank, row.settled_rank ?? null)}
            />
            <Fact
              label="DAM μ peak"
              value={row.settled_peak == null ? "—" : usd(row.settled_peak, 2)}
            />
            <Fact
              label="DAM Σμ $/MW"
              value={
                row.settled_total == null ? "—" : usd(row.settled_total, 2)
              }
            />
            <Fact label="DAM hrs bind" value={row.settled_hours ?? "—"} />
          </>
        )}
      </div>
      {standout && (
        <div className="bdp-why">
          <span className="bdp-section-title">Why it stood out</span>
          <p>{STANDOUT_CONSTRAINT_KIND[standout.kind] ?? standout.kind}</p>
          <div className="bdp-kv">
            <Fact
              label="Σμ, today"
              value={usd(standout.forecast_total, 2)}
            />
            <Fact
              label="Σμ, 30-day median"
              value={usd(standout.forecast_history_median, 2)}
            />
            <Fact
              label="History days"
              value={standout.forecast_history_days}
            />
            {standout.chronic_bound_days != null && (
              <Fact
                label="Days bound / 30"
                value={standout.chronic_bound_days}
              />
            )}
          </div>
        </div>
      )}
      <HistoryBlock
        low={row.settled_history_p10 ?? null}
        q25={row.settled_history_p25 ?? null}
        median={row.settled_history_p50 ?? null}
        q75={row.settled_history_p75 ?? null}
        high={row.settled_history_p90 ?? null}
        mark={settled ? row.settled_total ?? null : row.forecast_total ?? null}
        values={row.settled_history ?? []}
        unit="Σμ"
      />
      <div className="bdp-reach">
        <span className="bdp-section-title">
          Grid reach · import ↔ export{" "}
          {reach && !loading && <em>{reach.sps.length} located</em>}
        </span>
        <div className="bdp-reach__dipole">
          <Dipole imp={imp} exp={exp} />
        </div>
        {loading ? (
          <div className="cr-mem-msg">loading members…</div>
        ) : (
          <MemberList reach={reach} />
        )}
        <SfDipoleLegend />
      </div>
    </>
  );
}
