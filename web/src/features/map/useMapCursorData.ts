import { useCallback, useMemo } from "react";
import type { SpRow, ConditionsEntry } from "../../api/types";
import { formatCT } from "../../lib/time";
import {
  getForecastCached,
  getForecastHorizon,
  getConditionsCached,
} from "../../api/prefetch";
import { useMapRows } from "./useMapRows";
import type { NetworkStats } from "../../components/panels/SidePanel";

/** One SP's forecast / realized / error decomposition, carried by every card. */
export interface SpDecomposition {
  predicted: number | null;
  market: number | null;
  error: number | null;
  marketSpp: number | null;
  predictedSpp: number | null;
}

export interface MapCursorData {
  /** The cursor instant — the `t` /map/exposures and /map/reach are scoped to. */
  cursorTs: Date | undefined;
  /** The cursor's CT delivery day — the day the Constraints tab ranks. */
  deliveryDay: string | undefined;
  /** Whether the cursor's forecast day is still a horizon-2 preview (0123). */
  isPreviewDay: boolean;
  spRows: SpRow[];
  forecastRows: SpRow[];
  lambdaSource: "settled" | "persisted" | null;
  errorRows: SpRow[];
  conditionsStats: ConditionsEntry | null;
  networkStats: NetworkStats;
  spDecomp: (spId: string) => SpDecomposition;
}

/**
 * Everything the map cursor derives for the panes and side panel: the CT day,
 * the current hour's rows, the forecast-error rows, conditions, network stats,
 * and the per-SP decomposition. All null/fallback semantics match what the panes
 * expect (forecast-only error rows, model ≥ ercot node counts).
 */
export function useMapCursorData(
  timestamps: Date[],
  currentIndex: number,
  forecastRunId: string | null
): MapCursorData {
  const deliveryDay = useMemo<string | undefined>(() => {
    const ts = timestamps[currentIndex];
    return ts ? formatCT(ts, "yyyy-MM-dd") : undefined;
  }, [timestamps, currentIndex]);

  const cursorTs = useMemo<Date | undefined>(
    () => timestamps[currentIndex],
    [timestamps, currentIndex]
  );

  // Read-only off the per-day provenance the range response carried; no toggle
  // and no extra fetch, so this only labels which days are still previews.
  const isPreviewDay = useMemo<boolean>(() => {
    const ts = timestamps[currentIndex];
    return ts ? getForecastHorizon(ts) === 2 : false;
  }, [timestamps, currentIndex]);

  const { spRows, forecastRows, lambdaSource } = useMapRows(timestamps, currentIndex);

  // Forecast − realized congestion per SP, derived client-side from the two
  // series already in state. An SP missing either value rides through with a
  // null error; empty when no forecast covers the hour.
  const errorRows = useMemo<SpRow[]>(() => {
    if (!forecastRows.length) return [];
    const marketById = new Map(spRows.map((r) => [r.sp_id, r.congestion]));
    return forecastRows.map((f) => {
      const m = marketById.get(f.sp_id);
      const error =
        f.congestion != null && m != null ? f.congestion - m : null;
      return { sp_id: f.sp_id, congestion: error, spp: null };
    });
  }, [forecastRows, spRows]);

  // Side-panel network stats from state already in hand. `systemLambda` is the
  // forecast entry's DAM system-λ at the cursor; `congestionAbsTotal` is Σ|C|
  // over this hour's realized rows. The model forecasts its full nodal universe
  // while ERCOT lights only priced nodes, so model ≥ ercot.
  const networkStats = useMemo<NetworkStats>(() => {
    const cur = timestamps[currentIndex] ?? null;
    const fc = cur ? getForecastCached(cur) : null;
    let absTotal: number | null = null;
    let ercot = 0;
    for (const r of spRows) {
      if (r.congestion != null) {
        ercot++;
        absTotal = (absTotal ?? 0) + Math.abs(r.congestion);
      }
    }
    let model = 0;
    for (const r of forecastRows) if (r.congestion != null) model++;
    return {
      forecastRunId,
      systemLambda: fc?.system_lambda ?? null,
      congestionAbsTotal: absTotal,
      modelNodes: model,
      ercotNodes: ercot,
    };
  }, [timestamps, currentIndex, spRows, forecastRows, forecastRunId]);

  // Load / Wind / Solar / Outages (0141), same cursor hour, from its own
  // soft-fail cache. A missing entry collapses to null so SidePanel dashes it.
  const conditionsStats = useMemo<ConditionsEntry | null>(() => {
    const cur = timestamps[currentIndex] ?? null;
    return (cur ? getConditionsCached(cur) : null) ?? null;
  }, [timestamps, currentIndex]);

  // Predicted from the forecast rows, market from the realized rows, error =
  // predicted − market when both exist. Side-independent.
  const spDecomp = useCallback(
    (spId: string): SpDecomposition => {
      const f = forecastRows.find((r) => r.sp_id === spId);
      const m = spRows.find((r) => r.sp_id === spId);
      const predicted = f?.congestion ?? null;
      const market = m?.congestion ?? null;
      const error =
        predicted != null && market != null ? predicted - market : null;
      return {
        predicted,
        market,
        error,
        marketSpp: m?.spp ?? null,
        predictedSpp: f?.spp ?? null,
      };
    },
    [forecastRows, spRows]
  );

  return {
    cursorTs,
    deliveryDay,
    isPreviewDay,
    spRows,
    forecastRows,
    lambdaSource,
    errorRows,
    conditionsStats,
    networkStats,
    spDecomp,
  };
}
