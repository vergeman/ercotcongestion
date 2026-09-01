import { requestJson } from "./http";
import type {
  BriefDay,
  BriefDetails,
  BriefHeroLatest,
  BriefHeroShell,
  Standouts,
} from "./types";

const dayQuery = (deliveryDate: string) => new URLSearchParams({ delivery_date: deliveryDate });

export function fetchBriefHeroLatest(signal?: AbortSignal): Promise<BriefHeroLatest | null> {
  return requestJson("/analysis/hero/latest", { signal });
}
export function fetchBriefDay(deliveryDate: string, signal?: AbortSignal): Promise<BriefDay | null> {
  return requestJson("/analysis/brief", { query: dayQuery(deliveryDate), signal });
}
export function fetchBriefHeroShell(
  deliveryDate: string,
  signal?: AbortSignal,
): Promise<BriefHeroShell | null> {
  return requestJson("/analysis/brief/hero", { query: dayQuery(deliveryDate), signal });
}
export function fetchBriefStandouts(deliveryDate: string, signal?: AbortSignal): Promise<Standouts | null> {
  const query = dayQuery(deliveryDate); query.set("k", "4");
  return requestJson("/analysis/standouts", { query, signal });
}
export function fetchBriefDetails(deliveryDate: string, signal?: AbortSignal): Promise<BriefDetails | null> {
  const query = dayQuery(deliveryDate); query.set("include_standouts", "false");
  return requestJson("/analysis/brief/details", { query, signal });
}
