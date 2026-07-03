export interface BusState {
  bus_id: string;
  modeled_congestion: number | null;
  binding_proximity: number | null;
  lmp: number | null;
  basis: number | null;
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

export type ViewMode =
  | "modeled_congestion"
  | "lmp"
  | "congestion_vs_basis"
  | "binding_proximity";

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
  rank_spearman: number | null;
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

export interface ScorecardResponse {
  run_id: string;
  params: ScorecardParams;
  headline: ScorecardHeadline;
  zones: ScorecardZone[];
  series: ScorecardSeries;
  warnings: string[];
}

export interface BusFeatureProperties {
  bus_id: string;
  weather_zone: string;
  load_zone: string;
  voltage: number;
  capacity_mw: number;
  cluster_id?: number | null;
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
