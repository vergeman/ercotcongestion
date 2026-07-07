import type {
  ErcotSppRangeEntry,
  ErcotStateRangeEntry,
  IbpErcotRangeEntry,
  StateRangeEntry,
  StateRangeResponse,
} from "./types";
import {
  fetchErcotSppRange,
  fetchErcotStateRange,
  fetchIbpErcotRange,
  fetchStateRange,
} from "./client";

const cache = new Map<string, StateRangeEntry>();
const ercotCache = new Map<string, ErcotStateRangeEntry>();
const ercotSppCache = new Map<string, ErcotSppRangeEntry>();
const ibpErcotCache = new Map<string, IbpErcotRangeEntry>();
let promotedIbpRunId: string | null = null;

function cacheKey(ts: Date): string {
  return ts.toISOString();
}

function roundToInterval(ts: Date, intervalMs = 15 * 60 * 1000): Date {
  return new Date(Math.round(ts.getTime() / intervalMs) * intervalMs);
}

// Backend hours arrive as either plain ISO or scenario-labeled
// ``<label>|<iso>`` (see ercot congestion matrices). Strip the label so
// the cache key stays aligned with the model side.
function normalizeInterval(raw: string): Date {
  const iso = raw.includes("|") ? raw.split("|", 2)[1] : raw;
  return roundToInterval(new Date(iso));
}

export function getCached(ts: Date): StateRangeEntry | undefined {
  return cache.get(cacheKey(roundToInterval(ts)));
}

// ERCOT congestion (SPP − system_λ) side. `undefined` means either the
// backend has no artifact for this window (503) or this hour wasn't
// requested. Consumers must fall back to rendering the model side alone.
export function getErcotCached(ts: Date): ErcotStateRangeEntry | undefined {
  return ercotCache.get(cacheKey(roundToInterval(ts)));
}

// Raw DAM SPP side. Same soft-fail contract as `getErcotCached`.
export function getErcotSppCached(ts: Date): ErcotSppRangeEntry | undefined {
  return ercotSppCache.get(cacheKey(roundToInterval(ts)));
}

// Promoted bp_ercot panel per hour. Same soft-fail contract; `undefined`
// means no BP entry for this hour (either the promoted run had nothing to
// say, or no run is promoted at all — check `getIbpPromotedRunId()` to
// disambiguate).
export function getIbpErcotCached(ts: Date): IbpErcotRangeEntry | undefined {
  return ibpErcotCache.get(cacheKey(roundToInterval(ts)));
}

// `null` when no bp_ercot run has been promoted for the last window we
// prefetched. Right-pane badge reads from this to show which run painted
// the map, and the App uses null vs. non-null to pick the empty pane vs.
// the topology pane.
export function getIbpPromotedRunId(): string | null {
  return promotedIbpRunId;
}

export async function prefetchWindow(
  start: Date,
  end: Date
): Promise<StateRangeResponse> {
  const [modelData, ercotData, ercotSppData, ibpErcotData] = await Promise.all([
    fetchStateRange(start, end),
    fetchErcotStateRange(start, end),
    fetchErcotSppRange(start, end),
    fetchIbpErcotRange(start, end),
  ]);
  for (const entry of modelData.entries) {
    const ts = roundToInterval(new Date(entry.interval_ts));
    cache.set(cacheKey(ts), entry);
  }
  if (ercotData) {
    for (const entry of ercotData.entries) {
      const ts = normalizeInterval(entry.interval_ts);
      // Multiple scenario-labeled hours can collapse to the same wall-clock
      // interval; first write wins so we don't oscillate between scenarios.
      const key = cacheKey(ts);
      if (!ercotCache.has(key)) ercotCache.set(key, entry);
    }
  }
  if (ercotSppData) {
    for (const entry of ercotSppData.entries) {
      const ts = roundToInterval(new Date(entry.interval_ts));
      ercotSppCache.set(cacheKey(ts), entry);
    }
  }
  if (ibpErcotData) {
    promotedIbpRunId = ibpErcotData.run_id;
    for (const entry of ibpErcotData.entries) {
      const ts = roundToInterval(new Date(entry.interval_ts));
      const key = cacheKey(ts);
      if (!ibpErcotCache.has(key)) ibpErcotCache.set(key, entry);
    }
  } else {
    promotedIbpRunId = null;
  }
  return modelData;
}

export function getAvailableTimestamps(): Date[] {
  return Array.from(cache.keys())
    .map((k) => new Date(k))
    .sort((a, b) => a.getTime() - b.getTime());
}

export function clearCache(): void {
  cache.clear();
  ercotCache.clear();
  ercotSppCache.clear();
  ibpErcotCache.clear();
  promotedIbpRunId = null;
}
