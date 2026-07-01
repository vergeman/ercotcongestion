# Basis

The point of doing basis first was to get a wide enough sample to retune the
modeled-congestion/LMP thresholds away from that 3-hour map slice.

* TODO: |modeled_congestion|-vs-|basis| Spearman ρ; see whether current thresholds make the
  rank coloring stable across both regimes.
  * clearly-congested hours (high n_binding_lines in snapshot_meta) vs
  * clearly-quiet hours

```
ercot=# SELECT
ercot-#   percentile_cont(0.01) WITHIN GROUP (ORDER BY basis) AS p01,
ercot-#   percentile_cont(0.50) WITHIN GROUP (ORDER BY basis) AS p50,
ercot-#   percentile_cont(0.99) WITHIN GROUP (ORDER BY basis) AS p99,
ercot-#   AVG(basis) AS mean,
ercot-#   AVG(ABS(basis)) AS mean_abs,
ercot-#   STDDEV(basis) AS stddev
ercot-# FROM bus_snapshots
ercot-# WHERE basis IS NOT NULL;

        p01         |        p50        |        p99        |       mean        |     mean_abs      |       stddev
--------------------+-------------------+-------------------+-------------------+-------------------+--------------------
 -70.33749999999961 | 8.152500000003823 | 47.07085207760333 | 6.273075067831787 | 16.10012173139327 | 22.570763414139037
```


The distribution:

* p01: −$70.34 reasonable lower tail
* p50: +$8.15 median basis is positive
* p99 +$47.07 reasonable upper tail
* mean: +$6.27 model LMPs systematically above zonal
* mean_abs: $16.10 typical magnitude — fine, in expected range
* stddev $22.57 reasonable spread


The shape (p01 to p99) is healthy. But that +$8 median bias is the thing worth
understanding:

It says: across 4M observations, the typical bus's model LMP exceeds its zonal
hub LMP by ~$8/MWh. There are several plausible explanations and they have very
different implications:

* **Marginal cost calibration is high**:
  * The fuel-based marginal costs may be set higher than ERCOT's actual offer
    curves clear at.
  * ERCOT has a lot of $0-marginal-cost wind/solar that depresses zonal hubs
    more than your synthetic dispatch realizes.

  Easy to check: compare lmp_mean from snapshot_meta against the zonal mean for
  the same hours.

* **Topology asymmetry**:
  * TAMU's synthetic 2000-bus network has different congestion patterns than the
    real ERCOT grid.
  * Buses systematically congest "outward" from hubs in the model, pushing model
    LMPs up relative to hubs.

* **Hub vs node arithmetic**:
  * Hub LMPs (HB_NORTH etc.) are aggregates over multiple settlement points;
  * I'm comparing them to a single bus's nodal LMP.
  * There's a structural reason buses average above hubs in some grids —
    load-pocket buses see uplift.

* **Loss/uplift accounting differences**:
  * ERCOT settlement points include or exclude certain components your synthetic
    OPF doesn't model.

The reason this matters: Spearman ρ on raw basis vs |basis| is robust to a
constant bias (rank order is preserved under translation), so the validation
panel will still work.

But if you're showing scatter plots with "basis" on an axis, viewers will notice
the cloud is shifted off zero and ask why. You have two options:

Scatter Plot shift:

  * **De-mean basis per timestamp**: before display (subtract the cross-bus mean
    at each hour).
    * This isolates the spatial basis signal from the systematic bias, which
      is what modeled congestion is supposed to predict anyway. Defensible and
      clean. <-- Preferred.
    * Show raw basis with disclosure: "model LMPs run ~$8 above zonal on
      average; this is a calibration limit, not a modeled-congestion signal."


If the +$8 is roughly uniform across all four zones, but if one zone is wildly
different — say West is +$25 and Houston is −$2 — that's a topology/congestion
story and more interesting to investigate, possibly a finding rather than a
flaw.

```
ercot=# SELECT
ercot-#   blz.load_zone,
ercot-#   AVG(bs.basis) AS mean_basis,
ercot-#   AVG(ABS(bs.basis)) AS mean_abs_basis,
ercot-#   COUNT(*) AS n
ercot-# FROM bus_snapshots bs
ercot-# JOIN bus_load_zones blz ON blz.bus_id = bs.bus_id
ercot-# WHERE bs.basis IS NOT NULL
ercot-# GROUP BY blz.load_zone
ercot-# ORDER BY blz.load_zone;

 load_zone |     mean_basis       |   mean_abs_basis    |    n     |    suggest bias              |
-----------+----------------------+---------------------+----------|------------------------------
 houston   |   1.3233410085604993 |  12.336144830345637 |  642930  |  model tracks zonal closely
 north     |   6.070571977180018  |  15.389340025100513 | 1142494  |  small positive bias
 south     |   3.1254685087330443 |  13.280351159233419 | 1251866  |  moderate positive bias
 west      |  13.42205776960491   |  22.67355547526903  | 1028688  |  outlier

```

* This isn't a uniform calibration bias.
* Houston is essentially unbiased.
* West is biased ~10× harder than Houston, with ~80% larger typical magnitudes.
  * That's a spatial story, not a global miscalibration
  * exactly the kind of finding that makes the validation panel interesting
    rather than embarrassing.

* Likely explanation: synthetic grid systematically under-resolves West Texas
  export congestion.
  * West Texas is where most ERCOT wind sits (the Panhandle and West regions in
    your wind decomposition).
  * In ERCOT, that wind frequently creates negative basis at West-zone nodes:
    * Wind floods the local network, transmission constraints prevent it from
      flowing east to load centers, and West LMPs collapse below the hub.
    * Synthetic grid presumably has different transmission topology and
      different congestion patterns, so it doesn't reproduce that
      west-to-load-center bottleneck.
    * Result: model dispatches West wind more freely than reality permits, model
      LMPs in West stay high, observed zonal West LMP sits low → big positive
      basis.
  * Houston, by contrast, is a load center with diverse generation nearby.
    * There's no comparable structural congestion pattern to mis-model, so the
      bias is small.

1. The validation panel just got a structural narrative: instead of
   "|modeled_congestion| correlates with |basis| at ρ=X," you get:
  * modeled-congestion-vs-basis correlation is strong in Houston/South where
    the synthetic grid resembles ERCOT's congestion pattern
  * weaker in West where the model under-resolves wind export bottlenecks.
  * tells viewers exactly where the model has predictive value and where it
    doesn't - the whole point of the panel.

2. Per-zone regime breakdown is now mandatory in the panel, not just
   nice-to-have.
  * "Regime breakdowns: congested vs quiet hours, by zone, by time-of-day"
  * Prioritize zone breakdown to the top; compute ρ separately for the four
    zones.

Now confirm the West bias correlates with wind generation:
```
SELECT
  CASE WHEN (sm.wind_factor_by_region->>'west')::float > 0.4 THEN 'high_wind'
       ELSE 'low_wind' END AS wind_regime,
  blz.load_zone,
  AVG(bs.basis) AS mean_basis,
  COUNT(*) AS n
FROM bus_snapshots bs
JOIN bus_load_zones blz ON blz.bus_id = bs.bus_id
JOIN snapshot_meta sm ON sm.interval_ts = bs.interval_ts
WHERE bs.basis IS NOT NULL
  AND blz.load_zone IN ('west', 'houston')
  AND sm.wind_factor_by_region ? 'west'
GROUP BY 1, 2
ORDER BY 2, 1;

wind_regime | load_zone |     mean_basis      |   n
-------------+-----------+---------------------+--------
 high_wind   | houston   |  3.1258798670027903 | 369315
 low_wind    | houston   | -1.1096565921034343 | 273615
 high_wind   | west      |  22.672783257188552 | 590904
 low_wind    | west      |  0.9357844167265318 | 437784

NB: shape of wind factor:
 { "west": 0.5096884661961647, "north": 0.5018863925392115, "south": ...}
```

* West row:
  * Low wind (factor ≤ 0.4): mean basis = +$0.94: model tracks zonal almost
    perfectly
  * High wind (factor > 0.4): mean basis = +$22.67: model is $22 above zonal

* A 24 x swing on wind output. That's not calibration noise. The model and
  reality agree on West-zone prices when wind is low; they diverge by an
  enormous margin specifically when wind is high.
  * Synthetic grid under-resolves West Texas wind export congestion
  * Real West nodes collapse under wind flooding while the model dispatches that
    wind freely
  * Houston is the control case and behaves correctly. Symmetric small bias
    either side of zero (+$3.13 high wind, −$1.11 low wind)
    * Expected for a load center where wind isn't the dominant local price
      driver.


* Conclusion:
  * The synthetic TAMU grid reproduces ERCOT zonal pricing well in load centers
    (Houston, South) and in low-wind regimes everywhere.
  * It systematically over-prices West Texas during high-wind hours, by an
    average of ~$22/MWh.
  * Consistent with the synthetic network not capturing the real
    West-to-load-center transmission constraints that cause West nodes to
    collapse under wind output during ERCOT operations.
  * The model's predictive value for modeled congestion is therefore
    strongest in Houston and South, weaker in North, and degraded in West
    during high-wind hours.

* The "regime" axis isn't optional. It's the primary axis. You need at minimum:
  * Per-zone ρ (4 numbers)
  * Per-zone × wind-regime ρ (8 numbers, with West-high-wind highlighted)
  * Pooled ρ for context but not as the headline


TODO:

* Compute ρ on de-meaned-per-(zone, hour) basis for the "raw" comparison,
  alongside the literal ρ on raw basis.

* The de-meaned version asks "does modeled congestion predict spatial
  mispricing within a zone at a moment in time" - which is the question
  modeled congestion is actually trying to answer.


---

What basis is in the DB today: it's from the model's own OPF solution — lmp[bus]
− lmp[hub]. So modeled_congestion (PTDF · μ_signed) vs basis (LMP − hub LMP) is
an internal consistency check on our OPF: does the sensitivity-based congestion
component reconstruct the LMP spread? By LMP-decomposition theory it should
match in sign and magnitude. That's the Pearson that's being computed.

What the working outline actually wants (Phase 4, Tier 2): sign agreement,
Spearman rank correlation, and pairwise zonal spreads between ERCOT SPP-derived
basis and model-derived basis. That's the headline claim — model reproduces
ERCOT's structural congestion pattern. It's a different comparison entirely.

Why the magnitude gap concern is real but not fatal:

  - Model OPF ≠ ERCOT OPF (different topology, dispatch, load allocation), so magnitudes won't line up.
  - Reference-price choice (Phase 2 table) shifts magnitude by a constant across a snapshot.
  - The outline is explicit: "we are not predicting $/MWh" — direction and rank are the deliverable.


So what should basis's role be?

1. Short term (this sprint's validation endpoint): basis is a same-OPF sanity
   check that modeled_congestion sign is right. Pearson ρ ≈ 1 would be
   reassuring; the sprint2b plan §5 framing A (signed vs signed) targets this.
   Sign-agreement rate (framing C) is the more honest number given the outline's
   stance.

2. Medium term (what the outline actually promises): you need a second
   basis_ercot column populated from real ERCOT SPPs, and the validation ρ
   should be modeled_congestion vs basis_ercot — Spearman, not Pearson. That's
   the "structural validation" claim.

Recommendation: treat basis today as diagnostic scaffolding, not headline.
Prioritize the ERCOT-actuals basis column (it's implied by Phase 2 but not in
any sprint I've seen), and switch the validation panel's headline from Pearson
to Spearman + sign-agreement. Otherwise you're claiming "structural validation"
but reporting a metric that tests the wrong thing.
