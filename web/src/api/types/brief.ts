import type { SourceDescriptor } from "./common";

// Brief hero content is composed from query-layer slots, not a stored blob.
export interface HeroSegment {
  text: string;
  ref: string;
}

export interface BriefHero {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id?: string;
  delivery_date?: string;
  horizon?: number;
  segments?: { headline: HeroSegment[]; lede: HeroSegment[] };
  slots?: Record<string, Record<string, unknown>>;
  verdict?: Record<string, Record<string, unknown> | null> | null;
  cursor?: { t: string; ws: string; we: string };
  provenance?: {
    run_id: string;
    delivery_date: string;
    horizon: number;
    basis: "forecast" | "settled";
  };
}

export interface BriefHeroLatest {
  available: boolean;
  run_id: string;
  delivery_date?: string;
  horizon?: number;
}

export interface TopConstraintRow {
  constraint_key: string;
  forecast_rank: number | null;
  forecast_total: number;
  forecast_peak: number;
  forecast_hours: number;
  zone: string | null;
  kv_max: number | null;
  settled_rank: number | null;
  settled_total: number | null;
  settled_peak: number | null;
  settled_hours: number | null;
  settled_history_p10: number | null;
  settled_history_p25: number | null;
  settled_history_p50: number | null;
  settled_history_p75: number | null;
  settled_history_p90: number | null;
  settled_history: number[];
}

export interface TopConstraints {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  n_ranked?: number;
  k?: number; // served forecast top-k; rows outside it get the post-settlement asterisk.
  rows?: TopConstraintRow[];
}

export interface VoltageClassRow {
  voltage_class: string;
  constraint_keys: number;
  binding_hours: number;
  average_mu: number;
  share_of_mu: number;
}

export interface ChronicElementRow {
  element: string;
  contingency: string;
  days_bound: number;
  window_days: number;
  usual_total: number;
}

export interface BriefContext {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  basis?: "forecast" | "settled";
  voltage_classes?: VoltageClassRow[];
  chronic_elements?: ChronicElementRow[];
}

export interface StandoutRow {
  constraint_key: string;
  kind: "forecast_elevated" | "chronic_under_called" | "settled_elevated";
  forecast_total: number;
  forecast_history_median: number | null;
  forecast_history_days: number;
  chronic_bound_days: number | null;
  settled_total: number | null;
  zone: string | null;
  kv_max: number | null;
  forecast_rank: number | null;
  forecast_peak: number | null;
  forecast_hours: number | null;
  settled_rank: number | null;
  settled_peak: number | null;
  settled_hours: number | null;
  settled_history_p10: number | null;
  settled_history_p25: number | null;
  settled_history_p50: number | null;
  settled_history_p75: number | null;
  settled_history_p90: number | null;
  settled_history: number[];
}

export interface NodeStandoutRow {
  settlement_point: string;
  essp_member_count: number;
  kind: "forecast_elevated" | "forecast_depressed" | "settled_elevated";
  zone: string | null;
  forecast_total: number;
  forecast_rank: number | null;
  forecast_history_median: number | null;
  forecast_history_days: number;
  settled_total: number | null;
  settled_rank: number | null;
  dominant_driver: string | null;
  driver_share: number | null;
  settled_history_p10: number | null;
  settled_history_p25: number | null;
  settled_history_p50: number | null;
  settled_history_p75: number | null;
  settled_history_p90: number | null;
  settled_history: number[];
}

export interface Standouts {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  basis: "forecast" | "settled";
  rows?: StandoutRow[];
  node_rows?: NodeStandoutRow[];
}

export interface TopNodeRow {
  settlement_point: string;
  essp_member_count: number;
  zone: string | null;
  forecast_rank: number | null;
  forecast_total: number;
  settled_rank: number | null;
  settled_total: number | null;
  delta: number | null;
  dominant_driver: string | null;
  driver_share: number | null;
  coverage: number | null;
  settled_history_p10: number | null;
  settled_history_p25: number | null;
  settled_history_p50: number | null;
  settled_history_p75: number | null;
  settled_history_p90: number | null;
  settled_history: number[];
}

export interface TopNodes {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  n_ranked?: number;
  k?: number; // served forecast top-k; rows outside it get the post-settlement asterisk.
  grouping?: "study_delivery_day" | "exact_settled" | "study_essp_missing";
  rows?: TopNodeRow[];
}

// Independent daily verification halves. Constraint and node scores never blend.
export interface AnalysisGradeMetrics {
  detection_ap: number | null;
  magnitude_overlap: number | null;
  timing_daily_skill: number | null;
  timing_hourly_skill: number | null;
}

export interface AnalysisGradeSupport {
  daily_bound_count: number;
  hourly_bound_count: number;
  forecast_total: number;
  settled_total: number;
  daily_bound_rate: number;
  hourly_bound_rate: number;
  forecast_to_settled_ratio: number | null;
  magnitude_ceiling: number | null;
  magnitude_of_ceiling: number | null;
}

export interface AnalysisGradeHalf {
  graded: boolean;
  unavailable_reason?: string | null;
  universe_size?: number | null;
  support?: AnalysisGradeSupport | null;
  sources?: SourceDescriptor[];
  source_metrics?: AnalysisGradeSourceMetrics[];
}

export interface AnalysisGradeSourceMetrics {
  id: string;
  metrics: AnalysisGradeMetrics;
}

export interface AnalysisGrade {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  constraints?: AnalysisGradeHalf;
  nodes?: AnalysisGradeHalf;
}

export interface AnalysisGradeHistoryHalf {
  sources?: SourceDescriptor[];
  source_metrics?: AnalysisGradeSourceMetrics[];
}

export interface AnalysisGradeHistoryDay {
  delivery_date: string;
  constraints: AnalysisGradeHistoryHalf;
  nodes: AnalysisGradeHistoryHalf;
}

export interface AnalysisGradeHistory {
  available: boolean;
  unavailable_reason?: "artifact_missing";
  run_id: string;
  delivery_date: string;
  horizon?: number;
  days?: AnalysisGradeHistoryDay[];
}

// The first-paint payload carries the hero and lightweight date navigation.
export interface BriefHeroShell {
  hero: BriefHero;
  previous_delivery_date: string | null;
  next_delivery_date: string | null;
}

export interface BriefDetails {
  context: BriefContext;
  standouts?: Standouts | null;
  top_nodes: TopNodes;
  top_constraints: TopConstraints;
  grade: AnalysisGrade;
  grade_history: AnalysisGradeHistory;
}
