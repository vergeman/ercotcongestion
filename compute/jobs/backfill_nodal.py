"""Backtest walk → nodal panel seed, and the R5 verdict, against the bar as written.

The one-time historical backfill runner (README §A): walk the validated
predictions forward through the SF map, stream the per-week nodal P10/P50/P90 +
point panel to a flat npz, and — with `--to-db` / `--load-nodal-npz` — bulk-seed
`forecast_nodal` and flip `forecast_current[ercot]`, plus the pre-registered R5
gate. Shared DB writers live in `compute.forecast_store`; they remain imported here
as temporary compatibility re-exports. The projection math it drives lives in
`compute.sf.project`.

    docker compose run --rm compute python -m compute.jobs.backfill_nodal \
      --preds /compute/mu/mu_preds.npz --out /compute/mu/mu_bands_weekly.csv

"""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import pandas as pd

from compute.artifacts import DEFAULT_RUNS_ROOT, RunArtifacts
# Compatibility re-exports while external callers migrate to compute.forecast_store.
from compute.forecast_store import (
    FORECAST_LAYER,
    nodal_to_db,
    persist_sf_mu_artifact,
    sf_artifact_to_db,
    upsert_pointer,
)
from compute.mu.score import REFIT_DAYS, RTC_B, weeks_from_preds
from compute.time import delivery_date_of
from compute.sf.project import (
    DRIVERS_K,
    DRIVERS_MAX_DAYS,
    MAP_RUN_ID,
    N_DRAWS,
    SfMuArtifact,
    _NodalAccumulator,
    load_window_sf,
    materialize_drivers,
    parse_curated_days,
    propagate_window,
    residual_pool,
    resolve_sf_window,
)

log = logging.getLogger("compute.jobs.backfill_nodal")

# Retained for tests that redirect the mounted runs PVC.
RUNS_ROOT = DEFAULT_RUNS_ROOT


def preds_path_for(run_id: str) -> str:
    """The μ predictions/residual-pool npz for `run_id` on the runs PVC.

    Same layout every stage uses — `runs/<run_id>/mu/mu_preds.npz`, where
    `mu_model --preds-out` writes it (runbook step 2) — so passing `--run-id`
    is enough and `--preds` need not be spelled out. The shared artifact catalog
    also supplies the matching `daily_forecast` and `mu_model` locations.
    """
    return str(RunArtifacts(run_id, RUNS_ROOT).predictions)


def scores_path_for(run_id: str) -> str:
    """The μ weekly score CSV for `run_id` — `runs/<run_id>/mu/mu_score_weekly.csv`.

    The per-(week × source × regime) currencies `compute.mu.score` writes and `r5`
    reads. A μ-stage artifact (score schema: source/regime/pooled_r2/…), so it lives
    under `mu/` beside the residual pool — a different file from `mu_weekly.csv`,
    which is `mu_model`'s calibration output."""
    return str(RunArtifacts(run_id, RUNS_ROOT).scores)


def bands_path_for(run_id: str) -> str:
    """The P50 band-metrics CSV for `run_id` — `runs/<run_id>/forecast/mu_bands_weekly.csv`.
    A forecast-stage output (this job produces it), so it lives under `forecast/`."""
    return str(RunArtifacts(run_id, RUNS_ROOT).bands)


def nodal_path_for(run_id: str) -> str:
    """The per-week nodal P10/P50/P90 + point panel npz for `run_id` —
    `runs/<run_id>/forecast/mu_nodal.npz`. The forecast-stage seed/reload artifact."""
    return str(RunArtifacts(run_id, RUNS_ROOT).nodal_panel)


def resolve_walk_paths(run_id: str | None, preds: str | None, scores: str | None,
                       out: str | None, nodal_out: str | None,
                       *, load_nodal_npz: bool = False,
                       ) -> tuple[str | None, str | None, str | None, str | None]:
    """Resolve the walk's inputs/outputs from `--run-id` (canonical `runs/<id>/`
    tree), falling back to the legacy bundled `compute/mu` paths run-id-less.

    Explicit values always win. Inputs (`preds`, `scores`) always resolve to *a*
    path so the run-id-less metrics mode keeps reading the legacy bundle; the
    derived OUTPUT paths (`out`, `nodal_out`) are filled only under a run id, so a
    run-id-less run keeps them opt-in (None) — its current behavior, unchanged.
    `--load-nodal-npz` is a standalone seed mode that runs no walk and derives
    nothing here (its own guard refuses the walk flags)."""
    if load_nodal_npz:
        return preds, scores, out, nodal_out
    legacy = RUNS_ROOT.parent / "mu"
    preds = preds or (preds_path_for(run_id) if run_id
                      else str(legacy / "mu_preds.npz"))
    scores = scores or (scores_path_for(run_id) if run_id
                        else str(legacy / "mu_score_weekly.csv"))
    if run_id:
        out = out or bands_path_for(run_id)
        nodal_out = nodal_out or nodal_path_for(run_id)
    return preds, scores, out, nodal_out


def walk(M: pd.DataFrame, C: pd.DataFrame, preds: pd.DataFrame,
         n_draws: int = N_DRAWS, seed: int = 0,
         nodal_out: str | None = None,
         curated: dict | None = None,
         sf_loader=None) -> pd.DataFrame:
    """Walk the scored weeks forward through the SF map.

    ``sf_loader`` (0095-0002) routes the backfill through the same persisted weekly
    SF the live forecast reads, so a historic day matches live: a callable
    ``week → SF | None`` (the causal ``max(window_end ≤ week)`` map window). A week
    with no causal window is skipped. ``sf_loader=None`` keeps the self-contained
    path — SF is refit per window inside `propagate_window` (the synthetic tests and
    the ``--fit-sf`` escape hatch)."""
    if isinstance(preds.index, pd.MultiIndex):
        preds = preds.reset_index()
    weeks = weeks_from_preds(preds)
    rng = np.random.default_rng(seed)
    log.info("propagating %d weeks × %d draws (week 1 has no residual pool → no "
             "bands); SF %s", len(weeks), n_draws,
             "from persisted map" if sf_loader is not None else "refit per window")

    # Emitting the panel only tees the arrays already computed — same rng draws,
    # so the metrics row (and `mu_bands_weekly.csv`) is byte-identical either way.
    sink = _NodalAccumulator() if nodal_out else None
    # `curated` is {delivery_date: None} for the --drivers days; the walk fills the
    # ones whose operating day falls inside a scored window with that day's SF+μ
    # artifact (§4a). None ⟹ no artifact requested (the common path, no extra work).
    want_sf_mu = bool(curated)
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

        sf = None
        if sf_loader is not None:
            sf = sf_loader(s)
            if sf is None or sf.empty:
                log.info("  week %2d/%d %s  no causal persisted SF window — skipped",
                         i + 1, len(weeks), s.date())
                continue

        end = s + pd.Timedelta(days=REFIT_DAYS)
        row, panel, SF, E_mu = propagate_window(
            s, end, M, C, by_week[s], eps, n_draws, rng, sf=sf,
            want_panel=sink is not None, want_sf_mu=want_sf_mu)
        if row is None:
            continue

        rows.append(row)
        if sink is not None:
            assert panel is not None      # want_panel=True ⟹ panel built when row is
            sink.add(panel, s)
        if want_sf_mu and E_mu is not None:
            # Slice the week's E_mu to each requested operating day and pair it with
            # this window's SF — the per-day artifact forecast_day would emit.
            dd = delivery_date_of(pd.Series(E_mu.index, index=E_mu.index))
            for day in list(curated):
                mask = (dd == day).to_numpy()
                if mask.any():
                    curated[day] = SfMuArtifact(SF=SF, E_mu=E_mu.loc[mask])
        done, el = i + 1, time.perf_counter() - t0
        log.info("  week %2d/%d %s  cov80 %.3f  P50 R2 %+.3f  eta %.0fm",
                 done, len(weeks), s.date(), rows[-1]["coverage80"],
                 rows[-1]["pooled_r2"], (el / done) * (len(weeks) - done) / 60)
    if sink is not None and nodal_out is not None:
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

    import psycopg

    from compute.mu.mu_model import load_preds
    from compute.sf.panels import load_congestion_panel, load_shadow_prices

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preds", default=None,
                   help="μ predictions/residual-pool npz; defaults to "
                        "runs/<run-id>/mu/mu_preds.npz on the runs PVC when "
                        "--run-id is given")
    p.add_argument("--scores", default=None,
                   help="μ weekly score CSV (r5); defaults to "
                        "runs/<run-id>/mu/mu_score_weekly.csv with --run-id, else "
                        "the legacy compute/mu bundle")
    p.add_argument("--start", default="2024-12-11")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--draws", type=int, default=N_DRAWS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None,
                   help="P50 band-metrics CSV; defaults to "
                        "runs/<run-id>/forecast/mu_bands_weekly.csv when --run-id "
                        "is given, else opt-in (nothing written)")
    p.add_argument("--nodal-out", default=None,
                   help="stream the per-week nodal P10/P50/P90 + point panel to "
                        "this flat vocab-coded .npz; defaults to "
                        "runs/<run-id>/forecast/mu_nodal.npz with --run-id, else "
                        "opt-in — omit run-id-less and nothing changes (no panel, "
                        "metrics CSV byte-identical)")
    p.add_argument("--to-db", action="store_true",
                   help="COPY the nodal panel into forecast_nodal and flip the "
                        "forecast_current[ercot] pointer (after rows land); requires "
                        "--run-id (which derives --nodal-out) or an explicit --nodal-out")
    p.add_argument("--run-id", default=None,
                   help="model-version tag for the forecast_nodal rows + pointer "
                        "(e.g. mu-all-v1); required with --to-db / --load-nodal-npz")
    p.add_argument("--load-nodal-npz", default=None,
                   help="seed forecast_nodal from an EXISTING panel .npz and flip "
                        "the forecast_current[ercot] pointer, WITHOUT re-running the "
                        "walk — the npz-of-record bulk path for standing up a fresh "
                        "DB (e.g. production catch-up). Requires --run-id; skips "
                        "preds/M/C entirely")
    p.add_argument("--drivers", default=None,
                   help="offline/debug: materialize top-k driver rows for an "
                        "EXPLICIT comma-separated list of curated delivery days "
                        "(e.g. 2025-06-01,2025-07-15). Curated only — refuses a "
                        "span and >%d days (full history is ~75M rows)"
                        % DRIVERS_MAX_DAYS)
    p.add_argument("--drivers-out", default=None,
                   help="CSV path for --drivers rows (default: drivers_<k>.csv)")
    p.add_argument("--drivers-k", type=int, default=DRIVERS_K,
                   help="top-k constraints per (ts, sp) for --drivers")
    p.add_argument("--map-run-id", default=MAP_RUN_ID,
                   help="weekly SF-map run to read persisted SF from (default %r); "
                        "the backfill projects through the same SF the live forecast "
                        "reads, so historic == live (0095-0002)" % MAP_RUN_ID)
    p.add_argument("--fit-sf", action="store_true",
                   help="refit SF per window in-process instead of reading the "
                        "persisted map — the pre-0002 self-contained behavior")
    args = p.parse_args(argv)

    # Resolve the walk's inputs/outputs from --run-id before the flag checks below,
    # so a run id derives --nodal-out (which --to-db then requires). --preds/--scores
    # always resolve to a path; --out/--nodal-out derive only under a run id.
    args.preds, args.scores, args.out, args.nodal_out = resolve_walk_paths(
        args.run_id, args.preds, args.scores, args.out, args.nodal_out,
        load_nodal_npz=bool(args.load_nodal_npz))

    if args.to_db and not (args.nodal_out and args.run_id):
        p.error("--to-db requires --run-id (which derives --nodal-out) or an "
                "explicit --nodal-out to load the panel from")
    if args.load_nodal_npz:
        if not args.run_id:
            p.error("--load-nodal-npz requires --run-id (the run to seed + promote)")
        if args.nodal_out or args.to_db or args.drivers:
            p.error("--load-nodal-npz is a standalone seed-from-npz mode; it does "
                    "not run the walk, so --nodal-out/--to-db/--drivers make no "
                    "sense with it")
    curated = None
    if args.drivers is not None:
        try:
            curated = {d.date(): None for d in parse_curated_days(args.drivers)}
        except ValueError as e:
            p.error(str(e))

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    if args.load_nodal_npz:
        # Seed a fresh DB from the npz-of-record — no walk, no preds/M/C. The whole
        # run is (re)written and the pointer flipped LAST, one transaction, so a
        # reader never sees a half-loaded run (same discipline as --to-db).
        with psycopg.connect(dsn) as conn:
            n = nodal_to_db(args.load_nodal_npz, conn, run_id=args.run_id)
            upsert_pointer(conn, FORECAST_LAYER, args.run_id)
            conn.commit()
        log.info("forecast_nodal <- %s rows from %s (run_id=%s); "
                 "forecast_current[%s] -> %s", n, args.load_nodal_npz, args.run_id,
                 FORECAST_LAYER, args.run_id)
        return 0

    log.info("loading residual pool from %s", args.preds)
    preds = load_preds(args.preds)
    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
    log.info("M = %s   C = %s", M.shape, C.shape)

    # Route the backfill through the same persisted weekly SF the live forecast
    # reads (0095-0002), so a historic week matches live: per week s, load the
    # causal (window_end ≤ s) latest map window. `--fit-sf` restores the pre-0002
    # in-process refit. The loader keeps its own open connection across the walk.
    sf_loader = None
    sf_conn = None
    if not args.fit_sf:
        sf_conn = psycopg.connect(dsn)

        def sf_loader(s, _c=sf_conn, _rid=args.map_run_id):
            win = resolve_sf_window(_c, _rid, as_of=pd.Timestamp(s))
            return None if win is None else load_window_sf(_c, _rid, win[0])

    # Create the derived forecast/ tree before the walk streams the nodal npz into
    # it — a first run on a fresh PVC has no runs/<id>/forecast/ dir yet.
    if args.nodal_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.nodal_out)) or ".",
                    exist_ok=True)
    try:
        bands = walk(M, C, preds, args.draws, args.seed, nodal_out=args.nodal_out,
                     curated=curated, sf_loader=sf_loader)
    finally:
        if sf_conn is not None:
            sf_conn.close()
    scores = pd.read_csv(args.scores, parse_dates=["week"])
    print(r5(scores, bands))
    if args.out and not bands.empty:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        bands.to_csv(args.out, index=False)
        print(f"wrote {args.out}")

    if curated is not None:
        # Curated-day debug: the walk filled `curated` with each requested day's
        # SF+μ artifact; materialize its top-k driver rows to CSV. If --run-id is
        # set, also land the artifact in forecast_sf_artifact (the object the
        # endpoints read; §4a) so a curated day is inspectable end to end.
        missing = [d for d, a in curated.items() if a is None]
        if missing:
            log.warning("--drivers: %d requested day(s) not covered by the walk "
                        "window — skipped: %s", len(missing), missing)
        conn = psycopg.connect(dsn) if args.run_id else None
        frames = []
        for day, art in curated.items():
            if art is None:
                continue
            frames.append(materialize_drivers(art, args.drivers_k).assign(
                delivery_date=day))
            if conn is not None:
                persist_sf_mu_artifact(conn, art.SF, art.E_mu,
                                       run_id=args.run_id, delivery_date=day)
        if conn is not None:
            conn.commit()
            conn.close()
        drivers = (pd.concat(frames, ignore_index=True) if frames
                   else pd.DataFrame())
        out = args.drivers_out or f"drivers_{args.drivers_k}.csv"
        drivers.to_csv(out, index=False)
        log.info("--drivers: %d rows across %d curated day(s) -> %s",
                 len(drivers), len(frames), out)

    if args.to_db:
        # Load the panel just written to disk, then flip the pointer LAST — one
        # transaction, so a reader never sees a half-written run.
        with psycopg.connect(dsn) as conn:
            n = nodal_to_db(args.nodal_out, conn, run_id=args.run_id)
            upsert_pointer(conn, FORECAST_LAYER, args.run_id)
            conn.commit()
        log.info("forecast_nodal <- %s rows (run_id=%s); forecast_current[%s] -> %s",
                 n, args.run_id, FORECAST_LAYER, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
