# 0147 - transmission-hover-and-reach-fallback

Type: fix
Branch: fix/0147-transmission-hover-and-reach-fallback

## Goal

* Restore hover isolation on transmission constraints (only GTC worked).
* Make the node fade + DetailCard show the same constituents on every day, including artifact-less ones.
* Stop the hover request storm and keep the multi-constraint node card reachable across a transmission line.
* Replace the fixed `k=15` reach cap with a threshold so broad constraints aren't truncated and noise-peak ones aren't flooded.

## Context

* 0116 rewrote the overview to native layers but only wired a hit target for GTC gates; transmission corridors got none.
* 0144 made `/map/reach` day-aware, so it returns empty on any day without an artifact (every forward day) — the fade and card silently blanked.
* The overview `nodes` field is a truncated top-6 glyph set (bundle `k=6`), NOT full membership.

## Approach

* Work in: `web/src/components/map/GridMap.tsx`, `web/src/components/map/OverviewPopover.tsx`, `api/map.py`, `api/models.py`, `web/src/api/types.ts`, `web/src/components/map/DetailCard.tsx`.
* Transmission hover — add `ov-corridor-hit` (wide, ~invisible line over the corridor source); bind the constraint handlers to `["ov-gtc-hit","ov-corridor-hit"]`; derive popover `kind` from feature `ctype`; add `transmission` kind/label/color to `OverviewPopover`.
* Fade membership — read the full `reach`/`focusReach` set (matches the card), overview glyph field only as a pre-load fallback. Do NOT key it off the truncated overview `nodes`.
* Server fallback — `_nearest_past_artifact_day`; in `get_map_reach`, when the day's artifact is missing serve the nearest earlier built day, skip the interval gate, set `basis="nearest_past"`. Scope to `artifact_missing` only (leave `constraint_not_in_artifact` unavailable). DetailCard shows "SF as of <date>" when `basis==="nearest_past"`.
* Request storm — bind the constraint hover handlers once: stash `onIsolateConstraint`/`onConstraintPreview`/`onConstraintSelect` in `callbacksRef`, drop them from the effect deps.
* Sticky node card — corridor/GTC `onEnter`/`onMove`/`onLeave` yield (`overStickyNodeCard()`) while a `kind:"node"` member card is showing, so the pointer can travel onto it.
* Reach threshold — add `abs_floor` param to `/map/reach`; filter = `|SF| >= max(min_frac*peak, abs_floor)`. Single-source `REACH_THRESHOLD_OPTS = {full, minFrac:0.15, absFloor:0.03}` in `client.ts`; the map fetches (`MapWorkspace`) AND the shared `useConstraintReach` hook (map sidebar, Brief evidence, **BriefFootprintMap**) both use it. Footprint/glow draw the full set; the row lists (`DetailCard`, `MemberList`) slice to 20 + "+N more". Defaults (`abs_floor=0`) leave the matrix Read pane's complete reach unchanged.
* Do NOT touch: exposures / 0146 node-not-in-fit path; matrix Read pane `full` mode (must stay complete — hence `abs_floor` default 0).

## Acceptance

* [x] Hovering a transmission corridor isolates it and fades non-members (same as GTC).
* [x] On an artifact-less/forward day the card fills from the nearest past day and shows "SF as of <date>"; `basis=nearest_past` in the response.
* [x] Node glow == DetailCard constituent list (no member hidden past the glyph's top-6).
* [x] One `mouseenter` → ~2 `/map/reach` calls per fresh hover (no re-fire storm).
* [x] A multi-constraint node card survives sliding across a transmission line onto it.
* [x] Threshold reach: WESTEX|BASE CASE glows ~300 (was 15), NELRIO ~9, noise-peak (peak<0.03) → empty; card lists 20 + "+N more".
* [x] BriefFootprintMap + Brief evidence + map sidebar share the same threshold via `useConstraintReach`; footprint draws the full set, lists cap at 20.
* [x] `api/tests/test_map.py` reach tests pass (incl. nearest-past fallback); `tsc --noEmit` clean.

## Follow-up (open)

* `min_frac=0.15`/`abs_floor=0.03` chosen from the current window's node-count distribution; revisit if broad constraints glow too densely or noise-peak constraints (now empty cards) need a "no significant reach" message.
* The fade still falls back to the overview glyph (k=6) when reach is empty, so a suppressed noise constraint can glow ~6 nodes while its card is empty — tighten if it matters.
