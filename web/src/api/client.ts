import type {
  ErcotStateRangeResponse,
  ErcotSppRangeResponse,
  ErcotRangeResponse,
  ForecastRangeResponse,
  MapMeta,
  ExposuresResponse,
  ConstraintReach,
  MapOverview,
  RankedConstraints,
  ScoreboardHeadline,
  ScoreboardWeekly,
  ScoreboardDaily,
  MatrixFrame,
  AnalysisBrief,
  BriefHero,
  BriefHeroLatest,
  Standouts,
  TopConstraints,
  TopNodes,
  AnalysisGrade,
  AnalysisBasis,
  AnalysisNodeResponse,
  AnalysisPathResponse,
  AnalysisSettlementPointsResponse,
  AnalysisEsspGroupsResponse,
  EsspSource,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchTopology(): Promise<unknown> {
  const r = await fetch(`${BASE}/topology`);
  if (!r.ok) throw new Error(`topology ${r.status}`);
  return r.json();
}

export interface MatrixFrameRequest {
  rowLimit?: number;
  columnLimit?: number;
  rowPreset?: "top30" | "top100" | "pinned";
  constraintType?: "gtc" | "transmission" | "radial";
  constraintSearch?: string;
  settlementPointSearch?: string;
  pinnedConstraints?: string[];
  pinnedSettlementPoints?: string[];
  columnSet?: "core" | "anchors" | "pinned" | "core_pinned";
  signal?: AbortSignal;
}

// A Matrix frame is a causal, immutable-artifact-backed rectangle.  Unlike the
// playback range APIs, an unavailable historical artifact is a successful
// response with `available: false`; callers can present that distinction
// directly instead of treating it as a network failure.
export async function fetchMatrixFrame(
  intervalTs: Date,
  {
    rowLimit = 30,
    columnLimit = 40,
    rowPreset = "top30",
    constraintType,
    constraintSearch,
    settlementPointSearch,
    pinnedConstraints = [],
    pinnedSettlementPoints = [],
    columnSet = "core",
    signal,
  }: MatrixFrameRequest = {}
): Promise<MatrixFrame> {
  const qs = new URLSearchParams({
    interval_ts: intervalTs.toISOString(),
    row_limit: String(rowLimit),
    column_limit: String(columnLimit),
    column_set: columnSet,
    row_preset: rowPreset,
  });
  if (constraintType) qs.set("constraint_type", constraintType);
  if (constraintSearch) qs.set("constraint_search", constraintSearch);
  if (settlementPointSearch) qs.set("settlement_point_search", settlementPointSearch);
  pinnedConstraints.forEach((key) => qs.append("pinned_constraint", key));
  pinnedSettlementPoints.forEach((point) => qs.append("pinned_settlement_point", point));
  const r = await fetch(`${BASE}/matrix/frame?${qs.toString()}`, { signal });
  if (!r.ok) throw new Error(`matrix/frame ${r.status}`);
  return r.json();
}

// ERCOT SP congestion (SPP − system_λ) over the window. Returns `null` — not
// throws — when the backend reports the artifact isn't built (503), so the
// caller can render an empty map rather than error out.
export async function fetchErcotStateRange(
  start: Date,
  end: Date
): Promise<ErcotStateRangeResponse | null> {
  const r = await fetch(
    `${BASE}/ercot_state_range?start=${start.toISOString()}&end=${end.toISOString()}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`ercot_state_range ${r.status}`);
  return r.json();
}

// Raw DAM SPP per settlement point over the window. Same soft-fail contract
// as ercot_state_range: 503 returns null.
export async function fetchErcotSppRange(
  start: Date,
  end: Date
): Promise<ErcotSppRangeResponse | null> {
  const r = await fetch(
    `${BASE}/ercot_spp_range?start=${start.toISOString()}&end=${end.toISOString()}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`ercot_spp_range ${r.status}`);
  return r.json();
}

// Compact replacement for the two realized range calls above. Settlement-point
// IDs are sent once, and congestion + SPP share the same timestamped rows.
export async function fetchErcotRange(
  start: Date,
  end: Date
): Promise<ErcotRangeResponse | null> {
  const r = await fetch(
    `${BASE}/ercot_range?start=${start.toISOString()}&end=${end.toISOString()}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`ercot_range ${r.status}`);
  return r.json();
}

// =============================================================================
// /map/* — implied shift-factor structure for the current refit. Same soft-fail
// contract as the realized ranges: 503 (no window built) returns null so the
// caller renders the map without the SF overlay rather than erroring out.
// These are not time-indexed — one resolved (run_id, window_start) per request.
// =============================================================================

// The refit being served (run + window + confidence). Null on 503.
export async function fetchMapMeta(): Promise<MapMeta | null> {
  const r = await fetch(`${BASE}/map/meta`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/meta ${r.status}`);
  return r.json();
}

// Per-hour forecast congestion (P10/P50/P90) per SP over the window — the left
// ("prediction") pane's fill, aligned to the same scrubber as the realized
// ranges. Each hour carries its system-λ so predicted LMP = p50 + λ resolves on
// the client. Call with no args for the default landing view: the server returns
// the current run's latest delivery day — a UTC calendar day, so in CT it spans
// 19:00 → 18:00 (CDT) rather than midnight to midnight — and the response's
// start/end define the window the realized ranges are then fetched to match.
// Same soft-fail contract:
// 503 (no forecast run published / no hours in range) returns null so the pane
// falls back rather than erroring.
export async function fetchForecastRange(
  start?: Date,
  end?: Date
): Promise<ForecastRangeResponse | null> {
  const qs = new URLSearchParams();
  if (start) qs.set("start", start.toISOString());
  if (end) qs.set("end", end.toISOString());
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const r = await fetch(`${BASE}/forecast_range${suffix}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`forecast_range ${r.status}`);
  return r.json();
}

// Top-k constraints driving a node, by |sf| — the node-explorer click. An
// unknown `sp` returns an empty exposures list, not an error. Null on 503.
export async function fetchMapExposures(
  sp: string,
  k = 15
): Promise<ExposuresResponse | null> {
  const r = await fetch(
    `${BASE}/map/exposures?sp=${encodeURIComponent(sp)}&k=${k}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/exposures ${r.status}`);
  return r.json();
}

// Top-k nodes a constraint drives, by |sf| — the constraint click. Signed `sf`
// carries the import/export dipole. Null on 503.
export async function fetchMapReach(
  constraint: string,
  k = 15
): Promise<ConstraintReach | null> {
  const r = await fetch(
    `${BASE}/map/reach?constraint=${encodeURIComponent(constraint)}&k=${k}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/reach ${r.status}`);
  return r.json();
}

// The de-piled overview: top-`n` constraints by binding hours, each at its |SF|²
// core with its type and signed top-`k` field. One bulk payload for the initial
// all-constraints presentation (replaces the /map/constraints centroid pile).
// Null on 503.
export async function fetchMapOverview(
  n = 70,
  k = 16
): Promise<MapOverview | null> {
  const r = await fetch(`${BASE}/map/overview?n=${n}&k=${k}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/overview ${r.status}`);
  return r.json();
}

// The per-day ranked constraint list — "which constraints drive today's
// congestion", the list companion to the overview marker pile. `basis` picks the
// μ series (predicted E_mu vs realized DAM shadow prices); the server owns the
// order, so the client never re-ranks. Omit `day` for the forecast run's latest
// built day. Same soft-fail contract: 503 (no forecast run / no artifact) returns
// null so the panel renders empty rather than erroring.
export async function fetchMapConstraintsRanked(
  basis: "predicted" | "realized" = "predicted",
  day?: string,
  k = 30
): Promise<RankedConstraints | null> {
  const qs = new URLSearchParams({ basis, k: String(k) });
  if (day) qs.set("day", day);
  const r = await fetch(`${BASE}/map/constraints/ranked?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/constraints/ranked ${r.status}`);
  return r.json();
}

// The rolling backtest headline (30/90-day tiles) for the side-panel scorecard.
// Same soft-fail contract: 503 (no board loaded / regime has no rows) returns
// null so the panel renders its network stats without the scorecard rather than
// erroring. Reads the backtest board — independent of the forecast run.
export async function fetchScoreboardHeadline(
  regime = "all"
): Promise<ScoreboardHeadline | null> {
  const r = await fetch(
    `${BASE}/scoreboard/headline?regime=${encodeURIComponent(regime)}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`scoreboard/headline ${r.status}`);
  return r.json();
}

// The full weekly backtest series + pooled pre/post-RTC+B summary for the
// scoreboard page. All sources ride along regardless of `source` (the page's
// foregrounded series). Same soft-fail contract: 503 (no board / regime empty)
// returns null. Reads the backtest board — independent of the forecast run.
export async function fetchScoreboardWeekly(
  source = "model",
  regime = "all"
): Promise<ScoreboardWeekly | null> {
  const qs = new URLSearchParams({ source, regime });
  const r = await fetch(`${BASE}/scoreboard/weekly?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`scoreboard/weekly ${r.status}`);
  return r.json();
}

// The LIVE per-delivery-day grade series — grades of the SERVED forecast, the
// live counterpart to the weekly backtest board. All sources ride along
// regardless of `source` (the page's foregrounded series). Resolves its own
// run_id (the run with the most recent graded day), independent of the board.
// Same soft-fail contract: 503 (no live grade has run yet / no rows since the
// date) returns null so the page renders the backtest board alone rather than
// erroring.
export async function fetchScoreboardDaily(
  source = "model",
  since?: string
): Promise<ScoreboardDaily | null> {
  const qs = new URLSearchParams({ source });
  if (since) qs.set("since", since);
  const r = await fetch(`${BASE}/scoreboard/daily?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`scoreboard/daily ${r.status}`);
  return r.json();
}

// =============================================================================
// /analysis/brief[/latest] — the server-computed daily Insight Brief (0124/0125).
// Both fetchers soft-fail to null on 503 (no forecast run published), matching
// the scoreboard/matrix contract; a day/run with no brief is not a network
// failure but an `available: false` envelope the page renders as an empty state.
// =============================================================================

// The latest day's full brief for the current run, plus `available_dates` — the
// run's sorted day index the page steps prev/next through. The page's landing
// call. Null on 503 (no forecast run published yet).
export async function fetchAnalysisBriefLatest(
  runId?: string
): Promise<AnalysisBrief | null> {
  const qs = new URLSearchParams();
  if (runId) qs.set("run_id", runId);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const r = await fetch(`${BASE}/analysis/brief/latest${suffix}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/brief/latest ${r.status}`);
  return r.json();
}

// One specific day's full brief (the frozen 0124 per-day endpoint). Used for the
// prev/next day steps once `available_dates` is known. Null on 503; a day with no
// brief returns an `available: false` envelope (not an error).
export async function fetchAnalysisBrief(
  deliveryDate: string,
  runId?: string
): Promise<AnalysisBrief | null> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate });
  if (runId) qs.set("run_id", runId);
  const r = await fetch(`${BASE}/analysis/brief?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/brief ${r.status}`);
  return r.json();
}

// v6's generated hero.  An absent artifact is a successful, explicit empty
// state; 503 still means no published run at all.
export async function fetchBriefHero(
  deliveryDate: string,
  runId?: string
): Promise<BriefHero | null> {
  const qs = new URLSearchParams({ date: deliveryDate });
  if (runId) qs.set("run_id", runId);
  const r = await fetch(`${BASE}/analysis/hero?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/hero ${r.status}`);
  return r.json();
}

// V6 cold-entry discovery. This intentionally does not read the legacy
// analysis_brief index: it selects only days with both UTC artifacts required
// to stitch the Brief's Chicago delivery-day tables.
export async function fetchBriefHeroLatest(
  runId?: string,
): Promise<BriefHeroLatest | null> {
  const qs = new URLSearchParams();
  if (runId) qs.set("run_id", runId);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const r = await fetch(`${BASE}/analysis/hero/latest${suffix}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/hero/latest ${r.status}`);
  return r.json();
}

export async function fetchTopConstraints(
  deliveryDate: string,
  { runId, horizon, k = 10 }: { runId?: string; horizon?: number; k?: number } = {},
): Promise<TopConstraints | null> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate, k: String(k) });
  if (runId) qs.set("run_id", runId);
  if (horizon != null) qs.set("horizon", String(horizon));
  const r = await fetch(`${BASE}/analysis/top-constraints?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/top-constraints ${r.status}`);
  return r.json();
}

export async function fetchStandouts(
  deliveryDate: string,
  { runId, horizon, k = 4 }: { runId?: string; horizon?: number; k?: number } = {},
): Promise<Standouts | null> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate, k: String(k) });
  if (runId) qs.set("run_id", runId);
  if (horizon != null) qs.set("horizon", String(horizon));
  const r = await fetch(`${BASE}/analysis/standouts?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/standouts ${r.status}`);
  return r.json();
}

export async function fetchTopNodes(
  deliveryDate: string,
  { runId, horizon, k = 15 }: { runId?: string; horizon?: number; k?: number } = {},
): Promise<TopNodes | null> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate, k: String(k) });
  if (runId) qs.set("run_id", runId);
  if (horizon != null) qs.set("horizon", String(horizon));
  const r = await fetch(`${BASE}/analysis/top-nodes?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/top-nodes ${r.status}`);
  return r.json();
}

export async function fetchAnalysisGrade(
  deliveryDate: string,
  { runId, horizon }: { runId?: string; horizon?: number } = {},
): Promise<AnalysisGrade | null> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate });
  if (runId) qs.set("run_id", runId);
  if (horizon != null) qs.set("horizon", String(horizon));
  const r = await fetch(`${BASE}/analysis/grade?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/grade ${r.status}`);
  return r.json();
}

// Full-artifact brief attribution. Unlike `/matrix/frame`, these requests do
// not bound the SF transpose: a selected node/path receives every nonzero term.
export interface AnalysisAttributionRequest {
  deliveryDate: string;
  basis?: AnalysisBasis;
  runId?: string;
  horizon?: number;
  hours?: string[];
  minAbsSf?: number;
  signal?: AbortSignal;
}

function attributionQuery(request: AnalysisAttributionRequest): URLSearchParams {
  const qs = new URLSearchParams({ delivery_date: request.deliveryDate });
  if (request.basis) qs.set("basis", request.basis);
  if (request.runId) qs.set("run_id", request.runId);
  if (request.horizon != null) qs.set("horizon", String(request.horizon));
  if (request.minAbsSf != null) qs.set("min_abs_sf", String(request.minAbsSf));
  request.hours?.forEach((hour) => qs.append("hours", hour));
  return qs;
}

export async function fetchAnalysisNode(
  settlementPoint: string,
  request: AnalysisAttributionRequest,
): Promise<AnalysisNodeResponse> {
  const qs = attributionQuery(request);
  qs.set("settlement_point", settlementPoint);
  const r = await fetch(`${BASE}/analysis/node?${qs.toString()}`, { signal: request.signal });
  if (!r.ok) throw new Error(`analysis/node ${r.status}`);
  return r.json();
}

export async function fetchAnalysisPath(
  source: string,
  sink: string,
  request: AnalysisAttributionRequest,
): Promise<AnalysisPathResponse> {
  const qs = attributionQuery(request);
  qs.set("source", source);
  qs.set("sink", sink);
  const r = await fetch(`${BASE}/analysis/path?${qs.toString()}`, { signal: request.signal });
  if (!r.ok) throw new Error(`analysis/path ${r.status}`);
  return r.json();
}

export async function fetchAnalysisSettlementPoints(
  deliveryDate: string,
  { runId, horizon, signal }: Pick<AnalysisAttributionRequest, "runId" | "horizon" | "signal"> = {},
): Promise<AnalysisSettlementPointsResponse> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate });
  if (runId) qs.set("run_id", runId);
  if (horizon != null) qs.set("horizon", String(horizon));
  const r = await fetch(`${BASE}/analysis/settlement-points?${qs.toString()}`, { signal });
  if (!r.ok) throw new Error(`analysis/settlement-points ${r.status}`);
  return r.json();
}

export async function fetchAnalysisEsspGroups(
  intervalTs: string,
  source: EsspSource = "study",
  signal?: AbortSignal,
): Promise<AnalysisEsspGroupsResponse> {
  const qs = new URLSearchParams({ interval_ts: intervalTs, source });
  const r = await fetch(`${BASE}/analysis/essp?${qs.toString()}`, { signal });
  if (!r.ok) throw new Error(`analysis/essp ${r.status}`);
  return r.json();
}
