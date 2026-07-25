import type {
  ErcotStateRangeResponse,
  ErcotSppRangeResponse,
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
// the current run's latest operating day, and the response's start/end define the
// window the realized ranges are then fetched to match. Same soft-fail contract:
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
