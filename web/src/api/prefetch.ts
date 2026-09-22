import type {
  ErcotRangeResponse,
  ForecastRangeResponse,
  ForecastStateEntry,
  ConditionsEntry,
  ConditionsRangeResponse,
} from "./types";
import {
  fetchErcotRange,
  fetchForecastRange,
  fetchConditionsRange,
} from "./client";
import { deliveryDateCT } from "../lib/time";

interface ErcotCongestionEntry {
  interval_ts: string;
  system_lambda: number | null;
  sps: Array<{ sp_id: string; congestion: number | null }>;
}

interface ErcotSppEntry {
  interval_ts: string;
  sps: Array<{ sp_id: string; spp: number | null }>;
}

const ercotCache = new Map<string, ErcotCongestionEntry>();
const ercotSppCache = new Map<string, ErcotSppEntry>();
const forecastCache = new Map<string, ForecastStateEntry>();
// Supplemental ERCOT load, wind, solar, and outage data for the Stats tab.
const conditionsCache = new Map<string, ConditionsEntry>();
let forecastRunId: string | null = null;
let forecastHorizons: Record<string, number> = {};
let activeRequest: AbortController | null = null;

function cacheKey(ts: Date): string {
  return ts.toISOString();
}

function roundToInterval(ts: Date, intervalMs = 15 * 60 * 1000): Date {
  return new Date(Math.round(ts.getTime() / intervalMs) * intervalMs);
}

// Strip optional scenario labels from backend timestamps.
function normalizeInterval(raw: string): Date {
  const iso = raw.includes("|") ? raw.split("|", 2)[1] : raw;
  return roundToInterval(new Date(iso));
}

export function getErcotCached(ts: Date): ErcotCongestionEntry | undefined {
  return ercotCache.get(cacheKey(roundToInterval(ts)));
}

export function getErcotSppCached(ts: Date): ErcotSppEntry | undefined {
  return ercotSppCache.get(cacheKey(roundToInterval(ts)));
}

export function getForecastCached(ts: Date): ForecastStateEntry | undefined {
  return forecastCache.get(cacheKey(roundToInterval(ts)));
}

export function getConditionsCached(ts: Date): ConditionsEntry | undefined {
  return conditionsCache.get(cacheKey(roundToInterval(ts)));
}

export function getForecastRunId(): string | null {
  return forecastRunId;
}

export function getForecastHorizon(ts: Date): number | null {
  const key = deliveryDateCT(ts);
  return forecastHorizons[key] ?? null;
}

// Expand compact ERCOT rows at the API boundary.
function ingestErcotRange(data: ErcotRangeResponse | null): void {
  if (!data) return;
  for (const entry of data.entries) {
    const stateEntry: ErcotCongestionEntry = {
      interval_ts: entry.interval_ts,
      system_lambda: entry.system_lambda,
      sps: data.sp_ids.map((sp_id, index) => ({
        sp_id,
        congestion: entry.congestion[index] ?? null,
      })),
    };
    const sppEntry: ErcotSppEntry = {
      interval_ts: entry.interval_ts,
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
  forecastHorizons = data.horizons ?? {};
  for (const entry of data.entries) {
    const stateEntry: ForecastStateEntry = {
      interval_ts: entry.interval_ts,
      system_lambda: entry.system_lambda,
      lambda_source: entry.lambda_source,
      sps: data.sp_ids.map((sp_id, index) => ({
        sp_id,
        forecast_congestion: entry.congestion[index] ?? null,
      })),
    };
    const ts = roundToInterval(new Date(entry.interval_ts));
    forecastCache.set(cacheKey(ts), stateEntry);
  }
}

function ingestConditionsRange(data: ConditionsRangeResponse | null): void {
  if (!data) return;
  for (const entry of data.entries) {
    const ts = roundToInterval(new Date(entry.interval_ts));
    conditionsCache.set(cacheKey(ts), entry);
  }
}

// Load a window into the shared playback caches.
export async function prefetchWindow(
  start?: Date,
  end?: Date,
): Promise<{ start: Date; end: Date } | null> {
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  const isCurrent = () => activeRequest === controller;
  clearCache();
  if (start && end) {
    const [ercotData, forecastData, conditionsData] = await Promise.all([
      fetchErcotRange(start, end, controller.signal),
      fetchForecastRange(start, end, controller.signal),
      fetchConditionsRange(start, end, controller.signal),
    ]);
    if (!isCurrent()) return null;
    ingestErcotRange(ercotData);
    ingestForecast(forecastData);
    ingestConditionsRange(conditionsData);
    return { start, end };
  }

  const forecastData = await fetchForecastRange(undefined, undefined, controller.signal);
  if (!forecastData) return null;
  const winStart = new Date(forecastData.start);
  const winEnd = new Date(forecastData.end);
  const [ercotData, conditionsData] = await Promise.all([
    fetchErcotRange(winStart, winEnd, controller.signal),
    fetchConditionsRange(winStart, winEnd, controller.signal),
  ]);
  if (!isCurrent()) return null;
  ingestErcotRange(ercotData);
  ingestForecast(forecastData);
  ingestConditionsRange(conditionsData);
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
  conditionsCache.clear();
  forecastRunId = null;
  forecastHorizons = {};
}
