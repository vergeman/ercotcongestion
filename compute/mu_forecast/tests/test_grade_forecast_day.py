"""Tests for the `grade_forecast_day` live-grading job (plan 0102 / 0003-live-grading).

Deterministic and DB-free: every DB seam of `grade_forecast_day` (the served forecast,
its SF artifact, and the shadow-price / congestion loaders) is stubbed so the ORCHESTRATION
— the score grid, the common-node intersection, and which quantity each source is
scored on — is exercised against the shared screening helper in
milliseconds. The reconciliation guarantee (spec §7) is proven structurally here:
`grade_forecast_day`'s per-source rows are asserted byte-equal to the recomputed
independently on the same Y / Yh, so a live number and a backtest number are the
same currency by construction. The null-guard (spec §6) — a flat map cannot
manufacture a screening score — and the fail-loud paths round it out.

Enough nodes (30) that `row_spearman` (needs ≥10) and `topdecile_hit` (≥20)
actually score rather than declining to NaN for want of width.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

import compute.jobs.grade_forecast_day as gd
from compute.evaluation.mu import mu_climatology, mu_null, mu_persistence
from compute.metrics import screening_metrics
from compute.evaluation.sf import predict

D = pd.Timestamp("2025-09-15", tz="America/Chicago").tz_convert("UTC")  # a CT-midnight day
SPS = [f"SP{i}" for i in range(30)]
KEYS = ["K0|c", "K1|c", "K2|c"]


def _scenario(seed: int = 0):
    """A fixed (M, C, SF, served-point-forecast) world."""
    rng = np.random.default_rng(seed)

    # Shadow prices over D−1 and D (48 h) — nonneg with zeros, so persistence (D−1)
    # is a real, non-flat source and oracle (D) projects to varied congestion.
    hoursM = pd.date_range(D - pd.Timedelta(days=1), periods=48, freq="h", tz="UTC")
    Mv = rng.gamma(1.0, 5.0, size=(48, 3)) * (rng.random((48, 3)) > 0.4)
    M = pd.DataFrame(Mv, index=hoursM, columns=KEYS)

    # Realized congestion over D's 24 h × 30 nodes — the target Y.
    hoursD = pd.date_range(D, periods=24, freq="h", tz="UTC")
    C = pd.DataFrame(rng.normal(0, 10, size=(24, 30)), index=hoursD, columns=SPS)

    SF = pd.DataFrame(rng.normal(0, 0.2, size=(3, 30)),
                      index=KEYS, columns=SPS).astype("f4")

    point = pd.DataFrame(rng.normal(0, 8, size=(24, 30)), index=hoursD, columns=SPS)
    fc = {"point": point}
    return M, C, SF, fc, hoursD


def _install(monkeypatch, M, C, SF, fc):
    monkeypatch.setattr(gd, "load_served_forecast",
                        lambda conn, run_id, D_, horizon=1: fc)
    monkeypatch.setattr(gd, "load_shadow_prices", lambda conn, lo, hi: M)
    monkeypatch.setattr(gd, "load_congestion_panel", lambda conn, lo, hi: C)
    monkeypatch.setattr(gd, "load_served_sf",
                        lambda conn, run_id, D_, horizon: SF)
    monkeypatch.setattr(gd, "score_served_essp",
                        lambda conn, D_, SF_: {
                            "essp_precision": None, "essp_recall": None})


# ---------------------------------------------------------------------------
# Reconciliation: every source row uses identical screening inputs (spec §7)
# ---------------------------------------------------------------------------

def test_rows_reproduce_screening_metrics_on_the_same_inputs(monkeypatch, caplog):
    M, C, SF, fc, hoursD = _scenario()
    _install(monkeypatch, M, C, SF, fc)

    with caplog.at_level(logging.INFO, logger=gd.__name__):
        rows = grade_rows(monkeypatch, M, C, SF, fc)
    by_src = {r["source"]: r for r in rows}
    assert set(by_src) == {
        "scoreboard_model_served_nodal",
        "scoreboard_oracle_settled_mu_nodal",
        "scoreboard_persistence_prior_day_nodal",
        "scoreboard_climatology_trailing_window_nodal",
        "scoreboard_null_flat_nodal",
    }

    hours = hoursD
    cols = M.loc[hours].columns
    Y = C.loc[hours, SPS].to_numpy(float)

    # model: the served deterministic point.
    want = screening_metrics(Y, fc["point"].loc[hours, SPS].to_numpy(float))
    for k, v in want.items():
        _eq(by_src["scoreboard_model_served_nodal"][k], v)

    # comparators: each mu source projected through SF, same metric.
    srcs = {
        "oracle": M.loc[hours],
        "persistence": mu_persistence(M, hours, cols),
        "climatology": mu_climatology(M.loc[M.index < D], hours, cols),
        "null": mu_null(hours, cols),
    }
    source_ids = {
        "oracle": "scoreboard_oracle_settled_mu_nodal",
        "persistence": "scoreboard_persistence_prior_day_nodal",
        "climatology": "scoreboard_climatology_trailing_window_nodal",
        "null": "scoreboard_null_flat_nodal",
    }
    for name, Msrc in srcs.items():
        Yh = pd.DataFrame(predict(Msrc, SF), index=hours, columns=SF.columns)[SPS]
        want = screening_metrics(Y, Yh.to_numpy(float))
        for k, v in want.items():
            _eq(by_src[source_ids[name]][k], v)

    messages = [record.getMessage() for record in caplog.records]
    assert "grade_forecast_day start: delivery_date=2025-09-15 run_id=t horizon=1" in messages
    assert any(message.startswith("grade_forecast_day complete: delivery_date=2025-09-15 ")
               and "elapsed_s=" in message for message in messages)


def test_rows_do_not_expose_retired_band_metrics(monkeypatch):
    M, C, SF, fc, hoursD = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    rows = grade_rows(monkeypatch, M, C, SF, fc)
    by_src = {r["source"]: r for r in rows}

    for row in by_src.values():
        assert not {"coverage80", "band_width", "pinball"} & set(row)


def test_essp_agreement_is_stamped_on_model_row_only(monkeypatch):
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    monkeypatch.setattr(gd, "score_served_essp",
                        lambda *args: {"essp_precision": 1.0, "essp_recall": 0.5})
    by_src = {r["source"]: r for r in grade_rows(monkeypatch, M, C, SF, fc)}
    assert by_src["scoreboard_model_served_nodal"]["essp_precision"] == 1.0
    assert by_src["scoreboard_model_served_nodal"]["essp_recall"] == 0.5
    for source in ("scoreboard_oracle_settled_mu_nodal",
                   "scoreboard_persistence_prior_day_nodal",
                   "scoreboard_climatology_trailing_window_nodal",
                   "scoreboard_null_flat_nodal"):
        assert by_src[source]["essp_precision"] is None
        assert by_src[source]["essp_recall"] is None


def test_null_source_cannot_manufacture_a_screening_score(monkeypatch):
    """The integrity tripwire (spec §6): a flat map ranks nothing, so its screening
    cells are NaN — never a number that could read as skill. If this regresses, the
    whole live board is suspect."""
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    rows = grade_rows(monkeypatch, M, C, SF, fc)
    null = next(r for r in rows if r["source"] == "scoreboard_null_flat_nodal")
    assert np.isnan(null["rank_spearman"])
    assert np.isnan(null["topdecile_hit"])


def test_coverage_grain_is_shared_across_sources(monkeypatch):
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    rows = grade_rows(monkeypatch, M, C, SF, fc)
    for r in rows:
        assert r["n_hours"] == 24
        assert r["n_nodes"] == 30
        # Every constraint is in the (stubbed) SF, so the map covers all the day's
        # μ-mass — sf_coverage == 1.0, identical on every source row.
        assert r["sf_coverage"] == pytest.approx(1.0)
        # model_coverage needs the prediction-time key set (the deferred snapshot).
        assert r["model_coverage"] is None


# ---------------------------------------------------------------------------
# Fail-loud: nothing to grade is an error, never a hollow row
# ---------------------------------------------------------------------------

def test_raises_when_nothing_was_served(monkeypatch):
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    monkeypatch.setattr(gd, "load_served_forecast",
                        lambda conn, run_id, D_, horizon=1: {})
    with pytest.raises(RuntimeError, match="no served forecast"):
        gd.grade_day(None, D, run_id="t")


def test_raises_when_served_sf_artifact_is_missing(monkeypatch):
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    monkeypatch.setattr(gd, "load_served_sf", lambda *args: (_ for _ in ()).throw(
        RuntimeError("no served SF artifact")))
    with pytest.raises(RuntimeError, match="no served SF artifact"):
        gd.grade_day(None, D, run_id="t")


def test_raises_when_realized_has_not_published(monkeypatch):
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    monkeypatch.setattr(gd, "load_congestion_panel",
                        lambda conn, lo, hi: pd.DataFrame())
    with pytest.raises(RuntimeError, match="realized DAM has not published"):
        gd.grade_day(None, D, run_id="t")


# ---------------------------------------------------------------------------
# resolve_gradeable_date — the daily-tick day selector (fake cursor)
# ---------------------------------------------------------------------------

class _FakeCur:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._conn.sql, self._conn.params = sql, params

    def fetchone(self):
        return self._conn.row


class _FakeConn:
    def __init__(self, row):
        self.row = row
        self.sql = None
        self.params = None

    def cursor(self):
        return _FakeCur(self)


def test_resolve_gradeable_date_returns_the_newest_gradeable_day_as_ct_midnight(caplog):
    import datetime as _dt
    conn = _FakeConn((_dt.date(2025, 9, 15),))
    with caplog.at_level(logging.INFO, logger=gd.__name__):
        D_ = gd.resolve_gradeable_date(conn, "t")
    assert D_ == D
    assert conn.params == {"run_id": "t", "horizon": 1}
    messages = [record.getMessage() for record in caplog.records]
    assert "grade selection start: run_id=t horizon=1" in messages
    assert any(message.startswith("grade selection complete: run_id=t ")
               and "delivery_date=2025-09-15" in message
               and "elapsed_s=" in message for message in messages)


def test_horizon_scopes_the_read_and_stamps_every_row(monkeypatch):
    """grade_day(horizon=2) reads the horizon-2 served rows and stamps horizon=2 on
    every source row — the two tracks grade independently (0123)."""
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    seen = {}

    def _read(conn, run_id, D_, horizon=1):
        seen["horizon"] = horizon
        return fc

    monkeypatch.setattr(gd, "load_served_forecast", _read)
    rows = gd.grade_day(None, D, run_id="t", horizon=2)
    assert seen["horizon"] == 2
    assert all(r["horizon"] == 2 for r in rows)


def test_horizons_use_their_own_served_sf_artifacts(monkeypatch):
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    seen = []
    def _sf(conn, run_id, D_, horizon):
        seen.append(horizon)
        return SF if horizon == 1 else -SF
    monkeypatch.setattr(gd, "load_served_sf", _sf)
    h1 = gd.grade_day(None, D, run_id="t", horizon=1)
    h2 = gd.grade_day(None, D, run_id="t", horizon=2)
    assert seen == [1, 2]
    assert h1[1]["rank_spearman"] != h2[1]["rank_spearman"]


def test_resolve_gradeable_date_scopes_to_horizon():
    """The day selector filters both served rows and the graded-already check to the
    requested horizon, so the final and preview tracks select independently."""
    conn = _FakeConn((D.date(),))
    assert gd.resolve_gradeable_date(conn, "t", horizon=2) == D
    assert conn.params == {"run_id": "t", "horizon": 2}
    sql = " ".join(conn.sql.split()).lower()
    assert "and horizon = %(horizon)s" in sql
    assert "sd.horizon = %(horizon)s" in sql


def test_resolve_gradeable_date_none_when_no_served_day_is_gradeable():
    assert gd.resolve_gradeable_date(_FakeConn(None), "t") is None


def test_resolve_gradeable_date_none_when_candidates_are_only_partially_realized():
    """The selector's EXISTS clause excludes a candidate without its D + 23h λ."""
    assert gd.resolve_gradeable_date(_FakeConn(None), "t") is None


def test_resolve_gradeable_date_selector_checks_expected_final_hour_not_nodal_max():
    """The DB returns the newest candidate whose final hour is realized.

    A missing result represents both no served candidates and candidates whose
    final hour has not published, so either state stays safely ungradeable.
    """
    conn = _FakeConn((D.date(),))
    assert gd.resolve_gradeable_date(conn, "t") == D

    sql = " ".join(conn.sql.split()).lower()
    assert "select max(ts) from forecast_nodal" not in sql
    assert "((c.delivery_date + 1)::timestamp at time zone 'america/chicago')" in sql
    assert "interval '1 hour'" in sql
    assert "order by c.delivery_date desc" in sql
    assert "limit 1" in sql


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def grade_rows(monkeypatch, M, C, SF, fc) -> list[dict]:
    return gd.grade_day(None, D, run_id="t")


def _eq(got, want):
    """NaN-aware scalar compare for the metric cells."""
    if want is None or (isinstance(want, float) and np.isnan(want)):
        assert got is None or (isinstance(got, float) and np.isnan(got))
    else:
        assert got == pytest.approx(want, rel=1e-9, abs=1e-9)
