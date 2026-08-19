import type { AnalysisNodeResponse } from "../api/types";

// 0139/0006 — node-vs-node congestion basis in the SF lens.
//
// Two full node columns of implied shift factors, joined on constraint, are a
// congestion basis: `LMP_A,cong − LMP_B,cong`, decomposed constraint-by-
// constraint. This is the one number implied SF is most entitled to compute,
// since CRRs hedge the congestion component only — energy and loss never enter.
//
// The reduction is a straight port of the prototype `nodeBasis()`
// (docs/matrix_index_prototype.html): the union of constraints located on
// either node (a one-sided constraint still creates basis), the app's
// `congestion adder = −SF·μ` convention (see docs/SF.md and lib/matrix.ts's
// matrixContribution), and a |contrib| sort. No new SF↔contribution math.
//
//   contribᶜ = −(SF[c,A] − SF[c,B]) · μᶜ     signed $/MWh added to (cong_A − cong_B)
//   basis    = Σ contribᶜ                     = LMP_A,cong − LMP_B,cong

export interface BasisRow {
  constraint: string;
  // `null` where the node has no located SF for this constraint (one-sided).
  sfA: number | null;
  sfB: number | null;
  // The constraint's shadow price μ (node-independent), or `null` when it could
  // not be recovered (an SF of exactly zero carries no μ).
  mu: number | null;
  // Signed $/MWh this constraint adds to (cong_A − cong_B).
  contrib: number;
  // True when both nodes locate this constraint; false for a one-sided term.
  mutual: boolean;
}

export interface BasisResult {
  // Ranked by |contrib| descending.
  rows: BasisRow[];
  // Σ contrib = the signed congestion basis (cong_A − cong_B), $/MWh.
  total: number;
  // The top row's |contrib| as a fraction (0..1) of |total|; 0 when there is
  // no basis. Powers the "N% of the basis is [top constraint]" readout.
  topShare: number;
  // The constraint key of the top row, or null when there are no shared terms.
  topConstraint: string | null;
}

// One node's implied-SF column, reduced from an /analysis/node response into
// the two maps the basis join needs: constraint → SF, and constraint → μ.
//
// μ is derived per term from the app's convention (contribution = −SF·μ ⇒
// μ = −contribution / SF). It reflects whichever basis the node was fetched at:
// `predicted` carries Forecast μ, `realized` carries ERCOT DAM μ — the SF-lens
// value sub-toggle picks the fetch, so μ here already follows the toggle.
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

// The pure reduction. `colA`/`colB` are constraint → SF maps (only located
// constraints appear); `muByConstraint` is constraint → μ (node-independent).
// Callers merge the two columns' μ before calling — both sides should agree on
// a shared constraint, so either works; `basisFromNodes` prefers A and falls
// back to B.
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
    // A missing μ contributes nothing (an SF of exactly zero carries no price),
    // but the row still shows so the user sees the located, un-priced term.
    const contrib = mu == null ? 0 : -((sfA ?? 0) - (sfB ?? 0)) * mu;
    total += contrib;
    rows.push({ constraint, sfA, sfB, mu, contrib, mutual: hasA && hasB });
  }
  rows.sort((a, b) => Math.abs(b.contrib) - Math.abs(a.contrib));
  const top = rows[0];
  const topShare = top && total !== 0 ? Math.abs(top.contrib) / Math.abs(total) : 0;
  return { rows, total, topShare, topConstraint: top?.constraint ?? null };
}

// Convenience join over two /analysis/node responses fetched at the same hour
// and basis: build each column, merge μ (prefer A, fall back to B), reduce.
export function basisFromNodes(
  a: AnalysisNodeResponse | null,
  b: AnalysisNodeResponse | null,
): BasisResult {
  const colA = nodeColumn(a);
  const colB = nodeColumn(b);
  const mu = new Map<string, number | null>(colB.mu);
  for (const [constraint, value] of colA.mu) {
    // Prefer A's μ, but fill from B when A could not recover it (SF == 0 on A).
    if (value != null || !mu.has(constraint)) mu.set(constraint, value);
  }
  return nodeBasis(colA.sf, colB.sf, mu);
}
