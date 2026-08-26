# ERCOT Constraints, Shift Factors, and the Centroid Artifact
<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [ERCOT Constraints, Shift Factors, and the Centroid Artifact](#ercot-constraints-shift-factors-and-the-centroid-artifact)
  - [1. Naming structure](#1-naming-structure)
  - [2. Two families of constraint](#2-two-families-of-constraint)
    - [Thermal element — a real branch (your textbook line)](#thermal-element--a-real-branch-your-textbook-line)
    - [Generic Transmission Constraint (GTC) — an interface, not a line](#generic-transmission-constraint-gtc--an-interface-not-a-line)
  - [3. The centroid flaw: a vector reduced to a point](#3-the-centroid-flaw-a-vector-reduced-to-a-point)
  - [4. Identifying noise and low-support constraints](#4-identifying-noise-and-low-support-constraints)
    - [Why `binding_hours` is the wrong filter](#why-binding_hours-is-the-wrong-filter)
    - [What the artifact actually looks like — the ridge clamp](#what-the-artifact-actually-looks-like--the-ridge-clamp)
    - [The verdict and guardrails](#the-verdict-and-guardrails)
  - [5. Reading one node across constraints](#5-reading-one-node-across-constraints)
    - [The SF map audits its own geocodes](#the-sf-map-audits-its-own-geocodes)
  - [6. Reproducing this: the queries and the co-binding result](#6-reproducing-this-the-queries-and-the-co-binding-result)
    - [Reach — which nodes a constraint drives](#reach--which-nodes-a-constraint-drives)
    - [Driver profile — the co-binding study](#driver-profile--the-co-binding-study)
    - [The audit — SF vs stored coordinates](#the-audit--sf-vs-stored-coordinates)
- [Congestion and Shift Factors](#congestion-and-shift-factors)
  - [Constraints and Shadow Prices](#constraints-and-shadow-prices)
  - [Shift Factors](#shift-factors)
    - [Shift Factor Interpretation: sign, import/export, color](#shift-factor-interpretation-sign-importexport-color)
    - [Worked example](#worked-example)
    - [The mixture](#the-mixture)
    - [Real example: WESTEX | BASE CASE](#real-example-westex--base-case)
    - [The SF is flat; the shadow price is the switch](#the-sf-is-flat-the-shadow-price-is-the-switch)
    - [Color convention](#color-convention)
  - [Constraint contribution and nodal congestion](#constraint-contribution-and-nodal-congestion)
    - [Forecast versus ERCOT DAM contribution](#forecast-versus-ercot-dam-contribution)

<!-- markdown-toc end -->

What a "constraint" actually is in the shadow-price feed, how the two families
differ, and why locating one at its |SF|-weighted centroid is often meaningless.

## 1. Naming structure

Every constraint key is `MonitoredElement | Contingency` — **what is watched**
and **under what outage**. ERCOT never monitors an element in the abstract; it
monitors it *for a specific contingency*.

```
HARGRO_TWINBU1_1 | DBAKCED5     watch Hargrove–Twin Buttes ckt 1 WHEN contingency DBAKCED5 trips
VALEXP           | BASE CASE    watch the Valley Export interface with the full system intact
```

The right-hand side is the contingency, not a place:

- **`BASE CASE`** — no contingency. The limit binds with every element in
  service, i.e. a *chronic, structural* limit (not one that only appears after
  a failure).
- **`S…` / `D…` / `M…`** — an N-1 (or N-2) outage code; the letters encode the
  element(s) that trip (`S` single, `D` double, …). Most binding constraints
  are these: "monitor X for the loss of Y."

Keys are treated as opaque strings in this project (`strip(name)|strip(cont)`);
geography is recovered from *which settlement points respond*, never from the
name.

## 2. Two families of constraint

Both appear in the same feed and look alike, but they are different objects.

### Thermal element — a real branch (your textbook line)
`STATIONA_STATIONB_kV_ckt | contingency`, e.g. `LPLMK_LPLNE_1|SBWDDBM5`,
`138_FTS_LNC_1|BASE CASE`. A single physical line or transformer between two
substations, limited by its **MVA/thermal rating**. Its shift factor **is** the
branch PTDF. These are the constraints whose centroids are trustworthy — one
local element, compact reach.

### Generic Transmission Constraint (GTC) — an interface, not a line
`SHORTNAME | BASE CASE`, e.g. `VALEXP` (Valley Export), `PNHNDL` (Panhandle),
`WESTEX` (West Texas export), `NELRIO`. A named limit on an **interface** — a
whole *cutplane of lines* — usually set by an offline **stability study**
(voltage/transient), not a conductor rating. The constrained quantity is
Σ(flows across the boundary) ≤ X MW. There is no single "VALEXP line"; it is a
boundary. Its shift factor is the **sum of its member branches' PTDFs** (a
generalized shift factor onto the interface).

| | Thermal element | GTC / interface |
|---|---|---|
| Key looks like | `A_B_kV_ckt \| cont` | `SHORTNAME \| BASE CASE` |
| Physical object | one branch | a cutplane of branches |
| Limit set by | thermal rating | stability study |
| Shift factor | branch PTDF | Σ branch PTDFs |
| Centroid useful? | usually yes | no (see §3) |

**Shift factors, correctly.** A PTDF is indexed by *(branch, bus)*; for one
branch the vector spans **every bus in the network**, not just buses "on" the
line. Buses electrically behind the branch have high |PTDF|; the sign splits the
grid into two sides (the price **dipole**). In DC-OPF, node congestion is
`congestion_i = −Σ_c GSF[c,i]·μ_c`, so this project's price-space `SF[i,c]`
equals that generation shift factor. `SF ≈ 0.80` at a Rio Grande Valley node on
`VALEXP` means ~0.80 MW of a 1 MW injection there loads the Valley interface —
the pocket is radially fed *through* the boundary, so the whole pocket shares
~0.80. That uniform cluster is the cleanest possible shift-factor signature.

## 3. The centroid flaw: a vector reduced to a point

Each constraint is located at the **|SF|-weighted centroid** of the settlement
points it drives (`compute/sf_map/geography/derive.py`). That reduces a whole SF *vector* to one
(lat, lon), and the reduction is only honest when the vector is a **single
compact blob**. It fails in two common cases:

1. **Sharp peak + diffuse tail.** Every node in ERCOT responds *a little* to a
   big interface. For `VALEXP`, 55% of |SF| mass is the tight RGV pocket at
   ~26.2°N, but 45% is spread thin statewide. The weighted mean is a tug-of-war
   and settles at **Corpus (~27.9°N)** — a latitude where almost no mass
   actually lives. The mean of "the Valley" and "everywhere else" is not a place.

2. **Interfaces are rings.** A GTC's member lines *ring* the pocket, so the mass
   is a ring/pocket and the mean is its empty center. GTCs are therefore exactly
   the constraints where the centroid is *least* meaningful.

**Consequences.**
- The centroid encodes spatial *concentration* inversely: a local constraint
  gets a good pin; a spread one is dragged toward the ERCOT centroid (~31°N).
  `geo_spread_km` is the map's own measure of how much to distrust the pin.
- Fixing bad geocodes does **not** fix this. Relocating four mis-placed RGV
  batteries moved the `VALEXP` centroid only ~0.2° — still Corpus. The Corpus
  placement is a property of the *method*, not the data.
- The physically meaningful object is the **SF vector / reach cluster**, not the
  single point. To place a marker in the pocket, locate to the **peak**
  (top-k centroid → ~26.7°, inside the Valley) or draw the reach directly rather
  than one centroid for high-spread constraints.

## 4. Identifying noise and low-support constraints

Not every constraint's SF is trustworthy — but **the tell is the *shape* of the
SF vector, not the hour count.** These are all real, binding constraints on real
price data; "low confidence" here means the *fitted* SF is a numerical artifact,
not that the constraint is fake.

### Why `binding_hours` is the wrong filter

The intuitive filter is "few binding hours ⇒ weak fit." It fails in both
directions, because what actually matters is whether the regression column is
**identifiable** — was the constraint the dominant binding element in its hours,
or always co-binding with a collinear neighbor the ridge can't separate? Hours is
only a lagging proxy for that, and a bad one:

| constraint | binding_h | peak \|SF\| | shape | verdict |
|---|---|---|---|---|
| `TRDWEL\|BASE CASE` | 48 | 0.453 | smooth taper, 0 railed | **clean** |
| `35050__B\|DTHSFBR5` | 34 | 0.512 | smooth taper, 0 railed | **clean** |
| `PLC_KAME_1\|SPORNCA9` | 46 | 0.806 | graded dipole (+/− lobes), 0 railed | **clean** |
| `6429__D\|DMTSCOS5` | **82** | **1.000** | **3 nodes at ±1, cliff to <0.2** | **artifact** |

The three "clean" ones bind *fewer* hours than the artifact. An hours filter
(`binding_hours < 50`) flags all three as low-confidence — **false positives** —
and would have *passed* `6429__D` (82 h) if not for a separate clip check. Hours
is demoted to a secondary **"thin support"** annotation: a caveat, never a
verdict.

### What the artifact actually looks like — the ridge clamp

SFs are unitless in [−1, 1]; the ridge solve caps at ±1 (`SF_ABS_CAP`). A node
pinned at exactly `±1.000` is **railed**. Railing is not itself an error —
|SF| = 1.0 is the signature of a **radially-fed** node (100% of an injection
crosses the element), and a genuine radial *resource* legitimately rails. What
smells is the pattern the ill-conditioned solve leaves behind: **several nodes
co-equal at the cap, geographically scattered, detached from the body by a
magnitude cliff** — the solve couldn't resolve the collinearity, so it dumped the
shared response onto a few columns at the cap and left everything else at the
noise floor.

Two persisted shape scalars capture this (`compute/sf_map/geography/persist.py`):

- **`n_rail`** — nodes with `|SF| ≥ 0.999`. A radial *pocket* plateaus just
  *under* the cap (`VALEXP`: 61 nodes at ~0.80); a radial *resource* rails
  **one** node. **≥ 2** co-equal at the cap is the clamp.
- **`peak_offrail`** — the top of the graded body beneath the rail (max \|SF\|
  among non-railed nodes). A rail with a real body under it is a resource; a rail
  with `peak_offrail ≈ 0` is an isolated spike.

**The single-rail contrast** — same node, `JUNG_SLR_RN`, on two elements:

| constraint | n_rail | peak_offrail | reading |
|---|---|---|---|
| `BELCNTY_XFMR\|SFRYTMP8` | 1 (`JUNG_SLR` −1.0) | 0.258 | one solar plant radial behind a transformer, atop a coherent local decay → **keep** |
| `PLC_KAME_1\|SPORNCA9` | 0 (`JUNG_SLR` −0.806) | — | same plant, unclamped, clean graded dipole → **keep** |

`JUNG_SLR` railing on one element but landing at a clean −0.806 on another shows
its true coupling is ~0.8; the −1.0 is a mild clamp of that, not a new fact. A
*single* rail that is the peak of a coherent, geographically-local graded body is
a radial resource — trustworthy. Contrast `6429__D`: **three** co-equal rails
spanning 330 km (San Angelo ↔ central TX), detached by a cliff — the clamp.

The old worked example still holds under this rule: `SCARBI_TITAN_1_1|MVCRAN89`
stacks ~4 Brownsville nodes at −1.0 then cliffs to <0.04, so `n_rail ≥ 2` flags
it. Its Houston "reach" nodes are `argsort` scraping the floor after the real
signal runs out — not a corridor.

### The verdict and guardrails

**Low confidence** := `n_rail ≥ 2` **or** (`n_rail ≥ 1` **and**
`peak_offrail < 0.10`). Everything else — including any unclipped graded SF, and a
lone rail atop a real body — is trusted geometry, optionally tagged *thin
support* if `binding_hours < 50`.

1. **Reach magnitude floor** (`GET /map/reach?min_frac=`, default 0.05). Drops
   nodes with `|SF| < min_frac · peak|SF|`, so top-k can't pad a weakly-fit
   constraint with noise-floor nodes. `SCARBI_TITAN` returns 6 nodes, not 15;
   `VALEXP`'s pocket is unaffected.
2. **Low-confidence overlay badge** (`GridMap.tsx`, `DetailCard.tsx`). A
   constraint meeting the rail verdict renders muted slate with a "low confidence
   — ridge clamp" note; a merely thin one keeps full color with a "thin support"
   caveat.

**Rule of thumb:** unclipped, or one rail atop a graded body, with a smooth
falloff → trust the geometry (however few the hours). Several nodes pinned at the
cap, scattered, with a cliff to the floor → treat the SF as unidentified and
ignore its map position. (And even a trustworthy SF still gets an untrustworthy
*centroid* if it is spatially spread — §3.)

## 5. Reading one node across constraints

**A shift factor is per-constraint. A node has no absolute "import/export"
identity — only a sign relative to a specific element.** The same node reads
differently on two constraints because each is a different electrical cut:

| node | on `VALEXP\|BASE CASE` | on `HAINE__LA_PAL1_1\|MHARNED5` |
|---|---|---|
| `MV_VALV4_RN` (Mission) | **+0.82** — deep inside the pocket | **−0.15** — on the relief side |

`VALEXP` is the Valley's **outer boundary** (pocket vs the rest of ERCOT); every
node inside reads strong positive. `HAINE__LA_PAL` is a **single line inside** the
Valley; it splits the RGV into two sub-areas and `MV_VALV4` lands on the relief
side. Two orthogonal cuts → same node, opposite signs. No contradiction.

Magnitude also tells the type: a **boundary** (VALEXP, family-2 monopole)
separates the whole pocket → strong, uniform (~±0.8); an **internal line**
(HAINE, family-1 dipole) redistributes among neighbors → weak, graded (~0.1–0.5)
with a real + and − cluster.

### The SF map audits its own geocodes

A node whose position looks geographically wrong for a constraint has **two**
possible causes; the node's *whole driver profile* tells them apart:

- **Mis-geocode** (trust the SF, fix the map): the node's strongest drivers are
  **all** one region's constraints. `CFLAT_ES_RN` was geocoded to West Texas but
  has `VALEXP` +0.74 and every top driver is an RGV constraint (HAINE, HARLNS,
  LASPUL…). It cannot be 74% coupled to the Valley interface from Midland — it is
  a Valley node ("Citrus Flatts" → Citrus City BESS, Mission) plotted wrong.
- **Ridge leakage** (a real fit artifact): the node responds anomalously to
  **one** co-binding constraint while its *other* drivers stay consistent with its
  true location. This is the co-binding collinearity caveat (§4), not a mis-map.

The tell is coherence: one query — *nodes with pocket-level `VALEXP` \|SF\| but
geocoded outside the RGV* — surfaced four mis-geocoded storage/mobile resources
(`CFLAT`, `MESQUITE_RN/RN2`, `E_HARRIS`) whose fuzzy name-match had matched the
wrong "Citrus"/"Mesquite". **The implied-SF map is a geocode auditor:** electrical
coupling is ground truth the name-based geocoder never sees.

## 6. Reproducing this: the queries and the co-binding result

Two tables back everything above (`run_id = 'map-v1'`):

- **`implied_shift_factors(run_id, window_start, constraint_key, settlement_point, sf)`**
  — one row per fitted SF per refit window. This is the reach.
- **`constraint_geo(run_id, window_start, constraint_key, lat, lon, spread_km,
  max_abs_sf, binding_hours, …)`** — the derived per-constraint centroid (§3).

Settlement-point coordinates are **not** in the DB; they live only in
`data/processed/settlement_points_geocoded.csv`. So any *geography* question is a
join across the DB and that CSV. Every query below pins to the latest refit
window with:

```sql
WITH w AS (SELECT max(window_start) AS ws
           FROM implied_shift_factors WHERE run_id='map-v1')
```

### Reach — which nodes a constraint drives

```sql
SELECT settlement_point, round(sf::numeric,3) AS sf
FROM implied_shift_factors, w
WHERE run_id='map-v1' AND window_start=w.ws
  AND constraint_key='VALEXP|BASE CASE'
ORDER BY abs(sf) DESC LIMIT 12;
```

`VALEXP` returns a **plateau** — 61 nodes at |SF|≈0.80 (`MV_VALV4_RN` 0.824,
`FRONT_EC_CC1` 0.822, `RIOG_ESR_RN` 0.817, …), the whole RGV pocket fed through
the interface. Swap the key to `HAINE__LA_PAL1_1|MHARNED5` and you instead get a
**graded dipole** (`CFLAT_ES_RN` −0.525, `HARLIN_1_RN` −0.330, then a + cluster
`LAUR_BESS_RN` +0.142, `RN_SR_WIND1` +0.132) — the internal-line signature of §5.

### Driver profile — the co-binding study

Flip the filter: hold the *node* fixed and rank its constraints. This is the
co-binding check that tells mis-geocode from ridge leakage.

```sql
SELECT constraint_key, round(sf::numeric,3) AS sf
FROM implied_shift_factors, w
WHERE run_id='map-v1' AND window_start=w.ws
  AND settlement_point='CFLAT_ES_RN'
ORDER BY abs(sf) DESC LIMIT 8;
```

**Result** — the two suspect nodes' entire profiles are RGV constraints:

| driver | `CFLAT_ES_RN` | `E_HARRIS_RN` |
|---|---|---|
| `VALEXP\|BASE CASE` | **+0.736** | **+0.785** |
| `HARLNS_OLEAND1_1\|MTGURIO5` (Harlingen) | −0.556 | −0.410 |
| `HARLNS_OLEAND1_1\|MTGULAP5` | −0.564 | −0.374 |
| `HAINE__LA_PAL1_1\|MHARNED5` | −0.525 | −0.281 |
| `HAINE__LA_PAL1_1\|SRAYRI38` | −0.578 | −0.350 |
| `LASPUL_RAYMND1_1\|MHARNED5` (La Sara/Pull) | −0.394 | — |
| `LOYOLA_69_1\|SKINKLE8` | +0.397 | — |

**Every strong driver is a Valley element.** A node cannot be 74–79% coupled to
the Valley Export interface *and* sit in West Texas / east Houston, so the SF is
right and the geocode is wrong — **mis-geocode confirmed, not ridge leakage.**
(Ridge leakage would show *one* anomalous co-binding constraint while the node's
*other* drivers stayed consistent with its true location — not a wall-to-wall RGV
profile.) Both were re-placed in the pocket (`CFLAT` → Citrus City BESS, Mission)
or dropped as unplaceable (`E_HARRIS`, `MESQUITE`), so they no longer drag the
`VALEXP` centroid.

### The audit — SF vs stored coordinates

Because coordinates are not in the DB, run the audit as an export + pandas join:
high-|SF| `VALEXP` nodes that were geocoded *outside* the RGV (lat > 28) are the
suspects.

```sql
-- SQL: pocket-level VALEXP nodes → valexp_hi.csv
SELECT settlement_point, round(sf::numeric,3)
FROM implied_shift_factors, w
WHERE run_id='map-v1' AND window_start=w.ws
  AND constraint_key='VALEXP|BASE CASE' AND abs(sf) >= 0.5
ORDER BY abs(sf) DESC;
```

```python
import pandas as pd
sf  = pd.read_csv('valexp_hi.csv', names=['settlement_point','sf'])
geo = pd.read_csv('data/processed/settlement_points_geocoded.csv',
                  usecols=['settlement_point','lat','lon'])
audit = sf.merge(geo, on='settlement_point').query('lat > 28')  # pocket SF, not in the Valley
```

Pre-fix this returned the four mis-geocoded nodes. **Post-fix it returns zero** —
all 61 pocket-level nodes now geocode inside the RGV (or, for `E_HARRIS`/`DC_R`,
carry no coordinates at all and are excluded from the centroid). That empty result
is the regression test for the whole geocode cleanup.

---

# Congestion and Shift Factors

The core relationship is:

```text
congestion[sp, t] ≈ -Σc SF[c, sp] × μ[c, t]
```

where:

- `sp` is a settlement point;
- `c` is a transmission constraint;
- `t` is a delivery interval;
- `SF[c, sp]` is this project's recovered, implied shift factor; and
- `μ[c, t]` is a constraint shadow price, either forecast by the project or published
  with the ERCOT Day-Ahead Market.

This gives the tool three complementary lenses:

- The **map** supplies geographic orientation and communicates import/export lobes.
- The **matrix** exposes the recovered coefficients and exact congestion arithmetic.
- The **scorecard and playback history** show whether the model worked out of sample
  and how the result changed over time.

For an analyst, the matrix is a factor-exposure and relative-value screening
surface. For a market operations or market-analysis user, it is a
constraint-risk forecast, decomposition, and post-market review surface. In both
cases it remains a research aid: the implied factors do not replace ERCOT's
market model, topology, or participant-only data.

## Constraints and Shadow Prices

A transmission constraint limits a monitored network element under a base case or a
contingency. When the modeled flow reaches its limit, the constraint may bind. Its
shadow price, `μ`, measures the marginal system cost of relaxing that limit by one
unit under the market optimization.

A high shadow price therefore indicates expensive congestion pressure on a constraint.
It does not, by itself, say which settlement points gain or lose. That spatial
distribution is supplied by shift factors.

## Shift Factors

A shift factor describes how an incremental injection or withdrawal at a location
changes flow on a monitored constraint, relative to the market's reference convention.
The sign identifies which side of the interface the location occupies; the magnitude
describes sensitivity.

The matrix is indexed as:

```text
SF[constraint, settlement point]
```

The project uses its own documented sign convention. Users should compare formulas,
not informal labels such as “import” or “export,” when reconciling another source's
convention.

### Shift Factor Interpretation: sign, import/export, color

These are **implied shift factors (SF)** — recovered by ridge regression from the
price identity `congestion = −Σ_c SF[c, sp] · μ[c]` (see `compute/sf_map/model/fit.py`),
where `μ ≥ 0` is a constraint's shadow price. They are an econometric proxy for
ERCOT's network sensitivities, **not** ERCOT's published PTDF/DFAX.

A shift factor is a *sensitivity*: `SF[c, sp] = ∂(flow on constraint c) /
∂(injection at sp)`, measured relative to a **reference bus** — i.e. it's the
effect of moving 1 MW *from the reference to that node*, not a lone injection.
Values are unitless and clipped to `[−1, 1]` (`SF_ABS_CAP`); magnitudes above 1
out of the ridge solve are treated as numerical artifacts.

For a single binding constraint (`μ > 0`), a node's congestion price is `−SF·μ`:

| SF sign | Congestion price | Side | Physical meaning | Color |
|---------|-----------------|------|------------------|-------|
| **SF < 0** | **↑ high** (positive) | **import** | receiving end — *relieves* the constraint, but the pocket is still a **net importer** of power | 🔴 red |
| **SF > 0** | **↓ low / negative** | **export** | sending end — *aggravates* the constraint; generation is trapped behind the limit | 🔵 blue |

The key subtlety: **"relieves the constraint" and "net importer" are the same
fact, seen at two different moments.** The shift factor is a *marginal*
(derivative) quantity — what the *next* MW does. "Importing" describes the node's
*current* state.

### Worked example

Constraint `A–B` is a monitored transmission element that's binding (maxed out).
Node A has `SF = −0.5`.

**What SF = −0.5 means:** move 1 MW from the reference to A, and flow on the
constraint drops by 0.5 MW. (Only half of that transfer routes through this
element — topology sets the magnitude; the sign says it *relieves* the element.)

**Why A relieves it:** picture A inside a load pocket fed by an import line that's
the binding constraint.

- 100 MW load, 40 MW local generation → the pocket **imports 60 MW** across the
  line, which is at its 60 MW limit → binding.
- Inject 1 MW of local generation at A → 41 MW local, **59 MW imported**. The
  line carries less → flow drops → `SF_A < 0`.

**Why A is still "importing":** after the injection the pocket still imports
59 MW. A did **not** become an exporter — it imports *slightly less*. Local
generation at A **substitutes for imported energy** that would otherwise have to
cross the constraint; that's *why* it's valuable there, and it's only valuable
because A was short (import-constrained) to begin with.

> `SF < 0` at A  ⟺  injecting relieves the line  ⟺  A is a net importer  ⟺  A's
> congestion price is high. All one fact.

A would only flip to export (`SF > 0`) if you piled in enough local generation to
exceed local load and push power *out* across the line.

### The mixture

A real constraint has two sides, so the physically typical signature is a
**mixture**: some member nodes `SF < 0` (import, red) and some `SF > 0` (export,
blue) — the constraint is the seam between a load pocket and a generation pocket.
An all-one-sign constraint usually means the opposite lobe's nodes fell below the
display floor or weren't geolocated, not that it doesn't exist. The meaningful
signal is the **split**, because sign is measured against a reference.

### Real example: WESTEX | BASE CASE

A West Texas export interface (base-case / N-0 limit). At a glance the panel shows
*only export* nodes — but the full SF row (1,043 nodes) has both lobes:

| Lobe | count | peak \|SF\| | \|SF\|-weighted centroid |
|------|-------|-------------|--------------------------|
| export (SF>0) | 743 | **0.82** | 32.2, **−101.0** (West Texas wind/solar) |
| import (SF<0) | 300 | **0.17** | 30.2, **−96.6** (central-east load) |

The export lobe is a tight cluster of West Texas renewables (`BAIRDWND`, `ANSON`,
`RRC_WIND`, `*_SLR`) all at ~0.8; the import lobe is real but **~5× weaker and
diffuse**, so no import node cracks the top-20-by-|SF| panel view. Hence "all
constituents export" is a *display artifact*, not physics.

Reading: this constrains **exports out of West Texas** (= imports into the east
*from* the west) — the west is the trapped-generation **sending** end, not an
importer. A constraint that limited imports *into* the west would put the strong
lobe on the import (SF<0, red) side instead.

### The SF is flat; the shadow price is the switch

Injecting at an export node (SF>0) loads the constraint — that's what *makes* it a
constraint (the limit caps that flow). But the SF itself does **not** decline to
zero or flip as you inject: it's a property of the wires (topology + reactances),
constant regardless of loading. Flow rises linearly (slope = SF) until it hits the
limit; at that instant the **shadow price μ jumps from 0 to positive**.

| State | SF (export node) | μ | congestion = −SF·μ |
|-------|------------------|---|--------------------|
| below limit | +0.8 (flat) | 0 | 0 — costless |
| binding | +0.8 (flat) | >0 | −0.8·μ < 0 — priced down |

So the node's *price* is ~0 until binding, then jumps negative — but that's **μ**
flipping on, not the SF changing. SFs only move when **topology** changes (a line
trips), which is why constraints are `MonitoredElement + Contingency` pairs.

### Color convention

**Import = red, export = blue**, everywhere in the app (map fill, legend, reach
glow, constraint panel, node popover, detail card). This matches ISO price-map
convention (high LMP = red/hot, low = blue/cool): import is scarce and expensive
(red), export is trapped and cheap (blue). Note this is the *opposite* of a raw
diverging colormap of the SF value itself (where positive would be red) — we
color by the **import/export price meaning**, i.e. by the sign of `−SF`, so the
SF-sign layers agree with the congestion fill by construction.


## Constraint contribution and nodal congestion

For a selected constraint, settlement point, and hour:

```text
contribution[c, sp, t] = -SF[c, sp] × μ[c, t]
```

Total modeled congestion at the settlement point is the column sum:

```text
congestion[sp, t] = Σc contribution[c, sp, t]
```

This distinction matters. A point can have large exposure to several constraints but a
small net congestion price because positive and negative contributions cancel:

```text
Constraint A contribution   +$35/MWh
Constraint B contribution   -$28/MWh
Constraint C contribution    -$6/MWh
                            -----------
Net nodal congestion         +$1/MWh
```

The gross activity is still economically important. The small net is not evidence that
the node is structurally quiet.

### Forecast versus ERCOT DAM contribution

The matrix should expose two contribution calculations:

```text
Forecast contribution
    = -implied SF × predicted μ

ERCOT DAM contribution
    = -implied SF × published DAM μ
```

Only the shadow-price source changes. Neither mode uses an official ERCOT shift factor.
Before DAM results exist, ERCOT DAM contribution is **unavailable**, not zero. After
publication, comparing the two modes helps separate:

- a missed constraint activation or shadow-price magnitude; from
- a weakness in the recovered spatial relationship.
