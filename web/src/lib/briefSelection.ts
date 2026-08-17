// A Brief table row is an inspection action, not a navigation link (plan/0135).
// This module is the single source for what a clicked row *is*: a discriminated
// selection over the four row schemas the Brief ranks — a Standouts constraint,
// a Standouts node, a Top-Constraints row, and a Top-Nodal-Congestion row — and
// the two things every consumer of a selection needs from it regardless of
// which table it came from: its stable geographic identity (constraint key or
// settlement point) and the Map deep link that selects it.

import type {
  NodeStandoutRow,
  StandoutRow,
  TopConstraintRow,
  TopNodeRow,
} from "../api/types";
import { buildMapLink, mapLinkTo, type MapTarget } from "./mapLinks";

// The row the detail panel opened over. `kind` discriminates the row schema (and
// so the evidence the panel renders); a standout and a ranked row of the *same*
// element still resolve to the same `MapTarget` — the geographic identity below.
export type BriefSelection =
  | { kind: "standout-constraint"; row: StandoutRow }
  | { kind: "standout-node"; row: NodeStandoutRow }
  | { kind: "constraint"; row: TopConstraintRow }
  | { kind: "node"; row: TopNodeRow };

// Whether the selection is geographically a constraint (an SF column with a
// reach) or a node (a single located point) — the axis the abstract footprint
// map and the Map deep link both key off, collapsing the four row kinds to two.
export type BriefSelectionGeo = "constraint" | "node";

export function selectionGeo(sel: BriefSelection): BriefSelectionGeo {
  return sel.kind === "standout-node" || sel.kind === "node"
    ? "node"
    : "constraint";
}

// The Map selection param this row targets. A constraint carries its
// `constraint_key`; a node its `settlement_point`.
export function selectionMapTarget(sel: BriefSelection): MapTarget {
  switch (sel.kind) {
    case "standout-constraint":
    case "constraint":
      return { kind: "constraint", value: sel.row.constraint_key };
    case "standout-node":
    case "node":
      return { kind: "sp", value: sel.row.settlement_point };
  }
}

// A stable string identity for the selected element, used to key React state and
// to tell whether two selections point at the same element across tables.
export function selectionIdentity(sel: BriefSelection): string {
  const target = selectionMapTarget(sel);
  return `${target.kind}:${target.value}`;
}

// The raw element key (constraint key or settlement point) — the panel header's
// title before any pretty-printing.
export function selectionKey(sel: BriefSelection): string {
  return selectionMapTarget(sel).value;
}

// The Map handoff link a selected row hands to the full Map — moved here from
// the Brief's per-row links (plan/0135 + 0131 task note): select the row's own
// element, land on the default Forecast × Congestion view, never carry autoPlay
// (that is the hero's action alone). Falls back to the bare selection link (no
// coordinate) if the hero's cursor has not loaded yet — still a valid, working
// link, just without the day's window.
export function briefElementMapHref(
  heroCursor: { t: string; ws: string; we: string } | null | undefined,
  sel: BriefSelection
): string {
  const target = selectionMapTarget(sel);
  if (!heroCursor) return mapLinkTo(target);
  return buildMapLink({
    t: new Date(heroCursor.t),
    ws: new Date(heroCursor.ws),
    we: new Date(heroCursor.we),
    view: "forecast",
    data: "congestion",
    target,
  });
}
