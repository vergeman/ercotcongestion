"""Backtest walk → nodal panel seed, and the R5 verdict, against the bar as written.

The one-time historical backfill runner (README §A): walk the validated
predictions forward through the SF map, stream the per-week nodal P10/P50/P90 +
point panel to a flat npz, and — with `--to-db` / `--load-nodal-npz` — bulk-seed
`forecast_nodal` and flip `forecast_current[ercot]`. Owns the DB writers the daily
`forecast_day` also uses (`nodal_to_db`, `persist_sf_mu_artifact`, `upsert_pointer`)
and the pre-registered R5 gate. The projection math it drives lives in
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

from compute.mu.score import REFIT_DAYS, RTC_B, weeks_from_preds
from compute.sf.project import (
    DRIVERS_K,
    DRIVERS_MAX_DAYS,
    N_DRAWS,
    SfMuArtifact,
    _NodalAccumulator,
    build_sf_mu_artifact,
    load_nodal,
    materialize_drivers,
    parse_curated_days,
    propagate_window,
    residual_pool,
)

log = logging.getLogger("compute.jobs.backfill_nodal")

FORECAST_LAYER = "ercot"


def _delivery_dates(ts: pd.Series) -> pd.Series:
    """UTC calendar date of each tz-aware UTC hour — the `forecast_nodal`/
    `forecast_sf_artifact` `delivery_date` and the idempotency scope for a re-run.

    The whole stack below the API speaks UTC instants: every `interval_ts` is a
    true UTC instant (migration 17 repaired the CT-as-UTC drift), the API coerces
    to UTC, and the model slices the UTC-normalized index. `delivery_date` is
    therefore the UTC date, not the ERCOT CT operating day — a UTC day's 24 hours
    share one `delivery_date`, so a single-day write/scope is clean. (The DAM-close
    vintage cutoff in `features.py` stays a CT wall-clock event; that pins each
    covariate's *publication time* per interval and is independent of this label.)
    """
    return ts.dt.tz_convert("UTC").dt.date


def nodal_to_db(npz_path: str, conn, *, run_id: str,
                delivery_date=None) -> int:
    """Load a `save_nodal` panel and `COPY` it into `forecast_nodal` for `run_id`.

    Idempotent by delete-then-copy scoped to what is written, so a re-run replaces
    cleanly (spec §5b, phase2b §6): with `delivery_date` set, only that operating
    day for the run is cleared and only its rows land (the single-day production
    path); with it `None`, the whole run is cleared and every day in the npz is
    (re)written (the backtest bulk path). `delivery_date` is derived per row from
    the CT-local date of `ts`, so the same PK never both survives and reappears —
    collisions replace, not duplicate.

    Does NOT commit and does NOT touch the pointer — the caller flips
    `forecast_current` via `upsert_pointer` AFTER these rows land, so a reader
    never sees a half-written day. Returns the number of rows written.
    """
    target = pd.Timestamp(delivery_date).date() if delivery_date is not None else None
    df = load_nodal(npz_path)
    df = df.assign(delivery_date=_delivery_dates(df["ts"]))
    if target is not None:
        df = df[df["delivery_date"] == target]

    with conn.cursor() as cur:
        if target is not None:
            cur.execute(
                "DELETE FROM forecast_nodal WHERE run_id = %s "
                "AND delivery_date = %s", (run_id, target))
        else:
            cur.execute("DELETE FROM forecast_nodal WHERE run_id = %s", (run_id,))

    ts_iso = df["ts"].astype(str).to_numpy()          # ISO w/ +00:00 offset
    dd_iso = df["delivery_date"].astype(str).to_numpy()
    sp = df["settlement_point"].to_numpy()
    p10, p50, p90 = (df[c].to_numpy(np.float64) for c in ("p10", "p50", "p90"))
    point = df["point"].to_numpy(np.float64)

    def _f(v) -> float | None:                        # NaN percentile -> NULL
        return v if np.isfinite(v) else None

    sql = ("COPY forecast_nodal (run_id, delivery_date, ts, settlement_point, "
           "p10, p50, p90, point) FROM STDIN")
    n = len(df)
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for i in range(n):
            cp.write_row((run_id, dd_iso[i], ts_iso[i], sp[i],
                          _f(p10[i]), _f(p50[i]), _f(p90[i]), _f(point[i])))
    return n


def upsert_pointer(conn, layer: str, run_id: str) -> None:
    """Flip `forecast_current[layer] = run_id`. Call ONLY after the rows land —
    this feature's own pointer, mirroring `set_current_pointer` for the IBP map,
    never the legacy `implied_binding_proximity_current`."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_current (layer, run_id) VALUES (%s, %s) "
            "ON CONFLICT (layer) DO UPDATE "
            "SET run_id = EXCLUDED.run_id, promoted_at = now()",
            (layer, run_id))


def sf_artifact_to_db(conn, *, run_id: str, delivery_date, sf_npz: bytes) -> None:
    """Upsert the day's SF+μ npz blob into `forecast_sf_artifact` for
    `(run_id, delivery_date)`. Idempotent replace-in-place, the same discipline as
    `nodal_to_db` (0010): a re-run overwrites the day's blob, never appends. Does
    NOT commit — the caller owns the transaction."""
    dd = pd.Timestamp(delivery_date).date()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_sf_artifact (run_id, delivery_date, sf_npz) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (run_id, delivery_date) DO UPDATE "
            "SET sf_npz = EXCLUDED.sf_npz",
            (run_id, dd, sf_npz))


def persist_sf_mu_artifact(conn, SF: pd.DataFrame, E_mu: pd.DataFrame, *,
                           run_id: str, delivery_date, npz_dir: str | None = None,
                           ) -> bytes:
    """Build the day's SF+μ blob once and land it per `(run_id, delivery_date)`.

    Always upserts the `forecast_sf_artifact` bytea; also drops the identical npz
    under `npz_dir` when given (§5c — disk and DB hold the same bytes, either is
    authoritative). Idempotent replace per key; does NOT commit. Returns the blob so
    the caller can size/inspect it. `forecast_day` (phase2b) is the production
    caller; `--drivers` (below) is the offline one."""
    blob = build_sf_mu_artifact(SF, E_mu)
    if npz_dir is not None:
        dd = pd.Timestamp(delivery_date).date()
        with open(os.path.join(npz_dir, f"sf_mu_{run_id}_{dd.isoformat()}.npz"),
                  "wb") as fh:
            fh.write(blob)
    sf_artifact_to_db(conn, run_id=run_id, delivery_date=delivery_date, sf_npz=blob)
    return blob


def walk(M: pd.DataFrame, C: pd.DataFrame, preds: pd.DataFrame,
         n_draws: int = N_DRAWS, seed: int = 0,
         nodal_out: str | None = None,
         curated: dict | None = None) -> pd.DataFrame:
    if isinstance(preds.index, pd.MultiIndex):
        preds = preds.reset_index()
    weeks = weeks_from_preds(preds)
    rng = np.random.default_rng(seed)
    log.info("propagating %d weeks × %d draws (week 1 has no residual pool → no "
             "bands)", len(weeks), n_draws)

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

        end = s + pd.Timedelta(days=REFIT_DAYS)
        row, panel, SF, E_mu = propagate_window(
            s, end, M, C, by_week[s], eps, n_draws, rng,
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
            dd = _delivery_dates(pd.Series(E_mu.index, index=E_mu.index))
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
    p.add_argument("--to-db", action="store_true",
                   help="COPY the --nodal-out panel into forecast_nodal and flip "
                        "the forecast_current[ercot] pointer (after rows land); "
                        "requires --nodal-out and --run-id")
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
    args = p.parse_args(argv)
    if args.to_db and not (args.nodal_out and args.run_id):
        p.error("--to-db requires --nodal-out (the panel is loaded from it) "
                "and --run-id")
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

    preds = load_preds(args.preds)
    lo = pd.Timestamp(args.start, tz="America/Chicago")
    hi = pd.Timestamp(args.end, tz="America/Chicago")
    with psycopg.connect(dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)
    log.info("M = %s   C = %s", M.shape, C.shape)

    bands = walk(M, C, preds, args.draws, args.seed, nodal_out=args.nodal_out,
                 curated=curated)
    scores = pd.read_csv(args.scores, parse_dates=["week"])
    print(r5(scores, bands))
    if args.out and not bands.empty:
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
