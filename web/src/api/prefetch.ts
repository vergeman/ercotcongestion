import type {
  ErcotSppRangeEntry,
  ErcotRangeResponse,
  ErcotStateRangeEntry,
  ForecastRangeEntry,
  ForecastRangeResponse,
} from "./types";
import {
  fetchErcotRange,
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

// Decode the compact wire shape exactly once at the API boundary. Rendering and
// cache lookups keep their simple object-based shape, while the network avoids
// repeating every settlement-point ID in every hour and in both realized feeds.
function ingestErcotRange(data: ErcotRangeResponse | null): void {
  if (!data) return;
  for (const entry of data.entries) {
    const stateEntry: ErcotStateRangeEntry = {
      interval_ts: entry.interval_ts,
      sps: data.sp_ids.map((sp_id, index) => ({
        sp_id,
        congestion: entry.congestion[index] ?? null,
      })),
    };
    const sppEntry: ErcotSppRangeEntry = {
      interval_ts: entry.interval_ts,
      total_load_mw: entry.total_load_mw,
      sps: data.sp_ids.map((sp_id, index) => ({
        sp_id,
        spp: entry.spp[index] ?? null,
      })),
    };
    const ts = normalizeInterval(entry.interval_ts);
    const key = cacheKey(ts);
    if (!ercotCache.has(key)) ercotCache.set(key, stateEntry);
    ercotSppCache.set(key, sppEntry);
  }
}

function ingestForecast(data: ForecastRangeResponse | null): void {
  if (!data) return;
  forecastRunId = data.run_id;
  for (const entry of data.entries) {
    const ts = roundToInterval(new Date(entry.interval_ts));
    forecastCache.set(cacheKey(ts), entry);
  }
}

// Load a window into the caches. With an explicit [start, end] (a history scrub)
// the compact realized range and forecast fetch in parallel. With no window — the default landing view —
// the forecast leads: fetch the current run's latest operating day first, then
// the realized ranges for the span its response reports, so the prediction pane
// defines the day and realized is fetched to match. Returns the resolved window
// for cursor placement, or null when there's nothing to show (no explicit window
// and no forecast published).
export async function prefetchWindow(
  start?: Date,
  end?: Date
): Promise<{ start: Date; end: Date } | null> {
  // Replace, don't accumulate: the caches are module-level and back the union
  // in getAvailableTimestamps(), so a stale prior window would otherwise linger
  // on the timeline (and leave the cursor stranded on an old frame). Clear first
  // on every load — explicit window or default landing.
  clearCache();
  if (start && end) {
    const [ercotData, forecastData] = await Promise.all([
      fetchErcotRange(start, end),
      fetchForecastRange(start, end),
    ]);
    ingestErcotRange(ercotData);
    ingestForecast(forecastData);
    return { start, end };
  }

  const forecastData = await fetchForecastRange();
  if (!forecastData) return null;
  const winStart = new Date(forecastData.start);
  const winEnd = new Date(forecastData.end);
  const ercotData = await fetchErcotRange(winStart, winEnd);
  ingestErcotRange(ercotData);
  ingestForecast(forecastData);
  return { start: winStart, end: winEnd };
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
