# regime_scorecard — diagnostic + findings

Step 1 of [plan/handoff-regime.md](../../../plan/handoff-regime.md).
Recomputes the existing zone-aggregated scorecard metrics — `mean_corr`,
`zone_rank_spearman_per_hour`, `mean_sign_agreement` — **per regime bucket** and reports
them alongside the pooled numbers. Answers: does the model track ERCOT
better in stressed hours than in slack hours, or is pooled tracking
diluted by hours where nothing much is happening?

Diagnostic only. Nothing under `runs/<run>/mapping/` is touched;
outputs land in `runs/<run>/experiments/regime_scorecard/`.

## TL;DR — findings on `v1-annual-2`

**Recommended pair for the writeup:** `kkt_perbus × zone_local_spp`.

* Second-best pooled `mean_corr` (0.274) and best pooled `sign_agreement`
  (0.723) — within 4% of the same-method "proxy ceiling" using genuinely
  different methods on each side.
* The **only** promoted pair whose per-regime metrics stay flat across
  net-load quartiles — sign_agreement holds ~72-75% whether it's a
  windy shoulder hour or a heat-wave scarcity hour. Every other pair
  sags 12-20 points in the low-net-load (windy/mild) regime.
* The **only** pair whose `zone_rank_spearman_per_hour` climbs monotonically with
  congestion magnitude (Q1 → Q4: 0.06 → 0.37). Every other pair peaks
  in Q2/Q3 and dips in Q4 — a pathology on the biggest-congestion hours.

## What "quartile" means

`q4` means **4 equal-count quantile buckets**. For `net_load:q4` on
`v1-annual-2` (7816 hours):

* Compute per-hour `net_load = load − wind − solar`, one scalar per hour.
* Sort those 7816 numbers, cut them into 4 equal-size groups of 1954.
* Q1 = lowest 25% of hours (11.4 → 27.1 GW — windy/mild shoulder hours).
* Q2 = next 25% (27.1 → 35.6 GW).
* Q3 = next 25% (35.6 → 43.3 GW).
* Q4 = highest 25% (43.3 → 68.8 GW — heat-wave / scarcity hours).

A "bucket" is literally the timestamp list that fell in that range.
`Q4 zone_rank_spearman_per_hour = 0.35` means "on the 1954 hours with the highest
net-load, the model's rank ordering of zonal congestion correlates
0.35 with ERCOT's." The diagnostic reports all four buckets so we can
see the shape of the tracking-vs-regime curve — which bucket
concentrates the signal is the finding, not an input assumption.

Any `qN` works: `q2` = median split, `q4` = quartiles, `q8` = octiles.
`binding_active` is categorical (0/1) so it has 2 buckets, not
quantiles.

## Findings — full sweep

Ran against all three pairs in `compute/mapping/pairs/default.json` on
`v1-annual-2`, partition `system_lambda_merit_order` hierarchical k=6.

### Pooled headline (all 7816 hours)

| Pair                                       | rank_sp | mean_corr | sign_agr |
|--------------------------------------------|--------:|----------:|---------:|
| `kkt_perbus × system_lambda`               |   0.291 |     0.229 |    0.655 |
| **`kkt_perbus × zone_local_spp`**          |   0.230 | **0.274** |**0.723** |
| `load_weighted × load_weighted` (ceiling)  |   0.256 |     0.284 |    0.714 |

The load-weighted × load-weighted "proxy ceiling" pair squeezes out
slightly higher `mean_corr` than `kkt × zone_local_spp`, but that's
not a fair fight — same method on both sides is by construction more
aligned. `zone_local_spp` gets ~96% of the way to the ceiling on
`mean_corr` and ~101% on `sign_agr`, using genuinely different methods
on each side. That's the meaningful benchmark.

### `net_load:q4` — where the pairs separate

**`zone_rank_spearman_per_hour` by quartile:**

|                              |    Q1 |    Q2 |    Q3 |    Q4 | Q1→Q4 spread |
|------------------------------|------:|------:|------:|------:|-------------:|
| `kkt × λ`                    | 0.102 | 0.369 | 0.350 | 0.345 |        0.243 |
| **`kkt × zone_local_spp`**   | 0.210 | 0.248 | 0.206 | 0.255 |    **0.045** |
| `load_weighted × lw`         | 0.063 | 0.337 | 0.314 | 0.312 |        0.249 |

**`sign_agreement` by quartile:**

|                              |    Q1 |    Q2 |    Q3 |    Q4 | Q1→Q4 spread |
|------------------------------|------:|------:|------:|------:|-------------:|
| `kkt × λ`                    | 0.587 | 0.653 | 0.674 | 0.710 |       +0.123 |
| **`kkt × zone_local_spp`**   | 0.752 | 0.734 | 0.714 | 0.717 |    **−0.035**|
| `load_weighted × lw`         | 0.569 | 0.731 | 0.757 | 0.766 |       +0.197 |

`kkt × zone_local_spp` is the only pair with regime-flat behavior on
net_load. The other two show the same shape — Q1 (low net load,
wind-heavy) sags, Q2-Q4 climb — meaning they struggle in windy/mild
hours. Zone-recentering the ERCOT side fixes that specifically, and
does it without needing OPF μ or clustering-conditioning: the fix is
upstream in the reference-price definition, not downstream in the
analysis.

That reframes the handoff's original hypothesis: **regime dilution is
a symptom of scalar references, not of the modeling itself.** Once the
ERCOT side subtracts a per-zone mean, the regime axis becomes
uninformative for net_load.

### `congestion_magnitude:q4` — the healthiest signature

**`zone_rank_spearman_per_hour` by quartile:**

|                              |    Q1 |    Q2 |    Q3 |    Q4 |
|------------------------------|------:|------:|------:|------:|
| `kkt × λ`                    | 0.195 | 0.347 | 0.337 | 0.286 |
| **`kkt × zone_local_spp`**   | 0.056 | 0.204 | 0.291 | 0.369 |
| `load_weighted × lw`         | 0.114 | 0.321 | 0.320 | 0.271 |

Only `kkt × zone_local_spp` climbs monotonically Q1 → Q4. The other
two peak in Q2/Q3 and *dip* in Q4 — a pathology on the biggest-
congestion hours. `kkt × zone_local_spp` has a genuinely different
failure mode: noisy in the quiet hours, cleanest in the loud ones,
which is the direction you want if this is going to be a headline
metric on scarcity events.

### `binding_active` — negative across all three pairs

Same 7815/1 split for every pair — one hour "inactive", every other
hour "active". The proxy (`max |model_C[:, t]| > deadband`) can't
answer the binding question at the matrix layer regardless of pair,
because outlier buses always push per-hour max into the thousands of
$/MWh. To answer the binding question honestly you need OPF μ directly
from `bus_snapshots`, not the matrix — that's what the handoff's
step 2 `regime_partition` with a binding fingerprint would need.

The negative finding is now documented across the entire promoted pair
set. The scheme stays in the CLI so any future run captures the same
non-result.

## Recommended pair

**Use `kkt_perbus × zone_local_spp` as the reference pair for the
writeup and any downstream regime work.** Rationale:

1. Best pooled `sign_agreement` (0.723) — model gets sign of zonal
   congestion right on ~72% of hours.
2. Only pair whose sign_agreement is regime-flat across net_load
   (72-75% in every quartile). Portfolio-piece framing: "the model
   identifies sign of zonal congestion at ~72% accuracy, uniformly
   across the net-load distribution."
3. Only pair whose `zone_rank_spearman_per_hour` improves monotonically with
   congestion magnitude — the right direction if scarcity events are
   the headline story.
4. Regime dilution disappears — so the handoff's regime-conditioning
   roadmap (steps 2-5) can be reconsidered rather than built out
   speculatively.

## Suggested next steps

Ordered by leverage-per-effort:

1. **Re-promote scorecard for `kkt_perbus × zone_local_spp` on
   `v1-annual-2`.** Currently the promoted scorecard file
   (`runs/v1-annual-2/mapping/scorecard_v1-annual-2_..._k6.json`) was
   written under merit_order defaults. Rerunning
   `compute.mapping.scorecard --run-id v1-annual-2 --model-ref
   kkt_perbus --ercot-ref zone_local_spp` promotes the pair the
   writeup will actually use, and clears the pooled-drift warnings
   this diagnostic emits.
2. **Rethink handoff-regime.md steps 2-5 against `kkt × zls`.** The
   original motivation was "pool dilutes, condition on regime to
   recover." That story doesn't survive the pair swap — net_load
   conditioning adds nothing on the recommended pair. Before building
   the `regime_partition` stage or `--regime-mode stacked` clustering,
   check whether the 864-bus "hard core" from
   [handoff-post-cluster](../../../plan/handoff-post-cluster.md) is
   still hard on this pair. It might have already melted, in which
   case the whole roadmap collapses to "just use the right reference."
3. **Cluster on `kkt_perbus`, not `system_lambda_merit_order`.** The
   partition currently used everywhere (`--ref system_lambda_merit_order`)
   is bus-clustered on the wrong signal. Re-run
   `compute.clustering.runner` with `--ref kkt_perbus` and rerun this
   diagnostic — the regime picture may sharpen further when the
   partition is on the same method as the model side.
4. **Investigate why `kkt × zls` `zone_rank_spearman_per_hour` is *lower* in Q1
   congestion_magnitude buckets.** 0.056 on 1954 quiet hours is close
   to noise. Is it that there's genuinely nothing to rank when
   congestion is small, or is zone_local_spp introducing artifacts in
   the low-signal regime? Sanity-check by looking at the actual per-
   bucket hour lists (already emitted in the JSON output under
   `buckets[i].hours`) — pull the Q1 hours and confirm they're the
   expected shoulder-load / mild-weather timestamps.
5. **Drop `binding_active` from the default `--bins`** or rewrite it
   against OPF μ from `bus_snapshots` (requires a DB read + hooking
   into the regimes covariate loader). Current definition is
   negatively confirmed on all three pairs.
6. **Retire the "regime-conditioning" framing in the writeup and
   replace with "reference-pair selection" as the headline structural
   finding.** The pair-comparison table above tells a cleaner and
   more novel story than a regime-conditioned scorecard would.

## Run it

Single pair:

```
docker compose run --rm compute python -m compute.experiments.regime_scorecard.run \
    --run-id v1-annual-2 \
    --bins congestion_magnitude:q4,net_load:q4,binding_active \
    --model-ref kkt_perbus \
    --ercot-ref zone_local_spp \
    --ref system_lambda_merit_order \
    --algo hierarchical_on_beta \
    --k 6
```

Full promoted-pair sweep:

```
for pair in \
    "kkt_perbus,system_lambda" \
    "kkt_perbus,zone_local_spp" \
    "load_weighted,load_weighted"; do
  IFS=',' read -r MREF EREF <<< "$pair"
  docker compose run --rm compute python -m compute.experiments.regime_scorecard.run \
      --run-id v1-annual-2 \
      --bins congestion_magnitude:q4,net_load:q4 \
      --model-ref "$MREF" --ercot-ref "$EREF" \
      --ref system_lambda_merit_order \
      --algo hierarchical_on_beta --k 6
done
```

One invocation runs against **one** `(model_ref, ercot_ref, partition_ref)`
tuple — same axis as `compute/mapping/scorecard.py`. `--bins` accepts a
comma list; one output file per scheme. Multiple schemes in one
invocation share matrix + partition loads.

## Bin schemes

| Scheme                     | Driver                                                              |
|----------------------------|---------------------------------------------------------------------|
| `congestion_magnitude:qN`  | Per-hour mean of `|ercot_C|` across SPs. In-npz, no DB access.      |
| `net_load:qN`              | `load − wind − solar` from ERCOT DB. Requires Postgres.             |
| `binding_active`           | Per-hour `max |model_C| > deadband`. Binary. See negative finding above.|

## Output

`runs/<run>/experiments/regime_scorecard/<run>_<ref>_<algo>_k<K>_<scheme>.json`:

```json
{
  "run_id": "v1-annual-2",
  "params": {"model_ref": "kkt_perbus", "ercot_ref": "zone_local_spp", ...},
  "scheme_meta": {
    "driver": "net_load",
    "n_buckets": 4,
    "edges": [11447, 27056, 35575, 43348, 68846],
    "bucket_labels": ["Q1", "Q2", "Q3", "Q4"],
    "covariate_missing": []
  },
  "buckets": [
    {"id": 0, "label": "Q1", "range": [11447, 27056], "n_hours": 1954,
     "zone_rank_spearman_per_hour": 0.21, "mean_corr": 0.29, "mean_sign_agreement": 0.75,
     "hours": ["2025-02-06T06:00:00+00:00", ...]},
    ...,
    {"id": null, "label": "pooled", "n_hours": 7816, "hours": null,
     "zone_rank_spearman_per_hour": ..., "mean_corr": ..., "mean_sign_agreement": ...}
  ],
  "warnings": [...]
}
```

Per-bucket `"hours"` is the timestamp list that fell in the bucket —
makes "why did Q4 pop?" answerable by eyeballing (are they all July
afternoons? all winter storm hours?). Pooled row leaves `"hours": null`
to avoid duplicating the full window.

## Pooled sanity check

Before writing anything, the run script computes the pooled row and
compares it to the existing promoted scorecard at
`runs/<run>/mapping/scorecard_<run>_<ref>_<algo>_k<K>.json`. When the
current mapping/clustering artifacts on disk no longer reproduce the
promoted headline, the diagnostic warns and adds a `pooled/*_drift`
entry to `warnings`, but keeps running — the per-bucket rows are still
valid against the current artifacts. Drift is a data-consistency issue
for the user to reconcile (rerun `compute.mapping.scorecard` or
re-promote), not a defect in the diagnostic.

Drift is also expected when the pair passed via `--model-ref` /
`--ercot-ref` doesn't match what the promoted scorecard was computed
under (which is the case for all sweep rows above — the promoted
scorecard was written under merit_order defaults).
