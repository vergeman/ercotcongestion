"""One-shot loader: mu weekly CSVs -> scoreboard_weekly (the backtest board).

spec-phase3-scoreboard.md §0 / §2.1 / §8 step 2. Reshape-and-serve, NOT new
measurement: the pre-registered currencies already live per (week x source x
regime) in mu_score_weekly.csv, and the P50 band metrics per week (model source
only) in mu_bands_weekly.csv. This joins the two and COPYs them into
scoreboard_weekly under one run_id so the API serves indexed rows, not files. The
numbers are transcribed as-is — the loader never redefines a gate or re-measures a
baseline (§6).

run_id names the model version that produced the board (same semantics as
forecast_nodal's run_id): a config change starts a fresh, non-spliced track. The
load is idempotent by delete-then-copy scoped to run_id, so a re-run replaces that
run's board cleanly and leaves other runs untouched. It is also the canonical
artifact namespace (plan/0113): `--score` / `--bands` default to that run's CSVs
under `runs/<run-id>/` and need not be spelled out.

    docker compose run --rm compute python -m compute.jobs.load_scoreboard \
        --run-id mu-all-v1
"""
from __future__ import annotations

import logging

import pandas as pd

from compute.jobs.backfill_nodal import bands_path_for, scores_path_for

log = logging.getLogger("compute.jobs.load_scoreboard")

# Metric columns carried straight from mu_score_weekly.csv, in table order.
_SCORE_METRICS = (
    "pooled_r2", "mae", "rank_spearman", "sign_agree", "topdecile_hit",
)
# P50 band metrics from mu_bands_weekly.csv — attached only to the rows they were
# measured on (source='model', regime='all'); NULL everywhere else.
_BAND_METRICS = ("coverage80", "band_width", "pinball")
_COVERAGE = ("sf_coverage", "model_coverage")
_COUNTS = ("n_hours", "n_nodes")

# The (source, regime) the bands CSV describes: it has no source/regime columns —
# it is the model's P50 band, pooled over `all`.
_BANDS_SOURCE = "model"
_BANDS_REGIME = "all"

# The bands CSV can be emitted by a run whose week anchor sits a day off the score
# CSV's (they need not come from the same run). Attach band metrics to the model/all
# rows by nearest week within this tolerance — exact (0-day) when the two are
# regenerated together, forgiving of the drift otherwise. A week beyond tolerance
# gets no band metrics (NULL), never a wrong week's.
_BANDS_JOIN_TOL = pd.Timedelta("3D")

# pandas' default NA set swallows the literal string "null" — which is the name of
# the flat-prediction baseline source (the null-guard comparator, spec §6). Turn
# the defaults off and NA only true blanks, so `null` survives as a source string
# while an empty numeric cell still becomes NaN -> SQL NULL.
_NA_VALUES = ("", "NaN", "nan", "NA", "N/A", "#N/A")


def _read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=False, na_values=_NA_VALUES)


def _week_ts(s: pd.Series) -> pd.Series:
    """`2025-08-14 00:00:00+00:00` -> a tz-naive midnight Timestamp (the week key)."""
    return pd.to_datetime(s, utc=True).dt.tz_localize(None).dt.normalize()


def _band_by_week(score: pd.DataFrame, bands: pd.DataFrame) -> dict:
    """Nearest-week map: model/all week (Timestamp) -> (coverage80, band_width,
    pinball). Uses merge_asof(direction='nearest') within `_BANDS_JOIN_TOL` so a
    day of anchor drift between the two CSVs still lands the bands on the right
    week; a NaN metric (no bands week in tolerance) rides through and becomes NULL.
    """
    model_all = (
        score[(score["source"] == _BANDS_SOURCE) & (score["regime"] == _BANDS_REGIME)]
        [["week"]].sort_values("week")
    )
    merged = pd.merge_asof(
        model_all,
        bands[["week", *_BAND_METRICS]].sort_values("week"),
        on="week", direction="nearest", tolerance=_BANDS_JOIN_TOL,
    )
    matched = int(merged[list(_BAND_METRICS)].notna().any(axis=1).sum())
    log.info("bands joined to %d/%d model/all weeks (nearest within %s)",
             matched, len(model_all), _BANDS_JOIN_TOL)
    return {
        r.week: (r.coverage80, r.band_width, r.pinball)
        for r in merged.itertuples(index=False)
    }


def build_rows(score_csv: str, bands_csv: str, *, run_id: str) -> list[tuple]:
    """Join the two weekly CSVs into scoreboard_weekly rows for `run_id`.

    Every score row rides through as-is (all sources, all regimes); the band
    metrics are looked up by week and attached only to the (model, all) rows they
    belong to. NaN cells become None so a missing metric lands as SQL NULL rather
    than dropping the row.
    """
    score = _read_csv(score_csv)
    score["week"] = _week_ts(score["week"])

    bands = _read_csv(bands_csv)
    bands["week"] = _week_ts(bands["week"])

    band_by_week = _band_by_week(score, bands)

    def _v(x):  # NaN -> NULL, keep everything else as-is
        return None if pd.isna(x) else x

    def _i(x):  # nullable int for the count columns
        return None if pd.isna(x) else int(x)

    rows: list[tuple] = []
    for _, r in score.iterrows():
        week = r["week"]
        is_bands_row = r["source"] == _BANDS_SOURCE and r["regime"] == _BANDS_REGIME
        band_vals = band_by_week.get(week) if is_bands_row else None
        cov80, bwidth, pinball = band_vals if band_vals is not None else (None, None, None)
        rows.append((
            run_id, week.date(), r["source"], r["regime"],
            *(_v(r[c]) for c in _SCORE_METRICS),
            _v(cov80), _v(bwidth), _v(pinball),
            *(_v(r[c]) for c in _COVERAGE),
            *(_i(r[c]) for c in _COUNTS),
        ))
    return rows


def resolve_board_paths(run_id: str, score: str | None, bands: str | None,
                        ) -> tuple[str, str]:
    """Default the score/bands CSVs to `run_id`'s canonical `runs/<run-id>/` paths.

    The score CSV is a μ-stage artifact (`mu/mu_score_weekly.csv`, the score schema
    `compute.mu.score` writes — NOT `mu_weekly.csv`, which is `mu_model`'s
    calibration output); the bands CSV is the forecast-stage output
    (`forecast/mu_bands_weekly.csv`, `backfill_nodal --out`). Explicit `--score` /
    `--bands` always win.
    """
    return (score or scores_path_for(run_id), bands or bands_path_for(run_id))


def load_scoreboard(score_csv: str, bands_csv: str, conn, *, run_id: str) -> int:
    """Delete-then-COPY the board for `run_id`. Does NOT commit — caller owns the
    transaction. Returns the number of rows written."""
    rows = build_rows(score_csv, bands_csv, run_id=run_id)
    cols = (
        "run_id", "week", "source", "regime",
        *_SCORE_METRICS, *_BAND_METRICS, *_COVERAGE, *_COUNTS,
    )
    with conn.cursor() as cur:
        cur.execute("DELETE FROM scoreboard_weekly WHERE run_id = %s", (run_id,))
        sql = f"COPY scoreboard_weekly ({', '.join(cols)}) FROM STDIN"
        with cur.copy(sql) as cp:
            for row in rows:
                cp.write_row(row)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    import psycopg

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--run-id", required=True,
                   help="model-version tag for this board (e.g. mu-all-v1); the "
                        "idempotency scope AND the artifact namespace — --score / "
                        "--bands default to this run's CSVs under runs/<run-id>/")
    p.add_argument("--score", default=None,
                   help="μ weekly score CSV; defaults to "
                        "runs/<run-id>/mu/mu_score_weekly.csv")
    p.add_argument("--bands", default=None,
                   help="P50 band-metrics CSV; defaults to "
                        "runs/<run-id>/forecast/mu_bands_weekly.csv")
    args = p.parse_args(argv)

    args.score, args.bands = resolve_board_paths(
        args.run_id, args.score, args.bands)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    with psycopg.connect(dsn) as conn:
        n = load_scoreboard(args.score, args.bands, conn, run_id=args.run_id)
        conn.commit()
    log.info("scoreboard_weekly <- %s rows (run_id=%s) from %s + %s",
             n, args.run_id, args.score, args.bands)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
