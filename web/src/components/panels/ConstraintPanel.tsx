import { useEffect, useState } from "react";
import type {
  RankedConstraints,
  ConstraintReach,
  ConstraintLobe,
} from "../../api/types";
import { fetchMapReach } from "../../api/client";

// The `Constraints` tab (plan/0103): a per-day ranked list of the constraints
// driving congestion — the list-shaped companion to the map's marker pile, which
// piles up and can't rank. Each row shows its congestion-contribution magnitude
// (a gauge), its member count, and its source↔sink dipole; hovering a row isolates
// that constraint — here (dim every other row, reveal its members) AND on the map
// overlay (via `onHover`), the same way the map itself is navigated. The server
// owns the order — this component never re-ranks.
//
// Colour: source/sink is a diverging polarity, and blue↔red is the app's reserved
// dipole pair (OverviewOverlay .ov-src/.ov-snk) — source (import, SF<0) blue, sink
// (export, SF>0) red, reused verbatim so a lobe reads the same on panel and map.

const SRC = "#3b82f6"; // source / import lobe (SF<0) — app-reserved
const SNK = "#ef4444"; // sink / export lobe (SF>0) — app-reserved

// One /map/reach lookup per constraint is stable for the session (same map run),
// so cache it module-side: hovering down the list is then instant and never spams
// the endpoint.
const reachCache = new Map<string, ConstraintReach | null>();

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

// Compact magnitude for the contribution figure (a relative $·SF·h score):
// 1.2k / 3.4M so the number stays one glance wide.
function fmtMag(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}k`;
  return v.toFixed(0);
}

// One constraint's expanded membership — the signed reach, source ends (SF<0) then
// sink ends (SF>0), each coloured by its pole. Reads the module cache first, so a
// re-hover paints instantly; only a cache miss hits /map/reach.
function Membership({
  id,
  onMemberHover,
}: {
  id: string;
  onMemberHover?: (sp: string | null) => void;
}) {
  const [reach, setReach] = useState<ConstraintReach | null>(
    reachCache.has(id) ? reachCache.get(id)! : null
  );
  const [loading, setLoading] = useState(!reachCache.has(id));
  useEffect(() => {
    if (reachCache.has(id)) {
      setReach(reachCache.get(id)!);
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    fetchMapReach(id, 20)
      .then((r) => {
        reachCache.set(id, r);
        if (live) setReach(r);
      })
      .catch(() => {
        reachCache.set(id, null);
        if (live) setReach(null);
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [id]);

  if (loading) return <div className="cp-mem-msg">loading members…</div>;
  if (!reach || reach.sps.length === 0)
    return <div className="cp-mem-msg">no located members</div>;

  return (
    <ul
      className="cp-mem"
      role="list"
      onMouseLeave={() => onMemberHover?.(null)}
    >
      {reach.sps.map((s) => {
        const src = s.sf < 0;
        return (
          <li
            key={s.settlement_point}
            className="cp-mem-row"
            onMouseEnter={() => onMemberHover?.(s.settlement_point)}
          >
            <span className="cp-dot" style={{ background: src ? SRC : SNK }} />
            <span className="cp-mem-sp mono">{s.settlement_point}</span>
            <span className="cp-mem-sf mono" style={{ color: src ? SRC : SNK }}>
              {src ? "src" : "snk"} {s.sf.toFixed(2)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// The source↔sink dipole as a compact bicolor gauge: blue (source, import) vs red
// (sink, export), split by located-node share, so the row shows at a glance which
// way the constraint pushes congestion. Peaks + counts ride the tooltip.
function Dipole({ src, snk }: { src: ConstraintLobe; snk: ConstraintLobe }) {
  const s = src.n_nodes;
  const k = snk.n_nodes;
  const tot = s + k || 1;
  const pk = (l: ConstraintLobe) =>
    l.peak_sf != null ? Math.abs(l.peak_sf).toFixed(2) : "—";
  return (
    <span
      className="cp-dip"
      title={`source (import) ${s} nodes · peak ${pk(src)}   ↔   sink (export) ${k} nodes · peak ${pk(snk)}`}
    >
      <span className="cp-dip-seg" style={{ width: `${(s / tot) * 100}%`, background: SRC }} />
      <span className="cp-dip-seg" style={{ width: `${(k / tot) * 100}%`, background: SNK }} />
    </span>
  );
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
      <div className="np-section__header cp-header">
        <span className="label">Constraints</span>
        <div className="cp-basis-toggle" role="group" aria-label="ranking basis">
          {(["predicted", "realized"] as const).map((b) => (
            <button
              key={b}
              className={basis === b ? "active" : ""}
              aria-pressed={basis === b}
              title={
                b === "predicted"
                  ? "Predicted: the model's forecast shadow price (E[μ]) projected through the SF map."
                  : "Realized: ERCOT's published DAM shadow prices for the day — the actual market outcome."
              }
              onClick={() => onBasis(b)}
            >
              {b === "predicted" ? "predicted" : "realized"}
            </button>
          ))}
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
        constraint. <span style={{ color: SRC }}>Source</span>/
        <span style={{ color: SNK }}>sink</span> = the import/export ends. Hover a
        row to isolate it on the map; click to expand its source/sink members.
      </div>

      {loading && <div className="cp-mem-msg">loading ranking…</div>}
      {!loading && !ranked && (
        <div className="cp-mem-msg">
          no ranking for this day{basis === "realized" ? " (DAM not published yet)" : ""}
        </div>
      )}
      {!loading && ranked && rows.length === 0 && (
        <div className="cp-mem-msg">no constraints carried contribution</div>
      )}

      {rows.length > 0 && (
        <div className="cp-colhead" aria-hidden="true">
          <span className="cp-ch cp-ch-r" title="Rank by contribution">#</span>
          <span className="cp-ch">Constraint</span>
          <span className="cp-ch cp-ch-r" title="Member nodes above the |SF| floor">Nodes</span>
          <span className="cp-ch cp-ch-r" title="Congestion contribution (shadow-price mass × SF reach)">Contrib</span>
          <span className="cp-ch" title="Source (import, blue) ↔ sink (export, red) split by node share">Dipole</span>
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
                <span className="cp-key mono" title={c.constraint_id}>
                  {c.constraint_id}
                </span>
                <span className="cp-n mono">{c.n_members}</span>
                <span className="cp-meter" title="congestion contribution">
                  <span className="cp-meter-fill" style={{ width: `${w}%` }} />
                  <span className="cp-meter-num mono">
                    {fmtMag(c.congestion_contribution)}
                  </span>
                </span>
                <Dipole src={c.source_lobe} snk={c.sink_lobe} />
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
        .cp-basis-toggle { display: flex; gap: 4px; }
        .cp-basis-toggle button {
          padding: 2px 8px; font-size: 10px;
          font-family: var(--font-label); letter-spacing: var(--track-label);
        }
        .cp-meta { margin-bottom: 6px; color: var(--text-muted); }
        .cp-caption {
          font-size: 10.5px; line-height: 1.5; color: var(--text-muted);
          margin-bottom: 10px;
        }
        .cp-caption b { color: var(--text-secondary); font-weight: 600; }
        .cp-mem-msg {
          font-size: 11px; color: var(--text-muted);
          padding: 8px 2px; font-family: var(--font-label);
          letter-spacing: normal;
        }
        /* One shared grid so the header labels sit exactly over the row cells. */
        .cp-colhead, .cp-head {
          display: grid;
          grid-template-columns: 1.6em minmax(0,1fr) 2.6em 4.8em 3.4em;
          align-items: center; column-gap: 8px;
        }
        .cp-colhead {
          padding: 0 2px 4px; border-bottom: 1px solid var(--border);
          font-family: var(--font-label); font-size: 9px;
          letter-spacing: var(--track-label); text-transform: uppercase; color: var(--text-muted);
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
          padding: 5px 2px; cursor: pointer; color: inherit;
        }
        .cp-head:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); }
        .cp-head:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .cp-rank { font-size: 10px; color: var(--text-muted); text-align: right; }
        .cp-key {
          font-size: 10.5px; color: var(--text-primary);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .cp-n { font-size: 10.5px; color: var(--text-secondary); text-align: right; }
        .cp-meter {
          position: relative; height: 13px; width: 100%;
          background: var(--border); border-radius: 3px; overflow: hidden;
          display: inline-flex; align-items: center; justify-content: flex-end;
        }
        .cp-meter-fill {
          position: absolute; left: 0; top: 0; bottom: 0;
          background: var(--accent); border-radius: 3px;
        }
        .cp-meter-num {
          position: relative; font-size: 9px; color: var(--text-primary);
          padding-right: 4px;
        }
        .cp-dip {
          display: inline-flex; height: 9px; width: 100%;
          border-radius: 2px; overflow: hidden; gap: 1.5px;
          background: var(--bg-panel);
        }
        .cp-dip-seg { height: 100%; }
        .cp-mem { list-style: none; margin: 0 0 6px; padding: 2px 0 4px 20px; }
        .cp-mem-row { display: flex; align-items: center; gap: 6px; padding: 2px 4px;
          border-radius: 3px; cursor: default; }
        .cp-mem-row:hover { background: color-mix(in srgb, var(--accent) 10%, transparent); }
        .cp-dot { width: 7px; height: 7px; border-radius: 2px; flex: 0 0 auto; }
        .cp-mem-sp {
          flex: 1; font-size: 10px; color: var(--text-secondary);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .cp-mem-sf { font-size: 10px; font-weight: 700; white-space: nowrap; }
      `}</style>
    </div>
  );
}
