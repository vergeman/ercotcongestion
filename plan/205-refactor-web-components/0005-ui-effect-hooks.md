# 205-0005 - UI-effect hooks and hook placement

Type: refactor
Branch: refactor/205-0005-ui-effect-hooks

## Goal

* Extract the duplicated dismiss/focus effects into small reusable hooks.
* Relocate single-surface hooks that leaked into `hooks/` down to their `features/` folder.
* Change no behavior — dismissal, focus, and fetch semantics stay identical.

## Context

* Data-fetch hooks are already well-extracted (`useBriefDay`, `useScoreboard`, `useMapBootstrap`, `features/matrix/*`); the heavy inline-effect files that remain are `GridMap` (imperative MapLibre, out of scope) and `MapWorkspace` (owned by 205-0004).
* Three sites hand-roll keyboard/pointer dismissal with slightly different bundles: `BriefPage` GradeCard popover (outside-click + Escape), `BriefDetailPanel` (Escape + focus-trap + return-focus), `MobileDrawer` (Escape only).
* `features/` is meant to be per-surface (hooks + components colocated) and `hooks/` generic; `useBriefDay`, `useScoreboard`, `useMapRows`, `useMapBootstrap` are single-surface but currently sit in `hooks/`.

## Approach

* Work in: `web/src/hooks/` (new shared hooks) and the three dismiss sites.
* Add `usePopoverDismiss` (outside-click + Escape) — adopt in `BriefPage` GradeCard's formula popover; reuse anywhere else the same pattern appears.
* Add `useModalDismiss` (Escape + optional focus-trap + return-focus) — adopt in `BriefDetailPanel` and `MobileDrawer`; keep the drawer's no-trap behavior by making the trap opt-in.
* Relocate `useBriefDay` → `features/brief/`, `useScoreboard`/`useScoreboardChart` neighbors → `features/scoreboard/`, `useMapRows`/`useMapBootstrap` → `features/map/`; update imports. Leave genuinely generic hooks (`useMediaQuery`, `useTimeCursor`, `useSharedExplorer`) in `hooks/`.
* Comments: as hooks are extracted/relocated, revise their comments to brief, plain-English intent — cut statistical jargon, over-explanation, and verbosity (power terminology is fine).
* Do NOT touch: `GridMap` effects, `MapWorkspace` hook extraction (205-0004 owns it), or any fetch/abort logic — this branch is dismiss/placement only.

## Acceptance

* [ ] `usePopoverDismiss` and `useModalDismiss` exist and back the three former hand-rolled sites; no raw `addEventListener("keydown"/"mousedown")` dismiss code remains at those call sites.
* [ ] The relocated hooks live under their `features/` folder; `hooks/` holds only cross-surface hooks.
* [ ] Escape/outside-click close, focus-trap, and return-focus behave exactly as before on each surface.
* [ ] Comments on extracted/relocated hooks are brief plain English — no statistical jargon, over-explanation, or verbosity.
* [ ] `npx tsc -b` and `npm run lint` clean against baseline.
