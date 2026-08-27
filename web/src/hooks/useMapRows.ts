import { useMemo } from "react";
import type { SpRow } from "../api/types";
import { getErcotCached, getErcotSppCached, getForecastCached } from "../api/prefetch";

/** Derives the current map rows from the shared explorer's cached frame. */
export function useMapRows(timestamps: Date[], currentIndex: number) {
  return useMemo(() => {
    const timestamp = timestamps[currentIndex];
    if (!timestamp) return { spRows: [] as SpRow[], forecastRows: [] as SpRow[], lambdaSource: null as "settled" | "persisted" | null };
    const congestion = getErcotCached(timestamp);
    const spp = getErcotSppCached(timestamp);
    const rows = new Map<string, SpRow>();
    for (const row of congestion?.sps ?? []) rows.set(row.sp_id, { sp_id: row.sp_id, congestion: row.congestion, spp: null });
    for (const row of spp?.sps ?? []) {
      const current = rows.get(row.sp_id);
      if (current) current.spp = row.spp;
      else rows.set(row.sp_id, { sp_id: row.sp_id, congestion: null, spp: row.spp });
    }
    const forecast = getForecastCached(timestamp);
    const forecastRows = forecast?.sps.map((row) => ({
      sp_id: row.sp_id, congestion: row.forecast_congestion,
      spp: row.forecast_congestion != null && forecast.system_lambda != null ? row.forecast_congestion + forecast.system_lambda : null,
    })) ?? [];
    return { spRows: [...rows.values()], forecastRows, lambdaSource: forecast?.lambda_source ?? null };
  }, [timestamps, currentIndex]);
}
