import { useState } from "react";
import type {
  AnalysisConstraintRow,
  MatrixDamStatus,
} from "../../api/types";
import { ConstraintReachStyles } from "../panels/ConstraintReach";
import type { MatrixEntitySelection, MatrixValTab } from "../../lib/matrix";
import {
  ConstraintRead,
  NodeRead,
  nodeDefaultDir,
  type NodeSort,
  type NodeSortKey,
} from "./read";

// The Matrix Read lens's detail (plan/0139-0003): a constraint's full SF reach
// (both dipole lobes, not a display top-k) or a node's full ranked driver
// column (not the bounded SF-grid rectangle). Reuses the genuinely
// selection-agnostic Brief pieces — the reach hook/glyphs
// (components/panels/ConstraintReach) and the footprint map — but does not
// reuse BriefDetailPanel's ConstraintEvidence/NodeEvidence: those render
// Brief's own pre-aggregated summary row (dominant driver, one μ peak) which
// this pane's data model doesn't have and deliberately goes beyond (the full
// column, every located member). History is left for 0004 — Matrix's
// full-vocabulary selections mostly fall outside Brief's own top-k, so there
// is no cheap, honest source for it yet.

interface Props {
  selection: MatrixEntitySelection;
  timestamp: Date | null;
  val: MatrixValTab;
  deliveryDate: string | null;
  damStatus: MatrixDamStatus | null;
  constraintRow: AnalysisConstraintRow | null;
  nodeMeta: {
    type: string | null;
    zone: string | null;
    lat: number | null;
    lon: number | null;
  } | null;
  onNavigateToMap: (search: string) => void;
}

export default function MatrixReadDetail({
  selection,
  timestamp,
  val,
  deliveryDate,
  damStatus,
  constraintRow,
  nodeMeta,
  onNavigateToMap,
}: Props) {
  // The node table's sort lives here, above NodeRead, so it survives switching
  // between nodes (NodeRead and its table remount, but this frame stays).
  const [nodeSort, setNodeSort] = useState<NodeSort>({
    key: "contribution",
    dir: "desc",
  });
  const toggleNodeSort = (key: NodeSortKey) =>
    setNodeSort((cur) =>
      cur.key === key
        ? { key, dir: cur.dir === "asc" ? "desc" : "asc" }
        : { key, dir: nodeDefaultDir(key) }
    );

  if (!selection) {
    return (
      <div className="mrd mrd--empty">
        Select a constraint or node from the index to see its evidence.
      </div>
    );
  }
  return (
    <div className="mrd">
      <ConstraintReachStyles />
      {selection.kind === "constraint" ? (
        <ConstraintRead
          selectionKey={selection.key}
          row={constraintRow}
          timestamp={timestamp}
          onNavigateToMap={onNavigateToMap}
        />
      ) : (
        <NodeRead
          point={selection.point}
          meta={nodeMeta}
          timestamp={timestamp}
          val={val}
          deliveryDate={deliveryDate}
          damStatus={damStatus}
          sort={nodeSort}
          onToggleSort={toggleNodeSort}
          onNavigateToMap={onNavigateToMap}
        />
      )}
      <style>{`
        /* Two columns: a scrolling evidence column on the left and the grid
           footprint pinned full-height on the right. The pane's own
           .matrix-workspace__read container owns the height; the left column
           scrolls within it while the map stays put. */
        .mrd { --mrd-fact-label: 216px; --mrd-fact-value: 130px; height: 100%; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 0; }
        .mrd--empty { color: var(--text-secondary); display: grid; place-items: center; padding: 40px 20px; text-align: center; }
        .mrd__main { min-width: 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 4px 20px 24px 2px; }
        .mrd__map { min-width: 0; border-left: 1px solid var(--border); padding-left: 18px; }
        /* Fill the column height with the footprint, overriding the Brief
           default's fixed aspect box — the map centres (xMidYMid meet) inside. */
        .mrd__map .bfm { margin: 0; height: 100%; display: flex; flex-direction: column; }
        .mrd__map .bfm__frame { flex: 1; min-height: 0; margin-top: 0; }
        .mrd__map .bfm__svg { height: 100%; }
        .mrd__head { margin-bottom: 12px; }
        .mrd__title { margin: 2px 0 0; font-family: var(--font-mono); font-size: var(--fs-xl); line-height: 1.2; overflow-wrap: anywhere; }
        .mrd__eyebrow { color: var(--text-secondary); font: 600 var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .mrd__contingency { color: var(--text-muted); font-weight: 400; }
        .mrd-section-title { display: block; margin-bottom: 8px; color: var(--text-secondary); font: 600 var(--fs-md) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .mrd-section-title em { font-style: normal; color: var(--text-muted); text-transform: none; }
        /* A compact facts table: every label and value shares the same two
           columns, while numeric values can right-align without drifting to
           the far side of the Detail pane. */
        .mrd-kv { display: grid; width: 100%; margin: 0 0 4px; }
        .mrd-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-bottom: 4px; }
        .mrd-summary__section { min-width: 0; }
        .mrd-summary .mrd-section-title { padding-bottom: 8px; border-bottom: 1px solid var(--border); }
        .mrd-summary .mrd-kv .kv__row { grid-template-columns: minmax(0, 1fr) 112px; gap: 10px; }
        @media (max-width: 760px) {
          .mrd { grid-template-columns: 1fr; height: auto; }
          .mrd__main { overflow-y: visible; padding-right: 2px; }
          .mrd__map { border-left: 0; border-top: 1px solid var(--border); padding-left: 0; padding-top: 16px; margin-top: 4px; height: 320px; }
          .mrd-summary { grid-template-columns: 1fr; gap: 18px; }
        }
        /* Matrix lays the shared kv row (components/detail/Fact) out as a
           label / numeric-value / spare grid instead of the drawer's flex row;
           the base row, value tone and numeric alignment come from the shared
           rules. */
        .mrd-kv .kv__row { display: grid; grid-template-columns: minmax(0, var(--mrd-fact-label)) var(--mrd-fact-value) minmax(0, 1fr); gap: 14px; }
        @media (max-width: 440px) { .mrd-kv .kv__row { grid-template-columns: minmax(0, 1fr) minmax(120px, 150px); } }
        .mrd-notice, .mrd-loading { margin-top: 14px; padding: 8px 10px; border: 1px solid var(--border); background: var(--accent-dim); color: var(--text-secondary); font-size: var(--fs-label); }
        .mrd-reach, .mrd-drivers { margin-top: 22px; padding-top: 22px; border-top: 1px solid var(--border); }
        .mrd-reach__dipole { width: 100%; margin: 8px 0 10px; }
        .mrd-lobes { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        .mrd-lobe h4 { margin: 0 0 6px; font-size: var(--fs-label); color: var(--text-secondary); font-weight: 600; }
        .mrd-lobe h4 em { font-style: normal; color: var(--text-muted); }
        .mrd-lobe__tail { margin-top: 4px; }
        .mrd-lobe__tail summary { color: var(--accent); cursor: pointer; font-size: var(--fs-micro); padding: 4px 2px; }
        .mrd-drv { width: 100%; border-collapse: collapse; font-size: var(--fs-label); }
        .mrd-drv th, .mrd-drv td { text-align: right; padding: 5px 8px; border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent); }
        .mrd-drv th { color: var(--text-muted); font-size: var(--fs-micro); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
        .mrd-drv th:first-child, .mrd-drv td:first-child { text-align: left; }
        .mrd-drv__key { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .mrd-drv__side { color: var(--text-muted); }
        .mrd-drv__clip { color: var(--text-muted); padding-left: 1px; }
        /* Clickable sort headers keep the header look, gaining a pointer and an
           accent when active. */
        .mrd-drv th.mrd-drv__sort { cursor: pointer; user-select: none; white-space: nowrap; }
        .mrd-drv th.mrd-drv__sort:hover { color: var(--text-secondary); }
        .mrd-drv th.mrd-drv__sort.is-active { color: var(--accent); }
        .mrd-drv__note { margin-top: 8px; color: var(--text-muted); font-size: var(--fs-micro); }
        @media (max-width: 900px) { .mrd-lobes { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
