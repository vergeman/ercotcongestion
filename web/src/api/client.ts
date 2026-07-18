import type {
  ErcotStateRangeResponse,
  ErcotSppRangeResponse,
  ForecastRangeResponse,
  MapMeta,
  ConstraintGeo,
  ExposuresResponse,
  ConstraintReach,
  MapOverview,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchTopology(): Promise<unknown> {
  const r = await fetch(`${BASE}/topology`);
  if (!r.ok) throw new Error(`topology ${r.status}`);
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

// Every constraint's centroid for the current refit — the overlay layer.
// Null on 503.
export async function fetchMapConstraints(): Promise<ConstraintGeo[] | null> {
  const r = await fetch(`${BASE}/map/constraints`);
  if (r.status === 503) return null;
  if (!r.ok) throw new Error(`map/constraints ${r.status}`);
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
