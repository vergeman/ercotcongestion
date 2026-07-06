# 0058 - map-palette-mc-lmp

Type: feat
Branch: feat/0058-map-palette-mc-lmp

## Goal

Fix the MC palette's mid-range collapse, add an ERCOT counterpart for
visual validation, and retire the drifted Congestion-vs-Basis tab.

## Context

* MC palette anchors on `P99(|mc|)` with `γ=1.8`. One heavy hour lifts
  P99 to $400+, damping typical-hour buses ($30–$90) to near-cream.
* Within one snapshot, LMP mirrors MC's spatial pattern because
  `LMP = system_λ + congestion + losses` and `system_λ` is uniform.
* No ERCOT-side congestion map exists. The right quantity is
  `SPP − system_λ` per SP (NP4-190-CD + NP4-523-CD; both ingested).
* The "Congestion vs Basis" tab drifted: `basis` is now
  `model_LMP − ERCOT_zonal_LMP` (a cross-system delta with calibration
  bias baked in), not the hub-relative same-OPF quantity its name and
  `Basis.md` still describe.

## Decisions

* **Q1 — MC palette.** Tighten anchor + reduce γ: `MC_PCT_HIGH 0.99→0.90`,
  `MC_GAMMA 1.8→1.2`. Keeps "same $/MWh = same shade"; outliers stay on
  the rational tail.
* **Q2 — LMP palette.** Unchanged. Window-median cream; `system_λ` drift
  shows as global brightness across frames.
* **Q3 — Layout: paired split per palette.** No standalone ERCOT view.
  The `ComparisonMode` toggle (Split/Single/Diff) is retired; every
  palette pill renders a two-pane split:
    * `Modeled Congestion` → model MC | SP `SPP − system_λ`.
    * `LMP` → model LMP | SP raw `dam_spp`.
    * `Binding Proximity` → model | empty (no ERCOT counterpart).
* **Q4 — Congestion vs Basis.** Retire. Paired-split MC is the cleaner
  answer. Delete the ViewMode entry and the rank-Δ path in `colors.ts`.

## Scope

* Touch: `web/src/lib/colors.ts`, `Legend.tsx`, `GridMap.tsx`, `App.tsx`,
  `Header.tsx`, `CompareMap.tsx`, `api/models.py`, new `api/ercot_spp.py`.
* Don't touch: compute-side MC definition, OPF write path, DB schema.

## Acceptance

Code-complete items are checked; live-app or compute-container checks
are left open.

* [x] Decisions recorded above.
* [x] **Q1 code.** `MC_PCT_HIGH`, `MC_GAMMA` updated; legend anchor label
      reads `|value| P90`.
* [ ] **Q1 visual.** Bus at |mc|≈$50 renders visibly non-cream on
      `runs/v1-3d`.
* [x] **Q2.** No LMP palette code change.
* [x] **Q3 code.** `ComparisonMode` removed; palette pills always show
      the paired split; right pane routed by `rightPaneFor(viewMode)`
      (`/ercot_state_range` for MC, `/ercot_spp_range` for LMP, empty
      for binding proximity).
* [ ] **Q3 live.** Camera sync mirrors both directions; palette switch
      preserves model-pane camera.
* [x] **Q4.** `computeCongestionVsBasisRank`, `rankDeltaColor`,
      `percentileRank`, and `DELTA_*` gone from `colors.ts`; no refs in
      `web/src/`; curated events retargeted.
* [x] **Backend code.** `/ercot_spp_range` reads `ercot_dam_spp` with
      `DISTINCT ON` DST collapse, 503 on empty; registered in `main.py`.
* [ ] **Backend smoke.** SP counts match `/ercot_state_range` on a
      known window; 503 fires outside ingested data.
* [x] **Diagnostic script.** `lmp_mc_identity.py` computes
      `LMP_b − system_λ − MC_b` per snapshot and reports PASS/FAIL at
      1/5 $/MWh tolerance.
* [ ] **Diagnostic run.** Executed on the sample window, reports PASS.
