import { useState } from "react";
import type { RankedConstraints } from "../../api/types";
import Tooltip from "../ui/Tooltip";
import {
  ConstraintReachStyles,
  Dipole,
  Membership,
  SfDipoleLegend,
  fmtMag,
} from "./ConstraintReach";

// The `Constraints` tab (plan/0103): a per-day ranked list of the constraints
// driving congestion — the list-shaped companion to the map's marker pile, which
// piles up and can't rank. Each row shows its congestion-contribution magnitude
// (a gauge), its member count, and its import↔export dipole; hovering a row isolates
// that constraint — here (dim every other row, reveal its members) AND on the map
// overlay (via `onHover`), the same way the map itself is navigated. The server
// owns the order — this component never re-ranks.
//
// The reach fetch/cache, the Dipole/Membership glyphs, and the SF legend are the
// shared constraint-structure primitives (./ConstraintReach) — the same evidence
// the Brief detail panel renders (plan/0135), so they live once, not per page.

interface Props {
  ranked: RankedConstraints | null;
  loading: boolean;
  basis: "predicted" | "realized";
  onBasis: (b: "predicted" | "realized") => void;
  // Synced hover: the constraint the MAP is isolating (drives which row lights),
  // and the callback a hovered row fires to isolate on the map. Optional so the
  // panel stands alone, but App wires both so hover is symmetric.
  highlightedId?: string | null;
  onHover?: (id: string | null) => void;
  // Row click → lock the map's focus on this constraint (isolation + the src/sink
  // reach coloring), so the user can pan/zoom into it without a mouse-out clearing
  // it. The row also expands its members in-panel.
  onSelect?: (id: string) => void;
  // A constituent SP hovered in an expanded row → ring that node on the map.
  onMemberHover?: (sp: string | null) => void;
}

export default function ConstraintPanel({
  ranked,
  loading,
  basis,
  onBasis,
  highlightedId,
  onHover,
  onSelect,
  onMemberHover,
}: Props) {
  // Hover is non-destructive: it isolates the constraint on the MAP (via onHover)
  // and lights its row, but leaves the list intact so you can scroll freely. Click
  // is the only thing that expands a row to its members. `litId` is whichever row
  // the hover points at — panel-side (hoverId) or map-side (highlightedId).
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const litId = hoverId ?? highlightedId ?? null;

  const rows = ranked?.constraints ?? [];
  // The gauge is relative to the heaviest constraint (rank 1, since the server
  // sorts descending). Guard the empty/zero case.
  const maxContrib = rows.length ? rows[0].congestion_contribution || 1 : 1;

  const setHover = (id: string | null) => {
    setHoverId(id);
    onHover?.(id);
  };

  return (
    <div className="cp">
      <ConstraintReachStyles />
      <div className="np-section__header cp-header">
        <span className="label">Constraints</span>
        <div className="cp-header-actions">
          {loading && <span className="cp-loading label">loading…</span>}
          <div className="cp-basis-toggle" role="group" aria-label="ranking basis">
          {(["predicted", "realized"] as const).map((b) => (
            <Tooltip
              key={b}
              as="button"
              placement="bottom"
              className={basis === b ? "active" : ""}
              aria-pressed={basis === b}
              tip={
                b === "predicted"
                  ? "Rank constraints by the model's forecast — what it expected to bind before the day."
                  : "Rank constraints by ERCOT's actual published results for the day — what really bound."
              }
              onClick={() => onBasis(b)}
            >
              {b === "predicted" ? "Predicted" : "Realized"}
            </Tooltip>
          ))}
          </div>
        </div>
      </div>

      {ranked && (
        <div className="cp-meta label">
          {ranked.delivery_date} · {basis} · {ranked.n_ranked} constraints ranked ·
          showing top {rows.length}
        </div>
      )}
      <div className="cp-caption">
        Ranked by <b>contribution</b> = shadow-price mass × SF reach (how much a
        constraint drives the day's congestion). The bar is its share of the top
        constraint. Hover a row to isolate it on the map; click to expand its
        member nodes.
        <SfDipoleLegend />
      </div>

      {!loading && !ranked && (
        <div className="cr-mem-msg">
          no ranking for this day{basis === "realized" ? " (DAM not published yet)" : ""}
        </div>
      )}
      {!loading && ranked && rows.length === 0 && (
        <div className="cr-mem-msg">no constraints carried contribution</div>
      )}

      {rows.length > 0 && (
        <div className="cp-colhead" aria-hidden="true">
          <Tooltip className="cp-ch cp-ch-r" tabIndex={-1} tip="Rank by contribution">#</Tooltip>
          <Tooltip className="cp-ch" tabIndex={-1} tip="ERCOT's identifier for the transmission constraint (line/element and contingency)">Constraint</Tooltip>
          <Tooltip className="cp-ch cp-ch-r" tabIndex={-1} tip="Member nodes above the |SF| floor">Nodes</Tooltip>
          <Tooltip className="cp-ch cp-ch-r" tabIndex={-1} tip="Congestion contribution (shadow-price mass × SF reach)">Contrib</Tooltip>
          <Tooltip className="cp-ch" tabIndex={-1} tip="Import (SF<0, soft magenta) ↔ export (SF>0, teal) split by node share">Dipole</Tooltip>
        </div>
      )}

      <ul className="cp-list" role="list" onMouseLeave={() => setHover(null)}>
        {rows.map((c) => {
          const lit = litId === c.constraint_id;
          const expanded = expandedId === c.constraint_id;
          const w = Math.max(2, (c.congestion_contribution / maxContrib) * 100);
          return (
            <li
              key={c.constraint_id}
              className={`cp-row${lit ? " cp-lit" : ""}${expanded ? " cp-expanded" : ""}`}
              onMouseEnter={() => setHover(c.constraint_id)}
            >
              <button
                className="cp-head"
                aria-expanded={expanded}
                onFocus={() => setHover(c.constraint_id)}
                onBlur={() => setHover(null)}
                onClick={() => {
                  setExpandedId(expanded ? null : c.constraint_id);
                  onSelect?.(c.constraint_id); // lock the map's focus on it
                }}
              >
                <span className="cp-rank mono">{c.rank}</span>
                <span className="cp-key mono">{c.constraint_id}</span>
                <span className="cp-n mono">{c.n_members}</span>
                <span className="cp-meter">
                  <span className="cp-meter-fill" style={{ width: `${w}%` }} />
                  <span className="cp-meter-num mono">
                    {fmtMag(c.congestion_contribution)}
                  </span>
                </span>
                <Dipole imp={c.n_import} exp={c.n_export} />
              </button>
              {expanded && (
                <Membership
                  id={c.constraint_id}
                  onMemberHover={onMemberHover}
                />
              )}
            </li>
          );
        })}
      </ul>

      <style>{`
        .cp-header { display: flex; justify-content: space-between; align-items: center; }
        /* Loading sits inline, left of the toggle (which stays right-anchored), so
           the ranking's arrival never drops the layout vertically. */
        .cp-header-actions { display: flex; align-items: center; gap: 8px; }
        .cp-loading { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
        .cp-basis-toggle { display: flex; gap: 4px; }
        .cp-basis-toggle button {
          padding: 2px 8px; font-size: 11px;
          font-family: var(--font-label); letter-spacing: var(--track-label);
        }
        .cp-meta { margin-bottom: 6px; color: var(--text-secondary); }
        .cp-caption {
          font-size: 11.5px; line-height: 1.5; color: var(--text-secondary);
          margin-bottom: 10px;
        }
        .cp-caption b { color: var(--text-secondary); font-weight: 600; }
        /* One shared grid so the header labels sit exactly over the row cells.
           Columns are px (not em) because the header and data rows have different
           font-sizes — em would resolve to different widths and drift apart. */
        .cp-colhead, .cp-head {
          display: grid;
          grid-template-columns: 22px minmax(0,1fr) 44px 78px 54px;
          align-items: center; column-gap: 10px;
        }
        .cp-colhead {
          padding: 0 2px 7px; border-bottom: 1px solid var(--border);
          font-family: var(--font-label); font-weight: var(--fw-label); font-size: 11px;
          letter-spacing: var(--track-label); color: var(--text-muted);
        }
        .cp-ch { text-align: left; }
        .cp-ch-r { text-align: right; }
        .cp-list { list-style: none; margin: 0; padding: 0; }
        .cp-row { border-bottom: 1px solid var(--border); }
        /* Lit = the row the hover points at (here or on the map). Non-destructive:
           just a highlight, so the rest of the list stays put and scrollable. */
        .cp-row.cp-lit { background: color-mix(in srgb, var(--accent) 13%, transparent); }
        .cp-row.cp-expanded { background: color-mix(in srgb, var(--accent) 6%, transparent); }
        .cp-head {
          width: 100%; text-align: left; background: none; border: none;
          padding: 8px 2px; cursor: pointer; color: inherit;
        }
        .cp-head:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); }
        .cp-head:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .cp-rank { font-size: 12px; color: var(--text-muted); text-align: right; }
        .cp-key {
          font-size: 12px; color: var(--text-primary);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .cp-n { font-size: 12px; color: var(--text-secondary); text-align: right; }
        .cp-meter {
          position: relative; height: 16px; width: 100%;
          background: var(--border); border-radius: 3px; overflow: hidden;
          display: inline-flex; align-items: center; justify-content: flex-end;
        }
        .cp-meter-fill {
          position: absolute; left: 0; top: 0; bottom: 0;
          background: var(--accent); border-radius: 3px;
        }
        .cp-meter-num {
          position: relative; font-size: 10px; color: var(--text-primary);
          padding-right: 4px;
        }
      `}</style>
    </div>
  );
}
