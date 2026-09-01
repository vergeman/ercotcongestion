import { useEffect, useMemo, useReducer } from "react";
import type {
  AnalysisGrade, AnalysisGradeHistory, BriefContext, BriefHero,
  Standouts, TopConstraints, TopNodes,
} from "../api/types";
import {
  fetchBriefDetailsCached, fetchBriefHeroLatestCached, fetchBriefHeroShellCached,
  fetchBriefStandoutsCached,
} from "../api/briefCache";
import type { ConnectionState } from "./useExplorerSession";

type BriefDayState = {
  defaultDay: string | null; initialLookupDone: boolean; hero: BriefHero | null;
  topConstraints: TopConstraints | null;
  standouts: Standouts | null; topNodes: TopNodes | null; context: BriefContext | null;
  grade: AnalysisGrade | null; gradeHistory: AnalysisGradeHistory | null;
  heroLoading: boolean; topConstraintsLoading: boolean;
  standoutsLoading: boolean; topNodesLoading: boolean; contextLoading: boolean;
  gradeLoading: boolean; heroError: string | null; detailsError: string | null;
  connectionState: ConnectionState; lastUpdated: Date | null;
  adjacentDays: { previous: string | null; next: string | null };
};

const initialState: BriefDayState = {
  defaultDay: null, initialLookupDone: false, hero: null,
  topConstraints: null, standouts: null, topNodes: null, context: null, grade: null,
  gradeHistory: null, heroLoading: false,
  topConstraintsLoading: false, standoutsLoading: false, topNodesLoading: false,
  contextLoading: false, gradeLoading: false, heroError: null, detailsError: null,
  connectionState: "loading", lastUpdated: null, adjacentDays: { previous: null, next: null },
};

export type BriefDayAction = { type: "patch"; patch: Partial<BriefDayState> };

/** Reducces dependent brief loading transitions into an inspectable state machine. */
export function briefDayReducer(state: BriefDayState, action: BriefDayAction): BriefDayState {
  return action.type === "patch" ? { ...state, ...action.patch } : state;
}

const isAbort = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

/** Owns a delivery day's progressive Brief requests and their cancellation. */
export function useBriefDay(cursorDay: string | null, detailsRetry: number) {
  const [state, dispatch] = useReducer(briefDayReducer, initialState);
  const patch = (next: Partial<BriefDayState>) => dispatch({ type: "patch", patch: next });

  useEffect(() => {
    if (cursorDay) { patch({ initialLookupDone: true }); return; }
    const controller = new AbortController();
    fetchBriefHeroLatestCached(controller.signal)
      .then((latest) => { if (!controller.signal.aborted) patch({ defaultDay: latest?.delivery_date ?? null, initialLookupDone: true }); })
      .catch((error: unknown) => { if (!controller.signal.aborted && !isAbort(error)) patch({ initialLookupDone: true }); });
    return () => controller.abort();
  }, [cursorDay]);

  const deliveryDay = cursorDay ?? state.defaultDay;
  const heroDeliveryDay = state.hero?.available ? state.hero.provenance?.delivery_date : state.hero?.delivery_date;
  const heroMatchesDeliveryDay = heroDeliveryDay === deliveryDay;
  const heroPending = !!deliveryDay && !state.heroError && (state.heroLoading || !heroMatchesDeliveryDay);
  const heroReadyDay = state.hero?.available ? state.hero.provenance?.delivery_date : null;
  const globalLoading = (!deliveryDay && !state.initialLookupDone) || heroPending;

  useEffect(() => {
    if (!deliveryDay) { patch({ adjacentDays: { previous: null, next: null } }); return; }
    const controller = new AbortController();
    patch({ heroLoading: true, heroError: null, connectionState: "loading",
      hero: null, context: null, standouts: null, topNodes: null,
      topConstraints: null, grade: null, gradeHistory: null, detailsError: null,
      adjacentDays: { previous: null, next: null } });
    fetchBriefHeroShellCached(deliveryDay, controller.signal)
      .then((result) => { if (!controller.signal.aborted) patch({ hero: result?.hero ?? null,
        adjacentDays: { previous: result?.previous_delivery_date ?? null, next: result?.next_delivery_date ?? null },
        lastUpdated: new Date(), connectionState: "ok" }); })
      .catch((error: unknown) => { if (!controller.signal.aborted && !isAbort(error)) patch({ heroError: "The daily brief could not be loaded.", connectionState: "error" }); })
      .finally(() => { if (!controller.signal.aborted) patch({ heroLoading: false }); });
    return () => controller.abort();
  }, [deliveryDay]);

  useEffect(() => {
    if (!deliveryDay) return;
    const controller = new AbortController();
    patch({ standoutsLoading: true });
    fetchBriefStandoutsCached(deliveryDay, controller.signal)
      .then((standouts) => { if (!controller.signal.aborted) patch({ standouts }); })
      .catch((error: unknown) => { if (!controller.signal.aborted && !isAbort(error)) patch({ standouts: null }); })
      .finally(() => { if (!controller.signal.aborted) patch({ standoutsLoading: false }); });
    return () => controller.abort();
  }, [deliveryDay]);

  useEffect(() => {
    if (!deliveryDay || !state.hero?.available || state.hero.provenance?.delivery_date !== deliveryDay) return;
    const controller = new AbortController();
    patch({ detailsError: null, contextLoading: true, topNodesLoading: true, topConstraintsLoading: true, gradeLoading: true });
    fetchBriefDetailsCached(deliveryDay, controller.signal)
      .then((result) => { if (!controller.signal.aborted) patch({ context: result?.context ?? null,
        topNodes: result?.top_nodes ?? null, topConstraints: result?.top_constraints ?? null,
        grade: result?.grade ?? null, gradeHistory: result?.grade_history ?? null }); })
      .catch((error: unknown) => { if (!controller.signal.aborted && !isAbort(error)) patch({ detailsError: "The rest of this brief could not be loaded." }); })
      .finally(() => { if (!controller.signal.aborted) patch({ contextLoading: false, topNodesLoading: false, topConstraintsLoading: false, gradeLoading: false }); });
    return () => controller.abort();
  }, [deliveryDay, heroReadyDay, detailsRetry]);

  return useMemo(() => ({ ...state, deliveryDay, heroReadyDay, heroPending, globalLoading }), [state, deliveryDay, heroReadyDay, heroPending, globalLoading]);
}
