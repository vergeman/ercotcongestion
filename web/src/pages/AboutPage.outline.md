# `/about` — working outline & build checklist

**Audience & boundary.** `/about` answers *"what does this tell me and why trust
it."* Keep it narrative and visual. The full model math stays in
`docs/MODELS.md`; metric mechanics (source IDs, cadence, pooling) stay in
`docs/METRICS.md`. Link out — don't restate. The only intentional overlap with
the README is the one-line what-is-this hook (§1), reworded for a reader.

## Framing — the spine (north star for §1–§2 copy)

One claim, three layers — the whole page hangs off this. Present them as a
hierarchy, **not** three co-equal features:

1. **The novel core — the constraint / shift-factor map.** Recover the hidden
   transmission limits that actually price ERCOT congestion, from public price data
   alone. This is the wedge — the thing no public map shows (→ §3).
2. **The evidence — the map is validated, not guessed.** The recovered shift factors
   reproduce observed nodal congestion, and match ERCOT's own electrically-similar-point
   list (ESSP) **20/20** — a check the model never trained on. Lead with this; it's the
   strongest grade on the whole project (→ §3.2, §5).
3. **The application — the forecast, graded honestly.** Predict tomorrow's shadow
   prices, project them to nodes, grade every call against persistence in the open.
   Persistence is a hard bar and often wins — *say so*; the honesty is the credibility
   (→ §4, §5, §7).

Positioning line: **not** "a congestion forecaster" (that invites the one comparison it
loses) — it's **"a grid-structure explorer with an honest forecasting layer."** The core
is the validated map; the forecast is rigorous research built on top.

## Content sections

### [ ] 1. Hero — what & why
- The problem: where and when does the ERCOT grid congest, priced a day ahead.
- Narrative version of the README hook (only intentional overlap).
- Does NOT cover: repo structure, how to run.
- [ ] **SCREENSHOT/VIDEO:** hero — the Map in motion. Prefer a short looping
      **video/GIF** of playback (the "watch it move" autoplay), else a still.

> **STUB — owner to write the hook wording.** There is no README hook to reword:
> `README.md` is currently a one-line placeholder (`# Shifty`), so §1 is original
> copy, not an overlap. What the hook must land, in ~2–3 sentences:
> - **What:** a day-ahead forecast of *where* and *when* the ERCOT grid congests —
>   nodal congestion (`SPP − system λ`), one day ahead, at every settlement point.
> - **Why it's different:** it surfaces the transmission constraints driving that
>   congestion — the hidden control layer no public map shows (→ §3, the payoff).
> - **Trust:** every forecast is graded against what actually settled, in the open
>   (→ §5).
> Boundary: no repo/how-to-run. Keep it a reader's hook, not a spec line.

### [ ] 2. The four surfaces
- What **Brief / Map / Matrix / Scoreboard** each show and when to use each.
- Does NOT cover: metric formulas (→ §5).
- [ ] **SCREENSHOT (×4):** one shot per surface — Brief, Map, Matrix,
      Scoreboard. Small/tiled, captioned.

**Draft copy.** The same day-ahead forecast, read four ways. Start at the Brief;
open the others when you want the *where*, the *arithmetic*, or the *track record*.

- **Brief — the day in one page.** The plain-language readout: which constraints
  are expected to bind tomorrow and which nodes carry the most congestion, ranked.
  Start here. *Use it when* you want today's call without touching the machinery.
- **Map — where it happens.** The forecast in geographic space: each constraint's
  electrical footprint over Texas, import (red) / export (blue) lobes, and a
  playback scrubber to watch congestion move hour by hour. *Use it when* the
  question is *where* and *when*.
- **Matrix — the arithmetic, exposed.** The recovered shift-factor coefficients
  and the exact `congestion = −Σ SF·μ` sum behind any node — a factor-exposure and
  relative-value screening surface. *Use it when* you want to see *why* a node
  prices the way it does, constraint by constraint.
- **Scoreboard — does it work?** The out-of-sample track record: the model graded
  against persistence, a trailing-average baseline, and an oracle ceiling, over
  time (→ §5). *Use it when* you want to know whether to trust any of the above.

### [ ] 3. Constraints: the hidden control layer ⭐ (signature section)
The differentiator — surfaces and locates something no public map shows.
Conceptual + visual; all ridge/geo math stays in `docs/MODELS.md` (link from 3.2).

- [ ] **3.1 What a constraint is** — a transmission limit; when the grid hits
      it, it *binds* and a shadow price μ appears. Invisible on any public map.
  - **Draft copy.** The grid runs on wires with limits. A *constraint* is one
    monitored piece of the network — a specific line or transformer, watched under
    a specific "what if this other thing fails" contingency (ERCOT names them
    `MonitoredElement | Contingency`). When forecast flow reaches that element's
    limit, the constraint **binds**, and the market puts a price on it: the
    **shadow price μ**, the marginal cost of relaxing the limit by one more MW. A
    high μ means expensive pressure at that point in the grid. ERCOT publishes
    these shadow prices, but as opaque keys with no location attached — so you can
    see *that* something is binding, never *where* it sits or *what* it does to
    prices around it. That gap is what this tool closes.
- [ ] **3.1b Kinds of constraint** — three flavors, because they behave and locate
      differently (all math/geo detail → `docs/MODELS.md`):
  - **Transmission** — a specific monitored line or transformer at its thermal limit.
    The common case; locates to a **corridor** between two stations
    (`STNA_STNB_N` = line STNA→STNB, circuit N).
  - **Radial** — a single line feeding a pocket with no parallel path, so *all* the
    pocket's flow rides one element. Prone to sharp, localized price spikes (Rabbit Hill
    is the archetype); locates to a **tight cloud** at the pocket.
  - **GTC (Generic Transmission Constraint)** — an operator-defined *interface* limit
    across a whole region (a stability/voltage envelope, not one piece of steel). Its
    footprint is a **ring around a pocket**, not a point — the centroid can sit in empty
    space (this is the §3.2 "interface = ring" caveat). Often binds as `BASE CASE`.
  - **Reading the key** (`MonitoredElement | Contingency`): contingency prefix
    `S`/`D`/`B` = single / double / breaker outage; **`BASE CASE` = binds pre-contingency,
    i.e. in normal steady-state operation.** A bare number (`6437__F`) is a numeric bus
    element with no place content — located by zone only.
- [ ] **3.2 Locating it electrically (no name-matching)** — a constraint key has
      no coordinates, but its shadow price co-moves with congestion at every
      node; ridge-solving that identity gives a shift-factor row → an
      |SF|-weighted centroid = its implied location. Link to `docs/MODELS.md`.
  - [ ] **SCREENSHOT:** Map SF overlay — a located constraint's footprint
        (cloud/corridor/ring) over Texas.
  - **Draft copy.** A constraint key is just a string — no latitude, no longitude.
    But it leaves a fingerprint in prices. Every hour a constraint binds, its
    shadow price moves congestion at every settlement point in lockstep, through
    one identity: `congestion = −Σ SF·μ`. Feed a trailing window of realized
    prices into that identity and solve — by ridge regression, **prices in, shift
    factors out, no weather, no calendar, no station-name lookup** — and each
    constraint hands back a **shift-factor (SF) row**: how hard it pushes price at
    each node. Because every node carries a known lat/lon, that row *places* the
    constraint — its footprint is wherever its price influence concentrates. A
    compact constraint resolves to a tight cloud or corridor; a wide interface
    resolves to a ring around a whole pocket. (One honest caveat: collapsing a
    footprint to a single centroid pin is only faithful when it's compact —
    interfaces are rings whose center is empty, so the tool shows the *footprint*,
    not just a dot. The full recovery + geolocation math is in
    [`docs/MODELS.md`](../../../docs/MODELS.md).)
- [ ] **3.3 How constraints create the congestion you see** — `congestion =
      −Σ SF·μ`; a bound line lifts price one side, depresses the other; that
      spread *is* nodal congestion. Walk one constraint → node price map.
  - **Draft copy.** Nodal congestion isn't a property of a node — it's the sum of
    what every binding constraint does to it: `congestion = −Σ SF·μ`. Take one
    binding line. Its shadow price μ is a single number for the hour, but its SF
    row has two signs: nodes on the receiving side get their price **lifted**,
    nodes on the sending side get their price **pushed down**. That spread across
    the grid *is* nodal congestion — the same price separation you'd see in the
    day-ahead LMP map, now decomposed into the constraints that caused it. One
    node's final price is the sum of every constraint's contribution
    (`−SF·μ`), and those can cancel: a node with large exposure to three
    constraints can still net near zero if the pushes and pulls offset. The gross
    activity is real even when the net is quiet.
- [ ] **3.4 Import / export flows** — sign convention: **SF<0 = import = red,
      SF>0 = export = blue** (color by −SF; see `docs/SF.md`). What each side of
      a binding constraint means physically.
  - **Draft copy.** The sign of a shift factor tells you which side of the
    bottleneck a node sits on. **SF < 0 = import = red:** the receiving end — a
    load pocket pulling power across the limit; its congestion price is *high*
    because energy there is scarce and expensive. **SF > 0 = export = blue:** the
    sending end — generation trapped behind the limit with nowhere to go; its
    price is *low* or negative. (The app colors by the price meaning, `−SF`, so
    red always reads "scarce/expensive" the way any ISO price map does.) A real
    binding constraint is usually a **mixture** — red on one side, blue on the
    other, because it's the seam between a load pocket and a generation pocket. An
    all-one-color constraint normally just means the opposite lobe is weaker or
    off-screen, not that it isn't there. Full sign/color convention and worked
    examples:
    [`docs/Constraints_and_Shift_Factors.md`](../../../docs/Constraints_and_Shift_Factors.md).
- [ ] **3.5 The always-on constraints** — the handful that bind near-constantly
      and effectively govern regional flow. The "no one really sees this" payoff.
  - [ ] **DATA:** pull real names/frequencies from `/map/constraints/ranked`,
        the μ top-ten feed, or ESSP. **Do not invent.**
  - [ ] **CAVEAT:** brief-feed binding frequency is a *lower bound* — say a
        constraint *"appeared"* often, not that it *"bound"* N times.
  - [ ] **SCREENSHOT:** the ranked-constraints panel and/or the always-on
        constraint located on the map.
  - **STUB — awaiting data agent.** Prose frame is ready; the concrete names and
    numbers are the only gap. Drop-in shape once data lands:
    > *"A small number of constraints do most of the work. In the trailing
    > [WINDOW], the interfaces that appeared most often were [CONSTRAINT_A]
    > ([N]× / [X]% of days, [region]), [CONSTRAINT_B] …" — each with its located
    > footprint.*
    Data slots to fill (real values only): **constraint keys** (2–4), their
    **appearance frequency** phrased as *"appeared"* not *"bound N times"*
    (lower-bound caveat), the **window/date range** the counts cover, and the
    **region** each governs. Source: `/map/constraints/ranked`
    (predicted|realized), μ top-ten feed, or ESSP.

### [ ] 4. How the forecast works
- Two-head μ prediction: *if* it binds (`P(bind)`) × *how hard* (`E[μ|bind]`),
  multiplied, then projected to nodes. Builds on §3 (what a constraint is).
- Does NOT cover: ridge details, the ~86-covariate table (→ `docs/MODELS.md`).
- [ ] **DIAGRAM:** two heads → multiply → project. Simple, inline SVG.

**Draft copy.** §3 explained what a constraint is and how it prices the grid. The
forecast predicts the one moving part it can't observe yet: tomorrow's shadow
prices. Standing at day-ahead-market close the evening before delivery day *D*, it
asks, for every hour of *D* and every candidate constraint, two separate
questions:

1. **Will it bind?** — a probability, `P(bind)`.
2. **If it binds, how hard?** — the expected shadow price, `E[μ | bind]`.

Multiply them and you get the expected magnitude for that hour-and-constraint,
`E[μ] = P(bind) × E[μ | bind]`. Splitting the question in two is deliberate: the
"how hard" model trains **only on hours that actually bound**, so it estimates a
real congestion event instead of being averaged toward zero by the many quiet
hours. Both models read the same inputs — the grid's expected state for that hour
(load, wind, solar, outages, calendar) plus each constraint's own recent history
and its electrical location from §3. Finally, those expected shadow prices are
projected back through the shift-factor map (`−Σ SF·μ`, §3.3) to a congestion
number at every node. The full input catalog (~86 features) and the ridge/
gradient-boosting details live in [`docs/MODELS.md`](../../../docs/MODELS.md).

### [ ] 5. What we measure
- What **Rank ρ**, **Top-Decile Hit**, **Sign Agreement** *mean* and why each
  exists; Brief **Detection / Magnitude / Timing** in plain language.
- The baselines as honesty rails: **persistence**, **climatology**, **oracle**.
- Does NOT cover: source-catalog IDs, cadence/pooling (→ `docs/METRICS.md`).
- [ ] **SCREENSHOT:** a Scoreboard grade tile / the track-record chart.

**Draft copy.** A forecast is only worth as much as its track record, so every
prediction is graded after the fact against what actually settled. Three
higher-is-better measures, each asking a different question of the same day:

- **Rank ρ** — *did we order the grid right?* Each hour, rank every node by how
  congested we said it would be, rank them by how congested they actually were,
  and correlate the two orderings. It rewards getting the *relative* map right,
  even if the dollar levels are off.
- **Top-Decile Hit** — *did we find the worst spots?* Of the 10% most-congested
  nodes that actually occurred, how many did the forecast also put in its
  top 10%. This is the "where does it hurt" question, isolated.
- **Sign Agreement** — *right side of the line?* For each node, did we get the
  direction right — priced up vs. priced down relative to system price — pooled
  across the day (small deadband ignored).

A single number in isolation can flatter, so the model is **never shown alone**.
It always sits next to its honesty rails:

- **Persistence** — just repeat yesterday. Deceptively strong, and the bar the
  model actually has to clear (→ §7).
- **Climatology** — a trailing-window average. The "no information" baseline.
- **Oracle** — a non-deployable ceiling built from the *realized* shadow prices.
  It shows how much of the miss is bad shadow-price forecasting versus the limit
  of the map itself.

The Brief grades a related but distinct question — its own **Detection**
(did the constraints/nodes that mattered rank near the top), **Magnitude** (did
the amounts agree), and **Timing** (did they land in the right hours) — on the
constraint and node profiles rather than nodal Scoreboard rows; a good Brief
grade and a good Scoreboard grade don't imply each other. Exact definitions,
cadence, and source catalog: [`docs/METRICS.md`](../../../docs/METRICS.md).

### [ ] 6. Case studies — load-window walkthroughs
- 2–3 real days: a load-ramp / heat event → what the model called, what settled,
  how it scored vs persistence. Ties §3–§5 to a concrete story.
- [ ] **DATA:** use actual graded days from Scoreboard/Brief — **real numbers
      only**. Candidate dates TBD (ask owner or pick from graded history).
- [ ] **SCREENSHOT (per case):** the map at the event hour + its grade.

- [ ] **LEAD CASE — open with "Far West Sign Flip" (`farwest_diurnal_2025_jun20`,
      Jun 20–21 2025).** Best teacher for §3: the *same* constraint's dipole **flips
      polarity within a day** — overnight the Permian *imports* across saturated 138 kV
      (+$34/MWh, red lobe dominant), midday 5.6 GW of local solar saturates the *export*
      paths and it goes −$24/MWh (blue lobe dominant). One event shows binding, the
      import/export sign convention (§3.4), and the dipole *moving*.
  - Pair it with a **static** teaching image first — one **West Texas** always-on
    constraint's footprint — to introduce the two lobes before showing them flip. Use
    **`LPLMK_LPLNE_1`** (115 kV, West, appeared 96.7% of days), *not* a South/Coast one.
  - [ ] **SCREENSHOT / TIMESTAMPED LINK:** the Map at the overnight cursor
        (`cursor_ts` `2025-06-21T00:00Z`) **and** a midday hour, so the sign flip is
        visible. A live timestamped link (`/map?...&t=...`) works if a static shot can't
        show the motion.
  - ⚠️ **Geography guard:** keep the lead example **in the West**. Do **not** use
    `E_PASP|BASE CASE` — despite the "E_P" it's a **South Texas** GTC (not El Paso, which
    is WECC), so it doesn't belong in a Far West walkthrough.

**STUB — awaiting data agent (+ owner date picks).** Structure is fixed; only real
days and numbers are missing. Each case study follows the same beat so §3–§5 pay
off in a story:
> **[DATE] — [event, e.g. a west-Texas evening load ramp].**
> *Setup:* what the grid was doing (heat / ramp / low wind). *Call:* which
> constraint(s) the model flagged and where (ties to §3). *Settled:* what actually
> bound and how the congestion map looked (§3.3). *Score:* the day's Rank ρ /
> Top-Decile / Sign Agreement **vs. persistence** (§5) — real graded numbers only.

Data slots per case (2–3 total): **delivery date**, **the driving constraint(s)**,
**forecast vs. settled** outcome, and the **graded metrics with the persistence
comparison**. Pull from Scoreboard/Brief graded history — **do not invent**.
Prefer days that visibly exercise §3 (a located interface governing the event).

### [ ] 7. Honest limits
- Persistence is hard to beat; the SF map drifts (in-sample vs OOS R² gap);
  binding is rare (~3% of hours). Set expectations plainly.

**Draft copy.** This is a research aid, not a market oracle. Four things to keep in
mind:

- **Persistence is a hard bar.** The grid mostly looks like it did yesterday, so
  "repeat yesterday" scores well on all three measures. Beating it is the real
  test, and the margin is often thin — which is exactly why the model is always
  shown next to it (§5).
- **The map drifts.** The shift factors are refit on a trailing window and the grid
  keeps changing, so a footprint fit on the past doesn't perfectly describe the
  future. On data the fit has seen it reproduces prices almost exactly (R² ≈ 0.99);
  out of sample that falls to ≈ 0.75, and only about half the map's structure
  survives from one disjoint window to the next. The Map sidebar surfaces these
  numbers rather than hiding them.
- **Binding is rare.** Most hours, most constraints do nothing — bind events are a
  small fraction of all hour-and-constraint cells. The forecast is a needle-finding
  problem, and a quiet day is the common case.
- **These are implied, not official.** The shift factors are recovered from prices
  by regression — an econometric proxy for ERCOT's network sensitivities, not
  ERCOT's published PTDFs or market model. And a spread-out interface is better
  read as a footprint than a single pin (§3.2). Treat the output as a lens on the
  market, not a replacement for it.

## Asset checklist (screenshots / video)
- [ ] hero video or still (§1)
- [ ] Brief / Map / Matrix / Scoreboard shots (§2)
- [ ] SF footprint overlay (§3.2)
- [ ] ranked-constraints / always-on shot (§3.5)
- [ ] Scoreboard tile or track chart (§5)
- [ ] one map+grade per case study (§6)
- [ ] Decide asset home (e.g. `web/public/about/` for served images).
