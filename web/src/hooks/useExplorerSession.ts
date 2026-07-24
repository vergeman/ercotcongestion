import { useCallback, useEffect, useState } from "react";
import type { Palette } from "../api/types";
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
  type CongestionStats,
  type LmpStats,
} from "../lib/colors";
import type { CuratedEvent } from "../lib/events";
import type { SparkPoint } from "../components/playback/TimelineSparkline";

export type ConnectionState = "ok" | "error" | "loading";

/** State shared by every live explorer workspace, independent of its rendering. */
export function useExplorerSession() {
  const [timestamps, setTimestamps] = useState<Date[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [sparkSeries, setSparkSeries] = useState<SparkPoint[]>([]);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  const [congestionStats, setCongestionStats] = useState<CongestionStats | null>(null);
  const [sppStats, setSppStats] = useState<LmpStats | null>(null);
  const [forecastCongestionStats, setForecastCongestionStats] = useState<CongestionStats | null>(null);
  const [forecastLmpStats, setForecastLmpStats] = useState<LmpStats | null>(null);
  const [errorStats, setErrorStats] = useState<CongestionStats | null>(null);
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

      const allCong: Array<number | null> = [];
      const allSpp: Array<number | null> = [];
      const allFcCong: Array<number | null> = [];
      const allFcLmp: Array<number | null> = [];
      const allError: Array<number | null> = [];
      for (const timestamp of nextTimestamps) {
        const congestion = getErcotCached(timestamp);
        if (congestion) for (const sp of congestion.sps) allCong.push(sp.congestion);
        const spp = getErcotSppCached(timestamp);
        if (spp) for (const sp of spp.sps) allSpp.push(sp.spp);
        const forecast = getForecastCached(timestamp);
        if (forecast) for (const sp of forecast.sps) {
          allFcCong.push(sp.p50);
          allFcLmp.push(sp.p50 != null && forecast.system_lambda != null ? sp.p50 + forecast.system_lambda : null);
        }
        if (congestion && forecast) {
          const marketById = new Map(congestion.sps.map((sp) => [sp.sp_id, sp.congestion]));
          for (const sp of forecast.sps) {
            const market = marketById.get(sp.sp_id);
            if (sp.p50 != null && market != null) allError.push(sp.p50 - market);
          }
        }
      }
      setCongestionStats(allCong.length ? computeCongestionStats(allCong) : null);
      setSppStats(allSpp.length ? computeLmpStats(allSpp) : null);
      setForecastCongestionStats(allFcCong.length ? computeCongestionStats(allFcCong) : null);
      setForecastLmpStats(allFcLmp.length ? computeLmpStats(allFcLmp) : null);
      setErrorStats(allError.length ? computeCongestionStats(allError) : null);
      setForecastRunId(getForecastRunId());
      setSparkSeries(nextTimestamps.map((timestamp) => {
        const congestion = getErcotCached(timestamp);
        let congestion_abs_total: number | null = null;
        if (congestion) {
          congestion_abs_total = 0;
          for (const sp of congestion.sps) if (sp.congestion != null) congestion_abs_total += Math.abs(sp.congestion);
        }
        return { congestion_abs_total };
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

  const selectEvent = useCallback((event: CuratedEvent, onSuggestedPalette?: (palette: Palette) => void) => {
    setActiveEventId(event.id);
    if (event.suggested_view) onSuggestedPalette?.(event.suggested_view);
    void loadWindow(new Date(event.window_start), new Date(event.window_end), new Date(event.cursor_ts));
  }, [loadWindow]);

  const loadCustomWindow = useCallback((start: Date, end: Date) => {
    setActiveEventId(null);
    void loadWindow(start, end);
  }, [loadWindow]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadWindow(undefined, undefined, new Date()), 0);
    return () => window.clearTimeout(timer);
  }, [loadWindow]);

  return {
    timestamps, currentIndex, setCurrentIndex, loading, connectionState, setConnectionState,
    lastUpdated, sparkSeries, activeEventId, congestionStats, sppStats,
    forecastCongestionStats, forecastLmpStats, errorStats, forecastRunId,
    selectEvent, loadCustomWindow,
  };
}
