"""``rolling_bp(skip_window_starts=...)`` — the incremental-append hook.

A boundary whose ``window_start`` is in the skip set must be fit-free, score-free,
and callback-free; every other boundary must be byte-identical to a full run. This
is what lets the map runner recompute only the windows it does not already have
(plan 0092) — the correctness rests on ``window_start`` fully determining the fit.
"""
import numpy as np
import pandas as pd

from compute.sf.rolling import RefitWindow, rolling_bp

WINDOW_DAYS = 14
REFIT_DAYS = 7
MIN_HOURS = 5


def _panels():
    """A congestion panel generated from a known SF so every fit is non-empty.

    Three constraints bind on ~30% of hours; ``C = -M · SFᵀ`` over four SPs, so
    each 14-day window clears ``min_hours`` and ``implied_shift_factors`` returns a
    non-empty matrix (the skip logic is what we exercise, not fit accuracy).
    """
    rng = np.random.default_rng(0)
    idx = pd.date_range("2025-01-01", periods=40 * 24, freq="h", tz="UTC")
    n = len(idx)
    cons = ["A|c", "B|c", "C|c"]
    M = pd.DataFrame(
        {c: np.clip(rng.normal(0, 200, n) * (rng.random(n) < 0.30), 0, None)
         for c in cons},
        index=idx,
    )
    sps = ["SP0", "SP1", "SP2", "SP3"]
    sf_true = rng.normal(0, 0.2, size=(len(cons), len(sps)))
    C = pd.DataFrame(-(M.to_numpy() @ sf_true), index=idx, columns=sps)
    return M, C


def _run(M, C, skip):
    fired: list[RefitWindow] = []
    bp = rolling_bp(
        M, C,
        window_days=WINDOW_DAYS, refit_days=REFIT_DAYS, min_hours=MIN_HOURS,
        on_refit_window=fired.append,
        skip_window_starts=skip,
    )
    return bp, fired


def test_skip_omits_exactly_the_target_window():
    M, C = _panels()

    bp_full, fired_full = _run(M, C, skip=None)
    # Pick a middle boundary that actually produced scored rows — not warmup,
    # not the (possibly clamped) tail whose window_start could alias another.
    target = fired_full[len(fired_full) // 2]
    target_ns = pd.Timestamp(target.window_start).value

    bp_skip, fired_skip = _run(M, C, skip=frozenset({target_ns}))

    # The callback fired for every boundary except the skipped one.
    starts_full = [pd.Timestamp(w.window_start).value for w in fired_full]
    starts_skip = [pd.Timestamp(w.window_start).value for w in fired_skip]
    assert target_ns in starts_full
    assert target_ns not in starts_skip
    assert starts_skip == [s for s in starts_full if s != target_ns]

    # The skipped panel equals the full panel with exactly the target window's
    # scored hours removed — no other boundary's output shifted.
    dropped = bp_full.loc[
        (bp_full.index >= target.score_start) & (bp_full.index < target.score_end)
    ]
    assert not dropped.empty
    expected = bp_full.drop(index=dropped.index)
    pd.testing.assert_frame_equal(bp_skip, expected)


def test_skip_none_matches_default():
    M, C = _panels()
    bp_default, _ = _run(M, C, skip=None)
    bp_empty, _ = _run(M, C, skip=frozenset())
    pd.testing.assert_frame_equal(bp_default, bp_empty)
