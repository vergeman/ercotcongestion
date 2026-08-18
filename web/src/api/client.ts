import type {
  ErcotStateRangeResponse,
  ErcotSppRangeResponse,
  ErcotRangeResponse,
  ForecastRangeResponse,
  ExposuresResponse,
  ConstraintReach,
  MapSummary,
  RankedConstraints,
  ScoreboardSummary,
  MatrixFrame,
  BriefHeroLatest,
  BriefDay,
  AnalysisBasis,
  AnalysisNodeResponse,
  AnalysisSettlementPointsResponse,
  AnalysisConstraintsResponse,
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

// One bundled payload for the Map workspace's load-time requests (0137) —
// replaces the topology + overview + meta + headline fan-out with a single
// request. Each
// field keeps its prior section shape; overview/meta/headline are null
// exactly when that section's own endpoint would 503 (nothing built/loaded
// for it yet). Interaction endpoints (map/reach, map/exposures,
// map/constraints/ranked) are untouched — they fire on hover/click/
// navigation, not load, so they stay their own calls.
export async function fetchMapSummary(): Promise<MapSummary> {
  const r = await fetch(`${BASE}/map/summary`);
  if (!r.ok) throw new Error(`map/summary ${r.status}`);
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

export interface MapReachOptions {
  k?: number;
  minFrac?: number;
  // 0139/0001: drops the row LIMIT entirely (bounded only by minFrac) — the
  // matrix Read pane's "give me everything" call, as opposed to `k`'s
  // display-oriented top-k (map click, brief).
  full?: boolean;
}

// Top-k (or, with `full: true`, the complete) nodes a constraint drives, by
// |sf| — the constraint click. Signed `sf` carries the import/export dipole.
// Null on 503.
export async function fetchMapReach(
  constraint: string,
  { k = 15, minFrac, full }: MapReachOptions = {}
): Promise<ConstraintReach | null> {
  const qs = new URLSearchParams({ constraint });
  if (full) qs.set("full", "true");
  else qs.set("k", String(k));
  if (minFrac != null) qs.set("min_frac", String(minFrac));
  const r = await fetch(`${BASE}/map/reach?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/reach ${r.status}`);
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

// One bundled payload for the Scoreboard page's load-time requests (0137) —
// replaces the
// weekly + headline + daily fan-out with a single request. Each field keeps
// its prior section shape; null exactly when that section's own endpoint
// would 503 (that board has no rows yet), so the page can still render the
// sections that do have data. `source`/`since` are fixed server-side to match
// what the Scoreboard page always requested (`model`, full history) — only
// `regime` varies from the client.
export async function fetchScoreboardSummary(
  regime = "all"
): Promise<ScoreboardSummary | null> {
  const r = await fetch(
    `${BASE}/scoreboard/summary?regime=${encodeURIComponent(regime)}`
  );
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`scoreboard/summary ${r.status}`);
  return r.json();
}

// V6 cold-entry discovery selects only days with both UTC artifacts required
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

// One bundled payload for a Brief delivery day (0137) — replaces the
// hero/context/standouts/top-nodes/top-constraints/grade/grade-history
// fan-out with a single request. Each field keeps its prior section shape.
export async function fetchBriefDay(
  deliveryDate: string,
  runId?: string,
): Promise<BriefDay | null> {
  const qs = new URLSearchParams({ day: deliveryDate });
  if (runId) qs.set("run", runId);
  const r = await fetch(`${BASE}/analysis/brief?${qs.toString()}`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`analysis/brief ${r.status}`);
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

// The full constraint vocabulary for one day's artifact (plan/0139-0001) —
// the Matrix sidebar's search index, not a Brief top-k.
export async function fetchAnalysisConstraints(
  deliveryDate: string,
  { runId, horizon, signal }: Pick<AnalysisAttributionRequest, "runId" | "horizon" | "signal"> = {},
): Promise<AnalysisConstraintsResponse> {
  const qs = new URLSearchParams({ delivery_date: deliveryDate });
  if (runId) qs.set("run_id", runId);
  if (horizon != null) qs.set("horizon", String(horizon));
  const r = await fetch(`${BASE}/analysis/constraints?${qs.toString()}`, { signal });
  if (!r.ok) throw new Error(`analysis/constraints ${r.status}`);
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
