import type { Standouts } from "../../../api/types";
import type { BriefSelection } from "../../../lib/briefSelection";
import {
  constraintName,
  percent,
  rankMovement,
  usd,
  zoneLabel,
} from "../../../lib/format";
import { HistoryBars, HistoryWhisker } from "../HistoryGlyphs";
import { LoadingState } from "./LoadingState";

export default function StandoutsPanel({
  data,
  loading,
  settled,
  onSelect,
}: {
  data: Standouts | null;
  loading: boolean;
  settled: boolean;
  onSelect: (selection: BriefSelection) => void;
}) {
  const constraints = data?.rows ?? [];
  const nodes = data?.node_rows ?? [];
  return (
    <section className="an-standouts" aria-labelledby="standouts-title">
      <div className="an-section-heading">
        <h2 id="standouts-title">Standouts</h2>
        <p>
          Today’s forecast calls that depart from each element’s own trailing
          30-day forecast history.
        </p>
      </div>
      {loading && <LoadingState>Finding unusual calls…</LoadingState>}
      {!loading &&
        (!data?.available || (!constraints.length && !nodes.length)) && (
          <p className="an-panel-state">
            No calls cleared the current anomaly thresholds.
          </p>
        )}
      {!loading && data?.available && !!constraints.length && (
        <div className="an-standouts__table">
          <h3>Constraints</h3>
          <div className="an-table-wrap">
            <table className="an-table an-table--standouts">
              <colgroup>
                <col className="an-standouts__constraint" />
                <col className="an-standouts__zone" />
                <col className="an-standouts__kv" />
                <col className="an-standouts__rank" />
                <col className="an-standouts__peak" />
                <col className="an-standouts__hours" />
                <col className="an-standouts__sum" />
                {settled && (
                  <>
                    <col className="an-standouts__rank" />
                    <col className="an-standouts__peak" />
                    <col className="an-standouts__hours" />
                    <col className="an-standouts__sum" />
                  </>
                )}
                <col className="an-standouts__whisker" />
                <col className="an-standouts__bars" />
              </colgroup>
              <thead>
                <tr className="an-table__groups">
                  <th colSpan={3} />
                  <th className="an-table__forecast" colSpan={4}>
                    Forecast
                  </th>
                  {settled && (
                    <th
                      className="an-table__split an-table__settled"
                      colSpan={4}
                    >
                      DAM settled
                    </th>
                  )}
                  <th colSpan={2}>Settled vs its own 30 days</th>
                </tr>
                <tr>
                  <th>Constraint</th>
                  <th>Zone</th>
                  <th>kV</th>
                  <th>Rank</th>
                  <th>
                    <span className="an-table__mu">μ</span> peak
                  </th>
                  <th>Hrs bind</th>
                  <th>
                    Σ<span className="an-table__mu">μ</span> $/MW
                  </th>
                  {settled && (
                    <>
                      <th className="an-table__split">Rank</th>
                      <th>
                        <span className="an-table__mu">μ</span> peak
                      </th>
                      <th>Hrs bind</th>
                      <th>
                        Σ<span className="an-table__mu">μ</span> $/MW
                      </th>
                    </>
                  )}
                  <th>
                    Σ<span className="an-table__mu">μ</span> p10–p90, 30 d
                  </th>
                  <th>
                    Σ<span className="an-table__mu">μ</span> each of 30 days
                  </th>
                </tr>
              </thead>
              <tbody>
                {constraints.map((row) => (
                  <tr
                    className={
                      row.kind === "settled_elevated"
                        ? "an-standouts__added"
                        : undefined
                    }
                    key={row.constraint_key}
                  >
                    <td>
                      {row.kind === "settled_elevated" && (
                        <span className="an-standouts__asterisk">*</span>
                      )}
                      <button
                        type="button"
                        className="an-row-link"
                        onClick={() =>
                          onSelect({ kind: "standout-constraint", row })
                        }
                      >
                        {constraintName(row.constraint_key)}
                      </button>
                    </td>
                    <td>{zoneLabel(row.zone)}</td>
                    <td>{row.kv_max == null ? "—" : Math.round(row.kv_max)}</td>
                    <td>{row.forecast_rank ?? "—"}</td>
                    <td>
                      {row.forecast_peak == null
                        ? "—"
                        : usd(row.forecast_peak, 2)}
                    </td>
                    <td>{row.forecast_hours ?? "—"}</td>
                    <td>{usd(row.forecast_total, 2)}</td>
                    {settled && (
                      <>
                        <td className="an-table__split">
                          {rankMovement(row.forecast_rank, row.settled_rank)}
                        </td>
                        <td>
                          {row.settled_peak == null
                            ? "—"
                            : usd(row.settled_peak, 2)}
                        </td>
                        <td>{row.settled_hours ?? "—"}</td>
                        <td>
                          {row.settled_total == null
                            ? "—"
                            : usd(row.settled_total, 2)}
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
        </div>
      )}
      {!loading && data?.available && !!nodes.length && (
        <div className="an-standouts__table">
          <h3>Nodes</h3>
          <div className="an-table-wrap">
            <table className="an-table an-table--standouts an-table--standouts-nodes">
              <colgroup>
                <col className="an-standouts__node" />
                <col className="an-standouts__zone" />
                <col className="an-standouts__driver" />
                <col className="an-standouts__rank" />
                <col className="an-standouts__node-value" />
                {settled && (
                  <>
                    <col className="an-standouts__rank" />
                    <col className="an-standouts__node-value" />
                  </>
                )}
                <col className="an-standouts__whisker" />
                <col className="an-standouts__bars" />
              </colgroup>
              <thead>
                <tr className="an-table__groups">
                  <th colSpan={3} />
                  <th className="an-table__forecast" colSpan={2}>
                    Forecast
                  </th>
                  {settled && (
                    <th
                      className="an-table__split an-table__settled"
                      colSpan={2}
                    >
                      DAM settled
                    </th>
                  )}
                  <th colSpan={2}>Settled vs its own 30 days</th>
                </tr>
                <tr>
                  <th>Node</th>
                  <th>Zone</th>
                  <th>Dominant driver</th>
                  <th>Rank</th>
                  <th>7×16 $/MWh</th>
                  {settled && (
                    <>
                      <th className="an-table__split">Rank</th>
                      <th>7×16 $/MWh</th>
                    </>
                  )}
                  <th>$/MWh p10–p90, 30 d</th>
                  <th>$/MWh each of 30 days</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((row) => (
                  <tr
                    className={
                      row.kind === "settled_elevated"
                        ? "an-standouts__added"
                        : undefined
                    }
                    key={row.settlement_point}
                  >
                    <td>
                      {row.kind === "settled_elevated" && (
                        <span className="an-standouts__asterisk">*</span>
                      )}
                      <button
                        type="button"
                        className="an-row-link"
                        onClick={() => onSelect({ kind: "standout-node", row })}
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
                      {constraintName(row.dominant_driver)}{" "}
                      {row.driver_share != null && (
                        <small>{percent(row.driver_share)}</small>
                      )}
                    </td>
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
        </div>
      )}
    </section>
  );
}

