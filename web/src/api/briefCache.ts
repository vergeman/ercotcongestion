import {
  fetchAnalysisGrade,
  fetchAnalysisGradeHistory,
  fetchBriefContext,
  fetchBriefHero,
  fetchBriefHeroLatest,
  fetchStandouts,
  fetchTopConstraints,
  fetchTopNodes,
} from "./client";
import type {
  AnalysisGrade,
  AnalysisGradeHistory,
  BriefContext,
  BriefHero,
  BriefHeroLatest,
  Standouts,
  TopConstraints,
  TopNodes,
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

export function fetchBriefHeroCached(
  deliveryDate: string,
  runId?: string,
): Promise<BriefHero | null> {
  return cached(`hero:${deliveryDate}:${scope(runId)}`, () => fetchBriefHero(deliveryDate, runId));
}

export function fetchBriefContextCached(
  deliveryDate: string,
  runId?: string,
): Promise<BriefContext | null> {
  return cached(`context:${deliveryDate}:${scope(runId)}`, () => fetchBriefContext(deliveryDate, { runId }));
}

export function fetchStandoutsCached(
  deliveryDate: string,
  runId?: string,
): Promise<Standouts | null> {
  return cached(`standouts:${deliveryDate}:${scope(runId)}`, () => fetchStandouts(deliveryDate, { runId }));
}

export function fetchTopNodesCached(
  deliveryDate: string,
  runId?: string,
): Promise<TopNodes | null> {
  return cached(`top-nodes:${deliveryDate}:${scope(runId)}`, () => fetchTopNodes(deliveryDate, { runId }));
}

export function fetchTopConstraintsCached(
  deliveryDate: string,
  runId?: string,
): Promise<TopConstraints | null> {
  return cached(`top-constraints:${deliveryDate}:${scope(runId)}`, () => fetchTopConstraints(deliveryDate, { runId }));
}

export function fetchAnalysisGradeCached(
  deliveryDate: string,
  runId?: string,
): Promise<AnalysisGrade | null> {
  return cached(`grade:${deliveryDate}:${scope(runId)}`, () => fetchAnalysisGrade(deliveryDate, { runId }));
}

export function fetchAnalysisGradeHistoryCached(
  deliveryDate: string,
  runId?: string,
): Promise<AnalysisGradeHistory | null> {
  return cached(`grade-history:${deliveryDate}:${scope(runId)}`, () => fetchAnalysisGradeHistory(deliveryDate, { runId }));
}
