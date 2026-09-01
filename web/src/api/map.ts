import { requestJson, requestRequiredJson } from "./http";
import type {
  ConstraintReach,
  ExposureRank,
  ExposuresResponse,
  MapSummary,
  MapScorecard,
  RankedConstraints,
} from "./types";

export interface MapReachOptions {
  k?: number;
  minFrac?: number;
  absFloor?: number;
  t?: Date;
  full?: boolean;
  signal?: AbortSignal;
}

export const REACH_THRESHOLD_OPTS: MapReachOptions = {
  full: true,
  minFrac: 0.15,
  absFloor: 0.03,
};

export function fetchMapSummary(signal?: AbortSignal): Promise<MapSummary> {
  return requestRequiredJson("/map/summary", { signal });
}

export function fetchMapScorecard(
  day: string,
  signal?: AbortSignal,
): Promise<MapScorecard | null> {
  return requestJson("/map/scorecard", {
    query: new URLSearchParams({ day }), signal,
  });
}

export function fetchMapExposures(
  sp: string,
  k = 15,
  t?: Date,
  rank?: ExposureRank,
  signal?: AbortSignal,
): Promise<ExposuresResponse | null> {
  const query = new URLSearchParams({ sp, k: String(k) });
  if (t) query.set("t", t.toISOString());
  if (rank) query.set("rank", rank);
  return requestJson("/map/exposures", { query, signal });
}

export function fetchMapReach(
  constraint: string,
  options: MapReachOptions = {},
): Promise<ConstraintReach | null> {
  const { k = 15, minFrac, absFloor, full, t, signal } = options;
  const query = new URLSearchParams({ constraint });
  if (full) query.set("full", "true");
  else query.set("k", String(k));
  if (minFrac != null) query.set("min_frac", String(minFrac));
  if (absFloor != null) query.set("abs_floor", String(absFloor));
  if (t) query.set("t", t.toISOString());
  return requestJson("/map/reach", { query, signal });
}

export function fetchMapConstraintsRanked(
  basis: "predicted" | "realized" = "predicted",
  day?: string,
  k = 30,
  signal?: AbortSignal,
): Promise<RankedConstraints | null> {
  const query = new URLSearchParams({ basis, k: String(k) });
  if (day) query.set("day", day);
  return requestJson("/map/constraints/ranked", { query, signal });
}
