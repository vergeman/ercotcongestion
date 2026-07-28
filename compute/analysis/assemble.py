"""Assemble the per-day brief from a forecast_sf_artifact.

``build_brief`` is the one entry point the job calls: it wires the finding
families (F1–F5a) over every hour of one day's SF + μ̂ and folds them into the
persisted document shape (docs/daily_brief_engine.md "Output shape"):

    brief = {
      provenance: {run_id, delivery_date, horizon, artifact_date, mu_basis, ...},
      hours: { <iso hour>: {constraints, hotspots, hub_dipole, best_pair,
                            after_action}, ... },
      day:   {daily_ranks, peak_hours, watchlist},
    }

Per hour, each F1 constraint carries its F2 node extrema and F3 shape stats; the
hour also gets F4 hotspots and the F5a hub dipole. ``best_pair`` (F5b) and
``after_action`` (F6) are placeholders here — later commits fill them. The day
roll-up is the "what to look at tomorrow" filter: whole-day constraint ranks,
the peak hours, and the constraints/nodes that recur across the day.

Everything is a pure function of the artifact, so a rebuild is deterministic.
Floats are rounded once at the end to keep the stored JSON compact and stable.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import cast

import pandas as pd

from compute.analysis.brief import (
    TOP_K_CONSTRAINTS,
    WATCHLIST_MIN_HOURS,
    nodal_congestion,
)
from compute.analysis.families import (
    canonical_hubs,
    common_nodes,
    constraint_node_extrema,
    constraint_stats,
    hour_ranked_constraints,
    hub_dipole,
    nodal_hotspots,
    sf_reach,
    split_constraint_key,
)


def _round(obj, ndigits: int = 4):
    """Recursively round floats in a JSON-ish structure; leave everything else."""
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, ndigits) for v in obj]
    return obj


def _hour_entry(reach, E_mu, SF, hour, metadata, hubs, top_k):
    """One hour: F1 constraints (+F2 nodes, +F3 stats), F4 hotspots, F5a dipole."""
    mu = E_mu.loc[hour]
    cong = nodal_congestion(SF, mu)

    constraints = hour_ranked_constraints(reach, E_mu, hour, top_k=top_k)
    extrema_by_key = {}
    for finding in constraints:
        key = finding["constraint_key"]
        sf_row = SF.loc[key]
        nodes = constraint_node_extrema(sf_row, mu[key], metadata)
        extrema_by_key[key] = nodes
        finding["nodes"] = nodes
        finding["stats"] = constraint_stats(sf_row, mu[key])

    return {
        "constraints": constraints,
        "hotspots": nodal_hotspots(cong, SF, mu),
        "common_nodes": common_nodes(extrema_by_key),
        "hub_dipole": hub_dipole(cong, SF, mu, hubs),
        "best_pair": None,      # F5b — later commit
        "after_action": None,   # F6 — filled when DAM lands
    }


def _day_rollup(reach, E_mu, hour_entries: Mapping[str, dict], top_k: int,
                min_hours: int) -> dict:
    """Whole-day ranks, peak hours, and the recurring-item watchlist."""
    daily_score = E_mu.abs().sum(axis=0) * reach
    ranked = sorted(daily_score.index, key=lambda k: (-float(daily_score[k]), str(k)))
    daily_ranks = []
    for rank, key in enumerate(ranked[:top_k], start=1):
        name, contingency = split_constraint_key(key)
        daily_ranks.append({
            "constraint_key": str(key), "constraint_name": name,
            "contingency_name": contingency,
            "daily_score": float(daily_score[key]), "daily_rank": rank,
        })

    # Peak hours: the hour whose top constraint has the largest footprint, and
    # the hour with the widest hub dipole.
    peak_hour_score = max(
        hour_entries,
        key=lambda h: (hour_entries[h]["constraints"][0]["hour_score"]
                       if hour_entries[h]["constraints"] else 0.0),
    )
    peak_dipole = max(hour_entries, key=lambda h: hour_entries[h]["hub_dipole"]["spread"])

    # Watchlist: constraints in the F1 top-K, and hotspot nodes, that recur in
    # ≥ min_hours hours across the day.
    constraint_hours: Counter = Counter()
    node_hours: Counter = Counter()
    for entry in hour_entries.values():
        for c in entry["constraints"]:
            constraint_hours[c["constraint_key"]] += 1
        for h in entry["hotspots"]:
            node_hours[h["settlement_point"]] += 1
    watch_constraints = sorted(
        ({"constraint_key": k, "hours": n} for k, n in constraint_hours.items()
         if n >= min_hours),
        key=lambda d: (-d["hours"], d["constraint_key"]),
    )
    watch_nodes = sorted(
        ({"settlement_point": k, "hours": n} for k, n in node_hours.items()
         if n >= min_hours),
        key=lambda d: (-d["hours"], d["settlement_point"]),
    )

    return {
        "daily_ranks": daily_ranks,
        "peak_hours": {"by_hour_score": peak_hour_score, "by_dipole_spread": peak_dipole},
        "watchlist": {"constraints": watch_constraints, "nodes": watch_nodes},
    }


def build_brief(SF: pd.DataFrame, E_mu: pd.DataFrame, metadata: Mapping[str, Mapping],
                *, run_id: str, delivery_date, horizon: int = 1,
                artifact_date=None, mu_basis: str = "forecast",
                top_k: int = TOP_K_CONSTRAINTS,
                watchlist_min_hours: int = WATCHLIST_MIN_HOURS) -> dict:
    """Build the full brief document for one delivery day.

    ``SF`` (constraints × SPs) and ``E_mu`` (hours × constraints) are the decoded
    artifact; ``metadata`` maps SP → attributes for node labeling. The hours axis
    is taken from ``E_mu.index`` in order.
    """
    reach = sf_reach(SF)
    hubs = canonical_hubs(SF.columns)

    hours = {
        pd.Timestamp(hour).isoformat(): _hour_entry(
            reach, E_mu, SF, hour, metadata, hubs, top_k)
        for hour in E_mu.index
    }
    day = _day_rollup(reach, E_mu, hours, top_k, watchlist_min_hours)

    brief: dict = {
        "provenance": {
            "run_id": str(run_id),
            "delivery_date": str(delivery_date),
            "horizon": int(horizon),
            "artifact_date": str(artifact_date) if artifact_date is not None else None,
            "mu_basis": mu_basis,
            "n_constraints": int(SF.shape[0]),
            "n_settlement_points": int(SF.shape[1]),
            "n_hours": int(len(E_mu.index)),
            "dam_match_coverage": None,   # set by F6 after-action
        },
        "hours": hours,
        "day": day,
    }
    return cast(dict, _round(brief))
