"""The `grade_day` job — grade the SERVED forecast for one delivery day D.

The live half of the scoreboard (plan/0102 Phase 3, 0003-live-grading). Where the
backtest board (compute.jobs.load_scoreboard → scoreboard_weekly) transcribes a
pre-registered walk, this grades what `daily_forecast` actually *served*, one day
behind, once realized DAM prices publish:

  1. pull the served point forecast for D from `forecast_nodal` (the deterministic
     E[μ]·SF the model published at D−1 close);
  2. build realized nodal congestion for D — `SPP − system_λ`, the same quantity
     the map fits and the realized pane serves;
  3. score every source with the **same `score_matrix`** the backtest uses, so a
     live number and a backtest number are the same currency (spec §2.2 / §7);
  4. write one row per source to `scoreboard_daily`, idempotent per (run_id, D).

**Model vs comparators.** The `model` source is graded on the served point — the
honest out-of-sample product. The comparators (`oracle`, `persistence`,
`climatology`, `null`) are recomputed on D "for context": an SF map fit on the
trailing window ending at D, each baseline μ projected through it and scored
against the same realized C. This reuses `score.py`'s source constructors and
metric — never redefining a gate or re-measuring a baseline outside the shared
harness (spec §6). The `null` (flat) source is the integrity tripwire: a flat map
ranks nothing, so `score_matrix` returns NaN screening cells — a live `null` that
scores above chance means the metric path regressed.

**Same node set for every source.** All sources are scored on the intersection of
the map's nodes, the served forecast's nodes, and the nodes with realized C — so
the model's Yh and each baseline's Yh sit on the identical (hours × nodes) matrix
as realized Y, and the per-day `model − persistence` delta is apples-to-apples.

**No refit.** Grading reads the served panel; it does not re-run the model. The one
fit here is the cheap trailing-window SF solve for the baselines (the same
`implied_shift_factors` the backtest and the map use), nowhere near the mu fit's
peak — which is why the daily tick folds this in as a second step rather than
standing up a second job (`daily_forecast.main`).

**Deferred.** Miss-attribution (the scoreboard_miss decomposition) is out of 0003;
the live grade above is the shipped deliverable.
"""
from __future__ import annotations

import logging
from time import perf_counter

import numpy as np
import pandas as pd

from compute.mu.score import (
    STD_FLOOR,
    mu_climatology,
    mu_null,
    mu_persistence,
    score_matrix,
)
from compute.sf.config import MIN_HOURS, RIDGE_LAMBDA as LAM, WINDOW_DAYS
from compute.sf.eval import predict
from compute.sf.fit import implied_shift_factors
from compute.sf.panels import load_congestion_panel, load_shadow_prices
from compute.sf.project import band_metrics

log = logging.getLogger(__name__)

# The comparators recomputed on D alongside the served model (spec §6). `null` is
# the flat-map tripwire; `oracle` is the ceiling. Model is graded on the served
# point, so it is not built from an mu source here.
_BASELINES = ("oracle", "persistence", "climatology", "null")

# scoreboard_daily columns, in table order — the tuple `persist_grades` COPYs.
_COLS = (
    "run_id", "delivery_date", "source",
    "pooled_r2", "mae", "rank_spearman", "sign_agree", "topdecile_hit",
    "coverage80", "band_width", "pinball",
    "sf_coverage", "model_coverage", "n_hours", "n_nodes",
)

# The currency keys score_matrix emits, in table order.
_METRICS = ("pooled_r2", "mae", "rank_spearman", "sign_agree", "topdecile_hit")
_BANDS = ("coverage80", "band_width", "pinball")


def _as_utc_day(D) -> pd.Timestamp:
    """Normalize any date-ish `D` to a tz-aware UTC midnight — the day boundary the
    whole pipeline slices on (matches `daily_forecast._as_utc_day`)."""
    ts = pd.Timestamp(D)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts != ts.normalize():
        raise ValueError(f"delivery day must be a UTC midnight boundary, got {ts}")
    return ts.normalize()


def _v(x) -> float | None:
    """NaN / None → SQL NULL; everything else → float. A declined (flat) or missing
    cell must land as NULL, never as a number masquerading as a real score."""
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else x


def load_served_forecast(conn, run_id: str, D: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Read the served nodal panel for (run_id, delivery_date=D) back into wide
    (ts × settlement_point) frames for point / p10 / p50 / p90.

    Empty dict if nothing was served for that day+run — the caller fails loud, since
    there is no product to grade.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts, settlement_point, point, p10, p50, p90
            FROM forecast_nodal
            WHERE run_id = %s AND delivery_date = %s
            ORDER BY ts, settlement_point
            """,
            (run_id, D.date()),
        )
        rows = cur.fetchall()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["ts", "sp", "point", "p10", "p50", "p90"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    out: dict[str, pd.DataFrame] = {}
    for q in ("point", "p10", "p50", "p90"):
        w = df.pivot(index="ts", columns="sp", values=q).sort_index()
        w.columns.name = None
        out[q] = w
    return out


def grade_day(
    conn,
    D,
    *,
    run_id: str,
    window_days: int = WINDOW_DAYS,
    lam: float = LAM,
    min_hours: int = MIN_HOURS,
) -> list[dict]:
    """Grade the served forecast for UTC delivery day D; return one row per source.

    Reads only; the caller persists (`persist_grades`) and owns the transaction.
    Fails loud when there is nothing to grade — no served panel, no realized
    congestion, or a degenerate SF fit — rather than writing a hollow row.
    """
    D = _as_utc_day(D)
    started = perf_counter()
    log.info("grade_day start: delivery_date=%s run_id=%s", D.date(), run_id)

    # --- the served product (model source) ----------------------------------
    fc = load_served_forecast(conn, run_id, D)
    if not fc:
        raise RuntimeError(
            f"no served forecast_nodal rows for run_id={run_id} delivery_date="
            f"{D.date()} — nothing to grade (run daily_forecast for D first).")

    # --- realized congestion + shadow prices over the fit+score window ------
    # `end = D + 1 day` so the score block is D's 24 UTC hours; the fit window is
    # [D − window_days, D). M reaches back for the SF fit AND the persistence lag
    # (yesterday's μ), C for the fit and D's realized Y.
    lo = D - pd.Timedelta(days=window_days)
    hi = D + pd.Timedelta(days=1)
    M = load_shadow_prices(conn, lo, hi)
    C = load_congestion_panel(conn, lo, hi)
    if M.empty or C.empty:
        raise RuntimeError(
            f"no shadow-price / congestion panel over [{lo.date()}, {hi.date()}) "
            f"for {D.date()} — realized DAM has not published (fail, do not grade).")

    M_fit = M.loc[(M.index >= lo) & (M.index < D)]
    C_fit = C.loc[(C.index >= lo) & (C.index < D)]
    if M_fit.empty:
        raise RuntimeError(f"empty SF fit window for {D.date()} — no binding history")
    SF = implied_shift_factors(M_fit, C_fit, lam=lam, min_hours=min_hours,
                               standardize=True, std_floor=STD_FLOOR)
    if SF.empty:
        raise RuntimeError(f"degenerate SF fit for {D.date()} — no constraint kept")

    # D's score block, on the SAME grid the backtest uses: hours with both a
    # shadow-price row and realized congestion.
    M_score = M.loc[(M.index >= D) & (M.index < hi)]
    C_score = C.loc[(C.index >= D) & (C.index < hi)]
    hours = M_score.index.intersection(C_score.index)
    if not len(hours):
        raise RuntimeError(
            f"no realized hours for {D.date()} — DAM SPP / system_λ not both "
            f"present for D (fail, do not grade a partial day as complete).")
    M_score, C_score = M_score.loc[hours], C_score.loc[hours]
    cols = M_score.columns

    # Common node set: nodes the map located AND the forecast served AND that have
    # realized C — so every source is scored on the identical (hours × nodes)
    # matrix. Ordered by the SF columns for determinism.
    served_sps = set(fc["point"].columns)
    realized_sps = set(C_score.columns)
    N = [sp for sp in SF.columns if sp in served_sps and sp in realized_sps]
    if not N:
        raise RuntimeError(
            f"no nodes shared by the map, the served forecast, and realized C for "
            f"{D.date()} — cannot score (coverage collapse or wrong run_id).")
    if len(N) < len(SF.columns):
        log.info("grade_day %s: scoring %d/%d mapped nodes the served forecast "
                 "also covers", D.date(), len(N), len(SF.columns))

    # Realized Y on the common grid — the target for every source.
    Y = C_score.reindex(columns=N).to_numpy(float)

    # SF coverage: the scored day's |μ|-mass the map has a column for — a miss on a
    # blind-spot constraint must not be charged to the forecast, so it rides next to
    # the grade (spec §6 / handoff §5.4). model_coverage (mass on keys the model
    # predicted) needs the prediction-time key set, which is the deferred snapshot —
    # NULL here.
    mass_all = float(M_score.abs().to_numpy(float).sum())
    in_cols = cols.intersection(SF.index)
    sf_coverage = (float(M_score[in_cols].abs().to_numpy(float).sum()) / mass_all
                   if mass_all > 0 else np.nan)

    def _row(source: str, metrics: dict, bands: dict | None = None) -> dict:
        row = {"run_id": run_id, "delivery_date": D.date(), "source": source,
               **{k: metrics.get(k) for k in _METRICS},
               "coverage80": None, "band_width": None, "pinball": None,
               "sf_coverage": sf_coverage, "model_coverage": None,
               "n_hours": len(hours), "n_nodes": len(N)}
        if bands is not None:
            row.update({k: bands.get(k) for k in _BANDS})
        return row

    rows: list[dict] = []

    # --- model: the served deterministic point, plus live P50 bands ---------
    Yh_model = fc["point"].reindex(index=hours, columns=N).to_numpy(float)
    bm = band_metrics(
        Y,
        fc["p10"].reindex(index=hours, columns=N).to_numpy(float),
        fc["p50"].reindex(index=hours, columns=N).to_numpy(float),
        fc["p90"].reindex(index=hours, columns=N).to_numpy(float),
    )
    rows.append(_row("model", score_matrix(Y, Yh_model), bands=bm))

    # --- comparators: recomputed on D, projected through the trailing-window SF -
    srcs = {
        "oracle": M_score,                                    # realized μ (ceiling)
        "persistence": mu_persistence(M, hours, cols),        # same hour, prev day
        "climatology": mu_climatology(M_fit, hours, cols),    # P(bind)·E[μ|bind]
        "null": mu_null(hours, cols),                         # flat map (tripwire)
    }
    for name in _BASELINES:
        Yh = pd.DataFrame(predict(srcs[name], SF), index=hours, columns=SF.columns)
        Yh = Yh.reindex(columns=N).to_numpy(float)
        rows.append(_row(name, score_matrix(Y, Yh)))

    m = rows[0]
    p = next(r for r in rows if r["source"] == "persistence")
    log.info("grade_day complete: delivery_date=%s run_id=%s elapsed_s=%.3f | "
             "%d h × %d nodes | model top-dec %.3f (persistence %.3f, Δ%+.3f) "
             "| sf_coverage %.3f",
             D.date(), run_id, perf_counter() - started, len(hours), len(N),
             m["topdecile_hit"] if m["topdecile_hit"] is not None else float("nan"),
             p["topdecile_hit"] if p["topdecile_hit"] is not None else float("nan"),
             (m["topdecile_hit"] - p["topdecile_hit"])
             if m["topdecile_hit"] is not None and p["topdecile_hit"] is not None
             else float("nan"),
             sf_coverage)
    return rows


def persist_grades(conn, run_id: str, D, rows: list[dict]) -> int:
    """Delete-then-COPY the day's grades into scoreboard_daily. Idempotent per
    (run_id, delivery_date); does NOT commit — the caller owns the transaction.
    Returns rows written."""
    D = _as_utc_day(D)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM scoreboard_daily WHERE run_id = %s AND delivery_date = %s",
            (run_id, D.date()),
        )
        sql = f"COPY scoreboard_daily ({', '.join(_COLS)}) FROM STDIN"
        with cur.copy(sql) as cp:
            for r in rows:
                cp.write_row(tuple(
                    r[c] if c in ("run_id", "delivery_date", "source")
                    else (int(r[c]) if c in ("n_hours", "n_nodes") and r[c] is not None
                          else _v(r[c]))
                    for c in _COLS
                ))
    return len(rows)


def resolve_gradeable_date(conn, run_id: str) -> pd.Timestamp | None:
    """Return the newest forecast day that has not been graded and is complete.

    A UTC delivery day ends at 23:00, so this checks directly for the system-lambda
    price at that known hour. If it exists, the day is ready to grade; if not, the
    selector waits. It deliberately does not search the forecast table for each
    day's latest timestamp, which became slow as forecast history grew. Returning
    ``None`` simply means there is nothing ready to grade yet.
    """
    started = perf_counter()
    log.info("grade selection start: run_id=%s", run_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.delivery_date
            FROM (SELECT DISTINCT delivery_date FROM forecast_nodal
                  WHERE run_id = %(run_id)s) c
            WHERE NOT EXISTS (
                    SELECT 1 FROM scoreboard_daily sd
                    WHERE sd.run_id = %(run_id)s
                      AND sd.delivery_date = c.delivery_date)
              AND EXISTS (
                    SELECT 1 FROM dam_system_lambda l
                    WHERE l.interval_ts =
                        (c.delivery_date::timestamp AT TIME ZONE 'UTC')
                        + INTERVAL '23 hours')
            ORDER BY c.delivery_date DESC
            LIMIT 1
            """,
            {"run_id": run_id},
        )
        row = cur.fetchone()
    D = None if row is None else _as_utc_day(row[0])
    log.info("grade selection complete: run_id=%s delivery_date=%s elapsed_s=%.3f",
             run_id, D.date() if D is not None else None, perf_counter() - started)
    return D


# --------------------------------------------------------------------------
# CLI — explicit single-day grade / backfill (the daily tick calls the functions
# above directly; this is the hand-run path, same shape as daily_forecast).
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import psycopg

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--delivery-date", default="auto",
                   help="'auto' (the most recent fully-realized ungraded served "
                        "day) or 'YYYY-MM-DD'")
    p.add_argument("--run-id", required=True,
                   help="model version whose served forecast to grade (e.g. "
                        "mu-all-v1) — the same run_id daily_forecast published")
    p.add_argument("--to-db", action="store_true",
                   help="persist the grades; omit for a dry run (compute + report "
                        "only, nothing written)")
    p.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    p.add_argument("--lam", type=float, default=LAM)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    with psycopg.connect(dsn) as conn:
        if args.delivery_date == "auto":
            D = resolve_gradeable_date(conn, args.run_id)
            if D is None:
                log.info("nothing gradeable for run_id=%s (no ungraded fully-"
                         "realized served day)", args.run_id)
                return 0
        else:
            D = _as_utc_day(args.delivery_date)

        rows = grade_day(conn, D, run_id=args.run_id,
                         window_days=args.window_days, lam=args.lam)
        if args.to_db:
            n = persist_grades(conn, args.run_id, D, rows)
            conn.commit()
            log.info("scoreboard_daily <- %d rows for %s (run_id=%s)",
                     n, D.date(), args.run_id)
        else:
            log.info("dry run (--to-db not set): %d source rows for %s, nothing "
                     "written", len(rows), D.date())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
