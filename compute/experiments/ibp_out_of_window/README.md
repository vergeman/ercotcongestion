# ibp_out_of_window — validating the implied-SF matrix out of sample

The harness behind version 3 pivot; it answers one question the production stage
cannot answer about itself: **is the SF matrix worth what its diagnostics say it
is?**

It is not. `compute/implied_binding_proximity` reports **mean R² = 0.985**
(`ibp_sweep_trials.csv`, `full_year` row), and `plan/version2-pivot.md` builds
the v2 pivot on that number. It is an *in-sample* statistic, computed on a fit
window that contains the rows it scores. Measured out-of-window, the same matrix
is worth **0.746** — and that still requires being handed tomorrow's shadow
prices.

**Depends on:** the production module, unmodified. Every script imports
`implied_binding_proximity.fit.implied_shift_factors` and `.panels` directly, at
production defaults (`window=60, refit=7, λ=1e-1, std_floor=100,
min_binding_hours=25`). Nothing is reimplemented — if the fit changes, these
results change with it.

## The one-line difference

```python
# rolling.py:99-100 (production): window ends where scoring ENDS
window_end = score_end          # -> the fit window CONTAINS the scored week

# common.py (here): window ends where scoring BEGINS
window_end = refit_start        # -> no lookahead
```

That line is the entire gap between 0.986 and 0.746. Note the production choice
is *defensible for what it was built for* — `bp_ercot` is a retrospective
explanatory map ("what drove congestion at this node, that week"), and a
trailing-inclusive window is reasonable for that. The error was quoting a
retrospective fit statistic as forecast validation.

## Files

- `common.py` — shared rig: panel loading, the honest window, `r2` (same
  definition as `diagnostics._r2`, so numbers are directly comparable), and the
  three μ sources.
- `oos_gate.py` — the gate `version2-pivot.md` §5 calls for and leaves unrun.
  In-sample vs out-of-window, oracle μ.
- `screening_and_coverage.py` — (1) the same predictions scored in four
  currencies, because pooled R² is the wrong yardstick for a screening tool;
  (2) decomposes the weekly collapses into *coverage* vs *rotation*.
- `sf_stability.py` — how fast SF actually moves. Corrects a contaminated
  stability estimate.
- `results/` — captured CSVs, one row per scored week.

Run any of them (~4–8 min each; `sf_stability` is the slowest at 3 fits/week):

```bash
docker compose run --rm compute \
  python -m compute.experiments.ibp_out_of_window.oos_gate
```

## Results

### 1. The gate — the map is real, but it is not 0.985

44 weeks over 2025. Oracle μ means the model is handed realized shadow prices,
so this isolates the SF map from any bind-forecasting skill. **It is a ceiling,
not a product.**

| | pooled R² | median-SP R² |
| --- | ---: | ---: |
| In-sample, as the pipeline reports it | **0.986** | 0.987 |
| **Out-of-window, oracle μ** | **0.746** | 0.643 |
| Predict-zero null | −0.042 | — |

Weekly OOS: median 0.843, p25 0.653, **min −0.019** (2025-04-20).

0.746 against a −0.04 null is a genuine result — the map carries real
out-of-sample information, and the pivot's instinct that this beats
PTDF-on-a-fake-grid is right. It is simply not the number in the doc.

### 2. Screening currency — the yardstick changes the verdict

Pooled R² measures $-magnitude. Screening value is *which nodes are worst, in
which direction*. Rank-Spearman and top-decile hit are cross-node, per hour;
sign-agreement is per node-hour with a $1/MWh deadband.

| μ source | pooled R² | rank-Spearman | sign-agree | top-decile hit |
| --- | ---: | ---: | ---: | ---: |
| **Oracle** (realized μ) | **0.746** | **0.835** | **0.907** | **0.780** |
| Climatology (P(bind\|hr) × mean μ\|bind) | 0.235 | 0.511 | 0.738 | 0.628 |
| Persistence (yesterday, same hour) | 0.173 | 0.581 | 0.771 | 0.649 |
| Null | −0.042 | 0.0 | 0.500 | 0.100 |

Two things follow.

**Persistence·SF has almost no magnitude skill and still screens well** — it puts
65% of the truly worst-decile nodes in its own worst decile, against a 10% random
baseline. A magnitude-only gate would have discarded a working screening tool.

**The baseline hierarchy inverts with the currency.** Climatology wins on
magnitude; persistence wins on rank, sign, and top-decile. They carry different
information — climatology the severity distribution, recent-binding *which*
constraints are live. Both belong in the μ-model; neither is "the" baseline.

### 3. Coverage vs drift — the collapses are mostly a coverage failure

Constraints absent from the fit window get an implicit **SF = 0**: the model
cannot see them at all. So a bad week has two candidate mechanisms, with
opposite fixes.

| | mean | corr with weekly oracle R² |
| --- | ---: | ---: |
| **coverage** — share of scored-week μ-mass with an SF column | 0.811 | **0.453** |
| **rotation** — corr(trailing SF, scored-week SF) | 0.428 | 0.312 |

Coverage is the stronger explanator: in a typical week **~19% of the μ-mass
driving congestion comes from constraints the SF matrix has no column for**, and
the collapse weeks skew low (0.66–0.78 versus 0.87 for the best weeks). But it is
not the whole story — 2025-08-03 has 96% coverage and still scores 0.264, so
genuine rotation is a real secondary mechanism.

**The mechanisms differ by week, and that is the product insight.** *"A novel
constraint entered the binding set"* is a sharper, more actionable alert than
*"the map moved"* — and it implies a different fix (faster incorporation of new
constraints, shorter refit cadence in shoulder seasons) than drift does.

*Caveat:* `rotation` refits on 168 hours at `min_hours=5` and is a noisy
estimator. Read it as directional; §4 is the trustworthy stability number.

### 4. SF is not quasi-static — 0.47, not 0.90

`version2-pivot.md` §3 calls SF "quasi-static, refit weekly." The obvious check —
correlate SF across consecutive weekly refits — gives 0.90 and appears to confirm
it. **That number is contaminated:** consecutive refits use 60-day windows that
overlap by **53 of 60 days**, so it is mostly measuring shared training data.

| estimator | corr(SF, SF′) |
| --- | ---: |
| Consecutive refits, 53/60-day overlap | 0.897 |
| **Disjoint adjacent 60-day windows** | **0.468** |

Disjoint: median 0.471, p25 0.442, min 0.349. Over a 60-day separation the map
retains under half its structure. This refutes the quasi-static premise, explains
why oracle-μ OOS tops out at 0.746 rather than approaching the in-sample 0.99,
and promotes drift from a footnote to a measured, central phenomenon.

## What this implies for the production stage

Detail in `plan/version2-pivot-review.md` §7. In short:

1. **These metrics belong in `diagnostics.py`**, emitted per refit alongside the
   existing in-sample R² — they are the only numbers in the pipeline that mean
   what the pivot needs them to mean.
2. **`sweep_sf.py` should select on them.** It currently selects on in-sample
   `mean_r2` (monotone in `n_kept` — a degrees-of-freedom curve) plus `bp`
   percentiles and clip counts, i.e. on *cosmetics*. The production config was
   never calibrated against anything held out, so **0.746 is likely
   conservative**: the ridge is decorative (λ four orders too small to
   regularize), collinear grouping has not landed, and the coverage gap is
   unaddressed. Re-sweep before treating it as a bound.
