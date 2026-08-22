import { requestJson, requestRequiredJson } from "./http";
import type { ConditionsRangeResponse, ErcotRangeResponse, ForecastRangeResponse } from "./types";

const rangeQuery = (start?: Date, end?: Date) => {
  const query = new URLSearchParams();
  if (start) query.set("start", start.toISOString());
  if (end) query.set("end", end.toISOString());
  return query;
};

export function fetchTopology(signal?: AbortSignal): Promise<unknown> {
  return requestRequiredJson("/topology", { signal });
}

export function fetchErcotRange(
  start: Date,
  end: Date,
  signal?: AbortSignal,
): Promise<ErcotRangeResponse | null> {
  return requestJson("/ercot_range", { query: rangeQuery(start, end), signal });
}

export function fetchForecastRange(
  start?: Date,
  end?: Date,
  signal?: AbortSignal,
): Promise<ForecastRangeResponse | null> {
  return requestJson("/forecast_range", { query: rangeQuery(start, end), signal });
}

export function fetchConditionsRange(
  start?: Date,
  end?: Date,
  signal?: AbortSignal,
): Promise<ConditionsRangeResponse | null> {
  return requestJson("/conditions_range", { query: rangeQuery(start, end), signal });
}
