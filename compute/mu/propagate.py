"""Commit 5 — sample the heads, push them through the map, read the bands. Then
the R5 verdict, against the bar as written.

The point forecast (commit 4) answers "how close is the number". This answers the
question a trader actually asks — *how sure are you* — by turning the two heads
back into the distribution they were always implicitly describing:

    for each draw d:
        bind[k,h] ~ Bernoulli(p_bind[k,h])              # head 1
        μ[k,h]    ~ E[μ|bind][k,h] · exp(ε),  ε ~ residuals   # head 2 + spread
        C[·,h]    = −μ[·,h] · SF                        # the map, unchanged
    P10/P50/P90 = percentiles of C across draws

**Where the spread comes from, and why not from the training window.** Head 2 is a
GBM; its residuals *on its own training window* are the residuals of a model that
has already fitted them, so they are too small, and bands built from them would be
confidently narrow — the exact failure the 0085 summary calls "a confident wrong
band is worse than an honest wide one". Instead the residual pool for week `s` is
the log-space error the model made on **the weeks it already scored, all strictly
before `s`** — genuinely out-of-sample errors, from the same model, on the same
market. Week 1 therefore has no pool and gets no bands: 46 weeks are scored, 45
carry bands, and that is stated rather than papered over.

**The known understatement.** Head 1 is sampled independently per constraint. The
constraints are collinear (0083 — that is *why* R3 failed), so the true joint
binding set is far more correlated than independent Bernoullis, and a sum of
independent draws has too thin a tail. This makes coverage a *measurement*, not a
formality: if the bands are too narrow, this is the first place to look. Reported,
not assumed away.

    docker compose run --rm compute python -m compute.mu.propagate \
      --preds /compute/mu/mu_preds.npz --out /compute/mu/mu_bands_weekly.csv
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from compute.mu.score import (
    LAM, MIN_HOURS, REFIT_DAYS, RTC_B, STD_FLOOR, WINDOW_DAYS, score_matrix,
    weeks_from_preds,
)
from compute.sf.fit import implied_shift_factors

log = logging.getLogger("compute.mu.propagate")

N_DRAWS = 200
DRAW_CHUNK = 25          # cap peak memory; percentiles need every draw kept
RESID_CAP = 500_000      # the pool is sampled from, not enumerated
QUANTILES = (10, 50, 90)


@dataclass
class NodalPanel:
    """The per-SP forecast panel `walk()` already computes and discards.

    The node axis is ragged week to week — it is exactly `SF.columns` for the
    week's fit, never unioned or filled — so a panel is one window's grid, not
    a dense cross-week array. `point` is the deterministic `E[μ]·SF` (§4), which
    is NOT the sampling median `p50`; both are stored because they differ.
    """
    ts: np.ndarray                  # (H,)   tz-aware UTC hours = `hours`
    settlement_points: np.ndarray   # (N,)   = SF.columns
    p10: np.ndarray                 # (H, N) float32
    p50: np.ndarray                 # (H, N) float32  median of draws
    p90: np.ndarray                 # (H, N) float32
    point: np.ndarray               # (H, N) float32  deterministic E[μ]·SF
    sf_r2: np.ndarray | None        # (N,)   per-SP SF fit R², if available


def _epoch_us(idx) -> np.ndarray:
    """int64 UTC microseconds, matching `mu_model.save_preds`' timestamp encoding.

    Microseconds (not ns) because pandas 3 makes `us` the default resolution, so
    an ns round-trip returns a different dtype and silently fails an index
    compare; the data is hourly, so there is no precision to lose either way.
    """
    di = pd.DatetimeIndex(idx)
    if di.tz is not None:
        di = di.tz_convert("UTC").tz_localize(None)
    return di.to_numpy("datetime64[us]").astype("int64")


class _NodalAccumulator:
    """Streams `NodalPanel`s to flat vocab-coded columns one window at a time.

    The node axis is ragged week to week (§9), so weeks are never densified into
    a common `(T, N, 3)` array: each panel's `(H, N)` grids are raveled to
    `(H*N,)` rows and its SPs mapped onto one growing `sp_vocab` — the same
    `key_vocab` + `key_code` idiom `mu_model.save_preds` uses to keep repeated
    strings out of the file. Peak memory is one week of percentiles (~2 MB), not
    the 45-week concat.
    """

    def __init__(self) -> None:
        self._sp_code: dict[str, int] = {}
        self._buf: dict[str, list[np.ndarray]] = {
            k: [] for k in ("ts", "sp_code", "p10", "p50", "p90", "point", "week")}

    def add(self, panel: NodalPanel, week: pd.Timestamp) -> None:
        H, N = len(panel.ts), len(panel.settlement_points)
        code = np.fromiter(
            (self._sp_code.setdefault(str(sp), len(self._sp_code))
             for sp in panel.settlement_points),
            dtype=np.int32, count=N)
        ts_us = _epoch_us(panel.ts)                          # (H,)
        week_us = int(_epoch_us(pd.DatetimeIndex([week]))[0])
        # Row r = h*N + n: `ravel` is C-order (hour-major), so `repeat` the hours
        # and `tile` the SP codes to line the axes up with the percentile grids.
        b = self._buf
        b["ts"].append(np.repeat(ts_us, N))
        b["sp_code"].append(np.tile(code, H))
        b["p10"].append(panel.p10.ravel())
        b["p50"].append(panel.p50.ravel())
        b["p90"].append(panel.p90.ravel())
        b["point"].append(panel.point.ravel())
        b["week"].append(np.full(H * N, week_us, dtype=np.int64))

    def save(self, path: str) -> None:
        cols = {k: (np.concatenate(v) if v else np.empty(0, np.int64))
                for k, v in self._buf.items()}
        vocab = np.array(list(self._sp_code), dtype=object).astype("U")
        save_nodal(path, cols, vocab)


def save_nodal(path: str, cols: dict[str, np.ndarray], sp_vocab: np.ndarray) -> None:
    """Write the flat nodal panel as a compressed .npz.

    Same encoding as `mu_model.save_preds`: int64 UTC-µs `ts`/`week`, an int32
    `sp_code` against a string `sp_vocab` (never a string per row — at ~7.5M rows
    that is a gigabyte of repeated SP names), float32 percentiles + `point`.
    """
    np.savez_compressed(
        path,
        ts=cols["ts"].astype("int64"),
        sp_code=cols["sp_code"].astype("int32"),
        sp_vocab=np.asarray(sp_vocab, dtype=object).astype("U"),
        p10=cols["p10"].astype("float32"),
        p50=cols["p50"].astype("float32"),
        p90=cols["p90"].astype("float32"),
        point=cols["point"].astype("float32"),
        week=cols["week"].astype("int64"),
    )


def load_nodal(path: str) -> pd.DataFrame:
    """Inverse of `save_nodal`: tz-aware UTC `ts`/`week`, decoded
    `settlement_point`, and the p10/p50/p90/point columns. Round-trips exactly —
    see the test."""
    z = np.load(path, allow_pickle=False)
    vocab = z["sp_vocab"]
    return pd.DataFrame({
        "ts": pd.to_datetime(z["ts"], unit="us", utc=True),
        "settlement_point": vocab[z["sp_code"]],
        "p10": z["p10"], "p50": z["p50"], "p90": z["p90"], "point": z["point"],
        "week": pd.to_datetime(z["week"], unit="us", utc=True),
    })


def residual_pool(prior: pd.DataFrame, cap: int = RESID_CAP,
                  rng: np.random.Generator | None = None) -> np.ndarray:
    """Head 2's out-of-sample log-space errors on the weeks already behind us.

    Log space because head 2 fits `log1p(μ)` — μ spans $0.01 to $4,000 and an
    additive residual drawn from that would be meaningless at one end and absurd
    at the other. `expm1(log1p(μ̂) + ε)` keeps the draw positive and scales the
    spread with the level, which is how shadow prices actually behave.
    """
    b = prior[(prior["y_bind"] == 1) & prior["y_mu"].notna()]
    if b.empty:
        return np.array([], dtype=np.float32)
    eps = (np.log1p(b["y_mu"].to_numpy(np.float64))
           - np.log1p(np.clip(b["mu_gbm"].to_numpy(np.float64), 0, None)))
    eps = eps[np.isfinite(eps)].astype(np.float32)
    if len(eps) > cap:
        rng = rng or np.random.default_rng(0)
        eps = rng.choice(eps, size=cap, replace=False)
    return eps


def _wide(week_preds: pd.DataFrame, col: str, hours: pd.DatetimeIndex,
          cols: pd.Index) -> np.ndarray:
    w = week_preds.pivot_table(index="interval_ts", columns="key", values=col,
                               aggfunc="mean")
    return w.reindex(index=hours, columns=cols).fillna(0.0).to_numpy(np.float32)


def draw_congestion(week_preds: pd.DataFrame, SF: pd.DataFrame,
                    hours: pd.DatetimeIndex, eps: np.ndarray,
                    n_draws: int = N_DRAWS,
                    rng: np.random.Generator | None = None,
                    *, want_point: bool = False,
                    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """(draws × hours × nodes) of sampled nodal congestion.

    With `want_point`, also return the deterministic point forecast
    `point = −(E[μ]·SF)` where `E[μ] = P(bind)·E[μ|bind]` (§4). It reuses the
    `P`/`MU`/`SFm` arrays already built here — no sampling, no second SF
    multiply — and is the model's expectation, distinct from the draws' median.
    """
    rng = rng or np.random.default_rng(0)
    cols = SF.index                                   # only keys the map carries
    P = _wide(week_preds, "p_bind", hours, cols)      # (H, K)
    MU = _wide(week_preds, "mu_gbm", hours, cols)     # (H, K) = E[μ | bind]
    SFm = SF.to_numpy(np.float32)                     # (K, N)
    H, K, N = len(hours), len(cols), SF.shape[1]

    out = np.empty((n_draws, H, N), dtype=np.float32)
    log_mu = np.log1p(np.clip(MU, 0, None))
    for lo in range(0, n_draws, DRAW_CHUNK):
        d = min(DRAW_CHUNK, n_draws - lo)
        bind = rng.random((d, H, K), dtype=np.float32) < P            # head 1
        e = (rng.choice(eps, size=(d, H, K)) if len(eps)
             else np.zeros((d, H, K), np.float32))                    # spread
        mu = np.expm1(log_mu[None] + e) * bind                        # head 2
        np.clip(mu, 0, None, out=mu)          # a shadow price is never negative
        out[lo:lo + d] = -(mu.reshape(d * H, K) @ SFm).reshape(d, H, N)
    if want_point:
        E_mu = P * MU                                 # (H, K) E[μ]=P(bind)·E[μ|bind]
        point = -(E_mu @ SFm).astype(np.float32)      # (H, N) same sign as draws
        return out, point
    return out


def band_metrics(Y: np.ndarray, p10: np.ndarray, p50: np.ndarray,
                 p90: np.ndarray) -> dict:
    """Coverage FIRST, then skill. A band that misses is not a narrower band, it
    is a wrong one, and P50 skill next to broken coverage is a sales pitch.

    Percentiles are computed once by the caller (`np.percentile(draws,
    QUANTILES, axis=0)`) and passed in, so the scored p50 and the served p50
    can never diverge — both read the same array."""
    inside = (Y >= p10) & (Y <= p90)
    m = {
        "coverage80": float(np.nanmean(inside)),      # target 0.80
        "band_width": float(np.nanmean(p90 - p10)),
        "pinball": float(np.nanmean([_pinball(Y, q, p / 100)
                                     for q, p in zip((p10, p50, p90), QUANTILES)])),
        **score_matrix(Y, p50),                       # P50 is the point forecast
    }
    return m


def _pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = y - q
    return float(np.nanmean(np.maximum(tau * d, (tau - 1) * d)))


def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    eps: np.ndarray, n_draws: int, rng: np.random.Generator,
    *, want_panel: bool = False,
) -> tuple[dict | None, NodalPanel | None]:
    """One window, shared by the backtest and (later) `forecast_day`.

    Fit SF on ``[s−WINDOW_DAYS, s)``, score/draw over ``[s, end)``, and build the
    weekly-metrics row exactly as `walk()` did. Returns ``(row, None)`` normally;
    with ``want_panel`` also returns the `NodalPanel` teed from the same draws and
    the same `np.percentile` call the metrics use. ``(None, None)`` on any skip
    (empty fit window, empty SF, no scored hours) — the caller's `continue`.
    """
    lo, hi = s - pd.Timedelta(days=WINDOW_DAYS), s
    M_fit = M.loc[(M.index >= lo) & (M.index < hi)]
    C_fit = C.loc[(C.index >= lo) & (C.index < hi)]
    if M_fit.empty:
        return None, None
    SF = implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                               standardize=True, std_floor=STD_FLOOR)
    if SF.empty:
        return None, None

    M_score = M.loc[(M.index >= s) & (M.index < end)]
    C_score = C.loc[(C.index >= s) & (C.index < end)]
    hours = M_score.index.intersection(C_score.index)
    if not len(hours):
        return None, None

    wp = wp[wp["key"].isin(SF.index)]
    Y = C_score.loc[hours, SF.columns].to_numpy(np.float32)

    mass_all = float(M_score.abs().to_numpy(float).sum())
    cov_cols = M_score.columns.intersection(SF.index)
    sf_coverage = (float(M_score[cov_cols].abs().to_numpy(float).sum())
                   / mass_all if mass_all > 0 else np.nan)

    panel = None
    if want_panel:
        draws, point = draw_congestion(wp, SF, hours, eps, n_draws, rng,
                                       want_point=True)
        p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)
        panel = NodalPanel(
            ts=hours.to_numpy(),
            settlement_points=SF.columns.to_numpy(),
            p10=p10.astype(np.float32), p50=p50.astype(np.float32),
            p90=p90.astype(np.float32), point=point,
            sf_r2=None,          # implied_shift_factors exposes no per-SP R² (§11)
        )
    else:
        draws = draw_congestion(wp, SF, hours, eps, n_draws, rng)
        p10, p50, p90 = np.percentile(draws, QUANTILES, axis=0)

    row = {"week": s, "n_hours": len(hours), "n_nodes": SF.shape[1],
           "n_resid": len(eps), "sf_coverage": sf_coverage,
           **band_metrics(Y, p10, p50, p90)}
    return row, panel


def walk(M: pd.DataFrame, C: pd.DataFrame, preds: pd.DataFrame,
         n_draws: int = N_DRAWS, seed: int = 0,
         nodal_out: str | None = None) -> pd.DataFrame:
    if isinstance(preds.index, pd.MultiIndex):
        preds = preds.reset_index()
    weeks = weeks_from_preds(preds)
    rng = np.random.default_rng(seed)
    log.info("propagating %d weeks × %d draws (week 1 has no residual pool → no "
             "bands)", len(weeks), n_draws)

    # Emitting the panel only tees the arrays already computed — same rng draws,
    # so the metrics row (and `mu_bands_weekly.csv`) is byte-identical either way.
    sink = _NodalAccumulator() if nodal_out else None
    by_week = dict(tuple(preds.groupby("week", sort=False)))
    rows: list[dict] = []
    t0 = time.perf_counter()
    for i, s in enumerate(weeks):
        # The pool is every week the model has ALREADY scored — out-of-sample
        # errors, strictly in the past. Empty on week 1, by construction.
        prior = preds[preds["week"] < s]
        eps = residual_pool(prior, rng=rng)
        if not len(eps):
            log.info("  week %2d/%d %s  no residual pool yet — skipped",
                     i + 1, len(weeks), s.date())
            continue

        end = s + pd.Timedelta(days=REFIT_DAYS)
        row, panel = propagate_window(s, end, M, C, by_week[s], eps, n_draws, rng,
                                      want_panel=sink is not None)
        if row is None:
            continue

        rows.append(row)
        if sink is not None:
            sink.add(panel, s)
        done, el = i + 1, time.perf_counter() - t0
        log.info("  week %2d/%d %s  cov80 %.3f  P50 R2 %+.3f  eta %.0fm",
                 done, len(weeks), s.date(), rows[-1]["coverage80"],
                 rows[-1]["pooled_r2"], (el / done) * (len(weeks) - done) / 60)
    if sink is not None:
        sink.save(nodal_out)
        log.info("wrote nodal panel → %s", nodal_out)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# R5 — the verdict, against the bar as written
# --------------------------------------------------------------------------

def gate(r2: float, spearman: float, sign: float, topdec: float) -> str:
    """§5.5, transcribed. Either currency can clear a row ("either bar clears").

    Written as code so the bar cannot drift while being read. It was fixed before
    the numbers existed and is not edited now that they do — that is the whole
    point of pre-registering it. If this function and the doc ever disagree, the
    doc wins and this is the bug.
    """
    if r2 >= 0.5 or (spearman >= 0.70 and sign >= 0.85):
        return "FORECAST PRODUCT"
    if (0.3 <= r2 < 0.5) or (0.60 <= spearman < 0.70 and topdec >= 0.60):
        return "SCREENING TOOL"
    if r2 < 0.3 or (spearman < 0.60 and topdec <= 0.649):
        return "NOT THE PRODUCT"
    return "BETWEEN BARS — read the table, do not round"


def existence_test(model: dict, persistence: dict) -> tuple[bool, str]:
    """"Beat persistence in the screening currency" (handoff §5.5).

    Relative, so persistence must be the one measured in THIS harness — the
    0.581/0.771/0.649 in the handoff came from the old 60-day, λ=0.1 map, and
    grading against those would be grading against a different experiment.
    """
    keys = ["rank_spearman", "sign_agree", "topdecile_hit"]
    wins = {k: model[k] > persistence[k] for k in keys}
    detail = "  ".join(
        f"{k.split('_')[0]} {model[k]:.3f} vs {persistence[k]:.3f} "
        f"{'WIN' if wins[k] else 'LOSS'}" for k in keys)
    return all(wins.values()), detail


def r5(score_csv: pd.DataFrame, bands: pd.DataFrame) -> str:
    """Both readings of R5, printed together, in the currency each was set in."""
    a = score_csv[score_csv["regime"] == "all"]
    out = ["\n=== R5 — does the covariate μ-model beat persistence? ===\n"]

    def cell(src: str, d: pd.DataFrame) -> dict:
        r = d[d["source"] == src]
        return {k: float(r[k].mean()) for k in
                ["pooled_r2", "rank_spearman", "sign_agree", "topdecile_hit"]}

    for label, d in [("ALL 46 WEEKS", a),
                     ("PRE-RTC+B", a[a["week"] < RTC_B]),
                     ("POST-RTC+B", a[a["week"] >= RTC_B])]:
        m, p = cell("model", d), cell("persistence", d)
        v = gate(m["pooled_r2"], m["rank_spearman"], m["sign_agree"],
                 m["topdecile_hit"])
        beat, detail = existence_test(m, p)
        out += [f"{label}  (n={d['week'].nunique()})",
                f"  gate            : {v}",
                f"    R² {m['pooled_r2']:+.3f} (bar 0.50 / 0.30)   "
                f"Spearman {m['rank_spearman']:.3f} (bar 0.70 / 0.60)   "
                f"sign {m['sign_agree']:.3f} (bar 0.85)   "
                f"top-dec {m['topdecile_hit']:.3f} (bar 0.60)",
                f"  existence test  : {'PASS' if beat else 'FAIL'} — {detail}",
                ""]

    if not bands.empty:
        out += ["=== BANDS (P10/P50/P90) ===",
                f"  weeks {len(bands)}   coverage80 {bands.coverage80.mean():.3f} "
                f"(target 0.800)   mean width ${bands.band_width.mean():.2f}",
                f"  P50: R² {bands.pooled_r2.mean():+.3f}   MAE "
                f"${bands.mae.mean():.2f}   pinball {bands.pinball.mean():.3f}",
                f"  SF coverage {bands.sf_coverage.mean():.3f} — μ-mass the map "
                f"has a column for; the rest is the map's blind spot, not the "
                f"forecast's miss", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import psycopg

    from compute.mu.mu_model import load_preds
    from compute.sf.panels import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preds", default="/compute/mu/mu_preds.npz")
    p.add_argument("--scores", default="/compute/mu/mu_score_weekly.csv")
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--draws", type=int, default=N_DRAWS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None)
    p.add_argument("--nodal-out", default=None,
                   help="stream the per-week nodal P10/P50/P90 + point panel to "
                        "this flat vocab-coded .npz; omit and nothing changes "
                        "(no panel, metrics CSV byte-identical)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    preds = load_preds(args.preds)
    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
    log.info("M = %s   C = %s", M.shape, C.shape)

    bands = walk(M, C, preds, args.draws, args.seed, nodal_out=args.nodal_out)
    scores = pd.read_csv(args.scores, parse_dates=["week"])
    print(r5(scores, bands))
    if args.out and not bands.empty:
        bands.to_csv(args.out, index=False)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
