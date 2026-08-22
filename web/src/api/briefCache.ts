import { QueryCache } from "./cache";
import {
  fetchBriefDay,
  fetchBriefDetails,
  fetchBriefHeroStats,
  fetchBriefStandouts,
  fetchBriefHeroLatest,
  fetchBriefHeroShell,
} from "./client";
import type {
  BriefDay,
  BriefDetails,
  BriefHeroStats,
  Standouts,
  BriefHeroLatest,
  BriefHeroShell,
} from "./types";

const entries = new QueryCache<unknown>({ maxSize: 48, ttlMs: 5 * 60 * 1000 });

function cached<T>(key: string, request: () => Promise<T>): Promise<T> {
  return entries.load(key, () => request()) as Promise<T>;
}

export function clearBriefCache(): void { entries.invalidate(); }

export function fetchBriefHeroLatestCached(): Promise<BriefHeroLatest | null> {
  return cached("hero-latest", fetchBriefHeroLatest);
}

export function fetchBriefDayCached(
  deliveryDate: string,
): Promise<BriefDay | null> {
  return cached(`brief:${deliveryDate}`, () => fetchBriefDay(deliveryDate));
}

export function fetchBriefHeroShellCached(
  deliveryDate: string,
): Promise<BriefHeroShell | null> {
  return cached(`brief-hero:${deliveryDate}`, () =>
    fetchBriefHeroShell(deliveryDate)
  );
}

export function fetchBriefHeroStatsCached(
  deliveryDate: string,
): Promise<BriefHeroStats | null> {
  return cached(`brief-hero-stats:${deliveryDate}`, () =>
    fetchBriefHeroStats(deliveryDate)
  );
}

export function fetchBriefStandoutsCached(
  deliveryDate: string,
): Promise<Standouts | null> {
  return cached(`brief-standouts:${deliveryDate}`, () =>
    fetchBriefStandouts(deliveryDate)
  );
}

export function fetchBriefDetailsCached(
  deliveryDate: string,
): Promise<BriefDetails | null> {
  return cached(`brief-details:${deliveryDate}`, () =>
    fetchBriefDetails(deliveryDate)
  );
}
