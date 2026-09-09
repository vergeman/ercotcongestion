import type { BriefContext } from "../../api/types";
import { percent, usd } from "../../lib/format";
import { LoadingState } from "./BriefPrimitives";

export default function ContextPanel({
  data,
  loading,
}: {
  data: BriefContext | null;
  loading: boolean;
}) {
  const voltage = data?.voltage_classes ?? [];
  const chronic = data?.chronic_elements ?? [];
  return (
    <section className="an-context" aria-labelledby="context-title">
      <div className="an-section-heading">
        <h2 id="context-title">Context</h2>
        <p>Structural context for this delivery day.</p>
      </div>
      {loading && <LoadingState>Loading grid context…</LoadingState>}
      {!loading && !data?.available && (
        <p className="an-panel-state">
          Context is unavailable for this delivery day.
        </p>
      )}
      {!loading && data?.available && (
        <>
          <div className="an-context__table">
            <h3>
              Congestion by voltage class{" "}
              <span>
                daily {data.basis === "settled" ? "DAM μ" : "forecast μ"}
              </span>
            </h3>
            {!voltage.length ? (
              <p className="an-panel-state">
                No congestion was available to classify.
              </p>
            ) : (
              <div className="an-table-wrap">
                <table className="an-table an-table--context">
                  <thead>
                    <tr>
                      <th>Class</th>
                      <th># constraints</th>
                      <th>Binding hours</th>
                      <th>
                        Avg <span className="an-table__mu">μ</span>
                      </th>
                      <th>
                        Share of Σ<span className="an-table__mu">μ</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {voltage.map((row) => (
                      <tr key={row.voltage_class}>
                        <td>{row.voltage_class}</td>
                        <td>{row.constraint_keys.toLocaleString()}</td>
                        <td>{row.binding_hours.toLocaleString()}</td>
                        <td>{usd(row.average_mu, 2)}</td>
                        <td>
                          <span className="an-context__share">
                            <i
                              style={{
                                width: `${Math.max(2, row.share_of_mu * 100)}%`,
                              }}
                            />
                            {percent(row.share_of_mu)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <div className="an-context__table">
            <h3>
              Chronic elements{" "}
              <span>bound on at least 24 of the prior 30 days</span>
            </h3>
            {!chronic.length ? (
              <p className="an-panel-state">
                No chronic elements were found in the trailing window.
              </p>
            ) : (
              <div className="an-table-wrap">
                <table className="an-table an-table--context an-table--chronic">
                  <thead>
                    <tr>
                      <th>Constraint</th>
                      <th>Contingency</th>
                      <th>Days bound</th>
                      <th>
                        Median Σ<span className="an-table__mu">μ</span>, binding
                        days
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {chronic.map((row) => (
                      <tr key={`${row.element}|${row.contingency}`}>
                        <td>{row.element}</td>
                        <td>{row.contingency || "—"}</td>
                        <td>
                          {row.days_bound} / {row.window_days}
                        </td>
                        <td>{usd(row.usual_total, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

