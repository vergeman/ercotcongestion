# Serving & Display Design — the μ-forecast as a visible predictive layer

**Companion to** `../handoff-ercot_implied_sf_project_design.md` (what/why, plan of
record) and `../version3-implementation-plan.md` (the *modeling* pipeline, S0–S6,
now complete). Those describe how the model was *built and validated*. This document
is about a different phase: **turning the finished model into something served and
displayed.** No new modeling; the science is frozen. The question here is product.

**One sentence:** repoint the existing two-map web chassis and FastAPI from the
retired synthetic-grid artifacts onto the real assets — the implied SF map, the
geocoded settlement points, and the daily μ-forecast — so the site shows a
predictive congestion map that grades itself the next day.

---

## 1. Ground truth: what serves today, and what it must become

### Serving today (all legacy — to be retired, not extended)
The live API (`api/`) and web app (`web/`) are wired to `v1-annual-2`, the
**synthetic-grid / clustering** run. Concretely:

- `/topology` serves ACTIVSg2000 synthetic **buses + lines** (left pane) plus ERCOT
  settlement points (right pane). We are no longer using the synthetic grid.
- `/ibp/ercot[_range]` serves `bp = max_c |SF|` per SP — the demoted "binding
  proximity" layer, from `v1-annual-2/ibp/bp_ercot.npz`.
- `/ercot_state`, `/ercot_spp_range` serve realized congestion (SPP − system_λ) and
  raw SPP.
- `/validation`, `/ptdf`, `/state`, the **clustering scorecard** (`ScorecardResponse`,
  zones/CCA/k-selection) — all synthetic-grid machinery. **Retire.**
- Web: `App.tsx` renders a `CompareMap` (model buses vs ERCOT SPs) with three palettes
  (`modeled_congestion`, `lmp`, `binding_proximity`), a playback scrubber over a loaded
  window, curated events, and a `StatsPanel` driven by the clustering scorecard.

**What is worth keeping** (§9 of the handoff, "kept with new jobs"): the two-map
chassis, the playback scrubber + `DateRangePicker` + curated-events mechanism, the
diverging/sequential palette machinery in `web/src/lib/colors.ts`, the prefetch/cache
layer, the DB-pointer-resolved-per-request serving pattern. **What dies:** the synthetic
buses/lines, the clustering scorecard, PTDF/validation, and the binding-proximity panel
(`/ibp`, `bp = max|SF|`) — the map's node value is congestion, not a bp layer.

### What the model actually produces (the assets to serve)
| Asset | Where it lives | Shape | Role in the product |
|---|---|---|---|
| **Implied SF map** | `compute/sf/fit.py::implied_shift_factors(M, C, …)`, refit per week on the honest trailing window | per week: `SF` (constraints × SPs) | The map. `congestion[sp] = −Σ_c SF[sp,c]·μ[c]`. Oracle ceiling **0.787**. |
| **μ-forecast** | `compute/mu/mu_model.py` → `mu_preds.npz` | `(hour × constraint-key)`: `p_bind`, `mu_gbm` (E[μ\|bind]), `mu_clim`, plus realized `y_bind`/`y_mu` | Two heads. What binds tomorrow and how hard. The shipped `all` config. |
| **Nodal forecast + bands** | `compute/mu/propagate.py` (draws) / `score.py` (point) | *currently* only weekly aggregate rows | Expected nodal congestion P10/P50/P90 — **the headline map**. |
| **Constraint geography** | `compute/mu/geo.py` — \|SF\|-weighted centroid of SP coords | per constraint: lat/lon, zone, kV | Puts anonymous constraint keys in space. The causal overlay. |
| **Geocoded SPs** | `data/processed/settlement_points_geocoded.csv` | 1,092 SPs w/ lat/lon (**97.9%** of the panel) | The node layer. Join key = `settlement_point`. |
| **Backtest scoreboard** | `compute/mu/mu_score_weekly.csv`, `mu_bands_weekly.csv` | per (week × source × regime): R², Spearman, sign, top-decile, coverage | The scorecard's backing data — **already computed.** |

---

## 2. The core reframe: forecast (left) vs realized (right)

The existing app is a *left-vs-right compare map with camera sync*. Today the split is
"synthetic model vs ERCOT." **Re-cast the same split as the product's spine:**

- **Left pane = Forecast.** What we predicted for this delivery day, using only inputs
  legal at DAM close (10:00 CT, D−1). Expected nodal congestion, P50, colored on the
  diverging palette; bands and drivers on hover.
- **Right pane = Realized.** What actually cleared — SPP − system_λ per SP — published
  the next day. Empty (or forecast-only) when the delivery day is still in the future.

This makes the compare-map **the scoreboard, made spatial.** Scrub to a past day and
you see prediction and outcome side by side; scrub to tomorrow and only the forecast
exists. The camera-sync, prefetch, palette, and scrubber code all carry over unchanged
— only the data sources behind the two panes change. This reframe is the single most
leveraged decision in the plan: it reuses ~all of the chassis and delivers the
headline ("a self-grading forecast map") for free.

Both panes now render **settlement points**, not buses — so `/topology` collapses to a
single geocoded-SP FeatureCollection and `spTopology` (already in `App.tsx`) becomes
the *only* topology. The synthetic-bus branch is deleted.

---

## 3. What to display — especially congestion

Congestion at a node is one signed scalar ($/MWh; ERCOT sign convention, negative =
the congestion component costs that node). Painted alone it is an inscrutable blob of
colored dots. The structure worth showing is **causal**: a sparse set of binding
constraints, each located in space, each pushing a specific set of nodes via the SF
map. So congestion is displayed as **two coupled layers**:

**(a) Nodal layer — the choropleth.** ~1,120 geocoded SPs, colored by forecast P50
congestion on a **diverging palette centered at 0** (reuse `computeModeledCongestionStats`
— it already anchors symmetric around zero at |mc| P90). Signed on purpose: some nodes
pay, some benefit; a one-sided heat scale would hide the export/import structure.
Node hover/click → detail card with P10/P50/P90, the constraints driving it, and fit
confidence (per-SP R² from the SF regression).

**(b) Constraint layer — the causal overlay (new, the key contribution).** Draw the
constraints predicted to bind this hour at their |SF|-weighted centroids (`geo.py`),
sized/opacity'd by forecast μ (severity) and P(bind) (confidence). This is *why* the
map looks the way it does. Two interactions make it legible:
- **Hover a constraint → light up its reach.** Fade all SPs except those it drives
  (high |SF|), signed: the positive-SF side and negative-SF side glow different ends
  of the palette. That is the congestion "dipole" — cheap side vs expensive side.
- **Optional corridor arc:** connect the constraint's positive-|SF| centroid to its
  negative-|SF| centroid — a drawn line showing the direction congestion pushes price.
  This is what "corridors" were in the superseded synthetic design, now *discovered
  from prices* rather than drawn from geography.

**(c) Node explorer (the map asset, oracle 0.787).** Click an SP → ranked signed
exposures to its top constraints ($/MWh per $ of μ), each with fit confidence and
binding-hours support. Click a constraint → its centroid + the nodes it moves.
**Guardrail from the handoff:** identifiability is unsolved and grouping did not fix it
(R3). Signed *per-constraint* claims stay caveated; lead with a stable unsigned
exposure magnitude per node. Label every exposure with its refit-to-refit
stability so a flickering attribution reads as low-confidence, not fact.

> **Which exposure summary (open — measure, don't bet).** Candidates for the per-node scalar `SF[sp,:] → ℝ`:
> - **max `max_c|SF|`** — simplest, rotation-robust, = legacy `bp`. Weak: hangs on one constraint, drops sign + distribution.
> - **signed sum `Σ SF`** — most identifiable, but *cancels* the corridor dipole (±5 → 0). Net push, not magnitude. Reject as an exposure cue.
> - **L1 `Σ|SF|`** — no cancel, but confounds strength with support size (many-weak ≈ one-strong); drifts more than L2.
> - **avg** — denominator artifact (measures sparsity, or penalizes breadth). Reject.
> - **L2 `‖SF[sp,:]‖₂`** — ridge already pins the min-L2 solution, so it's the summary the estimator controls → most stable under block-membership churn (block 2→3 members: max −33%, L2 −18%); no cancel.
>
> Lean L2 on the ridge argument, but **persist max/L1/L2 per node and pick by disjoint-window corr** (`sf/eval::_sf_corr` on the row summary) — a one-query measurement, not a design opinion.

**(d) Uncertainty is first-class, not decoration.** Bands under-cover today (coverage80
≈ 0.67 vs 0.80 target — independent-Bernoulli sampling of a correlated binding set,
§10 of handoff). Display the band, but annotate honestly ("bands indicative;
under-cover in correlated-binding hours") rather than implying calibration we don't
have. A joint/copula sampler would make them honest but not more skillful — a
correctness fix, not a product win.

**Palette / accessibility:** load the `dataviz` skill before touching chart or map
color. Diverging for signed congestion, sequential for magnitude/confidence, and
verify both light and dark. Congestion sign must survive colorblind viewing.

---

## 4. Serving architecture

Use a **self-owned DB-pointer pattern**: compute writes a run's artifacts → the job upserts
a pointer row this feature owns → the API resolves that pointer per request, so a new
forecast goes live without redeploy. This is the right architecture, but stand up a fresh
pointer this feature owns — do **not** reuse the legacy `implied_binding_proximity_current`
pointer, the `compute/promote.py` symlink tree, or `api/ibp.py` (all legacy).

### 4.1 The one real compute gap: persist the nodal forecast panel
`propagate.py` computes the full nodal draws (`draw_congestion` → `(draws, hours,
nodes)`) but keeps only `band_metrics(...)` per week — the nodal panel is thrown away.
**Task:** have propagate (and/or a thin production sibling) emit, per delivery day,
`(settlement_point, hour, p10, p50, p90, drivers)` — plus the point forecast from
`score.py`'s `predict(Msrc, SF)`. Everything else needed to serve already exists on
disk; this is the one thing that must be *produced* before it can be served.

### 4.2 New tables / pointers (self-owned)
- `forecast_nodal(run_id, delivery_date, ts, settlement_point, p10, p50, p90)` +
  `forecast_current` pointer (this feature's own).
- `constraint_geo(run_id, constraint_key, lat, lon, zone, kv, max_abs_sf)` — from `geo.py`.
- Drivers are reconstructed on read from a per-day SF+μ artifact, not stored — see
  spec-phase2a §0/§4a.
- Backtest weeks bulk-load once; daily production appends one delivery day.

### 4.3 New / changed endpoints
| Endpoint | Replaces / adds | Serves |
|---|---|---|
| `GET /topology` | **replace** | geocoded SPs only (drop buses/lines) |
| `GET /forecast/nodal_range?start&end` | **new** | P10/P50/P90 per SP per hour (left pane) |
| `GET /forecast/drivers?ts&sp` | **new** | top constraint drivers of a node (explorer) |
| `GET /forecast/constraints?ts` | **new** | constraints predicted to bind + geo (overlay) |
| `GET /realized/spp_range` | keep (`ercot_spp.py`) | realized SPP (right pane) |
| `GET /realized/congestion_range` | keep (`ercot_state.py`) | realized congestion (right pane) |
| `GET /scoreboard` | **new**, retires clustering scorecard | `mu_score_weekly.csv` reshaped (§6) |
| `GET /meta` | keep, repoint | served forecast run, refit params, last-updated |
| `/ibp/*`, `/validation`, `/ptdf`, `/state`, clustering scorecard | **retire** | — |

Keep the soft-fail contract the current code already uses: 404 = "nothing served yet";
503 = "artifact not built for this window" → client renders the available pane alone.

---

## 5. Phases

Ordered so each phase ships a usable surface and de-risks the next. Phases 1–3 are the
product; 4 is the secondary idea.

**Phase 0 — Retire & repoint (foundation).**
Delete synthetic-grid serving (buses/lines, PTDF, validation, clustering scorecard).
Repoint `/topology` to geocoded SPs. Collapse `App.tsx` to the SP-only topology; both
panes render SPs. Stand up the self-owned pointers for forecast + constraint_geo. *Exit:
the app loads with a single ERCOT SP map on the geocoded coordinates, nothing
synthetic left.*

**Phase 1 — Serve the map (the asset that already works).**
Persist and serve constraint geography (`geo.py`) + the node explorer (SF exposures)
and the realized right pane. This is the oracle-0.787 map — it needs no forecast, only
the SF fit and realized panels we already have. Node explorer, constraint overlay.
*Exit: click any node → who drives it; hover any constraint →
what it moves; right pane shows realized congestion.*

**Phase 2 — Serve the forecast (the headline).**
Close the §4.1 compute gap: emit the nodal P10/P50/P90 panel. Serve it into the **left
pane** as the predictive congestion choropleth, bands on hover, constraint overlay
colored by forecast μ. This is "the visible predictive layer." *Exit: pick a delivery
day → expected nodal congestion map with drivers and bands; forecast-vs-realized split
when the day is past.*

**Phase 3 — Scoreboard (self-grading).**
Reshape `mu_score_weekly.csv` into `/scoreboard`; build the scorecard page (§6). Wire a
daily production job (forecast at D−1 close → grade at D+1 when realized publishes).
*Exit: a public rolling track record, screening metrics leading, baselines + oracle
shown, pre/post-RTC+B split.*

**Phase 4 — Historic backtest slider (secondary).**
Reuse the scrubber + curated-events to replay historic delivery days through the
forecast using only inputs legal at each day's DAM close. "Would we have caught this?"
overlaid on the known event. See §7 and its leakage caveat.

---

## 6. Scorecard: evaluate & display predictive performance over time

The good news: **the numbers already exist.** `mu_score_weekly.csv` has, per week × μ
source × regime, exactly the pre-registered currencies (pooled R², MAE, rank-Spearman,
sign-agree, top-decile, plus SF/model coverage). `mu_bands_weekly.csv` adds coverage80
and band width. Serving is mostly reshape + plumbing; the design work is *what leads*.

**Design principles (from handoff §6/§7):**
- **Screening metrics lead** (rank-Spearman, sign, top-decile). Magnitude (R²/MAE)
  goes in a diagnostics tab — leading with R² makes a working *screener* read as a
  failing *forecast*.
- **Every headline against baselines, always.** Persistence and climatology on every
  chart; the **oracle 0.787** as the ceiling line — the skill-decomposition ("the map
  is solved, μ-forecasting is not") is the project's strongest standalone result and
  belongs on the scoreboard, not buried.
- **Pre/post-RTC+B split visible** on every pooled stat (cutover 2025-12-05). The
  shipped `all` is 0.610 top-decile pooled but 0.559 post-RTC+B — show both; don't let
  the pooled number launder the post-cutover miss.
- **Coverage reported alongside skill** every week — it explains collapse weeks; hiding
  it misattributes model failure to weeks that were really coverage gaps.
- **Regime splits** (summer_peak / winter_peak / high_wind_west / mild_shoulder) —
  already the `regime` column. But **one year of data**: spring ≈ low-demand ≈ the same
  weeks. Annotate the seasonal story as corroborating, not independent.

**Surfaces:**
1. **Headline tiles** — rolling 30/90d top-decile, Spearman, sign, R²; each with its
   persistence delta and the oracle ceiling.
2. **Time series** — weekly metric vs baselines vs oracle (this is `mu_score_weekly.csv`
   almost directly). Screening currency by default; magnitude behind a toggle.
3. **Coverage strip** beneath the series, same x-axis.
4. **Per-day grade** (once daily production runs) — the delivery day's forecast vs
   realized, top-decile hit for that day.
5. **Miss-attribution** (handoff §6) — snapshot inputs at prediction time; decompose
   misses into unforecastable-outage / driver-forecast-bust / model error.

**Integrity guardrails (non-negotiable, from §5.5/§7):** never edit a pre-registered
bar after seeing results; version the gates file (`gate()` in `propagate.py` is the
transcribed bar — keep it authoritative). Re-measure every baseline whenever the
operating point moves — "a baseline never re-measured is a souvenir." And a flat
prediction cannot score: `score.py` already overrides `topdecile_hit` to decline flat
rows; any new metric must be null-checked before it's trusted.

---

## 7. Historic backtest slider (secondary)

The scrubber already loads arbitrary historic windows. The idea: for a chosen historic
delivery day, run the *forecast* (not the realized panel) using only inputs available
at that day's DAM close, and replay it against the known outcome — did we anticipate,
e.g., a spring-maintenance congestion event before it bound?

This is genuinely compelling because it directly exercises the project's thesis
(anticipation vs persistence). **But it is also where skill gets fabricated**, so it
carries the heaviest caveat in the codebase:

⚠ **Cutoff discipline (handoff §3, §10).** `features.py:history_cutoff(D)` returns
midnight CT on D — correct *only* because DAM shadow prices for D−1 clear on D−2,
before DAM close for D. It is a fact about one product's publication schedule. The
backtest replay must pin every input at **DAM close (10:00 CT, D−1)** with its own
two-sided leakage test, and the SF map handed to day D must be the one fit on the
trailing window that had already closed before D (exactly as `score.py` and `geo.py`
refit walking-forward — a global SF fit "will not look like a bug, it will look like a
result"). Because `mu_preds.npz` and the weekly scores were produced this way, the
backtest can reuse them directly for the 46 validated weeks rather than re-running the
model live — which both avoids the leak and is far cheaper. **Do Phase 4 only after the
scoreboard (Phase 3) makes the walk-forward contract concrete in code.**

---

## 8. Open questions / decisions to make before building

- **Forecast granularity to persist.** Full nodal panel is 1,120 SPs × 24 h × 3
  quantiles per day — trivial. Drivers are the cost: cap top-k per node (k≈10?) or the
  `forecast_drivers` table is dense. Decide k against the explorer's needs.
- **Constraint groups vs raw keys.** R3 failed, so groups don't ship as an
  identifiability fix — but the *display* may still want to collapse co-binding keys
  for legibility. If so, group only for rendering, and never attach signed claims to a
  group (same trap, restated).
- **Daily production cadence.** The validated model is weekly-refit backtest. Standing
  up a daily forecast (D−1 close → publish) is new operational surface: a scheduled job
  that fits SF on the trailing window, runs the two heads on tomorrow's covariates,
  propagates, publishes (sets its own pointer). Scope this as its own mini-phase inside Phase 3.
- ~~**Retire vs archive.**~~ **Decided: delete the synthetic-grid endpoints** (routes,
  models, tests) — cheap to resurrect via git if ever needed. The OPF/synthetic
  *compute* and its writeup (handoff §8.1) stay; only the serving routes are deleted.
- ~~**Two-map vs single-map-with-toggle.**~~ **Decided: forecast (left) vs realized
  (right)** per §2. This is the design of record and drives the `App.tsx` refactor.

## 9. What this plan deliberately does *not* do

- No new modeling, features, or feeds. The science is frozen (handoff §5, §11).
- No attempt to fix band under-coverage as a *skill* gain (it's a correctness fix; book
  it honestly if done at all).
- No signed per-constraint headline claims (identifiability unsolved).
- No revival of the equivalent-network / what-if studies (deferred, §9 handoff).
