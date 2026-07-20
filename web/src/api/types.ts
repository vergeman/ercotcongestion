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

// The view axis, orthogonal to `Palette`. `forecastError` is the default landing
// view: a single map colored by P50 forecast − realized congestion (the product
// thesis, "where we missed the market"), SF overlay on. `dual` is the prediction
// | ERCOT side-by-side compare, SF overlay off by default. Because both panes
// subtract the same system-λ, LMP forecast error collapses exactly to congestion
// forecast error — so it is congestion-based regardless of the palette selection.
export type ViewMode = "forecastError" | "dual";

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

// =============================================================================
// /map/constraints/ranked — the per-day ranked constraint list (plan/0103). The
// list-shaped companion to the /map/overview marker pile: "which constraints
// drive today's congestion", ordered by a day-total contribution the map cannot
// express. Mirrors api/models.py ConstraintLobe / RankedConstraint /
// RankedConstraints. `basis` picks the μ series (predicted E_mu vs realized DAM
// shadow prices); the SF structure — reach, lobes, members — is shared.
// =============================================================================

// One end of a constraint's congestion dipole — its source (import, SF<0) or sink
// (export, SF>0) lobe. `lat`/`lon` are the |SF|-weighted centroid of the lobe's
// nodes; `peak_sf` the signed strongest node; `n_nodes` the located count above
// the floor. Null/zero for a one-sided or unlocated lobe.
export interface ConstraintLobe {
  lat: number | null;
  lon: number | null;
  peak_sf: number | null;
  n_nodes: number;
}

// One constraint in the per-day ranking. `congestion_contribution = mu_mass ·
// reach` is the sort key (descending); `rank` its 1-based position. `mu_mass`
// (Σ_ts |μ|) and `reach` (Σ_sp |SF|) are surfaced so the score is legible.
// `constraint_id` matches the overview's `constraint_key`, so a row highlights the
// same overlay mark; `source_lobe`/`sink_lobe` carry the import/export dipole.
export interface RankedConstraint {
  constraint_id: string;
  rank: number;
  congestion_contribution: number;
  mu_mass: number;
  reach: number;
  n_members: number;
  ctype: string | null; // 'gtc' | 'transmission' | 'radial'
  core_lat: number | null;
  core_lon: number | null;
  source_lobe: ConstraintLobe;
  sink_lobe: ConstraintLobe;
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

// =============================================================================
// /scoreboard/headline — the rolling backtest headline (30/90-day tiles). The
// panel scorecard's data. Mirrors api/models.py HeadlineCurrency /
// HeadlineWindow / ScoreboardHeadline. The one invariant (spec §6): a model
// figure never travels without its comparators — every currency carries the
// persistence delta and the oracle ceiling, so the client cannot render a lone
// model number.
// =============================================================================

// One pre-registered currency in one rolling window: the model figure with its
// comparators. `persistence_delta` = model − persistence (raw); read its sign
// against `higher_is_better`. `oracle` is the ceiling. Any field is null when a
// source had no scored week in the window.
export interface HeadlineCurrency {
  currency: string; // topdecile_hit | rank_spearman | sign_agree | pooled_r2
  higher_is_better: boolean;
  model: number | null;
  persistence: number | null;
  climatology: number | null;
  oracle: number | null;
  persistence_delta: number | null;
}

// One rolling window (30d / 90d): every currency pooled over the trailing weeks.
// `weeks` is how many weekly rows fed the pool; `week_start`/`week_end` bound them.
export interface HeadlineWindow {
  window_days: number; // 30 | 90
  weeks: number;
  week_start: string;
  week_end: string;
  currencies: HeadlineCurrency[];
}

// The rolling headline for one board (`run_id`) and `regime`. `as_of_week` is the
// latest week on the board — the anchor the windows trail from.
export interface ScoreboardHeadline {
  run_id: string;
  regime: string;
  as_of_week: string;
  windows: HeadlineWindow[];
}

// =============================================================================
// /scoreboard/weekly — the full weekly backtest series + pooled pre/post-RTC+B
// summary (the scoreboard page's data). Mirrors api/models.py WeeklyPoint /
// SourcePooled / WeeklySplit / ScoreboardWeekly. Every response carries all
// sources so a lone model figure can't be charted (§6).
// =============================================================================

// One (week, source) row for the chart. Screening currencies lead; magnitude
// (pooled_r2 / mae) files under a toggle. Band columns are model/all only.
export interface WeeklyPoint {
  week: string;
  source: string;
  pooled_r2: number | null;
  mae: number | null;
  rank_spearman: number | null;
  sign_agree: number | null;
  topdecile_hit: number | null;
  coverage80: number | null;
  band_width: number | null;
  pinball: number | null;
  sf_coverage: number | null;
  model_coverage: number | null;
  n_hours: number | null;
  n_nodes: number | null;
}

// One source's pooled currencies over a split — the week-mean of each metric.
export interface SourcePooled {
  source: string;
  pooled_r2: number | null;
  mae: number | null;
  rank_spearman: number | null;
  sign_agree: number | null;
  topdecile_hit: number | null;
}

// A pooled slice (all / pre_rtc_b / post_rtc_b). `gate` is the pre-registered
// verdict on the model's pooled means; `beats_persistence` the existence test.
export interface WeeklySplit {
  label: string; // all | pre_rtc_b | post_rtc_b
  n_weeks: number;
  sources: SourcePooled[];
  gate: string | null;
  beats_persistence: boolean | null;
}

export interface ScoreboardWeekly {
  run_id: string;
  regime: string;
  primary_source: string;
  rtc_b_cutover: string;
  points: WeeklyPoint[];
  splits: WeeklySplit[];
}

// =============================================================================
// /scoreboard/daily — the LIVE per-delivery-day board (plan/0102 §0003,
// spec-phase3 §3). Mirrors api/models.py DailyPoint / ScoreboardDaily. The live
// counterpart to the weekly backtest board: per-day grades of the SERVED
// forecast, same currency columns as WeeklyPoint so a live number and a backtest
// number are directly comparable. Every response carries all sources (model +
// persistence + climatology + oracle + the `null` flat tripwire), so a lone
// model figure can't be rendered (§6).
// =============================================================================

// One (delivery_date, source) live grade. Band columns (coverage80 / band_width
// / pinball) are populated on the model source only; model_coverage is NULL for
// now (deferred snapshot). All nullable — a declined/flat cell is null.
export interface DailyPoint {
  delivery_date: string;
  source: string;
  pooled_r2: number | null;
  mae: number | null;
  rank_spearman: number | null;
  sign_agree: number | null;
  topdecile_hit: number | null;
  coverage80: number | null;
  band_width: number | null;
  pinball: number | null;
  sf_coverage: number | null;
  model_coverage: number | null;
  n_hours: number | null;
  n_nodes: number | null;
}

export interface ScoreboardDaily {
  run_id: string;
  since: string | null;
  primary_source: string;
  points: DailyPoint[];
}
