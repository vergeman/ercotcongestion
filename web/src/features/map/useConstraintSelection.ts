import { useMemo } from "react";
import {
  fetchMapConstraintsRanked,
  fetchMapExposures,
  fetchMapReach,
  REACH_THRESHOLD_OPTS,
} from "../../api/client";
import type { ExposureRank } from "../../api/types";

/**
 * The map feature's request boundary for constraint ranking, reach, and node
 * drivers. Interaction state stays with its caller; transport details do not.
 */
export function useConstraintSelection() {
  return useMemo(() => ({
    loadRanked: fetchMapConstraintsRanked,
    loadExposures: (spId: string, rank: ExposureRank, cursorTs?: Date) =>
      fetchMapExposures(spId, 15, cursorTs, rank),
    loadReach: (constraintKey: string, cursorTs?: Date) =>
      fetchMapReach(constraintKey, { t: cursorTs, ...REACH_THRESHOLD_OPTS }),
  }), []);
}
