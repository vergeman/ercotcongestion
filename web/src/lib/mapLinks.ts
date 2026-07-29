// The Map's deep-link / selection convention, single-sourced.
//
// The Map reads (and writes) its current selection through the URL query: a
// constraint is `?constraint=<constraint_key>`, a settlement point is
// `?sp=<settlement_point>`. `MapWorkspace` parses this on load (deep-link) and
// re-emits it on every click, so the two directions must agree on the param
// names — which is why they live here rather than being spelled out inline in
// each place.
//
// Any page can therefore build a link into the map that selects a given
// constraint or node. The builders return a plain relative path, so the CALLER
// picks how it opens — same tab via `<Link to={mapConstraintLink(key)}>`, or a
// new tab via `<Link to={…} target="_blank">` / `<a href={…} target="_blank">`.
// The convention neither assumes nor forbids either. The map already renders a
// graceful "not present in this fit/window" state when a deep-linked target is
// absent, so callers need not pre-check availability.

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
