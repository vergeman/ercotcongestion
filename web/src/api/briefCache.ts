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

function cached<T>(
  key: string,
  request: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  return entries.load(key, request, signal) as Promise<T>;
}

export function clearBriefCache(): void { entries.invalidate(); }

export function fetchBriefHeroLatestCached(signal?: AbortSignal): Promise<BriefHeroLatest | null> {
  return cached("hero-latest", fetchBriefHeroLatest, signal);
}

export function fetchBriefDayCached(
  deliveryDate: string,
  signal?: AbortSignal,
): Promise<BriefDay | null> {
  return cached(`brief:${deliveryDate}`, (requestSignal) =>
    fetchBriefDay(deliveryDate, requestSignal), signal);
}

export function fetchBriefHeroShellCached(
  deliveryDate: string,
  signal?: AbortSignal,
): Promise<BriefHeroShell | null> {
  return cached(
    `brief-hero:${deliveryDate}`,
    (requestSignal) => fetchBriefHeroShell(deliveryDate, requestSignal),
    signal,
  );
}

export function fetchBriefHeroStatsCached(
  deliveryDate: string,
  signal?: AbortSignal,
): Promise<BriefHeroStats | null> {
  return cached(
    `brief-hero-stats:${deliveryDate}`,
    (requestSignal) => fetchBriefHeroStats(deliveryDate, requestSignal),
    signal,
  );
}

export function fetchBriefStandoutsCached(
  deliveryDate: string, signal?: AbortSignal,
): Promise<Standouts | null> {
  return cached(
    `brief-standouts:${deliveryDate}`,
    (requestSignal) => fetchBriefStandouts(deliveryDate, requestSignal),
    signal,
  );
}

export function fetchBriefDetailsCached(
  deliveryDate: string, signal?: AbortSignal,
): Promise<BriefDetails | null> {
  return cached(
    `brief-details:${deliveryDate}`,
    (requestSignal) => fetchBriefDetails(deliveryDate, requestSignal),
    signal,
  );
}
