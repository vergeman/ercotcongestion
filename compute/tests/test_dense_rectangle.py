"""Unit tests for the dense-rectangle sweep in ``compute.matrix``.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \
        /compute/tests/test_dense_rectangle.py -v
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from compute.matrix import (
    SP_COVERAGE_STRATEGIES,
    _first_dense_hour,
    _select_dense_rectangle,
)


REF_METHODS = ["m1", "m2"]


def _timestamps(n: int) -> list[datetime]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [base + timedelta(hours=i) for i in range(n)]


def _dense_bus_C(n_bus: int, n_hours: int) -> dict[str, np.ndarray]:
    """model_C with no structural NaN — buses are already filtered upstream."""
    return {m: np.zeros((n_bus, n_hours), dtype=float) for m in REF_METHODS}


def _sp_C_from_first_dense(
    first_dense: list[int], n_hours: int,
) -> dict[str, np.ndarray]:
    """ercot_C where each SP is NaN in ALL methods before ``first_dense[i]``.

    Any value at or after the first-dense hour is finite (0.0). This is the
    canonical monotonic-coverage shape used by the sweep.
    """
    n_sp = len(first_dense)
    out: dict[str, np.ndarray] = {}
    for m in REF_METHODS:
        arr = np.zeros((n_sp, n_hours), dtype=float)
        for i, fd in enumerate(first_dense):
            arr[i, :fd] = np.nan
        out[m] = arr
    return out


# ---------------------------------------------------------------------------
# _first_dense_hour helper
# ---------------------------------------------------------------------------

def test_first_dense_hour_monotonic():
    missing = np.array([
        [False, False, False, False],  # dense throughout
        [True,  False, False, False],  # first-dense = 1
        [True,  True,  True,  False],  # first-dense = 3
    ])
    out = _first_dense_hour(missing)
    assert list(out) == [0, 1, 3]


def test_first_dense_hour_non_monotonic_uses_last_nan():
    # NaN in the middle → conservative: rectangle must start after the gap.
    missing = np.array([
        [False, True, False, False, True, False, False],
    ])
    out = _first_dense_hour(missing)
    assert list(out) == [5]  # last NaN at col 4 → first_dense = 5


def test_first_dense_hour_empty_rows():
    out = _first_dense_hour(np.zeros((0, 10), dtype=bool))
    assert out.shape == (0,)


# ---------------------------------------------------------------------------
# _select_dense_rectangle — strategy behavior
# ---------------------------------------------------------------------------

def test_fully_dense_input_no_drops():
    n_hours = 24
    sp_ids = ["sp_a", "sp_b", "sp_c"]
    ts = _timestamps(n_hours)
    model_C = _dense_bus_C(4, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 0, 0], n_hours)

    new_ts, new_model, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=0.90,
    )
    assert new_ts == ts
    assert new_sp_ids == sp_ids
    for m in REF_METHODS:
        assert new_model[m].shape == (4, n_hours)
        assert new_ercot[m].shape == (3, n_hours)


def test_one_late_sp_is_dropped_by_max_area():
    n_hours = 100
    # sp_late doesn't come online until hour 90 → keeping it costs 90 hours.
    # Dropping it (k=2) gives area = 2 * 100 = 200, vs k=3 → 3 * 10 = 30.
    sp_ids = ["sp_a", "sp_b", "sp_late"]
    ts = _timestamps(n_hours)
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 0, 90], n_hours)

    new_ts, _, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=0.5,
    )
    assert set(new_sp_ids) == {"sp_a", "sp_b"}
    assert len(new_ts) == n_hours
    for m in REF_METHODS:
        assert new_ercot[m].shape == (2, n_hours)
        assert not np.isnan(new_ercot[m]).any()


def test_ladder_max_area_picks_argmax_of_product():
    # 5 SPs, first-dense at hours [0, 10, 20, 30, 90] out of 100.
    # areas: k=1 → 1*100=100, k=2 → 2*90=180, k=3 → 3*80=240,
    #        k=4 → 4*70=280, k=5 → 5*10=50 → argmax at k=4.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = [f"sp_{i}" for i in range(5)]
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 10, 20, 30, 90], n_hours)

    new_ts, _, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=0.0,
    )
    assert len(new_sp_ids) == 4
    assert set(new_sp_ids) == {"sp_0", "sp_1", "sp_2", "sp_3"}
    assert len(new_ts) == 70  # n_hours - 30
    for m in REF_METHODS:
        assert new_ercot[m].shape == (4, 70)
        assert not np.isnan(new_ercot[m]).any()


def test_max_hours_prefers_hour_axis_over_area():
    # Same ladder as above, but max_hours picks the k with the most hours
    # subject to the SP floor. With min_sp_fraction=0.0 the argmax over
    # hours_kept alone is k=1 (100 hours).
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = [f"sp_{i}" for i in range(5)]
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 10, 20, 30, 90], n_hours)

    _, _, _, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_hours", min_sp_fraction=0.0,
    )
    assert new_sp_ids == ["sp_0"]


def test_min_sp_fraction_floor_prevents_stripping_row_axis():
    # Same ladder — argmax area is at k=4, but with min_sp_fraction=1.0 we
    # must keep all 5. That reproduces the k=5 (10 hours) outcome.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = [f"sp_{i}" for i in range(5)]
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 10, 20, 30, 90], n_hours)

    new_ts, _, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=1.0,
    )
    assert len(new_sp_ids) == 5
    assert len(new_ts) == 10
    for m in REF_METHODS:
        assert new_ercot[m].shape == (5, 10)
        assert not np.isnan(new_ercot[m]).any()


def test_non_monotonic_sp_treated_conservatively():
    # sp_gap is NaN at a middle hour (index 50) but dense elsewhere.
    # The rectangle must start after that gap → first_dense = 51.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = ["sp_dense", "sp_gap"]
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 0], n_hours)
    for m in REF_METHODS:
        ercot_C[m][1, 50] = np.nan

    new_ts, _, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=1.0,
    )
    # Both SPs kept (floor=1.0), hour cutoff advanced past the gap.
    assert new_sp_ids == ["sp_dense", "sp_gap"]
    assert len(new_ts) == 49  # hours 51..99 inclusive
    for m in REF_METHODS:
        assert not np.isnan(new_ercot[m]).any()


def test_threshold_strategy_reproduces_all_or_nothing():
    # Old behavior: keep every SP, drop hours before the last SP came online.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = [f"sp_{i}" for i in range(5)]
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 10, 20, 30, 90], n_hours)

    new_ts, _, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="threshold", min_sp_fraction=0.90,
    )
    assert new_sp_ids == sp_ids  # nothing dropped
    assert len(new_ts) == 10     # n_hours - 90
    for m in REF_METHODS:
        assert new_ercot[m].shape == (5, 10)
        assert not np.isnan(new_ercot[m]).any()


def test_all_nan_method_on_ercot_side_is_ignored():
    # Simulates system_lambda_merit_order_ercot_C — a method whose ercot
    # matrix is entirely NaN because it isn't computed on that side. The
    # sweep must treat it as absent, not as an unsatisfiable constraint.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = ["sp_a", "sp_b"]
    model_C = _dense_bus_C(2, n_hours)
    ercot_C = _sp_C_from_first_dense([0, 0], n_hours)
    # Wipe m2 on the SP side entirely.
    ercot_C["m2"][:] = np.nan

    new_ts, _, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=0.90,
    )
    assert new_sp_ids == sp_ids
    assert len(new_ts) == n_hours
    # m1 (the viable one) stays dense on the kept slice.
    assert not np.isnan(new_ercot["m1"]).any()


def test_all_nan_method_on_model_side_is_ignored():
    # Simulates system_lambda_model_C — 100% NaN on the model side.
    # Sweep must not drop every column just because that method is empty.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = ["sp_a"]
    model_C = _dense_bus_C(3, n_hours)
    model_C["m2"][:] = np.nan  # method absent on model side
    ercot_C = _sp_C_from_first_dense([0], n_hours)

    new_ts, new_model, _, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=1.0,
    )
    assert new_sp_ids == sp_ids
    assert len(new_ts) == n_hours
    # m1 stays dense on the kept slice.
    assert not np.isnan(new_model["m1"]).any()


def test_bus_side_gap_drops_column_not_shift_start():
    # A late-window column where every bus is structurally NaN (reference
    # prices missing at that ts) must be dropped as a column — not turned
    # into a start-cutoff shift that would zero out the whole window.
    n_hours = 100
    ts = _timestamps(n_hours)
    sp_ids = ["sp_a", "sp_b"]
    model_C = _dense_bus_C(3, n_hours)
    # All buses NaN in every method at the last hour.
    for m in REF_METHODS:
        model_C[m][:, 99] = np.nan
    ercot_C = _sp_C_from_first_dense([0, 0], n_hours)

    new_ts, new_model, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, REF_METHODS,
        strategy="max_area", min_sp_fraction=0.90,
    )
    assert new_sp_ids == sp_ids
    assert len(new_ts) == 99
    assert new_ts[-1] == ts[98]  # the dropped hour was the last, not sliced from start
    for m in REF_METHODS:
        assert new_model[m].shape == (3, 99)
        assert new_ercot[m].shape == (2, 99)
        assert not np.isnan(new_model[m]).any()
        assert not np.isnan(new_ercot[m]).any()


def test_unknown_strategy_raises():
    ts = _timestamps(10)
    with pytest.raises(ValueError):
        _select_dense_rectangle(
            ts, _dense_bus_C(1, 10),
            _sp_C_from_first_dense([0], 10),
            ["sp_a"], REF_METHODS,
            strategy="not_a_real_strategy",
        )


def test_strategies_constant_is_advertised():
    # Regression guard so the CLI ``choices=`` list stays in sync.
    assert set(SP_COVERAGE_STRATEGIES) == {"max_area", "max_hours", "threshold"}


def test_empty_ref_methods_is_noop():
    ts = _timestamps(5)
    sp_ids = ["a", "b"]
    model_C: dict[str, np.ndarray] = {}
    ercot_C: dict[str, np.ndarray] = {}
    new_ts, new_model, new_ercot, new_sp_ids = _select_dense_rectangle(
        ts, model_C, ercot_C, sp_ids, [],
    )
    assert new_ts == ts and new_sp_ids == sp_ids
    assert new_model is model_C and new_ercot is ercot_C
