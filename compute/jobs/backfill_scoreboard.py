"""Backfill walk-forward μ scoreboard rows directly into ``scoreboard_weekly``."""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass

import pandas as pd

from compute.evaluation.mu import evaluate_predictions
from compute.mu_forecast.model.walk_forward import walk_forward_from_db
from compute.mu_forecast.model.runner import DEFAULT_REFIT_DAYS, DEFAULT_TRAIN_DAYS, FEATURE_SETS, arms_for
from compute.time import localize_ct

log = logging.getLogger("compute.jobs.backfill_scoreboard")

_SCORE_METRICS = ("rank_spearman", "sign_agree", "topdecile_hit")
_COVERAGE = ("sf_coverage", "model_coverage")
_COUNTS = ("n_hours", "n_nodes")
_NA_VALUES = ("", "NaN", "nan", "NA", "N/A", "#N/A")


@dataclass(frozen=True)
class SourceDefinition:
    """Weekly Scoreboard-owned identity for one admitted compute source."""

    id: str
    series_id: str
    label: str
    definition: str
    compute_id: str


SOURCE_DEFINITIONS = (
    SourceDefinition("scoreboard_model_backtest_nodal", "model", "Model",
                         "Walk-forward model projected to nodal congestion.",
                         "compute_mu_model_walk_forward"),
    SourceDefinition("scoreboard_persistence_backtest_nodal", "persistence", "Persistence",
                         "Prior-day μ baseline projected by each backtest map.",
                         "compute_mu_persistence_prior_day"),
    SourceDefinition("scoreboard_climatology_backtest_nodal", "climatology", "Climatology",
                         "Hourly μ climatology projected by each backtest map.",
                         "compute_mu_climatology_hourly"),
    SourceDefinition("scoreboard_oracle_backtest_nodal", "oracle", "Oracle",
                         "Realized μ projected by the held-out backtest map.",
                         "compute_mu_oracle_realized"),
    SourceDefinition("scoreboard_null_flat_nodal", "null", "Null",
                         "Flat nodal congestion tripwire.", "compute_mu_null_zero"),
)
SOURCE_BY_COMPUTE_ID = {source.compute_id: source for source in SOURCE_DEFINITIONS}


def _week_ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True).dt.tz_localize(None).dt.normalize()


def build_rows(score: pd.DataFrame, *, run_id: str) -> list[tuple]:
    """Build one COPY row per source/week screening metric."""
    score = score.copy()
    score["week"] = _week_ts(score["week"])

    def _v(x):
        return None if pd.isna(x) else x

    def _i(x):
        return None if pd.isna(x) else int(x)

    unknown = set(score["source"]) - set(SOURCE_BY_COMPUTE_ID)
    if unknown:
        raise ValueError(f"unadmitted compute source IDs: {sorted(unknown)}")

    return [
        (run_id, r["week"].date(), SOURCE_BY_COMPUTE_ID[r["source"]].id,
         *(_v(r[c]) for c in _SCORE_METRICS),
         *(_v(r[c]) for c in _COVERAGE), *(_i(r[c]) for c in _COUNTS))
        for _, r in score.iterrows()
    ]


def load_scoreboard(score: pd.DataFrame, conn, *, run_id: str) -> int:
    """Delete-then-COPY the point-only board for ``run_id``; does not commit."""
    rows = build_rows(score, run_id=run_id)
    cols = ("run_id", "week", "source", *_SCORE_METRICS,
            *_COVERAGE, *_COUNTS)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM scoreboard_weekly WHERE run_id = %s", (run_id,))
        with cur.copy(f"COPY scoreboard_weekly ({', '.join(cols)}) FROM STDIN") as cp:
            for row in rows:
                cp.write_row(row)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import psycopg

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-id", required=True)
    p.add_argument("--start", required=True, help="first CT scored date")
    p.add_argument("--end", required=True, help="exclusive CT score bound")
    p.add_argument("--score-from", default=None, help="override the scored-grid phase")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--policy", default="active_28d", choices=["active_28d", "all"])
    p.add_argument("--features", default="all", choices=sorted(FEATURE_SETS))
    p.add_argument("--chunk-weeks", type=int, default=32)
    args = p.parse_args(argv)
    if args.chunk_weeks < 0:
        p.error("--chunk-weeks must be non-negative")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    start = args.score_from or args.start
    spill_parent = os.environ.get("MU_SPILL_DIR")
    with tempfile.TemporaryDirectory(prefix="scoreboard-", dir=spill_parent) as spill_dir:
        with psycopg.connect(dsn) as conn:
            preds, _ = walk_forward_from_db(
                conn, start=start, end=args.end, train_days=args.train_days,
                refit_days=args.refit_days, policy=args.policy, arms=arms_for(args.features),
                chunk_weeks=args.chunk_weeks, spill_dir=spill_dir, scratch_dir=spill_dir)
            score = evaluate_predictions(conn, preds, end=localize_ct(args.end))
            if score.empty:
                log.warning("no scorable weeks; scoreboard unchanged")
                return 1
            n = load_scoreboard(score, conn, run_id=args.run_id)
            conn.commit()
    log.info("scoreboard_weekly <- %s rows (run_id=%s)", n, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
