# ERCOT Market-Implied Congestion Map & Forecast — Project Design (v3-aligned)

**Supersedes** `ercot_congestion_forecast_project_design.md` (the corridor/synthetic-grid design). This document is self-contained: enough context to start a fresh working session.

**One sentence:** A live, self-grading map and forecast of ERCOT congestion built entirely from public data — a weekly-refit, statistically validated estimate of which transmission constraints move which nodal prices (the implied shift-factor map), a daily forecast of what binds tomorrow and what it does to every settlement point, and a public scoreboard that grades the forecast the next day.

---

## 1. Background & Provenance (context for a fresh session)

- **Origin.** Project began as a synthetic-grid study: DC-OPF (PyPSA/HiGHS) on ACTIVSg2000/Texas2k over ~13,000 hours of 2025–2026, driven by real ERCOT zonal load and regional wind/solar, compared against real DAM outcomes. Price-space comparison measured and found weak: zone-level rank ρ ≈ 0.27 overall; regime-split ρ = 0.69 (high-wind-west) vs **−0.21 with sign inversion (summer peak)**. Synthetic thread is **frozen at a final writeup** — a completed investigation with findings (regime table, fabricated-DFW-bottleneck mechanism, non-clusterability of ERCOT congestion), not an abandoned one.
- **The pivot asset.** The Implied Binding Proximity (IBP) module's intermediate object — the full implied shift-factor matrix — turned out to be more valuable than the metric built on it. In any DC-OPF-cleared market, `congestion[sp,t] = −Σ_c SF[sp,c]·μ[c,t]` exactly. Both sides are public (NP4-190 SPPs, NP4-191 shadow prices); rolling ridge regression recovers SF. Constraint geography is never needed — constraints stay anonymous string keys whose location is revealed by which settlement points respond.
- **Validation status (measured, out-of-sample, 46 weeks, one harness, identical weeks).** Adopted operating point: **window 240d, refit 7d, λ=1, min_binding_hours=25, standardize=True**, ~1,120 SPs. Every μ source below is scored by the same code on the same weeks, with the μ source as the only thing that varies (`compute/mu/score.py`).

| μ source | pooled R² | rank-Spearman | sign-agree | top-decile hit |
| --- | ---: | ---: | ---: | ---: |
| **Oracle (realized μ)** | **0.787** | **0.835** | **0.907** | **0.762** |
| **Model `all` (0088 — SHIPPED)** | **0.355** | **0.681** | **0.849** | **0.610** |
| Model base (μ-model v1, 0085) | 0.222 | 0.548 | 0.787 | 0.523 |
| Climatology | 0.046 | 0.381 | — | 0.455 |
| Persistence (24h) | −0.011 | 0.496 | 0.736 | **0.561** |
| Null | ~0 | n/a (flat) | 0.500 | 0.100 (chance) |

> **The gap between row 1 (oracle) and every forecast row is still the headline.** But 0088 closed part of it: `all` (lagged μ + geography + weather-response) is the first μ forecast to clear both pre-registered bars — top-decile **0.610**, above persistence's 0.561 (existence) and the 0.60 product bar. **The lift is geography + weather-response, not the lagged-μ defect fix that was predicted to carry it** (`+lag` alone +0.002, the null). The model was under-specified in *structural* identity, not short-term memory. **Honest asterisk:** 0.610 is pooled; post-RTC+B `all` = 0.559 clears existence but misses the 0.60 product bar. μ-forecasting remains the open problem; the map (oracle 0.787) is still far above any forecast.

- **⚠ The old validation table (0.746 / 0.235 / 0.173) is retired.** It was measured at the *superseded* operating point (window 60, λ=0.1), by the frozen `experiments/` harness, over 44 different weeks. When R1 moved the operating point, nobody re-measured the baselines — because they were "just baselines." Re-measured honestly, persistence's top-decile is **0.561, not 0.649**, and its pooled R² is **negative**. This killed the project's assumed fallback; see §5.5.

- **Known limits (measured):** (a) in-sample R² 0.986 is identity-inflated — retired as evidence; (b) **coverage gap** — μ-mass on constraints absent from the fit window; ~half is seasonal memory (R2), so a warm-start recovers only 30–50% of it, not all of it; (c) **SF stability** between disjoint windows is dominated by regime rotation, and is **~2× better after RTC+B** (0.49 post vs 0.23 pre) — suggestive, not clean, and worth its own study; (d) **per-constraint signed attribution is not identifiable** under co-binding collinearity, and **grouping does not fix it** (R3 failed: +0.006 stability against the fair control, versus a pre-registered +0.10); (e) **forecast bands under-cover badly** — coverage80 = 0.673 against an 0.800 target, because binding is sampled independently per constraint while constraints actually bind in correlated sets. Same collinearity that killed R3.
- **Baseline inversion finding — and it is what beat us.** Climatology carries magnitude; persistence carries ranking and *the tail*. Persistence wins top-decile, the screener's own metric, and the reason is mechanical: **a line out yesterday is still out today.** Persistence implicitly carries transmission topology state. The covariate model carries none — every covariate it has (load, wind, solar, calendar, outages) is system-wide or zonal, *identical for every constraint in a given hour*. That asymmetry is the whole of §5.6.

---

## 2. Audience Framings (same artifact, three pitches)

| Audience | Framing | What they look at |
|---|---|---|
| Trading desk (CRR/DART) | "A constraint-exposure map and morning congestion screener at nodal granularity, with a public out-of-sample track record — and a benchmark against the market's own implied forecasts." | Node explorer, daily forecast map, scoreboard, market-benchmark page |
| ERCOT / market design / consultancies | "Public-data observability of congestion drivers: coverage vs. rotation diagnostics, outage-anticipated constraint activation, honest uncertainty." | Alert stream, coverage decomposition, methodology notes |
| Interviews | "Built the physics model first, learned the settlement identity from it, recovered the market's sensitivity map from prices, caught my own inflated number, pre-registered the gates, shipped it live." | The repo, the two writeups, the scoreboard |

The narrative arc is itself the pitch: physics model → measured its failure honestly → statistical map validated OOS → live graded product. Statistics for nowcasting the observed grid; physics for counterfactuals (deferred).

---

## 3. Datasets

### Ingested today
| Dataset | Report | Role |
|---|---|---|
| DAM Shadow Prices | NP4-191-CD | μ per binding constraint per hour — the `M` panel. Also carries **`from_station` / `to_station`** (the Leg-A bridge, §5.6) and **`limit_mw`** (an under-used topology observable, below). |
| DAM SPPs | NP4-190-CD | Congestion decomposition (LMP − λ reference) — the `C` panel. |
| DAM System Lambda | NP4-523-CD | Reference-price validation (merit-order λ cross-checks). |
| SP geocoding | NP4-160-SG + EIA-860 fuzzy match | **lat/lon for 1,092 of ~1,120 SPs**, plus `sp_type` and `matched_capacity_mw` — 495 are resource nodes, so *generation units are locatable*. `data/processed/settlement_points_geocoded.csv`. Under-exploited: see §5.6. |
| Load forecast by weather zone; wind/solar regional forecasts; actuals | MIS | μ-model covariates + regime binners. **All zonal or system-wide — the same numbers for every constraint.** |
| Zonal outage aggregate | (NP3-233 family) | `outages_zonal`. Aggregate MW. Same limitation: one number for all constraints. |

### The acquisition list — RESOLVED (the phase this list scoped is over)
| Dataset | Report | Status | Outcome |
|---|---|---|---|
| ~~**RUC weekly**~~ | NP5-753-CD | **DEAD (0087)** | Was "the prize." **Not on our access path:** NP5-753/754 return HTTP 404; NP5-755 (Hourly RUC) archives only to 2026-04-30 (259d short) *and* has no legal vintage (first view of day D arrives 16:00 D-1, 6h after DAM close). No archive depth fixes a timing failure. The whole "new information" thesis died here. |
| ~~RUC daily (DRUC)~~ | NP5-754-CD | **DEAD (0087)** | 404, falls with NP5-753. |
| ~~SCED RT binding~~ | NP6-86-CD | **Not used** | Was to encode persistence's recency explicitly; the RUC arm it belonged to is dead, and lagged μ (0088) covers this legally. |
| Unplanned resource outages | NP1-346-ER | **INGESTED, FLAT (0089)** | Reachable (archive to 2022-12-07), **D-4 snapshot legal to train *and* serve** (50.3% of outaged MW still out on delivery day, posted before close). Crosswalked through \|SF\| into a **per-constraint** exposure, join at **100% of outage MW**. Verdict: real but flat — `out − base` +0.007 R² / +0.012 top-dec (beats the zonal fallback) but `all+out − all` −0.003 / −0.001 (nil over `all`). The *asset* survives, not a lift. |
| ~~60-Day SCED/DAM Disclosures~~ | NP3-965 / NP3-966 | **CEILING DROPPED (0090 removed)** | The generation-channel ceiling this feed would have measured is dropped: 0089 already decided the feed realizably, and neither branch of the ceiling licenses an action (near-zero → kills feeds already parked; large → no realizable capture path). **The static-attribute and §7.4 market-benchmark uses remain open** if the writeups need them. |
| Transmission Outage Scheduler | — | **UNREACHABLE (R4)** | Behind the **MIS Secure Area** (Market Participant certificate, not our API subscription). The RUC-weekly substitute that would have made it unnecessary is itself dead (above), so the transmission-outage covariate stays unbuilt. |
| CRR auction results | Monthly/long-term, public | Not pursued | Second market benchmark / trader overlay — deferred with the product surfaces. |

### Structural notes
- **RTC+B break (2025-12-05):** DAM settlement identity survives (LMP = λ + ΣSF·μ) but virtual AS in DAM may shift μ patterns. Keep pre/post split visible in every pooled statistic and on the scoreboard. Never fit an SF window straddling the cutover without flagging.
- **⚠ Cutoff discipline — the single easiest way to fabricate skill here.** `features.py:history_cutoff(D)` returns **midnight CT on day D** ("all of D-1 is fair game"). That is correct, and it is correct **only because DAM shadow prices for D-1 clear on D-2**, before DAM close for D. It is a fact about *one product's publication schedule.* **RT and RUC do not publish that way.** Reusing `history_cutoff` for an NP6-86 or DRUC panel is a **14-hour lookahead**, and the existing `audit_leakage` would not catch it, because it is built around the DAM vintage logic. Anything published in real time needs **its own cutoff pinned at DAM close (10:00 CT on D-1), with its own two-sided test.** This project has already fabricated skill once this way (the retired 0.986).
- **⚠ Never train on a feature you cannot serve.** A 60-day-lagged column exists for historical rows and *does not exist for tomorrow*. Train on it and you either cannot serve the model at all, or you serve a degraded substitute and eat train/serve skew. Ablations and static attributes only.
- **`limit_mw` — a topology observable we already had, and an honest negative.** It is present on **100% of binding rows**; ~half of constraints have a moving limit (≈4,900 day-over-day jumps >5%), so derates *are* visible. But measured against each constraint's own trailing-28d median rating, a **derated element binds nearly 2× more often at a *lower* mean μ** (18.34 vs 26.43; same in Mar–Jun). The market redispatches around a known derate: it binds often and cheaply rather than blowing out. **This helps head 1, which already works, and does nothing for the tail.** It is also a caution against the intuition the whole outage thesis rests on — though it only sees an element's *own* rating, never an outage *elsewhere*, which is precisely what RUC adds.

---

## 4. The Implied SF Map (the asset)

- **Identity:** `C ≈ −M·SFᵀ` — C = (hours × SPs) congestion panel, M = (hours × constraints) shadow-price panel (zeros when not binding). Ridge per SP, rolling 60d window, weekly refit. Hours with no binding constraints are valid zero observations.
- **Constraint keys:** `strip(ConstraintName)|strip(ContingencyName)` — anonymous strings; geography lives on the geocoded SP side.
- **Identifiability rule:** co-binding constraints within a window form collinear blocks; within-block allocation is arbitrary and flips between refits. **All signed, named claims operate at constraint-GROUP level** (post-grouping, §5.2). `bp = max_c |SF|` legitimately sidesteps the issue (max over a block is stable) and survives as one map layer, demoted from headline.
- **Diagnostics as first-class outputs:** per-SP/per-group fit R², binding-hours support, refit-to-refit stability → propagate into every downstream confidence display.

---

## 5. Sequenced Plan

> **Status, mid-2026: §5.1–§5.6 are all DONE — no open compute items remain.** The five original risks (R1–R5) closed, three by failing; the information-phase risks (R6–R9) all closed too. **RUC died at the probe (R6/0087); the ablation shipped (R8/0088 — `all` clears both bars, lift is geo+wx not lagged μ); the generation channel is realized-flat (R9/0089); the 60-day ceiling is dropped.** What is left is publication. §5.6 below is kept as the record of the phase, annotated with outcomes.

| step | status | outcome |
|---|---|---|
| 5.1 OOS harness + re-sweep (R1) | ✅ | Operating point **moved**: `(60, λ=0.1)` → **`(240, λ=1)`**. Every number measured before this is provisional. |
| 5.2 Collinear grouping (R3) | ❌ **FAILED** | +0.006 stability vs a fair control, against a pre-registered +0.10. Does not ship. Signed per-constraint claims and the node explorer **stay blocked**. |
| 5.3 Coverage decomposition (R2) | ✅ | Qualified no: novel μ-mass is ~half seasonal memory. Warm-start recovers 30–50%, not all. |
| 5.4 μ-model v1 (R5) | ❌ **FAILED** | Model does not beat persistence in the screening currency. Loses top-decile 0.523 vs 0.561. |
| 5.5 The gate | ✅ read | **0085 model: NOT THE PRODUCT** in all three splits; assumed fallback did not exist. **Re-read after 0088: `all` clears both bars pooled.** |
| 5.6 The information phase | ✅ **DONE** | RUC dead (0087); ablation shipped (0088 — `all` 0.610, lift is geo+wx not lagged μ); generation channel realized-flat (0089); 60-day ceiling dropped. No open items. |

### 5.1 Institutionalize OOS evaluation; re-sweep on it
Move the 44-week harness into `diagnostics.py` as a permanent per-refit emission: OOS pooled R², cross-node rank-Spearman, sign-agreement (with $1 deadband), top-decile hit, coverage, disjoint-window SF stability. Re-run the hyperparameter sweep **selecting on OOS metrics** (prior selection was in-sample cosmetics): window ∈ {60,120,240,365}d, λ into its effective range (current 0.1 vs XᵀX diag ≈1440 is effectively OLS), refit ∈ {1,7,14}d. Measure the SF decay curve corr(SF_t, SF_{t+Δ}) for Δ ∈ {7,14,30,60}d. **Goes first: may lift every number and changes inputs to all later decisions.**

### 5.2 Collinear grouping (the corridor concept, reborn as an identifiability fix)
Correlation-cluster μ columns within each window; merge into composite constraint-group keys. **Pass criterion: disjoint-window stability rises materially from 0.468 and within-block allocation stops flipping.** Gates: constraint explorer, all signed per-group claims, error attribution. Groups are the operational unit everywhere below — they are what "corridors" were in the superseded design, discovered from co-binding rather than drawn from geography.

### 5.3 Coverage-gap decomposition & the lifetime constraint library
Decompose the 19% "novel" μ-mass into tiers — do this measurement **early**, it's one query against the extended history:
1. **Seasonal recurrence** (likely largest): constraint absent from the window but present in history → warm-start from last-fitted SF + seasonal binding profile. If ≥60% of novel mass is historical, the blind spot collapses to single digits with no new modeling.
2. **Outage-induced:** unpredictable by name, predictable as an *event* — outage near group X → elevated novel-binding probability → widen bands, fire anticipatory alert. Add intra-week SF incorporation (don't wait for weekly refit + 25h threshold) to shrink week-long blind spots to ~a day.
3. **Genuinely new** (topology/large-load energization): irreducible; flag honestly ("unmodeled constraint active, bands widened").

### 5.4 μ-model v1 (the forecast)
Per constraint group, two heads: **P(bind at h | covariates)** (GBM/logistic) and **E[μ | bind]** (net-load-bucketed conditional climatology → quantile regression later). Covariates: zonal load forecast, regional wind/solar forecasts, net load, calendar, recent binding history, **outage flags near the group** (the addition). Climatology = magnitude backbone; persistence enters as a feature. Cold start per §5.3. Propagate sampled binding sets through the SF map → nodal congestion with P10/P50/P90 bands.

### 5.5 Pre-registered decision gate (two currencies; either bar clears a row)
| outcome | magnitude bar | screening bar |
|---|---|---|
| Forecast product | pooled R² ≥ 0.5 | Spearman ≥ 0.70 **and** sign ≥ 0.85 |
| Screening tool | R² 0.3–0.5 | Spearman 0.60–0.70, top-decile ≥ 0.60 |
| Forecast is not the product | R² < 0.3 | Spearman < 0.60 **and** top-decile ≤ 0.649 |

**The bars above are pre-registered and have never been edited. They stay.** What follows is what happened when they were read.

**Verdict (0085): NOT THE PRODUCT**, in all three splits (pooled, pre- and post-RTC+B). Model 0.222 R² / 0.548 Spearman / 0.787 sign / 0.523 top-decile. **Existence test: FAIL** — it beats persistence on R², Spearman and sign, and *loses top-decile* (0.523 vs 0.561), which is the one measure a screener exists for.

**~~No-lose structure~~ — this was false, and it is the most portable lesson in the document.** The plan asserted for three branches that `persistence · SF` already cleared the screening bar (top-decile 0.649), so a screener would ship even if R5 failed. **That 0.649 was measured at the retired `(60, λ=0.1)` operating point.** When R1 moved the point, the baseline was never re-measured — because it was *a baseline*, the thing you check the model against, not a thing you check. Re-measured in the same harness on the same 46 weeks: **0.561, below the 0.60 bar, with a negative pooled R².**

> **A baseline that is never re-measured when the operating point moves is not a floor. It is a souvenir.** There was no no-lose structure. There was an unaudited number in a safety net. Every comparison number in this document is now produced by one harness, in one loop, on identical weeks, with the μ source as the only thing that varies.

**One rescue was attempted and refuted (0086).** Hypothesis: we lose top-decile because we rank nodes by a *mean* (`P(bind)·E[μ|bind]`) while persistence ranks by a realized extreme — a mean is the wrong statistic for a tail metric. Re-ranking by upper quantiles of the predictive distribution: **flat, then falling** (P75 0.515, P90 0.511, P99 0.472). The harness was first proven able to detect a *planted* quantile effect, so the null is real and not a blind instrument. The cheap explanation is dead; the missing-information story now carries the entire weight.

---

### 5.6 The information phase (DONE — outcomes in the banner)

> **RESOLVED.** The diagnosis below was right about the *disease* and wrong about the *cure*. RUC — the one hoped-for new source — is **dead** (0087: 404 / archive short / no legal vintage). The remaining arms shipped in **0088**: `all` = 0.355 R² / **0.610 top-decile**, the first μ forecast to clear both bars. But attribution **reversed the call** — the lagged-μ "defect fix" is the null (+0.002, below persistence), and **geography (+0.056) + weather-response (+0.073) carry the lift and compound**. So blindness #2 (geography) was the load-bearing one, not blindness #1 (short-lag memory). The generation channel (**0089**, NP1-346) is realized-flat; the 60-day ceiling (0090) is dropped. The bullets below are the plan as written; read them against this outcome.

**The diagnosis, in one line: the model does not know what persistence knows, and it does not know where anything is.**

Two structural blindnesses, both confirmed by reading the code rather than by theorising:

1. **No short-lag magnitude.** Head 2 (`E[μ|bind]`) has bind *incidence* recency (`binds_1d/7d/28d`, `days_since_bind`) and a **28-day average** magnitude (`mean_mu_28d`). It has **no lagged realized μ**. Persistence's entire content is yesterday's μ. So the model is *not* strictly more informed than the baseline it must beat — it is missing precisely the datum that decides the metric it loses. **And that datum is already in the database and already legal at DAM close.** This is a defect, not a research question.
2. **No geography.** Every covariate is zonal or system-wide — *identical for every constraint in a given hour*. The model literally cannot represent "high west-Texas wind stresses *these* corridors," because it does not know which corridor is in the west. Two constraints with identical bind histories in Panhandle and Houston are **the same row** to the GBM. The interaction everyone assumes it is learning is not weak; it is **inexpressible**.

The evidence that this is an *information* problem and not a *tuning* problem: the model recovers a flat **19–32% of the oracle ceiling in every regime**. Uniform under-recovery is the signature of a missing variable. A badly-tuned model fails unevenly. **Do not spend another branch tuning the current feature set.**

**Where the failure concentrates** (and it points at one thing): the top-decile loss is worst in the **lowest net-load hours** (−0.112, losing 23 of 25 weeks) and in **spring** (Apr −0.103, May −0.079, Jun −0.199), and is ~zero from October to February. Low load plus spring is **transmission maintenance season**. *Caveat: with one year of data those two splits are largely the same weeks; the regime split is the stronger signal, the seasonal one is corroborating.*

**The plan, in priority order.** The ordering rule is **"what adds information,"** not "what is cheap":

- **The blocker, first: can we backfill NP5-753 across the 46 backtest weeks?** If ERCOT's API serves only a rolling archive, RUC becomes a forward-only feature we can never validate against the existing harness, and the entire phase changes shape. This is a 20-minute probe and **nothing should start before it lands.**
- **RUC weekly (NP5-753) — the only genuine new information.** The only source that sees an outage *elsewhere* and is anticipatory at DAM close. Mechanism, stated so it can be falsified: *a constraint that appears in tomorrow's RUC-enforced list but has no recent binding history is a new spring outage — exactly the case persistence cannot see and the model cannot represent.* **Caveat: RUC is an incidence signal (no MW, no limit, no price), so it feeds head 1 — the head that already works (AUC 0.895).** Its value reaches the nodal top-decile only through `p × E[μ|bind]`, by putting probability mass on the *right* constraints. **First measurement after ingest, before any modeling: `P(DAM bind | in tomorrow's RUC list)` versus base rate, and the μ distribution conditional on it. If the lift is small, stop.**
- **The defect fixes, in the same branch** (not as a gate — they are *the baseline RUC must beat*, and shipping them separately would make RUC's contribution unattributable): lagged realized μ (1d/7d); constraint geography as the **|SF|-weighted centroid of settlement-point coordinates** — every constraint gets a real lat/lon from the map we already trust, since the station-name join *fails* (only 4.3% of μ-mass matches the geocoded file: those are *plant* names, constraint endpoints are *substations*); per-constraint weather-response vectors.
- **Ablate, or learn nothing.** base / +lagged-μ / +geo / +RUC / all. If the model improves and you cannot say *which* input did it, you will end up believing a feed is load-bearing when it isn't.
- **Then, gated on its own ablation:** the generation channel. Use the 60-day disclosures to build a *perfect-knowledge* generation covariate across all 46 weeks and measure the **ceiling** of what generation data could buy. Near-zero ceiling → kill NP1-346 and NP3-233 without a day of ingest. Large ceiling → permission to spend, not proof.

**Pre-register the bar before any of this runs.** R5 has failed once and one rescue has been refuted. A third attempt without a bar written in advance will find itself reading a 0.56 as a win because it is finally above persistence. Note that **absorbing persistence entirely still does not clear §5.5** — persistence's own top-decile is 0.561, below the 0.60 bar. Beating persistence wins the *existence test*; it does not win the *product*.

---

## 5.5 Possible ERCOT-specific additions

1. A post-RTC+B price-formation study (highest value, most current). You already
   have the pre/post split infrastructure. Turn it into a finding: did the
   December 2025 cutover change binding frequency, μ distributions, constraint
   mix, or the DA congestion pattern? ERCOT is actively validating RTC+B right
   now in mid-2026 — an independent, public-data assessment of how congestion
   behavior shifted is something staff there would genuinely read. Nobody
   outside has published this yet; it's timely in a way that expires.

2. Outage → constraint-activation study, framed operationally. You planned
   outage features for forecasting; reframe the same work as operations
   research: "given a scheduled outage, which constraint groups historically
   activate, with what lag and magnitude?" That's a congestion-management
   planning question, not a trading question — same code, inverted pitch.

3. A data-quality appendix. In building the ingest you've inevitably hit report
   gaps, naming inconsistencies, timestamp quirks across NP4-190/191/523. A
   short, specific catalog of public-data issues (with reproducible examples) is
   the kind of thing that gets forwarded internally. It signals: this person
   makes our data ecosystem better.


The common thread: each takes infrastructure you're building anyway and emits a
findings memo instead of (or alongside) a product feature. ERCOT hires for
people who study the market, not people who trade it — and #1 in particular has
a shelf life, so if you do one, do that one, and it slots naturally into the
writeup track as a third paper.

---
## 6. Product Surfaces (the revisit value)

- **Daily forecast map:** expected nodal congestion, P10/P50/P90 bands from sampled binding sets; graded next day.
- **Scoreboard:** screening metrics lead (rank-Spearman, sign, top-decile); pooled R²/MAE in a diagnostics tab — leading with magnitude would make a working screener read as a failing forecast. Rolling 30/90d windows; pre/post-RTC+B split visible.
- **Node explorer** (post-5.2): click a node → signed exposures to top constraint groups ($/MWh per $ of μ) with fit-confidence; per group → affected-node map. Served from the current refit only; retrospective layers labeled.
- **Two-type alert stream:** *coverage events* (novel constraint entered the binding set — upgraded to anticipatory via outage schedule) vs. *rotation events* (the map moved). Distinct mechanisms, distinct incidence.
- **Miss-attribution page:** snapshot every input (outages known, forecasts used) at prediction time; decompose misses into unforecastable-outage / driver-forecast-bust / model error. Makes the daily grade diagnostic, not just honest.
- **Trader overlay:** join group exposures to Hub/LZ path spreads → "exposure per path" view; CRR auction prices on those paths alongside.
- **Skill-decomposition page:** oracle **0.787** vs *every* realistic μ source ≈0.22 — where the skill lives (μ-forecasting, not the spatial map) is a standalone contribution, and it is now the project's strongest result. It stands regardless of the gate outcome, and it survived the gate *failing*.

---

## 7. Evaluation Framework

- All headline numbers OOS by construction (fit window ends strictly before scored week).
- **Currencies matched to claims:** magnitude (pooled R², MAE) vs screening (rank-Spearman, sign w/ deadband, top-decile hit). Baselines (climatology, persistence, null) reported in both, always.
- **Per-group and per-regime splits** (existing regime binners: summer_peak, winter_peak, high_wind_west, mild_shoulder) + pre/post-RTC+B.
- **Coverage reported alongside skill** every week (it explains collapse weeks; hiding it would misattribute).
- **Ablations — now the centrepiece, not a footnote (§5.6):** base / ± lagged realized μ / ± constraint geography / ± RUC / all. Adding three inputs at once and reading one number is how a team convinces itself an expensive feed is load-bearing when it isn't.
- **Every baseline is re-measured whenever the operating point moves.** Non-negotiable; see §5.5.
- **A flat prediction cannot score.** `topdecile_hit` ranks by `argsort(-pred)`, which breaks ties by *array index* — so an all-zero forecast "identifies" the first k nodes in column order every hour and scored **0.626** against a 0.10 chance rate. `compute/mu/score.py` overrides it to decline flat rows. Any new metric must be checked against the null source before it is trusted.

### 7.4 Market benchmark (the trader-credibility evaluation)
From the 60-day DAM disclosure (PTP obligation bids/awards) and CRR auction clearing prices, construct the market's implied path-level congestion expectations. Score the model against them: did model-expected DA congestion beat market-implied congestion, overall and by regime (esp. post-outage-surprise hours)? Even a null ("market efficient except after outage surprises") is a finding with commercial meaning. This is the evaluation a desk respects more than any statistical baseline.

---

## 8. Writeups (parallel, timeboxed)

1. **Synthetic-thread finale:** regime-conditional performance table (ρ 0.69 wind / −0.21 summer with sign inversion), the fabricated-DFW-bottleneck mechanism, non-clusterability of ERCOT congestion. Framed as the motivation for learning the map from prices: "what fabricated topology gets wrong."
2. **Methodology correction note:** 0.986 → 0.746 — settlement-identity R² inflation, lookahead windows, in-sample sweep selection. The self-audit is the feature.
3. *(Emerges from 5.3)* **Coverage-gap decomposition:** how much of "unpredictable" congestion is seasonal memory, outage-anticipatable, or irreducible.

---

## 9. Kept / Deferred / Dropped

- **Kept with new jobs:** ERCOT ingest + geocoded SP layer; congestion computation & λ estimators; regime binners (→ μ-model covariates); web chassis (two-map UI → forecast map + explorer); IBP core; `bp = max|SF|` as one layer.
- **Deferred (shelved, promised to no one):** market-implied equivalent network — inverting the SF map into a fitted reduced grid (~20-node) to restore what-if studies; blocked behind 5.1–5.2 because it inherits SF stability/identifiability wholesale. If revived: scoped as exploratory. LODF-based cold-start priors wait behind the same gate (need a credible network).
- **Dropped:** synthetic↔real comparison machinery (price-space measured weak; corridor bridge mathematically rescued by group-level signatures but mooted by the freeze); constraint geolocation alias table (IBP proved geography lives on the SP side); corridor-level binding forecaster (absorbed into §5.4's stronger nodal version).
- **OPF/ACTIVSg role:** no runtime role in the product. It is (a) a concluded first-class writeup, (b) the provenance of the KKT/PTDF fluency that produced IBP, (c) the runtime for the deferred equivalent network if it ever unshelves. Resist inventing pipeline roles for it.

---

## 10. Risks & Open Questions

**Live: none — the information phase is closed.** The items that were live here are resolved:
- ~~RUC archive depth~~ — **CLOSED, DEAD (0087):** 404 / archive short / no legal vintage.
- ~~RUC incidence lift~~ — **MOOT:** no RUC feed to condition on. The `limit_mw` precedent (topology change → 2× more binding at *lower* μ) stands as the closest proxy, and it is negative.
- ~~Attribution~~ — **ANSWERED (0088):** ablated; lift is geography + weather-response, not lagged μ.
- **Cutoff discipline for real-time feeds** — *not triggered.* Every shipped covariate (0088, 0089) is backward-only and legal under `history_cutoff`. The rule returns only if a future arm reads a feed posting after 10:00 CT on D-1; `audit_leakage` would not catch its absence, so re-read 0087 first.
- **One year of data.** "Spring" and "low demand" are largely the same weeks. Do not over-read the seasonal story.

**Standing:**
- **λ reference choice** contaminates C (congestion = SPP − reference); merit-order λ validated on 2025 — re-verify post-RTC+B.
- **RT variant** blurring (15-min vs 5-min) — quantify before shipping any RT layer.
- **Identifiability is unsolved, and grouping is not the fix** (R3). Signed per-constraint claims stay blocked. Two honest routes remain, both deferred: ship only claims that survive collinearity (`bp = max|SF|`, unsigned magnitude exposure), or attack it directly (elastic-net / sign-constrained fits, stability-selection over refits).
- **Bands under-cover (0.673 vs 0.800)** and the cause is known: independent-Bernoulli sampling of a correlated binding set. A joint/copula sampler makes them **honest, not skillful** (P50 R² 0.230 ≈ the point forecast's 0.222). Fix it for correctness, and do not book it as a win.
- **Scoreboard integrity:** never change a pre-registered bar after seeing results; version the gates file. **And re-measure every baseline whenever the operating point moves** — that is the lesson of §5.5, and it is not optional.

## 11. Critical Path

**All of §5.1–§5.6 is done. No open compute items remain.** The critical path, as it resolved:

```
RUC archive probe ──► DEAD (0087: 404 / archive short / no legal vintage)
§5.6 branch (lagged-μ + geo + wx, ablated, minus RUC) ──► SHIPPED (0088)
     └─ `all` = 0.355 R² / 0.610 top-dec: clears both bars, first μ source to ship.
        Attribution reversed — lift is geo+wx (+0.056/+0.073), not lagged μ (+0.002, null).
        Post-RTC+B `all` = 0.559 misses the product bar (clears existence).
generation channel (NP1-346, 0089) ──► REALIZED, FLAT (asset survives, no lift)
     └─ 60-day ceiling (0090) ──► DROPPED (no action hangs on either branch)
```

The forecast now beats persistence *and* clears the product bar pooled — two different questions, both answered. What remains is publication, not modeling.

**Parallel and independent of the above** — worth doing regardless of how §5.6 lands, because each is a finding rather than a feature:
- **The skill-decomposition result** (oracle 0.787 vs every real forecast ≈0.22) is publishable *now* and stands whatever happens next. The map is solved; μ-forecasting is not. That is the contribution.
- **The RTC+B stability finding** (disjoint SF stability ~2× higher post-cutover) — has a shelf life, per §5.5 item 1.
- **Writeups 8.1 / 8.2.**
