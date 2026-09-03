import { useMemo } from "react";
import {
  fetchMapConstraintsRanked,
  fetchMapExposures,
  fetchMapReach,
  REACH_THRESHOLD_OPTS,
} from "../../api/client";

/**
 * The map feature's request boundary for constraint ranking, reach, and node
 * drivers. Interaction state stays with its caller; transport details do not.
 */
export function useConstraintSelection() {
  return useMemo(() => ({
    loadRanked: fetchMapConstraintsRanked,
    // The node card is always the contribution ranking — what drove the node
    // this hour.
    loadExposures: (spId: string, cursorTs?: Date) =>
      fetchMapExposures(spId, 15, cursorTs, "contribution"),
    loadReach: (constraintKey: string, cursorTs?: Date) =>
      fetchMapReach(constraintKey, { t: cursorTs, ...REACH_THRESHOLD_OPTS }),
  }), []);
}
