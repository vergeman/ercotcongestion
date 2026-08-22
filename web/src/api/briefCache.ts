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

type CacheEntry<T> = {
  hasValue: boolean;
  value?: T;
  promise?: Promise<T>;
};

const entries = new Map<string, CacheEntry<unknown>>();

function cached<T>(key: string, request: () => Promise<T>): Promise<T> {
  const existing = entries.get(key) as CacheEntry<T> | undefined;
  if (existing?.hasValue) return Promise.resolve(existing.value as T);
  if (existing?.promise) return existing.promise;

  const entry: CacheEntry<T> = existing ?? { hasValue: false };
  const promise = request().then(
    (value) => {
      entry.value = value;
      entry.hasValue = true;
      entry.promise = undefined;
      return value;
    },
    (error) => {
      entry.promise = undefined;
      entries.delete(key);
      throw error;
    },
  );
  entry.promise = promise;
  entries.set(key, entry as CacheEntry<unknown>);
  return promise;
}

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
