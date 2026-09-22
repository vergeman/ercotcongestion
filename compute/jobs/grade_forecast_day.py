"""The `grade_forecast_day` job — grade the SERVED forecast for one delivery day D.

The live half of the scoreboard. Where the backtest board
(compute.jobs.backfill_scoreboard -> scoreboard_weekly) transcribes a
pre-registered walk, this grades what `daily_forecast` actually *served*, one
day behind, once realized DAM prices publish:

  1. pull the served point forecast for D from `forecast_nodal` (the deterministic
     E[μ]·SF the model published at D−1 close);
  2. build realized nodal congestion for D: `SPP − system_λ`, the same quantity
     the map fits and the realized pane serves;
  3. score every source with the same screening metrics the backtest uses, so a
     live number and a backtest number are the same currency
  4. write one row per source to `scoreboard_daily`, idempotent per (run_id, D).

Model vs comparators: the `model` source is graded on the served point. The
comparators (`oracle`, `persistence`, `climatology`, `null`) are recomputed on
D "for context" through the exact SF artifact that accompanied the served
forecast, then scored against the same realized C (congestion panel).

Same node set for every source. All sources are scored on the intersection of
the map's nodes, the served forecast's nodes, and the nodes with realized C; so
the model's Yh and each baseline's Yh sit on the identical (hours x nodes)
matrix as realized Y.

No refit. Grading reads the served panel and its keyed SF artifact; it does not
re-run the model or fit a substitute map.

This job calculates scoreboard grades only; Brief grades are calculated by
`materialize_brief_grade.py`.

"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd

from compute.time import ERCOT_TZ, ct_day_bounds, normalize_ct_day
from compute.evaluation.mu import mu_climatology, mu_null, mu_persistence
from compute.metrics import screening_metrics
from compute.sf_map.config import WINDOW_DAYS
from compute.evaluation.sf import predict
from compute.evaluation.essp import score_final_essp
from compute.inputs.dam import load_congestion_panel, load_shadow_prices
from compute.projection.codecs import load_sf_mu

log = logging.getLogger(__name__)

# The comparators recomputed on D alongside the served model. `null` is the
# flat-map tripwire; `oracle` is the ceiling. Model is graded on the served
# point, so it is not built from an mu source here.
@dataclass(frozen=True)
class SourceDefinition:
    """Served Scoreboard-owned construction for one daily source."""

    id: str
    series_id: str
    label: str
    definition: str
    constructor: str


SOURCE_DEFINITIONS = (
    SourceDefinition("scoreboard_model_served_nodal", "model", "Model",
                         "Served deterministic nodal forecast.", "model"),
    SourceDefinition("scoreboard_persistence_prior_day_nodal", "persistence", "Persistence",
                         "Prior-day μ projected through the served forecast SF artifact.", "persistence"),
    SourceDefinition("scoreboard_climatology_trailing_window_nodal", "climatology", "Climatology",
                         "Trailing-window μ climatology projected through the served forecast SF artifact.", "climatology"),
    SourceDefinition("scoreboard_oracle_settled_mu_nodal", "oracle", "Oracle",
                         "Settled-day μ projected through the served forecast SF artifact.", "oracle"),
    SourceDefinition("scoreboard_null_flat_nodal", "null", "Null",
                         "Flat nodal congestion tripwire.", "null"),
)
SOURCE_BY_CONSTRUCTOR = {source.constructor: source for source in SOURCE_DEFINITIONS}
_BASELINES = ("oracle", "persistence", "climatology", "null")

# scoreboard_daily columns, in table order — the tuple `persist_grades` COPYs.
_COLS = (
    "run_id", "delivery_date", "source", "horizon",
    "rank_spearman", "sign_agree", "topdecile_hit",
    "sf_coverage", "model_coverage", "n_hours", "n_nodes",
    "essp_precision", "essp_recall",
)

# The screening keys emitted by the scoreboard helper, in table order.
_METRICS = ("rank_spearman", "sign_agree", "topdecile_hit")


def _as_ct_day(D) -> pd.Timestamp:
    """Normalize any date-ish `D` to the UTC instant marking CT midnight."""
    return normalize_ct_day(D)


def _v(x) -> float | None:
    """NaN / None → SQL NULL; everything else → float. A declined (flat) or
    missing cell must land as NULL, never as a number masquerading as a real
    score.

    """
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else x


def load_served_forecast(conn, run_id: str, D: pd.Timestamp,
                         horizon: int = 1) -> dict[str, pd.DataFrame]:
    """Read the served nodal panel for (run_id, delivery_date=D, horizon).

    Each horizon is its own scoreboard track, so grading reads only the
    horizon's own rows. Empty dict if nothing was served for that
    day+run+horizon — the caller fails loud, since there is no product to
    grade.

    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts, settlement_point, point
            FROM forecast_nodal
            WHERE run_id = %s AND delivery_date = %s AND horizon = %s
            ORDER BY ts, settlement_point
            """,
            (run_id, D.date(), horizon),
        )
        rows = cur.fetchall()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["ts", "sp", "point"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    point = df.pivot(index="ts", columns="sp", values="point").sort_index()
    point.columns.name = None
    return {"point": point}


def load_served_sf(conn, run_id: str, D: pd.Timestamp, horizon: int) -> pd.DataFrame:
    """Load and validate the exact SF matrix served alongside this forecast."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT sf_npz FROM forecast_sf_artifact "
            "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
            (run_id, D.date(), horizon),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"no served SF artifact for run_id={run_id} delivery_date={D.date()} "
            f"horizon={horizon} — cannot grade against a substitute map")
    blob = row["sf_npz"] if isinstance(row, dict) else row[0]
    try:
        SF = load_sf_mu(bytes(blob)).SF
    except Exception as exc:
        raise RuntimeError(
            f"invalid served SF artifact for run_id={run_id} delivery_date={D.date()} "
            f"horizon={horizon}") from exc
    if (SF.empty or not SF.index.is_unique or not SF.columns.is_unique
            or not np.isfinite(SF.to_numpy(dtype=float)).all()
            or any(not str(label) for label in SF.index)
            or any(not str(label) for label in SF.columns)):
        raise RuntimeError(
            f"invalid served SF artifact for run_id={run_id} delivery_date={D.date()} "
            f"horizon={horizon}")
    return SF


def score_served_essp(conn, D: pd.Timestamp,
                      SF: pd.DataFrame) -> dict[str, float | None]:
    """Validate the already-loaded served SF artifact against ESSP."""
    return score_final_essp(conn, D, SF)


def grade_day(
    conn,
    D,
    *,
    run_id: str,
    horizon: int = 1,
    window_days: int = WINDOW_DAYS,
) -> list[dict]:
    """Grade the served forecast for CT delivery day D; return one row per source.

    `horizon` selects the track to grade (1 = final/t+1, 2 = preview/t+2) —
    each horizon is graded against the same realized C on its own served rows,
    so preview and final are two independent scoreboard tracks per run_id.

    """
    D = _as_ct_day(D)
    started = perf_counter()
    log.info("grade_forecast_day start: delivery_date=%s run_id=%s horizon=%d",
             D.date(), run_id, horizon)

    # --- the served product (model source) ----------------------------------
    fc = load_served_forecast(conn, run_id, D, horizon)
    if not fc:
        raise RuntimeError(
            f"no served forecast_nodal rows for run_id={run_id} delivery_date="
            f"{D.date()} horizon={horizon} — nothing to grade (run daily_forecast "
            f"for D first).")

    # The artifact is a hard prerequisite. Load it before any potentially
    # expensive input reads so a missing/corrupt artifact cannot lead to writes.
    SF = load_served_sf(conn, run_id, D, horizon)

    # --- realized congestion + shadow prices over history + score day --------
    #
    # `hi` is D's next CT midnight, so the score block is D's CT calendar day
    # (23/24/25 hours across a DST transition), not necessarily a flat `D + 1
    # day`, which would land an hour off on a spring-forward/fall-back day.
    #
    # The history window [D − window_days, D) provides climatology and
    # persistence; only D's realized congestion is needed for scoring.
    #

    lo = D - pd.Timedelta(days=window_days)
    _, hi = ct_day_bounds(D)
    M = load_shadow_prices(conn, lo, hi)
    C = load_congestion_panel(conn, D, hi)
    if M.empty or C.empty:
        raise RuntimeError(
            f"no shadow-price / congestion panel over [{lo.date()}, {hi.date()}) "
            f"for {D.date()} — realized DAM has not published (fail, do not grade).")

    M_history = M.loc[(M.index >= lo) & (M.index < D)]

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

    # Common node set: nodes the served map located AND the forecast served AND that
    # have realized C, so every source is scored on the identical (hours ×
    # nodes) matrix. Ordered by the SF columns for determinism.
    served_sps = set(fc["point"].columns)
    realized_sps = set(C_score.columns)
    N = [sp for sp in SF.columns if sp in served_sps and sp in realized_sps]
    if not N:
        raise RuntimeError(
            f"no nodes shared by the map, the served forecast, and realized C for "
            f"{D.date()} — cannot score (coverage collapse or wrong run_id).")
    if len(N) < len(SF.columns):
        log.info("grade_forecast_day %s: scoring %d/%d mapped nodes the served forecast "
                 "also covers", D.date(), len(N), len(SF.columns))

    # Realized Y on the common grid — the target for every source.
    Y = C_score.reindex(columns=N).to_numpy(float)

    # SF coverage: the scored day's |μ|-mass represented by served SF rows.
    mass_all = float(M_score.abs().to_numpy(float).sum())
    in_cols = cols.intersection(SF.index)
    sf_coverage = (float(M_score[in_cols].abs().to_numpy(float).sum()) / mass_all
                   if mass_all > 0 else np.nan)

    def _row(source: str, metrics: dict) -> dict:
        row = {"run_id": run_id, "delivery_date": D.date(), "source": source,
               "horizon": horizon,
               **{k: metrics.get(k) for k in _METRICS},
               "sf_coverage": sf_coverage, "model_coverage": None,
               "n_hours": len(hours), "n_nodes": len(N),
               "essp_precision": None, "essp_recall": None}
        return row

    rows: list[dict] = []

    # --- model: the served deterministic point ------------------------------
    Yh_model = fc["point"].reindex(index=hours, columns=N).to_numpy(float)
    rows.append(_row(SOURCE_BY_CONSTRUCTOR["model"].id,
                     screening_metrics(Y, Yh_model)))
    rows[0].update(score_served_essp(conn, D, SF))

    # --- comparators: recomputed on D, projected through the served SF ------
    srcs = {
        "oracle": M_score,                                    # settled μ benchmark
        "persistence": mu_persistence(M, hours, cols),        # same hour, prev day
        "climatology": mu_climatology(M_history, hours, cols), # P(bind)·E[μ|bind]
        "null": mu_null(hours, cols),                         # flat map (tripwire)
    }

    for mu_name in _BASELINES:
        Yh = pd.DataFrame(predict(srcs[mu_name], SF), index=hours, columns=SF.columns)
        Yh = Yh.reindex(columns=N).to_numpy(float)

        # the metrics (spearman, sign_agree, top_decile) get calculated in
        # screening_metrics, since have Y, Yh.
        rows.append(_row(SOURCE_BY_CONSTRUCTOR[mu_name].id,
                         screening_metrics(Y, Yh)))

    m = rows[0]
    p = next(r for r in rows
             if r["source"] == SOURCE_BY_CONSTRUCTOR["persistence"].id)
    log.info("grade_forecast_day complete: delivery_date=%s run_id=%s elapsed_s=%.3f | "
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


def persist_grades(conn, run_id: str, D, rows: list[dict], horizon: int = 1) -> int:
    """Delete-then-COPY the day's grades into scoreboard_daily. Idempotent per
    (run_id, delivery_date, horizon) — each horizon is its own track, so
    re-grading one never clears the other; does NOT commit — the caller owns
    the transaction. Returns rows written.

    """
    D = _as_ct_day(D)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM scoreboard_daily WHERE run_id = %s AND delivery_date = %s "
            "AND horizon = %s",
            (run_id, D.date(), horizon),
        )
        sql = f"COPY scoreboard_daily ({', '.join(_COLS)}) FROM STDIN"
        with cur.copy(sql) as cp:
            for r in rows:
                cp.write_row(tuple(
                    r[c] if c in ("run_id", "delivery_date", "source")
                    else (int(r[c]) if c in ("n_hours", "n_nodes", "horizon")
                          and r[c] is not None
                          else _v(r[c]))
                    for c in _COLS
                ))
    return len(rows)


def resolve_gradeable_date(conn, run_id: str, horizon: int = 1) -> pd.Timestamp | None:
    """Return the newest forecast day that has not been graded and is complete.

    Scoped to `horizon`: a day counts as gradeable only when it has served rows
    AND no scoreboard row for THIS horizon, so the two tracks select
    independently. The final tick never skips a day just because the preview
    track already graded it.

    """
    started = perf_counter()
    log.info("grade selection start: run_id=%s horizon=%d", run_id, horizon)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.delivery_date
            FROM (SELECT DISTINCT delivery_date FROM forecast_nodal
                  WHERE run_id = %(run_id)s AND horizon = %(horizon)s) c
            WHERE NOT EXISTS (
                    SELECT 1 FROM scoreboard_daily sd
                    WHERE sd.run_id = %(run_id)s
                      AND sd.horizon = %(horizon)s
                      AND sd.delivery_date = c.delivery_date)
              AND EXISTS (
                    SELECT 1 FROM dam_system_lambda l
                    WHERE l.interval_ts =
                        ((c.delivery_date + 1)::timestamp AT TIME ZONE '{ERCOT_TZ}')
                        - INTERVAL '1 hour')
            ORDER BY c.delivery_date DESC
            LIMIT 1
            """,
            {"run_id": run_id, "horizon": horizon},
        )
        row = cur.fetchone()
    D = None if row is None else _as_ct_day(row[0])
    log.info("grade selection complete: run_id=%s horizon=%d delivery_date=%s "
             "elapsed_s=%.3f", run_id, horizon, D.date() if D is not None else None,
             perf_counter() - started)
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
    p.add_argument("--horizon", type=int, choices=(1, 2), default=1,
                   help="which track to grade: 1 = final/t+1 (default), 2 = "
                        "preview/t+2 (0123). Each horizon is an independent track.")
    p.add_argument("--to-db", action="store_true",
                   help="persist the grades; omit for a dry run (compute + report "
                        "only, nothing written)")
    p.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    with psycopg.connect(dsn) as conn:
        if args.delivery_date == "auto":
            D = resolve_gradeable_date(conn, args.run_id, args.horizon)
            if D is None:
                log.info("nothing gradeable for run_id=%s horizon=%d (no ungraded "
                         "fully-realized served day)", args.run_id, args.horizon)
                return 0
        else:
            D = _as_ct_day(args.delivery_date)

        rows = grade_day(conn, D, run_id=args.run_id, horizon=args.horizon,
                         window_days=args.window_days)
        if args.to_db:
            n = persist_grades(conn, args.run_id, D, rows, args.horizon)
            conn.commit()
            log.info("scoreboard_daily <- %d rows for %s (run_id=%s horizon=%d)",
                     n, D.date(), args.run_id, args.horizon)
        else:
            log.info("dry run (--to-db not set): %d source rows for %s, nothing "
                     "written", len(rows), D.date())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
