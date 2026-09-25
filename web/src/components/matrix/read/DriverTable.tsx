import { useMemo } from "react";
import type { AnalysisContributionTerm } from "../../../api/types";
import { shiftFactorColor } from "../../../lib/colors";
import { constraintName, usd } from "../../../lib/format";
import {
  NODE_COLUMNS,
  nodeSortValue,
  termMu,
  type NodeSort,
  type NodeSortKey,
} from "./sort";

function DriverRow({ term }: { term: AnalysisContributionTerm }) {
  const side = term.shift_factor >= 0 ? "positive" : "negative";
  const mu = termMu(term);
  return (
    <tr>
      <td className="mrd-drv__key mono">
        {constraintName(term.constraint_key)}
      </td>
      <td className="mono">{term.binding_hours}h</td>
      <td className="mrd-drv__side">{side}</td>
      <td
        className="mono"
        style={{ color: shiftFactorColor(term.shift_factor) }}
      >
        {term.shift_factor.toFixed(3)}
        {term.sf_clipped && <span className="mrd-drv__clip">*</span>}
      </td>
      <td className="mono">{mu == null ? "—" : usd(mu, 2)}</td>
      <td
        className={`mono${
          term.contribution >= 0 ? " kv__value--pos" : " kv__value--neg"
        }`}
      >
        {usd(term.contribution, 2)}
      </td>
    </tr>
  );
}

// One sortable table over the node's full nonzero-SF set — it replaces the old
// drivers table plus the separate structural-exposure disclosure. Sort by $/MWh
// (default) for the drivers, by SF for structural exposure, by bind/clip to spot
// what is not structurally sound.
export function DriverTable({
  terms,
  sort,
  onToggleSort,
}: {
  terms: AnalysisContributionTerm[];
  sort: NodeSort;
  onToggleSort: (key: NodeSortKey) => void;
}) {
  const rows = useMemo(() => {
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...terms].sort(
      (a, b) => sign * (nodeSortValue(a, sort.key) - nodeSortValue(b, sort.key))
    );
  }, [terms, sort]);
  const clipped = rows.some((t) => t.sf_clipped);
  return (
    <>
      <table className="mrd-drv">
        <thead>
          <tr>
            <th>constraint</th>
            {NODE_COLUMNS.map((c) => {
              const active = sort.key === c.key;
              return (
                <th
                  key={c.key}
                  className={`mrd-drv__sort${active ? " is-active" : ""}`}
                  title={c.title}
                  tabIndex={0}
                  aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                  onClick={() => onToggleSort(c.key)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onToggleSort(c.key);
                    }
                  }}
                >
                  {c.label}
                  {active ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((term) => (
            <DriverRow key={term.constraint_key} term={term} />
          ))}
        </tbody>
      </table>
      {clipped && (
        <div className="mrd-drv__note">
          * SF pinned at the fit's ±1 clip — a bound, not a measurement
        </div>
      )}
    </>
  );
}
