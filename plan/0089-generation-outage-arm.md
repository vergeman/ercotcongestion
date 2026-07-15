# 0089 - generation-outage-arm

Type: feat
Branch: feat/0089-generation-outage-arm

**Companion to** `plan/version3-implementation-plan.md` §S6 (S6e, R9).
**Predecessor:** `plan/0088-mu-panel-and-ablation.md` — the panel and harness this arm plugs into.
**Sibling (demoted):** `plan/0090-generation-channel-ceiling.md` — the 60-day-disclosure *ceiling* probe. NP1-346 is directly reachable and shippable, so the build decision is made by the realizable lift here, not a ceiling there. 0090 survives only as optional context (realizable ≤ ceiling).

## Goal

Ingest **NP1-346-ER (Unplanned Resource Outages)** across the backtest, build a **per-constraint outaged-generation exposure** covariate via the |SF| crosswalk, add it to the 0088 panel as an ablation arm, and score it through the **unchanged** harness against `lag`/`geo`/`wx` and the **zonal fallback we already have**. Verdict, build-or-kill: does per-constraint outage exposure beat the zonal aggregate as *lift*, or degrade to the fallback R4 already left us?

## Context

* **The probe is done and in the tree** (`compute/mu/outage_probe.py`, read-only). This plan is what to build given it — the `ruc_probe.py`/`0087` pattern.
* **This is the covariate R4 wanted and couldn't build.** R4 closed to the zonal fallback: `features.outage_panel` hands the model four numbers identical for every constraint in an hour — 0085 §5.6's diagnosis of why persistence beat us. NP1-346 is unit-level, so the |SF| crosswalk makes it genuinely per-constraint.
* **It clears the two gates RUC died on** (`0087`):
  * **Gate A (depth): PASS.** Archive reaches 2022-12-07, 99.8% daily density over the backtest.
  * **Gate B (timing): PASS — the one that matters.** Posted ~05:00 CT (before the 10:00 DAM close), and 50.3% of outaged MW carries a `Planned End Date` past the delivery day — forward information published in time.
* **SHIPPABLE, unlike the 60-day disclosures (0090).** A **D-4 snapshot** (outages active on the third day before posting), backward-only ⇒ legal under the existing `history_cutoff` to train *and* serve. No `realtime_cutoff`. The ablation-only rule that governs 0090 does not apply.
* **These are GENERATION outages, not transmission.** Does not reopen R4 (outaged transmission elements → constraint keys) and does not observe the "line out yesterday still out today" mechanism behind persistence's win.

## Approach

* Work in `compute/mu/` (crosswalk + covariate); ingest (`migrations/`, loaders) **only after commit 1 passes its gate** — R4's lesson: prove the join before paying for the backfill.
* **Reuse `compute/mu/geo.py`'s crosswalk discipline.** Locating outaged MW is the same `Σ_sp |SF[c,sp]| · x[sp]` operation as a constraint centroid, with the same leak trap: `SF` from the honest per-week refit, never a global fit.
* **Reuse `compute/mu/score.py` and `compute/mu/propagate.py` as-is** — the harness is the control variable.

### Commit 1 — Authoritative crosswalk. Before any ingest.

Replace the probe's 55.8% station-prefix heuristic (the fuzzy matching R4 warns against) with a real map or kill the arm. Build `resource → settlement_point` from ERCOT's authoritative registries (`RESOURCE_NODE` in `Settlement_Points_*.csv`; the `ResDMEList` NP3-988 registry), strict precedence (unit code → resource-name → substation), refusing to place a unit an ambiguous substation cannot pin. Report coverage **by outage MW, never row count**.

Decision, pre-registered (R4's bar): **≥60% MW → BUILD** · **30–60% → build flagged, joinable subset only, unlocated MW reported weekly** · **<30% → DEAD**, degrade to `outages_zonal`, close with no ingest.

### Commit 2 — Ingest NP1-346. Only if commit 1 cleared.

Migration + loader + backfill over the archive (`2024-12-11 → present`).
* **An ARCHIVE product, not a JSON `/np*-cd/` endpoint** — document index + per-document binary downloads — so it does not fit `backfill.py`'s `ENDPOINTS`/`client.get` machinery and gets its own driver, launchable as a Job like `backfill_dam_close.py`:
  * `ErcotClient.archive_index(product)` / `download_archive(product, doc_id)` — reusable archive transport (paged index; raw-bytes download).
  * `ercot_ingest/outage_parse.py` — `parse_report` (zip→xlsx) and the pure, unit-tested `to_records(df, posted_date)`.
  * `ercot_ingest/loaders.py::load_resource_outages` — beside `load_outages`, delegating to `to_records`.
  * `ercot_ingest/backfill_outages.py` (`--start/--end/--resume`) + `ops/deploy/jobs/backfill_outages_job.yml`.
* **Payload:** zip wrapping an xlsx, data on sheet 2 (`Unplanned Resource Outages`), header row 5. `parse_report` asserts the wire columns so drift fails loud (`0087`'s schema was wrong in five fields): `Resource Name`, `Resource Unit Code`, `Fuel Type`, `Outage Type`, `Available MW Maximum`, `Available MW During Outage`, `Effective MW Reduction Due to Outage`, `Actual Outage Start`, `Planned End Date`, `Actual End Date`, `Nature Of Work`. Store `effective_mw_reduction`, `actual_outage_start`, `planned_end_date`; `posted_date` **is the vintage** (describes `posted_date − 3`).
* **Key (from the wire):** `(posted_date, resource_unit_code, actual_outage_start)`, **not** the pair — unit codes repeat within a snapshot (`FRNYPP_ST10` ×7 on 2026-07-14), each with its own start; keying on the code alone silently drops ~20% of rows. Migration 27 keys the triple.
* **Recurring ingest, folded into the one existing cron.** `live_updater.py` calls a **self-throttling** `backfill_outages.update_recent()` on every 15-min `ercot-ingest` cycle: it returns immediately outside a UTC refresh window (~12:00–16:00) and after one cheap `ingest_log` lookup once today's snapshot is in — so the archive is hit ~once/day. No separate CronJob.

### Commit 3 — Per-constraint outage-exposure covariate

`out_exposure[D, constraint] = Σ_sp |SF[constraint, sp]| · outage_MW_expected_at_D[sp]`, from the honest per-week SF refit (`geo.geo_panel` pattern). Two flavours:
* `out_exposure_now` — MW out in the newest snapshot admissible at DAM close (D-4).
* `out_exposure_planned` — MW whose `Planned End Date ≥ D`, i.e. *expected still out on D*. The forward-looking content Gate B found.

Optional fuel split (`_gas`, `_wind`, …) only if commit 1's coverage supports it per-fuel.

> ⚠ **LEAK TRAP — identical to 0088 commit 3.** `|SF|` for day D must come from the window closing on or before D, and the snapshot must be the D-4 vintage, never later. A global SF or a fresher snapshot leaks the future and **will look like a result.** Assert both.

### Commit 4 — The ablation (marginal to 0088)

0088's five arms are frozen (`plan/s6-gate.md`); this arm was not among them, so measure its **marginal** value on the same panel/harness: `base` / `all` / `out` / `all+out`, with the **zonal fallback as an explicit row** — the thing `out` must beat. Score through `compute/mu/score.py` unchanged, same weeks/map/`(240, 7, λ=1)`, both bars, pre/post RTC+B.

### Commit 5 — Verdict

`plan/0089-summary.md`, house style of `plan/0085-summary.md`, filled either way. If per-constraint exposure does not beat the zonal aggregate as lift, say so plainly — a clean, honest kill, not a failure to hide.

### Do NOT touch

* `compute/mu/score.py`, `compute/mu/propagate.py` — the harness is the control.
* `plan/s6-gate.md` and 0088's five arms — pre-registered.
* The R4 transmission-outage story — this arm is **generation**.
* RUC, in any form.

## Acceptance

* [x] Probe committed and run before any migration/loader; Gates A/B/C and the Leg-D screen recorded.
* [x] **Commit 1 crosswalk: 100% of outage MW located on the sampled snapshots (by MW, not rows) → BUILD**, well past the 60% bar.
* [x] Ingest keys on `(posted_date, resource_unit_code, actual_outage_start)`; a test confirms a repeated unit code within a snapshot yields distinct records.
* [x] Recurring ingest: `live_updater` calls the self-throttling `update_recent()` on the 15-min cron (~once/day).
* [x] A test asserts the covariate for day D reads only snapshots posted at or before `dam_close(D)` (the D-4 rule), never later.
* [x] A test asserts week *w*'s `|SF|` was fit on a window ending at or before *w*'s refit start (0088 leak trap).
* [x] A test asserts the exposure is per-constraint — two constraints on the same day get different values.
* [x] `out_exposure_planned` uses `Planned End Date`; a test confirms it reflects MW expected still out on D.
* [x] One ablation table: `out`/`all+out` vs the zonal fallback and 0088's arms, both bars, pooled and pre/post RTC+B → `compute/runs/outage_ablation.csv`.
* [x] **Verdict filled** (`plan/0089-summary.md`): the arm is real but flat. `out − base` = +0.007 R² / +0.012 top-decile (positive — per-constraint beats the zonal aggregate, sign-consistent across both RTC+B halves); `all+out − all` = −0.003 R² / −0.001 top-decile (nil — redundant with `all`). `out` (top-decile 0.535) clears neither the existence (0.561) nor product (0.60) bar; `all`/`all+out` clear both. Value kept is the *asset* (reachable, located, leak-safe feed), not a lift.

**Effort:** commit 1 S · commit 2 M · commit 3 M · commit 4 S · commit 5 S.
**Retires:** R9 — realizably, not as a ceiling: measures what a shippable 3-day-lagged public feed actually delivers, the number 0090's ceiling only upper-bounded.
