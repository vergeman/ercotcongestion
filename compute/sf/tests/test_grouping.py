"""Tests for the 0083 collinear-grouping primitive.

Run inside the compute container:
    docker compose run --rm compute python -m pytest \\
        /compute/sf/tests/test_grouping.py -v
"""
import numpy as np
import pandas as pd
import pytest

from compute.sf.grouping import (
    aggregate_mu,
    constraint_linkage,
    cut_groups,
    group_constraints,
    group_members,
)

RHO = 0.8
SWEEP = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]


def _blocks(labels: pd.Series) -> list[set]:
    return [set(g.index) for _, g in labels.groupby(labels)]


# ------------------------------------------------------------------ clustering

def test_recovers_planted_blocks(planted):
    M, expected = planted
    got = _blocks(group_constraints(M, rho_min=RHO))
    assert sorted(map(sorted, got)) == sorted(map(sorted, expected))


def test_exactly_collinear_pair_merges(planted):
    """D1 = 3·D0 — the degenerate case the ridge cannot separate at all."""
    M, _ = planted
    for rho in [r for r in SWEEP if r < 1.0]:
        labels = group_constraints(M, rho_min=rho)
        assert labels["D0|C"] == labels["D1|C"], f"failed to merge at rho={rho}"


def test_independent_constraint_never_merges(planted):
    M, _ = planted
    for rho in SWEEP:
        labels = group_constraints(M, rho_min=rho)
        assert (labels == labels["C0|C"]).sum() == 1, f"C0 merged at rho={rho}"


def test_degenerate_columns_stay_singletons(planted):
    """A never-binding column and a one-hour column have no usable correlation;
    they must not merge on noise."""
    labels = group_constraints(planted[0], rho_min=RHO)
    for key in ("E_never|C", "F_thin|C"):
        assert (labels == labels[key]).sum() == 1
        assert labels[key] == key


def test_complete_linkage_guarantee(planted):
    """The cut is a promise about every *pair*, not the cluster average: any two
    constraints sharing a group correlate at >= rho_min."""
    M, _ = planted
    corr = M.corr()
    labels = group_constraints(M, rho_min=RHO)
    for _, grp in labels.groupby(labels):
        members = sorted(grp.index)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                assert corr.loc[a, b] >= RHO - 1e-9


def test_rho_min_one_is_identity(planted):
    """The no-op the grouped/ungrouped A/B depends on."""
    M, _ = planted
    labels = group_constraints(M, rho_min=1.0)
    assert labels.nunique() == M.shape[1]
    assert (labels.index == labels.to_numpy()).all()


def test_n_groups_monotone_in_rho_min(planted):
    M, _ = planted
    counts = [group_constraints(M, rho_min=r).nunique() for r in SWEEP]
    assert counts == sorted(counts)


def test_group_named_for_dominant_member(planted):
    M, _ = planted
    mass = M.abs().sum()
    labels = group_constraints(M, rho_min=RHO)
    for key, grp in labels.groupby(labels):
        assert key == max(grp.index, key=lambda k: (mass[k], k))


def test_two_stage_matches_single_shot(planted):
    """The tree is built once per window and cut per threshold; that must agree
    with the single-shot path exactly, or the rho sweep is measuring a different
    object than the fit uses."""
    M, _ = planted
    link = constraint_linkage(M)
    for rho in SWEEP:
        assert cut_groups(link, rho).equals(group_constraints(M, rho))


def test_single_column_panel():
    M = pd.DataFrame({"only|C": [1.0, 0.0, 3.0]})
    labels = group_constraints(M, rho_min=RHO)
    assert labels.to_dict() == {"only|C": "only|C"}


# ------------------------------------------------------------------ aggregation

def test_aggregate_mu_is_the_member_sum(planted):
    M, _ = planted
    labels = group_constraints(M, rho_min=RHO)
    Mg = aggregate_mu(M, labels)
    assert Mg.shape == (M.shape[0], labels.nunique())
    a_key = labels["A0|C"]
    expected = M[["A0|C", "A1|C", "A2|C"]].sum(axis=1)
    assert np.allclose(Mg[a_key].to_numpy(), expected.to_numpy())


def test_aggregate_mu_preserves_mass(planted):
    """Mass-preserving aggregation is what lets coverage mean the same thing
    before and after grouping."""
    M, _ = planted
    Mg = aggregate_mu(M, group_constraints(M, rho_min=RHO))
    assert np.isclose(Mg.to_numpy().sum(), M.to_numpy().sum())


def test_aggregate_mu_columns_deterministic(planted):
    M, _ = planted
    Mg = aggregate_mu(M, group_constraints(M, rho_min=RHO))
    assert list(Mg.columns) == sorted(Mg.columns)


def test_aggregate_mu_drops_constraints_absent_from_labels(planted):
    """Score-time behavior: labels come from the fit window, so a constraint
    that first appears in the scored week has no group and no SF column — it is
    the novel μ-mass that `coverage` reports, not a new column to predict with."""
    M, _ = planted
    labels = group_constraints(M, rho_min=RHO)
    Mg = aggregate_mu(M, labels)

    M_score = M.copy()
    M_score["NOVEL|C"] = 42.0
    Mg_score = aggregate_mu(M_score, labels)

    assert "NOVEL|C" not in Mg_score.columns
    assert list(Mg_score.columns) == list(Mg.columns)


# ------------------------------------------------------------------ membership

def test_group_members_shares_sum_to_one(planted):
    M, _ = planted
    mem = group_members(M, group_constraints(M, rho_min=RHO))
    shares = mem.groupby("group_key")["mu_mass_share"].sum()
    assert np.allclose(shares.to_numpy(), 1.0)


def test_group_members_expands_to_full_constraint_set(planted):
    M, _ = planted
    mem = group_members(M, group_constraints(M, rho_min=RHO))
    assert len(mem) == M.shape[1]
    assert set(mem["constraint_key"]) == set(M.columns)


def test_group_members_zero_mass_group_splits_uniformly(planted):
    """E_never carries no mass; the share must not be a division by zero."""
    M, _ = planted
    mem = group_members(M, group_constraints(M, rho_min=RHO))
    assert mem["mu_mass_share"].notna().all()
    never = mem[mem["group_key"] == "E_never|C"]
    assert np.isclose(never["mu_mass_share"].sum(), 1.0)


@pytest.mark.parametrize("empty", [pd.DataFrame(), pd.DataFrame(index=[1, 2])])
def test_empty_panel_is_handled(empty):
    labels = pd.Series(dtype=object)
    assert aggregate_mu(empty, labels).empty
    assert group_members(empty, labels).empty
