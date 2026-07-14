# 0089 - generation-outage-arm

Type: feat
Branch: feat/0089-generation-outage-arm

**Companion to** `plan/version3-implementation-plan.md` §S6 (S6e, R9).
**Predecessor:** `plan/0088-mu-panel-and-ablation.md` — the panel and the harness this
arm plugs into.
**Sibling (demoted):** `plan/0090-generation-channel-ceiling.md` — the 60-day-disclosure
*ceiling* probe, which existed to decide whether NP1-346 was worth building. **NP1-346
is directly reachable and shippable, so that decision is now made by measuring the
realizable lift here, not a ceiling there.** 0090 survives only as optional context
(realizable ≤ ceiling).

## Goal

* Ingest **NP1-346-ER (Unplanned Resource Outages)** across the backtest and build a
  **per-constraint outaged-generation exposure** covariate, via the |SF| crosswalk.
* Add it to the 0088 panel as an ablation arm (`out_*`) and score it through the
  **unchanged** harness against `lag`/`geo`/`wx` and against the **zonal fallback we
  already have**.
* State a **build-or-kill** verdict: does per-constraint outage exposure beat the
  zonal aggregate as *lift* — or does it degrade to the fallback R4 already left us?

## Context

* **The probe is already done, and it is in the tree.** `compute/mu/outage_probe.py`
  (read-only, ingests nothing) ran all five legs to completion. This plan is what to
  build *given* the probe, and the probe is committed as the evidence, exactly as
  `ruc_probe.py` was for `0087`.
* **This is the covariate R4 wanted and could not build.** R4 closed to the **zonal
  fallback**: `features.outage_panel` hands the model **four numbers identical for
  every constraint in a given hour**. That sameness *is* 0085 §5.6's diagnosis of why
  persistence beat us — the model cannot tell two constraints apart, so it cannot know
  *which* one binds. NP1-346 is **unit-level**, so with the |SF| crosswalk it becomes
  genuinely per-constraint.
* **It clears the two gates RUC died on** (`0087`):
  * **Gate A (depth): PASS.** Archive reaches **2022-12-07** — 735 days before panel
    start, 99.8% daily density over the backtest.
  * **Gate B (timing): PASS — and this is the one that matters.** RUC failed because no
    run before DAM close ever described day D. NP1-346 does: it is posted ~05:00 (before
    the 10:00 close), and **50.3% of outaged MW carries a `Planned End Date` past the
    delivery day** — i.e. is *expected still out* on D. That is genuine forward
    information, published in time.
* **Unlike the 60-day disclosures (0090), this is SHIPPABLE.** The report is a
  **D-4 snapshot** (a snapshot of outages active on the third day before posting).
  Backward-only ⇒ **legal under the existing `history_cutoff`**, legal to **train
  *and* serve**. No `realtime_cutoff` (re-read `0087` before ever adding one). The
  ablation-only / never-serve rule that governs 0090 **does not apply here.**
* **The open gate — the join (Gate C) — is the likely killer, and it is unresolved.**
  Exact `Resource Unit Code` → settlement point is only **22.6% of outage MW**, *below*
  the 30% floor. A station-prefix heuristic reaches 55.8%, but **that is exactly the
  fuzzy matching R4 warns against** (it derives station `B` from `B_DAVIS_B_DAVIG1`, and
  117 rows sit on stations mapping to several settlement points). **An authoritative
  crosswalk is commit 1, and it gates everything after it.**
* **These are GENERATION outages, not transmission.** It does **not** reopen R4 (which
  was about outaged *transmission elements* → constraint keys), and it does **not**
  observe the "a line out yesterday is still out today" mechanism behind persistence's
  win. Do not let this arm be described as the transmission-outage covariate.
* **The signal screen is weak but real.** Leg D: per-constraint outage exposure vs
  realized |μ|, **cross-sectional rank-ρ mean +0.075, positive on 96% of days.** A
  zonal aggregate scores **exactly 0** here by construction. Weak, and it is a *screen*,
  not a lift number — but it is information R4 concluded we did not have.

## Approach

* Work in: `compute/mu/` (crosswalk + covariate), plus ingest (`migrations/`, loaders)
  **only after commit 1 passes its gate**. The order is R4's lesson: prove the join
  before paying for the backfill.
* **Reuse `compute/mu/geo.py`'s crosswalk discipline.** Locating outaged MW in the SF
  map is the *same operation* as locating a constraint's centroid — `Σ_sp |SF[c,sp]| ·
  x[sp]` — and it carries the **same leak trap**: the `SF` must come from the honest
  per-week refit, never a global fit. `geo_panel` already refuses a global `SF` by
  construction; the outage exposure builds on that, it does not re-solve it.
* **Reuse `compute/mu/score.py` and `compute/mu/propagate.py` as-is.** The harness is
  the control variable. 0089 does not get to write a second one any more than 0088 did.

### Commit 1 — The authoritative crosswalk. Before any ingest.

The probe's 55.8% leans on a heuristic; this replaces it with a real map or kills the
arm.

* Build `resource → settlement_point` from an **authoritative** ERCOT source (the
  `RESOURCE_NODE` registry in `data/raw/ercot_geocode/Settlement_Points_*.csv`, and/or
  the `ResDMEList` NP3-988 registry the report itself references), not by splitting
  underscores.
* Report coverage **by outage MW, never by row count** (key count flatters — see 0088).
* **Decision, pre-registered (R4's bar, restated):**
  * **≥60% of outage MW cleanly locatable → BUILD** the per-constraint covariate.
  * **30–60% → build it, flagged, on the joinable subset only** — and report the
    unlocated MW every week, so the hole is visible rather than absorbed.
  * **<30% → the arm is DEAD.** It degrades to `outages_zonal`, which we already have,
    and this branch closes with that verdict and no ingest — the `0087` pattern.

### Commit 2 — Ingest NP1-346. Only if commit 1 cleared its gate.

* Migration + loader + backfill over the archive (`2024-12-11 → present`, panel range).
* **The payload is a zip wrapping an xlsx**, data on sheet 2 (`Unplanned Resource
  Outages`), header on row 5. Columns **verbatim from the wire** (dumped in the probe,
  not remembered — `0087`'s schema was wrong in five fields): `Resource Name`,
  `Resource Unit Code`, `Fuel Type`, `Outage Type`, `Available MW Maximum`,
  `Available MW During Outage`, `Effective MW Reduction Due to Outage`,
  `Actual Outage Start`, `Planned End Date`, `Actual End Date`, `Nature Of Work`.
* Store per `(posted_date, resource_unit_code)` with `effective_mw_reduction`,
  `actual_outage_start`, `planned_end_date`. `posted_date` **is the vintage** — the
  snapshot describes `posted_date − 3`.

### Commit 3 — The per-constraint outage-exposure covariate

* `out_exposure` per `(delivery_day, constraint)` = `Σ_sp |SF[constraint, sp]| ·
  outage_MW_expected_at_D[sp]`, from the **honest per-week SF refit** (`geo.geo_panel`
  pattern).
* **Two flavours, and the second is the point:**
  * `out_exposure_now` — MW out in the newest snapshot admissible at DAM close (D-4).
  * `out_exposure_planned` — MW whose **`Planned End Date` ≥ D**, i.e. *expected still
    out on the delivery day*. This is the forward-looking content Gate B found, and the
    thing RUC could not provide.
* Optionally split by fuel (`out_exposure_gas`, `out_exposure_wind`, …) — congestion
  responds differently to a thermal trip than a wind derate — but only if commit 1's
  coverage supports it per-fuel.

> ⚠ **LEAK TRAP — identical to 0088 commit 3.** `|SF|` for delivery day D must come
> from the trailing window that closed on or before D, and the outage snapshot must be
> the D-4 vintage, never a later one. A global SF or a fresher snapshot leaks the
> future and **it will look like a result.** Assert both.

### Commit 4 — The ablation (marginal to 0088)

* **0088's five arms are pre-registered and frozen** (`plan/s6-gate.md`); this arm was
  not among them, so it is **not** retro-added there. Instead measure its **marginal**
  value on the same panel and harness: `base` / `all` (0088's) / `out` alone /
  `all+out`, plus **the zonal fallback as an explicit row** — the thing `out` must beat
  to justify itself.
* Score through **`compute/mu/score.py`, unchanged**, same weeks, same map, same
  `(240, 7, λ=1)`. Report both pre-registered bars and pre/post RTC+B.

### Commit 5 — Verdict

* `plan/0089-summary.md`, house style of `plan/0085-summary.md`, verdict filled in
  either way. **If per-constraint outage exposure does not beat the zonal aggregate as
  lift, say so plainly** — that degrades the arm to the fallback R4 already gave us, and
  it is a clean, honest kill, not a failure to hide.

### Do NOT touch

* `compute/mu/score.py`, `compute/mu/propagate.py` — the harness is the control.
* `plan/s6-gate.md` and 0088's five arms — pre-registered, not edited here.
* The R4 transmission-outage story — this arm is **generation**, and conflating them
  re-opens a question this does not answer.
* RUC, in any form.

## Acceptance

* [ ] Probe committed and run **before** any migration or loader (`compute/mu/outage_probe.py`,
      already in tree); Gates A/B/C and the Leg-D screen recorded either way.
* [ ] Commit 1 crosswalk coverage reported as a fraction of **outage MW**, not row
      count; the build/flag/kill decision recorded against the pre-registered bar.
* [ ] If coverage <30%: branch closes with the verdict, **no rows ingested**.
* [ ] A test asserts the covariate for delivery day D reads **only** snapshots posted
      at or before `dam_close(D)` (the D-4 rule) and **never** a later vintage.
* [ ] A test asserts the `|SF|` used for week *w*'s exposure was fit on a window
      **ending at or before** week *w*'s refit start (the 0088 leak trap).
* [ ] A test asserts the exposure is **per-constraint** — two constraints on the same
      day receive **different** values (the whole point; the zonal fallback cannot).
* [ ] `out_exposure_planned` uses `Planned End Date` and a test confirms it reflects MW
      **expected still out on D**, not merely MW out in the snapshot.
* [ ] One ablation table: `out` and `all+out` against **the zonal fallback** and 0088's
      arms, both bars printed, pooled and pre/post RTC+B.
* [ ] Verdict stated plainly: does per-constraint outage exposure beat the zonal
      aggregate as lift? `plan/0089-summary.md` exists with it filled in.

**Effort:** commit 1 S · commit 2 M (ingest + backfill) · commit 3 M · commit 4 S ·
commit 5 S.
**Retires:** R9 — but *realizably*, not as a ceiling: this measures what a shippable
3-day-lagged public feed actually delivers, which is the number 0090's ceiling was only
ever an upper bound on.
