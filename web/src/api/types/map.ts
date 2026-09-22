import type { BootstrapSectionStatus } from "./common";

// Map colors show congestion (SPP − system λ) or LMP.
export type MapDataMode = "congestion" | "lmp";

// Market, Compare, and Error require settled data.
export type MapView = "forecast" | "market" | "compare" | "error";

// Per-SP row for the current hour, merged from the congestion and SPP caches.
// `sp_id` matches the topology feature's promoteId so the map can key
// feature-state directly off it.
export interface SpRow {
  sp_id: string;
  congestion: number | null;
  spp: number | null;
}

// ERCOT settlement point features in /topology.settlement_points.
export interface SPFeatureProperties {
  sp_id: string;
  sp_type: string;
  load_zone: string | null;
  capacity_mw: number;
}

// Forecast congestion is the modeled congestion adder for one settlement point.
export interface ForecastSpState {
  sp_id: string;
  forecast_congestion: number | null;
}

export interface ForecastRangeEntry {
  interval_ts: string;
  system_lambda: number | null;
  lambda_source: "settled" | "persisted" | null;
  congestion: Array<number | null>;
}

// Expanded at the API boundary for map consumers.
export interface ForecastStateEntry {
  interval_ts: string;
  system_lambda: number | null;
  lambda_source: "settled" | "persisted" | null;
  sps: ForecastSpState[];
}

// `horizons` maps each delivery date to its forecast horizon (1 or 2).
export interface ForecastRangeResponse {
  start: string;
  end: string;
  run_id: string;
  count: number;
  sp_ids: string[];
  entries: ForecastRangeEntry[];
  horizons: Record<string, number>;
}

// Load uses ERCOT weather zones; wind and solar use ERCOT generation regions.
// Outages are offline capacity from ERCOT NP1-346, not generation.
export interface ZoneLoad {
  zone: string;
  forecast_mw: number | null;
  actual_mw: number | null;
}

export interface RegionGen {
  region: string;
  forecast_mw: number | null;
  actual_mw: number | null;
}

export interface FuelOutage {
  fuel: string;
  forecast_mw: number | null;
  actual_mw: number | null;
}

export interface ConditionsEntry {
  interval_ts: string;
  load: ZoneLoad[];
  wind: RegionGen[];
  solar: RegionGen[];
  outages: FuelOutage[];
}

export interface ConditionsRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: ConditionsEntry[];
}

export interface MapMeta {
  run_id: string;
  window_start: string;
  window_end: string;
  sf_fit_r2: number | null;
  sf_oos_r2: number | null;
  coverage: number | null;
  sf_stability: number | null;
  n_kept: number | null;
}

// Fit details for the cursor's daily artifact.
export interface MapFitMetadata {
  run_id: string | null;
  window_start: string | null;
  window_end: string | null;
  sf_oos_r2: number | null;
  coverage: number | null;
  sf_stability: number | null;
  artifact_delivery_date: string | null;
  basis: "artifact" | "nearest_past" | null;
  available: boolean;
}

// A constraint's signed effect on a settlement point.
export interface SpExposure {
  constraint_key: string;
  ctype: string | null;
  sf: number;
  sf_clipped: boolean;
  mu: number | null;
  contribution: number | null;
  max_abs_sf: number | null;
  binding_hours: number | null;
}

export type ExposureRank = "contribution" | "sf";

// Constraints driving a selected settlement point.
export interface ExposuresResponse {
  sp: string;
  run_id: string;
  window_start: string;
  window_end: string;
  k: number;
  sf_oos_r2: number | null;
  sf_stability: number | null;
  node_max_abs_sf: number | null;
  rank: ExposureRank;
  // Sum of absolute contributions across all constraints, not just the top k.
  node_gross_total: number | null;
  available: boolean;
  // The point may be unavailable because it was not in service or in the fit.
  unavailable_reason:
    | "artifact_missing"
    | "interval_not_in_artifact"
    | "sp_not_in_service"
    | "sp_not_in_fit"
    | null;
  exposures: SpExposure[];
}

export interface ReachSp {
  settlement_point: string;
  sf: number;
  lat: number | null;
  lon: number | null;
  settlement_point_type: string | null;
  load_zone: string | null;
}

// Settlement points affected by a selected constraint.
export interface ConstraintReach {
  constraint_key: string;
  ctype: string | null;
  run_id: string;
  window_start: string;
  window_end: string;
  k: number;
  sf_oos_r2: number | null;
  sf_stability: number | null;
  max_abs_sf: number | null;
  n_rail: number | null;
  peak_offrail: number | null;
  binding_hours: number | null;
  shadow_price: number | null;
  dam_mu: number | null;
  forecast_error: number | null;
  daily_mu_rank: number | null;
  daily_mu_sum: number | null;
  import_members: number | null;
  export_members: number | null;
  available: boolean;
  // `artifact_missing` means no daily artifact; `constraint_not_in_artifact`
  // means the day's fit does not contain this constraint.
  unavailable_reason: string | null;
  // `nearest_past` uses the latest earlier artifact when the requested day is missing.
  basis?: "artifact" | "nearest_past";
  // True when the response is limited to the requested top k.
  truncated: boolean;
  sps: ReachSp[];
}

// A constraint marker in the map overview.
export interface OverviewConstraint {
  constraint_key: string;
  ctype: string | null; // 'gtc' | 'transmission' | 'radial'
  binding_hours: number | null;
  max_abs_sf: number | null;
  nodes: ReachSp[];
}

export interface MapOverview {
  run_id: string;
  window_start: string;
  window_end: string;
  n: number;
  k: number;
  sf_oos_r2: number | null;
  sf_stability: number | null;
  constraints: OverviewConstraint[];
}

// A daily constraint ranking. The basis selects forecast or ERCOT DAM shadow prices.
export interface RankedConstraint {
  constraint_id: string;
  rank: number;
  congestion_contribution: number;
  mu_mass: number;
  binding_hours: number;
  reach: number;
  n_members: number;
  ctype: string | null; // 'gtc' | 'transmission' | 'radial'
  n_import: number;
  n_export: number;
}

export interface RankedConstraints {
  run_id: string;
  delivery_date: string; // ISO date (YYYY-MM-DD)
  basis: "predicted" | "realized";
  k: number;
  n_ranked: number;
  constraints: RankedConstraint[];
}

// Initial Map workspace payload, including settlement-point GeoJSON.
export interface MapSummary {
  topology: unknown;
  overview: MapOverview | null;
  meta: MapMeta | null;
  availability: Record<string, BootstrapSectionStatus>;
}

export interface MapScorecardSource {
  source_id: string;
  series_id: "model" | "persistence" | "oracle";
  rank_spearman: number | null;
  sign_agree: number | null;
  topdecile_hit: number | null;
}

export interface MapScorecard {
  available: boolean;
  unavailable_reason: string | null;
  basis: "served_daily" | "served_daily_pending" | "weekly_backtest_fallback" | null;
  run_id: string | null;
  delivery_date: string;
  scored_week: string | null;
  horizon: number | null;
  sources: MapScorecardSource[];
  fit_metadata: MapFitMetadata | null;
}
