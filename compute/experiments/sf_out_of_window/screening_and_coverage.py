"""Two questions the pooled-R2 gate cannot answer.

(1) SCREENING CURRENCY. Pooled R2 is a $-magnitude yardstick. The commercial
    question is which nodes are worst and in which direction -- rank and sign,
    not variance explained. Measure, per scored hour, cross-node rank-Spearman,
    sign-agreement, and top-decile hit rate, under each mu source. A model can
    have near-zero magnitude skill and still screen well; persistence does.

(2) COVERAGE vs DRIFT. The weekly collapses have two candidate mechanisms with
    opposite fixes:
      coverage = share of the scored week's mu-mass carried by constraints that
                 were IN the fit. Constraints the fit never saw get an implicit
                 SF=0 -- the model cannot see them at all. Low coverage is a
                 COVERAGE failure (fix: faster incorporation of new constraints,
                 shorter refit cadence in shoulder seasons).
      rotation = corr(SF fit on trailing window, SF refit on the scored week).
                 Low rotation is a STABILITY failure (fix: the drift product).

    NOTE: rotation refits on 168h at min_hours=5, so it is a noisy estimator --
    read it as directional. `sf_stability.py` is the trustworthy stability
    number.

    docker compose run --rm compute \
      python -m compute.experiments.sf_out_of_window.screening_and_coverage
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from compute.sf_map.fit import implied_shift_factors

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
    print(f"(1) SCREENING CURRENCY — mean over {len(df)} weeks")
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
