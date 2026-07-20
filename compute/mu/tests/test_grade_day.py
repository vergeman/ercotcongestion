"""Tests for the `grade_day` live-grading job (plan 0102 / 0003-live-grading).

Deterministic and DB-free: every DB seam of `grade_day` (the served-forecast read,
the shadow-price / congestion loaders, the SF fit) is stubbed so the ORCHESTRATION
— the score grid, the common-node intersection, and which quantity each source is
scored on — is exercised against the SHARED metric (`score_matrix`) in
milliseconds. The reconciliation guarantee (spec §7) is proven structurally here:
`grade_day`'s per-source rows are asserted byte-equal to `score_matrix` recomputed
independently on the same Y / Yh, so a live number and a backtest number are the
same currency by construction. The null-guard (spec §6) — a flat map cannot
manufacture a screening score — and the fail-loud paths round it out.

Enough nodes (30) that `row_spearman` (needs ≥10) and `topdecile_hit` (≥20)
actually score rather than declining to NaN for want of width.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import compute.jobs.grade_day as gd
from compute.mu.score import mu_climatology, mu_null, mu_persistence, score_matrix
from compute.sf.eval import predict
from compute.sf.project import band_metrics

D = pd.Timestamp("2025-09-15", tz="UTC")      # an arbitrary UTC-midnight delivery day
SPS = [f"SP{i}" for i in range(30)]
KEYS = ["K0|c", "K1|c", "K2|c"]


def _scenario(seed: int = 0):
    """A fixed (M, C, SF, served-forecast) world. `point` and `p50` are deliberately
    distinct so a test can tell whether the model was scored on the deterministic
    point (correct) or the sampling median."""
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
    p50 = point + 1.0                    # distinct from point on purpose
    fc = {"point": point, "p10": p50 - 5, "p50": p50, "p90": p50 + 5}
    return M, C, SF, fc, hoursD


def _install(monkeypatch, M, C, SF, fc):
    monkeypatch.setattr(gd, "load_served_forecast", lambda conn, run_id, D_: fc)
    monkeypatch.setattr(gd, "load_shadow_prices", lambda conn, lo, hi: M)
    monkeypatch.setattr(gd, "load_congestion_panel", lambda conn, lo, hi: C)
    monkeypatch.setattr(gd, "implied_shift_factors", lambda *a, **k: SF)


# ---------------------------------------------------------------------------
# Reconciliation: every source row IS score_matrix on the same Y / Yh (spec §7)
# ---------------------------------------------------------------------------

def test_rows_reproduce_score_matrix_on_the_same_inputs(monkeypatch):
    M, C, SF, fc, hoursD = _scenario()
    _install(monkeypatch, M, C, SF, fc)

    rows = grade_rows(monkeypatch, M, C, SF, fc)
    by_src = {r["source"]: r for r in rows}
    assert set(by_src) == {"model", "oracle", "persistence", "climatology", "null"}

    hours = hoursD
    cols = M.loc[hours].columns
    Y = C.loc[hours, SPS].to_numpy(float)

    # model: the served deterministic point (NOT p50) — the discriminating check.
    want = score_matrix(Y, fc["point"].loc[hours, SPS].to_numpy(float))
    for k, v in want.items():
        _eq(by_src["model"][k], v)
    # p50 would give a different pooled_r2 — prove we did not use it.
    p50_r2 = score_matrix(Y, fc["p50"].loc[hours, SPS].to_numpy(float))["pooled_r2"]
    assert not np.isclose(by_src["model"]["pooled_r2"], p50_r2)

    # comparators: each mu source projected through SF, same metric.
    srcs = {
        "oracle": M.loc[hours],
        "persistence": mu_persistence(M, hours, cols),
        "climatology": mu_climatology(M.loc[M.index < D], hours, cols),
        "null": mu_null(hours, cols),
    }
    for name, Msrc in srcs.items():
        Yh = pd.DataFrame(predict(Msrc, SF), index=hours, columns=SF.columns)[SPS]
        want = score_matrix(Y, Yh.to_numpy(float))
        for k, v in want.items():
            _eq(by_src[name][k], v)


def test_model_carries_live_bands_comparators_do_not(monkeypatch):
    M, C, SF, fc, hoursD = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    rows = grade_rows(monkeypatch, M, C, SF, fc)
    by_src = {r["source"]: r for r in rows}

    Y = C.loc[hoursD, SPS].to_numpy(float)
    want = band_metrics(Y,
                        fc["p10"].loc[hoursD, SPS].to_numpy(float),
                        fc["p50"].loc[hoursD, SPS].to_numpy(float),
                        fc["p90"].loc[hoursD, SPS].to_numpy(float))
    for k in ("coverage80", "band_width", "pinball"):
        _eq(by_src["model"][k], want[k])
        assert 0.0 <= by_src["model"]["coverage80"] <= 1.0
    # Bands are a model-only, quantile quantity — NULL on every comparator.
    for name in ("oracle", "persistence", "climatology", "null"):
        for k in ("coverage80", "band_width", "pinball"):
            assert by_src[name][k] is None


def test_null_source_cannot_manufacture_a_screening_score(monkeypatch):
    """The integrity tripwire (spec §6): a flat map ranks nothing, so its screening
    cells are NaN — never a number that could read as skill. If this regresses, the
    whole live board is suspect."""
    M, C, SF, fc, _ = _scenario()
    _install(monkeypatch, M, C, SF, fc)
    rows = grade_rows(monkeypatch, M, C, SF, fc)
    null = next(r for r in rows if r["source"] == "null")
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
    monkeypatch.setattr(gd, "load_served_forecast", lambda conn, run_id, D_: {})
    with pytest.raises(RuntimeError, match="no served forecast"):
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
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _FakeCur(self._row)


def test_resolve_gradeable_date_normalizes_to_utc_midnight():
    import datetime as _dt
    D_ = gd.resolve_gradeable_date(_FakeConn((_dt.date(2025, 9, 15),)), "t")
    assert D_ == D


def test_resolve_gradeable_date_none_when_nothing_gradeable():
    assert gd.resolve_gradeable_date(_FakeConn(None), "t") is None


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
