"""Unit tests for distributed-slack PTDF and binding_proximity_at.

Reproduces the Texas2k slack-bus artifact on a minimal 3-bus radial network:
with the slack at the leaf, PyPSA's single-slack PTDF gives every non-slack
column ~identical, so binding_proximity collapses to a single value. The
distributed-slack shift restores per-bus spread.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \
        /compute/test_binding_proximity.py -v
"""
import numpy as np
import pandas as pd
import pypsa
import pytest

from ptdf_lodf import distribute_slack, get_ptdf_lodf
from congestion.metrics import binding_proximity_at


def _radial_3bus() -> pypsa.Network:
    """Slack at leaf bus 'C' with a single line C-B and a load line B-A.

    Topology mirrors the Texas2k pathology: the slack bus is only connected to
    the rest of the grid through one branch. Single-slack PTDF should give
    every non-slack bus |PTDF[C-B, .]| == 1 on that branch.
    """
    n = pypsa.Network()
    n.set_snapshots(pd.DatetimeIndex(['2025-01-01']))
    for name, control in [('A', 'PQ'), ('B', 'PQ'), ('C', 'Slack')]:
        n.add('Bus', name, v_nom=345.0, control=control)
    n.add('Line', 'AB', bus0='A', bus1='B', x=0.05, r=0.0,
          s_nom=100.0, s_max_pu=1.0)
    n.add('Line', 'BC', bus0='B', bus1='C', x=0.05, r=0.0,
          s_nom=100.0, s_max_pu=1.0)
    return n


def test_distribute_slack_kills_slack_projection():
    """Hd @ w == 0: injecting per the slack distribution induces zero flow.

    This is the defining property of the distributed-slack shift and is what
    the PTDF sanity check in binding_proximity_diagnostics indirectly relies
    on to spot regressions.
    """
    rng = np.random.default_rng(0)
    H = rng.standard_normal((5, 4))
    w = np.array([0.1, 0.2, 0.3, 0.4])
    Hd = distribute_slack(H, w)
    proj = Hd @ w
    assert np.allclose(proj, 0.0, atol=1e-12)


def test_distribute_slack_uniform_equals_row_mean_shift():
    rng = np.random.default_rng(1)
    H = rng.standard_normal((6, 8))
    w = np.full(8, 1.0 / 8)
    Hd = distribute_slack(H, w)
    expected = H - H.mean(axis=1, keepdims=True)
    assert np.allclose(Hd, expected, atol=1e-14)


def test_distribute_slack_rejects_bad_weights():
    H = np.zeros((3, 4))
    with pytest.raises(ValueError):
        distribute_slack(H, np.array([0.25, 0.25, 0.25]))       # wrong length
    with pytest.raises(ValueError):
        distribute_slack(H, np.array([0.1, 0.2, 0.3, 0.5]))     # sums to 1.1
    with pytest.raises(ValueError):
        distribute_slack(H, np.array([np.nan, 0.5, 0.25, 0.25]))


def test_binding_proximity_collapses_under_single_slack_radial():
    """Reproduces the Texas2k artifact on a 3-bus toy network.

    With the slack at the leaf (bus C) and line BC saturating, single-slack
    binding_proximity for every non-slack bus should collapse to the same
    value — because |PTDF_single[BC, ·]| == 1 across the whole non-slack
    population when BC is the only path to the slack.
    """
    n = _radial_3bus()
    ptdf, _lodf, bus_names = get_ptdf_lodf(n)

    # Load bus A at 90 MW → line AB and BC both carry 90 MW toward slack C.
    line_p0 = pd.Series({'AB': 90.0, 'BC': 90.0})
    line_s_max_pu = None
    tx_p0 = pd.Series(dtype=float)
    tx_s_max_pu = None

    bp_single = binding_proximity_at(
        n, line_p0, tx_p0, line_s_max_pu, tx_s_max_pu,
        ptdf, bus_names,
    )
    # Non-slack buses A and B should get identical BP under single slack.
    non_slack = [b for b in bus_names if b != 'C']
    assert bp_single.loc[non_slack].nunique() == 1


def test_binding_proximity_recovers_spread_under_distributed_slack():
    n = _radial_3bus()
    ptdf, _lodf, bus_names = get_ptdf_lodf(n)

    line_p0 = pd.Series({'AB': 90.0, 'BC': 90.0})
    tx_p0 = pd.Series(dtype=float)

    # Load-weighted slack: all load is at A → w concentrates on A.
    idx = {b: i for i, b in enumerate(bus_names)}
    w = np.zeros(len(bus_names))
    w[idx['A']] = 1.0

    bp_dist = binding_proximity_at(
        n, line_p0, tx_p0, None, None,
        ptdf, bus_names, slack_weights=w,
    )
    # Under distributed slack the two non-slack buses no longer share a value:
    # A (where load lives) drives the line, B is only a pass-through node.
    non_slack = [b for b in bus_names if b != 'C']
    assert bp_dist.loc[non_slack].nunique() >= 2
