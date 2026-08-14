"""The `forecast_day` production job — fit-then-predict for one delivery day D.

At/after DAM close on D−1, produce the forecast for UTC delivery day D: the nodal
P10/P50/P90 + point panel and the per-day SF+μ artifact. This module is stage-1 +
stage-2 wired end to end **in memory**; persistence and the self-owned pointer flip
are added in the next commit (spec-phase2b §6).

**Why fit-then-predict, not load-and-serve.** The μ-model persists *predictions*,
never fitted boosters (`mu_model.py` has no `joblib.dump`), so there is no weight
file to serve. `forecast_day` refits the heads at run time on the trailing window —
cheap, and honest by construction: `features.py` reads every covariate at its
DAM-close vintage, so tomorrow's panel is fully buildable today (spec §1).

**UTC throughout.** Every `interval_ts` in the DB is a true UTC instant (migration
17), the API speaks UTC, and the model slices the UTC-normalized index — so a
"delivery day" here is a **UTC calendar day** `[D, D+1)` (24 hours, no DST folds),
and `delivery_date = D.date()` (UTC). The DAM-close vintage cutoff in `features.py`
stays a CT wall-clock event; it pins each covariate's publication time per interval
and is independent of this day label (spec §5).
"""
from __future__ import annotations

import gc
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from compute.jobs.backfill_nodal import (
    FORECAST_LAYER,
    nodal_to_db,
    persist_sf_mu_artifact,
    upsert_pointer,
)
from compute.jobs.daily_brief import compute_brief, persist_brief
from compute.jobs.forecast_history import load_artifact, persist_rollup
from compute.jobs.grade_day import (
    grade_day,
    persist_grades,
    resolve_gradeable_date,
)
from compute.jobs.materialize_brief_grade import materialize_day as materialize_brief_grade
from compute.mu.features import ERCOT_TZ, build_panel
from compute.mu.mu_model import (
    DEFAULT_TRAIN_DAYS,
    arms_for,
    load_preds,
    predict_day,
    spill_panel_features,
)
from compute.mu.score import REFIT_DAYS, WINDOW_DAYS
from compute.sf.panels import (
    dam_shadow_covers_window,
    load_congestion_panel,
    load_shadow_prices,
)
from compute.sf.project import (
    MAP_RUN_ID,
    MAX_SF_AGE_DAYS,
    MIN_SF_COVERAGE,
    N_DRAWS,
    NodalPanel,
    _NodalAccumulator,
    build_sf_mu_artifact,
    load_forecast_sf,
    propagate_window,
    residual_pool,
    resolve_sf_window,
)

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"    # the mounted /compute/runs PVC


def preds_path_for(run_id: str) -> str:
    """Resolve the μ residual-pool npz for `run_id` on the runs PVC.

    The validated backtest's out-of-sample residuals, sampled to form the forward
    error pool (panel spec §7). It is the model-VERSION artifact — produced once per
    `run_id` (runbook step 2) and reused by every daily run — so it lives with the
    rest of the run's artifacts under `runs/<run_id>/mu/`, the same path
    `mu_model --preds-out` and `backfill_nodal --preds` write and read. Loading it
    from the mounted PVC by `run_id` replaces the old image-baked `compute/mu`
    copy, so refreshing the pool no longer needs an image rebuild. Pass `--preds`
    to override (parity with backfill_nodal/score/rerank).
    """
    return str(RUNS_ROOT / run_id / "mu" / "mu_preds.npz")

DEFAULT_ARMS = ("lag", "geo", "wx")      # the shipped `all` config (FEATURE_SETS)

# `run_id` names the MODEL VERSION, not the day (spec §4). Each daily run appends a
# new `delivery_date` under the same `run_id`; the `forecast_current` pointer only
# moves when the model *config* changes (arms, retune, RTC+B re-fit). Bump `run_id`
# on any change that would make two days' forecasts non-comparable — that is what
# keeps the whole forward track one queryable id and the scoreboard from splicing
# two different models. A re-run of a day under an unchanged `run_id` is an
# idempotent replace, and the pointer does not move.


@dataclass
class ForecastResult:
    """One delivery day's forecast, held in memory (nothing written yet).

    `panel` is the nodal P10/P50/P90 + point over D's 24 UTC hours; `SF`/`E_mu` are
    the day's fitted SF map and μ head that `sf_mu` serializes (panel spec §4a).
    `novelty`/`novel_keys` ride along for the run summary — constraints enforced in
    D−1's data that the fit universe never saw bind (spec §7); they are surfaced,
    not fatal.
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


def _as_utc_day(D) -> pd.Timestamp:
    """Normalize any date-ish `D` to a tz-aware UTC midnight — the day boundary the
    whole pipeline slices on (`refit_boundaries`/`predict_day` normalize the same
    way). Rejects a non-midnight instant so a caller can't silently forecast a
    24-hour block offset from the UTC day."""
    ts = pd.Timestamp(D)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts != ts.normalize():
        raise ValueError(f"delivery day must be a UTC midnight boundary, got {ts}")
    return ts.normalize()


def _assert_freshest_history_published(conn, D: pd.Timestamp) -> None:
    """Fail loud if delivery day D−1 has no `ercot_dam_shadow_prices` rows yet.

    The horizon-2 (preview) tick fires the same afternoon T+1's DAM is due (~13:30
    CT); the fit's freshest history day is D−1 (= T+1). A late ERCOT post would let
    the fit run with that day silently missing — a quietly degraded forecast. So
    before the fit, assert D−1's DAM has published (spec §8 pattern: fail, write
    nothing, prior rows intact). D−1's 24 UTC hours are `[D − 1 day, D)`.
    """
    lo = D - pd.Timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(interval_ts) FROM ercot_dam_shadow_prices "
            "WHERE interval_ts >= %s AND interval_ts < %s", (lo, D))
        ts_max = cur.fetchone()[0]
    # Not merely "any row": D−1's UTC window always catches the ~5h tail of the op-day
    # before it, so a bare existence check false-passes when T+1's own DAM has not yet
    # landed (0127). Require the shadow prices to actually span D−1's window.
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
    n_draws: int = N_DRAWS,
    preds_path: str | None = None,
    map_run_id: str = MAP_RUN_ID,
    max_sf_age_days: int = MAX_SF_AGE_DAYS,
    min_sf_coverage: float = MIN_SF_COVERAGE,
) -> ForecastResult:
    """Fit the heads on the trailing window and forecast UTC delivery day D.

    Two stages (spec §3), reusing the validated fit path and the shared window
    propagator:

      1. **μ inference** — `build_panel` at the DAM-close vintage over
         `[D−train_days, D+1)`; `predict_day(panel, D)` fits both heads on the
         trailing window and predicts D's 24 hours (`wp`: `p_bind`, `mu_gbm`).
      2. **propagation** — load the weekly map's persisted SF (run `map_run_id`) via
         `load_forecast_sf` and draw the nodal panel through it with
         `propagate_window` in forward mode (no realized `Y`, hours from D's UTC
         calendar). No per-day SF refit (0095-0002): the map fits this SF weekly, it
         is stationary within the refit interval, and the loader guards freshness /
         coverage and fails loud (prior pointer intact) on a stale, missing, or
         low-coverage map. The residual pool is the validated backtest's OOS errors,
         strictly before D.

    Reads only; writes nothing and does not touch the pointer (the next commit adds
    persistence). Every read — `M`/`C` end at D exclusive, and the SF window is
    causal (`window_end ≤ D`) — sees only intervals < D (spec §5 — the honest path).
    """
    D = _as_utc_day(D)
    # Horizon-2 (preview) fires while D−1's DAM is still landing; gate before the fit
    # so a late ERCOT post fails loud rather than fitting on a missing freshest day
    # (0123). Horizon 1 fires two hours after D−1 closed — no gate needed.
    if horizon == 2:
        _assert_freshest_history_published(conn, D)
    preds_path = preds_path or preds_path_for(run_id)
    # Reproducing the validated model means reproducing how it built its TRAIN rows.
    # The geo/wx arms fit a per-boundary SF/weather-response on
    # `[boundary − WINDOW_DAYS, boundary)`; the boundary covering the earliest train
    # day (`D − train_days`) sits up to `REFIT_DAYS` before it, so its fit window
    # reaches back `train_days + WINDOW_DAYS + REFIT_DAYS`. All of the shadow prices,
    # congestion, AND the system/weather panel (`build_panel` loads the last from its
    # `start`) must span that whole depth — anything shallower leaves the early train
    # margin with NaN geo/weather and short candidate history, the heads fit on
    # different features, and the forward forecast silently diverges from the model
    # the backtest validated (the reconciliation test, spec §9, pins this). The
    # `predict_day` train window is still `[D − train_days, D)`; the earlier panel
    # rows are built only to give the arms their history and are then sliced off.
    read_start = D - pd.Timedelta(days=train_days + WINDOW_DAYS + REFIT_DAYS)
    log.info("forecast_day %s  run_id=%s  horizon=%d  arms=%s  train_days=%d  preds=%s",
             D.date(), run_id, horizon, ",".join(arms), train_days, preds_path)

    # --- stage 1: μ inference ------------------------------------------------
    # M and C end at D (exclusive): the SF fit window and every covariate see only
    # intervals < D. `score_from=D` phase-locks the geo/wx refit grid so D is itself
    # a boundary — the arm SF for D closes at D, matching the propagation SF below.
    try:
        M = load_shadow_prices(conn, read_start, D)
        C = load_congestion_panel(conn, read_start, D) if "geo" in arms else None
        panel = build_panel(conn, M, read_start, D + pd.Timedelta(days=1),
                            C=C, score_from=D,
                            with_weather="wx" in arms,
                            with_outage="outage" in arms)
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
    # `build_panel` needed the deep read-margin `[read_start, D − train_days)` only
    # to give the geo/wx arms their per-boundary fit history; `predict_day` trains on
    # `[D − train_days, D)` and never reads an earlier row (its `searchsorted` skips
    # them). But they stay resident in the wide panel — ~2× the rows we use — and
    # coexist with the ~3.3 GB float64 fold matrix in `_predict_fold`, the walk's
    # peak-memory step, which tips a 16 GB node over. Drop them now; the fold fit and
    # `wp` are byte-identical (those rows were already outside every window it reads).
    keep_from = D - pd.Timedelta(days=train_days)
    panel = panel.loc[panel.index.get_level_values("interval_ts") >= keep_from]
    gc.collect()

    # The daily refit trains on the same 240-day window the backtest's late folds do,
    # so `_predict_fold`'s ~3.4 GB float64 bind matrix is the same peak-memory line —
    # in anonymous RAM it coexists with the resident panel and OOMs a 16 GB node (the
    # exact break the backtest's spill fixed but the serving path never inherited).
    # Spill it to disk always: MU_SPILL_DIR when set, else the system temp dir, which
    # is always writable. Values are bit-identical (every cell is filled), so the
    # forward forecast the reconciliation test pins is unchanged — only where the
    # matrix lives moves. The larger resident-panel spill stays opt-in (MU_SPILL_PANEL)
    # since it pays a one-time pyarrow copy; enable it when the bind spill alone leaves
    # too little headroom.
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

    # Load the weekly map's persisted SF instead of refitting it here (0095-0002).
    # Causal (window_end ≤ D) and guarded: a stale / missing / low-coverage map
    # raises, and no write has happened yet, so the prior pointer stays intact.
    SF_map = load_forecast_sf(conn, D, wp, run_id=map_run_id,
                              max_age_days=max_sf_age_days,
                              min_coverage=min_sf_coverage)
    # Pin the SF vintage in the result for the run log: a preview-vs-final diff for a
    # day is only clean if BOTH runs projected through the same weekly map window —
    # if a weekly refit landed between them the diff also carries a map change (0123).
    sf_win = resolve_sf_window(conn, map_run_id, as_of=D)
    sf_window_end = sf_win[1].date() if sf_win is not None else None

    # Stage 2 needs only `wp` and the loaded `SF_map` — never the feature `panel`,
    # and no longer M/C for an SF fit. In one
    # process `forecast_day` still holds the wide feature panel that built `wp`;
    # free it before propagation so the peak doesn't sum. With the SF now loaded
    # (not fit), M/C no longer feed an SF solve — they're kept only so
    # `propagate_window`'s forward-mode bookkeeping (`M_score`, empty for D) has a
    # frame — so trim them to the recent tail to bound memory.
    del panel
    fit_lo = D - pd.Timedelta(days=WINDOW_DAYS)
    M = M.loc[M.index >= fit_lo]
    if C is not None:
        C = C.loc[C.index >= fit_lo]
    gc.collect()

    # --- stage 2: propagation ------------------------------------------------
    rng = np.random.default_rng(seed)
    preds = load_preds(preds_path)
    eps = residual_pool(preds[preds["week"] < D], rng=rng)      # OOS, strictly < D

    # A UTC day is always 24 hours (no DST in UTC). These are D's score-block hours.
    forward_hours = pd.date_range(D, periods=24, freq="h", tz="UTC")
    _, panel_out, SF, E_mu = propagate_window(     # forward mode → no metrics row
        s=D, end=D + pd.Timedelta(days=1), M=M, C=C, wp=wp, eps=eps,
        n_draws=n_draws, rng=rng, sf=SF_map,
        want_panel=True, want_sf_mu=True, forward_hours=forward_hours)
    if panel_out is None:
        raise RuntimeError(f"propagation produced no panel for {D.date()} — the "
                           f"loaded SF map projected nothing (spec §8: fail loudly)")
    log.info("stage 2: SF %dx%d, panel %d hours x %d SPs",
             SF.shape[0], SF.shape[1], len(panel_out.ts),
             len(panel_out.settlement_points))

    # Degenerate μ head → an all-zero (flat) panel. The backtest scorer already
    # declines flat rows; forward, there is nothing downstream to catch it, so
    # assert non-flat before this becomes a publishable result (spec §8).
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
    """Land one day's forecast and flip this feature's own pointer **last** (§6).

    Order is the contract: `forecast_nodal` rows, then the `forecast_sf_artifact`
    blob, then `upsert_pointer(forecast_current[layer])`, then one `commit()`. The
    commit is the atomic publish — under MVCC a reader resolving the pointer sees
    the whole day or none of it, never a half-written panel; and any failure before
    the commit rolls the transaction back, leaving the **prior pointer intact** with
    no degraded day written (spec §8).

    Idempotent per `(run_id, delivery_date, horizon)`: `nodal_to_db`/
    `persist_sf_mu_artifact` both replace-in-place scoped to the UTC delivery date and
    horizon, so a re-run of D under the same `run_id` overwrites only that horizon's
    rows and blob — a horizon-1 (final) publish never touches the preserved horizon-2
    (preview) rows and vice versa (0123) — and leaves the pointer where it is.
    `npz_dir` (optional) is the on-disk artifact of record (spec §5c) — the nodal and
    SF+μ npz land there too, byte-identical to the DB, each tagged with an `h{horizon}`
    suffix so the two tracks never share a filename; omitted, only the DB is written (a
    throwaway temp file carries the nodal panel into `COPY`). `layer`
    defaults to the served `ercot` pointer; a test overrides it to a scratch layer so
    it never touches the live one. Returns rows written.
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
    """`tomorrow` → the CT day `horizon` days ahead; else parse `YYYY-MM-DD` as a UTC
    day. Both go through `_as_utc_day`, so the CLI and the daily cron share one code
    path.

    `tomorrow` means what an operator standing in Texas means: horizon 1 (final) is
    the CT calendar date after today's (T+1, the classic next day); horizon 2
    (preview) is two CT days out (T+2 — the run lands inside D's decision window,
    before D's DAM closes). Both are the UTC-day *label* the rest of the pipeline
    slices on. Resolving off the UTC clock instead is a live footgun — after 19:00 CT
    (18:00 CST) the UTC date has already rolled, so an evening hand-run silently
    resolved a day late and skipped one entirely (a real prod hole on 2026-07-27). An
    explicit `YYYY-MM-DD` names the day directly and ignores horizon. The CT date is
    normalized *before* the offset is added, so the arithmetic is naive and a
    23-/25-hour DST day cannot shift the answer.
    """
    if spec == "tomorrow":
        now = now if now is not None else pd.Timestamp.now(tz="UTC")
        today_ct = now.tz_convert(ERCOT_TZ).normalize().tz_localize(None)
        return _as_utc_day(today_ct + pd.Timedelta(days=horizon))
    return _as_utc_day(spec)


def _ct_span(D: pd.Timestamp) -> str:
    """`D`'s 24 UTC delivery hours rendered as their CT wall-clock span.

    The delivery day is a UTC calendar day, so in CT it runs 19:00 → 18:00 (CDT) /
    18:00 → 17:00 (CST) — not midnight to midnight. Logging the span alongside the
    date makes an off-by-one day self-evident in the run log instead of something
    you discover by scrubbing onto a hole.
    """
    lo = D.tz_convert(ERCOT_TZ)
    hi = (D + pd.Timedelta(hours=23)).tz_convert(ERCOT_TZ)
    return f"CT {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M} {hi:%Z}"


def _day_already_published(conn, run_id: str, D: pd.Timestamp,
                           horizon: int = 1) -> bool:
    """True when `(run_id, delivery_date, horizon)` already has rows in
    `forecast_nodal`.

    Scoped to horizon (0123) so the check is per-track: the preview's existence must
    never block the final run for the same day and vice versa — they publish side by
    side. The write is a replace-in-place, so a re-run overwrites a published day with
    no confirmation. Cheap enough to check before the fit, so an unintended re-run
    costs a query instead of 20 minutes and a clobbered panel.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM forecast_nodal WHERE run_id = %s AND delivery_date = %s "
            "AND horizon = %s LIMIT 1", (run_id, D.date(), horizon))
        return cur.fetchone() is not None


def _summary(result: ForecastResult) -> str:
    """The run-log coverage/novelty line (spec §7): what the day covered and what it
    could not. A sudden coverage drop is an ingest problem surfacing, not silent
    skill loss — so it is reported every run, not buried."""
    seen = result.n_scored_keys
    cov = seen / (seen + result.novelty) if (seen + result.novelty) else float("nan")
    sample = ", ".join(result.novel_keys[:5])
    # map_run_id + SF window pin the geography vintage: a preview(h2)-vs-final(h1) diff
    # for a day is only a clean covariate-vintage delta if BOTH projected through the
    # same weekly map window (0123).
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

    Horizon-scoped (0123): the h2 tick grades the h2 track and the h1 tick the h1
    track, two independent scoreboards — a day the preview already graded does not
    stop the final from grading it and vice versa.

    Non-fatal by contract. The forecast has already been published and committed by
    the time this runs, so a grading failure must NOT fail the publish or move the
    pointer — it logs and the transaction rolls back. The next tick retries on its
    own: `grade_day` is idempotent and `resolve_gradeable_date` self-selects the
    latest still-ungraded day, so a transient miss heals without any retry logic.
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


def _brief_latest(conn, run_id: str, published: "pd.Timestamp", horizon: int,
                  graded: "pd.Timestamp | None" = None) -> None:
    """Build the Analysis brief in the same tick, on THIS horizon's track (0124).

    Two upserts into ``analysis_brief`` (keyed run_id, delivery_date, horizon — the
    same scope as the artifact and the scoreboard, so the h1 and h2 tracks are
    independent and neither clobbers the other):

      * ``published`` — the day this tick just forecast: the forward, forecast-basis
        brief the Analysis home serves for the coming day (no after-action yet);
      * ``graded`` — the realized day ``_grade_latest`` just graded: re-briefed so F6
        after-action fills now that its DAM has landed (the same "re-run in the
        grading tick" pattern as grade_day; the upsert makes it idempotent).

    Non-fatal by contract, exactly like ``_grade_latest``: the forecast is already
    published and committed, so a brief failure must not fail the publish or move
    the pointer. Each day is its own transaction, so one failing can't sink the
    other, and the next tick re-runs both (a no-op refresh when nothing changed).
    """
    days = [published]
    if graded is not None and graded.date() != published.date():
        days.append(graded)
    for D in days:
        try:
            brief = compute_brief(conn, run_id, D.date(), horizon)
            persist_brief(conn, run_id, D.date(), horizon, brief)
            conn.commit()
            log.info("brief: analysis_brief <- %s (run_id=%s horizon=%d)",
                     D.date(), run_id, horizon)
        except Exception:
            conn.rollback()
            log.exception("brief step failed for %s (non-fatal; forecast already "
                          "published for this tick)", D.date())


def _forecast_history_latest(conn, run_id: str, published: "pd.Timestamp",
                             horizon: int) -> None:
    """Append the just-published day's queryable forecast history, fail-soft.

    This runs only after ``persist_forecast`` has committed the artifact and
    pointer.  Rollup failure therefore cannot retract or poison a published
    forecast; the idempotent backfill job repairs any skipped day.
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
                        "path; names the UTC day label directly)")
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
    p.add_argument("--draws", type=int, default=N_DRAWS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--npz-dir", default=None,
                   help="also write the nodal + SF+mu npz here (disk of record, "
                        "spec §5c); DB-only when omitted")
    p.add_argument("--map-run-id", default=MAP_RUN_ID,
                   help=f"weekly SF-map run to project through (default "
                        f"{MAP_RUN_ID!r}); the forecast reads its persisted SF "
                        f"instead of refitting (0095-0002)")
    p.add_argument("--preds", default=None,
                   help="μ residual-pool npz (the OOS error pool for the P10/P90 "
                        "bands); defaults to runs/<run-id>/mu/mu_preds.npz on the "
                        "runs PVC")
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
    p.add_argument("--no-brief", action="store_true",
                   help="skip the Analysis brief step that normally follows a "
                        "--to-db publish (0124). The tick briefs the day it just "
                        "published on this horizon track, and re-briefs the day it "
                        "just graded to fill after-action; both are non-fatal")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    D = _resolve_delivery_date(args.delivery_date, horizon=args.horizon)
    log.info("delivery_date=%s (%s) from --delivery-date %s (horizon %d)",
             D.date(), _ct_span(D), args.delivery_date, args.horizon)
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
                              seed=args.seed, n_draws=args.draws,
                              preds_path=args.preds,
                              map_run_id=args.map_run_id,
                              max_sf_age_days=args.max_sf_age_days,
                              min_sf_coverage=args.min_sf_coverage)
        log.info(_summary(result))
        if args.to_db:
            persist_forecast(conn, result, npz_dir=args.npz_dir)
            # Grade the most recent realized served day in the same tick. Free the
            # fit's working set first so the two peaks don't sum on a 16Gi node.
            del result
            gc.collect()
            graded = None
            if not args.no_grade:
                graded = _grade_latest(conn, args.run_id, args.horizon)
            _forecast_history_latest(conn, args.run_id, D, args.horizon)
            # Brief in the same tick (0124): the forward brief for the day just
            # published on this horizon track, plus an after-action re-brief of the
            # day grade_latest just realized. Non-fatal, so it never sinks a publish.
            if not args.no_brief:
                _brief_latest(conn, args.run_id, D, args.horizon, graded=graded)
        else:
            log.info("dry run (--to-db not set): nothing written, pointer unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
