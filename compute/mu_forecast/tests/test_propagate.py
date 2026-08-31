"""Deterministic SF projection and its persisted artifact contracts."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from compute.forecast_store import (
    nodal_to_db, persist_sf_mu_artifact, sf_artifact_to_db, upsert_pointer,
)
from compute.jobs.backfill_nodal import walk
from compute.evaluation.mu import REFIT_DAYS, WINDOW_DAYS
from compute.projection.codecs import (
    DRIVERS_MAX_DAYS,
    NodalPanel,
    SfMuArtifact,
    _NodalAccumulator,
    build_sf_mu_artifact,
    load_nodal,
    load_sf_mu,
    materialize_drivers,
    node_drivers,
    parse_curated_days,
    save_sf_mu,
)
from compute.projection.propagate import propagate_window
from compute.sf_map.storage.maps import sf_mass_coverage

RNG = np.random.default_rng(11)

def _hours(n=48):
    return pd.date_range(pd.Timestamp("2025-10-01", tz="UTC"), periods=n, freq="h")
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


def test_panel_reduces_to_the_deterministic_point_metrics():
    """The served panel and scored row use the same direct point projection."""
    s, end, M, C, wp, shours = _window_frames()
    row, panel, _, _ = propagate_window(s, end, M, C, wp, want_panel=True)
    assert isinstance(panel, NodalPanel)
    assert list(panel.settlement_points) == list(C.columns)   # == SF.columns
    assert len(panel.ts) == len(shours) == row["n_hours"]

    Y = C.loc[shours, list(panel.settlement_points)].to_numpy(np.float32)
    from compute.metrics import score_matrix
    assert row["mae"] == pytest.approx(score_matrix(Y, panel.point)["mae"])


def test_want_panel_does_not_perturb_the_metrics_row():
    """Emission is a tee, not a fork: the row must be identical whether or not the
    panel is built (same seed, same draws, same percentiles)."""
    args = _window_frames()[:5]
    r0, p0, _, _ = propagate_window(*args)
    r1, p1, _, _ = propagate_window(*args, want_panel=True)
    assert p0 is None and isinstance(p1, NodalPanel)
    assert r0 is not None and r0.keys() == r1.keys()
    for k in r0:                                    # nan_ok: some metrics are nan
        assert r0[k] == pytest.approx(r1[k], nan_ok=True) if isinstance(
            r0[k], float) else r0[k] == r1[k]


def test_panel_is_bit_for_bit_deterministic():
    s, end, M, C, wp, _ = _window_frames()
    a = propagate_window(s, end, M, C, wp, want_panel=True)[1]
    b = propagate_window(s, end, M, C, wp, want_panel=True)[1]
    np.testing.assert_array_equal(a.point, b.point)


def test_propagate_window_skips_when_the_fit_window_is_empty():
    _, _, M, C, wp, _ = _window_frames()
    s2 = M.index.max() + pd.Timedelta(days=365)     # fit window lands past all data
    row, panel, _, _ = propagate_window(s2, s2 + pd.Timedelta(days=REFIT_DAYS), M, C, wp)
    assert row is None and panel is None


# ------------------------------------------- injected (persisted) SF (0095-0002)

def test_propagate_window_projects_through_injected_sf():
    """With `sf=` given, the window uses that matrix verbatim (no refit) — the path
    the forecast/backfill take reading the map's persisted SF. It bypasses the
    empty-fit-window skip, and the returned SF is the injected object itself."""
    s, end, M, C, wp, _ = _window_frames()
    # Injected SF on the SAME node universe as C (the backtest row reads Y from C on
    # SF.columns), keyed to the wp constraints — a persisted map, not a fresh fit.
    nodes = list(C.columns[:3])
    inj = pd.DataFrame(RNG.normal(0, 0.2, (4, len(nodes))),
                       index=[f"K{i}|Z" for i in range(4)], columns=nodes)
    _, panel, SF, _ = propagate_window(s, end, M, C, wp, want_panel=True,
                                       want_sf_mu=True, sf=inj)
    assert SF is inj                                  # used verbatim, never refit
    assert list(panel.settlement_points) == list(inj.columns)

    # An empty fit window would make the fitting path skip; the injected path does
    # not touch M_fit, so it still projects.
    s2 = M.index.max() + pd.Timedelta(days=365)
    fh = pd.date_range(s2, periods=24, freq="h", tz="UTC")
    _, panel2, SF2, _ = propagate_window(
        s2, s2 + pd.Timedelta(days=REFIT_DAYS), M, C, wp,
        want_panel=True, want_sf_mu=True, sf=inj,
        forward_hours=fh)
    assert panel2 is not None and SF2 is inj


def test_sf_mass_coverage_is_binding_mass_weighted():
    """Coverage weights by predicted binding mass (p_bind·mu_gbm), not key count —
    a covered key that dominates the mass carries it; a day that predicts no binding
    is vacuously covered."""
    wp = pd.DataFrame({"key": ["A", "B"], "p_bind": [1.0, 1.0], "mu_gbm": [90., 10.]})
    SF = pd.DataFrame([[0.1]], index=["A"], columns=["N0"])
    assert sf_mass_coverage(SF, wp) == pytest.approx(0.9)   # A holds 90 of 100 mass
    quiet = pd.DataFrame({"key": ["A"], "p_bind": [0.0], "mu_gbm": [0.0]})
    assert sf_mass_coverage(SF, quiet) == 1.0


def test_load_forecast_sf_fails_loud_on_missing_stale_empty_or_low_coverage(monkeypatch):
    """The shared-fit guard (0095-0002 acceptance): a missing / stale / empty /
    low-coverage map raises so the caller keeps the prior pointer; a fresh,
    covered window returns the SF to project through."""
    import compute.sf_map.storage.maps as proj

    Dd = pd.Timestamp("2025-09-15", tz="UTC")
    wp = pd.DataFrame({"key": ["K0|Z", "K1|Z"], "p_bind": [0.8, 0.8],
                       "mu_gbm": [50., 50.]})
    SF = pd.DataFrame([[0.3, 0.1], [0.2, 0.4]], index=["K0|Z", "K1|Z"],
                      columns=["N0", "N1"])

    monkeypatch.setattr(proj, "resolve_sf_window", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="no persisted SF window"):
        proj.load_forecast_sf(None, Dd, wp)

    we = Dd - pd.Timedelta(days=30)                    # closes 30d before D → stale
    monkeypatch.setattr(proj, "resolve_sf_window",
                        lambda *a, **k: (we - pd.Timedelta(days=240), we))
    monkeypatch.setattr(proj, "load_window_sf", lambda *a, **k: SF)
    with pytest.raises(RuntimeError, match="stale SF map"):
        proj.load_forecast_sf(None, Dd, wp, max_age_days=14)

    we2 = Dd - pd.Timedelta(days=3)                    # fresh from here on
    monkeypatch.setattr(proj, "resolve_sf_window",
                        lambda *a, **k: (we2 - pd.Timedelta(days=240), we2))
    monkeypatch.setattr(proj, "load_window_sf", lambda *a, **k: pd.DataFrame())
    with pytest.raises(RuntimeError, match="empty SF matrix"):
        proj.load_forecast_sf(None, Dd, wp)

    off = pd.DataFrame([[0.3]], index=["OTHER|Z"], columns=["N0"])   # covers neither key
    monkeypatch.setattr(proj, "load_window_sf", lambda *a, **k: off)
    with pytest.raises(RuntimeError, match="low SF coverage"):
        proj.load_forecast_sf(None, Dd, wp, min_coverage=0.5)

    monkeypatch.setattr(proj, "load_window_sf", lambda *a, **k: SF)
    got = proj.load_forecast_sf(None, Dd, wp, max_age_days=14, min_coverage=0.5)
    assert got is SF


# -------------------------------------------------------- the nodal npz sink

def test_nodal_npz_round_trips_the_panel(tmp_path):
    """`save_nodal → load_nodal` recovers a window's `ts`/SP/`point`
    exactly, and the node axis for the week is `SF.columns` in order — the flat
    vocab coding is lossless (spec §2)."""
    s, end, M, C, wp, _ = _window_frames()
    _, panel, _, _ = propagate_window(s, end, M, C, wp, want_panel=True)
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
    # values line up with the (H,N) C-order ravel.
    np.testing.assert_allclose(df["point"].to_numpy(), panel.point.ravel(),
                               rtol=1e-6)


def test_accumulator_keeps_ragged_node_axes_per_week(tmp_path):
    """The node set is ragged week to week (spec §9): each week keeps its own SP
    axis, never a union-and-fill, and a shared SP is coded once in `sp_vocab`."""
    def _panel(ts, sps, val):
        arr = np.full((len(ts), len(sps)), val, np.float32)
        return NodalPanel(ts=ts.to_numpy(), settlement_points=np.array(sps), point=arr,
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
    b0 = walk(M, C, preds)
    path = str(tmp_path / "n.npz")
    b1 = walk(M, C, preds, nodal_out=path)

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
  settlement_point text NOT NULL, point real,
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
    3 SPs with deterministic point values."""
    ts = pd.date_range("2025-06-01", periods=n_hours, freq="h", tz="UTC")
    sps = ["N0", "N1", "N2"]
    a = np.random.default_rng(seed).normal(0, 5, (n_hours, len(sps))).astype("f4")
    panel = NodalPanel(ts=ts.to_numpy(), settlement_points=np.array(sps), point=a,
                       sf_r2=None)
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
    equals `load_nodal` and does not double."""
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
                    "WHERE run_id = %s AND point IS NULL", (run_id,))
        assert cur.fetchone()[0] == 0


def test_re_run_overwrites_prior_values_not_appends(pg, tmp_path):
    """Idempotency must be replacement, not accumulation: a second load with
    different values leaves the new point in place at the same PK, not two rows."""
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
        cur.execute("SELECT point FROM forecast_nodal WHERE run_id = %s "
                    "ORDER BY ts, settlement_point LIMIT 1", (run_id,))
        assert cur.fetchone()[0] == pytest.approx(float(got["point"].iloc[0]),
                                                  rel=1e-5)


def test_delivery_date_scope_replaces_only_that_day(pg, tmp_path):
    """With `delivery_date` set, only that CT day (0133) is cleared and written —
    the single-day production path — leaving other days for the run untouched."""
    conn, run_id, _ = pg
    path = _panel_npz(tmp_path)
    df = load_nodal(path)
    days = sorted(set(df["ts"].dt.tz_convert("America/Chicago").dt.date))
    assert len(days) >= 2                             # the panel spans >1 CT day

    nodal_to_db(path, conn, run_id=run_id); conn.commit()   # all days
    before = _count(conn, run_id)
    n = nodal_to_db(path, conn, run_id=run_id,
                    delivery_date=str(days[0]))       # rewrite just day 0
    conn.commit()
    day0 = int((df["ts"].dt.tz_convert("America/Chicago").dt.date == days[0]).sum())
    assert n == day0 < before
    assert _count(conn, run_id) == before             # other days survived


def test_seam_hour_from_a_pre_cutover_row_is_replaced_not_collided(pg, tmp_path):
    """0133b: a stale row from before the CT-day cutover, still labeled by the
    OLD UTC-calendar-day convention, must be cleanly replaced — not collide —
    when the CT day that now legitimately owns that `ts` is (re)written.

    This reproduces a real production crash: `nodal_to_db` used to scope its
    DELETE by the `delivery_date` column, but the real primary key is
    `(run_id, ts, settlement_point, horizon)`, which has no such scope. A `ts`
    in the ~5 CT-evening seam hours per day carries a *different*
    `delivery_date` label depending on which convention wrote it, so a
    delivery_date-scoped DELETE misses the stale row and the COPY hits a
    UniqueViolation on it instead of replacing it.
    """
    conn, run_id, _ = pg
    seam_ts = pd.Timestamp("2026-07-31 00:00:00", tz="UTC")  # CT 19:00 on 07-30
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO forecast_nodal "
            "(run_id, delivery_date, ts, settlement_point, point, horizon) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (run_id, "2026-07-31", seam_ts, "SP0", 1.0, 1))
    conn.commit()

    # 2026-07-30's OWN CT-day block legitimately covers seam_ts too (its 19:00
    # CT hour) — the exact overlap that used to collide.
    ts = pd.date_range(pd.Timestamp("2026-07-30", tz="America/Chicago").tz_convert("UTC"),
                       periods=24, freq="h")
    assert seam_ts in ts
    a = np.random.default_rng(3).normal(0, 5, (24, 1)).astype("f4")
    panel = NodalPanel(ts=ts.to_numpy(), settlement_points=np.array(["SP0"]),
                       point=a, sf_r2=None)
    sink = _NodalAccumulator()
    sink.add(panel, ts[0])
    path = str(tmp_path / "seam.npz")
    sink.save(path)

    n = nodal_to_db(path, conn, run_id=run_id, delivery_date="2026-07-30", horizon=1)
    conn.commit()
    assert n == 24

    with conn.cursor() as cur:
        cur.execute("SELECT delivery_date, point FROM forecast_nodal "
                    "WHERE run_id = %s AND ts = %s", (run_id, seam_ts))
        rows = cur.fetchall()
    assert len(rows) == 1                        # replaced, not duplicated
    assert str(rows[0][0]) == "2026-07-30"        # now correctly CT-labeled
    assert rows[0][1] != pytest.approx(1.0)       # the stale value is gone


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
