import type {
  StateResponse,
  StateRangeResponse,
  ScorecardResponse,
  PtdfResponse,
  ErcotStateRangeResponse,
  ErcotSppRangeResponse,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
console.log("META", import.meta);
export async function fetchTopology(): Promise<unknown> {
  const r = await fetch(`${BASE}/topology`);
  if (!r.ok) throw new Error(`topology ${r.status}`);
  return r.json();
}

export async function fetchState(ts: Date): Promise<StateResponse> {
  const r = await fetch(`${BASE}/state?t=${ts.toISOString()}`);
  if (!r.ok) throw new Error(`state ${r.status}`);
  return r.json();
}

export async function fetchStateRange(
  start: Date,
  end: Date
): Promise<StateRangeResponse> {
  const r = await fetch(
    `${BASE}/state_range?start=${start.toISOString()}&end=${end.toISOString()}`
  );
  if (!r.ok) throw new Error(`state_range ${r.status}`);
  return r.json();
}

// ERCOT SP snapshots for the same window (S3.4). Returns `null` — not
// throws — when the backend reports the ERCOT artifact isn't built (503),
// so the caller can render the model side unaffected.
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

// Raw DAM SPP per settlement point over the window. Same soft-fail
// contract as ercot_state_range: 503 returns null so the model side
// still renders.
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

export async function fetchScorecard(
  runId: string,
  algo = "hierarchical_on_beta",
  k = 6
): Promise<ScorecardResponse> {
  const r = await fetch(
    `${BASE}/validation?run_id=${encodeURIComponent(runId)}` +
      `&algo=${encodeURIComponent(algo)}&k=${k}`
  );
  if (!r.ok) throw new Error(`validation ${r.status}`);
  return r.json();
}

// Module-level cache. PTDF columns are topology-static, so once fetched
// they're good for the session.
const ptdfCache = new Map<string, PtdfResponse>();
const ptdfInflight = new Map<string, Promise<PtdfResponse>>();

export async function fetchPtdf(lineId: string): Promise<PtdfResponse> {
  const cached = ptdfCache.get(lineId);
  if (cached) return cached;
  const inflight = ptdfInflight.get(lineId);
  if (inflight) return inflight;

  const promise = (async () => {
    const r = await fetch(`${BASE}/ptdf?line_id=${encodeURIComponent(lineId)}`);
    if (!r.ok) throw new Error(`ptdf ${r.status}`);
    const data: PtdfResponse = await r.json();
    ptdfCache.set(lineId, data);
    ptdfInflight.delete(lineId);
    return data;
  })();
  ptdfInflight.set(lineId, promise);
  return promise;
}
