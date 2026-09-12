import { useCallback, useEffect, useMemo, useState } from "react";
import type { MapDataMode } from "../api/types";
import {
  getAvailableTimestamps,
  getErcotCached,
  getErcotSppCached,
  getForecastCached,
  getForecastRunId,
  prefetchWindow,
} from "../api/prefetch";
import {
  computeCongestionStats,
  computeLmpStats,
} from "../lib/colors";
import type { CuratedEvent } from "../lib/events";
import type { SparkPoint } from "../components/playback/TimelineSparkline";

export type ConnectionState = "ok" | "error" | "loading";

/** State shared by every live explorer workspace, independent of its rendering. */
export function useExplorerSession(opts?: {
  initialCursor?: Date | null;
  initialWindow?: { start: Date; end: Date } | null;
}) {
  const [timestamps, setTimestamps] = useState<Date[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [sparkSeries, setSparkSeries] = useState<SparkPoint[]>([]);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  const [forecastRunId, setForecastRunId] = useState<string | null>(null);

  const loadWindow = useCallback(async (start?: Date, end?: Date, cursorTs?: Date) => {
    setLoading(true);
    setConnectionState("loading");
    try {
      await prefetchWindow(start, end);
      const nextTimestamps = getAvailableTimestamps();
      setTimestamps(nextTimestamps);
      if (!nextTimestamps.length) {
        setConnectionState("error");
        return;
      }

      setForecastRunId(getForecastRunId());
      setSparkSeries(nextTimestamps.map((timestamp) => {
        const market = getErcotCached(timestamp);
        const forecast = getForecastCached(timestamp);
        const absoluteTotal = (values: Array<number | null>): number | null => {
          let total = 0;
          let hasValue = false;
          for (const value of values) {
            if (value != null) {
              total += Math.abs(value);
              hasValue = true;
            }
          }
          return hasValue ? total : null;
        };
        return {
          forecast_congestion_abs_total: forecast
            ? absoluteTotal(forecast.sps.map((sp) => sp.forecast_congestion))
            : null,
          market_congestion_abs_total: market
            ? absoluteTotal(market.sps.map((sp) => sp.congestion))
            : null,
          system_lambda: market?.system_lambda ?? null,
        };
      }));
      if (cursorTs) {
        const target = cursorTs.getTime();
        const closest = nextTimestamps.reduce((best, timestamp, index) =>
          Math.abs(timestamp.getTime() - target) < Math.abs(nextTimestamps[best].getTime() - target) ? index : best, 0);
        setCurrentIndex(closest);
      } else {
        setCurrentIndex(0);
      }
      setLastUpdated(new Date());
      setConnectionState("ok");
    } catch {
      setConnectionState("error");
    } finally {
      setLoading(false);
    }
  }, []);

  const selectEvent = useCallback((event: CuratedEvent, onSuggestedData?: (dataMode: MapDataMode) => void) => {
    setActiveEventId(event.id);
    if (event.suggested_view) onSuggestedData?.(event.suggested_view);
    void loadWindow(new Date(event.window_start), new Date(event.window_end), new Date(event.cursor_ts));
  }, [loadWindow]);

  const loadCustomWindow = useCallback((start: Date, end: Date) => {
    setActiveEventId(null);
    void loadWindow(start, end);
  }, [loadWindow]);

  // Landing load, from the URL coordinate. Precedence:
  //  1. a stored window [ws, we] that *contains* the cursor (or when there is no
  //     cursor) → restore that exact range — the Map → Analysis → Map round-trip;
  //  2. a cursor only (or a stored window that no longer contains it, e.g. the
  //     hour moved on Analysis) → a ±1-day window around the cursor;
  //  3. nothing → the default window around now.
  // Runs once — loadWindow is stable and the coordinate is read at mount.
  const initialCursor = opts?.initialCursor ?? null;
  const initialWindow = opts?.initialWindow ?? null;
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const inWindow =
        initialWindow &&
        initialCursor &&
        initialCursor.getTime() >= initialWindow.start.getTime() &&
        initialCursor.getTime() <= initialWindow.end.getTime();
      if (initialWindow && (inWindow || !initialCursor)) {
        void loadWindow(initialWindow.start, initialWindow.end, initialCursor ?? undefined);
      } else if (initialCursor) {
        const pad = 24 * 60 * 60 * 1000; // ±1 day so the day and its neighbors load
        void loadWindow(
          new Date(initialCursor.getTime() - pad),
          new Date(initialCursor.getTime() + pad),
          initialCursor
        );
      } else {
        void loadWindow(undefined, undefined, new Date());
      }
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadWindow]);

  // Stats describe the loaded playback range for the cropped legend only.
  // Fixed dollar transforms own map colors.
  const dayStats = useMemo(() => {
    if (!timestamps.length) {
      return {
        congestionStats: null,
        sppStats: null,
        forecastCongestionStats: null,
        forecastLmpStats: null,
        errorStats: null,
      };
    }

    const actualCongestion: Array<number | null> = [];
    const actualLmp: Array<number | null> = [];
    const forecastCongestion: Array<number | null> = [];
    const forecastLmp: Array<number | null> = [];
    const forecastError: Array<number | null> = [];

    for (const timestamp of timestamps) {

      const congestion = getErcotCached(timestamp);
      if (congestion) for (const sp of congestion.sps) actualCongestion.push(sp.congestion);
      const spp = getErcotSppCached(timestamp);
      if (spp) for (const sp of spp.sps) actualLmp.push(sp.spp);
      const forecast = getForecastCached(timestamp);
      if (forecast) {
        for (const sp of forecast.sps) {
          forecastCongestion.push(sp.forecast_congestion);
          forecastLmp.push(
            sp.forecast_congestion != null && forecast.system_lambda != null
              ? sp.forecast_congestion + forecast.system_lambda
              : null
          );
        }
      }
      if (congestion && forecast) {
        const marketById = new Map(congestion.sps.map((sp) => [sp.sp_id, sp.congestion]));
        for (const sp of forecast.sps) {
          const market = marketById.get(sp.sp_id);
          if (sp.forecast_congestion != null && market != null) forecastError.push(sp.forecast_congestion - market);
        }
      }
    }

    return {
      congestionStats: actualCongestion.length ? computeCongestionStats(actualCongestion) : null,
      sppStats: actualLmp.length ? computeLmpStats(actualLmp) : null,
      forecastCongestionStats: forecastCongestion.length
        ? computeCongestionStats(forecastCongestion)
        : null,
      forecastLmpStats: forecastLmp.length ? computeLmpStats(forecastLmp) : null,
      errorStats: forecastError.length ? computeCongestionStats(forecastError) : null,
    };
  }, [timestamps]);

  return {
    timestamps, currentIndex, setCurrentIndex, loading, connectionState, setConnectionState,
    lastUpdated, sparkSeries, activeEventId, ...dayStats, forecastRunId,
    selectEvent, loadCustomWindow,
  };
}
