import type { AnalysisContributionTerm } from "../../../api/types";

// A constraint's shadow price this hour, backed out of −SF·μ. Null when the SF
// is zero (no relationship to divide through).
export function termMu(term: AnalysisContributionTerm): number | null {
  return term.shift_factor !== 0 ? -term.contribution / term.shift_factor : null;
}

// The node table's sortable columns. Default is $/MWh (driver strength), so the
// table opens as the drivers list; sort by SF for structural exposure, and the
// `*` on a capped SF flags what the fit could not trust.
export type NodeSortKey = "sf" | "side" | "mu" | "contribution" | "binding";
export interface NodeSort {
  key: NodeSortKey;
  dir: "asc" | "desc";
}

export const NODE_COLUMNS: Array<{ key: NodeSortKey; label: string; title: string }> = [
  { key: "binding", label: "bind", title: "Hours the constraint bound on the delivery day." },
  { key: "side", label: "side", title: "Import (SF<0) or export (SF≥0)." },
  { key: "sf", label: "SF", title: "Implied shift factor; sorts by |SF|. * = pinned at the fit's clip." },
  { key: "mu", label: "μ", title: "Constraint shadow price this hour ($/MWh)." },
  { key: "contribution", label: "$/MWh", title: "This node's congestion from the constraint (−SF·μ); sorts by magnitude." },
];

// Bigger sorts first under descending. SF and $/MWh key off magnitude (the
// driver/exposure strength); side keys off the SF sign so imports and exports
// group together.
export function nodeSortValue(term: AnalysisContributionTerm, key: NodeSortKey): number {
  switch (key) {
    case "sf": return Math.abs(term.shift_factor);
    case "side": return Math.sign(term.shift_factor);
    case "mu": return termMu(term) ?? -Infinity;
    case "contribution": return Math.abs(term.contribution);
    case "binding": return term.binding_hours;
  }
}

export function nodeDefaultDir(key: NodeSortKey): "asc" | "desc" {
  return key === "side" ? "asc" : "desc";
}
