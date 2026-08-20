import {
  fetchBriefDay,
  fetchBriefDetails,
  fetchBriefHeroLatest,
  fetchBriefHeroShell,
} from "./client";
import type {
  BriefDay,
  BriefDetails,
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

const scope = (runId?: string) => runId ?? "default";

export function fetchBriefHeroLatestCached(runId?: string): Promise<BriefHeroLatest | null> {
  return cached(`hero-latest:${scope(runId)}`, () => fetchBriefHeroLatest(runId));
}

export function fetchBriefDayCached(
  deliveryDate: string,
  runId?: string,
): Promise<BriefDay | null> {
  return cached(`brief:${deliveryDate}:${scope(runId)}`, () => fetchBriefDay(deliveryDate, runId));
}

export function fetchBriefHeroShellCached(
  deliveryDate: string,
  runId?: string,
): Promise<BriefHeroShell | null> {
  return cached(`brief-hero:${deliveryDate}:${scope(runId)}`, () =>
    fetchBriefHeroShell(deliveryDate, runId)
  );
}

export function fetchBriefDetailsCached(
  deliveryDate: string,
  runId?: string,
): Promise<BriefDetails | null> {
  return cached(`brief-details:${deliveryDate}:${scope(runId)}`, () =>
    fetchBriefDetails(deliveryDate, runId)
  );
}
