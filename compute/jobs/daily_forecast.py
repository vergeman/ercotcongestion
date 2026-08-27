"""The `forecast_day` production job — fit-then-predict for one delivery day D.

At/after DAM close on D−1, produce the deterministic nodal forecast for CT
delivery day D and the per-day SF+μ artifact.

"delivery day" here is the **CT calendar day**: `[ct_day_bounds(D)]`, DST-aware
(23/24/25 hours), not a fixed 24-hour UTC block. `delivery_date = D.date()` is
that CT calendar date - a UTC-midnight cut split five CT-evening hours into the
following block.

"""
from __future__ import annotations

import gc
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from compute.artifacts import DEFAULT_RUNS_ROOT
from compute.forecast_store import (
    FORECAST_LAYER,
    nodal_to_db,
    persist_sf_mu_artifact,
    upsert_pointer,
)
from compute.jobs.forecast_history import load_artifact, persist_rollup
from compute.jobs.grade_day import (
    grade_day,
    persist_grades,
    resolve_gradeable_date,
)
from compute.jobs.materialize_brief_grade import materialize_day as materialize_brief_grade
from compute.mu_forecast.panel.build import build_panel
from compute.time import ERCOT_TZ, ct_day_bounds, normalize_ct_day
from compute.mu_forecast.model.runner import (
    DEFAULT_TRAIN_DAYS,
    arms_for,
    predict_day,
    spill_panel_features,
)
from compute.evaluation.mu import REFIT_DAYS, WINDOW_DAYS
from compute.inputs.dam import (
    dam_shadow_covers_window,
    load_congestion_panel,
    load_shadow_prices,
)
from compute.projection.codecs import (
    NodalPanel,
    _NodalAccumulator,
    build_sf_mu_artifact,
)
from compute.projection.propagate import propagate_window
from compute.sf_map.storage.maps import (
    MAP_RUN_ID,
    MAX_SF_AGE_DAYS,
    MIN_SF_COVERAGE,
    load_forecast_sf,
    resolve_sf_window,
)

log = logging.getLogger(__name__)

# Retained for tests that redirect the mounted runs PVC.
RUNS_ROOT = DEFAULT_RUNS_ROOT


DEFAULT_ARMS = ("lag", "geo", "wx")      # the shipped `all` config (FEATURE_SETS)

# `run_id` names the MODEL VERSION. Each daily run appends a new
# `delivery_date` under the same `run_id`

@dataclass
class ForecastResult:
    """One delivery day's forecast, held in memory (nothing written yet).

    `panel` is the deterministic nodal point forecast over D's CT hours; `SF`/`E_mu` are
    the day's fitted SF map and μ head that `sf_mu` serializes.
    """

    run_id: str
    delivery_date: date
    panel: NodalPanel
    SF: pd.DataFrame
    E_mu: pd.DataFrame
    sf_mu: bytes
    horizon: int = 1              # 1 = final/t+1, 2 = preview/t+2 (0123)
    novelty: int = 0
    novel_keys: list[str] = field(default_factory=list)
    n_scored_keys: int = 0        # constraints predicted (in wp) — coverage numerator
    map_run_id: str = ""          # weekly SF map projected through (run-log provenance)
    sf_window_end: date | None = None   # its window close — pins the SF vintage used


def _as_ct_day(D) -> pd.Timestamp:
    """Normalize any date-ish `D` to the UTC instant marking CT midnight - the
    delivery-day block boundary the whole pipeline slices on (`predict_day`
    anchors the same way).

    """
    return normalize_ct_day(D)


def _ct_block_end(D: pd.Timestamp) -> pd.Timestamp:
    """The exclusive upper bound of D's CT delivery-day block — D's next CT
    midnight. Not `D + 24h`: DST transition days are 23/25 hours (0133)."""
    _, end = ct_day_bounds(D)
    return end


def _assert_freshest_history_published(conn, D: pd.Timestamp) -> None:
    """Fail loud if delivery day D−1 has no `ercot_dam_shadow_prices` rows yet.

    The horizon-2 (preview) tick fires the same afternoon T+1's DAM is due
    (~13:30 CT); the fit's freshest history day is D−1 (= T+1). A late ERCOT
    post would let the fit run with that day silently missing. So before the
    fit, assert D−1's DAM has published.

    """
    lo, _ = ct_day_bounds(D.tz_convert(ERCOT_TZ).date() - timedelta(days=1))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(interval_ts) FROM ercot_dam_shadow_prices "
            "WHERE interval_ts >= %s AND interval_ts < %s", (lo, D))
        ts_max = cur.fetchone()[0]
    # Not merely "any row": D−1's UTC window always catches the ~5h tail of the
    # op-day before it, so a bare existence check false-passes when T+1's own
    # DAM has not yet landed. Require the shadow prices to actually span D−1's
    # window.
    if not dam_shadow_covers_window(ts_max, lo):
        raise RuntimeError(
            f"horizon-2 gate: ercot_dam_shadow_prices does not span delivery day "
            f"{lo.date()} (D−1, the freshest history day; latest interval "
            f"{ts_max}) — T+1's DAM has not published yet, only the prior op-day's "
            f"tail. Refusing to fit a preview on stale history (spec §8: fail, "
            f"nothing written, prior rows intact).")


def forecast_day(
    conn,
    D,
    *,
    run_id: str,
    horizon: int = 1,
    train_days: int = DEFAULT_TRAIN_DAYS,
    arms: tuple[str, ...] = DEFAULT_ARMS,
    seed: int = 0,
    map_run_id: str = MAP_RUN_ID,
    max_sf_age_days: int = MAX_SF_AGE_DAYS,
    min_sf_coverage: float = MIN_SF_COVERAGE,
    fire_time: pd.Timestamp | None = None,
) -> ForecastResult:
    """Fit the heads on the trailing window and forecast CT delivery day D.

    Two stages:

      1. **μ inference** — `build_panel` at the DAM-close vintage over
         `[D−train_days, D+1)`; `predict_day(panel, D)` fits both heads on the
         trailing window and predicts D's 24 hours (`wp`: `p_bind`, `mu_gbm`).
         2. **propagation** — load the weekly map's persisted SF (run
         `map_run_id`) via `load_forecast_sf` and project the nodal panel through
         it with `propagate_window`; the map fits this SF weekly, and is
         stationary within the refit interval.

    `fire_time` is this run's instant, standing in for "now" — the covariate
    vintage cutoff (`build_panel`'s `vintage_cutoff`). It defaults to the
    actual wall clock (`pd.Timestamp.now`), which for every live tick is
    already well after D's DAM close. It matters for a **historical h2
    backfill**: it reproduces exactly what that live run could have seen — one
    daily load/wind/solar snapshot and up to a day of outage snapshots earlier
    than the DAM-close default would read — so a re-backfilled preview stays a
    genuinely disadvantaged preview instead of collapsing into a re-labeled
    final (`compute/jobs/backfill_artifacts.py` computes it).

    Reads only; writes nothing and does not touch the pointer (the next commit adds
    persistence). Every read sees only intervals < D.

    """
    D = _as_ct_day(D)
    fire_time = fire_time if fire_time is not None else pd.Timestamp.now(tz="UTC")
    block_end = _ct_block_end(D)      # D's next CT midnight — DST-aware
    # Horizon-2 (preview) fires while D−1's DAM is still landing; a late ERCOT
    # post fails loud rather than fitting on a missing freshest day. Horizon 1
    # fires two hours after D−1 closed.
    if horizon == 2:
        _assert_freshest_history_published(conn, D)
    read_start = D - pd.Timedelta(days=train_days + WINDOW_DAYS + REFIT_DAYS)
    log.info("forecast_day %s  run_id=%s  horizon=%d  arms=%s  train_days=%d  "
             "fire_time=%s",
             D.date(), run_id, horizon, ",".join(arms), train_days, fire_time,
             )

    # --- stage 1: μ inference ------------------------------------------------
    try:
        M = load_shadow_prices(conn, read_start, D)
        C = load_congestion_panel(conn, read_start, D) if "geo" in arms else None
        panel = build_panel(conn, M, read_start, block_end,
                            C=C, score_from=D,
                            with_weather="wx" in arms,
                            with_outage="outage" in arms,
                            vintage_cutoff=fire_time)
    except Exception as e:
        # Any failure assembling the inputs (a covariate source empty, ingest late)
        # is fatal — an honest forecast can't be built, so fail and keep the prior
        # pointer rather than emit a degraded one. Chained, so the root cause shows.
        raise RuntimeError(
            f"failed to build the feature panel for {D.date()} — a covariate "
            f"vintage is missing or ingest is late (spec §8: fail, keep pointer)"
        ) from e
    if panel.empty:
        raise RuntimeError(f"empty feature panel for {D.date()} — no covariate "
                           f"vintage at DAM close (spec §8: fail, keep pointer)")

    keep_from = D - pd.Timedelta(days=train_days)
    panel = panel.loc[panel.index.get_level_values("interval_ts") >= keep_from]
    gc.collect()

    # The daily refit trains on the same 240-day window the backtest's late folds do,
    # in anonymous RAM it coexists with the resident panel and OOMs a 16 GB node.
    # Spill it to disk always: MU_SPILL_DIR when set, else the system temp dir, which
    # is always writable.

    spill_dir = os.environ.get("MU_SPILL_DIR") or tempfile.gettempdir()
    if os.environ.get("MU_SPILL_PANEL"):
        panel = spill_panel_features(panel, spill_dir)
    wp = predict_day(panel, D, train_days=train_days, arms=arms, seed=seed,
                     spill_dir=spill_dir)
    novelty = int(wp.attrs.get("novelty", 0))
    novel_keys = list(wp.attrs.get("novel_keys", []))
    if len(wp) == 0:
        raise RuntimeError(
            f"no scorable constraints for {D.date()} — either no covariate vintage "
            f"for D's hours, or every enforced key is novel with no binding history "
            f"to fit ({novelty} novel). Refusing to publish an empty forecast "
            f"(spec §8: novel keys are surfaced, but an all-novel day has no map).")
    log.info("stage 1: panel %s rows, wp %d scored keys, novelty=%d",
             f"{len(panel):,}", wp["key"].nunique() if len(wp) else 0, novelty)

    # Load the weekly map's persisted SF
    SF_map = load_forecast_sf(conn, D, wp, run_id=map_run_id,
                              max_age_days=max_sf_age_days,
                              min_coverage=min_sf_coverage)
    # Pin the SF vintage in the result for the run log
    sf_win = resolve_sf_window(conn, map_run_id, as_of=D)
    sf_window_end = sf_win[1].date() if sf_win is not None else None

    # Stage 2 needs only `wp` and the loaded `SF_map` — never the feature
    # `panel`, and no longer M/C for an SF fit. `forecast_day` still holds the
    # wide feature panel that built `wp`; free it before propagation so the
    # peak doesn't sum. With the SF now loaded (not fit), M/C no longer feed an
    # SF solve — they're kept only so `propagate_window`'s forward-mode
    # bookkeeping (`M_score`, empty for D) has a frame.
    del panel
    fit_lo = D - pd.Timedelta(days=WINDOW_DAYS)
    M = M.loc[M.index >= fit_lo]
    if C is not None:
        C = C.loc[C.index >= fit_lo]
    gc.collect()

    # --- STAGE 2: DETERMINISTIC PROJECTION -----------------------------------

    # D's score-block hours — D's CT calendar day, 23/24/25 hours across a DST
    # transition.
    forward_hours = pd.date_range(D, block_end, freq="h", inclusive="left")
    _, panel_out, SF, E_mu = propagate_window(     # forward mode → no metrics row
        s=D, end=block_end, M=M, C=C, wp=wp, sf=SF_map,
        want_panel=True, want_sf_mu=True, forward_hours=forward_hours)
    if panel_out is None:
        raise RuntimeError(f"propagation produced no panel for {D.date()} — the "
                           f"loaded SF map projected nothing (spec §8: fail loudly)")
    log.info("stage 2: SF %dx%d, panel %d hours x %d SPs",
             SF.shape[0], SF.shape[1], len(panel_out.ts),
             len(panel_out.settlement_points))

    # Degenerate μ head → an all-zero (flat) panel..
    finite = panel_out.point[np.isfinite(panel_out.point)]
    if finite.size == 0 or float(np.abs(finite).max()) == 0.0:
        raise RuntimeError(
            f"degenerate all-zero forecast for {D.date()} — the mu head produced no "
            f"non-zero congestion (flat panel). Refusing to publish (spec §8).")

    sf_mu = build_sf_mu_artifact(SF, E_mu)
    return ForecastResult(
        run_id=run_id, delivery_date=D.date(), panel=panel_out,
        SF=SF, E_mu=E_mu, sf_mu=sf_mu, horizon=horizon,
        novelty=novelty, novel_keys=novel_keys,
        n_scored_keys=int(wp["key"].nunique()) if len(wp) else 0,
        map_run_id=map_run_id, sf_window_end=sf_window_end)


def _write_nodal_npz(result: ForecastResult, path: str) -> None:
    """Serialize the in-memory `NodalPanel` to the flat vocab-coded npz `nodal_to_db`
    reads — the exact format `walk()` streams, so a forward day and a backtest day
    are byte-compatible on disk. `week` is the delivery day itself (one window)."""
    sink = _NodalAccumulator()
    sink.add(result.panel, pd.Timestamp(result.delivery_date, tz="UTC"))
    sink.save(path)


def persist_forecast(conn, result: ForecastResult, *,
                     npz_dir: str | None = None,
                     layer: str = FORECAST_LAYER) -> int:
    """Land one day's forecast and flip this feature's own pointer **last**.

    Order is the contract: `forecast_nodal` rows, then the `forecast_sf_artifact`
    blob, then `upsert_pointer(forecast_current[layer])`, then one `commit()`.

    Idempotent per `(run_id, delivery_date, horizon)`: `nodal_to_db`/
    `persist_sf_mu_artifact` both replace-in-place scoped to the CT delivery
    date and horizon, so a re-run of D under the same `run_id` overwrites only
    that horizon's rows and blob — a horizon-1 (final) publish never touches
    the preserved horizon-2 (preview) rows and vice versa — and leaves the
    pointer where it is. `npz_dir` (optional) is the on-disk artifact of record
    — the nodal and SF+μ npz land there too, byte-identical to the DB, each
    tagged with an `h{horizon}` suffix so the two tracks never share a
    filename; omitted, only the DB is written (a throwaway temp file carries
    the nodal panel into `COPY`). `layer` defaults to the served `ercot`
    pointer; a test overrides it to a scratch layer so it never touches the
    live one. Returns rows written.

    """
    D = result.delivery_date
    run_id = result.run_id
    horizon = result.horizon
    if npz_dir is None:
        tmp = tempfile.TemporaryDirectory()
        out_dir = tmp.name
    else:
        tmp = None
        os.makedirs(npz_dir, exist_ok=True)
        out_dir = npz_dir
    try:
        nodal_path = os.path.join(out_dir,
                                  f"nodal_{run_id}_{D.isoformat()}h{horizon}.npz")
        _write_nodal_npz(result, nodal_path)
        n = nodal_to_db(nodal_path, conn, run_id=run_id, delivery_date=D,
                        horizon=horizon)
        persist_sf_mu_artifact(conn, result.SF, result.E_mu,
                               run_id=run_id, delivery_date=D, npz_dir=npz_dir,
                               horizon=horizon)
        upsert_pointer(conn, layer, run_id)               # pointer LAST, before commit
        conn.commit()                                     # the atomic flip
    finally:
        if tmp is not None:
            tmp.cleanup()
    log.info("published %s nodal rows for %s (horizon %d) under run_id=%s; "
             "pointer[%s] -> %s", f"{n:,}", D, horizon, run_id, layer, run_id)
    return n


# --------------------------------------------------------------------------
# CLI — the daily tick and single-day backfill on the identical path (spec §7)
# --------------------------------------------------------------------------

def _resolve_delivery_date(spec: str, *, horizon: int = 1,
                           now: pd.Timestamp | None = None) -> pd.Timestamp:
    """`tomorrow` → the CT day `horizon` days ahead; else parse `YYYY-MM-DD` as the
    CT day directly. Both go through `_as_ct_day`, so the CLI and the daily cron
    share one code path.

    `tomorrow` means what an operator standing in Texas means: horizon 1 (final) is
    the CT calendar date after today's (T+1, the classic next day); horizon 2
    (preview) is two CT days out (T+2 — the run lands inside D's decision window,
    before D's DAM closes). The CT date is normalized *before* the offset is added, so
    the arithmetic is naive and a 23-/25-hour DST day cannot shift the answer.
    """
    if spec == "tomorrow":
        now = now if now is not None else pd.Timestamp.now(tz="UTC")
        today_ct = now.tz_convert(ERCOT_TZ).normalize().tz_localize(None)
        return _as_ct_day(today_ct + pd.Timedelta(days=horizon))
    return _as_ct_day(spec)


def _ct_span(D: pd.Timestamp) -> str:
    """D's CT delivery-day span, wall clock and DST tag.

    D is already CT midnight (0133), so this always reads 00:00 -> 23:00 CT;
    logging it anyway keeps a regression (an off-CT-midnight D) self-evident in
    the run log instead of something discovered by scrubbing onto a hole.
    """
    lo = D.tz_convert(ERCOT_TZ)
    hi = (_ct_block_end(D) - pd.Timedelta(hours=1)).tz_convert(ERCOT_TZ)
    return f"CT {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M} {hi:%Z}"


def _day_already_published(conn, run_id: str, D: pd.Timestamp,
                           horizon: int = 1) -> bool:
    """True when `(run_id, delivery_date, horizon)` already has rows in
    `forecast_nodal`.

    The preview's existence must never block the final run for the same day and
    vice versa — they publish side by side.

    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecast_nodal WHERE run_id = %s AND delivery_date = %s "
            "AND horizon = %s LIMIT 1", (run_id, D.date(), horizon))
        return cur.fetchone() is not None


def _summary(result: ForecastResult) -> str:

    seen = result.n_scored_keys
    cov = seen / (seen + result.novelty) if (seen + result.novelty) else float("nan")
    sample = ", ".join(result.novel_keys[:5])
    # map_run_id + SF window pin the geography vintage: a preview(h2)-vs-final(h1) diff
    # for a day is only a clean covariate-vintage delta if BOTH projected through the
    # same weekly map window.
    return (f"horizon {result.horizon}; coverage: {result.SF.shape[0]} SF "
            f"constraints x {len(result.panel.settlement_points)} SPs over "
            f"{len(result.panel.ts)} h; scored {seen} keys, "
            f"{result.novelty} novel (enforced D-1, no fit history; "
            f"{cov:.1%} scored); map_run_id={result.map_run_id} "
            f"SF window_end={result.sf_window_end}"
            + (f" — e.g. {sample}" if sample else ""))


def _grade_latest(conn, run_id: str, horizon: int = 1) -> "pd.Timestamp | None":
    """Fold the live grade into the daily tick (no separate job): grade the most
    recent fully-realized, ungraded served day for `run_id` on THIS horizon's track.

    Returns the day it graded (so the brief step can re-brief it for F6
    after-action now that its DAM has landed), or None when nothing was gradeable
    or grading failed.

    Horizon-scoped: the h2 tick grades the h2 track and the h1 tick the h1
    track, two independent scoreboards — a day the preview already graded does
    not stop the final from grading it and vice versa.
    """
    try:
        D = resolve_gradeable_date(conn, run_id, horizon)
        if D is None:
            log.info("live grade: no ungraded fully-realized served day this tick "
                     "(horizon %d)", horizon)
            return None
        rows = grade_day(conn, D, run_id=run_id, horizon=horizon)
        n = persist_grades(conn, run_id, D, rows, horizon)
        conn.commit()
        if not materialize_brief_grade(conn, run_id, D.date(), horizon):
            log.warning("live grade: Brief v6 history skipped for %s (run_id=%s horizon=%d)",
                        D.date(), run_id, horizon)
        log.info("live grade: scoreboard_daily <- %d rows for %s (run_id=%s "
                 "horizon=%d)", n, D.date(), run_id, horizon)
        return D
    except Exception:
        conn.rollback()
        log.exception("live grade step failed (non-fatal; forecast already "
                      "published for this tick)")
        return None


def _forecast_history_latest(conn, run_id: str, published: "pd.Timestamp",
                             horizon: int) -> None:
    """Append the just-published day's queryable forecast history, fail-soft.

    This runs only after ``persist_forecast`` has committed the artifact and
    pointer. The idempotent backfill job repairs any skipped day.

    """
    try:
        artifact = load_artifact(conn, run_id, published.date(), horizon)
        if artifact is None:
            log.warning("forecast-history step skipped for %s: published artifact "
                        "is unexpectedly missing (run_id=%s horizon=%d)",
                        published.date(), run_id, horizon)
            return
        n = persist_rollup(conn, run_id, published.date(), horizon, artifact)
        conn.commit()
        log.info("forecast history: forecast_constraint_daily <- %d rows for %s "
                 "(run_id=%s horizon=%d)", n, published.date(), run_id, horizon)
    except Exception:
        conn.rollback()
        log.exception("forecast-history step failed for %s (non-fatal; forecast "
                      "already published for this tick)", published.date())


def main(argv: list[str] | None = None) -> int:
    import argparse

    import psycopg

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--delivery-date", required=True,
                   help="'tomorrow' (the daily tick — the next CT calendar date) "
                        "or 'YYYY-MM-DD' (single-day backfill on the identical "
                        "path; names the CT day label directly)")
    p.add_argument("--run-id", required=True,
                   help="model version, e.g. mu-all-v1 — NOT the day (spec §4)")
    p.add_argument("--horizon", type=int, choices=(1, 2), default=1,
                   help="1 = final/t+1 (the noon tick, verification-grade; default); "
                        "2 = preview/t+2 (the afternoon tick, inside D's decision "
                        "window). Same model version; horizon 2 resolves 'tomorrow' "
                        "to T+2, gates on D−1's DAM, and persists side by side with "
                        "the final — never overwriting it (0123).")
    p.add_argument("--to-db", action="store_true",
                   help="persist + flip the pointer; omit for a dry run (compute "
                        "and report only, nothing written)")
    p.add_argument("--features", default="all",
                   help="ablation arm set (default 'all' = the shipped lag+geo+wx)")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--npz-dir", default=None,
                   help="also write the nodal + SF+mu npz here (disk of record, "
                        "spec §5c); DB-only when omitted")
    p.add_argument("--map-run-id", default=MAP_RUN_ID,
                   help=f"weekly SF-map run to project through (default "
                        f"{MAP_RUN_ID!r}); the forecast reads its persisted SF "
                        f"instead of refitting (0095-0002)")
    p.add_argument("--max-sf-age-days", type=int, default=MAX_SF_AGE_DAYS,
                   help=f"fail loud if the latest map window closes more than this "
                        f"many days before D (default {MAX_SF_AGE_DAYS})")
    p.add_argument("--min-sf-coverage", type=float, default=MIN_SF_COVERAGE,
                   help=f"fail loud if the map locates less than this share of D's "
                        f"predicted binding mass (default {MIN_SF_COVERAGE})")
    p.add_argument("--force", action="store_true",
                   help="allow overwriting a delivery day already published under "
                        "this --run-id. Without it a --to-db run that would replace "
                        "existing forecast_nodal rows exits non-zero before the fit")
    p.add_argument("--no-grade", action="store_true",
                   help="skip the live grade step that normally follows a --to-db "
                        "publish. The daily tick grades the most recent fully-"
                        "realized served day in the same run (no separate job); "
                        "pass this for a forecast-only backfill of a future/today "
                        "day whose realized has not published yet")
    p.add_argument("--fire-time", default=None,
                   help="the run's covariate-vintage cutoff (ISO instant, any tz — "
                        "0133); defaults to the actual wall clock (live behavior). "
                        "Pass a historical h2 run's real fire instant (20:15Z on "
                        "D−2, the live cron's own schedule) for a vintage-faithful "
                        "single-day preview backfill — see backfill_artifacts.py, "
                        "which computes this automatically for a date range")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # prep dates
    D = _resolve_delivery_date(args.delivery_date, horizon=args.horizon)
    log.info("delivery_date=%s (%s) from --delivery-date %s (horizon %d)",
             D.date(), _ct_span(D), args.delivery_date, args.horizon)
    fire_time = None
    if args.fire_time is not None:
        fire_time = pd.Timestamp(args.fire_time)
        if fire_time.tzinfo is None:      # a bare instant with no offset is UTC
            fire_time = fire_time.tz_localize("UTC")

    # prep features
    arms = arms_for(args.features)

    dsn = (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
           f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

    with psycopg.connect(dsn) as conn:
        # Before the fit, not after: a re-run that would clobber a published day
        # should cost a query, not 20 minutes of compute and the day it replaces.
        if args.to_db and not args.force and _day_already_published(
                conn, args.run_id, D, args.horizon):
            log.error("%s is already published under run_id=%s horizon=%d — refusing "
                      "to overwrite. Re-run with --force if that is intended.",
                      D.date(), args.run_id, args.horizon)
            return 1
        result = forecast_day(conn, D, run_id=args.run_id, horizon=args.horizon,
                              train_days=args.train_days, arms=arms,
                              seed=args.seed,
                              map_run_id=args.map_run_id,
                              max_sf_age_days=args.max_sf_age_days,
                              min_sf_coverage=args.min_sf_coverage,
                              fire_time=fire_time)
        log.info(_summary(result))
        if args.to_db:
            persist_forecast(conn, result, npz_dir=args.npz_dir)
            # Grade the most recent realized served day in the same tick. Free the
            # fit's working set first so the two peaks don't sum on a 16Gi node.
            del result
            gc.collect()
            if not args.no_grade:
                _grade_latest(conn, args.run_id, args.horizon)
            _forecast_history_latest(conn, args.run_id, D, args.horizon)
        else:
            log.info("dry run (--to-db not set): nothing written, pointer unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
