# binding_proximity: slack-bus artifact and the case for distributed slack

## Background: what "slack" is and why it matters here

DC power flow conserves power: every injected MW has to be withdrawn
somewhere. PTDF answers *"if 1 MW is injected at bus b, how much shows up
on line ℓ?"* — but that question is ill-posed until you also say where
the balancing MW leaves. The bus (or set of buses) that absorbs that
balance is the **slack**.

* **Single-slack PTDF** (PyPSA's default): pick one bus, put all
  balancing there. Mathematically clean, but the physical scenario —
  "everything rebalances at one bus" — is not how a real grid behaves.
* **Distributed-slack PTDF**: spread the balancing across many buses in
  proportion to a weight vector `w` (`Σ w_k = 1`). The linear correction
  is one matmul:
  ```
  PTDF_dist[ℓ, b] = PTDF_single[ℓ, b] - (PTDF_single · w)[ℓ]
  ```
  Load-weighted `w` (`w_b ∝ load_b`) is the industry-standard operational
  choice and what the pipeline now uses inside `binding_proximity_at`.

Why this specifically matters for `binding_proximity`: the metric takes a
**max over branches**, so it is sensitive to any single PTDF row
blowing up. Texas2k's slack (WADSWORTH, bus 7098) is a topological leaf
attached only through transformer T688, so single-slack PTDF gives every
non-slack bus `|PTDF[T688, ·]| ≈ 1`, and the `max` collapses the whole
network to `loading[T688]`. Distributing the slack across load cancels
that projection out. `modeled_congestion` is unaffected because it takes
a **μ-weighted sum**: T688 never binds in base case, its μ is ~0, and the
artifact does not propagate — so that path stays single-slack.

## The observed problem

On the map, `binding_proximity` looks nearly constant across every bus per
snapshot. Even when a line is highlighted as binding between two specific buses,
the endpoint buses report the same proximity value as buses on the far side of
the state that clearly don't drive that line. The metric has no spatial
contrast — and therefore, as displayed, no information.

Concretely, on `2025-12-31 00:00 UTC` (a snapshot with 14 base-case binding
lines):

```
n_buses = 2750
distinct binding_proximity values (rounded @ 4dp): 75
2666 / 2750 buses have identical value 0.5984
```

Two-thirds of the network reports the same value to four decimals. The 84
outliers are not concentrated at binding-line endpoints — they're just wherever
some *other* local branch happened to beat the network-wide floor.

## The metric, as designed

From `compute/congestion/metrics.py:65-95`:

```
binding_proximity[b] = max_{ℓ : |PTDF[ℓ, b]| > 1e-4}
                          |PTDF[ℓ, b]| · |flow_ℓ| / (s_nom_ℓ · s_max_pu_ℓ)
```

For each bus `b`, take the max over branches of (electrical influence on that
branch × that branch's loading fraction). The intent is honest: a bus is
"close to binding" if some heavily-loaded branch is one that the bus
meaningfully drives. Both the sensitivity term (PTDF) and the state term
(loading) are correct in isolation. The problem is what "PTDF" resolves to.

## Root cause: single-slack PTDF + a topological radial

PTDF is not a purely physical property. DC power flow requires that any
injected MW is *withdrawn* somewhere — the "slack." Different slack choices
produce different PTDF matrices, all mathematically correct but answering
different physical questions:

* **Single-slack PTDF** (what the current pipeline uses): answers "if I inject
  1 MW at bus `b` and withdraw 1 MW at the one chosen slack bus, what
  fraction shows up on line `ℓ`?"
* **Distributed-slack PTDF** (what ISOs use operationally): answers "if load
  rises 1 MW at bus `b` and the system rebalances across many buses in
  proportion to their load/gen share, what fraction shows up on line `ℓ`?"

The current pipeline calls `sub.calculate_PTDF()` with no slack argument
(`compute/ptdf_lodf.py:62`), which honors PyPSA's rule: if any bus is marked
`control='Slack'`, use it; otherwise fall back to the first bus in the index.

### The Texas2k slack designation

The Texas2k `.nc` file explicitly marks **bus 7098 (WADSWORTH substation)** as
`control='Slack'`, and its co-located ~1300 MW generator as
`control='Slack'`. This is a MATPOWER-inherited convention — synthetic Texas
cases from Texas A&M (ACTIVSg2000 lineage) require exactly one bus per island
to be type 3 (slack) for AC power flow to solve. For load-flow *results*, the
choice is invisible. For PTDF *interpretation*, it matters enormously.

Bus 7098 has one property that turns this from a numerical curiosity into a
metric-killing artifact:

```
Lines with 7098 as endpoint:        0
Transformers with 7098 as endpoint: 1  (T688: 7098 <-> 7095)
```

**T688 is the only branch connected to the slack**. It's a topological bridge:
delete it and 7098 is islanded. To route 1 MW from any bus back to 7098, 100%
of that MW must traverse T688. Empirically:

```
T688 PTDF row: min=-1.0000  max=0.0000  mean=-0.9996
|row| > 0.99 on 2750 / 2751 buses
```

Every non-slack bus in the network has `|PTDF[T688, b]| ≈ 1`. Since PTDF
values on all other branches are typically < 0.5, T688's contribution
(`1.0 × loading[T688]`) wins the `max` for virtually every bus. Every bus's
`binding_proximity` reduces to `loading[T688]`.

In the 2025-12-31 snapshot, T688 was loaded at 0.5984 → 2666 buses report
0.5984 exactly.

The chain end-to-end:

> Texas A&M picked bus 7098 as the slack when they authored the case (probably
> arbitrary — a large substation with a swing generator, in a central-ish
> location) → 7098 happens to be a topological leaf attached by one
> transformer → PyPSA's single-slack PTDF gives every bus `|PTDF|=1` on that
> transformer → the metric's `max` locks onto T688 → the whole network reports
> the same value.

## Empirical confirmation

Same OPF solution, three PTDF regimes on `2025-12-31 00:00 UTC`:

| statistic                | A single-slack (current) | B load-weighted distributed | C gen-weighted distributed |
| ------------------------ | ------------------------ | --------------------------- | -------------------------- |
| min                      | 0.5984                   | 0.0434                      | 0.0401                     |
| max                      | 0.6963                   | 0.6963                      | 0.6902                     |
| sd                       | 0.0070                   | 0.1506                      | 0.1492                     |
| distinct @ 4dp (of 2750) | 75                       | 1477                        | 1421                       |

Endpoints of five base-case binding lines (loading = 1.0 each):

```
                        current (A)         load-weighted (B)
                        bus0    bus1        bus0    bus1
L61   (1019–1029)       0.598   0.598       0.154   0.536
L85   (1027–1132)       0.598   0.598       0.294   0.265
L185  (1071–1130)       0.598   0.598       0.119   0.353
L189  (1081–1129)       0.598   0.598       0.197   0.376
L287  (1114–13169)      0.598   0.598       0.517   0.172
```

Under (A), endpoints of binding lines are indistinguishable from arbitrary
buses. Under (B), endpoints show physical shift factors — sometimes symmetric
(both ends drive the flow, L85: 0.29/0.27), sometimes one-sided (L287:
0.52/0.17). Median-bus sanity check under (B): typical "quiet" buses drop from
0.598 to the 0.05–0.25 range, correctly reflecting that they are electrically
distant from any heavily-loaded branch.

Same experiment on `2026-04-03 13:00 UTC` (a high-congestion snapshot with 22
binding lines): (A) and (B) look nearly identical there — because
non-T688 branches are heavily loaded enough to win the `max` under either
regime. The artifact is worst in low-congestion snapshots, which are the
majority.

## The distributed-slack correction

Given a single-slack PTDF `H` (rows = branches, cols = buses, slack column all
zeros) and a distribution vector `w` over buses (`w.sum() == 1`), the
distributed-slack PTDF is:

```
H_dist[ℓ, b] = H[ℓ, b] - Σ_k w[k] · H[ℓ, k]
             = H[ℓ, b] - (H · w)[ℓ]
```

One matrix-vector product per snapshot. No re-solve, no additional PyPSA
machinery. The choice of `w`:

* **Load-weighted** (`w[b] ∝ load[b]`): distributes the balancing across the
  load footprint. Matches how ISOs compute operational PTDFs.
* **Gen-weighted** (`w[b] ∝ dispatch[b]`): distributes across generators.
  Reasonable alternative; slightly different weighting for the same effect.
* **Uniform**: `w[b] = 1/n`. Simple; ignores the fact that Wadsworth is not
  equivalent to a load pocket.

Load-weighted is the industry-standard choice.

## Two distinct proximity metrics: base-case vs N-1

`binding_proximity` uses base-case flows only. The N-1 highlight on the map is
contingency-driven: "line ℓ would bind if line k trips." A line that's 60%
loaded in base case and 105% loaded post-contingency does not register in
`binding_proximity` — because 0.6 loses to any 1.0 loading elsewhere in the
base case.

These are two different operational questions and they should stay as two
separate metrics, not be merged into one:

* `binding_proximity[b]` (fix the slack, keep the field) — **base-case
  gradient**. *"Given the current dispatch, which buses drive branches that
  are heavily loaded right now?"*
* `binding_proximity_n1[b]` (new field) — **N-1 gradient**. *"Under the top-K
  credible single-element outages, which buses drive branches that would
  overload post-contingency?"*

Merging them into a single `max(...)` would hide which scenario drove any
given bus's value — an operator staring at a hot spot can't tell whether it's
current dispatch or a specific outage that made it hot. Keeping them separate
also lets the frontend offer a toggle: "current stress" vs "outage-worst-case
stress," and the N-1 layer visually confirms the map's existing N-1 highlight
(endpoints of the highlighted line light up because their bp_n1 spiked).

The N-1 formula (using the distributed-slack PTDF from the first fix):

```
bp_N1[b] = max_{ℓ, k ∈ top_K}  |PTDF[ℓ, b] + LODF[ℓ, k] · PTDF[k, b]|
                             · min(1, |flow[ℓ] + LODF[ℓ, k] · flow[k]| / limit[ℓ])
```

`k` iterates only over the top-K contingencies that the pipeline already ranks
in `compute_contingencies_at` (K ~ 10-50), so the extra cost is
O(n_bus · n_branch · K), not O(n_bus · n_branch²). LODF is a topology-only
matrix (already returned by `get_ptdf_lodf`); base-case flows come from the
same OPF solution that feeds `binding_proximity`.

Distributed slack (metric A fix) and the N-1 metric (metric B addition) are
independent changes. See `plan/0057-binding-proximity-fix.md` for scope
splits and the recommended phased rollout.

## FAQ

### Why don't the endpoints of a binding line always show elevated `binding_proximity`?

Because `binding_proximity` and "binding lines" measure different things.
A bus lights up when it *most strongly drives* whichever loaded branch has
the highest `|PTDF| × loading` — which need not be the binding line, and
that line's endpoints need not be the buses that drive it hardest.

Four concrete reasons the two views can diverge:

1. **BP is a max, and the maximizing line often isn't the binding one.**
   Per-bus,
   ```
   binding_proximity[b] = max_ℓ  |PTDF_dist[ℓ, b]| · |flow_ℓ| / limit_ℓ
   ```
   (see `compute/congestion/metrics.py`). A binding line `ℓ*` contributes
   `|PTDF_dist[ℓ*, b]| × 1.0`. If some other line `ℓ'` has
   `|PTDF_dist[ℓ', b]| = 0.5` and loading 0.9, that product is 0.45 — and
   any bus where the binding line's PTDF drops below 0.45 gets its BP set
   by `ℓ'`, not by `ℓ*`. Different lines "win" for different buses. A
   binding line's endpoints only dominate BP if they *also* carry a high
   PTDF on that specific branch, which is not automatic.

2. **Endpoint ≠ high PTDF.** A line's PTDF magnitude at its own endpoint
   is an electrical quantity — the shift factor of that node under the
   chosen slack — not a topological label. For a line sitting mid-corridor
   with power flowing through it from multiple upstream injections,
   endpoint buses can have moderate PTDFs (~0.2–0.4) because the flow is
   already "made" by injections farther out. The buses that maximally
   drive `ℓ*` are wherever the PTDF row peaks — often a cluster of
   upstream neighbors, not the two nodes named in the line's `bus0`/`bus1`
   fields.

3. **Distributed slack redistributes the endpoint values.** Under
   single-slack, one endpoint of a line typically had `|PTDF| ≈ 1`. Under
   load-weighted distributed slack,
   `PTDF_dist[ℓ, b] = PTDF_single[ℓ, b] − Σ_k w_k · PTDF_single[ℓ, k]`.
   If the binding line sits in a load-dense area, its whole PTDF row gets
   shifted downward on those nearby (heavily-weighted) buses — the
   correction cancels out precisely the buses that *look* like they should
   be endpoints. This is the intended price of fixing the T688 collapse:
   BP now measures marginal *influence* rather than raw radial
   connectivity.

4. **`PTDF_INFLUENCE_EPS = 1e-4` filter.** Any line whose distributed-slack
   PTDF at bus `b` falls below 1e-4 is dropped from the `max` for that
   bus. That's primarily a numerical-noise gate, but it also means
   far-field buses whose only apparent "connection" to a binding line was
   the single-slack radial artifact now have that connection correctly
   zeroed out — the wanted behavior post-fix.

**Debugging a specific case.** If a binding line looks orphaned on the map,
pull `PTDF_dist[ℓ*, :]`, sort it by `|·|`, and look at where the top-10
buses land geographically. Typically you'll find them clustered *near* the
binding line rather than on its literal endpoints — that cluster is what
BP is highlighting, and it is the physically-correct answer to *"which
buses drive this branch?"*
