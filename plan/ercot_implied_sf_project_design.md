# ERCOT Congestion Map — The Plain-Language Version

*A big-picture companion to the dense planning docs. If the stats-heavy handoff
(`handoff-ercot_implied_sf_project_design.md`), the master plan
(`version3-implementation-plan.md`), or the 0082/0083 branch notes made your eyes
glaze over — start here. This says **what we're building, why, which code does
what, how the math works, and how we grade it**, in the fewest technical terms
possible.*

---

## 0. Where the project actually landed (read this before the roadmap)

*This document was written when the forecast was still unbuilt and the roadmap
below (§11) still read R1→R5 as a hopeful sequence. Most of that is now history,
and it did not go the way §11 hoped. The conceptual and math sections (§2–§4, §10)
are unchanged and still correct — but wherever the prose says "we're about to" or
"no-lose," trust this section instead. Full detail lives in the branch summaries
`plan/0082-summary.md … plan/0089-summary.md`.*

**The one finding that survived everything: the map is solved; the forecast is
not.** Fed the *true* shadow prices, the map explains ~**79%** of nodal congestion
and names ~**76%** of the worst locations. Fed any realistic forecast, that drops
to ~**22%**. The entire remaining problem is **forecasting μ** — which elements
strain tomorrow — and nothing we have tried has closed the gap to a shippable bar.

The risks, as they actually resolved:

| risk | question | outcome |
|---|---|---|
| **R1** ✅ | Does honest grading change the settings? | **Yes.** Longer window (60→240 days) and real regularization (0.1→1.0). The old 98.6% was graded on the training week; honest accuracy is ~75%. (0082) |
| **R2** ✅ | Is the coverage blind spot cheap to fix? | **Half.** ~half the missed constraints are seasonal, but the 240-day window already recovers most of that memory for free — no cheap warm-start win. (0082/0084) |
| **R3** ❌ | Does **grouping** co-binding constraints steady the map? | **No.** +0.006 against a +0.10 bar — ERCOT's co-binding blocks are too small (1.1×) to bite. Grouping does not ship; signed per-constraint claims stay blocked. (0083) |
| **R4** ⛔ | Can we join real-world **outages** to constraints? | **The name-join works (98% of force); the transmission-outage *feed* is unreachable** — behind ERCOT's Market-Participant-only secure area. Degrades to a crude zonal aggregate. (0085) |
| **R5** ❌ | Does the forecast beat "same as yesterday"? | **No — and the "no-lose" premise was false.** The model loses top-decile (0.523 vs persistence 0.561), the one metric a screener is for. The safety-net baseline everyone trusted turned out to be a stale number from a retired operating point. (0085) |

**The second-generation phase — chasing R5's failure:**

| risk | question | outcome |
|---|---|---|
| **R6/R7** ⛔ | **RUC** — ERCOT's reliability run, the one genuinely *new* signal? | **Dead.** No reliability run at or before market close describes the next day, at any archive depth — there is no honest vintage to forecast from. (0087) |
| **R8** 🔄 | Was the model just **under-specified** (missing lagged μ, geography, weather response)? | **In flight.** Added all three in one panel with a pre-registered ablation; the five-arm run is code-complete, awaiting a large-enough machine. The likeliest outcome — and the most valuable — is that lagged μ was a plain *defect fix* the model had been missing. (0088) |
| **R9** 🔄 | Is there a **public** outage feed after all? | **In flight.** A public *generation*-outage feed (NP1-346) is reachable, deep, and legal to serve — placed per-constraint through the map. It is not the transmission feed R4 wanted; whether it beats the zonal aggregate is pending the run. (0089) |

**So RUC is no longer an option** anywhere in the plan, and the "no-lose finale" in
§11 never existed. What is genuinely valuable and shippable today is the **skill
decomposition itself** (oracle ~0.79 vs every real forecast ~0.22) — a public,
honest measurement of exactly where the problem is.

---

## 1. What are we actually building?

**A live, self-grading map of where the Texas power grid is congested — built
entirely from public price data.**

Three things, in plain terms:

1. **A map** showing, for every location on the grid, *which bottlenecks are
   pushing its electricity price around.*
2. **A forecast** of what will get congested tomorrow and what that does to
   prices everywhere.
3. **A scoreboard** that grades yesterday's forecast against what actually
   happened — in public, honestly.

Nobody outside ERCOT publishes this. That's the point.

---

## 2. The one idea the whole project rests on

In electricity markets like ERCOT, the price at each location breaks into two
parts: a base energy price (the same everywhere) plus a **congestion** part (the
extra cost of getting power *to that specific spot* past the grid's bottlenecks).

Here's the magic. There's an exact accounting rule baked into how the market
clears:

> **congestion at a location = the sum of (how badly each bottleneck is hurting)
> × (how sensitive this location is to that bottleneck).**

- "How badly each bottleneck is hurting" is called a **shadow price** — *and
  ERCOT publishes it.*
- The location's congestion is derivable from published prices too.
- The only unknown is that middle number — **how sensitive each location is to
  each bottleneck.** That grid of sensitivities is the **shift-factor (SF) map.**

So we have an equation where two of the three pieces are public, and we solve
backwards for the third. Run a regression over lots of hours of history and the
**shift-factor map falls out.** That map *is the asset.*

**Why this is remarkable:** we never need to know the physical grid — where the
wires run, which substation is where. The bottlenecks stay anonymous text labels.
Their "location" is revealed automatically by *which price nodes react when they
bind.* We learn the grid's behavior without ever seeing its blueprint.

---

## 3. How the map is actually computed (ridge regression)

This is the statistical engine. Written as matrices, the identity from §2 is:

```
C = −M · SFᵀ
```

- **M** = shadow prices, a table of `hours × bottlenecks` (how much each
  bottleneck hurt, each hour). Zero when a bottleneck wasn't binding.
- **C** = congestion, a table of `hours × nodes` (the price effect at each
  location, each hour).
- **SF** = the shift-factor map we want to solve for.

**The setup is a regression, one node at a time.** Take a single node — say
Houston.

*Build the dataset.* Line up the history hour by hour. Each hour is one **row** —
one training example — recording two things: Houston's congestion that hour (the
number we want to explain) and the shadow price of every bottleneck that hour (the
inputs). Over a 240-day window that's ~5,760 rows — a long table:

```
hour        | bottleneck_A pain | bottleneck_B pain | ... | Houston congestion
2025-01-01  |       120         |        0          | ... |       −8.40
2025-01-01  |        95         |       40          | ... |      −11.10
...         |                   |                   |     |
```

*Solve for the sensitivities.* The regression looks for one number per bottleneck
— Houston's sensitivity to A, to B, and so on — such that "Σ (pain × sensitivity)"
reproduces Houston's actual congestion **as well as possible across all ~5,760
hours at once.** It isn't fit hour by hour; it's fit *over* all the hours
together, finding the single set of sensitivities with the smallest total error
over the whole window.

*"Regressed through time" = sliding the window.* That solve gives Houston's
sensitivities as of today. A week later we slide the 240-day window forward — drop
the oldest week, add the newest — and re-solve. Repeat weekly. So "through time"
does **not** mean the regression models time dynamics; each fit is a static
snapshot over its window, and we simply **re-fit a fresh snapshot on a rolling
window**, the way a moving average slides. That rolling refit is `rolling.py`'s
job (§8).

One caution about what the time dimension *is*: to this regression, hours are just
independent examples (rows). It does **not** say "Houston's congestion now depends
on Houston's congestion an hour ago." It's a same-hour relationship — *this*
hour's bottleneck pains explain *this* hour's congestion — averaged over many
hours.

**From one node to all nodes — batched, not coupled.** Now the key question: when
we do every node at once, are the nodes *linked*, or just *stacked*?

They're **stacked — the regressions are independent.** Houston's sensitivities are
solved with no reference to Dallas's. Nothing lets one node's congestion pull on
another node's coefficients.

So why do them in one shot? Because **the inputs are identical for every node** —
every node is exposed to the same bottlenecks in the same hours; only the output
column changes. Instead of one output column (Houston) we hand the solver the
*whole* congestion table C (all ~1,000 nodes as columns) as the output Y, and it
returns one column of sensitivities per node. The expensive step — inverting the
inputs' cross-product — is computed **once** and reused for every node. The matrix
form is purely a **batching/efficiency device, not a statement that nodes
interact.**

Do nodes influence each other at all, then? Only *indirectly*, through shared
bottlenecks: if Houston and Dallas both respond to bottleneck A, they'll move
together whenever A binds — but that shows up as each having *its own* coefficient
on the shared input A, never as a direct Houston→Dallas term. "These two places
are electrically related" is captured entirely by *which bottlenecks they share* —
exactly the §2 insight that geography lives on the node side.

In `fit.py` the whole batched solve is a single line:

```python
beta = np.linalg.solve(Xs.T @ Xs + lam * np.eye(K), Xs.T @ Y)
```

**Ordinary regression** would solve `β = (XᵀX)⁻¹ XᵀY`. Read it as: `XᵀY` is "how
much each bottleneck moves together with the node's congestion," and `(XᵀX)⁻¹`
divides out how much the bottlenecks overlap *with each other*, so shared credit
isn't double-counted.

**Ridge regression** is that, plus one term — the `+ lam * np.eye(K)`, i.e.
`β = (XᵀX + λI)⁻¹ XᵀY`. That extra `λ` on the diagonal is the **regularization**.

### What are `lam` and `np.eye`?

Decoding the two symbols in that added term:

- **`np.eye(K)`** is the **identity matrix** — a `K × K` grid (K = number of
  bottlenecks kept) with **1s down the diagonal and 0s everywhere else.** So
  `lam * np.eye(K)` is a matrix with `lam` on the diagonal and 0 off it, and
  adding it to `XᵀX` simply **adds `lam` to each of `XᵀX`'s diagonal entries** —
  nothing else changes.
- **`lam` (λ)** is the **strength dial** — the single knob. It's the size of that
  diagonal nudge: small `lam` = gentle, large `lam` = aggressive.

Everything that little diagonal nudge buys — safe matrix inversion *and*
coefficient shrinkage — is the next section.

### What is regularization?

Regularization is a **penalty that discourages the coefficients from getting
large.** Ordinary regression has one goal: fit the training data as closely as
possible. Given enough freedom it will contort the coefficients into huge,
opposing values to chase every last wiggle — including the random noise. That
fits the past beautifully and predicts the future badly. This is *overfitting*.

Ridge changes the goal to: *fit the data well **and** keep the coefficients
small.* The `λ` knob sets the exchange rate between those two aims:

- **λ = 0** → no penalty → ordinary regression → free to overfit.
- **λ large** → heavy penalty → coefficients squashed toward zero → very stable
  but can under-fit (it starts ignoring real signal).

Mechanically, adding `λ` to the diagonal before inverting also makes the matrix
better-behaved to invert. That matters most when two bottlenecks are highly
correlated (they often bind together): then `XᵀX` is nearly un-invertible,
ordinary regression produces wild coefficients that flip sign between refits, and
ridge damps the wildness. *(This is the same co-binding instability that branch
0083's grouping attacks from the other side — ridge softens it; grouping removes
the ambiguity structurally.)*

**The catch we caught in 0082:** the old `λ = 0.1` was *decorative*. The penalty
only bites if it's comparable in size to the diagonal of `XᵀX` — and that diagonal
was ≈1440. Adding 0.1 to 1440 does nothing, so the model was effectively running
with **no regularization at all** while appearing to have some. The honest
re-sweep raised it to `λ = 1.0` — still modest, but now it actually shrinks the
noisiest coefficients, which is part of why stability improved.

*(A project-specific wrinkle: before applying the penalty, the code
`standardize`s each bottleneck's column by its typical size, then rescales the
answer back to real units. Without that, `λ` would punish a bottleneck that
happens to be measured in small numbers far more than one measured in large
numbers — an accident of units, not importance. See `fit.py:87-101`.)*

---

## 4. Why shift factors, not just shadow prices?

A natural objection: *if I ultimately want congestion, why go through this
shift-factor regression at all? Why not just work with the shadow prices — they're
already zero when nothing's congested and positive when something is?* And the
sharper version: *congestion = LMP − system-λ, and both of those are public, so
congestion is **already known** — why not just regress against congestion directly?*

Both are the right questions, and they dissolve once you see that **shadow price,
shift factor, and congestion are three different things playing three different
roles** — not competing choices.

**Shadow price ≠ congestion. They're not even the same kind of object.**

- A **shadow price** `μ[c,t]` is **one number per *constraint* per hour.** It has
  no location. It says *how hard bottleneck c is straining* — nothing about *where
  on the grid that strain lands.* (~1,000 anonymous constraints.)
- **Congestion** `congestion[node,t]` is **one number per *node* per hour** — the
  congestion adder in Houston's price, in Dallas's, at each of ~1,084 settlement
  points. *This is the thing people trade and settle on.*

They're related but live in different spaces — constraint space vs node space —
and you can't hand someone the first when they need the second.

**The shadow price is spatially blind — SF is the entire spatial story.** Look at
the identity `congestion[node,t] = −Σ_c SF[node,c]·μ[c,t]`:

- `μ[c,t]` is **always ≥ 0, and identical for every node.** A constraint straining
  at $50 is $50 for Houston and $50 for Dallas.
- Yet that same $50 event might be **+$12** at Houston and **−$8** at Dallas.

Where does every bit of that spatial variation — who's up, who's down, by how much
— come from? **Entirely from `SF`.** The shadow price contributes zero spatial
information; it's a location-less strength. So "just use the shadow prices" leaves
you knowing a constraint strained by $50 with **no way to turn that into a price at
any particular node.** The shift factor is the mandatory bridge — and it isn't
published (ERCOT gives you μ and prices, not the sensitivity map), which is exactly
why we recover it by regression (§3).

**Now the caveat — "but congestion is already known, so why not regress against
it?"** Two answers, and the second is the important one:

1. **For the *observed* map, you're completely right — no model needed.** Today's
   and yesterday's congestion is just `LMP − system-λ`, published: subtract and
   display. If all we wanted were a rear-view congestion map, there'd be no SF and
   no regression at all. **SF exists only for the two things subtraction can't do:
   forecast *tomorrow's* congestion (tomorrow's LMP isn't published yet), and
   *attribute* today's number to specific bottlenecks (the node explorer).**
2. **And here's the twist: congestion *is* what we "regress against" — it's the
   target, not an alternative to SF.** The shift-factor regression takes observed
   congestion (`LMP − system-λ`, exactly as the caveat says) as its **output Y**
   and the observed shadow prices as its **inputs X**, and the coefficients that
   fall out *are* the shift factors. "Regress against congestion" and "recover
   shift factors" are **the same regression** — the SF map is just the name for its
   output. What the fit buys you over the raw congestion number is that it
   **un-tangles** each node's congestion (a messy sum of many constraints' effects)
   into *per-constraint contributions* you can forecast and attribute separately.

If instead the question means *"skip the μ/SF split and predict future congestion
directly from weather and load"* — that's possible, but it's the wrong trade:
you'd need ~1,084 separate node-level forecast models, each forced to re-learn the
whole grid's response, all chasing a tangled moving sum, with no attribution and no
counterfactuals. The decomposition replaces that with something far smaller and
more honest (next).

**Why the decomposition is the good design, not just the necessary one.** Splitting
`congestion = SF × μ` factors one brutal forecasting problem into two friendly
ones:

- **μ — the forecastable part:** *which constraints bind tomorrow, and how hard.*
  Driven by weather, load, and outages — physical, predictable — and only a few
  dozen constraints bind on a given day. **This is where you *do* predict shadow
  prices; it's the μ-model on the roadmap (§11) — not an alternative to SF, but the
  *other factor*.**
- **SF — the structural part:** the grid's wiring. Slow-moving, already recovered,
  one matrix.

Predict μ (small, physical) → multiply by the SF map → nodal congestion at **all
1,084 nodes at once**, plus two things a direct-congestion model can't give you:
**attribution** ("Houston's $12 is 70% group X, 30% Y" — §7 unlocks this) and
**counterfactuals** ("what if constraint X binds at $100 tomorrow?" = one matrix
multiply).

**One-line version:** shadow prices tell you *that* the grid is straining and *how
hard*; shift factors tell you *what that does to the price at each specific node.*
Congestion is what the SF regression is fit *against* — its target — and the shift
factors are what that fit produces; you then forecast congestion by predicting the
shadow prices (the μ-model) and multiplying by the recovered map.

### So what does the forecast actually predict? (isn't that *also* 1,000 models?)

Follow that last sentence to its natural objection. Once SF is recovered, **the
only thing predicted from weather and load is μ — the shadow prices.** SF is *not*
forecast from weather; it's the recovered structural map, refreshed slowly on the
rolling window. The live forecast is a two-stage pipeline:

```
weather, load, outages ──► μ-model ──► μ̂  (predicted shadow prices)
                                        │
                   recovered SF map ────┤
                                        ▼
                          congestion = −SF · μ̂   (all ~1,084 nodes, one matmul)
```

*(This μ-model was the unbuilt part when this document was written — roadmap R5. It
**has since been built (0085), and it failed its gate** (§0): the design below is
sound and was implemented close to as described, but the resulting forecast does not
beat "same as yesterday" where a screener is graded. What follows is that design,
kept because it is still the right frame; §0 has the outcome.)*

Now the fair objection: the μ-model is **per-constraint** (the plan hoped per-*group*,
but grouping failed — §7), so isn't that *also* ~1,000 models — didn't we just
relocate the problem? The honest
answer: **the win isn't fewer models, it's which dimension you learn statistically
versus which you get exactly and for free.** Three asymmetries put the modeling
budget in the right place:

1. **Nodes are dense; constraints are sparse.** Essentially *every* node has
   nonzero congestion every hour (a sum over whatever's binding, spread by SF), but
   only *a few dozen* constraints bind at once — most of the ~1,000 library are
   structural zeros almost always. Predicting μ is mostly "predict which few switch
   on." Predicting node congestion directly is ~1,084 *dense* targets, all nonzero
   every hour.
2. **Constraints are the causal unit; node congestion is a derived superposition.**
   "This West Texas line overloads when regional wind is high and load is up" is a
   clean, low-dimensional, physical relationship. A node's congestion is *many*
   such events summed and filtered through SF — to predict it directly, a node
   model would have to re-derive the grid from one node's worth of signal.
3. **The big dense dimension becomes free.** Once you have μ̂, **all 1,084 nodes
   come out of one matrix multiply** — zero per-node modeling. The decomposition
   takes the large dense dimension (nodes) *out* of "things you fit" and into a
   matmul, leaving only the sparse causal dimension to model. Direct
   node-forecasting spends its whole budget on exactly the dimension SF already
   handles exactly.

Underneath sits a **pooling** point: the SF fit estimates each constraint's spatial
signature using *all 1,084 nodes at once* against the shared μ, and the μ-model
uses *all of that constraint's history*. A direct node model can't pool across
nodes — it never sees the shared latent cause (μ) that ties them together.

**How the μ-model works.** Per constraint (pooled into one model, since grouping
failed), two heads:

- **P(bind at hour h | covariates)** — a classifier (logistic / gradient-boosted
  trees) on zonal load forecast, regional wind/solar forecasts, net load, calendar,
  recent binding history, and outage flags near the group. Output: probability the
  group is binding in hour h.
- **E[μ | it binds]** — how hard, given it binds. Starts lightweight
  (net-load-bucketed conditional climatology — *not* a trained model per
  constraint), graduating to quantile regression for P10/P50/P90 later.

**Why two heads and not one model of μ?** Because μ is a *spike-at-zero* variable —
exactly 0 the large majority of hours, then a positive, heavy-tailed jump when it
binds. A single regressor on μ handles that badly: the mass of zeros drags it
toward zero (chronically under-predicting the magnitudes that matter), and it
blurs two questions with different drivers — *does* it bind (a discrete event, from
outages / load thresholds) versus *how hard* (a continuous redispatch cost).
Splitting gives a clean classifier, a magnitude model that only ever sees hours
with a real magnitude to explain, and — together — a proper predictive
*distribution* (a point mass at 0 with probability 1−p, a continuous piece with
probability p) that you can sample for the bands. You lose nothing:
`E[μ] = P(bind) × E[μ|bind]`. It also lets you grade the two skills separately,
which maps onto persistence carrying the ranking skill and climatology the
magnitude (§9). This split-at-zero design is standard for intermittent targets —
rainfall, insurance claims, demand spikes.

To get nodal bands: **sample** binding sets from the first head, assign magnitudes
from the second, push each sample through `−SF · μ` for a nodal congestion vector,
and read the spread across samples as P10/P50/P90 per node. (The plan had grouping
(§7) cut the model count; grouping failed, so the heads are **per constraint** and
the model is *pooled* across them — one model with constraint identity as a feature,
rather than N tiny separate models. Only constraints that clear the support bar and
carry real μ-mass get modeled — a few hundred at most, dominated by a much smaller
handful.)

**The caveat that keeps this honest:** the decomposition *isolates* the hard part,
it doesn't eliminate it. The measured ceiling (oracle-μ R² ≈ **0.787** re-measured
in the fair harness, §9) is what you'd get with *perfect* μ̂ — so essentially all
remaining forecast skill lives in this μ-model, which is exactly why it was the
last, most expensive step, and why building it (0085) is where the project's
forecast ambition met the wall (§0). What SF bought you is that the spatial half is
exact and free, so every bit
of modeling effort goes to the one part that actually carries the skill.

### μ still has "freedom" — how we buy it down

Shrinking congestion to μ doesn't make μ *easy*: a shadow price still has a lot of
latitude, and the natural next question is "can we add information to pin it down?"
Yes — and most of the roadmap past R3 is exactly that. Split μ's freedom into two
kinds, because they call for opposite responses:

- **Reducible** — things we *could* know but haven't fed the model yet (an outage
  is scheduled, it'll be 108 °F, the market already priced this path). More
  information genuinely narrows these.
- **Irreducible** — day-ahead μ depends on the cleared unit commitment and the bids
  offered, which *don't exist yet* at forecast time. No feature removes this; the
  honest response is to **emit a distribution (P10/P50/P90 bands)**, not a point
  guess. The bands *are* the residual freedom made visible — also why the
  scoreboard leads with screening metrics over exact magnitude.

The information you can add, by type:

1. **Causal drivers of binding** (features for P(bind)): load/wind/solar forecasts,
   net load, calendar, recent binding history — already planned — plus the big one,
   **transmission outages** (R4, §11), rated highest-value because outages drive the
   *novel* binding that hurts most and are knowable in advance. Two not yet in the
   docs, worth flagging: **temperature / thermal line ratings** (a line de-rates
   when hot, so the same flow binds on a 105 °F afternoon that wouldn't at night)
   and **planned generator outages** (they redraw the flow pattern).
2. **Other people's forecasts** (market-revealed): CRR auction clearing prices and
   60-day DAM PTP obligation awards *are* the market's own money-backed congestion
   forecast. Currently framed as the *benchmark to beat*; they could double as
   *features* — with the caveat that using them as inputs partly forfeits them as an
   independent yardstick.
3. **Cross-timeframe signals**: real-time / SCED shadow prices are a noisier but
   more frequent leading indicator, and the basis for incorporating a novel
   constraint within ~a day instead of waiting for the weekly refit.
4. **Historical priors**: the lifetime constraint library + seasonal binding
   profiles (§6) shrink the guess for constraints too rare to fit from the recent
   window — "this element historically binds August afternoons."
5. **Physical/economic structure on μ itself**: co-binding structure (grouping, §7);
   **merit-order / offer-stack bounds** on E[μ|bind] magnitude (μ is a redispatch
   cost, so the offer stack bounds plausible magnitudes from economics, not just
   statistics); and — the trap — **network (LODF/PTDF) priors**, powerful but the
   deliberately deferred equivalent-network, because it reintroduces exactly the
   topology-dependence the price-based pivot escaped.

The intended sequencing was to prove the cheap μ-model beats persistence first,
*then* buy down the freedom, outages first by information-per-effort. **That is what
was tried, and the "prove it first" step (R5) failed** — the μ-model does not beat
persistence where a screener is graded (§0), and the "no-lose" framing turned out to
rest on a stale baseline. What survives is the diagnosis: the freedom that's left is
dominated by information the model *cannot* see at forecast time (which elements are
out of service), which is why the follow-on work (0088/0089) is all about adding
back that missing information. And some freedom is irreducible by construction —
hence bands, not point forecasts.

---

## 5. Where this came from (the short backstory)

The project started as a **physics simulation** — a from-scratch model of the
Texas grid, trying to predict prices. It didn't match reality well (details in
the frozen writeup). But building it taught us the accounting rule in §2. So we
**pivoted**: stop simulating the grid, and instead *learn its behavior straight
from prices.* The simulation is done and shelved; the price-based map is the
product now.

---

## 6. The honesty problem we already fixed (branch 0082)

The map originally looked ~98.6% accurate. That number was **cheating** — the
model was graded on the same week it was trained on, like giving a student the
exam answers in advance. When we graded it *honestly* (train on the past, grade
on the next unseen week), real accuracy was **~75%**.

Branch 0082 fixed this permanently by building an **honest grader** (`eval.py`)
and then **re-tuning the settings** against the honest score. Two takeaways:

- The best settings changed: a **longer training window (240 days, was 60)** and
  **real regularization (λ=1.0, was the do-nothing 0.1)**. The map got more
  accurate, covers more congestion, and stays fresh longer between refits.
- About **19% of congestion** comes from bottlenecks the model hasn't seen in its
  window — the "coverage gap," explained next.

### The 19% coverage gap, in detail

This one isn't about the regression's *coefficients* — it's about which
bottlenecks the regression **even has a column for.**

The fit only learns a shift factor for a bottleneck that actually showed up, and
bound often enough, *inside its training window.* In `fit.py`:

```python
keep = (M > 0).sum() >= min_hours   # drop bottlenecks binding < 25 hours
```

Any bottleneck that bound fewer than 25 hours gets **dropped entirely** — no
column, no shift factor. And one that never appeared in the window has no column
either.

Now grade an unseen week. Some of that week's congestion is caused by bottlenecks
the map **has no column for**. The map literally cannot attribute that congestion
to anything — it's invisible. Weighted by how much pain each bottleneck caused,
**~19% of a typical week's congestion comes from bottlenecks the map couldn't
see.** That's the coverage gap, and it's the single biggest predictor of the
model's worst weeks: when a big novel bottleneck fires, coverage craters and
accuracy collapses with it.

### Why 25 hours, and is it swept?

The `min_hours = 25` in that drop rule is a **minimum-support threshold** — the
fewest hours a bottleneck must bind, inside the window, before the regression will
even try to estimate its sensitivity.

The reasoning is the same as for any regression: **you can't estimate a
coefficient from almost no data.** If a bottleneck binds for only three or four
hours out of ~5,760, those few points are swamped by noise and whatever
sensitivity the fit assigns is basically random. Worse, that noisy coefficient
would flow straight into the `bp = max|SF|` layer (`metric.py`), where a single
junk value can win the `max` and corrupt a node's headline number. So we require a
floor of genuine "on" hours — enough observations to pin the sensitivity down —
and drop anything below it as unidentifiable.

Why **25** specifically? It's a **judgment-call round number, not an optimized
constant.** 25 hours is ~1% of the 60-day window it was originally set on (and
under half a percent of the 240-day window) — i.e. "a couple dozen observations,"
the rough floor below which a coefficient isn't worth trusting. It was never
claimed to be optimal.

**Is it in the sweep?** Yes and no, and the distinction matters:

- **Mechanically it's a sweep axis.** `sweep_ibp.py` exposes `--min-binding-hours`
  and threads it through the combo grid (`sweep_ibp.py:87,103-108`), right
  alongside window, refit, and λ. You *can* sweep it.
- **But it was held fixed at 25 in the honest 0082 re-sweep.** That run varied only
  window and λ (its default `--min-binding-hours` is the single value `"25"`),
  exactly as `std_floor` was pinned at 100. So the operating point we adopted
  (`240, λ=1.0`) was chosen *with `min_hours` frozen at 25*, not optimized over it.
  It remains an untuned knob and a fair candidate for a future sweep.

One tension worth naming: `min_hours` trades directly against the coverage gap
above. Raise it and you drop more rare bottlenecks → **coverage falls** (more of
each week goes unexplained); lower it and you admit noisier columns → the map gets
shakier. 25 is a middle setting on that dial — and because it wasn't swept,
whether a different value would buy coverage without much added noise is genuinely
open.

### Why "no free fix — real, bounded work"

The tempting hope was: "those novel bottlenecks probably showed up *last year* —
just remember them and warm-start, and the gap mostly closes for free." So
`coverage_probe.py` measured it against multi-year history. The answer:

- **~half** of the novel congestion *is* seasonal — bottlenecks that appear
  elsewhere in history, just not in the recent window. A "remember last year"
  warm-start could recover roughly **30–50%** of the gap.
- **The other half is genuinely new** — mostly shoulder-season constraints with
  no useful precedent. No amount of remembering helps; only faster refitting or
  real new modeling reaches them.

So:

- **"No free fix"** = the whole 19% will *not* fall to a cheap warm-start. Half of
  it needs actual work (shorter refit cadence, mid-week incorporation of new
  bottlenecks). Don't budget the gap as free money.
- **"Bounded work"** = but it's not an open-ended research swamp either. We know
  its *size* (19%), its *composition* (~half recoverable, ~half not), and what
  closing each half costs. It's a scoped, estimable task with a known ceiling.

That combination — *not free, but bounded and quantified* — is exactly what a
cheap probe is supposed to tell you before you spend real engineering time.

---

## 7. The grouping attempt (branch 0083) — tried, and it failed

*This section was written while grouping was in progress. It is done now, and the
verdict is at the end. The mechanism below is still exactly right — it is *why* the
fix looked promising — so it's kept in full; only the outcome changed.*

**The problem:** some bottlenecks *always bind together* (e.g. the same physical
power line under three different "what-if" contingency scenarios). When two things
always move in lockstep, the math **can't tell them apart** — it splits the credit
between them arbitrarily, and the split *flips randomly every week.* That makes any
statement like "this line drives that node's price" untrustworthy.

**The proposed fix:** find the bottlenecks that move together, **bundle them into a
group,** and treat the group as one unit. You can't say which member did it, but you
*can* reliably talk about the group. That would have unlocked the "node explorer"
(click a location, see what drives its price) and other signed claims.

**The question (called R3):** does grouping actually make the map **more stable
week-to-week** *without* costing accuracy? Pre-registered pass/fail bars were set
*before* seeing results, so the goalposts couldn't move — and **fail was declared a
legitimate outcome** in advance.

**The verdict: it failed.** Bundling bought **+0.006** stability against a fair
baseline; the bar was **+0.10**. The reason is the "early finding" this section
originally flagged, taken to its conclusion: the bundles ERCOT actually produces are
*tiny* — overwhelmingly the same physical element under different contingency labels
— so merging them is correct but irrelevant. The map's week-to-week movement comes
from the **congestion regime rotating**, not from credit flip-flopping inside small
blocks, and grouping was aimed squarely at the second thing. Nobody had checked
whether the blocks were even large enough for the fix to bite; they weren't (only
1.1× compression). So **grouping does not ship, the node explorer and every signed
per-constraint claim stay blocked, and the identifiability problem remains open for a
different attack.** The simpler `bp = max|SF|` layer is untouched and survives. Full
story in `plan/0083-summary.md`.

### A worked example: what the matrices actually look like

It helps to see this in the `C = −M · SFᵀ` matrices from §3, because there's a
common mix-up hiding in the word "decompose." First, the object model:

- A **constraint** (bottleneck) — say a line "DAL_HOU" — is *one* thing. It has
  **one shadow price per hour**: a single number that's `0` when it isn't binding
  and `> 0` when it is.
- A **node** (Dallas, Houston, Austin, …) is where a *price* is observed
  (~1,084 of them).
- A **shift factor** links the two: `SF[node, constraint]` = how much congestion
  at *that node* moves when *that constraint* binds by \$1 of shadow price.

So a single constraint isn't split "into a Dallas part and a Houston part."
Instead the one constraint DAL_HOU has a **whole column of shift factors**, one
per node — `SF[Dallas, DAL_HOU]`, `SF[Houston, DAL_HOU]`, … That mapping
(constraint → its effect at each node) is **not** the hard part; the regression
recovers it fine. The thing we genuinely *can't* pull apart is different: **two
separate constraints that always bind together.** Here's why, in numbers.

Take a toy world — **3 hours, 3 nodes** (Dallas, Houston, Austin), **2 constraints**
(X, Y).

**M — shadow prices** (`hours × constraints`). Published; an input.

```
              X      Y
 hour 1 │   10      0    │   ← only X binding, at $10
 hour 2 │    0      5    │   ← only Y binding, at $5
 hour 3 │    8      4    │   ← both binding
```

**SF — the shift-factor map** (`nodes × constraints`). The unknown we solve for.

```
              X      Y
Dallas  │   0.5    0.3   │
Houston │   0.2    0.7   │
Austin  │   0.1    0.1   │
```

**C — congestion** (`hours × nodes`). Observed from prices (`LMP − system-λ`); the
regression *target*. Each cell is `C[t,node] = −Σ_c M[t,c]·SF[node,c]` — e.g.
hour 3 at Dallas is `−(8·0.5 + 4·0.3) = −5.2`:

```
                Dallas   Houston   Austin
 hour 1 │       −5.0     −2.0     −1.0    │   = −10 · (X row)
 hour 2 │       −1.5     −3.5     −0.5    │   = −5 · (Y row)
 hour 3 │       −5.2     −4.4     −1.2    │   = −(8·X + 4·Y)
```

The pipeline observes **M and C** and solves **backwards for SF** — the reverse of
that arithmetic — one regression per node.

**When decomposition works.** Look at **M**: X and Y each bound *on their own* at
least once (hour 1: X alone; hour 2: Y alone). That independent variation is
exactly what lets the fit separate them — it got to see what X does without Y and
vice-versa — so it pins `SF[Dallas,X]=0.5` and `SF[Dallas,Y]=0.3` distinctly. No
problem.

**When it breaks (the twin case).** Now suppose X and Y are the *same line under
two contingencies* and **always bind together in fixed proportion** — whenever X
is \$10, Y is \$5:

```
              X      Y
 hour 1 │   10      5    │
 hour 2 │    6      3    │        column Y = 0.5 × column X   ← collinear
 hour 3 │    8      4    │
```

Now the two columns of M carry no independent information. Dallas's congestion is
always:

```
C[t,Dallas] = −( μ_X·SF[Dallas,X] + 0.5·μ_X·SF[Dallas,Y] )
            = −μ_X · ( SF[Dallas,X] + 0.5·SF[Dallas,Y] )
```

The data only ever constrains the **combination** `SF[Dallas,X] + 0.5·SF[Dallas,Y]`.
Infinitely many splits give identical congestion — `(0.5, 0.3)` fits exactly as
well as `(0.65, 0.0)` or `(0.2, 0.9)`. The regression picks one arbitrarily, and
because the tiny random wiggle that tips the choice differs each refit, **the split
flips week to week.** *That's* the "can't decompose" problem — not one constraint
across nodes, but credit between two constraints that never move apart.

**What grouping does.** Stop fighting the unwinnable fight: if X and Y always move
together, **sum their columns before fitting** and solve one shift factor for the
bundle.

```
   m_g[t] = M[t,X] + M[t,Y]        ← one merged shadow-price column
   solve  SF[Dallas, group]         ← one honest, stable number
```

We recover the one thing the prices actually determined — the group's total effect
on each node — and stop reporting a fake, flip-flopping split. So if there really
were a separate "Dallas constraint" and "Houston constraint" that always fired
together, we'd quit pretending to say how much each individually contributes and
report their combined, stable effect, because that combined number is the only
thing the data ever told us. (Note that a single constraint *named* for a corridor
is **not** ambiguous by itself — it has one shadow price and a clean per-node SF
column. Ambiguity appears only when **two constraints** are statistical twins,
which is why the grouping code merges on correlation *between constraint columns*.)

### A connection worth noting: GTCs

ERCOT already publishes some **composite** constraints — *Generic Transmission
Constraints* (GTCs: West Texas Export, Panhandle, North-to-Houston, …), engineered
stability/voltage limits rather than single thermal lines. A GTC is a hand-drawn
bundle of underlying elements — which makes it **ERCOT's manual version of exactly
the co-binding groups we discover statistically here.** Two clarifications follow:

- **GTCs are already in the data.** They bind in the DAM and carry shadow prices
  (NP4-191) like any other constraint, so they're already columns in **M** and the
  SF fit already uses them — no special handling; they're anonymous keys among the
  rest. The big ones are among ERCOT's most persistent, most *regime-driven*
  congestion drivers (West Texas Export tracks wind output), making them prime
  μ-model covariate targets.
- **GTCs are *not* outages.** A GTC is a *constraint* (a column/target in μ — what
  we predict); an outage is a *driver* (an element out of service that makes
  constraints more likely to bind — the R4 covariate, §4). Different objects: one
  is the thing forecast, the other is a feature that helps forecast it.

---

## 8. The code — what each main path does

Everything for the product lives in `compute/sf/`. Follow the data:

| File | In plain terms |
|---|---|
| `ercot_ingest/` | Downloads the public ERCOT data (prices, shadow prices, load & weather forecasts) and stores it. The raw material. |
| `compute/sf/panels.py` | Builds the two big tables everything runs on: **M** (shadow prices) and **C** (congestion). |
| `compute/sf/fit.py` | The ridge regression (§3). Given M and C for a window, solves for the **shift-factor map**. The math core — deliberately small and pure. |
| `compute/sf/rolling.py` | Runs the fit **repeatedly on a moving window** — refit every week on the trailing 240 days, like a rolling average. The grid changes over seasons, so the map keeps re-learning. |
| `compute/sf/grouping.py` *(new, 0083)* | Finds bottlenecks that move together and bundles them into groups *before* the fit. The identifiability fix from §7. |
| `compute/sf/eval.py` *(new, 0082)* | **The honest grader.** Trains on the past, grades on the unseen next week, and scores the map every way in §9. Every trustworthy number comes from here. |
| `compute/sf/sweep_ibp.py` | **The auto-tuner.** Tries many setting combinations, grades each with the honest grader, picks the winner. How we found `(240 days, λ=1.0)`. |
| `compute/sf/coverage_probe.py` *(new, 0082)* | Answers "is a missed bottleneck a seasonal regular or genuinely new?" — the coverage-gap question in §6. |
| `compute/sf/persist.py` + `runner.py` | Save results to the database; provide the command-line entry point. The plumbing. |
| `compute/sf/metric.py` | Reduces the full map to one simple per-location number, `bp = max|SF|` ("binding proximity"). The older, simpler product layer — it sidesteps the grouping problem and survives no matter how 0083 lands. |

**Frozen / not part of the product:** the original physics simulation
(`compute/legacy/`, the `experiments/` folder). Kept runnable for the writeup, but
removed from the live pipeline.

---

## 9. How we grade the map — the metrics, in plain terms

The grader (`eval.py`) scores each week several different ways, because "is the
map good?" has several different answers depending on what you want from it. They
split into two **currencies**:

- **Magnitude** — did we get the actual dollar amounts right?
- **Screening** — did we get the *ranking and direction* right (which nodes are
  hot, up or down), even if the exact dollars are off?

A tool can be a great screener while being mediocre on magnitude. That's why we
report both and never collapse them into one number.

| Metric (`eval.py`) | Currency | What it answers | Scale |
|---|---|---|---|
| **R²** (`oos_pooled_r2`) | magnitude | "What fraction of the congestion's variation does the map explain?" | 1.0 = perfect · 0 = no better than guessing the average · negative = worse than that |
| **rank-Spearman** (`rank_spearman`) | screening | "Does the map rank the nodes in the right order — are the ones it calls most-congested actually the most congested?" It correlates *ranks*, not raw values, so it ignores magnitude errors and outliers. | 1 = perfect order · 0 = unrelated · −1 = reversed |
| **sign-agreement** (`sign_agree`) | screening | "Does the map get the *direction* right — is congestion helping or hurting this node?" Congestion can be + or −. A ±$1 deadband ignores near-zero node-hours where the sign is just noise. | fraction correct; 0.5 = coin flip |
| **top-decile hit** (`topdecile_hit`) | screening | "Of the 10% worst-congested nodes this hour, how many did the map also flag in its worst 10%?" This is the trader's question: *show me the hot spots.* | fraction caught; 0.10 = chance |
| **coverage** (`coverage`) | (diagnostic) | "What share of this week's congestion came from bottlenecks the map actually has a column for?" The complement of the §6 gap (≈0.81 covered ⇒ 19% gap). Reported *alongside* skill because it explains the collapse weeks. | fraction; higher = fewer blind spots |
| **stability / drift** (`sf_stability`, `sf_decay`) | (diagnostic) | "How much does the map itself change between refits?" A map that's accurate but rewrites itself every week is hard to build a product on. | correlation of the map now vs. a later map; 1 = unchanged |
| **group churn** (`group_churn`) | (diagnostic, 0083) | "Do the bottleneck *groups* keep the same members across refits?" If groups reshuffle weekly, the node explorer built on them can't be trusted. | membership overlap (Jaccard); 1 = identical |

A few of these deserve a sentence more:

- **"pooled" R²** just means it's computed over all node-hours thrown into one
  pot, rather than averaged per node. It's the headline magnitude number.
- **"OOS" (out-of-sample)** means the map was fit on data *ending strictly before*
  the week being graded — the honesty rule from §6. The dishonest in-sample
  version (`is_pooled_r2`, the old 0.986) is kept side-by-side only to show how
  big the inflation was.
- **"oracle μ"** on the R² means we feed the grader the bottleneck pains that
  *actually* happened, to isolate the *map's* quality from any error in
  *forecasting* which bottlenecks bind. It's the ceiling — the best the map could
  do if the forecast were perfect. The forecast (the roadmap, §11) is graded
  separately.
- **Stability has two flavors.** `sf_stability` correlates the map on one window
  against the map on the immediately-preceding, *non-overlapping* window of the
  same length — the honest refit-to-refit drift (~0.47 at the old settings, ~0.83
  at the new ones). The **decay curve** (`sf_decay`) is the same idea stretched
  out: correlate the map at time *t* against the map Δ days later, for growing Δ,
  to see *how fast* it goes stale. (A subtlety the code is careful about: Δ has to
  be at least as large as the window, or the two fits *share hours* and you'd be
  measuring overlap instead of drift.)
### Every score sits on a benchmark ladder

No metric means much alone — each is read against reference forecasts of
increasing sophistication that the map must sit *between* and beat:

| Benchmark | What it does | Role |
|---|---|---|
| **Oracle** | Feed in the **true μ that actually happened**, then apply SF. Uses future info — not a real forecast. | **Ceiling** — the best possible *if μ-forecasting were perfect*; isolates the SF map's own quality (**0.787** re-measured in the fair harness; **0.762** top-decile). |
| **Climatology** | Predict the **seasonal normal** — the typical value for this time of year / regime. | "Dumb but not stupid" baseline; wins on **magnitude** vs persistence. |
| **Persistence (24h)** | Predict **tomorrow = today**. | The naive "no change" baseline; **negative R² but wins top-decile (0.561)** — the one screening metric that matters. |
| **Null** | No skill — the mean, or random order. | **Floor** (R²≈0, Spearman 0, sign 0.5, top-decile 0.10). |

So oracle is the ceiling and null is the floor; **persistence is the bar in the
middle** a real model must clear to justify itself. The pre-registered existence
test is literally *beat persistence in the screening currency.* Oracle isn't a
competitor — it's the yardstick for how much headroom the *spatial* map has versus
how much is left for the *μ-forecast* (§4) to earn.

> **What actually happened (0085, §0):** the μ-forecast **did not** clear that
> middle bar — it loses persistence's top-decile 0.523 to 0.561. And the numbers in
> this table are the *fairly re-measured* ones: the figures the roadmap originally
> quoted (oracle 0.746, persistence's top-decile 0.649) came from a retired
> operating point and an older harness, and re-measuring them on identical weeks
> through the same map is what exposed the false "no-lose" premise. **A baseline
> that is never re-measured when the operating point moves is not a floor, it is a
> souvenir.**

---

## 10. Why window size matters (and it's two knobs, not one)

Two separate settings control the rolling fit, and they're easy to conflate:

- **Window length** (`window_days`, now 240) — *how much trailing history each
  fit uses.*
- **Refit cadence** (`refit_days`, 7) — *how often we re-run the fit.*

**Window length** trades **stability and coverage against adaptiveness:**

- **Longer window** → more hours in the fit → more bottlenecks clear the 25-hour
  bar (**higher coverage**), the regression is better-conditioned and less noisy
  (**more stable**, coefficients flip less) — but it's **slower to react** to a
  genuine change in the grid, and it can blur a sensitivity that is truly
  shifting over the season.
- **Shorter window** → **adapts faster** to new bottlenecks and seasonal shifts —
  but it's **noisier**, fewer bottlenecks clear the bar (**lower coverage**), and
  the map is **less stable** (more week-to-week flipping).

The honest re-sweep found **240 days beats 60 on all three at once** — accuracy,
coverage, *and* stability. That's the tell that the old 60-day window wasn't
buying adaptiveness; it was just **starving the fit of data.** The grid's
sensitivity map turns out to be fairly persistent, so more history helped
everywhere with little adaptiveness cost.

**But that's exactly why window length is *not* the lever for the coverage gap.**
Making the window longer to swallow more bottlenecks would drag in stale history
and re-introduce the very instability we just removed. The right lever for novel
bottlenecks is the *other* knob — a **faster refit cadence** (and mid-week
incorporation), which brings new bottlenecks into the map sooner *without*
lengthening the history each fit trusts. Length = how much past to trust;
cadence = how quickly to notice the present. The coverage gap is a
*cadence/novelty* problem, not a *window-length* one.

---

## 11. The roadmap — why the steps are in this order

The guiding principle: **run the cheap experiments that could kill the plan
*before* the expensive building.** Each step retires a specific risk. Here is how
they actually resolved — the principle held, but three of them closed by *failing*,
which is exactly what a cheap-first risk map is for (§0 has the one-line table):

1. **R1 — Honest grading + re-tune.** *Done (0082).* ✅ Cheap, and it changed the
   settings everything else depends on, so it went first: window 60→240, λ 0.1→1.0.
2. **R2 — Is the 19% coverage gap seasonal (easy) or new (hard)?** *Done (0082,
   revisited 0084).* ✅ "Half and half — no free lunch," and the 240-day window
   already collected most of the seasonal memory a library would have (§6).
3. **R3 — Does grouping raise stability?** *Done (0083).* ❌ **Failed** — +0.006 vs
   a +0.10 bar; the co-binding blocks are too small to matter. The node explorer and
   signed per-constraint claims stay **blocked** (§7).
4. **R4 — Can we link real-world outages to the constraints?** *Done (0085).* ⛔ The
   name-join works (98% of force); the transmission-outage **feed is unreachable**
   (Market-Participant-only secure area). Degraded to a crude zonal aggregate.
5. **R5 — Does the full forecast beat a dumb baseline?** *Done (0085).* ❌ **Failed,
   and it was never "no-lose."** The forecast loses top-decile to persistence, and
   the safety-net baseline that made it look no-lose was a stale souvenir (§0, §9).

**The second-generation phase — chasing R5's failure (still live):**

6. **R6/R7 — RUC, the one genuinely *new* signal?** *Done (0087).* ⛔ **Dead** — no
   reliability run at or before market close describes the next day, at any archive
   depth. **RUC is no longer on the table anywhere in the plan.**
7. **R8 — Was the model just under-specified?** *In flight (0088).* Add the missing
   cheap covariates — lagged shadow prices, geography, weather response — in one
   ablation. Most likely finding: lagged μ was a plain defect fix.
8. **R9 — Is there a *public* outage feed after all?** *In flight (0089).* A public
   *generation*-outage feed, reachable and legal to serve, placed per-constraint
   through the map. Not the transmission feed R4 wanted; lift vs the zonal aggregate
   is pending the run.

The full sequence, as it ran: honest grading → grouping (failed) → coverage
decomposition → forecast modeling (failed R5) → chase the failure with cheap
covariates and a public generation-outage feed. Product surfaces (node explorer,
daily forecast map, alerts) wait on a forecast that clears the bar — except the one
that ships **now regardless**: the honest skill-decomposition scoreboard (§0).

---

## 12. The one-paragraph summary

We're turning ERCOT's public price data into a live map of *what's congesting the
grid and where* — by exploiting an accounting identity that lets us recover the
grid's sensitivity map from prices alone (via a rolling ridge regression), no
physical model needed. We caught and fixed our own inflated accuracy claim (the
honest number is ~75%, not ~98%) and re-tuned on it. We then tried to steady the
map by bundling always-together bottlenecks (**it didn't help**), and to forecast
tomorrow's congestion (**it doesn't yet beat "same as yesterday"** at the job a
screener is for). Those failures are the point, not a detour: they were run cheaply
and recorded honestly, and they localized the whole problem to one place — **the map
is solved, forecasting *which* elements strain is not**, and the model is losing
largely because it can't see which elements are out of service. The live work
(0088/0089) is about adding that missing information back — cheap covariates the
model never had, and a public generation-outage feed. The single thing that ships
today regardless of how those land is the honest scoreboard itself: a public,
self-grading measurement of exactly how good the map is and exactly where the
forecast falls short.
