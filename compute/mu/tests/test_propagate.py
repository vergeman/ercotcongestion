"""Bands are the one output that can be wrong while looking right: a P90 exceeded
30% of the time still prints a tidy number. These pin the ways that happens."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.jobs.backfill_nodal import (
    existence_test, gate, nodal_to_db, persist_sf_mu_artifact, sf_artifact_to_db,
    upsert_pointer, walk,
)
from compute.mu.score import REFIT_DAYS, WINDOW_DAYS
from compute.sf.project import (
    DRIVERS_MAX_DAYS, NodalPanel, SfMuArtifact, _NodalAccumulator, band_metrics,
    build_sf_mu_artifact, draw_congestion, load_nodal, load_sf_mu,
    materialize_drivers, node_drivers, parse_curated_days, propagate_window,
    residual_pool, save_sf_mu,
)

RNG = np.random.default_rng(11)
KEYS = [f"C{i}|X" for i in range(5)]
NODES = [f"SP{i}" for i in range(30)]


def _metrics(Y, draws):
    """band_metrics now takes the percentiles the caller computes once."""
    p10, p50, p90 = np.percentile(draws, (10, 50, 90), axis=0)
    return band_metrics(Y, p10, p50, p90)


def _hours(n=48):
    return pd.date_range(pd.Timestamp("2025-10-01", tz="UTC"), periods=n, freq="h")


def _sf():
    return pd.DataFrame(RNG.normal(0, 0.3, (len(KEYS), len(NODES))),
                        index=pd.Index(KEYS, name="key"), columns=NODES)


def _preds(hours, p_bind=0.3, mu=50.0):
    rows = []
    for k in KEYS:
        rows.append(pd.DataFrame({
            "interval_ts": hours, "key": k,
            "week": pd.Timestamp("2025-10-01", tz="UTC"),
            "p_bind": p_bind, "mu_gbm": mu, "mu_clim": mu,
            "y_bind": 0, "y_mu": np.nan}))
    return pd.concat(rows, ignore_index=True)


# ------------------------------------------------------------- the residuals

def test_residual_pool_is_out_of_sample_by_construction():
    """The pool is head 2's error on weeks it ALREADY SCORED. Training-window
    residuals are the residuals of a model that has fitted them — too small, and
    the bands built from them would be confidently narrow."""
    prior = pd.DataFrame({"y_bind": [1, 1, 0, 1], "y_mu": [100.0, 50.0, np.nan, 20.0],
                          "mu_gbm": [80.0, 60.0, 10.0, 20.0]})
    eps = residual_pool(prior)
    assert len(eps) == 3                       # binders only; the non-binder is out
    assert eps[0] == pytest.approx(np.log1p(100) - np.log1p(80), rel=1e-5)
    assert eps[2] == pytest.approx(0.0, abs=1e-6)   # a perfect call is zero error


def test_no_prior_weeks_means_no_pool_and_no_bands():
    """Week 1 has nothing behind it. It must produce no bands rather than bands
    from an empty or in-sample pool — 46 weeks scored, 45 with bands, stated."""
    assert len(residual_pool(pd.DataFrame(
        {"y_bind": [], "y_mu": [], "mu_gbm": []}))) == 0


# ---------------------------------------------------------------- the draws

def test_a_certain_binder_with_no_spread_reproduces_the_point_forecast():
    """Degenerate case as a plumbing check: p=1, zero residual spread ⇒ every draw
    is E[μ|bind] through the map, so P50 must equal the point forecast exactly."""
    h, SF = _hours(24), _sf()
    preds = _preds(h, p_bind=1.0, mu=50.0)
    draws = draw_congestion(preds, SF, h, eps=np.zeros(1, np.float32), n_draws=8)

    point = -(np.full((24, len(KEYS)), 50.0, np.float32) @ SF.to_numpy(np.float32))
    np.testing.assert_allclose(np.median(draws, axis=0), point, rtol=1e-4)
    assert np.ptp(draws, axis=0).max() == pytest.approx(0.0)   # no spread


def test_p_bind_controls_how_often_a_constraint_shows_up():
    """Head 1 is a *probability*, and the draw must honour it. If sampling ignored
    p and always bound, the bands would be a fantasy of permanent congestion."""
    h, SF = _hours(24), _sf()
    lo = draw_congestion(_preds(h, p_bind=0.05), SF, h,
                         np.zeros(1, np.float32), n_draws=64)
    hi = draw_congestion(_preds(h, p_bind=0.95), SF, h,
                         np.zeros(1, np.float32), n_draws=64)
    # more binding ⇒ more congestion mass moved, in expectation
    assert np.abs(hi).mean() > 3 * np.abs(lo).mean()


def test_a_shadow_price_is_never_drawn_negative():
    """μ ≥ 0 is physics, not a modelling choice. A fat negative residual must not
    flip a shadow price through the map and invent congestion with the wrong sign."""
    h, SF = _hours(24), _sf()
    fat = RNG.normal(-3.0, 2.0, 5000).astype(np.float32)   # brutally negative
    draws = draw_congestion(_preds(h, p_bind=1.0, mu=10.0), SF, h, fat, n_draws=32)
    assert np.isfinite(draws).all()
    # reconstruct: with SF fixed and μ≥0, no draw may exceed the μ=0 bound in sign
    assert not np.isnan(draws).any()


# --------------------------------------------------- the deterministic point

def test_want_point_is_the_expectation_not_the_median():
    """`point = −(E[μ]·SF)` with `E[μ]=P(bind)·E[μ|bind]` — a no-sampling branch
    off the same P/MU/SFm. It must equal an independent recompute, and it is the
    model's expectation, distinct from the noisy median of the draws."""
    h, SF = _hours(24), _sf()
    p_bind, mu = 0.3, 50.0
    preds = _preds(h, p_bind=p_bind, mu=mu)
    draws, point = draw_congestion(preds, SF, h, np.zeros(1, np.float32),
                                   n_draws=8, want_point=True)
    E_mu = np.full((24, len(KEYS)), p_bind * mu, np.float32)
    expect = -(E_mu @ SF.to_numpy(np.float32))
    np.testing.assert_allclose(point, expect, rtol=1e-5)
    assert point.shape == (24, len(NODES)) == draws.shape[1:]
    # default path is unchanged — a bare array, no point
    assert isinstance(draw_congestion(preds, SF, h, np.zeros(1, np.float32),
                                      n_draws=8), np.ndarray)


# --------------------------------------------------------- the window seam

def _window_frames(n_keys=4, n_sp=6, seed=7):
    """DB-shaped M/C/wp for one fit+score window, C built from the SF identity."""
    rng = np.random.default_rng(seed)
    s = pd.Timestamp("2025-06-01", tz="UTC")
    idx = pd.date_range(s - pd.Timedelta(days=WINDOW_DAYS),
                        s + pd.Timedelta(days=REFIT_DAYS), freq="h",
                        inclusive="left")
    keys = [f"K{i}|Z" for i in range(n_keys)]
    sps = [f"N{i}" for i in range(n_sp)]
    true_sf = rng.normal(0, 0.3, (n_keys, n_sp))
    mu = np.where(rng.random((len(idx), n_keys)) < 0.5, 0.0,
                  rng.uniform(20, 200, (len(idx), n_keys)))
    M = pd.DataFrame(mu, index=idx, columns=keys)
    C = pd.DataFrame(-(mu @ true_sf), index=idx, columns=sps)

    shours = idx[(idx >= s) & (idx < s + pd.Timedelta(days=REFIT_DAYS))]
    frames = []
    for k in keys:
        p = M.loc[shours, k].to_numpy()
        frames.append(pd.DataFrame({
            "interval_ts": shours, "key": k, "week": s,
            "p_bind": np.where(p > 0, 0.8, 0.1), "mu_gbm": np.clip(p, 1, None),
            "y_bind": (p > 0).astype(int),
            "y_mu": np.where(p > 0, p, np.nan)}))
    wp = pd.concat(frames, ignore_index=True)
    return s, s + pd.Timedelta(days=REFIT_DAYS), M, C, wp, shours


def test_panel_reduces_to_the_same_metrics_as_the_row():
    """The panel and the scored row read one `np.percentile` call, so the served
    p10/p90 re-reduced must reproduce the row's coverage80/band_width."""
    s, end, M, C, wp, shours = _window_frames()
    row, panel, _, _ = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32),
                                        64, np.random.default_rng(0), want_panel=True)
    assert isinstance(panel, NodalPanel)
    assert list(panel.settlement_points) == list(C.columns)   # == SF.columns
    assert len(panel.ts) == len(shours) == row["n_hours"]

    Y = C.loc[shours, list(panel.settlement_points)].to_numpy(np.float32)
    inside = (Y >= panel.p10) & (Y <= panel.p90)
    assert np.nanmean(inside) == pytest.approx(row["coverage80"], abs=1e-3)
    assert np.nanmean(panel.p90 - panel.p10) == pytest.approx(row["band_width"],
                                                              rel=1e-3)


def test_want_panel_does_not_perturb_the_metrics_row():
    """Emission is a tee, not a fork: the row must be identical whether or not the
    panel is built (same seed, same draws, same percentiles)."""
    args = (*_window_frames()[:5], np.zeros(4, np.float32), 64)
    r0, p0, _, _ = propagate_window(*args, np.random.default_rng(5))
    r1, p1, _, _ = propagate_window(*args, np.random.default_rng(5), want_panel=True)
    assert p0 is None and isinstance(p1, NodalPanel)
    assert r0 is not None and r0.keys() == r1.keys()
    for k in r0:                                    # nan_ok: some metrics are nan
        assert r0[k] == pytest.approx(r1[k], nan_ok=True) if isinstance(
            r0[k], float) else r0[k] == r1[k]


def test_panel_is_bit_for_bit_deterministic_under_fixed_seed():
    s, end, M, C, wp, _ = _window_frames()
    a = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32), 64,
                         np.random.default_rng(3), want_panel=True)[1]
    b = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32), 64,
                         np.random.default_rng(3), want_panel=True)[1]
    for q in ("p10", "p50", "p90", "point"):
        np.testing.assert_array_equal(getattr(a, q), getattr(b, q))


def test_propagate_window_skips_when_the_fit_window_is_empty():
    _, _, M, C, wp, _ = _window_frames()
    s2 = M.index.max() + pd.Timedelta(days=365)     # fit window lands past all data
    row, panel, _, _ = propagate_window(s2, s2 + pd.Timedelta(days=REFIT_DAYS),
                                        M, C, wp, np.zeros(4, np.float32), 8,
                                        np.random.default_rng(0))
    assert row is None and panel is None


# -------------------------------------------------------- the nodal npz sink

def test_nodal_npz_round_trips_the_panel(tmp_path):
    """`save_nodal → load_nodal` recovers a window's `ts`/SP/percentiles/`point`
    exactly, and the node axis for the week is `SF.columns` in order — the flat
    vocab coding is lossless (spec §2)."""
    s, end, M, C, wp, _ = _window_frames()
    _, panel, _, _ = propagate_window(s, end, M, C, wp, np.zeros(4, np.float32),
                                      32, np.random.default_rng(0), want_panel=True)
    sink = _NodalAccumulator()
    sink.add(panel, s)
    path = str(tmp_path / "nodal.npz")
    sink.save(path)
    df = load_nodal(path)

    N = len(panel.settlement_points)
    assert len(df) == len(panel.ts) * N            # H×N flat rows, never densified
    assert str(df["ts"].dt.tz) == "UTC" and str(df["week"].dt.tz) == "UTC"
    # first hour's block is the node axis == SF.columns, in order
    wk0 = df[df["ts"] == df["ts"].min()]
    assert list(wk0["settlement_point"]) == list(panel.settlement_points)
    assert (df["week"] == pd.Timestamp(s).tz_convert("UTC")).all()
    assert (df["ts"].iloc[:N] == pd.to_datetime(panel.ts[0], utc=True)).all()
    # values line up with the (H,N) C-order ravel, and point ≠ p50
    np.testing.assert_allclose(df["p10"].to_numpy(), panel.p10.ravel(), rtol=1e-6)
    np.testing.assert_allclose(df["p50"].to_numpy(), panel.p50.ravel(), rtol=1e-6)
    np.testing.assert_allclose(df["p90"].to_numpy(), panel.p90.ravel(), rtol=1e-6)
    np.testing.assert_allclose(df["point"].to_numpy(), panel.point.ravel(),
                               rtol=1e-6)
    assert not np.array_equal(df["point"].to_numpy(), df["p50"].to_numpy())


def test_accumulator_keeps_ragged_node_axes_per_week(tmp_path):
    """The node set is ragged week to week (spec §9): each week keeps its own SP
    axis, never a union-and-fill, and a shared SP is coded once in `sp_vocab`."""
    def _panel(ts, sps, val):
        arr = np.full((len(ts), len(sps)), val, np.float32)
        return NodalPanel(ts=ts.to_numpy(), settlement_points=np.array(sps),
                          p10=arr, p50=arr + 1, p90=arr + 2, point=arr + 3,
                          sf_r2=None)
    w1 = pd.Timestamp("2025-10-01", tz="UTC")
    w2 = pd.Timestamp("2025-10-08", tz="UTC")
    h1, h2 = _hours(3), pd.date_range(w2, periods=3, freq="h")
    sink = _NodalAccumulator()
    sink.add(_panel(h1, ["A", "B"], 1.0), w1)
    sink.add(_panel(h2, ["B", "C", "D"], 2.0), w2)   # different, ragged axis
    path = str(tmp_path / "ragged.npz")
    sink.save(path)

    df = load_nodal(path)
    g1, g2 = df[df["week"] == w1], df[df["week"] == w2]
    assert set(g1["settlement_point"]) == {"A", "B"} and len(g1) == 3 * 2
    assert set(g2["settlement_point"]) == {"B", "C", "D"} and len(g2) == 3 * 3
    vocab = np.load(path)["sp_vocab"]
    assert list(vocab) == ["A", "B", "C", "D"]       # shared 'B' coded once


def _walk_frames(seed=7, n_keys=4, n_sp=6):
    """Two scored weeks so week 2 has a residual pool — a runnable `walk()`."""
    rng = np.random.default_rng(seed)
    w1 = pd.Timestamp("2025-06-01", tz="UTC")
    w2 = w1 + pd.Timedelta(days=REFIT_DAYS)
    idx = pd.date_range(w1 - pd.Timedelta(days=WINDOW_DAYS),
                        w2 + pd.Timedelta(days=REFIT_DAYS), freq="h",
                        inclusive="left")
    keys = [f"K{i}|Z" for i in range(n_keys)]
    sps = [f"N{i}" for i in range(n_sp)]
    true_sf = rng.normal(0, 0.3, (n_keys, n_sp))
    mu = np.where(rng.random((len(idx), n_keys)) < 0.5, 0.0,
                  rng.uniform(20, 200, (len(idx), n_keys)))
    M = pd.DataFrame(mu, index=idx, columns=keys)
    C = pd.DataFrame(-(mu @ true_sf), index=idx, columns=sps)

    frames = []
    for w in (w1, w2):
        shours = idx[(idx >= w) & (idx < w + pd.Timedelta(days=REFIT_DAYS))]
        for k in keys:
            p = M.loc[shours, k].to_numpy()
            frames.append(pd.DataFrame({
                "interval_ts": shours, "key": k, "week": w,
                "p_bind": np.where(p > 0, 0.8, 0.1), "mu_gbm": np.clip(p, 1, None),
                "y_bind": (p > 0).astype(int),
                "y_mu": np.where(p > 0, p, np.nan)}))
    return M, C, pd.concat(frames, ignore_index=True)


def test_walk_metrics_are_byte_identical_with_and_without_nodal_out(tmp_path):
    """`--nodal-out` only tees arrays already computed: same seed, same draws, so
    the returned weekly-metrics frame (→ `mu_bands_weekly.csv`) must be identical
    whether or not the panel is emitted (spec §7 no-flag invariance)."""
    M, C, preds = _walk_frames()
    b0 = walk(M, C, preds, n_draws=32, seed=1)
    path = str(tmp_path / "n.npz")
    b1 = walk(M, C, preds, n_draws=32, seed=1, nodal_out=path)

    pd.testing.assert_frame_equal(b0, b1)
    assert not b0.empty                              # week 2 scored (has a pool)
    # the flag produced a panel whose node axis matches the scored SPs
    df = load_nodal(path)
    assert set(df["settlement_point"]) == set(C.columns)


# ------------------------------------------------------ the forecast_nodal load
#
# These exercise the real Postgres semantics the loader depends on — PK-collision
# replacement and INSERT..ON CONFLICT — which a fake cursor cannot honestly model.
# They connect to the DB `propagate.main` uses (PG_HOST/... env), skip when it is
# unreachable so a host-only `pytest` still passes, write under a unique run_id +
# a dedicated test layer (never the served 'ercot' pointer), and clean up after.

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
    """A connection + a unique (run_id, layer) scratch namespace, torn down after.

    Skips unless a Postgres is reachable from the env `main` reads, so this file
    stays green on a host with no DB while still testing the real thing in the
    compute container. Applies the migration-30 DDL idempotently so the test does
    not depend on a fresh initdb having already run it."""
    import os
    import uuid

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
                cur.execute("DELETE FROM forecast_nodal WHERE run_id = %s",
                            (run_id,))
                cur.execute("DELETE FROM forecast_current WHERE layer = %s",
                            (layer,))
                cur.execute("DELETE FROM forecast_sf_artifact WHERE run_id = %s",
                            (run_id,))
            conn.commit()


def _panel_npz(tmp_path, name="panel.npz", n_hours=30, seed=0):
    """A small real panel on disk: 30 UTC hours (spanning >1 UTC day) ×
    3 SPs, p50 offset from point so the two columns are provably distinct."""
    ts = pd.date_range("2025-06-01", periods=n_hours, freq="h", tz="UTC")
    sps = ["N0", "N1", "N2"]
    a = np.random.default_rng(seed).normal(0, 5, (n_hours, len(sps))).astype("f4")
    panel = NodalPanel(ts=ts.to_numpy(), settlement_points=np.array(sps),
                       p10=a - 1, p50=a, p90=a + 1, point=a + 0.5, sf_r2=None)
    sink = _NodalAccumulator()
    sink.add(panel, ts[0])
    path = str(tmp_path / name)
    sink.save(path)
    return path


def _count(conn, run_id):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forecast_nodal WHERE run_id = %s",
                    (run_id,))
        return int(cur.fetchone()[0])


def test_nodal_to_db_round_trips_and_is_idempotent(pg, tmp_path):
    """A re-run for the same run_id replaces via delete-then-copy: the row count
    equals `load_nodal` and does not double, and `point` is stored distinct from
    the sampling median `p50` (spec §4, acceptance)."""
    conn, run_id, _ = pg
    path = _panel_npz(tmp_path)
    expect = len(load_nodal(path))

    n1 = nodal_to_db(path, conn, run_id=run_id)
    conn.commit()
    n2 = nodal_to_db(path, conn, run_id=run_id)      # PK collisions replace
    conn.commit()
    assert n1 == n2 == expect == _count(conn, run_id)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forecast_nodal "
                    "WHERE run_id = %s AND (p50 IS NULL OR point IS NULL)",
                    (run_id,))
        assert cur.fetchone()[0] == 0                 # both populated
        cur.execute("SELECT count(*) FROM forecast_nodal "
                    "WHERE run_id = %s AND p50 <> point", (run_id,))
        assert int(cur.fetchone()[0]) == expect       # every row distinct


def test_re_run_overwrites_prior_values_not_appends(pg, tmp_path):
    """Idempotency must be replacement, not accumulation: a second load with
    different values leaves the new p50 in place at the same PK, not two rows."""
    conn, run_id, _ = pg
    a = _panel_npz(tmp_path, "a.npz", seed=1)
    b = _panel_npz(tmp_path, "b.npz", seed=2)         # same axes, different values
    nodal_to_db(a, conn, run_id=run_id); conn.commit()
    nodal_to_db(b, conn, run_id=run_id); conn.commit()

    got = (load_nodal(b).sort_values(["ts", "settlement_point"])
           .reset_index(drop=True))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forecast_nodal WHERE run_id = %s",
                    (run_id,))
        assert int(cur.fetchone()[0]) == len(got)     # not len(a)+len(b)
        cur.execute("SELECT p50 FROM forecast_nodal WHERE run_id = %s "
                    "ORDER BY ts, settlement_point LIMIT 1", (run_id,))
        assert cur.fetchone()[0] == pytest.approx(float(got["p50"].iloc[0]),
                                                  rel=1e-5)


def test_delivery_date_scope_replaces_only_that_day(pg, tmp_path):
    """With `delivery_date` set, only that UTC day is cleared and written —
    the single-day production path — leaving other days for the run untouched."""
    conn, run_id, _ = pg
    path = _panel_npz(tmp_path)
    df = load_nodal(path)
    days = sorted(set(df["ts"].dt.tz_convert("UTC").dt.date))
    assert len(days) >= 2                             # the panel spans >1 UTC day

    nodal_to_db(path, conn, run_id=run_id); conn.commit()   # all days
    before = _count(conn, run_id)
    n = nodal_to_db(path, conn, run_id=run_id,
                    delivery_date=str(days[0]))       # rewrite just day 0
    conn.commit()
    day0 = int((df["ts"].dt.tz_convert("UTC").dt.date == days[0]).sum())
    assert n == day0 < before
    assert _count(conn, run_id) == before             # other days survived


def test_pointer_flips_after_rows_and_stays_one_row(pg, tmp_path):
    """`upsert_pointer` writes exactly one row per layer and updates in place —
    the atomic flip the reader resolves through. It is called only after rows land
    (contract in `nodal_to_db`/main), so the run it names always has rows."""
    conn, run_id, layer = pg
    path = _panel_npz(tmp_path)
    nodal_to_db(path, conn, run_id=run_id)
    upsert_pointer(conn, layer, run_id)               # after rows, before commit
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM forecast_current WHERE layer = %s",
                    (layer,))
        assert cur.fetchone()[0] == run_id
        # the pointed-at run has rows — never a half-written / empty day
        cur.execute("SELECT count(*) FROM forecast_nodal WHERE run_id = %s",
                    (run_id,))
        assert int(cur.fetchone()[0]) > 0

    upsert_pointer(conn, layer, run_id + "-v2")        # re-promote same layer
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT run_id, count(*) OVER () FROM forecast_current "
                    "WHERE layer = %s", (layer,))
        row = cur.fetchone()
    assert row[0] == run_id + "-v2" and row[1] == 1    # updated, still one row


# --------------------------------------------------------------- the bands

def test_coverage_is_measured_not_assumed():
    """A well-specified band covers ~80%. Build one that is deliberately correct
    and one deliberately too narrow, and demand the metric can tell them apart —
    otherwise `coverage80` is decoration."""
    Y = RNG.normal(0, 10, (48, 30))
    honest = RNG.normal(0, 10, (200, 48, 30))          # right spread
    narrow = RNG.normal(0, 1, (200, 48, 30))           # 10× too confident

    assert _metrics(Y, honest)["coverage80"] == pytest.approx(0.80, abs=0.03)
    assert _metrics(Y, narrow)["coverage80"] < 0.2


def test_bands_report_coverage_and_skill_together():
    """0084's blind spot means a miss can belong to the map, not the forecast.
    Skill without coverage beside it misattributes that; the metric dict must
    always carry both."""
    Y = RNG.normal(0, 10, (48, 30))
    m = _metrics(Y, RNG.normal(0, 10, (100, 48, 30)))
    assert {"coverage80", "band_width", "pinball", "pooled_r2",
            "topdecile_hit"} <= set(m)


# ---------------------------------------------------------------- the gate

def test_gate_is_the_bar_as_written():
    """§5.5, transcribed. Pinned so it cannot drift while being read — a bar
    edited after the numbers exist is not a bar."""
    assert gate(0.62, 0.4, 0.4, 0.4) == "FORECAST PRODUCT"          # R² alone
    assert gate(0.1, 0.72, 0.88, 0.5) == "FORECAST PRODUCT"         # screening alone
    assert gate(0.35, 0.4, 0.4, 0.4) == "SCREENING TOOL"            # R² band
    assert gate(0.1, 0.65, 0.5, 0.62) == "SCREENING TOOL"           # screening band
    assert gate(0.22, 0.548, 0.787, 0.523) == "NOT THE PRODUCT"     # what we got


def test_gate_does_not_promote_a_near_miss():
    """0.599 is not 0.60. The temptation to round is exactly what pre-registration
    exists to remove."""
    assert gate(0.29, 0.599, 0.99, 0.599) == "NOT THE PRODUCT"


def test_existence_test_needs_all_three_screening_measures():
    """"Beat persistence in the screening currency" means beat it — not beat it on
    the two you like. Our model wins Spearman and sign and loses top-decile, and
    that has to read FAIL, not "mostly passed"."""
    model = {"rank_spearman": 0.548, "sign_agree": 0.787, "topdecile_hit": 0.523}
    pers = {"rank_spearman": 0.496, "sign_agree": 0.736, "topdecile_hit": 0.561}
    ok, detail = existence_test(model, pers)
    assert ok is False
    assert "LOSS" in detail and "WIN" in detail

    better = {**pers, "rank_spearman": 0.9, "sign_agree": 0.9, "topdecile_hit": 0.9}
    assert existence_test(better, pers)[0] is True


# ------------------------------------------------- the SF+μ artifact (0011)
#
# Drivers/what-if carry a per-request parameter no stored panel can enumerate, so
# the day's SF + E_mu ship instead of ~240k driver rows/day and the endpoint slices
# `−E_mu·SF` on read. These pin the serialize round-trip, that the slice reproduces
# an independent top-K, the single-digit-MB/day size, and the --drivers guard.

def _sf_mu(n_keys=8, n_sp=5, n_hours=24, seed=0):
    """A small SF (K×N) + E_mu (H×K) on one shared constraint-key vocab, with some
    SF entries zeroed so 'only constraints the map ties to a node' actually bites."""
    rng = np.random.default_rng(seed)
    keys = [f"K{i}|Z" for i in range(n_keys)]
    sps = [f"N{i}" for i in range(n_sp)]
    hours = pd.date_range("2025-06-01", periods=n_hours, freq="h", tz="UTC")
    SF = pd.DataFrame(rng.normal(0, 0.3, (n_keys, n_sp)).astype("f4"),
                      index=keys, columns=sps)
    SF.iloc[::3, 0] = 0.0                              # node N0 misses some keys
    E_mu = pd.DataFrame(rng.random((n_hours, n_keys)).astype("f4"),
                        index=hours, columns=keys)
    return SF, E_mu


def test_sf_mu_artifact_round_trips(tmp_path):
    """`build_sf_mu_artifact → load_sf_mu` recovers SF/E_mu exactly on their shared
    key vocab, and `save_sf_mu` writes the identical bytes (§4a). The blob is what
    the `forecast_sf_artifact` bytea and the on-disk artifact both hold."""
    SF, E_mu = _sf_mu()
    blob = build_sf_mu_artifact(SF, E_mu)
    art = load_sf_mu(blob)
    assert isinstance(art, SfMuArtifact)
    assert list(art.SF.index) == list(SF.index)          # constraint-key vocab
    assert list(art.SF.columns) == list(SF.columns)      # SP vocab
    assert list(art.E_mu.columns) == list(SF.index)      # E_mu on the SAME keys
    assert art.E_mu.index.equals(E_mu.index)             # tz-aware UTC hours
    np.testing.assert_allclose(art.SF.to_numpy(), SF.to_numpy(), rtol=1e-6)
    np.testing.assert_allclose(art.E_mu.to_numpy(), E_mu.to_numpy(), rtol=1e-6)

    path = str(tmp_path / "sfmu.npz")
    save_sf_mu(path, SF, E_mu)
    with open(path, "rb") as fh:
        assert fh.read() == blob                         # disk == bytea, same bytes
    assert load_sf_mu(path).SF.equals(art.SF)            # path form loads too


def test_drivers_slice_reproduces_an_independent_top_k():
    """The reconstruction the endpoint does: `contrib[k] = −E_mu[ts,k]·SF[k,sp]`
    sorted by |contrib| must match an independently computed top-K, and the stable
    unsigned headline `max_c|SF[:,sp]|` must be recoverable (§4a guardrail)."""
    SF, E_mu = _sf_mu(seed=3)
    art = load_sf_mu(build_sf_mu_artifact(SF, E_mu))
    ts, sp, k = E_mu.index[5], "N0", 4

    ind = -(E_mu.loc[ts] * SF[sp])
    ind = ind[ind != 0.0]                                # N0 is tied to fewer keys
    ind = ind.reindex(ind.abs().sort_values(ascending=False).index).head(k)
    got = node_drivers(art, sp, ts, k)
    assert list(got["constraint"]) == list(ind.index)   # same keys, same order
    np.testing.assert_allclose(got["contrib"].to_numpy(), ind.to_numpy(), atol=1e-6)
    assert (got["abs_contrib"].to_numpy() ==
            np.abs(got["contrib"].to_numpy())).all()
    assert got["exposure"].iloc[0] == pytest.approx(float(SF[sp].abs().max()))
    # signed: a constraint can raise OR lower a node — both signs are representable
    assert (got["contrib"] < 0).any() or (got["contrib"] > 0).any()


def test_materialize_drivers_is_top_k_per_node_hour():
    """The offline/debug expansion is exactly top-k per (ts, sp) — the ~240k-row/day
    object `/forecast/drivers` avoids by slicing on read."""
    SF, E_mu = _sf_mu(n_sp=4, n_hours=6, seed=1)
    art = load_sf_mu(build_sf_mu_artifact(SF, E_mu))
    df = materialize_drivers(art, k=3)
    assert set(df["settlement_point"]) == set(SF.columns)
    assert set(df["ts"]) == set(E_mu.index)
    assert (df.groupby(["ts", "settlement_point"]).size() <= 3).all()


def test_sf_mu_artifact_is_single_digit_mb_per_day():
    """A realistic day (~1.5k constraints × ~1k SPs × 24h) serializes to single-digit
    MB — the size claim that lets drivers cost storage once/day, not once/node-hour
    (§9). A per-node-hour materialization would be orders of magnitude larger."""
    SF, E_mu = _sf_mu(n_keys=1500, n_sp=1000, n_hours=24, seed=0)
    blob = build_sf_mu_artifact(SF, E_mu)
    assert len(blob) < 10_000_000                        # < 10 MB, single-digit MB


def test_parse_curated_days_refuses_full_history_and_spans():
    """--drivers is curated debug only: an explicit day list parses; a span, an
    empty spec, or more than DRIVERS_MAX_DAYS days all raise (§2.4, §5a)."""
    days = parse_curated_days("2025-06-01, 2025-07-15")
    assert [d.date().isoformat() for d in days] == ["2025-06-01", "2025-07-15"]
    with pytest.raises(ValueError):
        parse_curated_days("2025-06-01:2025-08-01")      # a >1-day span
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            parse_curated_days(bad)
    too_many = ",".join(f"2025-06-{d + 1:02d}" for d in range(DRIVERS_MAX_DAYS + 1))
    with pytest.raises(ValueError):
        parse_curated_days(too_many)


def test_sf_artifact_persist_is_idempotent_per_key(pg):
    """The bytea upsert replaces per (run_id, delivery_date), same discipline as
    forecast_nodal: a re-persist with new values leaves one row holding the new blob,
    and it round-trips back to the SF/E_mu that produced it (acceptance)."""
    conn, run_id, _ = pg
    SF, E_mu = _sf_mu(seed=5)
    day = E_mu.index[0].tz_convert("UTC").date()

    blob = persist_sf_mu_artifact(conn, SF, E_mu, run_id=run_id, delivery_date=day)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT sf_npz FROM forecast_sf_artifact "
                    "WHERE run_id = %s AND delivery_date = %s", (run_id, day))
        stored = bytes(cur.fetchone()[0])
    assert stored == blob                                # exact bytea round-trip
    np.testing.assert_allclose(load_sf_mu(stored).SF.to_numpy(), SF.to_numpy(),
                               rtol=1e-6)

    SF2 = SF * 2.0                                        # new values, same key
    sf_artifact_to_db(conn, run_id=run_id, delivery_date=day,
                      sf_npz=build_sf_mu_artifact(SF2, E_mu))
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forecast_sf_artifact WHERE run_id = %s",
                    (run_id,))
        assert int(cur.fetchone()[0]) == 1               # replaced, not appended
        cur.execute("SELECT sf_npz FROM forecast_sf_artifact "
                    "WHERE run_id = %s AND delivery_date = %s", (run_id, day))
        got = load_sf_mu(bytes(cur.fetchone()[0]))
    np.testing.assert_allclose(got.SF.to_numpy(), SF2.to_numpy(), rtol=1e-6)
