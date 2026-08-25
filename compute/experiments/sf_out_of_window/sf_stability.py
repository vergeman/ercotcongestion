"""How fast does the SF map actually move?

`plan/version2-pivot.md` sec 3 asserts SF is "quasi-static, refit weekly". The
obvious check -- correlate SF between consecutive weekly refits -- gives 0.90
and appears to confirm it. That number is contaminated: consecutive refits use
60-day windows that OVERLAP BY 53 OF 60 DAYS, so the correlation is mostly
measuring shared training data, not stability.

Re-measured on DISJOINT adjacent 60-day windows, SF retains under half its
structure (0.47). The map is not quasi-static. This is a direct cause of the
gap between the in-sample R2 (0.986) and the out-of-window R2 (0.746) in
`oos_gate.py`, and it is why drift belongs in the product rather than in a
footnote.

    docker compose run --rm compute \
      python -m compute.experiments.sf_out_of_window.sf_stability
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from compute.sf_map.model.fit import implied_shift_factors

from .common import REFIT_DAYS, WINDOW_DAYS, load_panels, window

RESULTS = Path(__file__).parent / "results"


def main() -> None:
    M, C = load_panels()

    def fit(start, end):
        w = window(M, start, end)
        return implied_shift_factors(M.loc[w], C.loc[w])

    def corr(A: pd.DataFrame, B: pd.DataFrame) -> tuple[float, int]:
        shared = A.index.intersection(B.index)
        if len(shared) < 5:
            return float("nan"), len(shared)
        return float(np.corrcoef(A.loc[shared].to_numpy(float).ravel(),
                                 B.loc[shared].to_numpy(float).ravel())[0, 1]), len(shared)

    days = pd.Index(M.index.normalize().unique()).sort_values()
    D = pd.Timedelta(days=1)
    rows: list[dict] = []

    # Need 2 x window_days of history behind each point for the disjoint pair.
    for s in pd.date_range(days[0] + 2 * WINDOW_DAYS * D, days[-1],
                           freq=pd.Timedelta(days=REFIT_DAYS), inclusive="left"):
        older = fit(s - 2 * WINDOW_DAYS * D, s - WINDOW_DAYS * D)
        newer = fit(s - WINDOW_DAYS * D, s)
        # what the production cadence compares: 53/60 days of shared data
        prev_refit = fit(s - (WINDOW_DAYS + REFIT_DAYS) * D, s - REFIT_DAYS * D)

        c_disjoint, n = corr(older, newer)
        c_overlap, _ = corr(prev_refit, newer)
        rows.append(dict(week=s.date(), overlapping_60d=c_overlap,
                         disjoint_60d=c_disjoint, n_shared=n))

    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))

    print("\n=== SF stability, by estimator ===")
    print(f"  consecutive refits, 53/60-day OVERLAP (contaminated) : "
          f"{df.overlapping_60d.mean():.3f}")
    print(f"  DISJOINT adjacent 60-day windows (honest)            : "
          f"{df.disjoint_60d.mean():.3f}")
    print(f"    disjoint  median {df.disjoint_60d.median():.3f}  "
          f"p25 {df.disjoint_60d.quantile(.25):.3f}  min {df.disjoint_60d.min():.3f}")

    RESULTS.mkdir(exist_ok=True)
    df.to_csv(RESULTS / "sf_stability.csv", index=False)


if __name__ == "__main__":
    main()
