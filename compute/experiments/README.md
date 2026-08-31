# Experiments

Model-selection and diagnostic runs.

1. **`sf_out_of_window/`** — the foundation. Is the SF map worth what the
   pipeline claims out-of-window? Fits production SF unmodified, moving only the
   window boundary, and finds the honest OOS R² (0.746 vs in-sample 0.986) is
   limited by *drift*, not coverage.
   * `common.py`: shared rig: panel loading, window filter, R², and the three μ
     sources.
   * `oos_gate.py`: in-sample vs out-of-window, on oracle μ.
   * `screening_and_coverage.py`: four screening metrics, and the
     coverage-vs-drift split.
   * `sf_stability.py`: how fast the SF map actually moves (disjoint windows).

2. **`sf/`** — given the map is worth measuring, select its operating point
   `(window=240, refit=7, λ=1)`: the sweep, the coverage-gap decomposition, and
   the collinear-grouping verdict.
   * `sweep.py`: grid-search the three knobs (window, refit, λ); picks the
     operating point.
   * `grouping_verdict.py`: does bundling look-alike constraints steady the map?
     (no).
   * `coverage.py`: how much congestion lands on unseen constraints, and is it
     worth chasing (no).

3. **`mu/`** — the forecast layer. Holds the SF operating point fixed and varies
   only the feature set: the 5-arm ablation harness and its diagnostics.
   * `feature_ablation.py`: the 5-arm ablation (base/lag/geo/wx/all); which
     inputs help.
   * `outage_ablation.py`: do per-constraint outages beat the zonal average?
     (flat).
   * `rerank.py`: is the tail lost because we rank by the average? (no).

(`model_tutorial/` is reference material, not part of this chain.)
   * `walkthrough.py`: a runnable, database-free synthetic example of the SF and
     μ models.
   * `PRODUCTION_OUTLINE.md`: maps the walkthrough's equations to the production
     entry points.
