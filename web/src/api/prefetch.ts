import type {
  ErcotStateRangeEntry,
  StateRangeEntry,
  StateRangeResponse,
} from "./types";
import { fetchErcotStateRange, fetchStateRange } from "./client";

const cache = new Map<string, StateRangeEntry>();
const ercotCache = new Map<string, ErcotStateRangeEntry>();

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

// S3.4 — same-cadence cache for the ERCOT side. `undefined` means either
// the ERCOT artifact is missing (backend 503) or this hour wasn't in the
// requested window. Consumers should render the model side regardless.
export function getErcotCached(ts: Date): ErcotStateRangeEntry | undefined {
  return ercotCache.get(cacheKey(roundToInterval(ts)));
}

export async function prefetchWindow(
  start: Date,
  end: Date
): Promise<StateRangeResponse> {
  const [modelData, ercotData] = await Promise.all([
    fetchStateRange(start, end),
    fetchErcotStateRange(start, end),
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
}
