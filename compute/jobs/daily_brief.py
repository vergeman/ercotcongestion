"""Compute and persist the daily brief for a served forecast day.

The brief is a deterministic re-ranking of one ``forecast_sf_artifact`` into the
"what to look at" document the Analysis view serves (docs/daily_brief_engine.md).
This job runs right after ``daily_forecast`` publishes: it loads the day's SF+μ̂,
builds the brief (F1–F5a) via ``compute.analysis.assemble.build_brief``, and
upserts one JSONB row into ``analysis_brief`` keyed by
``(run_id, delivery_date, horizon)`` — the same idempotency scope as the
artifact, so a re-run replaces the day in place.

CLI (same shape as grade_day):
    docker compose run --rm compute python -m compute.jobs.daily_brief \\
        --run-id mu-all-v1 --delivery-date 2026-06-30 --to-db
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from time import perf_counter

import pandas as pd
from psycopg.rows import dict_row
from psycopg.types.json import Json

from compute.analysis.assemble import build_brief
from compute.analysis.metadata import load_sp_metadata
from compute.sf.panels import load_congestion_panel, load_shadow_prices
from compute.sf.project import load_sf_mu

log = logging.getLogger("daily_brief")


def _served_horizon(cur, run_id: str, D: date) -> int | None:
    """The horizon to serve for a day: the final (1) when present, else preview (2)."""
    cur.execute(
        "SELECT min(horizon) AS h FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s",
        (run_id, D),
    )
    row = cur.fetchone()
    return None if row is None or row["h"] is None else int(row["h"])


def _load_artifact(cur, run_id: str, D: date, horizon: int):
    """Decode the (run_id, delivery_date, horizon) SF+μ̂ blob, or None if absent."""
    cur.execute(
        "SELECT sf_npz FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
        (run_id, D, horizon),
    )
    row = cur.fetchone()
    return None if row is None else load_sf_mu(bytes(row["sf_npz"]))


def resolve_briefable_date(conn, run_id: str) -> date | None:
    """The most recent artifact day for ``run_id`` that has no brief yet."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT max(a.delivery_date) AS d
            FROM forecast_sf_artifact a
            LEFT JOIN analysis_brief b
              ON b.run_id = a.run_id AND b.delivery_date = a.delivery_date
            WHERE a.run_id = %s AND b.run_id IS NULL
            """,
            (run_id,),
        )
        row = cur.fetchone()
    return None if row is None or row["d"] is None else row["d"]


def _load_bands(cur, run_id: str, D: date, horizon: int) -> dict:
    """The served P10/P90 nodal congestion bands (hours × SP) for the band check."""
    cur.execute(
        "SELECT ts, settlement_point, p10, p90 FROM forecast_nodal "
        "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
        (run_id, D, horizon),
    )
    rows = cur.fetchall()
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return {q: df.pivot(index="ts", columns="settlement_point", values=q).sort_index()
            for q in ("p10", "p90")}


def _load_dam(conn, run_id: str, D: date, horizon: int) -> dict | None:
    """Realized DAM μ + SPP-congestion panels for D, with the forecast bands.

    Returns ``None`` when DAM has not published for the day (F6 stays off); the
    grading tick re-runs the job once it has, filling after-action idempotently.
    """
    start = datetime(D.year, D.month, D.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    M = load_shadow_prices(conn, start, end)          # (hours × constraint key)
    C = load_congestion_panel(conn, start, end)       # (hours × SP), SPP − λ
    if M.empty or C.empty:
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        bands = _load_bands(cur, run_id, D, horizon)
    return {"mu": M, "realized": C, "p10": bands.get("p10"), "p90": bands.get("p90")}


def compute_brief(conn, run_id: str, D: date, horizon: int | None = None) -> dict:
    """Load the day's artifact (+ realized DAM when present) and build its brief."""
    started = perf_counter()
    with conn.cursor(row_factory=dict_row) as cur:
        if horizon is None:
            horizon = _served_horizon(cur, run_id, D)
            if horizon is None:
                raise ValueError(
                    f"no forecast_sf_artifact for run_id={run_id} delivery_date={D}")
        artifact = _load_artifact(cur, run_id, D, horizon)
    if artifact is None:
        raise ValueError(
            f"no forecast_sf_artifact for run_id={run_id} delivery_date={D} "
            f"horizon={horizon}")

    dam = _load_dam(conn, run_id, D, horizon)
    SF, E_mu = artifact.SF, artifact.E_mu
    metadata = load_sp_metadata(SF.columns)
    brief = build_brief(
        SF, E_mu, metadata,
        run_id=run_id, delivery_date=D, horizon=horizon,
        artifact_date=D, mu_basis="forecast", dam=dam,
    )
    log.info("compute_brief: delivery_date=%s run_id=%s horizon=%d hours=%d "
             "constraints=%d sps=%d after_action=%s elapsed_s=%.2f",
             D, run_id, horizon, len(E_mu.index), SF.shape[0], SF.shape[1],
             dam is not None, perf_counter() - started)
    return brief


def persist_brief(conn, run_id: str, D: date, horizon: int, brief: dict) -> None:
    """Upsert the brief; a re-run for the day replaces the blob in place."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analysis_brief (run_id, delivery_date, horizon, brief, computed_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (run_id, delivery_date, horizon)
            DO UPDATE SET brief = EXCLUDED.brief, computed_at = now()
            """,
            (run_id, D, horizon, Json(brief)),
        )


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    from shared.settings import settings

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-id", required=True,
                   help="model version whose served artifact to summarize "
                        "(e.g. mu-all-v1) — the run_id daily_forecast published")
    p.add_argument("--delivery-date", default="auto",
                   help="'auto' (most recent artifact day without a brief) or "
                        "'YYYY-MM-DD'")
    p.add_argument("--horizon", type=int, choices=(1, 2), default=None,
                   help="artifact track to summarize; default coalesces (final "
                        "when present, else preview)")
    p.add_argument("--to-db", action="store_true",
                   help="persist the brief; omit for a dry run (compute only)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Default (tuple) row factory: the sf.panels loaders use conn.cursor() and
    # expect tuples; every dict read below asks for dict_row explicitly.
    with psycopg.connect(settings.pg_dsn) as conn:
        conn.autocommit = False
        if args.delivery_date == "auto":
            D = resolve_briefable_date(conn, args.run_id)
            if D is None:
                log.info("nothing to brief for run_id=%s (every artifact day has a "
                         "brief)", args.run_id)
                return 0
        else:
            D = date.fromisoformat(args.delivery_date)

        with conn.cursor(row_factory=dict_row) as cur:
            horizon = args.horizon or _served_horizon(cur, args.run_id, D)
        if horizon is None:
            log.info("no artifact for run_id=%s delivery_date=%s", args.run_id, D)
            return 0

        brief = compute_brief(conn, args.run_id, D, horizon)
        if args.to_db:
            persist_brief(conn, args.run_id, D, horizon, brief)
            conn.commit()
            log.info("analysis_brief <- (%s, %s, horizon=%d)", args.run_id, D, horizon)
        else:
            log.info("dry run (--to-db not set): built brief for %s, nothing written", D)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
