/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useState } from "react";
import type {
  MatrixEntitySelection,
  MatrixLens,
  MatrixTab,
  MatrixValTab,
} from "../../lib/matrix";
import { APP_STORAGE_PREFIX } from "../../lib/brand";

export const PIN_STORAGE_KEY = `${APP_STORAGE_PREFIX}.matrix-pins.v1`;
export const MAX_PINS = 20;

let rememberedTab: MatrixTab = "constraints";
let rememberedLens: MatrixLens = "read";
let rememberedVal: MatrixValTab = "sf";
let rememberedSelection: MatrixEntitySelection = null;
let rememberedBasisA: string | null = null;
let rememberedBasisB: string | null = null;

export interface MatrixRouteState {
  tab: MatrixTab;
  lens: MatrixLens;
  val: MatrixValTab;
  query: string;
  fType: string;
  fZone: string;
  selection: MatrixEntitySelection;
  pinnedConstraints: string[];
  pinnedSettlementPoints: string[];
  basisA: string | null;
  basisB: string | null;
  basisActiveSlot: "a" | "b";
}

export function boundedPins(values: string[]) {
  return [
    ...new Set(values.map((value) => value.trim()).filter(Boolean)),
  ].slice(0, MAX_PINS);
}

export function storedPins(): Pick<
  MatrixRouteState,
  "pinnedConstraints" | "pinnedSettlementPoints"
> {
  try {
    const value = JSON.parse(
      window.localStorage.getItem(PIN_STORAGE_KEY) ?? "null"
    ) as {
      version?: number;
      constraints?: string[];
      settlementPoints?: string[];
    } | null;
    if (value?.version === 1)
      return {
        pinnedConstraints: boundedPins(value.constraints ?? []),
        pinnedSettlementPoints: boundedPins(value.settlementPoints ?? []),
      };
  } catch {
    /* A malformed old value is recoverable through Reset. */
  }
  return { pinnedConstraints: [], pinnedSettlementPoints: [] };
}

export function storedSeeded(): boolean {
  try {
    return (
      (
        JSON.parse(window.localStorage.getItem(PIN_STORAGE_KEY) ?? "null") as {
          seeded?: boolean;
        } | null
      )?.seeded === true
    );
  } catch {
    return false;
  }
}

export function matrixRouteStateFromSearch(search: string): MatrixRouteState {
  const params = new URLSearchParams(search);
  const stored = storedPins();
  const constraintKey = params.get("constraint");
  const sp = params.get("sp");
  const tabParam = params.get("tab");
  const tab: MatrixTab =
    tabParam === "nodes" || tabParam === "constraints"
      ? tabParam
      : sp && !constraintKey
      ? "nodes"
      : "constraints";
  const lensParam = params.get("lens");
  const basisA = params.get("sp_a") || null;
  const basisB = params.get("sp_b") || null;
  const valParam = params.get("val");
  return {
    tab,
    lens:
      lensParam === "sf"
        ? "sf"
        : lensParam === "basis" && tab === "nodes"
        ? "basis"
        : "read",
    val: valParam === "fmu" || valParam === "dmu" ? valParam : "sf",
    query: (params.get("q") ?? params.get("constraint_search") ?? "").slice(
      0,
      64
    ),
    fType: params.get("type") ?? "",
    fZone: params.get("zone") ?? "",
    selection: constraintKey
      ? { kind: "constraint", key: constraintKey }
      : sp
      ? { kind: "node", point: sp }
      : null,
    pinnedConstraints: params.has("pinned_constraint")
      ? boundedPins(params.getAll("pinned_constraint"))
      : stored.pinnedConstraints,
    pinnedSettlementPoints: params.has("pinned_sp")
      ? boundedPins(params.getAll("pinned_sp"))
      : stored.pinnedSettlementPoints,
    basisA,
    basisB,
    basisActiveSlot: basisA && !basisB ? "b" : "a",
  };
}

export function matrixSearchFromRouteState(state: MatrixRouteState): string {
  const params = new URLSearchParams();
  params.set("tab", state.tab);
  if (state.lens !== "read") params.set("lens", state.lens);
  if (state.val !== "sf") params.set("val", state.val);
  if (state.query) params.set("q", state.query);
  if (state.fType) params.set("type", state.fType);
  if (state.fZone) params.set("zone", state.fZone);
  if (state.selection?.kind === "constraint")
    params.set("constraint", state.selection.key);
  if (state.selection?.kind === "node") params.set("sp", state.selection.point);
  if (state.basisA) params.set("sp_a", state.basisA);
  if (state.basisB) params.set("sp_b", state.basisB);
  return `?${params.toString()}`;
}

export function useMatrixRouteState(
  routeSearch: string,
  onRouteChange: (search: string) => void
) {
  const [state, setState] = useState<MatrixRouteState>(() => {
    const params = new URLSearchParams(routeSearch);
    const route = matrixRouteStateFromSearch(routeSearch);
    return {
      ...route,
      tab:
        params.has("tab") || params.has("sp") || params.has("constraint")
          ? route.tab
          : rememberedTab,
      lens: params.has("lens") ? route.lens : rememberedLens,
      val: params.has("val") ? route.val : rememberedVal,
      selection: route.selection ?? rememberedSelection,
      basisA: params.has("sp_a") ? route.basisA : rememberedBasisA,
      basisB: params.has("sp_b") ? route.basisB : rememberedBasisB,
    };
  });
  const update = (patch: Partial<MatrixRouteState>) =>
    setState((current) => {
      const next = { ...current, ...patch };
      rememberedTab = next.tab;
      rememberedLens = next.lens;
      rememberedVal = next.val;
      rememberedSelection = next.selection;
      rememberedBasisA = next.basisA;
      rememberedBasisB = next.basisB;
      onRouteChange(matrixSearchFromRouteState(next));
      return next;
    });
  useEffect(() => {
    const next = matrixRouteStateFromSearch(routeSearch);
    rememberedTab = next.tab;
    rememberedLens = next.lens;
    rememberedVal = next.val;
    rememberedSelection = next.selection;
    rememberedBasisA = next.basisA;
    rememberedBasisB = next.basisB;
    setState(next);
  }, [routeSearch]);
  return { state, update };
}
