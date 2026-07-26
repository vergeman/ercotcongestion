"""Grouping wired through the fit + eval paths (0083 commit 2).

The load-bearing tests here are the **no-ops**: `rho_min=None` and `rho_min=1.0`
must reproduce the ungrouped numbers exactly. If they don't, every grouped-vs-
ungrouped comparison in the R3 measurement is confounded by a wiring bug rather
than by the grouping itself.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/sf/tests/test_grouped_fit.py -v
"""
import numpy as np
import pandas as pd
import pytest

from compute.sf.eval import evaluate, evaluate_chunked
from compute.sf.grouping import group_constraints
from compute.sf.rolling import rolling_sf

METRICS = ["oos_pooled_r2", "is_pooled_r2", "rank_spearman", "sign_agree",
           "topdecile_hit", "coverage", "sf_stability", "n_kept"]


N_BLOCKS = 12
N_HOURS = 1500


@pytest.fixture
def panels():
    """(M, C) obeying the settlement identity C = −M·SFᵀ, so the ridge has a real
    signal to recover and the metrics are not noise.

    Wider than the `planted` fixture on purpose: `_sf_corr` needs ≥5 shared rows
    to return a stability number, so a panel with only a handful of kept groups
    reports NaN everywhere and the stability assertions below would pass
    vacuously. 12 blocks (some multi-member, some singleton) ≈ 28 constraints.
    """
    rng = np.random.default_rng(7)
    idx = pd.date_range("2025-01-01", periods=N_HOURS, freq="h", tz="UTC")

    cols = {}
    for b in range(N_BLOCKS):
        z = np.clip(rng.normal(0, 250, N_HOURS) * (rng.random(N_HOURS) < 0.35),
                    0, None)
        size = 1 + (b % 3)                      # blocks of 1, 2, 3 members
        for j in range(size):
            noise = np.where(z > 0, rng.normal(0, 4, N_HOURS), 0.0)
            cols[f"B{b}_{j}|C"] = z * (1.0 + 0.2 * j) + noise
    M = pd.DataFrame(cols, index=idx)

    sps = [f"SP{i}" for i in range(12)]
    SF_true = pd.DataFrame(rng.normal(0, 0.25, (M.shape[1], len(sps))),
                           index=M.columns, columns=sps)
    C = pd.DataFrame(-(M.to_numpy() @ SF_true.to_numpy()), index=idx, columns=sps)
    C += rng.normal(0, 0.5, C.shape)
    return M, C


# ------------------------------------------------------------------- no-ops

def test_evaluate_rho_min_one_is_a_noop(panels):
    """Bit-exact, not merely close. `topdecile_hit` ranks nodes by predicted
    congestion, so a 1e-13 wobble in the ridge solution is enough to reorder ties
    and move the metric — which is exactly how the layout-dependent version of
    this bug first showed up on real panels."""
    M, C = panels
    kw = dict(window_days=14, refit_days=7, lam=1.0, min_hours=10)
    base = evaluate(M, C, **kw)
    same = evaluate(M, C, rho_min=1.0, **kw)
    assert len(base) == len(same)
    for col in METRICS:
        a, b = base[col].to_numpy(float), same[col].to_numpy(float)
        assert np.array_equal(a, b, equal_nan=True), \
            f"{col} moved under the rho_min=1.0 no-op: {a} vs {b}"


def test_evaluate_grouped_emits_group_columns(panels):
    M, C = panels
    df = evaluate(M, C, window_days=14, refit_days=7, lam=1.0, min_hours=10,
                  rho_min=0.8)
    assert df["n_groups"].notna().all()
    # The planted blocks collapse ~28 constraints into 12 groups.
    assert (df["n_groups"] < df["n_constraints"]).all()
    assert df["group_churn"].iloc[1:].notna().all()   # first week has no prior


def test_n_constraints_means_the_same_thing_in_both_arms(panels):
    """`n_constraints` must count window-active constraints in BOTH arms. If the
    grouped arm counted every column of M while the ungrouped arm counted only
    post-min_hours survivors, the compression ratio the R3 verdict is read
    against would be comparing two different quantities."""
    M, C = panels
    kw = dict(window_days=14, refit_days=7, lam=1.0, min_hours=10)
    base = evaluate(M, C, **kw)
    grouped = evaluate(M, C, rho_min=0.8, **kw)

    np.testing.assert_array_equal(base["n_constraints"].to_numpy(),
                                  grouped["n_constraints"].to_numpy())
    # ...and it is neither the kept count nor the raw column count.
    assert (grouped["n_kept"] <= grouped["n_groups"]).all()
    assert (grouped["n_constraints"] <= M.shape[1]).all()


def test_evaluate_control_emits_projected_stability(panels):
    M, C = panels
    df = evaluate(M, C, window_days=14, refit_days=7, lam=1.0, min_hours=10,
                  rho_min=0.8, control=True)
    scored = df[df["sf_stability"].notna()]
    assert not scored.empty
    assert scored["sf_stability_proj"].notna().any()


def test_linkage_cache_does_not_change_results(panels):
    """The cache is a performance device for the rho sweep; it must be
    numerically invisible."""
    M, C = panels
    kw = dict(window_days=14, refit_days=7, lam=1.0, min_hours=10, rho_min=0.8)
    a = evaluate(M, C, **kw)
    b = evaluate(M, C, linkage_cache={}, **kw)
    for col in METRICS + ["n_groups", "group_churn"]:
        np.testing.assert_allclose(a[col].to_numpy(float), b[col].to_numpy(float),
                                   rtol=1e-12, equal_nan=True)


def test_chunked_evaluation_matches_the_full_history_run(panels):
    """Chunk boundaries are an allocation detail, not a scoring change."""
    M, C = panels
    window_days, refit_days = 14, 7
    start = M.index[0].normalize() + pd.Timedelta(days=2 * window_days)
    end = M.index[-1].normalize() + pd.Timedelta(days=1)
    kw = dict(window_days=window_days, refit_days=refit_days,
              lam=1.0, min_hours=10, rho_min=0.8)

    full = evaluate(M, C, **kw).reset_index(drop=True)

    def load_chunk(lo, hi):
        return (M.loc[(M.index >= lo) & (M.index < hi)],
                C.loc[(C.index >= lo) & (C.index < hi)])

    chunked = evaluate_chunked(load_chunk, score_from=start, end=end,
                               chunk_weeks=2, **kw)
    assert list(chunked["score_start"]) == list(full["score_start"])
    for col in METRICS + ["n_groups", "group_churn"]:
        np.testing.assert_allclose(chunked[col].to_numpy(float),
                                   full[col].to_numpy(float), rtol=1e-12,
                                   equal_nan=True)


# ------------------------------------------------------------------- callback

def test_refit_window_carries_labels_and_fit_panel(panels):
    M, C = panels
    seen = []
    rolling_sf(M, C, window_days=14, refit_days=7, lam=1.0, min_hours=10,
               rho_min=0.8, on_refit_window=seen.append)
    assert seen
    w = seen[0]
    # M_fit is the grouped panel and its columns are what SF's rows are keyed by
    # — that is the invariant runner's diagnostics depend on.
    assert w.labels is not None
    assert list(w.M_fit.columns) == sorted(w.labels.unique())
    assert set(w.SF.index) <= set(w.M_fit.columns)
    assert w.M_window.shape[1] > w.M_fit.shape[1]


def test_refit_window_ungrouped_fit_panel_is_the_raw_panel(panels):
    M, C = panels
    seen = []
    rolling_sf(M, C, window_days=14, refit_days=7, lam=1.0, min_hours=10,
               on_refit_window=seen.append)
    w = seen[0]
    assert w.labels is None
    assert w.M_fit is w.M_window


# ------------------------------------------------------------------- scoring

def test_novel_constraint_is_excluded_from_the_grouped_score(panels):
    """A constraint appearing only in the scored week has no group and no SF
    column. It must not crash the score path — it must land in the coverage gap."""
    M, C = panels
    M = M.copy()
    M["NOVEL|C"] = 0.0
    M.iloc[-24:, M.columns.get_loc("NOVEL|C")] = 500.0   # binds only at the end

    df = evaluate(M, C, window_days=14, refit_days=7, lam=1.0, min_hours=10,
                  rho_min=0.8)
    assert not df.empty
    assert (df["coverage"] <= 1.0 + 1e-9).all()
    assert df["coverage"].iloc[-1] < 1.0    # the novel mass is uncovered


def test_grouped_coverage_is_measured_against_the_raw_panel(panels):
    """Coverage denominators must be the same quantity in both arms, or the
    grouped/ungrouped comparison is meaningless."""
    M, C = panels
    kw = dict(window_days=14, refit_days=7, lam=1.0, min_hours=10)
    base = evaluate(M, C, **kw)
    grouped = evaluate(M, C, rho_min=0.8, **kw)
    # Same planted panel, no novel constraints: every constraint is in some kept
    # group, so coverage is 1.0 in both arms — not inflated by the aggregation.
    labels = group_constraints(M, rho_min=0.8)
    assert labels.nunique() < M.shape[1]
    np.testing.assert_allclose(base["coverage"].to_numpy(float),
                               grouped["coverage"].to_numpy(float),
                               rtol=1e-9, equal_nan=True)
