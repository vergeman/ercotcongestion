"""Tests for the `forecast_day` production job (plan 0013).

Two layers:

* **Always-on, deterministic** — the merge-blocking honesty guarantees and the
  fail-loud failure modes, exercised by stubbing the heavy fit/propagate seams so
  they run in milliseconds. The leakage guarantee (spec §5) is proven *structurally*
  here: `forecast_day` reads shadow prices / congestion with `end == D` (exclusive),
  hands propagation an `M` with no interval ≥ D, propagates `s == D`, and scores
  exactly D's 24 UTC hours. If any of those regressed, the day would read the future.
* **Gated integration** (`FORECAST_DAY_SLOW=1`) — the backtest reconciliation (spec
  §9), proven against the live DB *in process*: for a historic D, the SF map and the
  deterministic nodal `point` that `forecast_day`'s forward-mode propagation produces
  are byte-identical to what the validated backtest-mode propagation produces on the
  same `wp`/`M`/`C`. This pins exactly the code this branch added (`propagate_window`'s
  `forward_hours` branch) without depending on a bundled `mu_nodal.npz` reference,
  which goes stale the moment the model or the DB moves. ~5 min, so it is opt-in.
"""
from __future__ import annotations

import os
import uuid

import numpy as np
import pandas as pd
import pytest

import compute.jobs.daily_forecast as fd
from compute.jobs.daily_forecast import ForecastResult, forecast_day, persist_forecast
from compute.mu.score import REFIT_DAYS, WINDOW_DAYS
from compute.sf.project import NodalPanel, build_sf_mu_artifact, load_sf_mu

D = pd.Timestamp("2025-09-15", tz="UTC")      # an arbitrary UTC-midnight delivery day


# ----------------------------------------------------------------------------
# Stubbing the seams: build_panel / predict_day / propagate_window / loaders are
# replaced with lightweight recorders so `forecast_day`'s ORCHESTRATION (read
# windows, forward hours, guards) is tested without a 10-minute fit.
# ----------------------------------------------------------------------------

def _install_fakes(monkeypatch, *, novel=0, wp_rows=24, point_value=3.0,
                   build_raises=False, build_empty=False, panel_none=False):
    """Patch every external seam of `forecast_day`; return a dict the stubs write
    their observed call arguments into."""
    seen: dict = {}
    # M/C indexed strictly before D — what an `end == D` read returns.
    idx = pd.date_range(D - pd.Timedelta(days=10), periods=100, freq="h", tz="UTC")
    M_stub = pd.DataFrame({"K0|c": np.ones(len(idx), "f4")}, index=idx)
    C_stub = pd.DataFrame({"SP0": np.zeros(len(idx), "f4")}, index=idx)

    def fake_load_sp(conn, start, end):
        seen["sp_window"] = (start, end)
        return M_stub

    def fake_load_cong(conn, start, end):
        seen["cong_window"] = (start, end)
        return C_stub

    def fake_build_panel(conn, M, start, end, **kw):
        seen["panel_window"] = (start, end)
        seen["score_from"] = kw.get("score_from")
        if build_raises:
            raise ValueError("simulated loader failure")
        return pd.DataFrame() if build_empty else pd.DataFrame({"x": [1, 2, 3]})

    def fake_predict_day(panel, D_, *, train_days, arms, seed):
        hours = pd.date_range(D_, periods=24, freq="h", tz="UTC")
        if wp_rows == 0:
            wp = pd.DataFrame(columns=["interval_ts", "key", "p_bind", "mu_gbm"])
        else:
            wp = pd.DataFrame({"interval_ts": hours, "key": "K0|c",
                               "p_bind": 0.5, "mu_gbm": 10.0})
        wp.attrs["novelty"] = novel
        wp.attrs["novel_keys"] = [f"N{i}|c" for i in range(novel)]
        return wp

    def fake_load_preds(path):
        return pd.DataFrame({"week": [D - pd.Timedelta(days=7)],
                             "y_bind": [1], "y_mu": [5.0], "mu_gbm": [4.0]})

    def fake_propagate(s, end, M, C, wp, eps, n_draws, rng, **kw):
        seen["prop_s"] = s
        seen["prop_end"] = end
        seen["prop_M_max"] = None if M is None or M.empty else M.index.max()
        seen["forward_hours"] = kw["forward_hours"]
        fh = kw["forward_hours"]
        H = len(fh)
        pt = np.full((H, 1), point_value, "f4")
        panel = NodalPanel(ts=fh.to_numpy(), settlement_points=np.array(["SP0"]),
                           p10=pt - 1, p50=pt, p90=pt + 1, point=pt, sf_r2=None)
        SF = pd.DataFrame([[1.0]], index=["K0|c"], columns=["SP0"]).astype("f4")
        E_mu = pd.DataFrame(np.ones((H, 1), "f4"), index=fh, columns=["K0|c"])
        return (None, None if panel_none else panel, SF, E_mu)

    monkeypatch.setattr(fd, "load_shadow_prices", fake_load_sp)
    monkeypatch.setattr(fd, "load_congestion_panel", fake_load_cong)
    monkeypatch.setattr(fd, "build_panel", fake_build_panel)
    monkeypatch.setattr(fd, "predict_day", fake_predict_day)
    monkeypatch.setattr(fd, "load_preds", fake_load_preds)
    monkeypatch.setattr(fd, "propagate_window", fake_propagate)
    return seen


# ----------------------------------------------------------------------------
# Leakage / honesty (spec §5) — the merge blocker, deterministic
# ----------------------------------------------------------------------------

def test_reads_and_propagation_touch_no_interval_at_or_after_D(monkeypatch):
    """The honest path never reads an interval ≥ D. Shadow prices and congestion
    are loaded with `end == D` (exclusive); the `M` propagation fits its SF on has
    no row ≥ D; propagation runs `s == D`. This is the production `audit_leakage`
    (spec §5): pushing any of these to include D would be the leak."""
    seen = _install_fakes(monkeypatch)
    forecast_day(None, D, run_id="t", train_days=240)

    depth = pd.Timedelta(days=240 + WINDOW_DAYS + REFIT_DAYS)
    assert seen["sp_window"][1] == D              # shadow prices: [.., D)
    assert seen["cong_window"][1] == D            # congestion:    [.., D)
    # Reads (and the panel build, which loads the system/weather panel) reach back
    # train_days + WINDOW_DAYS + REFIT_DAYS so the earliest train boundary's SF /
    # weather-response fit has its full window (still all < D — honest).
    assert seen["sp_window"][0] == D - depth
    assert seen["cong_window"][0] == D - depth
    assert seen["panel_window"][0] == D - depth
    assert seen["prop_s"] == D                    # SF fit closes at D
    assert seen["prop_M_max"] < D                 # nothing ≥ D reaches the fit
    # D's forecast hours are the score block; those reads are DAM-close-vintage-
    # pinned in features.py, and no shadow-price/congestion read crossed D above.
    assert seen["panel_window"][1] == D + pd.Timedelta(days=1)


def test_score_block_is_exactly_Ds_utc_day(monkeypatch):
    """Forward hours are D's 24 UTC hours (a UTC day has no DST fold), and the
    propagation window is [D, D+1) — the score block, not a 7-day backtest week."""
    seen = _install_fakes(monkeypatch)
    forecast_day(None, D, run_id="t")

    fh = seen["forward_hours"]
    assert len(fh) == 24
    assert list(fh) == list(pd.date_range(D, periods=24, freq="h", tz="UTC"))
    assert seen["prop_end"] == D + pd.Timedelta(days=1)


def test_delivery_day_must_be_utc_midnight(monkeypatch):
    """A non-midnight instant is rejected rather than silently forecasting a block
    offset from the UTC day."""
    _install_fakes(monkeypatch)
    with pytest.raises(ValueError, match="UTC midnight"):
        forecast_day(None, pd.Timestamp("2025-09-15 05:00", tz="UTC"), run_id="t")


def test_delivery_date_and_result_are_utc(monkeypatch):
    _install_fakes(monkeypatch)
    r = forecast_day(None, "2025-09-15", run_id="mu-all-v1")
    assert r.delivery_date == D.date()
    assert len(r.panel.ts) == 24
    assert r.run_id == "mu-all-v1"


# ----------------------------------------------------------------------------
# Novelty & failure modes (spec §8) — fail loud, keep the prior pointer
# ----------------------------------------------------------------------------

def test_novelty_is_surfaced_not_fatal(monkeypatch):
    """Novel constraints (enforced D−1, no fit history) ride on the result and are
    counted — not an error, as long as something is coverable."""
    _install_fakes(monkeypatch, novel=7)
    r = forecast_day(None, D, run_id="t")
    assert r.novelty == 7
    assert len(r.novel_keys) == 7


def test_all_novel_day_fails_loudly(monkeypatch):
    """A day with no scorable constraint (empty `wp`) has no map — refuse it."""
    _install_fakes(monkeypatch, wp_rows=0, novel=3)
    with pytest.raises(RuntimeError, match="no scorable constraints"):
        forecast_day(None, D, run_id="t")


def test_missing_vintage_build_failure_fails_loudly(monkeypatch):
    """Any failure assembling inputs is fatal and chains the root cause — the job
    fails rather than emitting a degraded forecast (pointer untouched: no write
    happens on this path)."""
    _install_fakes(monkeypatch, build_raises=True)
    with pytest.raises(RuntimeError, match="failed to build the feature panel") as ei:
        forecast_day(None, D, run_id="t")
    assert isinstance(ei.value.__cause__, ValueError)


def test_empty_panel_fails_loudly(monkeypatch):
    _install_fakes(monkeypatch, build_empty=True)
    with pytest.raises(RuntimeError, match="empty feature panel"):
        forecast_day(None, D, run_id="t")


def test_degenerate_all_zero_mu_fails_loudly(monkeypatch):
    """An all-zero (flat) panel means the μ head collapsed — assert non-flat before
    it can be published (spec §8)."""
    _install_fakes(monkeypatch, point_value=0.0)
    with pytest.raises(RuntimeError, match="degenerate all-zero"):
        forecast_day(None, D, run_id="t")


def test_empty_propagation_panel_fails_loudly(monkeypatch):
    """No SF fit window / empty SF map → no panel → refuse (the map is the product)."""
    _install_fakes(monkeypatch, panel_none=True)
    with pytest.raises(RuntimeError, match="propagation produced no panel"):
        forecast_day(None, D, run_id="t")


# ----------------------------------------------------------------------------
# Persist: idempotency + atomicity (spec §6, §9) — real Postgres, scratch layer
# ----------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS forecast_nodal (
  run_id text NOT NULL, delivery_date date NOT NULL, ts timestamptz NOT NULL,
  settlement_point text NOT NULL, p10 real, p50 real, p90 real, point real,
  PRIMARY KEY (run_id, ts, settlement_point));
CREATE TABLE IF NOT EXISTS forecast_current (
  layer text PRIMARY KEY, run_id text NOT NULL,
  promoted_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS forecast_sf_artifact (
  run_id text NOT NULL, delivery_date date NOT NULL, sf_npz bytea NOT NULL,
  PRIMARY KEY (run_id, delivery_date));
"""


@pytest.fixture
def pg():
    """Connection + a scratch (run_id, layer) namespace, torn down after. Skips
    unless Postgres is reachable, so a host-only `pytest` stays green. The scratch
    `layer` keeps the test off the served `ercot` pointer entirely."""
    psycopg = pytest.importorskip("psycopg")
    try:
        dsn = (f"host={os.environ['PG_HOST']} "
               f"dbname={os.environ.get('PG_DB', 'ercot')} "
               f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
    except KeyError:
        pytest.skip("no PG_* env — DB tests run in the compute container only")
    try:
        conn = psycopg.connect(dsn, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres unreachable: {e}")

    run_id = f"zz-test-{uuid.uuid4().hex[:12]}"
    layer = f"zz-test-{uuid.uuid4().hex[:8]}"
    with conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_DDL)
        conn.commit()
        try:
            yield conn, run_id, layer
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM forecast_nodal WHERE run_id=%s", (run_id,))
                cur.execute("DELETE FROM forecast_current WHERE layer=%s", (layer,))
                cur.execute("DELETE FROM forecast_sf_artifact WHERE run_id=%s",
                            (run_id,))
            conn.commit()


def _synthetic_result(run_id, day=D, point_value=2.5):
    ts = pd.date_range(day, periods=24, freq="h", tz="UTC")
    sps = np.array(["SP_A", "SP_B", "SP_C"])
    keys = ["K1|c", "K2|c"]
    rng = np.random.default_rng(0)
    p50 = rng.random((24, 3)).astype("f4") + point_value
    panel = NodalPanel(ts=ts.to_numpy(), settlement_points=sps,
                       p10=(p50 - 0.5).astype("f4"), p50=p50,
                       p90=(p50 + 0.5).astype("f4"),
                       point=(p50 * 1.1).astype("f4"), sf_r2=None)
    SF = pd.DataFrame(rng.random((2, 3)).astype("f4"), index=keys, columns=sps)
    E_mu = pd.DataFrame(rng.random((24, 2)).astype("f4"), index=ts, columns=keys)
    return ForecastResult(run_id=run_id, delivery_date=day.date(), panel=panel,
                          SF=SF, E_mu=E_mu, sf_mu=build_sf_mu_artifact(SF, E_mu))


def _count(conn, run_id):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forecast_nodal WHERE run_id=%s", (run_id,))
        return int(cur.fetchone()[0])


def test_persist_is_idempotent_and_flips_pointer_last(pg):
    """Publishing D twice yields identical rows and one SF blob (replace, not
    append); the pointer is one row and names the run; all 24 hours carry one UTC
    `delivery_date`."""
    conn, run_id, layer = pg
    res = _synthetic_result(run_id)

    n1 = persist_forecast(conn, res, layer=layer)
    n2 = persist_forecast(conn, res, layer=layer)          # idempotent re-run
    assert n1 == n2 == 24 * 3
    assert _count(conn, run_id) == 24 * 3                   # replaced, not doubled

    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT delivery_date) FROM forecast_nodal "
                    "WHERE run_id=%s", (run_id,))
        assert int(cur.fetchone()[0]) == 1                 # one UTC delivery_date
        cur.execute("SELECT delivery_date FROM forecast_nodal WHERE run_id=%s "
                    "LIMIT 1", (run_id,))
        assert cur.fetchone()[0] == D.date()
        cur.execute("SELECT count(*) FROM forecast_sf_artifact WHERE run_id=%s",
                    (run_id,))
        assert int(cur.fetchone()[0]) == 1                 # one blob, replaced
        cur.execute("SELECT count(*), max(run_id) FROM forecast_current "
                    "WHERE layer=%s", (layer,))
        n_ptr, ptr = cur.fetchone()
        assert n_ptr == 1 and ptr == run_id                # pointer: one row, our run


def test_pointer_flips_only_after_rows_land(pg):
    """The pointer is written in the same transaction as the rows and committed
    once, so a reader resolving the pointer→run_id always finds the rows there
    (never a pointer ahead of a half-written panel)."""
    conn, run_id, layer = pg
    persist_forecast(conn, _synthetic_result(run_id), layer=layer)
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM forecast_current WHERE layer=%s", (layer,))
        pointed = cur.fetchone()[0]
    assert _count(conn, pointed) == 24 * 3                 # pointed run has its rows


def test_sf_blob_round_trips_from_db(pg):
    conn, run_id, layer = pg
    res = _synthetic_result(run_id)
    persist_forecast(conn, res, layer=layer)
    with conn.cursor() as cur:
        cur.execute("SELECT sf_npz FROM forecast_sf_artifact WHERE run_id=%s",
                    (run_id,))
        blob = bytes(cur.fetchone()[0])
    art = load_sf_mu(blob)
    np.testing.assert_allclose(art.SF.to_numpy(), res.SF.to_numpy(), rtol=1e-6)
    assert list(art.SF.index) == list(res.SF.index)


# ----------------------------------------------------------------------------
# Backtest reconciliation (spec §9) — gated: a real ~5-min in-process run
# ----------------------------------------------------------------------------

_SLOW = os.environ.get("FORECAST_DAY_SLOW") == "1"
slow = pytest.mark.skipif(
    not _SLOW,
    reason="set FORECAST_DAY_SLOW=1 to run the full-pipeline forecast_day "
           "integration test (~5 min, needs the live DB)")


def _panel_point_frame(panel: NodalPanel, tag: str = "point") -> pd.DataFrame:
    """Flatten a `NodalPanel`'s (H, N) deterministic `point` grid to tidy
    (ts, settlement_point, <tag>) rows for a join across the two modes."""
    H, N = panel.point.shape
    ts = pd.to_datetime(panel.ts, utc=True)
    return pd.DataFrame({
        "ts": np.repeat(ts.to_numpy(), N),
        "settlement_point": np.tile(panel.settlement_points, H),
        tag: panel.point.ravel().astype(np.float64),
    })


@slow
def test_forward_mode_reproduces_backtest_propagation(pg):
    """The decisive reconciliation (spec §9), proven in process: for a historic
    delivery day D, `propagate_window`'s forward branch — the honest path
    `forecast_day` takes (D's 24h calendar, no realized congestion) — must produce
    the SAME SF map and the SAME deterministic nodal `point` (= −E[μ]·SF) as the
    validated backtest branch, when both are handed identical `wp`/`M`/`C`.

    That is exactly what this branch changed: the SF fit, the E_mu build, and the
    `point` tee are shared code; the only new seam is the `forward_hours` branch that
    swaps `M_score ∩ C_score` for D's calendar and skips the realized `Y`. If that
    seam drifted — a cutoff, an hour offset, a node-universe change — forward and
    backtest would disagree on the (ts, node) both score. They must be byte-identical.

    Why not compare to a saved `mu_nodal.npz`: that reference is a function of the
    model VERSION and the DB SNAPSHOT that produced it, so it goes stale on any
    retrain or ingest and can only be refreshed by the full walk. This test is
    self-contained — it fits one delivery day in memory and needs no bundled
    artifact — while pinning the same guarantee for the code this branch owns. The
    unchanged refit path (`predict_day`/heads) is pinned by `mu_model`'s own tests.
    """
    from compute.mu.features import build_panel
    from compute.mu.mu_model import load_preds, predict_day
    from compute.sf.panels import load_congestion_panel, load_shadow_prices
    from compute.sf.project import N_DRAWS, propagate_window, residual_pool

    conn = pg[0]
    preds = load_preds(fd.PREDS_PATH)

    # An interior grid boundary: a full 240d of prior history so the SF map fits.
    weeks = pd.DatetimeIndex(sorted(preds["week"].unique()))
    weeks = weeks[(weeks >= weeks.min() + pd.Timedelta(days=240))
                  & (weeks <= weeks.max() - pd.Timedelta(days=7))]
    assert len(weeks), "no interior scored week to reconcile against"
    Dr = fd._as_utc_day(pd.Timestamp(weeks[len(weeks) // 2]))

    # Build SOME valid wp (data < Dr). Both modes share it, so its provenance is
    # irrelevant to whether they agree; a 240d read window keeps the fit in memory.
    read_start = Dr - pd.Timedelta(days=240)
    M_hon = load_shadow_prices(conn, read_start, Dr)
    C_hon = load_congestion_panel(conn, read_start, Dr)
    panel = build_panel(conn, M_hon, read_start, Dr + pd.Timedelta(days=1),
                        C=C_hon, score_from=Dr, with_weather=True, with_outage=False)
    wp = predict_day(panel, Dr, train_days=240, arms=("lag", "geo", "wx"), seed=0)
    del panel, M_hon, C_hon
    assert len(wp), "no scorable constraints — cannot reconcile"

    # Propagation inputs: the fit window [Dr−WINDOW_DAYS, Dr) plus a REALIZED score
    # block at Dr, so backtest mode has C_score to intersect (forward mode ignores it).
    prop_start = Dr - pd.Timedelta(days=WINDOW_DAYS)
    prop_end = Dr + pd.Timedelta(days=1)
    M = load_shadow_prices(conn, prop_start, prop_end)
    C = load_congestion_panel(conn, prop_start, prop_end)
    eps = residual_pool(preds[preds["week"] < Dr], rng=np.random.default_rng(0))

    # forward mode: hours = D's 24h calendar; no realized Y read.
    fwd_hours = pd.date_range(Dr, periods=24, freq="h", tz="UTC")
    _, p_fwd, SF_f, _ = propagate_window(
        s=Dr, end=prop_end, M=M, C=C, wp=wp, eps=eps,
        n_draws=N_DRAWS, rng=np.random.default_rng(0),
        want_panel=True, want_sf_mu=True, forward_hours=fwd_hours)
    # backtest mode: hours = M_score ∩ C_score over [Dr, Dr+1d); realized Y read.
    _, p_bt, SF_b, _ = propagate_window(
        s=Dr, end=prop_end, M=M, C=C, wp=wp, eps=eps,
        n_draws=N_DRAWS, rng=np.random.default_rng(0),
        want_panel=True, want_sf_mu=True)

    assert p_fwd is not None and p_bt is not None, "a mode produced no panel"
    assert SF_f.index.equals(SF_b.index), "SF constraint set differs across modes"
    assert SF_f.columns.equals(SF_b.columns), "SF node set differs across modes"

    merged = _panel_point_frame(p_fwd, "point_fwd").merge(
        _panel_point_frame(p_bt, "point_bt"), on=["ts", "settlement_point"])
    assert len(merged) > 100, "too few overlapping (ts, sp) to reconcile"
    np.testing.assert_array_equal(merged["point_fwd"].to_numpy(),
                                  merged["point_bt"].to_numpy())
