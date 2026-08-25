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
from compute.time import ct_day_bounds
from compute.evaluation.mu import REFIT_DAYS, WINDOW_DAYS
from compute.projection.propagate import NodalPanel, build_sf_mu_artifact, load_sf_mu

# An arbitrary CT-midnight delivery day, expressed in UTC (0133) — not a DST
# transition day, so it is 24 hours and `D + pd.Timedelta(days=1)` coincides with
# its true CT block end; DST-transition days get their own dedicated tests below.
D = pd.Timestamp("2025-09-15", tz="America/Chicago").tz_convert("UTC")


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
        seen["vintage_cutoff"] = kw.get("vintage_cutoff")
        if build_raises:
            raise ValueError("simulated loader failure")
        if build_empty:
            return pd.DataFrame()
        # A (key, interval_ts) MultiIndex like the real `build_panel`, so the
        # `keep_from` slice (`get_level_values("interval_ts")`) has its level. All
        # rows sit strictly before D (< keep_from is fine — predict_day is faked).
        hours = pd.date_range(D - pd.Timedelta(days=3), periods=3, freq="D", tz="UTC")
        idx = pd.MultiIndex.from_product([["K0|c"], hours],
                                         names=["key", "interval_ts"])
        return pd.DataFrame({"x": [1, 2, 3]}, index=idx)

    def fake_predict_day(panel, D_, *, train_days, arms, seed, spill_dir=None):
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

    def fake_load_forecast_sf(conn, D_, wp, **kw):
        # The persisted-SF read (0095-0002) is exercised by its own unit tests; here
        # it just returns a valid map so `forecast_day`'s orchestration proceeds.
        seen["sf_D"] = D_
        seen["map_run_id"] = kw.get("run_id")
        return pd.DataFrame([[1.0]], index=["K0|c"], columns=["SP0"]).astype("f4")

    def fake_resolve_sf_window(conn, run_id, *, as_of=None):
        # The run-log provenance capture (0123): forecast_day re-resolves the SF
        # window to pin the geography vintage in the result. A fixed causal window.
        seen["sf_window_run_id"] = run_id
        return (D - pd.Timedelta(days=7), D - pd.Timedelta(days=1))

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
    monkeypatch.setattr(fd, "load_forecast_sf", fake_load_forecast_sf)
    monkeypatch.setattr(fd, "resolve_sf_window", fake_resolve_sf_window)
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
    assert seen["panel_window"][1] == fd._ct_block_end(D)


def test_score_block_is_exactly_Ds_ct_day(monkeypatch):
    """Forward hours are D's CT calendar day (24h here — not a DST transition —
    see the DST-specific test below), and the propagation window is
    [D, next CT midnight) — the score block, not a 7-day backtest week."""
    seen = _install_fakes(monkeypatch)
    forecast_day(None, D, run_id="t")

    fh = seen["forward_hours"]
    block_end = fd._ct_block_end(D)
    assert len(fh) == 24
    assert list(fh) == list(pd.date_range(D, block_end, freq="h", inclusive="left"))
    assert seen["prop_end"] == block_end


@pytest.mark.parametrize("day, hours", [("2026-03-08", 23),    # spring forward
                                        ("2026-11-01", 25)])   # fall back
def test_score_block_is_dst_aware(monkeypatch, day, hours):
    """A spring-forward CT day scores 23 hours, a fall-back day 25 — never a flat
    24 (0133's whole point: a UTC-midnight cut never saw this because UTC has no
    DST fold)."""
    Dd = pd.Timestamp(day, tz="America/Chicago").tz_convert("UTC")
    seen = _install_fakes(monkeypatch)
    forecast_day(None, Dd, run_id="t")
    assert len(seen["forward_hours"]) == hours
    assert seen["prop_end"] - Dd == pd.Timedelta(hours=hours)


def test_delivery_day_buckets_to_its_ct_calendar_day(monkeypatch):
    """A non-midnight instant is not rejected — it is bucketed to its own CT
    calendar day's midnight, the same way `ct_day_bounds` normalizes any instant
    (0133: the day boundary is now derived, not merely validated)."""
    seen = _install_fakes(monkeypatch)
    # 05:00 UTC on 2025-09-15 IS D (CDT) — passing it should be a no-op.
    forecast_day(None, pd.Timestamp("2025-09-15 05:00", tz="UTC"), run_id="t")
    assert seen["prop_s"] == D


def test_delivery_date_and_result_are_ct(monkeypatch):
    _install_fakes(monkeypatch)
    r = forecast_day(None, "2025-09-15", run_id="mu-all-v1")
    assert r.delivery_date == D.date()
    assert len(r.panel.ts) == 24
    assert r.run_id == "mu-all-v1"


# ----------------------------------------------------------------------------
# Vintage-faithful preview backfill (0133) — fire_time -> build_panel's cutoff
# ----------------------------------------------------------------------------

def test_fire_time_defaults_to_the_wall_clock(monkeypatch):
    """Live serving passes no `fire_time` — it defaults to `now`, well after any
    D's DAM close, so the vintage cap is a no-op in production (spec: 0133)."""
    seen = _install_fakes(monkeypatch)
    before = pd.Timestamp.now(tz="UTC")
    forecast_day(None, D, run_id="t")
    after = pd.Timestamp.now(tz="UTC")
    cutoff = seen["vintage_cutoff"]
    assert cutoff is not None
    assert before <= cutoff <= after


def test_explicit_fire_time_reaches_build_panel(monkeypatch):
    """A caller's `fire_time` (the historical backfill path) is threaded straight
    through to `build_panel`'s `vintage_cutoff` — unmodified."""
    seen = _install_fakes(monkeypatch)
    fire_time = pd.Timestamp("2025-09-13 20:15", tz="UTC")
    forecast_day(None, D, run_id="t", fire_time=fire_time)
    assert seen["vintage_cutoff"] == fire_time


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
# CLI date resolution (0122) — `tomorrow` is a CT calendar step
# ----------------------------------------------------------------------------

def _tomorrow_at(ct_wall: str) -> str:
    """Resolve `tomorrow` as if the job were launched at CT wall-clock `ct_wall`."""
    now = pd.Timestamp(ct_wall, tz="America/Chicago").tz_convert("UTC")
    return fd._resolve_delivery_date("tomorrow", now=now).date().isoformat()


@pytest.mark.parametrize("day", ["2026-07-26",      # CDT, UTC-5
                                 "2026-01-15",      # CST, UTC-6
                                 "2026-03-08",      # spring forward (23h CT day)
                                 "2026-11-01"])     # fall back (25h CT day)
def test_tomorrow_is_the_same_day_all_day_long(day):
    """`tomorrow` is the next CT date no matter what hour of the CT day the job is
    launched. Resolving off the UTC clock broke exactly here: past 19:00 CT the UTC
    date has already rolled, so an evening run skipped a day (the 2026-07-27 prod
    hole). Both DST transitions are covered — the CT date is normalized before the
    day is added, so a 23-/25-hour day cannot shift it."""
    expect = (pd.Timestamp(day) + pd.Timedelta(days=1)).date().isoformat()
    for hour in ("00:30", "09:00", "12:00", "18:30", "20:10", "23:45"):
        assert _tomorrow_at(f"{day} {hour}") == expect


def test_explicit_date_is_parsed_as_the_ct_day_label():
    """An explicit `YYYY-MM-DD` names the CT day label directly (0133) — what the
    backfill recipe and every stored `delivery_date` mean."""
    assert fd._resolve_delivery_date("2026-07-27") == pd.Timestamp(
        "2026-07-27", tz="America/Chicago").tz_convert("UTC")


def test_ct_span_reports_the_delivery_blocks_wall_clock():
    """The logged span is CT midnight to midnight (0133) — D IS the CT day now, so
    this is mostly a regression tripwire: a drifted D would stop reading 00:00."""
    span = fd._ct_span(fd._resolve_delivery_date("2026-07-27"))
    assert "2026-07-27 00:00" in span and "2026-07-27 23:00" in span and "CDT" in span
    # Winter still tags the block with the correct DST offset.
    assert "CST" in fd._ct_span(fd._resolve_delivery_date("2026-01-15"))


# ----------------------------------------------------------------------------
# Horizon 2 (0123) — the preview: t+2 date resolution + the DAM-publication gate
# ----------------------------------------------------------------------------

@pytest.mark.parametrize("day", ["2026-07-26",      # CDT
                                 "2026-01-15",      # CST
                                 "2026-03-08",      # spring forward
                                 "2026-11-01"])     # fall back
def test_horizon_2_tomorrow_is_two_ct_days_out(day):
    """With horizon 2, `tomorrow` resolves to the CT date two days ahead (T+2) — the
    preview lands inside D's decision window — no matter the launch hour, both DST
    transitions covered. Horizon 1 stays the classic next CT day."""
    expect2 = (pd.Timestamp(day) + pd.Timedelta(days=2)).date().isoformat()
    expect1 = (pd.Timestamp(day) + pd.Timedelta(days=1)).date().isoformat()
    for hour in ("00:30", "12:00", "18:30", "20:10", "23:45"):
        now = pd.Timestamp(f"{day} {hour}", tz="America/Chicago").tz_convert("UTC")
        assert fd._resolve_delivery_date("tomorrow", horizon=2,
                                         now=now).date().isoformat() == expect2
        assert fd._resolve_delivery_date("tomorrow", horizon=1,
                                         now=now).date().isoformat() == expect1


def test_explicit_date_ignores_horizon():
    """An explicit `YYYY-MM-DD` names the CT day directly — horizon does not shift
    it (only `tomorrow` is horizon-relative)."""
    want = pd.Timestamp("2026-07-27", tz="America/Chicago").tz_convert("UTC")
    for h in (1, 2):
        assert fd._resolve_delivery_date("2026-07-27", horizon=h) == want


class _GateCur:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.sql, self._conn.params = sql, params

    def fetchone(self):
        # A SELECT max(...) aggregate always returns exactly one row (NULL when
        # nothing matched) — never zero rows. `(1,)`/`None` (this stub's original
        # shape) desynced from real cursor behavior and from `pd.Timestamp`
        # comparisons in `dam_shadow_covers_window`; both pre-existing stub bugs,
        # fixed alongside 0133 since this function is being touched anyway.
        return (self._conn.ts_max,)


class _GateConn:
    """Minimal fake conn for the DAM gate: `ts_max` is what the probed window's
    `max(interval_ts)` would return — `None` when nothing published. Records the
    executed query so the window can be asserted."""
    def __init__(self, ts_max):
        self.ts_max = ts_max
        self.sql = None
        self.params = None

    def cursor(self):
        return _GateCur(self)


def test_horizon_2_gate_passes_when_freshest_day_published():
    """D−1 has shadow-price rows spanning its window → the gate is silent, and it
    probed exactly D−1's CT-day window [D−1, D)."""
    conn = _GateConn(D - pd.Timedelta(hours=1))      # D−1's own late-evening row
    fd._assert_freshest_history_published(conn, D)      # no raise
    assert conn.params == (D - pd.Timedelta(days=1), D)


def test_horizon_2_gate_probes_the_true_ct_day_before_across_dst():
    """D−1's window is `ct_day_bounds(D−1)`, not a flat `D − 1 day` — the two only
    coincide off a DST transition. D = the day AFTER spring-forward, so D−1 IS the
    23-hour transition day itself — the case where they diverge."""
    Dd = pd.Timestamp("2026-03-09", tz="America/Chicago").tz_convert("UTC")
    conn = _GateConn(Dd - pd.Timedelta(hours=1))
    fd._assert_freshest_history_published(conn, Dd)
    want_lo, _ = ct_day_bounds(pd.Timestamp("2026-03-08").date())
    assert conn.params == (want_lo, Dd)
    assert want_lo != Dd - pd.Timedelta(days=1)      # the naive form would be wrong here


def test_horizon_2_gate_fails_loud_when_freshest_day_missing():
    """D−1 has no shadow-price rows (late ERCOT post) → RuntimeError, before any
    fit; nothing is written because the caller never reaches persistence."""
    with pytest.raises(RuntimeError, match="horizon-2 gate"):
        fd._assert_freshest_history_published(_GateConn(None), D)


def test_forecast_day_horizon_2_gates_before_fit_and_labels_result(monkeypatch):
    """forecast_day(horizon=2) runs the gate before stage 1 and stamps horizon=2 on
    the result; horizon=1 skips the gate entirely."""
    _install_fakes(monkeypatch)
    calls = []
    monkeypatch.setattr(fd, "_assert_freshest_history_published",
                        lambda conn, D_: calls.append(D_))
    r2 = forecast_day(None, D, run_id="t", horizon=2)
    assert calls == [D] and r2.horizon == 2

    calls.clear()
    r1 = forecast_day(None, D, run_id="t", horizon=1)
    assert calls == [] and r1.horizon == 1


def test_forecast_day_horizon_2_gate_stops_before_any_read(monkeypatch):
    """When the gate fails, the fit never starts — no shadow-price/panel read runs."""
    seen = _install_fakes(monkeypatch)
    with pytest.raises(RuntimeError, match="horizon-2 gate"):
        forecast_day(_GateConn(None), D, run_id="t", horizon=2)
    assert "sp_window" not in seen and "panel_window" not in seen


# ----------------------------------------------------------------------------
# Persist: idempotency + atomicity (spec §6, §9) — real Postgres, scratch layer
# ----------------------------------------------------------------------------

# Mirrors migrations 30/31 + 37 (the horizon column, widened PKs). IF NOT EXISTS, so
# against an already-migrated DB it is a no-op and the real tables are used.
_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS forecast_nodal (
  run_id text NOT NULL, delivery_date date NOT NULL, ts timestamptz NOT NULL,
  settlement_point text NOT NULL, p10 real, p50 real, p90 real, point real,
  horizon smallint NOT NULL DEFAULT 1,
  PRIMARY KEY (run_id, ts, settlement_point, horizon));
CREATE TABLE IF NOT EXISTS forecast_current (
  layer text PRIMARY KEY, run_id text NOT NULL,
  promoted_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS forecast_sf_artifact (
  run_id text NOT NULL, delivery_date date NOT NULL, sf_npz bytea NOT NULL,
  horizon smallint NOT NULL DEFAULT 1,
  PRIMARY KEY (run_id, delivery_date, horizon));
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


def _synthetic_result(run_id, day=D, point_value=2.5, horizon=1, seed=0):
    ts = pd.date_range(day, periods=24, freq="h", tz="UTC")
    sps = np.array(["SP_A", "SP_B", "SP_C"])
    keys = ["K1|c", "K2|c"]
    rng = np.random.default_rng(seed)
    p50 = rng.random((24, 3)).astype("f4") + point_value
    panel = NodalPanel(ts=ts.to_numpy(), settlement_points=sps,
                       p10=(p50 - 0.5).astype("f4"), p50=p50,
                       p90=(p50 + 0.5).astype("f4"),
                       point=(p50 * 1.1).astype("f4"), sf_r2=None)
    SF = pd.DataFrame(rng.random((2, 3)).astype("f4"), index=keys, columns=sps)
    E_mu = pd.DataFrame(rng.random((24, 2)).astype("f4"), index=ts, columns=keys)
    return ForecastResult(run_id=run_id, delivery_date=day.date(), panel=panel,
                          SF=SF, E_mu=E_mu, sf_mu=build_sf_mu_artifact(SF, E_mu),
                          horizon=horizon)


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


def test_published_day_is_detected_before_the_fit(pg):
    """The overwrite guard's probe (0122): a published `(run_id, delivery_date)`
    reads back as present, and neither a different run nor a different day does. The
    CLI runs this before the fit, so an unintended re-run costs a query instead of a
    clobbered panel."""
    conn, run_id, layer = pg
    other = D + pd.Timedelta(days=1)
    assert not fd._day_already_published(conn, run_id, D)
    persist_forecast(conn, _synthetic_result(run_id), layer=layer)
    assert fd._day_already_published(conn, run_id, D)
    assert not fd._day_already_published(conn, run_id, other)
    assert not fd._day_already_published(conn, f"{run_id}-nope", D)


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


def _sf_blob(conn, run_id, horizon):
    with conn.cursor() as cur:
        cur.execute("SELECT sf_npz FROM forecast_sf_artifact WHERE run_id=%s "
                    "AND horizon=%s", (run_id, horizon))
        row = cur.fetchone()
        return None if row is None else bytes(row[0])


def test_horizon_tracks_coexist_and_final_never_clobbers_preview(pg):
    """Acceptance (0123): publish preview (h2) then final (h1) for the same day and
    BOTH row sets survive; re-running the final replaces only its own horizon and
    leaves the preview's rows and blob byte-for-byte intact — the preserved audit
    trail."""
    conn, run_id, layer = pg
    # Distinct seeds so the two horizons' SF/E_mu blobs genuinely differ.
    persist_forecast(conn, _synthetic_result(run_id, horizon=2, seed=2), layer=layer)
    persist_forecast(conn, _synthetic_result(run_id, horizon=1, seed=1), layer=layer)

    # Both tracks present, side by side (72 rows each), one blob each.
    with conn.cursor() as cur:
        cur.execute("SELECT horizon, count(*) FROM forecast_nodal WHERE run_id=%s "
                    "GROUP BY horizon ORDER BY horizon", (run_id,))
        assert cur.fetchall() == [(1, 24 * 3), (2, 24 * 3)]
    preview_bytes = _sf_blob(conn, run_id, 2)
    assert preview_bytes is not None and preview_bytes != _sf_blob(conn, run_id, 1)

    # Re-run the final under the same run_id — replaces h1 only.
    persist_forecast(conn, _synthetic_result(run_id, horizon=1, seed=99), layer=layer)
    with conn.cursor() as cur:
        cur.execute("SELECT horizon, count(*) FROM forecast_nodal WHERE run_id=%s "
                    "GROUP BY horizon ORDER BY horizon", (run_id,))
        assert cur.fetchall() == [(1, 24 * 3), (2, 24 * 3)]   # still both, not tripled
    assert _sf_blob(conn, run_id, 2) == preview_bytes          # preview bytes intact


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
    from compute.mu_forecast.panel.build import build_panel
    from compute.mu_forecast.model.runner import load_preds, predict_day
    from compute.inputs.dam import load_congestion_panel, load_shadow_prices
    from compute.projection.propagate import N_DRAWS, propagate_window, residual_pool

    conn = pg[0]
    # Reconciliation fixture: a real walk-derived residual pool with enough weeks.
    # Production now resolves the pool per run_id off the runs PVC
    # (fd.preds_path_for); this self-contained test still reads the bundled
    # compute/mu/mu_preds.npz beside the μ library.
    bundled_preds = os.path.join(
        os.path.dirname(os.path.dirname(fd.__file__)), "mu", "mu_preds.npz")
    preds = load_preds(bundled_preds)

    # An interior grid boundary: a full 240d of prior history so the SF map fits.
    weeks = pd.DatetimeIndex(sorted(preds["week"].unique()))
    weeks = weeks[(weeks >= weeks.min() + pd.Timedelta(days=240))
                  & (weeks <= weeks.max() - pd.Timedelta(days=7))]
    assert len(weeks), "no interior scored week to reconcile against"
    Dr = fd._as_ct_day(pd.Timestamp(weeks[len(weeks) // 2]))
    prop_end = fd._ct_block_end(Dr)      # Dr's next CT midnight — DST-aware (0133)

    # Build SOME valid wp (data < Dr). Both modes share it, so its provenance is
    # irrelevant to whether they agree; a 240d read window keeps the fit in memory.
    read_start = Dr - pd.Timedelta(days=240)
    M_hon = load_shadow_prices(conn, read_start, Dr)
    C_hon = load_congestion_panel(conn, read_start, Dr)
    panel = build_panel(conn, M_hon, read_start, prop_end,
                        C=C_hon, score_from=Dr, with_weather=True, with_outage=False)
    wp = predict_day(panel, Dr, train_days=240, arms=("lag", "geo", "wx"), seed=0)
    del panel, M_hon, C_hon
    assert len(wp), "no scorable constraints — cannot reconcile"

    # Propagation inputs: the fit window [Dr−WINDOW_DAYS, Dr) plus a REALIZED score
    # block at Dr, so backtest mode has C_score to intersect (forward mode ignores it).
    prop_start = Dr - pd.Timedelta(days=WINDOW_DAYS)
    M = load_shadow_prices(conn, prop_start, prop_end)
    C = load_congestion_panel(conn, prop_start, prop_end)
    eps = residual_pool(preds[preds["week"] < Dr], rng=np.random.default_rng(0))

    # forward mode: hours = D's CT calendar day; no realized Y read.
    fwd_hours = pd.date_range(Dr, prop_end, freq="h", inclusive="left")
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
