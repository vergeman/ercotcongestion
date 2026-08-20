import { useEffect, useState } from "react";
import type { ConstraintReach } from "../../api/types";
import { fetchMapReach } from "../../api/client";
import { deliveryDateCT } from "../../lib/time";
import {
  SF_EXPORT_COLOR,
  SF_IMPORT_COLOR,
  shiftFactorColor,
} from "../../lib/colors";

// Shared constraint-structure primitives, used by BOTH the map's ranked
// Constraints sidebar (ConstraintPanel, plan/0103) and the Brief's detail panel
// (BriefDetailPanel, plan/0135). A constraint's "evidence" is the same on either
// surface — the located member nodes it drives (/map/reach) and the import↔export
// dipole those members form — so the fetch/cache, the two glyphs, and the SF
// legend live here once rather than being re-implemented per page.
//
// Colour: import/export is a structural polarity (docs/SF.md). Import (SF<0,
// receiving/expensive) is soft magenta; export (SF>0, trapped/cheap) is teal.

// A /map/reach lookup is stable for a given constraint *on a given delivery
// day* (0144 — reach is served from that day's SF artifact, not a session-wide
// rolling fit), so cache it module-side under both: re-opening the same
// constraint on the same day — a row hover in the sidebar, or re-opening the
// Brief panel — is instant and never re-hits the endpoint, while moving the
// scrubber to another day correctly refetches. Keying on the constraint alone
// would pin the first-viewed day's reach for every day after it.
//
// The key uses the CT delivery day rather than the instant so sweeping hours
// within one day is still a single fetch.
const reachCache = new Map<string, ConstraintReach | null>();

function reachKey(id: string, t?: Date): string {
  return `${t ? deliveryDateCT(t) : "latest"}|${id}`;
}

// How many driven nodes a bounded reach request asks for. Every display consumer
// (map sidebar, Brief evidence, Brief footprint) wants the same depth, and they
// share one cache — a caller passing a different `k` would store a shorter list
// under a key the others then read, so keep them on this one value.
export const REACH_K = 20;

// The reach for one constraint, from the shared cache or a single fetch. `id`
// null (nothing selected) resolves to no reach without a request. Both panels
// read through this so they share the cache and the soft-fail contract.
export function useConstraintReach(
  id: string | null,
  k = REACH_K,
  t?: Date
): { reach: ConstraintReach | null; loading: boolean } {
  const key = id ? reachKey(id, t) : null;
  const [reach, setReach] = useState<ConstraintReach | null>(
    key && reachCache.has(key) ? reachCache.get(key)! : null
  );
  const [loading, setLoading] = useState(!!key && !reachCache.has(key));

  useEffect(() => {
    if (!id || !key) {
      setReach(null);
      setLoading(false);
      return;
    }
    if (reachCache.has(key)) {
      setReach(reachCache.get(key)!);
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    fetchMapReach(id, { k, t })
      .then((r) => {
        reachCache.set(key, r);
        if (live) setReach(r);
      })
      .catch(() => {
        reachCache.set(key, null);
        if (live) setReach(null);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [id, k, key, t]);

  return { reach, loading };
}

// The constraint's complete reach (bounded only by the noise floor, no row
// limit — plan/0139-0001's `full=true` mode), separately cached from the
// bounded `useConstraintReach` above since the two payloads are not
// interchangeable (a k=20 cache hit must never satisfy a full-reach request,
// or vice versa). Used by the Matrix Read pane (0139-0003), which needs both
// dipole lobes complete, not a display top-k.
const fullReachCache = new Map<string, ConstraintReach | null>();

export function useFullConstraintReach(
  id: string | null,
  t?: Date
): { reach: ConstraintReach | null; loading: boolean } {
  const key = id ? reachKey(id, t) : null;
  const [reach, setReach] = useState<ConstraintReach | null>(
    key && fullReachCache.has(key) ? fullReachCache.get(key)! : null
  );
  const [loading, setLoading] = useState(!!key && !fullReachCache.has(key));

  useEffect(() => {
    if (!id || !key) {
      setReach(null);
      setLoading(false);
      return;
    }
    if (fullReachCache.has(key)) {
      setReach(fullReachCache.get(key)!);
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    fetchMapReach(id, { full: true, minFrac: 0, t })
      .then((r) => {
        fullReachCache.set(key, r);
        if (live) setReach(r);
      })
      .catch(() => {
        fullReachCache.set(key, null);
        if (live) setReach(null);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [id, key, t]);

  return { reach, loading };
}

// Compact magnitude for a contribution figure (a relative $·SF·h score):
// 1.2k / 3.4M so the number stays one glance wide.
export function fmtMag(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}k`;
  return v.toFixed(0);
}

// The import↔export split of a reach as (n_import, n_export) — the SF<0 vs SF>0
// located-node counts that feed the Dipole. Handy when the caller only has the
// reach payload (the Brief panel), not the ranked row's precomputed counts.
export function dipoleCounts(reach: ConstraintReach | null): {
  imp: number;
  exp: number;
} {
  let imp = 0;
  let exp = 0;
  for (const s of reach?.sps ?? []) {
    if (s.sf < 0) imp += 1;
    else exp += 1;
  }
  return { imp, exp };
}

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
  return (
    <ul className="cr-mem" role="list" onMouseLeave={() => onMemberHover?.(null)}>
      {reach.sps.map((s) => {
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
