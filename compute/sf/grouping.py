"""Collinear grouping of co-binding constraints (S2 / plan 0083).

Constraints that co-bind within a fit window are collinear columns of ``M``.
Only the mass-weighted sum ``Σ_c a_c·SF[c, sp]`` over such a block is
identifiable; the ridge's split of that sum across the block's members is
arbitrary and flips between refits. Every signed, named claim (node explorer,
error attribution) is therefore blocked until the fit's unit is a *group*.

The fix is **aggregate-then-fit**: cluster the μ columns, sum each block into
one composite column ``m_g[h] = Σ_{c∈g} μ[h, c]``, and solve the existing ridge
on the reduced panel. Averaging per-constraint SFs *after* the fit would leave
the arbitrary allocation inside the solve and fix nothing.

Pure functions over a window's ``M`` — no I/O, no DB. ``fit.py`` is untouched;
callers (``rolling``, ``eval``) map ``M → M_g`` before handing it to the ridge.

Two-stage API, because the correlation matrix and the linkage tree do not depend
on ``rho_min`` — only the *cut* does. The rho sweep (S2's whole point) would
otherwise recompute a ~1000×1000 correlation per threshold per refit window::

    link    = constraint_linkage(M_window)      # expensive, once per window
    labels  = cut_groups(link, rho_min=0.8)     # cheap, once per threshold
    M_g     = aggregate_mu(M_window, labels)
    members = group_members(M_window, labels)   # persistence / the explorer

``group_constraints`` bundles both stages for single-shot callers.
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
    """Per-constraint μ-mass over the window — ``Σ_h |μ[h, c]|``.

    The weight behind every ranking here: the dominant member that names a
    group, and the within-group shares in ``group_members``. Matches the mass
    definition ``eval.evaluate`` already uses for coverage, so "the group
    carries this constraint's mass" means the same thing on both sides.
    """
    return M.abs().sum(axis=0)


@dataclass
class ConstraintLinkage:
    """A window's clustering tree, cuttable at any ``rho_min``.

    ``Z`` is the scipy linkage over ``1 − corr``; ``keys`` are the constraint
    columns in ``Z``'s row order; ``mass`` is the per-constraint μ-mass used to
    name each group by its dominant member.
    """
    Z: np.ndarray
    keys: pd.Index
    mass: pd.Series
    linkage: str


def constraint_corr(M: pd.DataFrame) -> np.ndarray:
    """Correlation between ``M``'s columns over the window's rows.

    Taken over *all* rows, zeros included. The non-binding hours are real
    observations (NP4-191 publishes binding rows only, so absence is μ=0 by
    construction) and they are what conditions ``XᵀX`` — the matrix whose
    collinearity we are here to fix.

    ``np.corrcoef`` (BLAS) rather than ``DataFrame.corr`` (pairwise): at ~1,000
    constraints × ~5,800 hours the pandas path costs ~30s per call, and the rho
    sweep calls this once per refit window.

    Columns that never bind, or bind too few hours to correlate with anything,
    come back as 0 (→ distance 1, beyond any cut with ``rho_min > 0``) rather
    than NaN, so they can only ever be singletons.
    """
    X = M.to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(X, rowvar=False)
    corr = np.atleast_2d(np.asarray(corr, dtype=float)).copy()
    corr[~np.isfinite(corr)] = 0.0

    thin = ((M != 0).sum(axis=0) < MIN_CORR_HOURS).to_numpy()
    corr[thin, :] = 0.0
    corr[:, thin] = 0.0
    np.fill_diagonal(corr, 1.0)
    return corr


def constraint_linkage(
    M: pd.DataFrame, linkage: str = "complete"
) -> ConstraintLinkage:
    """Build the clustering tree for one window. The expensive half."""
    keys = pd.Index(M.columns)
    mass = mu_mass(M)
    if M.shape[1] <= 1:
        return ConstraintLinkage(
            Z=np.empty((0, 4)), keys=keys, mass=mass, linkage=linkage
        )

    dist = np.clip(1.0 - constraint_corr(M), 0.0, 2.0)
    # squareform demands an exactly symmetric, zero-diagonal matrix; corrcoef
    # can leave float asymmetry in the last bit.
    dist = (dist + dist.T) / 2.0
    np.fill_diagonal(dist, 0.0)
    Z = scipy_linkage(squareform(dist, checks=False), method=linkage)
    return ConstraintLinkage(Z=Z, keys=keys, mass=mass, linkage=linkage)


def cut_groups(link: ConstraintLinkage, rho_min: float) -> pd.Series:
    """Cut the tree at ``rho_min``. Returns constraint_key → group_key.

    The cut is ``criterion="distance"`` at ``t = 1 − rho_min``. Under
    ``complete`` linkage that is a guarantee about every pair, not just the
    cluster average: **any two constraints in a group correlate at ≥ rho_min**.
    Which also means only positively-correlated columns ever merge (for
    ``rho_min > 0``), so a summed group column can never cancel itself out.

    ``rho_min >= 1.0`` short-circuits to the identity mapping (every constraint
    its own group). Requiring corr ≥ 1 to merge means no merging, and making
    that exact — rather than "merges only bit-identical columns" — gives callers
    a true no-op for A/B-ing the grouped path against the ungrouped one.

    Group key = the group's highest-μ-mass member's ``constraint_key`` (ties
    broken lexicographically, so the labeling is deterministic). Readable in the
    UI ("this block is basically <that constraint>"), and a singleton group keys
    to itself — so the ungrouped case is schema-identical to today and the
    ``implied_shift_factors.constraint_key`` TEXT column absorbs both.
    """
    keys = link.keys
    if len(keys) <= 1 or rho_min >= 1.0:
        return pd.Series(keys, index=keys, dtype=object)

    labels = fcluster(link.Z, t=1.0 - rho_min, criterion="distance")
    mass = link.mass
    out = pd.Series(index=keys, dtype=object)
    for lab in np.unique(labels):
        members = keys[labels == lab]
        ranked = sorted(members, key=lambda k: (-float(mass[k]), str(k)))
        out.loc[members] = ranked[0]
    return out


def group_constraints(
    M: pd.DataFrame, rho_min: float, linkage: str = "complete"
) -> pd.Series:
    """Single-shot convenience: build the tree and cut it once."""
    return cut_groups(constraint_linkage(M, linkage=linkage), rho_min)


def aggregate_mu(M: pd.DataFrame, labels: pd.Series) -> pd.DataFrame:
    """Sum ``M``'s columns within each group → ``(hours × groups)``.

    ``m_g[h] = Σ_{c∈g} μ[h, c]`` — the mass-preserving aggregation, so a group's
    column carries exactly the μ-mass of its members and coverage means the same
    thing before and after grouping.

    Columns of ``M`` absent from ``labels`` are dropped. That is the intended
    behavior at *score* time: ``labels`` come from the fit window, and a
    constraint that shows up in the scored week without ever appearing in the
    fit window has no SF column to score against either — it is exactly the
    novel μ-mass that ``coverage`` is there to report. Callers must therefore
    compute coverage against the raw ``M``, not this reduced panel.

    Group columns are sorted so the panel's column order is deterministic.
    """
    if M.empty or labels.empty:
        return pd.DataFrame(index=M.index)
    cols = M.columns.intersection(labels.index)
    if len(cols) == 0:
        return pd.DataFrame(index=M.index)
    grouped = M[cols].T.groupby(labels.loc[cols].to_numpy()).sum().T
    grouped.columns.name = None
    return grouped.reindex(columns=sorted(grouped.columns))


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
