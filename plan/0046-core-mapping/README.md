# Core mapping — branch plans

Discrete branch-scoped decompositions of `plan/sprint-1-plan.md` (the core-mapping pivot).
Each file is one branch of work; sections within each file map to individual commits.

| # | Branch | Scope | Depends on |
|---|--------|-------|------------|
| 01 | `feat/cm.1-correlation-map` | New `compute/mapping/correlation_map.py`; SP → best model bus + ρ distribution. | — |
| 02 | `feat/cm.2-basis-regression` | New `compute/mapping/basis_regression.py`; per-SP R² against model temporal PCA basis. | 01 (shared loader) |
| 03 | `feat/cm.3-cca-scalar` | New `compute/mapping/cca.py`; system-level canonical-correlation scalar + PC cross-check. | 01 (shared loader) |
| 04 | `refactor/cm.4-retire-geo-transfer` | Remove `transfer_labels` from sweep; add `compute/mapping/diagnostics.py`. | 01 |
| 05 | `refactor/cm.5-polygons-display-only` | Polygons demoted to render helper; per-cell output becomes point tags. | 04 |
| 06 | `refactor/cm.6-ranking-demotion` | Composite → model-side only; freeze ref axis; cluster on β; retire redundant algos. | 02, 04, 05 |

Recommended order: 01 → 02 → 03 (parallel-safe) → 04 → 05 → 06.
