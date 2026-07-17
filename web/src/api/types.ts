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

// Raw DAM SPP per settlement point, per hour. Feeds the LMP palette so the
// price view renders directly from ERCOT's published prices.
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

// The palette drives both panes (prediction left, actual ERCOT right). Each
// mode picks the ERCOT quantity both panes render:
//   congestion → SPP − system_λ  (diverging palette)
//   lmp        → raw DAM SPP      (LMP palette)
export type ViewMode = "congestion" | "lmp";

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

// =============================================================================
// /map/* — the implied shift-factor structure (not time-indexed; one refit).
// Mirrors api/models.py MapMeta / ConstraintGeo / SpExposure / ExposuresResponse
// / ReachSp / ConstraintReach.
// =============================================================================

// The refit the map is serving — one sf_window_meta row. `oos_r2` /
// `sf_stability` are the confidence caveats every signed exposure renders with.
export interface MapMeta {
  run_id: string;
  window_start: string;
  window_end: string;
  fit_r2: number | null;
  oos_r2: number | null;
  coverage: number | null;
  sf_stability: number | null;
  n_kept: number | null;
}

// One constraint at its |SF|-weighted centroid — the overlay marker. Large
// `spread_km` is a multimodality caution (centroid can fall between lobes).
export interface ConstraintGeo {
  constraint_key: string;
  lat: number | null;
  lon: number | null;
  zone_shares: Record<string, number> | null;
  kv_mean: number | null;
  kv_max: number | null;
  spread_km: number | null;
  max_abs_sf: number | null;
  n_rail: number | null;
  peak_offrail: number | null;
  binding_hours: number | null;
}

// One constraint driving the queried node (a /map/exposures row). `sf` is the
// signed exposure ($/MWh per $ of μ) — caveated, read against window confidence.
export interface SpExposure {
  constraint_key: string;
  sf: number;
  lat: number | null;
  lon: number | null;
  max_abs_sf: number | null;
  binding_hours: number | null;
}

// Top-k constraints driving one node. `node_max_abs_sf` = max_c |SF[sp,c]| is
// the stable unsigned headline (spec §6); the signed `exposures` follow it.
export interface ExposuresResponse {
  sp: string;
  run_id: string;
  window_start: string;
  window_end: string;
  k: number;
  oos_r2: number | null;
  sf_stability: number | null;
  node_max_abs_sf: number | null;
  exposures: SpExposure[];
}

// One node a constraint drives (a /map/reach row). Signed `sf` splits the
// driven nodes into the constraint's import and export ends (the dipole).
export interface ReachSp {
  settlement_point: string;
  sf: number;
  lat: number | null;
  lon: number | null;
}

// Top-k nodes one constraint drives — the constraint click. `lat`/`lon` are the
// constraint's own centroid; `sps` carries the signed reach for the dipole glow.
export interface ConstraintReach {
  constraint_key: string;
  run_id: string;
  window_start: string;
  window_end: string;
  k: number;
  oos_r2: number | null;
  sf_stability: number | null;
  lat: number | null;
  lon: number | null;
  max_abs_sf: number | null;
  n_rail: number | null;
  peak_offrail: number | null;
  binding_hours: number | null;
  sps: ReachSp[];
}

// One constraint in the de-piled overview (a /map/overview row). Positioned at
// its |SF|²-core (`core_lat`/`core_lon`) — on its strongest lobe, not averaged to
// the empty center like `lat`/`lon` (the |SF|-mean centroid). `ctype` picks the
// mark's form; `nodes` is the signed top-k field the mark draws over (the overview
// ignores the sign; the drill-down colors it). Core NULL → unlocatable.
export interface OverviewConstraint {
  constraint_key: string;
  ctype: string | null; // 'gtc' | 'transmission' | 'radial'
  binding_hours: number | null;
  max_abs_sf: number | null;
  core_lat: number | null;
  core_lon: number | null;
  lat: number | null;
  lon: number | null;
  nodes: ReachSp[];
}

// The whole overview for the current refit — top-`n` constraints by binding hours,
// each at its core with its type and signed top-`k` field. One bulk payload.
export interface MapOverview {
  run_id: string;
  window_start: string;
  window_end: string;
  n: number;
  k: number;
  oos_r2: number | null;
  sf_stability: number | null;
  constraints: OverviewConstraint[];
}
