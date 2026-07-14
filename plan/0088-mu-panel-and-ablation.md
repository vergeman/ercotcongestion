# 0088 - mu-panel-and-ablation

Type: feat
Branch: feat/0088-mu-panel-and-ablation

**Companion to** `plan/version3-implementation-plan.md` §S6 (S6b, S6d).
**Predecessor:** `plan/0087-ruc-probe-and-ingest.md` — CLOSED, both gates failed.
**Sibling (parallel, independent branch):** `plan/0089-generation-channel-ceiling.md`.

## Goal

* Pre-register the sprint's two bars in `plan/s6-gate.md` **before any number exists**.
* Add every covariate the μ-model is missing — **lagged realized μ**, **constraint
  geography**, **per-constraint weather-response vectors** — in **one branch, one panel**.
* Run a **single ablation** (`base` / `+lag` / `+geo` / `+wx` / `all`) through the
  **unmodified** 0085 harness, so the μ source is the only thing that varies.
* Report every arm against **persistence** and **oracle** in one table, pooled and
  pre/post RTC+B, and **state per-arm attribution** — including a null result.

## Context

* **RUC is dead (0087) and it is not coming back.** NP5-753/754 are 404; NP5-755's
  archive is 259 days short; and no HRUC run at or before DAM close publishes a single
  row for delivery day D. It is a **timing** failure, not a **history** failure — a
  deeper archive fixes nothing. **Do not spend a day on an archive workaround.**
* **The "new information" thesis is therefore dead.** Everything here is a
  *reorganisation of data we already hold*. That is a weaker hand; the plan says so
  rather than pretending otherwise. It also means **nothing is left to absorb the
  credit** — if the cheap arms fail, there is no comfortable story to retreat into.
* **The map is solved; the forecast is not.** Oracle μ scores **0.787** pooled R²; every
  realistic forecast lands near **0.22**. The oracle-vs-forecast gap *is* the story.
* **The mean-vs-tail rescue is refuted (0086) — do not re-attempt it.** Re-ranking by
  upper predictive quantiles is flat, then falling (mean 0.516 → P75 0.515 → P90 0.511 →
  P99 0.472), and the harness was first proven able to detect a *planted* quantile
  effect, so the null is real. **Mechanism:** predictive spread comes from one *global*
  residual pool, so it scales with the level — the quantiles are nearly a monotone
  transform of the mean and **cannot reorder anything.** Winning a top-decile requires
  knowing **which nodes are spiky, node by node**. Commits 3 and 4 exist substantially to
  supply that per-constraint identity.
* **The station-name join FAILS — do not spend a day on fuzzy matching.** Only **4.3% of
  binding μ-mass** has a `from_station`/`to_station` matching
  `data/processed/settlement_points_geocoded.csv`: those are **plant** names, constraint
  endpoints are **transmission substations**. Different namespaces. The route that works
  is the **|SF|-weighted centroid** (commit 3).
* **Bands under-cover (0.673 vs 0.800).** Cause known: independent-Bernoulli sampling of
  a correlated binding set. A joint/copula sampler makes them **honest, not skillful**
  (P50 R² 0.230 ≈ point forecast 0.222). **Out of scope here**; if you fix it, book it as
  correctness, never as a win.

## Approach

**The rule for this branch: one branch, one panel, one harness, one ablation.** All arms
land together — shipping them apart makes each one's contribution unattributable.

**Reuse `compute/mu/score.py` and `compute/mu/propagate.py` as-is.** Do not write a second
scoring harness. The *whole reason* 0085's numbers are trustable is that there is exactly
one.

### Panel design — build once, ablate by column mask

**The single most important engineering decision in this sprint.** Do **not** rebuild the
panel per arm: `build_panel` (`compute/mu/features.py:397`) materialises ~10M rows and is
the peak-memory line of the package. Build it **once**, with every column; express each arm
as a **subset of feature columns**.

* Make `compute/mu/mu_model.py::feature_cols` (`mu_model.py:64`) arm-aware: a `--features`
  selector filtering by column-name prefix (`lag_*`, `geo_*`, `wx_*`).
* **Missing covariates stay NaN. Do not fill them.** Already the panel's law
  (`features.py:411`) and it holds for every new column here. The gradient boosters take
  NaN natively — **let them see the hole.** Filling one invents a covariate value the
  market never saw: the same class of error as a lookahead.
* **No `realtime_cutoff` is needed.** It existed for the RUC/RT feeds that do not publish
  on the DAM's schedule. **Every covariate here is backward-only and legal under the
  existing `history_cutoff`.** If a future arm ever reads a feed posting after 10:00 CT on
  D-1, that rule comes back — and `audit_leakage` (`features.py:471`) is built around DAM
  vintage logic and would **not** catch its absence. Re-read `0087` first.

### Commit 1 — Pre-register the bar. Before any number exists.

`plan/s6-gate.md`, versioned, **never edited post-hoc** (handoff §10). This is the *last*
cheap shot at R5's failure — exactly the condition under which a marginal number gets
talked into being a win.

Fix, in advance:
1. **The §5.5 product bar**, restated unchanged: **top-decile ≥ 0.60**.
2. **The existence bar:** beat **persistence** (0.496 R² / 0.736 rank-ρ / **0.561**
   top-decile).
3. **The distinction R5 blurred:** *beating persistence wins the existence test; it does
   not ship a product.* **Persistence's own top-decile is 0.561 — below the 0.60 bar.** A
   model that absorbs persistence entirely and adds nothing **still fails §5.5.** **Two
   bars. Both written down. Neither substitutes for the other.**

### Commit 2 — Lagged realized μ. A defect fix, not a feature.

`binding_history` (`features.py:306`) emits `binds_1d/7d/28d`, `bind_rate_life`,
`days_since_bind`, and **`mean_mu_28d`** — bind *incidence* recency plus a 28-day mean
magnitude, and **no short-lag magnitude at all**. **Persistence's entire content is
yesterday's μ, so the μ-model is not strictly more informed than the baseline it must
beat.** That is a defect, it may be a large part of why R5 failed, and it is free — the
data is already in `M`.

* In `compute/mu/features.py::binding_history`, add per constraint: `lag_mu_1d`,
  `lag_mu_7d`, `lag_max_mu_1d`, `lag_max_mu_7d`.
* **No new cutoff.** Legal at DAM close under the existing `history_cutoff` — D-1's shadow
  prices clear on D-2. The one place the DAM publication quirk works *in our favour*.

> **With RUC dead, this is the sprint's most likely source of lift** — and if it closes
> most of the gap alone, then 0086's "missing outage data is the whole story" was
> overstated. That is a finding, and the ablation is what makes it legible.

### Commit 3 — Constraint geography, via the |SF| centroid

`geo_centroid(SF) → (lat, lon)` per constraint = the **|SF|-weighted centroid** of
settlement-point coordinates from `data/processed/settlement_points_geocoded.csv` (1,092 of
~1,120 SPs carry lat/lon). Derive: distance to each wind region, distance to each solar
region, distance to each load zone, and kV where available.

> ⚠ **LEAK TRAP — the one that will look like a win.** The `SF` must come from the
> **honest trailing window the map is fit on for that week** — never a global fit. A global
> SF leaks the future into the geography, **and it will not look like a bug. It will look
> like a result.** Draw the SF per scored week from the same refit the scoring harness uses
> (`compute/sf/rolling.py`), and assert it.

> ⚠ **Do not attempt the station-name join.** 4.3% of μ-mass. See Context.

### Commit 4 — Per-constraint weather-response vectors

Over the trailing window, correlate each constraint's μ against each zonal load forecast
and each regional wind/solar forecast. Each constraint gets a learned sensitivity vector:
`wx_corr_load_<zone>`, `wx_corr_wind_<region>`, `wx_corr_solar_<region>`.

**This is the geography tag expressed directly in the currency the model needs, and it
requires no crosswalk at all** — no geocoding, no station names, no centroid.
Backward-only over the trailing window ⇒ **legal by construction.** It is also the most
direct attack on 0086: a per-constraint sensitivity vector is exactly the "which
constraints are spiky, and under what conditions" identity the model lacks — and lacking it
is *why* the quantile rescue had nothing to reorder.

### Commit 5 — The ablation

* Run `mu_model.py` once per arm: `base` / `+lag` / `+geo` / `+wx` / `all`.
* Score each through **`compute/mu/score.py`, unchanged** — same weeks, same map, same
  harness, same `(240, 7, λ=1)` operating point.
* Report per arm, against **persistence** and **oracle** in the same table: pooled R²,
  cross-node rank-Spearman, sign-agree, **top-decile hit**, coverage80. Pooled **and**
  pre/post RTC+B (2025-12-05).

Read the table against `plan/s6-gate.md`, and read **both** bars:
* **Existence test:** does any arm beat **persistence** (0.496 / 0.736 / **0.561**)?
* **Product test (§5.5):** does any arm clear **top-decile ≥ 0.60**?

**These are different questions and R5 blurred them.** An arm can win the existence test,
absorb persistence entirely, and **still not ship a product.** Say which test was passed.
**Do not let a 0.56 read as a win because it is finally above persistence.**

### Commit 6 — Verdict

`plan/0088-summary.md`, in the house style of `plan/0085-summary.md` — written for someone
who was not here. **The verdict section is filled in either way.** Four first-generation
risks have now closed by *failing* (R4, R5, R6, R7), and the project is in good shape
*because* they were recorded honestly rather than softened.

### Do NOT touch

* `compute/mu/score.py`, `compute/mu/propagate.py` — the harness is the control variable.
* The band sampler / coverage fix — out of scope (see Context).
* RUC ingest, in any form.
* Grouping and signed per-constraint claims — still blocked by R3.

## Acceptance

* [ ] `plan/s6-gate.md` committed **before commit 5 produces a single number**; never
      edited post-hoc.
* [ ] `lag_mu_1d`, `lag_mu_7d`, `lag_max_mu_1d`, `lag_max_mu_7d` exist;
      `audit_leakage` reports `min_slack_h ≥ 0`.
* [ ] A test asserts `lag_mu_1d` for delivery day D equals realized μ on D-1 and **never**
      reads day D.
* [ ] Centroid coverage reported as a fraction of **binding μ-mass**, not of key count.
      (Key count flatters; μ-mass is what the score is made of.)
* [ ] A test asserts the SF used for week *w*'s geography was fit on a window **ending at
      or before** week *w*'s refit start.
* [ ] Weather trailing window is the same length as the map's fit window; a test asserts
      the correlation window ends before `history_cutoff(D)`.
* [ ] The panel is built **once**; arms are selected by `--features` column-name prefix,
      and no arm refills a NaN.
* [ ] One table: all arms, both baselines, the pre-registered bars printed alongside;
      pooled and pre/post RTC+B.
* [ ] **Attribution stated per arm.** Which input worked? **If the answer is "lagged μ, and
      the rest added nothing," say that plainly** — it is the most valuable outcome this
      sprint can produce, and the one there is most institutional pressure to soften.
* [ ] `plan/0088-summary.md` exists with a verdict filled in, whichever way it went.

## Standing constraints

* **Identifiability is unsolved and grouping is not the fix (R3).** Signed per-constraint
  claims stay blocked; the μ-model heads are **per constraint** and the node explorer stays
  blocked.
* **RTC+B split (2025-12-05):** never fit an SF window straddling the cutover without
  flagging; keep pre/post visible in **all** pooled stats.
* **Re-measure every baseline whenever the operating point moves.** *A baseline that is
  never re-measured when the operating point moves is not a floor, it is a souvenir* — the
  0.649 that made R5 look like a no-lose bet was exactly that.

**Effort:** commit 1 XS · commits 2–4 M · commit 5 S · commit 6 S.
**Retires:** R8; delivers the §5.5 gate read.
