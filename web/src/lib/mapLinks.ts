import type { MapView, MapDataMode } from "../api/types";

export type MapTarget =
  | { kind: "constraint"; value: string }
  | { kind: "sp"; value: string };

export const MAP_PATH = "/map";

export function parseMapTarget(search: string): MapTarget | null {
  const params = new URLSearchParams(search);
  const constraint = params.get("constraint");
  if (constraint) return { kind: "constraint", value: constraint };
  const sp = params.get("sp");
  return sp ? { kind: "sp", value: sp } : null;
}

export function mapTargetSearch(target: MapTarget): string {
  const params = new URLSearchParams();
  params.set(target.kind, target.value);
  return `?${params.toString()}`;
}

export function mapLinkTo(target: MapTarget): string {
  return `${MAP_PATH}${mapTargetSearch(target)}`;
}

export const mapConstraintLink = (constraintKey: string): string =>
  mapLinkTo({ kind: "constraint", value: constraintKey });
export const mapSettlementPointLink = (settlementPoint: string): string =>
  mapLinkTo({ kind: "sp", value: settlementPoint });

export const DEFAULT_MAP_VIEW: MapView = "forecast";
export const DEFAULT_MAP_DATA_MODE: MapDataMode = "congestion";

export interface MapViewState {
  view: MapView;
  data: MapDataMode;
}

const VALID_VIEWS: readonly MapView[] = ["forecast", "market", "compare", "error"];
const VALID_DATA_MODES: readonly MapDataMode[] = ["congestion", "lmp"];

// Error always uses congestion data.
function canonicalizeMapViewState(view: MapView, data: MapDataMode): MapViewState {
  return view === "error" ? { view, data: "congestion" } : { view, data };
}

export function parseMapViewState(search: string): MapViewState {
  const params = new URLSearchParams(search);
  const rawView = params.get("view");
  const rawData = params.get("data");
  const view = (VALID_VIEWS as readonly string[]).includes(rawView ?? "")
    ? (rawView as MapView)
    : DEFAULT_MAP_VIEW;
  const data = (VALID_DATA_MODES as readonly string[]).includes(rawData ?? "")
    ? (rawData as MapDataMode)
    : DEFAULT_MAP_DATA_MODE;
  return canonicalizeMapViewState(view, data);
}

export function mapViewStateParams(state: MapViewState): URLSearchParams {
  const canon = canonicalizeMapViewState(state.view, state.data);
  const params = new URLSearchParams();
  params.set("view", canon.view);
  params.set("data", canon.data);
  return params;
}

export const AUTOPLAY_PARAM = "autoPlay";

export function hasAutoPlayRequest(search: string): boolean {
  return new URLSearchParams(search).get(AUTOPLAY_PARAM) === "true";
}

export function stripAutoPlay(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(AUTOPLAY_PARAM);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export interface MapLinkSpec extends MapViewState {
  t?: Date | null;
  ws?: Date | null;
  we?: Date | null;
  target?: MapTarget | null;
  autoPlay?: boolean;
}

const formatCoordinate = (value: Date) => `${value.toISOString().slice(0, 13)}Z`;

export function buildMapLink(spec: MapLinkSpec): string {
  const params = mapViewStateParams(spec);
  if (spec.t) params.set("t", formatCoordinate(spec.t));
  if (spec.ws) params.set("ws", formatCoordinate(spec.ws));
  if (spec.we) params.set("we", formatCoordinate(spec.we));
  if (spec.target) params.set(spec.target.kind, spec.target.value);
  if (spec.autoPlay) params.set(AUTOPLAY_PARAM, "true");
  return `${MAP_PATH}?${params.toString()}`;
}
