import { useEffect, useState } from "react";
import type { MapScorecard } from "../../api/types";
import { fetchMapScorecard } from "../../api/map";

/**
 * The cursor's CT delivery-day scorecard. The previous request is aborted so a
 * fast scrub can't publish an earlier day's score, and the prior scorecard stays
 * mounted until the new one lands, so numbers swap in place with no flash.
 */
export function useMapScorecard(
  deliveryDay: string | undefined,
  forecastRunId: string | null
): MapScorecard | null {
  const [scorecard, setScorecard] = useState<MapScorecard | null>(null);

  useEffect(() => {
    if (!deliveryDay) {
      return;
    }
    const controller = new AbortController();
    fetchMapScorecard(deliveryDay, forecastRunId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setScorecard(result);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !(error instanceof DOMException && error.name === "AbortError")) setScorecard(null);
      });
    return () => controller.abort();
  }, [deliveryDay, forecastRunId]);

  return scorecard;
}
