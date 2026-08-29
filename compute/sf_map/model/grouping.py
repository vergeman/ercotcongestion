"""Collinear grouping of co-binding constraints.

STATUS: INACTIVE IN PRODUCTION.

The 63-week ablation at the adopted ``(window_days=240, refit_days=7,
lambda=1.0)`` operating point found that grouping improved fair cross-window SF
stability by only +0.003 to +0.006 (depending on ``rho_min``), far below the
pre-registered +0.10 bar. Accuracy guards passed, but the groups were too small
(1.09–1.18× compression) for the collinearity fix to address the dominant
source of drift: changing congestion regimes. Keep this module for evaluation
and diagnostics; the production ``weekly_map`` runner leaves ``rho_min=None``
and fits raw constraint columns.

Constraints that co-bind within a fit window are collinear columns of ``M``.
Only the mass-weighted sum ``Σ_c a_c·SF[c, sp]`` over such a block is
identifiable; the ridge's split of that sum across the block's members is
arbitrary and flips between refits.

The fix is 'aggregate-then-fit': cluster the μ columns, sum each block into one
composite column ``m_g[h] = Σ_{c∈g} μ[h, c]``, and solve the existing ridge on
the reduced panel.

    link    = constraint_linkage(M_window)      # expensive, once per window
    labels  = cut_groups(link, rho_min=0.8)     # cheap, once per threshold
    M_g     = aggregate_mu(M_window, labels)
    members = group_members(M_window, labels)   # persistence / the explorer

"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage as scipy_linkage
from scipy.spatial.distance import squareform

# Below this many binding hours in the window a column has no usable correlation
# with anything; it stays a singleton rather than merging on noise.
MIN_CORR_HOURS = 2


def mu_mass(M: pd.DataFrame) -> pd.Series:
    """Per-constraint sum mu; μ-mass over the window: ``Σ_h |μ[h, c]|``.

    """
    return M.abs().sum(axis=0)


@dataclass
class ConstraintLinkage:
    """Z is the hierarchical clustering tree encoded as a NumPy array.

    For n input constraints, it has n - 1 rows and four columns:

    [left_child, right_child, merge_distance, number_of_members]

    Example with three constraints A, B, C:

    Z =
    [
      [0, 1, 0.10, 2],   # merge A and B at distance 0.10
      [2, 3, 0.70, 3],   # merge C with the A+B cluster at distance 0.70
    ]

    """
    Z: np.ndarray          # SciPy linkage tree over 1 − correlation.
    keys: pd.Index         # Clusterable constraints, in Z's row order.
    singletons: pd.Index   # Window-inactive (non-binding) constraints held out of the tree.
    mass: pd.Series        # Per-constraint μ-mass; names groups by dominant member.
    linkage: str           # Linkage method used to build Z.


def constraint_corr(M: pd.DataFrame) -> np.ndarray:
    """Calculates pairwise constraint correlations from M

    if M looks like (hour x constraints, mu)
      hour       μ_A    μ_B    μ_C
       1          100     90      0
       2          200    180     50
       3            0      0     10

    the pairwise correlation looks like: constraint x constraint

                   A       B       C
         A       1.00    0.99    0.20
         B       0.99    1.00    0.15
         C       0.20    0.15    1.00


    ``np.corrcoef`` (BLAS) rather than ``DataFrame.corr`` (pairwise): at ~1,000
    constraints × ~5,800 hours the pandas path costs ~30s per call, and the rho
    sweep calls this once per refit window.

    Columns that never bind, or bind too few hours to correlate with anything,
    come back as 0 (so distance 1) rather than NaN, so they can only ever be
    singletons.

    """
    X = M.to_numpy(dtype=float) # hours x constraint, mu

    # rowVar=False: each column is the variable, calculate pearson correlation
    # with every column pair

    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(X, rowvar=False)

    # convert to float, and ensure corr is a matrix (even if only a single
    # constraint). copy() means in-place modification is safe.
    corr = np.atleast_2d(np.asarray(corr, dtype=float)).copy()
    corr[~np.isfinite(corr)] = 0.0  # set runaway values to 0.0

    # thin: of binding hours, count column wise (axis=0) - label constraint as
    # thin (bool), set those constraints in corr matrix to 0, and set diagonal
    # (same constraints) to 1

    thin = ((M != 0).sum(axis=0) < MIN_CORR_HOURS).to_numpy()
    corr[thin, :] = 0.0
    corr[:, thin] = 0.0
    np.fill_diagonal(corr, 1.0)
    return corr


def constraint_linkage(
    M: pd.DataFrame, linkage: str = "complete"
) -> ConstraintLinkage:
    """Build the clustering tree for one window.

    Only window-active columns enter the tree. ``M`` is keyed by every
    constraint in the loaded history — 8,445 of them over 2.5 years — but
    inside any one 240-day window most never bind, and a column with fewer than
    ``MIN_CORR_HOURS`` binding hours has no usable correlation and is not
    grouped anyway.

    Clustering them means an 8,445² correlation per window instead of ~3,900²,
    for provably identical labels. So the held-out columns are recorded in
    ``singletons`` and mapped to themselves by ``cut_groups``.

    """
    all_keys = pd.Index(M.columns)
    mass = mu_mass(M)  # per constraint, sum all mu per hour. Series of constraint, mu sum values

    # NB: active_mask MIN_CORR_HOURS is over entire 240d window - low bar
    active_mask = ((M != 0).sum(axis=0) >= MIN_CORR_HOURS).to_numpy()
    keys = all_keys[active_mask]
    singletons = all_keys[~active_mask]  # non-binders in window

    if len(keys) <= 1:
        return ConstraintLinkage(Z=np.empty((0, 4)), keys=keys,
                                 singletons=all_keys.difference(keys),
                                 mass=mass, linkage=linkage)

    #
    # correlation matrix for eligible constraints, then converts it to distance:
    #
    dist = np.clip(1.0 - constraint_corr(M[keys]), 0.0, 2.0)

    # squareform demands an exactly symmetric, zero-diagonal matrix; corrcoef
    # can leave float asymmetry in the last bit.
    dist = (dist + dist.T) / 2.0   # avg floating point noise
    np.fill_diagonal(dist, 0.0)    # set distance to same point to 0

    # squareform is scipy pairwise distance format - convert to that
    # scipy_linkage: distances to Z - the hierarhical clustering tree as an
    # array

    Z = scipy_linkage(squareform(dist, checks=False), method=linkage)
    return ConstraintLinkage(Z=Z, keys=keys, singletons=singletons,
                             mass=mass, linkage=linkage)


def cut_groups(link: ConstraintLinkage, rho_min: float) -> pd.Series:
    """Cut the tree at ``rho_min``. Returns constraint_key → group_key.

    ``rho_min >= 1.0`` short-circuits to the identity mapping (every constraint
    its own group). Requiring corr ≥ 1 to merge means no merging.

    Group key = the group's highest-μ-mass member's ``constraint_key`` (ties
    broken lexicographically, so the labeling is deterministic).

    """
    keys = link.keys
    all_keys = keys.append(link.singletons)
    if len(keys) <= 1 or rho_min >= 1.0:
        return pd.Series(all_keys, index=all_keys, dtype=object)

    # fcluster: flat clusters from hierarchical
    # labels indicate group membership
    #
    # keys:   A B C D
    # labels: 1 1 2 3

    labels = fcluster(link.Z, t=1.0 - rho_min, criterion="distance")
    mass = link.mass  # mu
    out = pd.Series(index=all_keys, dtype=object)
    # Window-inactive columns were held out of the tree; they are singletons by
    # construction, so they key to themselves.
    out.loc[link.singletons] = link.singletons

    # loop through each group, build out: keys => group
    for lab in np.unique(labels):
        members = keys[labels == lab]
        ranked = sorted(members, key=lambda k: (-float(mass[k]), str(k)))  # mu then lex
        out.loc[members] = ranked[0]   # key to (top) representative member of group
    return out

def aggregate_mu(M: pd.DataFrame, labels: pd.Series) -> pd.DataFrame:
    """Sum ``M``'s columns within each group: ``(hours × groups)``.

    ``m_g[h] = Σ_{c∈g} μ[h, c]`` — the mass-preserving aggregation, so a group's
    column carries exactly the μ-mass of its members and coverage means the same
    thing before and after grouping.

    Columns of ``M`` absent from ``labels`` are dropped.

    Group columns are sorted so the panel's column order is deterministic.

    M =
    hour     A     B     C
    h1      10     5     2
    h2      20    10     0

    and labels says:

    A → A
    B → A
    C → C

    So A and B are one group, named A.

    The result is:

    grouped =
    hour     A     C
    h1      15     2
    h2      30     0

    """
    if M.empty or labels.empty:
        return pd.DataFrame(index=M.index)

    cols = M.columns.intersection(labels.index)   # constraints
    if len(cols) == 0:
        return pd.DataFrame(index=M.index)

    lab = labels.loc[cols]                        # group assignments
    if lab.is_unique:                             # no grouping, no sum needed
        return M if len(cols) == M.shape[1] else M[cols]

    #
    # aggregation
    # M transpose -> constraint x hour
    # lab.to_numpy() drops the index, so get an array of group labels
    # groupby - groups rows (hence the double transpose to return back original dims)
    # sum mu across cols (hours  in this case) per group
    #
    grouped = M[cols].T.groupby(lab.to_numpy()).sum().T
    grouped.columns.name = None
    return grouped.reindex(columns=sorted(grouped.columns))


def project_sf(SF: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Project an *ungrouped* SF into the group row-space. The fair-drift control.

    ``SF_proj[g, sp] = Σ_{c∈g} w_c · SF[c, sp]``, with ``w_c`` the within-group
    μ-mass shares — i.e. exactly the combination that is identifiable under
    collinearity, which is the whole reason the group is the fit's unit.

    Why S2 needs this: correlating a ~950-row grouped SF against a ~1,020-row
    ungrouped SF is not an apples-to-apples stability test — the grouped matrix
    would look steadier partly just for being smaller and better-conditioned.
    Projecting the *ungrouped* fit into the same group row-space isolates "did
    grouping stabilize the estimate" from "we changed the object".

    Members absent from ``SF`` (dropped by ``min_hours``) are excluded and the
    remaining shares renormalized, so a group is represented by the members the
    ungrouped fit actually estimated. Groups with no surviving member are
    dropped.
    """
    if SF.empty or members.empty:
        return pd.DataFrame(columns=SF.columns)

    m = members[members["constraint_key"].isin(SF.index)].copy()
    if m.empty:
        return pd.DataFrame(columns=SF.columns)
    totals = m.groupby("group_key")["mu_mass_share"].transform("sum")
    sizes = m.groupby("group_key")["mu_mass_share"].transform("size")
    w = np.where(totals > 0, m["mu_mass_share"] / totals, 1.0 / sizes)

    W = pd.DataFrame({"group_key": m["group_key"].to_numpy(), "w": w},
                     index=m["constraint_key"].to_numpy())
    weighted = SF.loc[W.index].mul(W["w"].to_numpy(), axis=0)
    out = weighted.groupby(W["group_key"].to_numpy()).sum()
    out.index.name = None
    return out.reindex(sorted(out.index))


def group_members(M: pd.DataFrame, labels: pd.Series) -> pd.DataFrame:
    """Group membership with within-group μ-mass shares.

    Returns ``(group_key, constraint_key, mu_mass_share)``, shares summing to 1
    within each group. Two consumers: the persistence side (expand a group key
    back to its members) and the fair-drift control in ``eval`` (project an
    ungrouped SF into the group row-space by mass-weighted average).

    A group whose members all carry zero mass in the window splits its share
    uniformly rather than dividing by zero.
    """
    if M.empty or labels.empty:
        return pd.DataFrame(
            columns=["group_key", "constraint_key", "mu_mass_share"]
        )
    cols = M.columns.intersection(labels.index)
    mass = mu_mass(M[cols])
    df = pd.DataFrame({
        "group_key": labels.loc[cols].to_numpy(),
        "constraint_key": cols.to_numpy(),
        "mu_mass": mass.loc[cols].to_numpy(dtype=float),
    })
    totals = df.groupby("group_key")["mu_mass"].transform("sum")
    sizes = df.groupby("group_key")["mu_mass"].transform("size")
    df["mu_mass_share"] = np.where(totals > 0, df["mu_mass"] / totals, 1.0 / sizes)
    df = df.drop(columns=["mu_mass"]).sort_values(
        ["group_key", "constraint_key"], ignore_index=True
    )
    return df
