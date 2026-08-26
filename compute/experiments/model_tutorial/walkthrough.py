"""A tiny, database-free version of the SF and mu models.

Run with ``python -m compute.experiments.model_tutorial.walkthrough``.
The numbers are synthetic.  The calculations and the table shapes match the
important parts of the production models, without their data-loading and
walk-forward machinery.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from compute.mu_forecast.model.heads import (apply_encoding, fit_bind_head, fit_mu_head,
                                              fold_matrix, predict_mu_head, target_encoding)
from compute.sf_map.model.fit import implied_shift_factors


KEYS = ("north_line", "west_line", "coast_line")
SPS = ("North_Node", "West_Node")


def make_example() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return shadow prices M, congestion C, and the small mu-model panel."""
    rng = np.random.default_rng(7)
    hours = pd.date_range("2025-07-01", periods=24 * 41, freq="h", tz="UTC")
    # arange: sequential range from 0, len(hours) -> 984
    net_load = 52_000 + 12_000 * np.sin(np.arange(len(hours)) / 24 * 2 * np.pi)
    net_load += rng.normal(0, 1_500, len(hours))
    # normal distribution [0, 1500] value for each hour
    # basically we have time periods and generated net_load values
    # shaped sine wave each hour

    # M has one row per hour and one column per constraint.  Zero means the
    # constraint did not bind in that hour.
    thresholds = np.array([56_000, 52_000, 59_000])
    sensitivity = np.array([0.009, 0.006, 0.008])
    raw = (net_load[:, None] - thresholds) * sensitivity
    # net_load[: None] turns net_load 1d array (984,) to (984, 1) 2d (984 rows, 1 col)
    # then subtract thresholds 1d array(, 3); (984, 1) - (, 3)  -> (984, 3)
    #
    # subtract x0 - thres[0], x0 - thres[1], x0 - thres[2]
    # subtract x1 - thres[0], x1 - thres[1], x1 - thres[2]
    # ...
    # raw.shape (984, 3)

    M = pd.DataFrame(np.maximum(raw + rng.normal(0, 10, raw.shape), 0),
                     index=hours, columns=KEYS)

    # so we basically converted net load into shadow prices
    # M = time x constraint  - where cells are mu


    # These are planted only so the tutorial can check that ridge retrieves a
    # sensible spatial map. Production does not know this answer in advance.
    #
    # sf - shift factors
    # M = (984, 3) @ planted_sf (3, 2): @ matrix multi
    # C = M @ planted_sf -> (984, 2)
    #
    planted_sf = np.array([[0.35, -0.10], [-0.25, 0.45], [0.15, 0.20]])
    C = pd.DataFrame(-(M.to_numpy() @ planted_sf) + rng.normal(0, 0.4, (len(M), 2)),
                     index=hours, columns=SPS)

    # The mu panel is long rather than wide: one row for each (hour, constraint).
    # These three inputs stand in for the much wider production feature panel.
    panel = (pd.DataFrame({"interval_ts": np.repeat(hours, len(KEYS)),
                          "key": np.tile(KEYS, len(hours)),
                          "net_load": np.repeat(net_load, len(KEYS)),
                          "hour": np.repeat(hours.hour, len(KEYS))})
             .set_index(["interval_ts", "key"]))

    # KEYS: constraints, SPS: settlment points
    # reshape(-1): flatten to 1d array, "-1" infer dimension
    # y_bind set if y_mu is > 1, else 0
    # then filter on the 0/1 y_bind, and set to np.nan
    panel["y_mu"] = M.reindex(columns=KEYS).to_numpy().reshape(-1)
    panel["y_bind"] = (panel["y_mu"] > 1.0).astype("int8")
    panel.loc[panel["y_bind"] == 0, "y_mu"] = np.nan

    # panel is (interval_ts, key) constraint row with netload, hour, y_mu and y_bind
    # its kind of an awkward shape (2952, 4)
    #                                               net_load  hour       y_mu  y_bind
    # interval_ts               key
    # 2025-07-01 00:00:00+00:00 north_line  52001.845230     0        NaN       0
    #                           west_line   52001.845230     0        NaN       0
    #                           coast_line  52001.845230     0        NaN       0
    # 2025-07-01 01:00:00+00:00 north_line  55553.946847     1        NaN       0
    #                           west_line   55553.946847     1  20.390796       1
    # ...                                            ...   ...        ...     ...
    # 2025-08-10 22:00:00+00:00 west_line   45959.938368    22        NaN       0
    #                           coast_line  45959.938368    22        NaN       0
    # 2025-08-10 23:00:00+00:00 north_line  49639.406741    23        NaN       0
    #                           west_line   49639.406741    23   6.885896       1
    #                           coast_line  49639.406741    23        NaN       0

    return M, C, panel


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit both tutorial models and return the SF matrix and one-day forecast."""
    M, C, panel = make_example() # synth data

    # --- Part 1: SF.  Rows are constraints; columns are settlement points.
    #                  values are SF [-1, 1]
    sf = implied_shift_factors(M, C, lam=1.0, min_hours=10, std_floor=20.0)

    # --- Part 2: mu.  Train on 40 days and predict the final day.
    # panel.index.get_level_values(field): level in multiindex - "position in index tuple"
    # cutoff -> min date
    # train, score: filtered panel before, after cutoff date
    cutoff = panel.index.get_level_values("interval_ts").min() + pd.Timedelta(days=40)
    train = panel[panel.index.get_level_values("interval_ts") < cutoff]
    score = panel[panel.index.get_level_values("interval_ts") >= cutoff]
    features = ["net_load", "hour", "key_bind_rate"]

    # This rate is calculated from training rows only.  It gives the pooled model
    # a small, safely-smoothed description of which constraint this row concerns.

    # key_bind_rate: basically an empirical base rate; a default
    #
    # pooled rate:  0.390972
    # rates:
    # key
    # coast_line    0.295593
    # north_line    0.387672
    # west_line     0.489652

    rates, pooled_rate = target_encoding(train)

    # apply_encoding() applies rates; sets each line's value to key_bind_rate
    # (repeated every hour, each respective rate from rates, per key)
    # train pre cutoff, score post cutoff
    #     (Pdb) train
    #                                           net_load  hour       y_mu  y_bind  key_bind_rate
    # interval_ts               key
    # 2025-07-01 00:00:00+00:00 north_line  52001.845230     0        NaN       0       0.387672
    #                           west_line   52001.845230     0        NaN       0       0.489652
    #                           coast_line  52001.845230     0        NaN       0       0.295593
    # 2025-07-01 01:00:00+00:00 north_line  55553.946847     1        NaN       0       0.387672
    #                           west_line   55553.946847     1  20.390796       1       0.489652

    # Model input x: (time, key) -> features[net_load, hour, key_bind_rate]
    # model head 1: train input x  predict_proba y_bind [0,1] probability
    # model head 2: train input x, predict y_mu  log([0, n]) value
    train = apply_encoding(train, rates, pooled_rate)
    score = apply_encoding(score, rates, pooled_rate)


    # HistGradientBoostingClassifier: bind model classifier -
    # what is P(bind), or what is y_bind (0 or 1) given the fold _matrix below
    # fold matrix:          hours x features (net_load, hour, key_bind_rate)
    # fit_bind_head(x, y): builds and calls model.fit(x, y) -> model.fit(fold_matrix, y_bind)
    #
    # once we fit the model, then we predict_proba on subsequent 'score' group (after cut off)
    #
    # p_bind.shape: (72,) - matches len(score)
    # array([1.40813984e-01, 9.16193729e-01, 7.28559639e-03, 9.58178113e-01,
    #   9.96574074e-01, 1.95720914e-01, 2.88229201e-01, 9.44897528e-01,
    #   1.04575172e-02, 9.89645000e-01, 9.98676010e-01, 2.25461166e-01 ...

    bind_model = fit_bind_head(fold_matrix(train, features), train["y_bind"].to_numpy())
    p_bind = bind_model.predict_proba(fold_matrix(score, features))[:, 1]  # (n_samples, n_classes)


    # The second model never sees non-binding rows. It therefore learns the size
    # of the shadow price *if* the first event happens.
    #
    # binders = filter only binding
    # fit_mu_head: HistGradientBoostingRegressor -> mu_model.
    #    model.fit(binders[cols], np.log1p(binders["y_mu"].clip(lower=MU_FLOOR)))
    #    log1p compresses extreme shadow prices
    # predict_mu_head:
    #    np.expm1(model.predict(score[features]))
    #    np.expm1: back-transform of a mean-in-log-space systematically underestimates mean
    #      NB: not probability but acutal value mu (why we use model.predict, not model.predict_proba)
    binders = train[train["y_bind"] == 1]
    mu_model = fit_mu_head(binders, features)  # y_mu
    mu_if_bind = predict_mu_head(mu_model, score, features)

    forecast = score.reset_index()[["interval_ts", "key", "net_load"]].copy()
    forecast["p_bind"] = p_bind
    forecast["mu_if_bind"] = mu_if_bind

    # "Hurdle Model": one head for the hurdle, one for the magnitude
    # E[mu]                 = P(bind)            * E(mu | bind)
    # med (product)         small (probability)    large: shadow price bind jump
    forecast["expected_mu"] = forecast["p_bind"] * forecast["mu_if_bind"]
    return sf, forecast, M, C, panel


def main() -> None:
    sf, forecast, M, C, panel = run()
    print("INPUT: M (hour x constraint) shadow prices")
    print("       C (hour x settlement point) congestion = LMP - system lambda\n")
    print("RIDGE OUTPUT: SF (constraint x settlement point)")
    print(sf.round(3).to_string())
    print("\nTWO-HEAD OUTPUT: final-day rows (first 9)")
    print(forecast.head(9).round({"net_load": 0, "p_bind": 3,
                                  "mu_if_bind": 2, "expected_mu": 2}).to_string(index=False))
    print("\nexpected_mu = p_bind * mu_if_bind")
    return sf, forecast, M, C, panel

if __name__ == "__main__":
    sf, forecast, M, C, panel = main()
