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

// The palette selects the ERCOT quantity a map colors by. Each mode picks the
// ERCOT quantity the pane renders:
//   congestion → SPP − system_λ  (diverging palette)
//   lmp        → raw DAM SPP      (LMP palette)
//   off        → no SP fill; the map shows the SF overlay alone (overlay-only
//                focus). The overlay stays independently toggleable.
export type Palette = "congestion" | "lmp" | "off";

// The view axis, orthogonal to `Palette`. `basis` is the default landing view:
// a single map colored by predicted − market congestion (the product thesis,
// "where we disagree with the market"), SF overlay on. `dual` is the prediction
// | ERCOT side-by-side compare, SF overlay off by default. Because both panes
// subtract the same system-λ, LMP-basis collapses exactly to congestion-basis —
// so basis is congestion-based regardless of the palette selection.
export type ViewMode = "basis" | "dual";

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
// /forecast_range — per-hour forecast congestion for the current forecast run,
// the prediction counterpart to /ercot_spp_range. Feeds the left ("prediction")
// pane through the same prefetch/scrubber path as the realized ranges, so the
// two panes align hour for hour. Expanded for prediction: P10/P50/P90 per SP,
// plus each hour's system-λ. Mirrors api/models.py ForecastSpState /
// ForecastRangeEntry / ForecastRangeResponse.
// =============================================================================

// One SP's forecast congestion at one hour. `p50` (sampling median) is the pane
// fill; `p10`/`p90` bracket it. Nullable — a NULL percentile rides through
// rather than dropping the SP.
export interface ForecastSpState {
  sp_id: string;
  p10: number | null;
  p50: number | null;
  p90: number | null;
}

// All SPs' forecast congestion at one interval, plus that hour's system-λ.
// Predicted LMP = p50 + system_lambda (same reference the market side
// subtracts). Null λ → LMP unset for the hour.
export interface ForecastRangeEntry {
  interval_ts: string;
  system_lambda: number | null;
  sps: ForecastSpState[];
}

// Per-hour forecast congestion across a window. `run_id` labels which refit is
// serving; the served day is the cursor hour's date. `entries` are the forecast
// hours in [start, end] for the current run.
export interface ForecastRangeResponse {
  start: string;
  end: string;
  run_id: string;
  count: number;
  entries: ForecastRangeEntry[];
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
