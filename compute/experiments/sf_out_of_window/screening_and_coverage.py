"""Two questions the main accuracy score (pooled R2) can't answer.

Pooled R2 tells you how close your dollar predictions are, on average. That's not
what a screening tool is for. It leaves two things unmeasured.

(1) SCREENING: which nodes are worst, and in which direction (over- or
    under-priced)." That's about *ranking and sign*, not average accuracy. So
    we measure three things instead: did it rank the nodes worst-to-best
    correctly (rank-Spearman), did it get the direction right (sign-agreement),
    and of the truly worst 10% did it flag them (top-decile hit). A model can
    be nearly useless at predicting exact dollars and still be a great screen
    -- "same as yesterday" (persistence) is exactly that.

(2) COVERAGE OR DRIFT: WHEN A WEEK GOES BAD, WHY? Two different failures, with
    opposite fixes:

      coverage = of all the congestion that actually happened this week, how much
                 landed on constraints the model had even *seen* during training.
                 Anything it never saw is invisible to it (treated as zero). If
                 coverage is low, the fix is to pull new constraints in faster --
                 refit more often, especially in shoulder seasons.

      rotation = how much the shift-factor map *moved* between the training window
                 and the scored week. If it moved a lot, the map itself is
                 unstable -- the fix is a drift product, not more data.

    NOTE: the rotation number here is measured on a short, thin window, so it's
    noisy -- treat it as a rough direction, not a hard figure. For the trustworthy
    stability number, use `sf_stability.py`.

    docker compose run --rm compute \
      python -m compute.experiments.sf_out_of_window.screening_and_coverage

"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from compute.sf_map.model.fit import implied_shift_factors

from .common import (
    REFIT_DAYS, WINDOW_DAYS, last_day, load_panels, mu_climatology, mu_oracle,
    mu_persistence, r2, refit_starts, window,
)

RESULTS = Path(__file__).parent / "results"
SIGN_DEADBAND = 1.0   # $/MWh -- ignore congestion-quiet node-hours


def row_spearman(Y: np.ndarray, Y_hat: np.ndarray) -> float:
    """Mean cross-node rank correlation, computed per hour."""
    out = []
    for a, b in zip(Y, Y_hat):
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() < 10 or np.ptp(a[m]) == 0 or np.ptp(b[m]) == 0:
            continue
        out.append(np.corrcoef(rankdata(a[m]), rankdata(b[m]))[0, 1])
    return float(np.mean(out)) if out else float("nan")


def sign_agreement(Y: np.ndarray, Y_hat: np.ndarray) -> float:
    m = np.isfinite(Y) & np.isfinite(Y_hat) & (np.abs(Y) > SIGN_DEADBAND)
    if m.sum() == 0:
        return float("nan")
    return float((np.sign(Y[m]) == np.sign(Y_hat[m])).mean())


def topdecile_hit(Y: np.ndarray, Y_hat: np.ndarray) -> float:
    """Of the truly worst-decile nodes each hour (most positive congestion),
    what share does the forecast also place in its own worst decile?
    Random baseline = 0.10."""
    out = []
    for a, b in zip(Y, Y_hat):
        m = np.isfinite(a) & np.isfinite(b)
        n = int(m.sum())
        if n < 20:
            continue
        k = max(1, n // 10)
        top_true = set(np.argsort(-a[m])[:k])
        top_pred = set(np.argsort(-b[m])[:k])
        out.append(len(top_true & top_pred) / k)
    return float(np.mean(out)) if out else float("nan")


def main() -> None:
    M, C = load_panels()
    end_day = last_day(M)
    rows: list[dict] = []

    for s in refit_starts(M):
        #
        # Filter datetimes, align window
        #
        score_end = min(s + pd.Timedelta(days=REFIT_DAYS),
                        end_day + pd.Timedelta(days=1))
        fit_w = window(M, s - pd.Timedelta(days=WINDOW_DAYS), s)
        M_fit, C_fit = M.loc[fit_w], C.loc[fit_w]
        SF = implied_shift_factors(M_fit, C_fit)
        if SF.empty:
            continue

        score_w = window(M, s, score_end)
        M_score, C_score = M.loc[score_w], C.loc[score_w]
        hours = M_score.index.intersection(C_score.index)
        if not len(hours):
            continue

        Y = C_score.loc[hours, SF.columns].to_numpy(float)
        cols = M_score.columns.intersection(SF.index)
        S = SF.loc[cols].to_numpy(float)

        #
        # METRICS
        #
        rec: dict = {"week": s.date()}
        mus = {
            "oracle": mu_oracle(M, hours, cols),
            "clim": mu_climatology(M_fit, hours, cols),
            "pers": mu_persistence(M, hours, cols),
        }
        for tag, X in mus.items():
            Y_hat = -(X @ S)
            rec[f"r2_{tag}"] = r2(Y.ravel(), Y_hat.ravel())
            rec[f"spearman_{tag}"] = row_spearman(Y, Y_hat)
            rec[f"sign_{tag}"] = sign_agreement(Y, Y_hat)
            rec[f"topdec_{tag}"] = topdecile_hit(Y, Y_hat)

        # coverage: mu-mass the SF matrix actually has a column for
        mass_all = float(M_score.abs().to_numpy(float).sum())
        mass_in = float(M_score[cols].abs().to_numpy(float).sum())
        rec["coverage"] = mass_in / mass_all if mass_all > 0 else np.nan

        # rotation: refit on the scored week alone, compare shared coefficients
        SF_week = implied_shift_factors(M_score, C_score, min_hours=5)
        shared = SF.index.intersection(SF_week.index)
        rec["n_shared"] = len(shared)
        rec["rotation_corr"] = (
            float(np.corrcoef(SF.loc[shared].to_numpy(float).ravel(),
                              SF_week.loc[shared].to_numpy(float).ravel())[0, 1])
            if len(shared) > 5 else np.nan
        )
        rows.append(rec)

    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)

    print("=" * 78)
    print(f"(1) SCREENING — mean over {len(df)} weeks")
    print("=" * 78)
    print(f"{'mu source':<14}{'pooled R2':>11}{'rank-Spearman':>16}"
          f"{'sign-agree':>13}{'top-decile hit':>17}")
    for tag, name in (("oracle", "oracle"), ("clim", "climatology"),
                      ("pers", "persistence")):
        print(f"{name:<14}{df[f'r2_{tag}'].mean():>11.3f}"
              f"{df[f'spearman_{tag}'].mean():>16.3f}"
              f"{df[f'sign_{tag}'].mean():>13.3f}"
              f"{df[f'topdec_{tag}'].mean():>17.3f}")
    print("\nnull: pooled R2 -0.042 | Spearman 0.0 | sign 0.500 | top-decile 0.100")

    print("\n" + "=" * 78)
    print("(2) COVERAGE vs DRIFT — worst 8 weeks by oracle-mu R2")
    print("=" * 78)
    cols = ["week", "r2_oracle", "coverage", "rotation_corr", "n_shared"]
    fmt = lambda v: f"{v:8.3f}"  # noqa: E731
    ordered = df.sort_values("r2_oracle")
    print(ordered.head(8)[cols].to_string(index=False, float_format=fmt))
    print("\nbest 8 weeks:")
    print(ordered.tail(8)[cols].to_string(index=False, float_format=fmt))

    print(f"\ncoverage      : mean {df.coverage.mean():.3f}  min {df.coverage.min():.3f}")
    print(f"rotation_corr : mean {df.rotation_corr.mean():.3f}  "
          f"min {df.rotation_corr.min():.3f}   (noisy — see sf_stability.py)")
    print(f"\ncorr( weekly oracle-R2 , coverage )      = "
          f"{df[['r2_oracle', 'coverage']].corr().iloc[0, 1]:.3f}")
    print(f"corr( weekly oracle-R2 , rotation_corr ) = "
          f"{df[['r2_oracle', 'rotation_corr']].corr().iloc[0, 1]:.3f}")

    RESULTS.mkdir(exist_ok=True)
    df.to_csv(RESULTS / "screening_and_coverage.csv", index=False)


if __name__ == "__main__":
    main()
