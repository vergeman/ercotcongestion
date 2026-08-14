// The Map's deep-link / selection convention, single-sourced.
//
// The Map reads (and writes) its current selection through the URL query: a
// constraint is `?constraint=<constraint_key>`, a settlement point is
// `?sp=<settlement_point>`. `MapWorkspace` parses this on load (deep-link) and
// re-emits it on every click, so the two directions must agree on the param
// names — which is why they live here rather than being spelled out inline in
// each place.
//
// 0131 adds the Map's other two axes to the same contract: `view` (0130's
// layout — forecast|market|compare|error) and `data` (congestion|lmp), plus
// `autoPlay`, a one-shot behaviour rather than durable state (see
// `AUTOPLAY_PARAM` below). All three, plus `constraint`/`sp`, are what a full
// Map deep link — e.g. the Brief hero's link — carries; `buildMapLink` composes
// them.
//
// Any page can therefore build a link into the map that selects a given
// constraint or node. The builders return a plain relative path, so the CALLER
// picks how it opens — same tab via `<Link to={mapConstraintLink(key)}>`, or a
// new tab via `<Link to={…} target="_blank">` / `<a href={…} target="_blank">`.
// The convention neither assumes nor forbids either. The map already renders a
// graceful "not present in this fit/window" state when a deep-linked target is
// absent, so callers need not pre-check availability.

import type { MapView, MapDataMode } from "../api/types";

// A resolved map selection. Mirrors the two `?…=` query forms above.
export type MapTarget =
  | { kind: "constraint"; value: string }
  | { kind: "sp"; value: string };

// The map route these links land on.
export const MAP_PATH = "/map";

// Parse a location search string ("?constraint=…" / "?sp=…") into a target, or
// null when neither param is present. `constraint` wins if both appear.
export function parseMapTarget(search: string): MapTarget | null {
  const params = new URLSearchParams(search);
  const constraint = params.get("constraint");
  if (constraint) return { kind: "constraint", value: constraint };
  const sp = params.get("sp");
  return sp ? { kind: "sp", value: sp } : null;
}

// The search string ("?constraint=…" / "?sp=…") that selects `target` — the
// serialize counterpart to `parseMapTarget`, used by the map when a click
// rewrites the route.
export function mapTargetSearch(target: MapTarget): string {
  const params = new URLSearchParams();
  params.set(target.kind, target.value);
  return `?${params.toString()}`;
}

// The full relative path ("/map?constraint=…" / "/map?sp=…") that selects
// `target`. Usable as a react-router <Link to> / navigate() (same tab) or as an
// <a href> with target="_blank" (new tab) — the caller decides.
export function mapLinkTo(target: MapTarget): string {
  return `${MAP_PATH}${mapTargetSearch(target)}`;
}

// Convenience builders for the two selection kinds.
export const mapConstraintLink = (constraintKey: string): string =>
  mapLinkTo({ kind: "constraint", value: constraintKey });
export const mapSettlementPointLink = (settlementPoint: string): string =>
  mapLinkTo({ kind: "sp", value: settlementPoint });

// ── View/data axes (0131) ───────────────────────────────────────────────────
//
// The Map's other two axes (0130), serialized the same way as the selection
// above: `view=forecast|market|compare|error` (exactly one), `data=congestion
// |lmp`. Both are durable state — unlike `autoPlay` below, they belong in
// every Map URL and survive navigation until the reader changes them.

export const DEFAULT_MAP_VIEW: MapView = "forecast";
export const DEFAULT_MAP_DATA_MODE: MapDataMode = "congestion";

export interface MapViewState {
  view: MapView;
  data: MapDataMode;
}

const VALID_VIEWS: readonly MapView[] = ["forecast", "market", "compare", "error"];
const VALID_DATA_MODES: readonly MapDataMode[] = ["congestion", "lmp"];

// Static canonicalization only — "no settled data in the loaded window"
// requires runtime session state the URL alone doesn't carry, so that
// downgrade stays a MapWorkspace effect (mirroring the Header's own
// disabled-chip rule). This function only enforces what the buttons can never
// produce regardless of data: Error's data axis is always congestion.
function canonicalizeMapViewState(view: MapView, data: MapDataMode): MapViewState {
  return view === "error" ? { view, data: "congestion" } : { view, data };
}

// Parse `view`/`data` from a location search string. Missing or unrecognized
// values fall back to the shipped default (Forecast × Congestion) rather than
// rejecting the link — a stale or hand-edited URL should still land somewhere
// sane, matching `parseMapTarget`'s graceful-fallback spirit.
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

// The `view=…&data=…` pair for `state`, canonicalized. Callers patch this
// into an existing search string rather than replacing it outright — see
// `App.tsx`'s `withCoord`, which is where t/ws/we/run/span/constraint/sp
// actually survive a view/data change.
export function mapViewStateParams(state: MapViewState): URLSearchParams {
  const canon = canonicalizeMapViewState(state.view, state.data);
  const params = new URLSearchParams();
  params.set("view", canon.view);
  params.set("data", canon.data);
  return params;
}

// ── autoPlay (0131) ──────────────────────────────────────────────────────────
//
// `autoPlay=true` requests exactly one playback on arrival — behaviour, not a
// durable preference. The contract is consume-once: a reader calls
// `consumeAutoPlay` on mount, and if it reports a request, immediately strips
// the param (via the returned `strip` helper) so a later in-session
// navigation — back to this route, or a Map↔Matrix hop — never replays it.
export const AUTOPLAY_PARAM = "autoPlay";

export function hasAutoPlayRequest(search: string): boolean {
  return new URLSearchParams(search).get(AUTOPLAY_PARAM) === "true";
}

// The same search string with `autoPlay` removed — the strip half of the
// consume-once contract. Every other param (coordinate, view/data, selection)
// passes through untouched.
export function stripAutoPlay(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(AUTOPLAY_PARAM);
  const query = params.toString();
  return query ? `?${query}` : "";
}

// ── Full link builder (0131) ────────────────────────────────────────────────
//
// The one place that composes a complete Map deep link: the shared time
// coordinate (already owned by `useTimeCursor`'s compact `…Z` hour form),
// the view/data axes, an optional selection, and whether to request a single
// autoplay. Used by the Brief hero and, per the plan's task note, the Brief's
// other `/map` links once this contract lands.
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
