import type { NodeStandoutRow, TopNodeRow } from "../../../api/types";
import { constraintName, percent, rankMovement, usd, zoneLabel } from "../../../lib/format";
import { Fact } from "../../detail/Fact";
import { HistoryBlock } from "./HistoryBlock";

const STANDOUT_NODE_KIND: Record<string, string> = {
  forecast_elevated: "Forecast runs hot vs its own 30-day history",
  forecast_depressed: "Forecast runs cold vs its own 30-day history",
  settled_elevated: "Settled elevated — not flagged before the day",
};

function dollarTone(value: number | null | undefined) {
  if (value == null) return undefined;
  return value >= 0 ? "pos" : ("neg" as const);
}

export function NodeEvidence({
  ranked,
  standout,
  settled,
}: {
  ranked: TopNodeRow | null;
  standout: NodeStandoutRow | null;
  settled: boolean;
}) {
  // Both node schemas share these fields; prefer whichever the selection carried.
  const zone = ranked?.zone ?? standout?.zone ?? null;
  const driver = ranked?.dominant_driver ?? standout?.dominant_driver ?? null;
  const driverShare = ranked?.driver_share ?? standout?.driver_share ?? null;
  const forecastRank = ranked?.forecast_rank ?? standout?.forecast_rank ?? null;
  const forecastTotal = ranked?.forecast_total ?? standout?.forecast_total ?? 0;
  const settledRank = ranked?.settled_rank ?? standout?.settled_rank ?? null;
  const settledTotal = ranked?.settled_total ?? standout?.settled_total ?? null;
  const essp = ranked?.essp_member_count ?? standout?.essp_member_count ?? null;
  const history = ranked ?? standout;
  return (
    <>
      <div className="bdp-kv">
        <Fact label="Zone" value={zoneLabel(zone)} />
        <Fact
          label="Dominant driver"
          value={
            <span title={driver ?? undefined}>
              {constraintName(driver)}
              {driverShare != null && (
                <small className="bdp-share"> {percent(driverShare)}</small>
              )}
            </span>
          }
        />
        <Fact label="Forecast rank" value={forecastRank ?? "—"} />
        <Fact
          label="Forecast 7×16 $/MWh"
          value={usd(forecastTotal, 2)}
          tone={dollarTone(forecastTotal)}
        />
        {ranked?.coverage != null && (
          <Fact label="SF coverage" value={percent(ranked.coverage)} />
        )}
        {essp != null && essp > 1 && (
          <Fact label="ESSP members" value={`≈${essp}`} />
        )}
        {settled && (
          <>
            <Fact
              label="DAM rank"
              value={rankMovement(forecastRank, settledRank)}
            />
            <Fact
              label="DAM 7×16 $/MWh"
              value={settledTotal == null ? "—" : usd(settledTotal, 2)}
              tone={dollarTone(settledTotal)}
            />
            {ranked?.delta != null && (
              <Fact
                label="Δ vs forecast"
                value={usd(ranked.delta, 2)}
                tone={dollarTone(ranked.delta)}
              />
            )}
          </>
        )}
      </div>
      {standout && (
        <div className="bdp-why">
          <span className="bdp-section-title">Why it stood out</span>
          <p>{STANDOUT_NODE_KIND[standout.kind] ?? standout.kind}</p>
          <div className="bdp-kv">
            <Fact label="Today" value={usd(standout.forecast_total, 2)} />
            <Fact
              label="30-day median"
              value={usd(standout.forecast_history_median, 2)}
            />
            <Fact label="History days" value={standout.forecast_history_days} />
          </div>
        </div>
      )}
      {history && (
        <HistoryBlock
          low={history.settled_history_p10}
          q25={history.settled_history_p25}
          median={history.settled_history_p50}
          q75={history.settled_history_p75}
          high={history.settled_history_p90}
          mark={settled ? settledTotal : forecastTotal}
          values={history.settled_history}
          unit="$/MWh"
        />
      )}
    </>
  );
}
