export interface BusState {
  bus_id: string;
  modeled_congestion: number | null;
  binding_proximity: number | null;
  lmp: number | null;
}

export interface BindingLine {
  line: string;
  shadow_price: number;
}

export interface Contingency {
  line: string;
  stress: number;
}

export interface ZoneOutage {
  thermal_mw: number;
  irr_mw: number;
}

export interface SnapshotMeta {
  interval_ts: string;
  status: string;
  objective_cost: number | null;
  total_load_mw: number | null;
  total_gen_mw: number | null;
  n_binding_lines: number | null;
  lmp_min: number | null;
  lmp_mean: number | null;
  lmp_max: number | null;
  modeled_congestion_total: number | null;
  modeled_congestion_abs_total: number | null;
  modeled_congestion_top10_share: number | null;
  binding_proximity_max: number | null;
  binding_proximity_p95: number | null;
  binding_lines: BindingLine[];
  top_contingencies: Contingency[];
  dispatch_by_carrier: Record<string, number>;
  wind_factor_by_region: Record<string, number>;
  solar_factor_by_region: Record<string, number>;
  outage_posting_ts: string | null;
  outages_by_zone: Record<string, ZoneOutage> | null;
  error_message: string | null;
}

export interface StateResponse {
  interval_ts: string;
  meta: SnapshotMeta;
  buses: BusState[];
}

export interface StateRangeEntry {
  interval_ts: string;
  meta: SnapshotMeta;
  buses: BusState[];
}

export interface StateRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: StateRangeEntry[];
}

// ERCOT SP snapshot payload. `sp_id` is the ERCOT settlement point
// identifier; `congestion` is the reference-adjusted congestion value
// (SPP − system_λ) from the run's congestion matrix.
export interface ErcotSpState {
  sp_id: string;
  congestion: number | null;
}

export interface ErcotStateRangeEntry {
  interval_ts: string;
  sps: ErcotSpState[];
}

export interface ErcotStateRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: ErcotStateRangeEntry[];
}

// Raw DAM SPP per settlement point, per hour. Feeds the LMP palette's
// right pane so LMP-vs-LMP renders directly from ERCOT's published prices.
export interface ErcotSpSpp {
  sp_id: string;
  spp: number | null;
}

export interface ErcotSppRangeEntry {
  interval_ts: string;
  sps: ErcotSpSpp[];
}

export interface ErcotSppRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: ErcotSppRangeEntry[];
}

// Promoted implied-binding-proximity panel per settlement point, per hour.
// Wire shape renames `settlement_point` → `sp_id` at the boundary so it
// matches the other ERCOT-side range types the client already consumes.
export interface ErcotSpBp {
  sp_id: string;
  bp: number | null;
}

export interface IbpErcotRangeEntry {
  interval_ts: string;
  sps: ErcotSpBp[];
}

export interface IbpErcotRangeResponse {
  start: string;
  end: string;
  count: number;
  run_id: string;
  entries: IbpErcotRangeEntry[];
}

// Every ViewMode drives a paired split view: model side on the left,
// ERCOT counterpart on the right (empty for binding proximity — ERCOT
// doesn't publish a comparable signal).
export type ViewMode = "modeled_congestion" | "lmp" | "binding_proximity";

// 0047 — zone-aggregated scorecard. Mirrors api/models.py::ScorecardResponse.

export interface ScorecardZone {
  cluster_id: number;
  n_buses: number;
  n_sps: number;
  corr: number | null;
  sign_agreement: number | null;
  model_side_std: number | null;
  ercot_side_std: number | null;
  outlier_buses: string[];
  outlier_sps: string[];
}

export interface ScorecardHeadline {
  zone_rank_spearman_per_hour: number | null;
  mean_corr: number | null;
  mean_sign_agreement: number | null;
  n_hours: number;
  n_zones: number;
}

export interface ScorecardSeries {
  hours: string[];
  cluster_ids: number[];
  model_Z: number[][]; // (n_hours, n_zones)
  ercot_Z: number[][]; // (n_hours, n_zones)
}

export interface ScorecardParams {
  ref: string;
  algo: string;
  k: number;
  deadband: number;
  min_members: number;
}

// 0079 — per-SP model-vs-ERCOT correlation summary, folded into
// ScorecardResponse below. Mirrors api/models.py::MappingCorrelationSummary.
// Run-scoped, not per-cell — unlike the rest of ScorecardResponse, there
// is no zones/series breakdown, and it may be absent (null).
export interface MappingCorrelationSummary {
  run_id: string;
  model_ref: string;
  ercot_ref: string;
  var_threshold: number;
  n_sp: number;
  n_bus: number;
  n_sp_dropped: number;
  n_bus_dropped: number;
  pct_gt_0_7: number;
  pct_gt_0_5: number;
  median_corr: number;
  median_spearman: number;
  median_sign: number;
  pct_sign_gt_0_7: number;
}

export interface ScorecardResponse {
  run_id: string;
  params: ScorecardParams;
  headline: ScorecardHeadline;
  zones: ScorecardZone[];
  series: ScorecardSeries;
  warnings: string[];
  mapping_correlation: MappingCorrelationSummary | null;
}

export interface BusFeatureProperties {
  bus_id: string;
  weather_zone: string;
  load_zone: string;
  voltage: number;
  capacity_mw: number;
  cluster_id?: number | null;
}

// ERCOT settlement point features in /api/topology.settlement_points.
// `cluster_id` is derived from the CM.1 correlation mapping: the cluster of
// the model bus with the highest correlation to this SP. Null when the SP
// has no mapping row or its best-match bus is unclustered. `best_corr` is
// that Pearson correlation (0..1), useful for opacity/size cues.
export interface SPFeatureProperties {
  sp_id: string;
  sp_type: string;
  cluster_id?: number | null;
  best_corr?: number | null;
}

export interface LineFeatureProperties {
  line_id: string;
  bus0: string;
  bus1: string;
  s_nom: number;
  length: number;
}

export interface PtdfBusEntry {
  bus_id: string;
  ptdf: number; // signed; sign tells you direction of response
}

export interface PtdfResponse {
  line_id: string;
  buses: PtdfBusEntry[];
  n_total_buses: number;
  n_returned: number;
}
