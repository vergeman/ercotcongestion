import type { BootstrapSectionStatus } from "./common";

// The Data axis: which ERCOT quantity a map pane colors by.
//   congestion:  SPP − system_λ  (diverging palette)
//   lmp:         raw DAM SPP / (for the forecast pane) forecast congestion + system_λ, the
//                predicted counterpart — see `ForecastRangeEntry.lambda_source`
//                for its persistence-λ provenance pre-settlement.
export type MapDataMode = "congestion" | "lmp";

// The View axis, orthogonal to `MapDataMode`. Exactly one is active:
//   forecast:  single map, the model's deterministic prediction (the bare `/map`
//              default landing view).
//   market:    single map, ERCOT's realized DAM values.
//   compare:   the prediction | ERCOT side-by-side split (formerly `dual`).
//   error:     single map, forecast − realized congestion (the product
//              thesis, "where we missed the market"). Because both panes
//              subtract the same system-λ, LMP forecast error collapses
//              exactly to congestion forecast error, so this view locks
//              `MapDataMode` to `"congestion"` regardless of the prior
//              selection.
// `market`, `compare`, and `error` require settled data in the loaded window;
// pre-market they fall back to `forecast`.
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

// =============================================================================
// /forecast_range — per-hour forecast congestion for the current forecast run,
// the prediction counterpart to /ercot_range. Feeds the left ("prediction")
// pane through the same prefetch/scrubber path as the realized ranges, so the
// two panes align hour for hour. Each SP carries deterministic congestion,
// plus each hour's system-λ. Mirrors api/models.py ForecastSpState /
// ForecastRangeEntry / ForecastRangeResponse.
// =============================================================================

// One SP's deterministic forecast congestion at one hour: −(E_mu · SF).
export interface ForecastSpState {
  sp_id: string;
  forecast_congestion: number | null;
}

// All SPs' forecast congestion at one interval, plus that hour's system-λ.
// Predicted LMP = forecast_congestion + system_lambda
//
// On an unsettled hour `system_lambda` falls back to the most recent settled
// day's λ at the same Central hour.
export interface ForecastRangeEntry {
  interval_ts: string;
  system_lambda: number | null;
  lambda_source: "settled" | "persisted" | null;
  sps: ForecastSpState[];
}

// Per-hour forecast congestion across a window. `run_id` labels which refit is
// serving; the served day is the cursor hour's date. `entries` are the forecast
// hours in [start, end] for the current run. `horizons` maps each served UTC
// delivery day (`"YYYY-MM-DD"`) to the horizon it came from — 1 = final/t+1,
// 2 = preview/t+2.
export interface ForecastRangeResponse {
  start: string;
  end: string;
  run_id: string;
  count: number;
  entries: ForecastRangeEntry[];
  horizons: Record<string, number>;
}

// =============================================================================
// /conditions_range — per-hour Load / Wind / Solar / Outages, merged into one
// response.
//
// Every row carries both `forecast_mw` and `actual_mw` so the map's Forecast/
// Market/Compare/Error toggle can pick one client-side, no per-side request.
//
//   load    `zone` is one of the 8 NP3-561/NP6-345 weather zones, plus
//           "system". Forecast is the latest `load_forecast_zonal` vintage
//           posted no later than the hour it describes (no lookahead).
//
//   wind/solar
//           `region` is one of the 5 wind / 6 solar regions, plus "system".
//           Forecast reads the vintaged `*_forecast_regional` tables (no
//           lookahead), not the actual tables' own forecast-looking columns
//           (those dedup to the most recent posting, ~49h after the hour).
//
//   outages a DIFFERENT quantity from wind/solar — MW currently OFFLINE
//           (NP1-346), not MW produced — and a different cadence underneath:
//           the source table is a daily snapshot, so a day's values repeat
//           across its 24 hourly entries. `fuel` is one of gas/wind/solar/
//           coal/other/hydro, plus "total". `forecast_mw` is the D-1
//           no-lookahead vintage (mirrors compute.mu_forecast.outage_exposure's
//           leak boundary); `actual_mw` is the newest vintage through the day.
//
// Any list may be empty for an hour with nothing from that source — the
// client's null-dash rendering handles it the same as a null field.
// =============================================================================

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

// =============================================================================
// /map/* — the implied shift-factor structure (not time-indexed; one refit).
// Mirrors api/models.py MapMeta / SpExposure / ExposuresResponse / ReachSp /
// ConstraintReach.
// =============================================================================

// The refit the map is serving — one sf_window_meta row. `sf_oos_r2` /
// `sf_stability` are the confidence caveats every signed exposure renders with.
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

// Diagnostics for the SF window that produced the cursor's daily artifact.
// Unlike MapMeta, this is deliberately cursor-scoped.
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

// One constraint driving the queried node (a /map/exposures row). `sf` is the
// signed exposure ($/MWh per $ of μ) — caveated, read against window confidence.
// `contribution` = -sf * mu is the constraint's actual $/MWh of this node's
// congestion at the requested interval, and is what `rank=contribution` orders
// by; both it and `mu` are null under `rank=sf`, which describes structure and
// has no hour attached. `sf_clipped` marks a cell the fit pinned at its cap.
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

// How /map/exposures orders its list. `contribution` answers "what drove this
// node at t" and drops constraints that did not bind; `sf` answers "what could
// move this node" over the whole day's fit, quiet constraints included.
export type ExposureRank = "contribution" | "sf";

// Top-k constraints driving one node. `node_max_abs_sf` = max_c |SF[sp,c]| is
// the stable unsigned headline (spec §6); the signed `exposures` follow it.
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
  // Full-constraint gross magnitude, independent of the returned top-k:
  // `sum(abs(contribution))`. It supports a bounded share when drivers offset
  // and is null under `rank=sf`.
  node_gross_total: number | null;
  available: boolean;
  // No SF for this node on this day — not the same as being in the fit and
  // driving nothing.
  // `sp_not_in_service`: the node did not exist yet;
  // `sp_not_in_fit`: it existed but the fit dropped it.
  unavailable_reason:
    | "artifact_missing"
    | "interval_not_in_artifact"
    | "sp_not_in_service"
    | "sp_not_in_fit"
    | null;
  exposures: SpExposure[];
}

// One node a constraint drives (a /map/reach row). Signed `sf` splits the
// driven nodes into the constraint's import and export ends (the dipole).
export interface ReachSp {
  settlement_point: string;
  sf: number;
  lat: number | null;
  lon: number | null;
  settlement_point_type: string | null;
  load_zone: string | null;
}

// Top-k nodes one constraint drives — the constraint click. `sps` carries the
// signed reach for the dipole glow, each node placed from its own coords.
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
  // Forecast μ from the requested cursor hour's daily artifact. It is null for
  // a structural nearest-past fallback or when no cursor hour was requested.
  shadow_price: number | null;
  dam_mu: number | null;
  forecast_error: number | null;
  daily_mu_rank: number | null;
  daily_mu_sum: number | null;
  import_members: number | null;
  export_members: number | null;
  available: boolean;
  // "artifact_missing" (the day has no artifact) or
  // "constraint_not_in_artifact" (the day's fit does not carry this key).
  unavailable_reason: string | null;
  // Provenance of the served SF. "artifact" = the requested day's own artifact
  // (day-exact). "nearest_past" = that day had no artifact (a lagging/failed
  // forecast job), so the nearest earlier built day was served — window_start
  // reports which. The card labels it "SF as of <date>" so it never silently
  // disagrees with the (empty) matrix for the requested day.
  basis?: "artifact" | "nearest_past";
  // reports whether a bounded (`k`-limited) call was cut short of the
  // constraint's complete reach — always `false` for a `full=true` call.
  truncated: boolean;
  sps: ReachSp[];
}

// One constraint in the de-piled overview (a /map/overview row). `ctype` picks the
// mark's form; `nodes` is the signed top-k field the mark draws over AND anchors on
// (the client positions the mark from these coords — the radial ring on the peak-|SF|
// node — so there is no persisted centroid). The overview ignores the sign; the
// drill-down colors it.
export interface OverviewConstraint {
  constraint_key: string;
  ctype: string | null; // 'gtc' | 'transmission' | 'radial'
  binding_hours: number | null;
  max_abs_sf: number | null;
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
  sf_oos_r2: number | null;
  sf_stability: number | null;
  constraints: OverviewConstraint[];
}

// =============================================================================
// /map/constraints/ranked — the per-day ranked constraint list. The list-shaped
// companion to the /map/overview marker pile: "which constraints drive today's
// congestion", ordered by a day-total contribution the map cannot express.
// Mirrors api/models.py RankedConstraint / RankedConstraints. `basis` picks the
// μ series (predicted E_mu vs realized DAM shadow prices); the SF structure —
// reach, lobes, members — is shared.
// =============================================================================

// One constraint in the per-day ranking. `congestion_contribution = mu_mass ·
// reach` is the sort key (descending); `rank` its 1-based position. `mu_mass`
// (Σ_ts |μ|) and `reach` (Σ_sp |SF|) are surfaced so the score is legible.
// `constraint_id` matches the overview's `constraint_key`, so a row highlights the
// same overlay mark; `n_import`/`n_export` (located-node counts on the SF<0/SF>0
// sides) carry the import/export dipole. The μ statistics follow `basis`; SF
// reach is a fixed structural summary from the daily artifact.
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

// The per-day ranked list for one forecast run and basis. `n_ranked` is how many
// constraints carried a non-zero contribution (the pool the top-`k` is drawn
// from); `constraints` is that top-`k`, already ordered — the client never
// re-ranks (the server owns the order).
export interface RankedConstraints {
  run_id: string;
  delivery_date: string; // ISO date (YYYY-MM-DD)
  basis: "predicted" | "realized";
  k: number;
  n_ranked: number;
  constraints: RankedConstraint[];
}

// /map/summary — one bundled payload for the Map workspace's load-time
// requests. `topology` is the raw settlement-point GeoJSON (unchanged shape
// from GET /topology).
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
