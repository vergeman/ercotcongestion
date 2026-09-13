import type { AnalysisNodeResponse } from "../api/types";

// Constraint-by-constraint congestion basis between two settlement points.

export interface BasisRow {
  constraint: string;
  sfA: number | null;
  sfB: number | null;
  mu: number | null;
  contrib: number;
  mutual: boolean;
}

export interface BasisResult {
  rows: BasisRow[];
  total: number;
  topShare: number;
  topConstraint: string | null;
}

export interface NodeColumn {
  sf: Map<string, number>;
  mu: Map<string, number | null>;
}

export function nodeColumn(node: AnalysisNodeResponse | null): NodeColumn {
  const sf = new Map<string, number>();
  const mu = new Map<string, number | null>();
  if (!node?.available) return { sf, mu };
  for (const term of node.terms ?? []) {
    sf.set(term.constraint_key, term.shift_factor);
    mu.set(term.constraint_key, term.shift_factor !== 0 ? -term.contribution / term.shift_factor : null);
  }
  return { sf, mu };
}

export function nodeBasis(
  colA: Map<string, number>,
  colB: Map<string, number>,
  muByConstraint: Map<string, number | null>,
): BasisResult {
  const constraints = new Set<string>([...colA.keys(), ...colB.keys()]);
  const rows: BasisRow[] = [];
  let total = 0;
  for (const constraint of constraints) {
    const hasA = colA.has(constraint);
    const hasB = colB.has(constraint);
    const sfA = hasA ? colA.get(constraint)! : null;
    const sfB = hasB ? colB.get(constraint)! : null;
    const mu = muByConstraint.get(constraint) ?? null;
    const contrib = mu == null ? 0 : -((sfA ?? 0) - (sfB ?? 0)) * mu;
    total += contrib;
    rows.push({ constraint, sfA, sfB, mu, contrib, mutual: hasA && hasB });
  }
  rows.sort((a, b) => Math.abs(b.contrib) - Math.abs(a.contrib));
  const top = rows[0];
  const topShare = top && total !== 0 ? Math.abs(top.contrib) / Math.abs(total) : 0;
  return { rows, total, topShare, topConstraint: top?.constraint ?? null };
}

export function basisFromNodes(
  a: AnalysisNodeResponse | null,
  b: AnalysisNodeResponse | null,
): BasisResult {
  const colA = nodeColumn(a);
  const colB = nodeColumn(b);
  const mu = new Map<string, number | null>(colB.mu);
  for (const [constraint, value] of colA.mu) {
    if (value != null || !mu.has(constraint)) mu.set(constraint, value);
  }
  return nodeBasis(colA.sf, colB.sf, mu);
}
