"""One-shot loader: μ weekly point scores -> ``scoreboard_weekly``.

The loader reshapes the pre-computed point metrics from ``mu_score_weekly.csv``;
it does not re-measure forecasts or require a band artifact.
"""
from __future__ import annotations

import logging

import pandas as pd

from compute.jobs.backfill_nodal import scores_path_for

log = logging.getLogger("compute.jobs.load_scoreboard")

_SCORE_METRICS = ("rank_spearman", "sign_agree", "topdecile_hit")
_COVERAGE = ("sf_coverage", "model_coverage")
_COUNTS = ("n_hours", "n_nodes")
_NA_VALUES = ("", "NaN", "nan", "NA", "N/A", "#N/A")


def _read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False, na_values=_NA_VALUES)


def _week_ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True).dt.tz_localize(None).dt.normalize()


def build_rows(score_csv: str, *, run_id: str) -> list[tuple]:
    """Build one COPY row per source/week screening metric."""
    score = _read_csv(score_csv)
    score["week"] = _week_ts(score["week"])

    def _v(x):
        return None if pd.isna(x) else x

    def _i(x):
        return None if pd.isna(x) else int(x)

    return [
        (run_id, r["week"].date(), r["source"],
         *(_v(r[c]) for c in _SCORE_METRICS),
         *(_v(r[c]) for c in _COVERAGE), *(_i(r[c]) for c in _COUNTS))
        for _, r in score.iterrows()
    ]


def resolve_board_paths(run_id: str, score: str | None) -> str:
    return score or scores_path_for(run_id)


def load_scoreboard(score_csv: str, conn, *, run_id: str) -> int:
    """Delete-then-COPY the point-only board for ``run_id``; does not commit."""
    rows = build_rows(score_csv, run_id=run_id)
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
    p.add_argument("--score", default=None,
                   help="μ weekly point-score CSV (defaults under runs/<run-id>/mu)")
    args = p.parse_args(argv)
    args.score = resolve_board_paths(args.run_id, args.score)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    with psycopg.connect(dsn) as conn:
        n = load_scoreboard(args.score, conn, run_id=args.run_id)
        conn.commit()
    log.info("scoreboard_weekly <- %s rows (run_id=%s) from %s", n, args.run_id,
             args.score)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
