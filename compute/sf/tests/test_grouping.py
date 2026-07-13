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
    project_sf,
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


def test_inactive_columns_do_not_change_the_grouping(planted):
    """The real panel is keyed by every constraint in the loaded history (~8,445
    over 2.5 years), but inside one 240d window most never bind. Those are held
    out of the clustering tree — an ~3,900² correlation instead of 8,445² — on
    the claim that they are forced singletons anyway. This is that claim: padding
    the panel with quiet columns must not move a single label."""
    M, _ = planted
    padded = M.copy()
    for i in range(25):
        padded[f"QUIET{i}|C"] = 0.0
    padded["ONE_HOUR|C"] = 0.0
    padded.iloc[3, padded.columns.get_loc("ONE_HOUR|C")] = 250.0

    base = group_constraints(M, rho_min=RHO)
    padded_labels = group_constraints(padded, rho_min=RHO)

    # Original constraints: labels unchanged.
    pd.testing.assert_series_equal(base, padded_labels.loc[base.index],
                                   check_names=False)
    # Padding columns: present, and each its own group.
    for i in range(25):
        assert padded_labels[f"QUIET{i}|C"] == f"QUIET{i}|C"
    assert padded_labels["ONE_HOUR|C"] == "ONE_HOUR|C"
    assert padded_labels.nunique() == base.nunique() + 26


def test_linkage_holds_out_inactive_columns(planted):
    M, _ = planted
    link = constraint_linkage(M)
    assert "E_never|C" in link.singletons     # never binds
    assert "F_thin|C" in link.singletons      # one binding hour
    assert "A0|C" in link.keys
    assert set(link.keys) | set(link.singletons) == set(M.columns)


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


def test_aggregate_mu_identity_labels_return_the_panel_untouched(planted):
    """When nothing merges, the aggregate must be the panel *itself* — not a
    groupby-sum round trip. The rebuild changes the array's memory layout, which
    changes BLAS reduction order in the ridge and shifts the solution by ~1e-13.
    That is enough to make rho_min=1.0 a non-exact no-op, which would confound
    every grouped-vs-ungrouped comparison in the R3 measurement."""
    M, _ = planted
    identity = group_constraints(M, rho_min=1.0)
    Mg = aggregate_mu(M, identity)
    assert Mg is M                                   # same object, no copy
    assert list(Mg.columns) == list(M.columns)       # original order preserved


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


# ------------------------------------------------------------------ projection

def _fake_sf(keys, n_sp=4) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    return pd.DataFrame(rng.normal(0, 0.3, (len(keys), n_sp)),
                        index=pd.Index(keys), columns=[f"SP{i}" for i in range(n_sp)])


def test_project_sf_is_the_mass_weighted_member_average(planted):
    M, _ = planted
    labels = group_constraints(M, rho_min=RHO)
    members = group_members(M, labels)
    SF = _fake_sf(M.columns)

    proj = project_sf(SF, members)
    assert list(proj.index) == sorted(labels.unique())

    a_key = labels["A0|C"]
    w = members[members.group_key == a_key].set_index("constraint_key")["mu_mass_share"]
    expected = SF.loc[w.index].mul(w, axis=0).sum()
    assert np.allclose(proj.loc[a_key].to_numpy(), expected.to_numpy())


def test_project_sf_singleton_group_is_the_constraint_itself(planted):
    M, _ = planted
    labels = group_constraints(M, rho_min=RHO)
    SF = _fake_sf(M.columns)
    proj = project_sf(SF, group_members(M, labels))
    assert np.allclose(proj.loc["C0|C"].to_numpy(), SF.loc["C0|C"].to_numpy())


def test_project_sf_renormalizes_over_members_the_fit_kept(planted):
    """`min_hours` drops constraints from the ungrouped SF. A group must then be
    represented by the members that were actually estimated — not diluted toward
    zero by missing rows."""
    M, _ = planted
    labels = group_constraints(M, rho_min=RHO)
    members = group_members(M, labels)
    a_key = labels["A0|C"]

    survivors = [k for k in M.columns if k != "A1|C"]      # drop one A member
    SF = _fake_sf(survivors)
    proj = project_sf(SF, members)

    w = members[(members.group_key == a_key)
                & (members.constraint_key != "A1|C")].set_index("constraint_key")
    w = w["mu_mass_share"] / w["mu_mass_share"].sum()      # renormalized
    expected = SF.loc[w.index].mul(w, axis=0).sum()
    assert np.allclose(proj.loc[a_key].to_numpy(), expected.to_numpy())


def test_project_sf_drops_groups_with_no_surviving_member(planted):
    M, _ = planted
    labels = group_constraints(M, rho_min=RHO)
    members = group_members(M, labels)
    SF = _fake_sf([k for k in M.columns if k != "C0|C"])
    assert "C0|C" not in project_sf(SF, members).index
