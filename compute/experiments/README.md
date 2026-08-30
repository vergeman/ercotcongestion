# Experiments

Model-selection and diagnostic runs.

1. **`sf_out_of_window/`** — the foundation. Is the SF map worth what the
   pipeline claims out-of-window? Fits production SF unmodified, moving only the
   window boundary, and finds the honest OOS R² (0.746 vs in-sample 0.986) is
   limited by *drift*, not coverage.

2. **`sf/`** — given the map is worth measuring, select its operating point
   `(window=240, refit=7, λ=1)`: the sweep, the coverage-gap decomposition, and
   the collinear-grouping verdict.

3. **`mu/`** — the forecast layer. Holds the SF operating point fixed and varies
   only the feature set: the 5-arm ablation harness and its diagnostics.

(`model_tutorial/` is reference material, not part of this chain.)
