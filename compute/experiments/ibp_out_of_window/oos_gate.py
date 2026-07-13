"""The gate: is the SF map worth what the pipeline says it is?

`plan/version2-pivot.md` sec 5 calls the out-of-window SF test "the gate" and
leaves it unrun. It is run here.

Fit SF on the trailing 60d ending STRICTLY BEFORE the scored week, predict the
next 7d from REALIZED mu. This isolates SF stability from any bind-forecasting
skill -- it is the ceiling the forecast product can never exceed, because it
assumes perfect foresight of every shadow price.

Compares against the number the pipeline actually reports, which is fit on a
window containing the scored week (see `common.py` docstring).

    docker compose run --rm compute \
      python -m compute.experiments.ibp_out_of_window.oos_gate
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from compute.implied_binding_proximity.fit import implied_shift_factors

from .common import (
    REFIT_DAYS, WINDOW_DAYS, last_day, load_panels, predict, r2, refit_starts,
    window,
)

RESULTS = Path(__file__).parent / "results"


def main() -> None:
    M, C = load_panels()
    print(f"panel: M {M.shape} (hours x constraints), C {C.shape} (hours x SPs)")

    end_day = last_day(M)
    rows: list[dict] = []

    for s in refit_starts(M):
        score_end = min(s + pd.Timedelta(days=REFIT_DAYS),
                        end_day + pd.Timedelta(days=1))

        # HONEST: window ends where scoring begins.
        fit_w = window(M, s - pd.Timedelta(days=WINDOW_DAYS), s)
        SF = implied_shift_factors(M.loc[fit_w], C.loc[fit_w])
        if SF.empty:
            continue

        # PIPELINE: window ends where scoring ends -> contains the scored week.
        pipe_w = window(M, score_end - pd.Timedelta(days=WINDOW_DAYS), score_end)
        SF_pipe = implied_shift_factors(M.loc[pipe_w], C.loc[pipe_w])

        def score(mask, sf):
            Ms, Cs = M.loc[mask], C.loc[mask]
            i = Ms.index.intersection(Cs.index)
            if not len(i) or sf.empty:
                return np.nan, np.nan
            Y = Cs.loc[i, sf.columns].to_numpy(float)
            Yh = predict(Ms.loc[i], sf)
            per_sp = [r2(Y[:, j], Yh[:, j]) for j in range(Y.shape[1])]
            return r2(Y.ravel(), Yh.ravel()), float(np.nanmedian(per_sp))

        is_pooled, is_med = score(pipe_w, SF_pipe)     # in-sample, as reported
        score_w = window(M, s, score_end)
        oos_pooled, oos_med = score(score_w, SF)       # out-of-window, oracle mu

        Y = C.loc[score_w, SF.columns].to_numpy(float)
        rows.append(dict(
            week=s.date(), n_kept=SF.shape[0],
            is_pooled=is_pooled, is_med_sp=is_med,
            oos_pooled=oos_pooled, oos_med_sp=oos_med,
            zero_pooled=r2(Y.ravel(), np.zeros_like(Y).ravel()),
        ))

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))

    print(f"\n=== MEANS over {len(df)} weeks ===")
    print(f"in-sample pooled R2 (what the pipeline reports) : {df.is_pooled.mean():.4f}")
    print(f"in-sample median-SP R2                          : {df.is_med_sp.mean():.4f}")
    print(f"OUT-OF-WINDOW pooled R2 (oracle mu)             : {df.oos_pooled.mean():.4f}")
    print(f"OUT-OF-WINDOW median-SP R2                      : {df.oos_med_sp.mean():.4f}")
    print(f"predict-zero baseline pooled R2                 : {df.zero_pooled.mean():.4f}")
    print(f"\nOOS pooled median / p25 / min : {df.oos_pooled.median():.3f} / "
          f"{df.oos_pooled.quantile(.25):.3f} / {df.oos_pooled.min():.3f}")

    RESULTS.mkdir(exist_ok=True)
    df.to_csv(RESULTS / "oos_gate.csv", index=False)


if __name__ == "__main__":
    main()
