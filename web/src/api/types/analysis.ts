// =============================================================================
// /analysis/node and /analysis/settlement-points — full-artifact attribution.
// These are intentionally sparse lists, not Matrix rectangles: every nonzero
// driver for a chosen node is preserved.
// =============================================================================

export type AnalysisBasis = "predicted" | "realized";

export interface AnalysisContributionTerm {
  constraint_key: string;
  contribution: number;
  shift_factor: number;
  // Delivery-day binding hours, and whether this node's SF was pinned at the
  // ridge clip (a bound, not a measurement). Let the node table sort structure.
  binding_hours: number;
  sf_clipped: boolean;
}

export interface NodeMarketState {
  forecast_congestion: number | null;
  forecast_lmp: number | null;
  realized_congestion: number | null;
  forecast_error: number | null;
  dam_lmp: number | null;
  forecast_lambda_source: "settled" | "persisted" | null;
}

export interface AnalysisNodeResponse {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  settlement_point?: string;
  run_id: string;
  delivery_date: string;
  horizon?: number;
  basis?: AnalysisBasis;
  hours?: string[];
  total?: number;
  n_terms?: number;
  coverage?: number | null;
  terms?: AnalysisContributionTerm[];
  market_state?: NodeMarketState | null;
  structural_n_terms?: number | null;
  structural_terms?: AnalysisContributionTerm[] | null;
  essp_member_count?: number | null;
}

export interface AnalysisSettlementPointsResponse {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  settlement_points?: string[];
  metadata?: AnalysisSettlementPointMetadata[];
}

export interface AnalysisSettlementPointMetadata {
  settlement_point: string;
  settlement_point_type: string | null;
  load_zone: string | null;
  lat: number | null;
  lon: number | null;
}

// /analysis/constraints — the full constraint vocabulary for one day's
// artifact, the search index behind the Matrix sidebar.
export interface AnalysisConstraintRow {
  constraint_key: string;
  name: string;
  contingency: string | null;
  ctype: string | null;
  zone: string | null;
  kv_max: number | null;
  binding_hours: number;
  daily_mu_rank: number;
  daily_mu_sum: number;
}

export interface AnalysisConstraintsResponse {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  rows?: AnalysisConstraintRow[];
  n_total?: number;
}
