export interface BusState {
  bus_id: string;
  fragility: number | null;
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
  fragility_total: number | null;
  fragility_top10_share: number | null;
  binding_lines: BindingLine[];
  top_contingencies: Contingency[];
  dispatch_by_carrier: Record<string, number>;
  wind_factor_by_region: Record<string, number>;
  solar_factor_by_region: Record<string, number>;
  outage_posting_ts: string | null;
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

export type ViewMode = "fragility" | "lmp";

export interface CorrelationResult {
  n: number;
  rho: number | null;
}

export interface ScatterPoint {
  fragility: number;
  abs_basis: number;
  congested: boolean;
}

export interface ValidationResponse {
  start: string;
  end: string;
  n_snapshots: number;
  n_observations: number;
  overall: CorrelationResult;
  congested: CorrelationResult;
  quiet: CorrelationResult;
  congested_threshold_n_binding: number;
  scatter: ScatterPoint[];
  by_zone: Record<string, CorrelationResult>;
  warnings: string[];
}

export interface BusFeatureProperties {
  bus_id: string;
  weather_zone: string;
  load_zone: string;
  voltage: number;
  capacity_mw: number;
}

export interface LineFeatureProperties {
  line_id: string;
  bus0: string;
  bus1: string;
  s_nom: number;
  length: number;
}
