import type {
  ErcotSppRangeEntry,
  ErcotStateRangeEntry,
  ForecastRangeEntry,
} from "./types";
import {
  fetchErcotSppRange,
  fetchErcotStateRange,
  fetchForecastRange,
} from "./client";

const ercotCache = new Map<string, ErcotStateRangeEntry>();
const ercotSppCache = new Map<string, ErcotSppRangeEntry>();
// Forecast (prediction) side — per-hour P10/P50/P90 + system-λ for the current
// forecast run. Aligned to the same interval keys as the realized caches so the
// left pane reads it hour for hour off the scrubber.
const forecastCache = new Map<string, ForecastRangeEntry>();
// The forecast run_id served for the loaded window — labels which refit the
// prediction pane is showing. `null` until a window with a forecast loads.
let forecastRunId: string | null = null;

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

// Forecast (prediction) side. Same soft-fail contract: `undefined` when the
// current run has no forecast for this hour (503 or an unrequested interval).
export function getForecastCached(ts: Date): ForecastRangeEntry | undefined {
  return forecastCache.get(cacheKey(roundToInterval(ts)));
}

// The forecast run_id served for the loaded window, or `null` when no forecast
// covered it (the prediction pane falls back to the realized rows).
export function getForecastRunId(): string | null {
  return forecastRunId;
}

export async function prefetchWindow(start: Date, end: Date): Promise<void> {
  const [ercotData, ercotSppData, forecastData] = await Promise.all([
    fetchErcotStateRange(start, end),
    fetchErcotSppRange(start, end),
    fetchForecastRange(start, end),
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
  if (forecastData) {
    forecastRunId = forecastData.run_id;
    for (const entry of forecastData.entries) {
      const ts = roundToInterval(new Date(entry.interval_ts));
      forecastCache.set(cacheKey(ts), entry);
    }
  }
}

// Timeline axis is the union of the ERCOT and forecast caches' hours — any side
// may have coverage the others lack (a forecast-only delivery day has no
// realized rows yet), and an SP that appears in only one still belongs on the
// scrubber.
export function getAvailableTimestamps(): Date[] {
  const keys = new Set<string>([
    ...ercotCache.keys(),
    ...ercotSppCache.keys(),
    ...forecastCache.keys(),
  ]);
  return Array.from(keys)
    .map((k) => new Date(k))
    .sort((a, b) => a.getTime() - b.getTime());
}

export function clearCache(): void {
  ercotCache.clear();
  ercotSppCache.clear();
  forecastCache.clear();
  forecastRunId = null;
}
