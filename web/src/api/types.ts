// ERCOT SP snapshot payload. `sp_id` is the ERCOT settlement point
// identifier; `congestion` is the reference-adjusted congestion value
// (SPP − system_λ) from the run's congestion matrix.
export interface ErcotSpState {
  sp_id: string;
  congestion: number | null;
}

export interface ErcotStateRangeEntry {
  interval_ts: string;
  system_lambda: number | null;
  sps: ErcotSpState[];
}

export interface ErcotStateRangeResponse {
  start: string;
  end: string;
  count: number;
  entries: ErcotStateRangeEntry[];
}

// =============================================================================
// /matrix/frame — one bounded, day-stable constraint × settlement-point frame.
// The API owns the row and column ordering.  `sf.values` is row-major and is
// aligned exactly to `rows` then `columns`; it contains recovered implied shift
// factors, not an official ERCOT shift-factor field.
// =============================================================================

export type MatrixDamStatus = "pending" | "partial" | "available";

// Which axis the backend gave the primary ranked/searched list. The wire shape
// is unchanged (`rows` are always constraints, `columns` always settlement
// points); the client transposes `nodes` at draw time.
export type MatrixOrientation = "constraints" | "nodes";

export interface MatrixRow {
  constraint_key: string;
  constraint_name: string;
  contingency_name: string | null;
  constraint_type: string | null;
  forecast_mu: number;
  ercot_dam_mu: number | null;
  daily_rank: number;
  binding_hours: number;
  max_abs_sf: number;
}

export interface MatrixColumn {
  settlement_point: string;
  settlement_point_type: string | null;
  load_zone: string | null;
  max_abs_sf: number;
}

// A cell whose |value| reaches the frame's `sf_abs_cap` was pinned there by the
// ridge fit's clip — a bound, not a measurement. No parallel mask is sent: the
// clip is exact, so `Math.abs(v) >= sf_abs_cap` is the same test the server
// would apply, at a fraction of the payload.
export interface MatrixSfValues {
  row_count: number;
  column_count: number;
  values: number[];
}

export interface MatrixFrame {
  available: boolean;
  unavailable_reason: string | null;
  run_id: string;
  delivery_date: string;
  interval_ts: string;
  fit_window_start: string | null;
  fit_window_end: string | null;
  orientation: MatrixOrientation;
  dam_status: MatrixDamStatus;
  row_ordering: string;
  column_ordering: string;
  rows_truncated: boolean;
  columns_truncated: boolean;
  total_constraint_count: number;
  total_settlement_point_count: number;
  sf_day_max_abs: number;
  contribution_day_max_abs: number;
  // The fit's |SF| clip, so the threshold has one source rather than a
  // hardcoded 1.0 on both sides of the wire.
  sf_abs_cap: number;
  rows: MatrixRow[];
  columns: MatrixColumn[];
  sf: MatrixSfValues;
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

// Compact realized-range wire format. `sp_ids` is the one settlement-point
// index for the response; each entry's same-length arrays align to it.
export interface ErcotRangeEntry {
  interval_ts: string;
  system_lambda: number | null;
  congestion: Array<number | null>;
  spp: Array<number | null>;
}

export interface ErcotRangeResponse {
  start: string;
  end: string;
  count: number;
  sp_ids: string[];
  entries: ErcotRangeEntry[];
}

// The Data axis (0130): which ERCOT quantity a map pane colors by.
//   congestion → SPP − system_λ  (diverging palette)
//   lmp        → raw DAM SPP / (for the forecast pane) P50 + system_λ, the
//                predicted counterpart — see `ForecastRangeEntry.lambda_source`
//                for its persistence-λ provenance pre-settlement.
export type MapDataMode = "congestion" | "lmp";

// The View axis (0130), orthogonal to `MapDataMode`. Exactly one is active:
//   forecast → single map, the model's own P50 prediction (the bare `/map`
//              default landing view).
//   market   → single map, ERCOT's realized DAM values.
//   compare  → the prediction | ERCOT side-by-side split (formerly `dual`).
//   error    → single map, P50 forecast − realized congestion (the product
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
// subtracts). On an unsettled hour `system_lambda` falls back to the most
// recent settled day's λ at the same Central hour (0130's persistence display
// convention — never a model input); `lambda_source` says which curve served
// it, `null` only when no settled day exists yet to persist from.
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
// 2 = preview/t+2 (0123) — the provenance behind the one coalesced series.
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
// response (plan/0141; replaces the earlier load_zone_range/generation_range/
// outages_range split once the frontend settled on one "Conditions" section).
// Every row carries both `forecast_mw` and `actual_mw` so the map's Forecast/
// Market/Compare/Error toggle can pick one client-side, no per-side request.
//
//   load    `zone` is one of the 8 NP3-561/NP6-345 weather zones, plus
//           "system". Forecast is the latest `load_forecast_zonal` vintage
//           posted no later than the hour it describes (no lookahead).
//   wind/solar
//           `region` is one of the 5 wind / 6 solar regions, plus "system".
//           Forecast reads the vintaged `*_forecast_regional` tables (no
//           lookahead), not the actual tables' own forecast-looking columns
//           (those dedup to the most recent posting, ~49h after the hour).
//   outages a DIFFERENT quantity from wind/solar — MW currently OFFLINE
//           (NP1-346), not MW produced — and a different cadence underneath:
//           the source table is a daily snapshot, so a day's values repeat
//           across its 24 hourly entries. `fuel` is one of gas/wind/solar/
//           coal/other/hydro, plus "total". `forecast_mw` is the D-1
//           no-lookahead vintage (mirrors compute.mu.outage_exposure's leak
//           boundary); `actual_mw` is the newest vintage through the day.
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
// move this node" over the whole day's fit, quiet constraints included. The two
// read identical SF values — only the ordering and filtering differ, which is
// exactly why they used to look like disagreeing data (0145).
export type ExposureRank = "contribution" | "sf";

// Top-k constraints driving one node. `node_max_abs_sf` = max_c |SF[sp,c]| is
// the stable unsigned headline (spec §6); the signed `exposures` follow it.
//
// 0144: served from the requested day's SF artifact, so these values match the
// matrix at the same node and interval. `window_start`/`window_end` bound that
// day's block, and `oos_r2`/`sf_stability` are null — they describe the rolling
// fit that no longer backs these numbers. `available: false` means the day has
// no artifact at all, as opposed to a node that simply drives nothing.
export interface ExposuresResponse {
  sp: string;
  run_id: string;
  window_start: string;
  window_end: string;
  k: number;
  oos_r2: number | null;
  sf_stability: number | null;
  node_max_abs_sf: number | null;
  rank: ExposureRank;
  // Full-constraint gross magnitude, independent of the returned top-k:
  // `sum(abs(contribution))`. It supports a bounded share when drivers offset
  // and is null under `rank=sf`.
  node_gross_total: number | null;
  available: boolean;
  // No SF for this node on this day — not the same as being in the fit and
  // driving nothing (0146). `sp_not_in_service`: the node did not exist yet;
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
  oos_r2: number | null;
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
  // 0144: "artifact_missing" (the day has no artifact) or
  // "constraint_not_in_artifact" (the day's fit does not carry this key).
  unavailable_reason: string | null;
  // Provenance of the served SF. "artifact" = the requested day's own artifact
  // (day-exact). "nearest_past" = that day had no artifact (a lagging/failed
  // forecast job), so the nearest earlier built day was served — window_start
  // reports which. The card labels it "SF as of <date>" so it never silently
  // disagrees with the (empty) matrix for the requested day.
  basis?: "artifact" | "nearest_past";
  // 0139/0001: reports whether a bounded (`k`-limited) call was cut short of
  // the constraint's complete reach — always `false` for a `full=true` call.
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
  oos_r2: number | null;
  sf_stability: number | null;
  constraints: OverviewConstraint[];
}

// =============================================================================
// /map/constraints/ranked — the per-day ranked constraint list (plan/0103). The
// list-shaped companion to the /map/overview marker pile: "which constraints
// drive today's congestion", ordered by a day-total contribution the map cannot
// express. Mirrors api/models.py RankedConstraint / RankedConstraints. `basis`
// picks the μ series (predicted E_mu vs realized DAM shadow prices); the SF
// structure — reach, lobes, members — is shared.
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
  // Which forecast track this row grades: 1 = final (fires D−1), 2 = preview
  // (fires D−2). One board carries one horizon; it rides on every point so a
  // reader never has to guess which track a number belongs to.
  horizon: number;
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
  // The single track `points` grades, and every track this run has graded — so
  // the page can offer the switch without a second request.
  horizon: number;
  horizons: number[];
  points: DailyPoint[];
}

// /scoreboard/summary — one bundled payload for the Scoreboard page's
// load-time requests (0137). Each field keeps its single-section shape; null
// exactly when that section's own endpoint would 503 (that board has no rows
// yet).
export interface ScoreboardSummary {
  weekly: ScoreboardWeekly | null;
  headline: ScoreboardHeadline | null;
  daily: ScoreboardDaily | null;
}

// /map/summary — one bundled payload for the Map workspace's load-time
// requests (0137). `topology` is the raw settlement-point GeoJSON (unchanged
// shape from GET /topology); the other three keep their single-section shape
// and are null exactly when that section's own endpoint would 503.
export interface MapSummary {
  topology: unknown;
  overview: MapOverview | null;
  meta: MapMeta | null;
  headline: ScoreboardHeadline | null;
}

// /analysis/hero — the on-demand v6 daily-brief hero.  Unlike the legacy
// analysis brief this is composed from query-layer slots, not a stored blob.
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
  forecast_history_median: number;
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
  forecast_history_median: number;
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

// /analysis/grade — independent daily verification halves. Constraint and node
// scores intentionally never blend into one headline value.
export interface AnalysisGradeMetrics {
  detection_ap: number | null;
  magnitude_overlap: number | null;
  timing_daily_skill: number | null;
  timing_hourly_skill: number | null;
  top_decile_daily_capture?: number | null;
  top_decile_hourly_capture?: number | null;
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
  model?: AnalysisGradeMetrics | null;
  persistence?: AnalysisGradeMetrics | null;
  climatology?: AnalysisGradeMetrics | null;
  support?: AnalysisGradeSupport | null;
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
  model: AnalysisGradeMetrics;
  persistence: AnalysisGradeMetrics;
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

// /analysis/brief — one bundled payload for a Brief delivery day (0137).
// Each field keeps the exact shape its single-section endpoint already
// served, so section consumers built against those shapes are untouched.
export interface BriefDay {
  hero: BriefHero;
  context: BriefContext;
  standouts: Standouts;
  top_nodes: TopNodes;
  top_constraints: TopConstraints;
  grade: AnalysisGrade;
  grade_history: AnalysisGradeHistory;
}

// `/analysis/brief/hero` is the first-paint payload. It deliberately carries
// only the hero plus inexpensive artifact-backed date navigation; the tables
// and grade arrive through `/analysis/brief/details` afterwards.
export interface BriefHeroShell {
  hero: BriefHero;
  previous_delivery_date: string | null;
  next_delivery_date: string | null;
}

export interface BriefHeroStats {
  run_id: string;
  delivery_date: string;
  horizon: number;
  slots: Record<string, Record<string, unknown>>;
}

export interface BriefDetails {
  context: BriefContext;
  standouts?: Standouts | null;
  top_nodes: TopNodes;
  top_constraints: TopConstraints;
  grade: AnalysisGrade;
  grade_history: AnalysisGradeHistory;
}

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
// artifact (plan/0139-0001), the search index behind the Matrix sidebar
// (0139-0002). Never a Brief top-k.
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

// /analysis/essp — hourly, source-explicit topology grouping.  GroupIndex is
// only meaningful within this returned hour/source; consumers key groups by
// their members rather than persisting it as a cross-day identity.
export type EsspSource = "study" | "final";

export interface EsspGroup {
  group_index: number;
  settlement_points: string[];
}

export interface AnalysisEsspGroupsResponse {
  available: boolean;
  unavailable_reason?: "essp_missing";
  interval_ts: string;
  source: EsspSource;
  groups?: EsspGroup[];
}
