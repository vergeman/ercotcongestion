import type { StateRangeEntry, StateRangeResponse } from './types';
import { fetchStateRange } from './client';

const PREFETCH_HOURS = 6;
const cache = new Map<string, StateRangeEntry>();

function cacheKey(ts: Date): string {
  return ts.toISOString();
}

function roundToInterval(ts: Date, intervalMs = 15 * 60 * 1000): Date {
  return new Date(Math.round(ts.getTime() / intervalMs) * intervalMs);
}

export function getCached(ts: Date): StateRangeEntry | undefined {
  return cache.get(cacheKey(roundToInterval(ts)));
}

export async function prefetchWindow(center: Date): Promise<StateRangeResponse> {
  const start = new Date(center.getTime() - PREFETCH_HOURS * 3600 * 1000);
  const end = new Date(center.getTime() + PREFETCH_HOURS * 3600 * 1000);

  const data = await fetchStateRange(start, end);
  for (const entry of data.entries) {
    const ts = roundToInterval(new Date(entry.interval_ts));
    cache.set(cacheKey(ts), entry);
  }
  return data;
}

export function getAvailableTimestamps(): Date[] {
  return Array.from(cache.keys())
    .map((k) => new Date(k))
    .sort((a, b) => a.getTime() - b.getTime());
}

export function clearCache(): void {
  cache.clear();
}
