import type {
  ErcotSppRangeEntry,
  ErcotStateRangeEntry,
} from "./types";
import { fetchErcotSppRange, fetchErcotStateRange } from "./client";

const ercotCache = new Map<string, ErcotStateRangeEntry>();
const ercotSppCache = new Map<string, ErcotSppRangeEntry>();

function cacheKey(ts: Date): string {
  return ts.toISOString();
}

function roundToInterval(ts: Date, intervalMs = 15 * 60 * 1000): Date {
  return new Date(Math.round(ts.getTime() / intervalMs) * intervalMs);
}

// Backend hours arrive as either plain ISO or scenario-labeled
// ``<label>|<iso>`` (see ercot congestion matrices). Strip the label so the
// cache key stays aligned across the two ERCOT sides.
function normalizeInterval(raw: string): Date {
  const iso = raw.includes("|") ? raw.split("|", 2)[1] : raw;
  return roundToInterval(new Date(iso));
}

// ERCOT congestion (SPP − system_λ) side. `undefined` means either the
// backend has no artifact for this window (503) or this hour wasn't requested.
export function getErcotCached(ts: Date): ErcotStateRangeEntry | undefined {
  return ercotCache.get(cacheKey(roundToInterval(ts)));
}

// Raw DAM SPP side. Same soft-fail contract as `getErcotCached`.
export function getErcotSppCached(ts: Date): ErcotSppRangeEntry | undefined {
  return ercotSppCache.get(cacheKey(roundToInterval(ts)));
}

export async function prefetchWindow(start: Date, end: Date): Promise<void> {
  const [ercotData, ercotSppData] = await Promise.all([
    fetchErcotStateRange(start, end),
    fetchErcotSppRange(start, end),
  ]);
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
}

// Timeline axis is the union of the two ERCOT caches' hours — either side may
// have coverage the other lacks, and an SP that appears in only one still
// belongs on the scrubber.
export function getAvailableTimestamps(): Date[] {
  const keys = new Set<string>([...ercotCache.keys(), ...ercotSppCache.keys()]);
  return Array.from(keys)
    .map((k) => new Date(k))
    .sort((a, b) => a.getTime() - b.getTime());
}

export function clearCache(): void {
  ercotCache.clear();
  ercotSppCache.clear();
}
