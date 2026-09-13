import { useMemo } from "react";
import {
  fetchMapConstraintsRanked,
  fetchMapExposures,
  fetchMapReach,
  REACH_THRESHOLD_OPTS,
} from "../../api/client";

/** Constraint requests used by map interactions. */
export function useConstraintSelection() {
  return useMemo(() => ({
    loadRanked: fetchMapConstraintsRanked,
    loadExposures: (spId: string, cursorTs?: Date) =>
      fetchMapExposures(spId, 15, cursorTs, "contribution"),
    loadReach: (constraintKey: string, cursorTs?: Date) =>
      fetchMapReach(constraintKey, { t: cursorTs, ...REACH_THRESHOLD_OPTS }),
  }), []);
}
