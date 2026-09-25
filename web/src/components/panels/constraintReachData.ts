import { useEffect, useState } from "react";
import type { ConstraintReach } from "../../api/types";
import { fetchMapReach, REACH_THRESHOLD_OPTS } from "../../api/client";
import { deliveryDateCT } from "../../lib/time";

const reachCache = new Map<string, ConstraintReach | null>();
const fullReachCache = new Map<string, ConstraintReach | null>();

function reachKey(id: string, t?: Date): string {
  return `${t ? deliveryDateCT(t) : "latest"}|${id}`;
}

export const REACH_K = 20;
export const REACH_ROW_CAP = 20;

function useReach(
  id: string | null,
  t: Date | undefined,
  full: boolean,
  k = REACH_K,
): { reach: ConstraintReach | null; loading: boolean } {
  const key = id ? reachKey(id, t) : null;
  const cache = full ? fullReachCache : reachCache;
  const cached = key ? cache.get(key) : undefined;
  const [reach, setReach] = useState<ConstraintReach | null>(cached ?? null);
  const [loading, setLoading] = useState(!!key && !cache.has(key));

  useEffect(() => {
    let live = true;
    const publish = (next: ConstraintReach | null, pending: boolean) => {
      queueMicrotask(() => {
        if (!live) return;
        setReach(next);
        setLoading(pending);
      });
    };
    if (!id || !key) {
      publish(null, false);
      return () => { live = false; };
    }
    if (cache.has(key)) {
      publish(cache.get(key) ?? null, false);
      return () => { live = false; };
    }
    publish(null, true);
    fetchMapReach(id, full ? { full: true, minFrac: 0, t } : { k, t, ...REACH_THRESHOLD_OPTS })
      .then((result) => {
        cache.set(key, result);
        if (live) setReach(result);
      })
      .catch(() => {
        cache.set(key, null);
        if (live) setReach(null);
      })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [cache, full, id, k, key, t]);

  return { reach, loading };
}

export function useConstraintReach(id: string | null, k = REACH_K, t?: Date) {
  return useReach(id, t, false, k);
}

export function useFullConstraintReach(id: string | null, t?: Date) {
  return useReach(id, t, true);
}

export function dipoleCounts(reach: ConstraintReach | null) {
  let negative = 0;
  let positive = 0;
  for (const member of reach?.sps ?? []) {
    if (member.sf < 0) negative += 1;
    else positive += 1;
  }
  return { negative, positive };
}
