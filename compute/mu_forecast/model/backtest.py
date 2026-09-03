"""Historical μ model backtesting.

This is a developer-only historical experiment. Production scoreboard backfills
use ``compute.jobs.backfill_scoreboard`` and publish directly to Postgres.
"""
from __future__ import annotations

import gc
import logging
import os
import time

import numpy as np
import pandas as pd

from compute.mu_forecast.model.artifacts import combine_pred_chunks, load_preds, save_preds
from compute.mu_forecast.model.heads import bind_metrics, reliability
from compute.mu_forecast.model.runner import (
    BIND_MATRIX_FILE, DEFAULT_REFIT_DAYS, DEFAULT_TRAIN_DAYS, FEATURE_SETS,
    PANEL_FILE, PANEL_LEADIN_DAYS, _predict_fold, arms_for, feature_cols,
    persist_outputs, spill_panel_features,
)
from compute.mu_forecast.model.scheduling import refit_boundaries, score_chunks

log = logging.getLogger("compute.mu_forecast.model.backtest")

def walk_forward(panel: pd.DataFrame,
                 train_days: int = DEFAULT_TRAIN_DAYS,
                 refit_days: int = DEFAULT_REFIT_DAYS,
                 score_from: pd.Timestamp | None = None,
                 score_until: pd.Timestamp | None = None,
                 anchor: pd.Timestamp | None = None,
                 seed: int = 0,
                 arms: tuple[str, ...] = ("lag", "geo", "wx"),
                 spill_dir: str | None = None,
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fit both heads on each trailing window; predict the next `refit_days`.

    `arms` selects the ablation arm (plan/0088): the panel is the same object in
    every arm, and only the column mask changes.

    Returns `(predictions, weekly)`:

      predictions  one row per scored (hour, constraint), with `p_bind`,
                   `mu_gbm` and the realized `y_bind` / `y_mu`. This is
                   what commit 4's harness and commit 5's sampler consume.
      weekly       one row per scored week: head-1 calibration, so a bad week is
                   visible as a week rather than averaged away.
    """
    feat = feature_cols(panel, arms)
    cols = feat + ["key_bind_rate"]
    ts = panel.index.get_level_values("interval_ts")
    starts = refit_boundaries(panel, train_days, refit_days, score_from, anchor)
    if score_until is not None:
        starts = starts[starts < pd.Timestamp(score_until)]
    if not len(starts):
        return pd.DataFrame(), pd.DataFrame()

    # The panel is built hour by hour, so it arrives sorted by time — which lets a
    # fold be a contiguous `iloc` slice (a view) instead of `panel[(ts>=lo)&(ts<s)]`
    # (a fresh ~1 GB copy of 4.5M rows, twice per week, on top of the 2.5 GB panel).
    # Sortedness is what makes that legal, so check it rather than assume it.
    if not ts.is_monotonic_increasing:
        raise ValueError("panel must be sorted by interval_ts")

    log.info("walk_forward: train=%dd refit=%dd arms=%s — %d cols, %d weeks [%s → %s]",
             train_days, refit_days, ",".join(arms) or "base", len(cols),
             len(starts), starts[0].date(), starts[-1].date())

    preds, weeks = [], []
    t_walk = time.perf_counter()
    for i, s in enumerate(starts):
        t0 = time.perf_counter()
        lo = s - pd.Timedelta(days=train_days)
        hi = s + pd.Timedelta(days=refit_days)

        # STRICTLY before: the train slice ENDS at `s`, so the scored week never
        # touches the fit. `searchsorted(..., "left")` on `s` puts the first row of
        # the scored week at the boundary and excludes it from train — same
        # half-open window as the mask it replaces.
        # `ts.searchsorted`, not `np.searchsorted(np.asarray(ts), ...)`: pandas 3
        # renders a tz-aware index as an OBJECT array of Timestamps, which then
        # compares tz-aware against tz-naive datetime64 and raises. The index's own
        # searchsorted keeps both the timezone and the (microsecond) unit.
        a, b, c = ts.searchsorted([lo, s, hi], side="left")
        train, score = panel.iloc[a:b], panel.iloc[b:c]
        if train.empty or score.empty or train["y_bind"].sum() < 10:
            continue

        out = _predict_fold(train, score, arms, seed, spill_dir)
        # The realized targets stay here — `walk_forward` is the caller that holds
        # the labels; the fold routine produced predictions only.
        out["y_bind"] = score["y_bind"].to_numpy()
        out["y_mu"] = score["y_mu"].to_numpy()
        out["week"] = s
        preds.append(out)

        row = {"week": s, "n_train": len(train), "n_score": len(score),
               **bind_metrics(out["y_bind"].to_numpy(), out["p_bind"].to_numpy())}
        weeks.append(row)

        # Per week, not every 8th: a 46-week walk is the long pole in this branch
        # and "is it stuck or is it slow" should not need a guess. The running ETA
        # is what makes an early kill (a misphased grid, a bad panel) cheap.
        dt = time.perf_counter() - t0
        done, elapsed = i + 1, time.perf_counter() - t_walk
        log.info("  week %2d/%d %s  %.0fs  (train %s, score %s)  eta %.0fm",
                 done, len(starts), s.date(), dt, f"{len(train):,}", f"{len(score):,}",
                 (elapsed / done) * (len(starts) - done) / 60)

    # The walk is done reading the on-disk bind matrix; drop it so the PVC is not
    # left holding a stale ~3.4 GB file between runs.
    if spill_dir is not None:
        try:
            os.remove(os.path.join(spill_dir, BIND_MATRIX_FILE))
        except OSError:
            pass

    return (pd.concat(preds) if preds else pd.DataFrame(),
            pd.DataFrame(weeks))


# --------------------------------------------------------------------------
def _fmt_reliability(rel: pd.DataFrame) -> str:
    lines = ["  p_bin      n     said    happened     gap"]
    for b, r in rel.iterrows():
        bar = "#" * int(round(r["y_rate"] * 20))
        lines.append(f"  {b/10:.1f}-{(b+1)/10:.1f} {int(r['n']):7d} "
                     f"{r['p_mean']:7.3f} {r['y_rate']:11.3f} {r['gap']:+7.3f}  {bar}")
    return "\n".join(lines)


def walk_forward_chunked(build_panel_for_range, *, score_from: pd.Timestamp,
                         end: pd.Timestamp, train_days: int, refit_days: int,
                         chunk_weeks: int, arms: tuple[str, ...],
                         spill_dir: str | None, chunk_dir: str,
                         ) -> tuple[pd.DataFrame, list[str]]:
    """Build, score, and release bounded historical panel chunks.

    Each chunk reads the score window plus its full causal training margin; only
    that chunk's predictions are held in RAM, then saved as a standard NPZ piece.
    ``combine_pred_chunks`` subsequently produces the canonical single artifact.
    """
    windows = score_chunks(score_from, end, refit_days, chunk_weeks)
    os.makedirs(chunk_dir, exist_ok=True)
    weekly_parts: list[pd.DataFrame] = []
    paths: list[str] = []
    for i, (chunk_start, chunk_end) in enumerate(windows, start=1):
        read_start = chunk_start - pd.Timedelta(days=train_days + PANEL_LEADIN_DAYS)
        log.info("chunk %d/%d: scores %s → %s; reads from %s",
                 i, len(windows), chunk_start.date(),
                 (chunk_end - pd.Timedelta(days=refit_days)).date(), read_start.date())
        panel = build_panel_for_range(read_start, chunk_end)
        try:
            log.info("chunk %d/%d: panel = %s rows x %s cols", i, len(windows),
                     f"{len(panel):,}", panel.shape[1])
            if spill_dir and os.environ.get("MU_SPILL_PANEL"):
                panel = spill_panel_features(panel, spill_dir)
            preds, weekly = walk_forward(
                panel, train_days, refit_days, chunk_start, chunk_end,
                arms=arms, spill_dir=spill_dir,
            )
            path = os.path.join(chunk_dir, f"preds-{i:04d}.npz")
            save_preds(path, preds)
            paths.append(path)
            weekly_parts.append(weekly)
            log.info("chunk %d/%d: wrote %s prediction rows", i, len(windows),
                     f"{len(preds):,}")
            del preds
        finally:
            del panel
            if spill_dir:
                try:
                    os.remove(os.path.join(spill_dir, PANEL_FILE))
                except OSError:
                    pass
            gc.collect()
    return (pd.concat(weekly_parts, ignore_index=True) if weekly_parts
            else pd.DataFrame()), paths


def walk_forward_from_db(conn, *, start: pd.Timestamp, end: pd.Timestamp,
                         train_days: int = DEFAULT_TRAIN_DAYS,
                         refit_days: int = DEFAULT_REFIT_DAYS,
                         policy: str = "active_28d",
                         arms: tuple[str, ...] = ("lag", "geo", "wx"),
                         chunk_weeks: int = 32, spill_dir: str | None = None,
                         scratch_dir: str | None = None,
                         ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a historical walk from Postgres without publishing its predictions."""
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices
    from compute.mu_forecast.panel.build import build_panel

    score_from = pd.Timestamp(start, tz="America/Chicago")
    end = pd.Timestamp(end, tz="America/Chicago")

    def build_range(read_start, read_end):
        M = load_shadow_prices(conn, read_start, read_end)
        C = load_congestion_panel(conn, read_start, read_end) if "geo" in arms else None
        try:
            return build_panel(conn, M, read_start, read_end, policy=policy, C=C,
                               score_from=score_from, with_weather="wx" in arms)
        finally:
            del M, C

    if chunk_weeks:
        if scratch_dir is None:
            raise ValueError("chunked walk requires a job-owned scratch directory")
        weekly, paths = walk_forward_chunked(
            build_range, score_from=score_from, end=end, train_days=train_days,
            refit_days=refit_days, chunk_weeks=chunk_weeks, arms=arms,
            spill_dir=spill_dir, chunk_dir=os.path.join(scratch_dir, "mu-pred-chunks"))
        if not paths:
            return pd.DataFrame(), weekly
        combined = os.path.join(scratch_dir, "mu-preds.npz")
        combine_pred_chunks(paths, combined)
        return load_preds(combined), weekly

    read_start = score_from - pd.Timedelta(days=train_days + PANEL_LEADIN_DAYS)
    panel = build_range(read_start, end)
    try:
        if spill_dir and os.environ.get("MU_SPILL_PANEL"):
            panel = spill_panel_features(panel, spill_dir)
        return walk_forward(panel, train_days, refit_days, score_from,
                            arms=arms, spill_dir=spill_dir)
    finally:
        del panel
        if spill_dir:
            try:
                os.remove(os.path.join(spill_dir, PANEL_FILE))
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    from compute.mu_forecast.panel.build import build_panel
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", default=None,
                   help="series origin: the first scored week (SAME meaning as "
                        "weekly_map/eval --start). The data-read floor is derived "
                        "as start − train_days − leadin; do NOT pass a data floor.")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--score-from", default=None,
                   help="override the scored-grid phase; defaults to --start. Rarely "
                        "needed — only to pin a phase different from the origin.")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--policy", default="active_28d", choices=["active_28d", "all"])
    p.add_argument("--features", default="all", choices=sorted(FEATURE_SETS),
                   help="ablation arm (plan/0088): which covariate families the "
                        "model may see. The panel is built identically either way.")
    p.add_argument("--chunk-weeks", type=int, default=32,
                   help="build and score this many weekly folds at a time, writing "
                        "temporary prediction chunks to bound full-history memory; "
                        "0 opts into the legacy single-panel walk")
    p.add_argument("--out", default=None, help="write weekly metrics CSV here")
    p.add_argument("--preds-out", default=None,
                   help="write per-row predictions .npz here")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # --start is the SERIES ORIGIN (first scored week), the same meaning it carries
    # in weekly_map/eval. --score-from overrides only the grid phase, defaulting to
    # the origin — so a single date drives all three stages.
    origin = args.score_from or args.start
    if origin is None:
        p.error("pass --start (the series origin / first scored week)")
    # CT, matching `lo`/`hi` below and `predict_day`'s CT anchor (0133) — `origin`
    # is a bare `YYYY-MM-DD` naming a CT calendar date, and `tz="UTC"` here used to
    # read the SAME string as a different instant (UTC midnight, not CT midnight)
    # than the read-floor did, desyncing the refit grid's phase from the CT day
    # boundary `predict_day`/`forecast_day` now score on.
    score_from_ts = pd.Timestamp(origin, tz="America/Chicago")
    if args.chunk_weeks < 0:
        p.error("--chunk-weeks must be non-negative")
    if args.chunk_weeks and not args.preds_out:
        p.error("--chunk-weeks requires --run-id or --preds-out for the final artifact")

    # Derive the data-read floor from the origin: the walk needs train_days of history
    # behind the first scored week, plus PANEL_LEADIN_DAYS of slack for the panel's
    # front-edge day-loss. This never shifts the scored grid (pinned by score_from);
    # it only guarantees the first fold gets its full trailing window.
    lo = (pd.Timestamp(origin, tz="America/Chicago")
          - pd.Timedelta(days=args.train_days + PANEL_LEADIN_DAYS))
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    arms = arms_for(args.features)

    # Resolve the disk spill directory once — both spills share it: the disk-backed
    # --preds-out PVC by default, MU_SPILL_DIR overrides.
    spill_dir = os.environ.get("MU_SPILL_DIR")
    if spill_dir is None and args.preds_out:
        spill_dir = os.path.join(
            os.path.dirname(os.path.abspath(args.preds_out)) or ".", "spill")

    if spill_dir:
        log.info("bind matrix spills to disk at %s", spill_dir)

    if args.chunk_weeks:
        chunk_dir = os.path.join(
            spill_dir or os.path.dirname(os.path.abspath(args.preds_out)),
            "mu-pred-chunks",
        )
        with psycopg.connect(dsn) as conn:
            def build_chunk(read_start, chunk_end):
                log.info("loading chunk inputs %s → %s", read_start.date(),
                         chunk_end.date())
                M = load_shadow_prices(conn, read_start, chunk_end)
                C = None
                if "geo" in arms:
                    C = load_congestion_panel(conn, read_start, chunk_end)
                    log.info("chunk C = %s", C.shape)
                panel = build_panel(conn, M, read_start, chunk_end,
                                    policy=args.policy, C=C,
                                    score_from=score_from_ts,
                                    with_weather="wx" in arms)
                del M, C
                return panel

            weekly, chunk_paths = walk_forward_chunked(
                build_chunk, score_from=score_from_ts, end=hi,
                train_days=args.train_days, refit_days=args.refit_days,
                chunk_weeks=args.chunk_weeks, arms=arms, spill_dir=spill_dir,
                chunk_dir=chunk_dir,
            )
        n_pred_rows = combine_pred_chunks(chunk_paths, args.preds_out)
        for path in chunk_paths:
            os.remove(path)
        try:
            os.rmdir(chunk_dir)
        except OSError:
            pass
        preds = None
        log.info("combined %d prediction chunks into %s (%s rows)",
                 len(chunk_paths), args.preds_out, f"{n_pred_rows:,}")
    else:
        with psycopg.connect(dsn) as conn:
            log.info("loading shadow prices %s → %s", lo.date(), hi.date())
            M = load_shadow_prices(conn, lo, hi)
            # The congestion panel is loaded only for the geography arm — it is what
            # `SF` is fitted against. Skipping it when no arm needs it keeps the base
            # run identical to 0085's and saves a large read.
            C = None
            if "geo" in arms:
                C = load_congestion_panel(conn, lo, hi)
                log.info("C = %s (geography arm is on)", C.shape)
            log.info("M = %s; building covariate panel (policy=%s)", M.shape, args.policy)
            panel = build_panel(conn, M, lo, hi, policy=args.policy, C=C,
                                score_from=score_from_ts,
                                with_weather="wx" in arms)
            anchor = M.index[0].normalize()
            del M, C

        log.info("panel = %s rows x %s cols, %.2f GB — arm %r sees %d features",
                 f"{len(panel):,}", panel.shape[1],
                 panel.memory_usage(deep=False).sum() / 1e9, args.features,
                 len(feature_cols(panel, arms)) + 1)
        if spill_dir and os.environ.get("MU_SPILL_PANEL"):
            panel = spill_panel_features(panel, spill_dir)

        # Anchor on the SHADOW-PRICE panel's first day so the scored weeks coincide
        # with sf/eval's — see refit_boundaries.
        preds, weekly = walk_forward(panel, args.train_days, args.refit_days,
                                     score_from_ts, anchor=anchor,
                                     arms=arms, spill_dir=spill_dir)
        del panel
        if spill_dir:
            try:
                os.remove(os.path.join(spill_dir, PANEL_FILE))
            except OSError:
                pass

    if weekly.empty:
        print("no scorable weeks")
        return 1

    print(f"\n=== HEAD 1: P(bind) — calibration first === [arm: {args.features}]")
    if preds is None:
        print(f"  weeks {len(weekly)}   rows {n_pred_rows:,}   "
              "(chunked; pooled calibration is in the prediction artifact)")
        print(f"  weekly mean Brier {weekly['brier'].mean():.5f}   "
              f"ECE {weekly['ece'].mean():.4f}   AUC {weekly['auc'].mean():.4f}")
    else:
        y = preds["y_bind"].to_numpy()
        pr = preds["p_bind"].to_numpy()
        pooled = bind_metrics(y, pr)
        print(f"  weeks {len(weekly)}   rows {len(preds):,}   "
              f"base rate {pooled['base_rate']:.4f}   mean pred {pooled['mean_pred']:.4f}")
        print(f"  Brier {pooled['brier']:.5f}   ECE {pooled['ece']:.4f}   "
              f"AUC {pooled['auc']:.4f}")
        print("\n  reliability curve (said vs happened):")
        print(_fmt_reliability(reliability(y, pr)))

    persist_outputs(weekly, preds if preds is not None else pd.DataFrame(),
                    args.out, None if preds is None else args.preds_out)
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
