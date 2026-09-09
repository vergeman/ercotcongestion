import type { TopNodes } from "../../api/types";
import type { BriefSelection } from "../../lib/briefSelection";
import {
  constraintName,
  percent,
  rankMovement,
  usd,
  zoneLabel,
} from "../../lib/format";
import { HistoryBars, HistoryWhisker } from "./HistoryGlyphs";
import { LoadingState } from "./BriefPrimitives";

export default function TopNodesPanel({
  data,
  loading,
  settled,
  onSelect,
}: {
  data: TopNodes | null;
  loading: boolean;
  settled: boolean;
  onSelect: (selection: BriefSelection) => void;
}) {
  // Same served-k derivation as the constraints table.
  const forecastK = data?.k;
  return (
    <section className="an-nodes" aria-labelledby="top-nodes-title">
      <div className="an-section-heading">
        <h2 id="top-nodes-title">Top Nodal Congestion</h2>
        <p>
          {settled
            ? "Forecast and DAM congestion, attributed across each node’s complete shift-factor column."
            : "Forecast congestion, attributed across each node’s complete shift-factor column."}
        </p>
      </div>
      {loading && <LoadingState>Loading nodal congestion…</LoadingState>}
      {!loading && (!data?.available || !data.rows?.length) && (
        <p className="an-panel-state">
          No ranked nodal congestion is available for this delivery day.
        </p>
      )}
      {!loading && data?.available && !!data.rows?.length && (
        <div className="an-table-wrap">
          <table className="an-table an-table--nodes">
            <colgroup>
              <col className="an-col-rank" />
              <col className="an-col-node" />
              <col className="an-col-zone" />
              <col className="an-col-driver" />
              <col className="an-col-share" />
              <col className="an-col-share" />
              <col className="an-col-rank" />
              <col className="an-col-money" />
              {settled && (
                <>
                  <col className="an-col-rank" />
                  <col className="an-col-money" />
                  <col className="an-col-money" />
                </>
              )}
              <col className="an-col-history" />
              <col className="an-col-history" />
            </colgroup>
            <thead>
              <tr className="an-table__groups">
                <th colSpan={6} />
                <th className="an-table__forecast" colSpan={2}>
                  Forecast
                </th>
                {settled && (
                  <th className="an-table__split an-table__settled" colSpan={3}>
                    DAM settled
                  </th>
                )}
                <th colSpan={2}>30-day history</th>
              </tr>
              <tr>
                <th>#</th>
                <th>Node</th>
                <th>Zone</th>
                <th>Dominant driver</th>
                <th>Share</th>
                <th>Cov</th>
                <th>Rank</th>
                <th>Peak</th>
                {settled && (
                  <>
                    <th className="an-table__split">Rank</th>
                    <th>Peak</th>
                    <th>Δ</th>
                  </>
                )}
                <th>$/MWh p10–p90</th>
                <th>$/MWh each day</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, index) => (
                <tr key={row.settlement_point}>
                  <td className="an-table__rank">
                    {settled ? index + 1 : row.forecast_rank ?? "—"}
                  </td>
                  <td>
                    {settled &&
                      forecastK != null &&
                      (row.forecast_rank == null ||
                        row.forecast_rank > forecastK) && (
                        <span className="an-standouts__asterisk">*</span>
                      )}
                    <button
                      type="button"
                      className="an-row-link"
                      onClick={() => onSelect({ kind: "node", row })}
                    >
                      {row.settlement_point}
                      {row.essp_member_count > 1 && (
                        <sup>≈{row.essp_member_count}</sup>
                      )}
                    </button>
                  </td>
                  <td>{zoneLabel(row.zone)}</td>
                  <td
                    className="an-table__driver"
                    title={row.dominant_driver ?? undefined}
                  >
                    {constraintName(row.dominant_driver)}
                  </td>
                  <td>{percent(row.driver_share)}</td>
                  <td>{percent(row.coverage)}</td>
                  <td>{row.forecast_rank ?? "—"}</td>
                  <td
                    className={
                      row.forecast_total >= 0
                        ? "an-table__positive"
                        : "an-table__negative"
                    }
                  >
                    {usd(row.forecast_total, 2)}
                  </td>
                  {settled && (
                    <>
                      <td className="an-table__split">
                        {rankMovement(row.forecast_rank, row.settled_rank)}
                      </td>
                      <td
                        className={
                          row.settled_total == null
                            ? ""
                            : row.settled_total >= 0
                            ? "an-table__positive"
                            : "an-table__negative"
                        }
                      >
                        {row.settled_total == null
                          ? "—"
                          : usd(row.settled_total, 2)}
                      </td>
                      <td
                        className={
                          row.delta == null
                            ? ""
                            : row.delta >= 0
                            ? "an-table__positive"
                            : "an-table__negative"
                        }
                      >
                        {row.delta == null ? "—" : usd(row.delta, 2)}
                      </td>
                    </>
                  )}
                  <td>
                    <HistoryWhisker
                      low={row.settled_history_p10}
                      q25={row.settled_history_p25}
                      median={row.settled_history_p50}
                      q75={row.settled_history_p75}
                      high={row.settled_history_p90}
                      mark={settled ? row.settled_total : row.forecast_total}
                    />
                  </td>
                  <td>
                    <HistoryBars values={row.settled_history} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

