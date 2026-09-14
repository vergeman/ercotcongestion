// Compatibility facade. New code should import the owning feature client.
export {
  fetchTopology,
  fetchErcotRange,
  fetchForecastRange,
  fetchConditionsRange,
} from "./explorer";
export {
  fetchMapSummary,
  fetchMapExposures,
  fetchMapReach,
  fetchMapConstraintsRanked,
  REACH_THRESHOLD_OPTS,
} from "./map";
export type { MapReachOptions } from "./map";
export {
  fetchMatrixFrame,
  fetchAnalysisNode,
  fetchAnalysisSettlementPoints,
  fetchAnalysisConstraints,
} from "./matrix";
export type { MatrixFrameRequest, AnalysisAttributionRequest } from "./matrix";
export {
  fetchBriefHeroLatest,
  fetchBriefHeroShell,
  fetchBriefStandouts,
  fetchBriefDetails,
} from "./brief";
export { fetchScoreboardSummary } from "./scoreboard";
