import type { BootstrapSectionStatus, SourceDescriptor } from "./common";

// =============================================================================
// /scoreboard/summary weekly — the full weekly backtest series + pooled pre/post-RTC+B
// summary (the scoreboard page's data). Mirrors api/models.py WeeklyPoint /
// SourcePooled / WeeklySplit / ScoreboardWeekly.
// =============================================================================

// One (week, source) row for the chart. All nullable — a declined screening
// metric rides through as null.
export interface WeeklyPoint {
  week: string;
  source_id: string;
  series_id: string;
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

// One source's independently hours-weighted metrics over a split.
export interface SourcePooled {
  source_id: string;
  series_id: string;
  rank_spearman: number | null;
  sign_agree: number | null;
  topdecile_hit: number | null;
}

// A pooled slice (all / pre_rtc_b / post_rtc_b) with an existence test.
export interface WeeklySplit {
  label: string; // all | pre_rtc_b | post_rtc_b
  n_weeks: number;
  n_days: number;
  sources: SourcePooled[];
  beats_persistence: boolean | null;
}

export interface ScoreboardWeekly {
  run_id: string;
  primary_source_id: string;
  rtc_b_cutover: string;
  points: WeeklyPoint[];
  splits: WeeklySplit[];
  sources: SourceDescriptor[];
}

// =============================================================================
// /scoreboard/summary daily section — the newest final LIVE grade.
// Mirrors api/models.py DailyPoint / ScoreboardDaily. The live
// counterpart to the weekly backtest board: per-day grades of the SERVED
// forecast, same currency columns as WeeklyPoint so a live number and a backtest
// number are directly comparable. Every response carries all sources (model +
// persistence + climatology + oracle + the `null` flat tripwire.)
// =============================================================================

// One (delivery_date, source) live grade. Band columns (coverage80 / band_width
// / pinball) are populated on the model source only; model_coverage is NULL for
// now (deferred snapshot).
export interface DailyPoint {
  delivery_date: string;
  source_id: string;
  series_id: string;
  // Which forecast track this row grades: 1 = final (fires D−1), 2 = preview
  // (fires D−2). One board carries one horizon; it rides on every point so a
  // reader never has to guess which track a number belongs to.
  horizon: number;
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
  primary_source_id: string;
  // The track `points` grades; this summary section is always the final track.
  horizon: number;
  selected_delivery_date: string;
  points: DailyPoint[];
  sources: SourceDescriptor[];
}

// The `/scoreboard/summary` chart sequence. Weekly backtest and daily served
// grades retain distinct date fields and provenance; the final track is the
// only live cadence included.
export type ScoreCadence = "backtest_weekly" | "served_daily";

export interface ScoreHistoryPoint {
  source_id: string;
  series_id: string;
  cadence: ScoreCadence;
  week: string | null;
  delivery_date: string | null;
  rank_spearman: number | null;
  sign_agree: number | null;
  topdecile_hit: number | null;
  sf_coverage: number | null;
  model_coverage: number | null;
  n_hours: number | null;
  n_nodes: number | null;
}

export interface ScoreboardHistory {
  primary_source_id: string;
  weekly_run_id: string;
  daily_run_id: string | null;
  boundary_date: string | null;
  points: ScoreHistoryPoint[];
  sources: SourceDescriptor[];
}

// /scoreboard/summary — one bundled payload for the Scoreboard page's load-time
// requests. `availability` makes every nullable section's soft-fail state
// explicit.
export interface ScoreboardSummary {
  weekly: ScoreboardWeekly | null;
  daily: ScoreboardDaily | null;
  history: ScoreboardHistory | null;
  availability: Record<string, BootstrapSectionStatus>;
}
