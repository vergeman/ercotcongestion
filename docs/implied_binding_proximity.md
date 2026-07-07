# market_implied_binding_proximity: an ERCOT-side counterpart to binding_proximity

## Purpose

`binding_proximity` is a model-side metric: for each bus,
`max_ℓ |PTDF[ℓ,b]| · loading_ℓ` — how strongly does this bus drive whichever
branch is most heavily loaded. It requires a network model (PTDF) and an OPF
solution (flows), so it has no direct ERCOT equivalent: ERCOT does not publish
a public PTDF matrix, and its binding constraints are named transmission
elements with no lat/lon and no correspondence to settlement points.

`bp_ercot` (market-implied binding proximity) reconstructs the same quantity
from public ERCOT market data alone, at settlement-point granularity, so the
two can be shown side by side on the map.

The key insight: **constraint locations are never needed.** A binding
constraint anywhere on the grid moves the price at every settlement point in
proportion to that point's shift factor on it. The geography lives entirely on
the SP side, which is already geocoded. Constraints remain anonymous string
keys whose location is revealed implicitly by which SPs light up.

## Definitions

| Term | Meaning |
|------|---------|
| **SP** | Settlement point: a priced ERCOT location (resource node, hub, load zone). The dots on the map. |
| **SF** | Shift factor: ERCOT's term for PTDF. Fraction of 1 MW injected at an SP that flows across a given constraint. |
| **μ (shadow price)** | $/MWh value of relaxing a binding constraint by 1 MW. Zero when not binding. |
| **Congestion component** | `SPP − reference price` per SP per interval (already computed in the pipeline). |

## The identity that makes it possible

In any DC-OPF-based market clearing (including ERCOT's DAM), the congestion
component of each SP's price is, by construction:

```
congestion[sp, t] = − Σ_c  SF[sp, c] · μ[c, t]
```

This is not an approximation or a correlation — it is the equation the market
optimizer itself uses to build LMPs. Both sides of it are observable:

* `μ[c, t]` — published per binding constraint per interval.
* `congestion[sp, t]` — already computed from published SPPs.

The only unknown is the SF matrix. Because constraint shadow prices fluctuate
independently over time (one binds Tuesday evening, another Wednesday noon),
the differential response of each SP across many intervals identifies its
sensitivity to each constraint. Estimation is a linear regression; the
equation itself is exact, so with sufficient data the recovered SFs approach
the true DAM shift factors (diagnostic: regression R² → 1).

## Datasets

| Dataset | Report | Role |
|---------|--------|------|
| DAM Shadow Prices | **NP4-191-CD** (public, per DAM run) | μ, limit, and value per active/binding constraint per hour. Website posting retains ~30 days; pull history via the ERCOT Data Portal archive / Public API (`/np4-191-cd/dam_shadow_prices`) or `gridstatus.get_shadow_prices_dam`. |
| DAM Settlement Point Prices | **NP4-190-CD** (public) | Source of the SP congestion decomposition (already in pipeline). Same OPF solve as NP4-191 → the identity holds exactly. |
| SP geocoding | NP4-160-SG + EIA-860 fuzzy match | Lat/lon per SP (already in pipeline). |
| *(RT variant)* SCED Shadow Prices | NP6-86-CD (public, per SCED run) | Same role for real-time. Noisier: 15-min SPP averaging over 5-min SCED runs blurs the identity. Keep DAM and RT regressions separate — different constraint sets and network models. |

Sources considered and rejected: the 60-Day SCED Disclosure (NP3-965-ER)
contains telemetry, base points, and offer curves but **no shift factor
columns**. ERCOT's hourly "Shift Factors by Resource Node" posting (Nodal
Protocols §6.5.7.1.13, NPRR280) would give SFs directly but may require MIS
market-participant access; the regression approach needs only public data.

## Methodology

1. **Constraint panel.** Key each constraint as
   `strip(ConstraintName) + '|' + strip(ContingencyName)` — a string ID only.
   Pivot NP4-191 to a matrix `M` of shape `(hours × constraints)` of shadow
   prices, zeros where not binding.
2. **Congestion panel.** Existing decomposition, pivoted to `C` of shape
   `(hours × SPs)`.
3. **Rolling ridge regression.** Over a 60-day window (re-fit every
   `--refit-days` days, default 7), keep constraints with ≥ `--min-binding-hours`
   binding hours (default 10; a coefficient cannot be identified for a
   constraint that never moves), then solve

   ```
   C ≈ − M · SFᵀ        (ridge-regularized least squares)
   ```

   per SP. Sign convention: positive SF = injection at that SP loads the
   constraint, matching PTDF convention. Hours with no binding constraints are
   valid observations (congestion ≈ 0) and stay in the panel.
4. **Metric.** Per hour:

   ```
   bp_ercot[sp, h] = max over constraints binding in h of |SF_implied[sp, c]|
   ```

   NP4-191 publishes only binding rows (μ > 0), so the "loading fraction"
   term from the model-side metric is identically 1 and drops out. Hours
   with no binding constraint yield `bp_ercot = 0` for every SP, matching
   the model side on quiet hours.
5. **Map.** Every value lands on a geocoded SP. Toggle against model-side
   `binding_proximity` per snapshot.

Implementation: `compute.implied_binding_proximity.runner` (rolling window,
default weekly re-fit, npz output at `runs/<run_id>/ibp/bp_ercot.npz` with
per-refit-window diagnostics JSON alongside).

## Relation to model-side metrics

| Model side | ERCOT side | Sensitivity term | State term |
|---|---|---|---|
| `binding_proximity` = max \|PTDF\|·loading | `bp_ercot` = max \|SF_implied\|·loading | Distributed-slack PTDF (topology) | Value/Limit from NP4-191 / NP6-86 |
| `modeled_congestion` = Σ PTDF·μ | congestion component (existing) | — | — |

Structural asymmetries to disclose on the map:

* The ERCOT side only sees constraints ERCOT activated/enforced; the model
  side sees the full loading gradient across all branches. For apples-to-apples
  views, the model metric can be restricted to binding branches.
* Model PTDFs come from ACTIVSg2000 topology; implied SFs come from the real
  grid. Divergence between them is itself signal, not noise.

**Bonus validation:** for constraints whose station names are recognizable,
implied-SF rows can be checked against distributed-slack PTDF rows of matched
model branches — a direct test of the slack-weighting choice from the
`binding_proximity` fix.

## Empirical sanity check (2025-07-23, single day)

A demo ridge regression on one day (24 hours, top-8 constraints by Σμ) —
deliberately under-specified — still recovered real electrical structure. For
constraint `15060__B|SW_LVLT5` (Vealmoor–Koch Tap 138 kV, West Texas), the
largest implied |SF| landed on Lamesa Solar (32.7N, −101.9W), Alpine BESS
(32.7N, −101.9W), Gun Mountain (32.2N, −101.5W), and Russek (31.2N, −101.5W) —
all within ~50 miles of the constraint — despite the regression never seeing a
location. Overall R² was poor (only 8 of 217 constraints included on 24
observations), confirming the need for the pooled multi-week window; two
far-field SPs in the top set were contamination from omitted correlated
constraints, which the full-column pooled regression removes.

## Worked example: the matrices, populated

Real numbers from 2025-07-23, cut down to 6 hours (HE15–20), 2 constraints,
and 3 SPs so the algebra is visible. In production the same shapes are
~1,440 hours × ~100 constraints × ~1,034 SPs.

**`M` — shadow-price panel (hours × constraints), $/MWh, from NP4-191:**

```
h    15060__B|SW_LVLT5   HARGRO_TWINBU1_1|DBAKCED5
15         0.0                    0.0
16         0.0                    0.0
17         0.0                    0.0
18         8.4                    0.0
19        16.6                    5.2
20        47.9                    4.0
```

**`C` — congestion panel (hours × SPs), $/MWh, from the existing
decomposition:**

```
h    GUNMTN_NODE   HB_HOUSTON   LAMESASLR_G
15      -4.07         17.98        -4.31
16      -0.16         19.40        -4.50
17       1.96         18.97        -1.30
18       8.86         18.87         7.05
19      22.22         17.18        36.46
20      54.18          7.24        57.76
```

Read the co-movement directly: when `15060__B` goes 0 → 8 → 17 → 48,
GUNMTN and LAMESA swing by ~$50 while HB_HOUSTON barely reacts. That
differential response *is* the shift-factor information.

**Solving `C ≈ −M · SFᵀ`** (ridge, fit on all 24 hours) gives
`SF = −(MᵀM + λI)⁻¹ MᵀC`:

```
                            GUNMTN_NODE   HB_HOUSTON   LAMESASLR_G
15060__B|SW_LVLT5              -0.370       -0.014        -0.342
HARGRO_TWINBU1_1|DBAKCED5       0.071        0.008         0.083
```

Interpretation: a 1 MW injection at GUNMTN_NODE changes flow on the
`15060__B` element by ~0.37 MW (sign = direction relative to the monitored
flow); Houston's coupling is ~0.01, i.e. electrically irrelevant to this
West Texas constraint. Note the toy fit omits the other ~130 constraints
active that day, so residual congestion (e.g. HB_HOUSTON's steady +$18
level) is unexplained here — the pooled full-column regression absorbs it.

**`bp_ercot` for HE20** — both constraints binding (loading = 1), so per SP
take the max |SF| over the active set:

```
GUNMTN_NODE:  max(|-0.370|, |0.071|) = 0.370
HB_HOUSTON:   max(|-0.014|, |0.008|) = 0.014
LAMESASLR_G:  max(|-0.342|, |0.083|) = 0.342
```

For HE15 (nothing binding among these): bp_ercot = 0 for all three. On the
map, HE20 lights up West Texas and leaves Houston dark — mirroring what the
model-side `binding_proximity` shows when a West Texas branch binds.

## GTC constraints

Generic Transmission Constraints (WESTEX, PNHNDL, NE_LOBO, etc.) are ERCOT's
interface-style constraints: a defined group of transmission elements whose
aggregate flow is capped by a (stability-driven, often dynamically updated)
Generic Transmission Limit. Each GTC is enforced as its own base-case
constraint in CRR, DAM, and SCED — so **they already appear in NP4-191-CD /
NP6-86-CD as ordinary constraint rows** (typically with contingency
`BASE CASE`) and need no special handling: the pipeline treats a GTC key
exactly like a thermal-line key.

Two properties worth knowing:

* Their SF footprint is wide — an interface between regions couples to
  hundreds of SPs, unlike a local thermal constraint — so GTC columns tend to
  dominate broad map patterns (all of West Texas lighting up under WESTEX).
  That is correct behavior, not contamination.
* Their limits move with system conditions (updated as often as every 10
  minutes in real time), so the `Value/Limit` loading term is only meaningful
  within-report; never assume a static GTL across days.

Model-side caveat: ACTIVSg2000 has no GTC equivalents (thermal limits only),
so GTC-driven congestion is a *structural divergence* between the two map
layers — worth calling out in validation rather than treating as model error.

## Known limitations

* **Collinear constraints** (always bind together) cannot be separated —
  group them into a composite key; `bp_ercot` takes a max, so attribution
  within the group is not needed.
* **Rare constraints** (< min binding hours) are dropped from the SF matrix
  and skipped in the max; their congestion lands in the residual.
* **Topology drift** within the window (outages, upgrades) blurs SFs — the
  reason for the rolling re-fit.
* **Reference-price error** in the congestion decomposition leaks into the
  regression; a falling R² is the first symptom.
* **MCL residual bias.** The regression input is
  `congestion = LMP − system_lambda`, which is `MCC + MCL` — the marginal
  cost of losses is folded in. ERCOT publishes no SP-level MCL feed to
  subtract, so losses appear as an R² ceiling below 1 and a small,
  systematic bias for SPs far from load centers. R² < 1 on the diagnostic
  is expected; treat it as a residual to note, not a failure signal.
* **RT variant** inherits all of the above plus temporal-averaging noise;
  treat DAM as the headline layer.

## Diagnostics

The runner writes one JSON per refit window under
`runs/<run_id>/ibp/diagnostics_YYYYMMDD.json` (the date is the score-period
start). Each file records how trustworthy that week's fit is:

| Field | Meaning |
|---|---|
| `window_start` / `window_end` | Trailing window used for the fit (window_end is exclusive). |
| `score_start` / `score_end` | Interval this fit was used to score (exclusive end). |
| `n_fit_hours` | Rows the ridge saw. |
| `n_constraints_in_window` | Distinct constraint keys with any binding row in the window. |
| `n_kept` / `n_dropped` | Constraints above / below `--min-binding-hours`. |
| `r2_overall` | R² of the fit on the training rows. Read against the MCL bias caveat above — a plateau well below 1 is expected, not a failure. |
| `per_sp_r2` | R² per settlement point; useful for spotting SPs where the fit is systematically off. |
| `kept_constraints` | List of `{key, binding_hours}` for constraints that survived the filter, sorted by binding hours. |
| `dropped_constraints` | Same shape, for constraints filtered by `--min-binding-hours`. |

## FAQ

### Aren't there far more constraints than SPs, with no overlap?

Constraints don't need to *be at* SPs — the coupling is electrical (through
the SF), not a name or location match. The full-year constraint universe is
large, but only ~5–20 bind per interval and a few dozen recurring constraints
explain most congestion rent. Intervals with no binding constraints are not
missing data: `bp_ercot ≈ 0` everywhere is the correct answer, matching the
model side on quiet days.

### Is this "just a proxy"?

For the DAM, no: the identity is exact by construction; only SF estimation is
imperfect, and R² measures how imperfect. Near 1, the recovered SFs are
essentially the true DAM shift factors. If R² is materially below 1, present
the layer as an approximation and say so.

### How were constraint locations known in the sanity check?

They weren't used in the computation. NP4-191 happens to include
From/To station names; when recognizable (VEALMOOR → near Big Spring, TX),
they provide a free after-the-fact spot check that the top-|SF| SPs cluster
where the constraint physically sits. Many station names are cryptic — the
method does not depend on them.
