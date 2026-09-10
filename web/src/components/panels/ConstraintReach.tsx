import type { ConstraintReach } from "../../api/types";
import {
  SF_EXPORT_COLOR,
  SF_IMPORT_COLOR,
  shiftFactorColor,
} from "../../lib/colors";
import { REACH_ROW_CAP, useConstraintReach } from "./constraintReachData";

// Shared constraint-structure primitives, used by BOTH the map's ranked
// Constraints sidebar (ConstraintPanel, plan/0103) and the Brief's detail panel
// (BriefDetailPanel, plan/0135). A constraint's "evidence" is the same on either
// surface — the located member nodes it drives (/map/reach) and the import↔export
// dipole those members form — so the fetch/cache, the two glyphs, and the SF
// legend live here once rather than being re-implemented per page.
//
// Colour: import/export is a structural polarity (docs/SF.md). Import (SF<0,
// receiving/expensive) is soft magenta; export (SF>0, trapped/cheap) is teal.

// The import↔export dipole as a compact bicolor gauge: soft magenta (import,
// SF<0) vs teal (export, SF>0), split by located-node share, so a constraint
// shows at a glance which way it pushes congestion.
export function Dipole({ imp, exp }: { imp: number; exp: number }) {
  const tot = imp + exp || 1;
  return (
    <span className="cr-dip">
      <span
        className="cr-dip-seg"
        style={{ width: `${(imp / tot) * 100}%`, background: SF_IMPORT_COLOR }}
      />
      <span
        className="cr-dip-seg"
        style={{ width: `${(exp / tot) * 100}%`, background: SF_EXPORT_COLOR }}
      />
    </span>
  );
}

// The located member nodes of an already-fetched reach — the signed reach,
// import ends (SF<0) then export ends (SF>0), each coloured by its pole. Pure:
// the caller owns the fetch (via useConstraintReach), so this renders the same
// list on either surface.
export function MemberList({
  reach,
  onMemberHover,
}: {
  reach: ConstraintReach | null;
  onMemberHover?: (sp: string | null) => void;
}) {
  if (!reach || reach.sps.length === 0)
    return <div className="cr-mem-msg">no located members</div>;
  const extra = reach.sps.length - REACH_ROW_CAP;
  return (
    <ul className="cr-mem" role="list" onMouseLeave={() => onMemberHover?.(null)}>
      {reach.sps.slice(0, REACH_ROW_CAP).map((s) => {
        const imp = s.sf < 0;
        return (
          <li
            key={s.settlement_point}
            className="cr-mem-row"
            onMouseEnter={() => onMemberHover?.(s.settlement_point)}
          >
            <span
              className="cr-dot"
              style={{ background: shiftFactorColor(s.sf) }}
            />
            <span className="cr-mem-sp mono">{s.settlement_point}</span>
            <span
              className="cr-mem-sf mono"
              style={{ color: shiftFactorColor(s.sf) }}
            >
              {imp ? "import" : "export"} {s.sf.toFixed(3)}
            </span>
          </li>
        );
      })}
      {extra > 0 && (
        <li className="cr-mem-msg">+ {extra} more nodes</li>
      )}
    </ul>
  );
}

// The fetch-owning wrapper the sidebar uses: reads the reach for `id` and
// renders MemberList, with the loading/empty states the ranked list expects.
export function Membership({
  id,
  onMemberHover,
}: {
  id: string;
  onMemberHover?: (sp: string | null) => void;
}) {
  const { reach, loading } = useConstraintReach(id);
  if (loading) return <div className="cr-mem-msg">loading members…</div>;
  return <MemberList reach={reach} onMemberHover={onMemberHover} />;
}

// The SF-sign key (docs/SF.md), inline so it reads next to the dipole/members it
// explains. Shared so the two surfaces describe the polarity identically.
export function SfDipoleLegend() {
  return (
    <span className="cr-legend">
      <span className="cr-legend-item">
        <span className="cr-dot" style={{ background: SF_IMPORT_COLOR }} />
        SF&nbsp;&lt;&nbsp;0 · import (price ↑)
      </span>
      <span className="cr-legend-item">
        <span className="cr-dot" style={{ background: SF_EXPORT_COLOR }} />
        SF&nbsp;&gt;&nbsp;0 · export (price ↓)
      </span>
    </span>
  );
}

// The one style block for every primitive above. Each host panel renders it
// exactly once at its root (ConstraintPanel and BriefDetailPanel each mount at
// most once per route), so the glyphs carry no per-instance <style>.
export function ConstraintReachStyles() {
  return (
    <style>{`
      .cr-mem-msg { font-size: 12px; color: var(--text-muted); padding: 8px 2px; font-family: var(--font-label); letter-spacing: normal; }
      .cr-mem { list-style: none; margin: 0 0 6px; padding: 2px 0 4px 20px; }
      .cr-mem-row { display: flex; align-items: center; gap: 6px; padding: 2px 4px; border-radius: 3px; cursor: default; }
      .cr-mem-row:hover { background: color-mix(in srgb, var(--accent) 10%, transparent); }
      .cr-dot { width: 7px; height: 7px; border-radius: 2px; flex: 0 0 auto; }
      .cr-mem-sp { flex: 1; font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .cr-mem-sf { font-size: 11px; font-weight: 700; white-space: nowrap; }
      .cr-dip { display: inline-flex; height: 12px; width: 100%; border-radius: 2px; overflow: hidden; gap: 1.5px; background: var(--bg-panel); }
      .cr-dip-seg { height: 100%; }
      .cr-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; }
      .cr-legend-item { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
    `}</style>
  );
}
