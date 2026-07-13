# Summary V1

* Below is a summary of v1
* Motivated a pivot to focus wholly on "Implied Shift Factor", stumbled upon
  while looking at Implied Binding Probability.


### Current model efficacy vs. ERCOT — run `v1-annual-2`

**Configuration:** `kkt_perbus` model reference vs. `zone_local_spp` ERCOT
reference, hierarchical clustering on β at K=12, over 7,816 hours (~full year).
2,594 model buses and 964 settlement points partitioned into zones; only **8 of
12 clusters survived** (zones 1, 12 dropped for too few SPs; zones 2, 3 had
buses but no SPs).

**Headline — weak-to-moderate structural agreement:**

| Metric | Value | Read |
|---|---|---|
| Zone-rank Spearman / hour | **0.244** | Model barely reproduces the *ordering* of which zones are most congested hour-to-hour |
| Mean zonal correlation | **0.297** | Weak co-movement of congestion magnitude |
| Mean sign agreement | **0.622** | Gets congestion *direction* right ~62% of hours — better than coin-flip but not strong |

**Per-settlement-point level is worse than the zonal aggregate:**

- Median per-SP correlation **0.317**, median Spearman **0.317**
- **0% of SPs** exceed corr 0.7; only **~2%** exceed 0.5
- Median sign agreement per SP **0.47** (essentially chance); only 35% of SPs
  beat 0.7 sign agreement

Aggregating to zones lifts the signal (mean sign 0.62 vs. 0.47 per-SP), as
expected — zonal averaging cancels idiosyncratic noise.

**The zonal average hides large dispersion.** The 8 zones split into two
regimes:

- *Zones that work:* Zone 11 (corr **0.53**, sign **0.88**), Zone 5 (corr 0.37,
  sign **0.98**), Zone 4 (corr 0.38, sign 0.79).
- *Zones that fail:* Zone 8 (corr **0.074**, sign 0.53 — largest model footprint,
  weakest match), Zone 6 (corr 0.20, sign **0.25**), Zone 7 (corr 0.24, sign
  **0.26**). Zones 6/7 sign agreement below 0.5 means the model systematically
  predicts congestion in the *opposite* direction from ERCOT there.

**Clustering quality:** silhouette peaks at K=4 (0.72) and drops to ~0.41 at the
chosen K=12 while within-cluster variance keeps falling — K=12 trades cluster
crispness for spatial resolution; buses/SPs are not cleanly separable into 12
behavioral zones.

**Bottom line:** consistent with this being a v1 "weak synth-grid → ERCOT
clustering result." The model is a **directional, structural approximation, not
a predictive one**: it captures gross spatial structure in a few well-connected
zones (5, 11, 4) where direction is reliable, is near-useless at the individual
settlement-point level, and inverts entirely in zones 6/7/8. This validates the
project's stated goal (structural/zonal validation, not LMP prediction), but an
overall Spearman of 0.24 is too low to treat the zonal map as broadly
trustworthy.
