import type { TopConstraints } from "../../api/types";
import type { BriefSelection } from "../../lib/briefSelection";
import { rankMovement, usd, zoneLabel } from "../../lib/format";
import { HistoryBars, HistoryWhisker } from "./HistoryGlyphs";
import { LoadingState } from "./BriefPrimitives";

export default function TopConstraintsPanel({
  data,
  loading,
  settled,
  onSelect,
}: {
  data: TopConstraints | null;
  loading: boolean;
  settled: boolean;
  onSelect: (selection: BriefSelection) => void;
}) {
  // Post-settlement, a row absent from the forecast top-k is marked. The
  // threshold is the k the server actually served (a required field on the
  // available response) — never a client-side constant that could desync.
  const forecastK = data?.k;
  return (
    <section className="an-constraints" aria-labelledby="top-constraints-title">
      <div className="an-section-heading">
        <h2 id="top-constraints-title">Top Constraints by Shadow Price (μ)</h2>
        <p>
          {settled
            ? "The complete forecast artifact, with same-key DAM evidence—not the legacy brief cast."
            : "The complete forecast artifact, ranked by daily forecast μ—not the legacy brief cast."}
        </p>
      </div>
      {loading && <LoadingState>Loading constraints…</LoadingState>}
      {!loading && (!data?.available || !data.rows?.length) && (
        <p className="an-panel-state">
          No ranked forecast constraints are available for this delivery day.
        </p>
      )}
      {!loading && data?.available && !!data.rows?.length && (
        <div className="an-table-wrap">
          <table className="an-table an-table--constraints">
            <colgroup>
              <col className="an-col-rank" />
              <col className="an-col-constraint" />
              <col className="an-col-zone" />
              <col className="an-col-kv" />
              <col className="an-col-rank" />
              <col className="an-col-money" />
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
                <th colSpan={4} />
                <th className="an-table__forecast" colSpan={3}>
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
                <th>Constraint</th>
                <th>Zone</th>
                <th>kV</th>
                <th>Rank</th>
                <th>
                  <span className="an-table__mu">μ</span> peak
                </th>
                <th>
                  Σ<span className="an-table__mu">μ</span> $/MW
                </th>
                {settled && (
                  <>
                    <th className="an-table__split">Rank</th>
                    <th>
                      <span className="an-table__mu">μ</span> peak
                    </th>
                    <th>
                      Σ<span className="an-table__mu">μ</span> $/MW
                    </th>
                  </>
                )}
                <th>
                  Σ<span className="an-table__mu">μ</span> p10–p90
                </th>
                <th>
                  Σ<span className="an-table__mu">μ</span> each day
                </th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, index) => (
                <tr key={row.constraint_key}>
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
                      onClick={() => onSelect({ kind: "constraint", row })}
                    >
                      {row.constraint_key}
                    </button>
                  </td>
                  <td>{zoneLabel(row.zone)}</td>
                  <td>{row.kv_max == null ? "—" : Math.round(row.kv_max)}</td>
                  <td>{row.forecast_rank ?? "—"}</td>
                  <td>{usd(row.forecast_peak, 2)}</td>
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
      )}
    </section>
  );
}

