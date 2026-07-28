"""Finding families — pure re-ranking over the full SF+μ̂ artifact.

Families 1–5 are pure functions of the forecast; 6 activates when DAM lands.
This module holds F1–F3, the "re-ranking" families that fix the screen problem
at the data layer (docs/daily_brief_engine.md):

* **F1** ranks a day's constraints two ways at once — by this hour's footprint
  and by the whole day's mass — because "rank 1 this hour" and "rank 2 all day"
  are different statements that the single displayed rank used to conflate.
* **F2** returns the *global* strongest import/export nodes for a constraint,
  from the full artifact rather than the bounded matrix frame (the inspector's
  visible-columns lie).
* **F3** describes a constraint's shape — breadth vs concentration — with the
  quantitative descriptors both June-30 walkthroughs converged on. Archetype
  *labels* are derived later, never stored as the primary fact.

Every family returns plain JSON-serializable dicts; rounding is left to the
serving layer, matching the matrix API.
"""
from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from compute.analysis.brief import SF_MEANINGFUL, TOP_K_CONSTRAINTS, TOP_N_NODES


def split_constraint_key(key: object) -> tuple[str, str | None]:
    """``"NAME|CONTINGENCY"`` → ``("NAME", "CONTINGENCY")``; no bar → (name, None)."""
    name, sep, contingency = str(key).partition("|")
    return name, (contingency if sep else None)


def sf_reach(SF: pd.DataFrame) -> pd.Series:
    """Per-constraint footprint ``Σ_sp |SF[c, sp]|``.

    Static across the day (one SF matrix per delivery day), so the engine
    computes it once and reuses it for every hour's F1 ranking.
    """
    return SF.abs().sum(axis=1)


def _ranked_keys(scores: pd.Series) -> list:
    """Constraint keys by descending score, ties broken by key for determinism."""
    return sorted(scores.index, key=lambda k: (-float(scores[k]), str(k)))


def _rank_map(scores: pd.Series) -> dict:
    return {k: i for i, k in enumerate(_ranked_keys(scores), start=1)}


# --- F1 — hour-ranked constraints (the screen) -----------------------------

def hour_ranked_constraints(reach: pd.Series, E_mu: pd.DataFrame, hour,
                            top_k: int = TOP_K_CONSTRAINTS) -> list[dict]:
    """Top-``top_k`` constraints for ``hour`` with both hour and daily ranks.

    ``hour_score[c] = |μ̂[c, hour]| × reach[c]`` is the exact-hour footprint;
    ``daily_score[c] = (Σ_hours |μ̂[c]|) × reach[c]`` is the whole-day mass. Both
    ranks are reported so the two are never conflated (the 107__B lesson: hour
    rank 1, daily rank 2, and "looks weak on screen" are three statements).
    """
    mu_hour = E_mu.loc[hour]
    hour_score = mu_hour.abs() * reach
    daily_score = E_mu.abs().sum(axis=0) * reach
    hour_rank = _rank_map(hour_score)
    daily_rank = _rank_map(daily_score)

    findings = []
    for key in _ranked_keys(hour_score)[:top_k]:
        name, contingency = split_constraint_key(key)
        findings.append({
            "constraint_key": str(key),
            "constraint_name": name,
            "contingency_name": contingency,
            "mu": float(mu_hour[key]),
            "hour_score": float(hour_score[key]),
            "hour_rank": hour_rank[key],
            "daily_score": float(daily_score[key]),
            "daily_rank": daily_rank[key],
        })
    return findings


# --- F2 — per-constraint node extrema (the "N nodes") ----------------------

def _node(sp: object, sf: float, contribution: float,
          metadata: Mapping[str, Mapping] | None) -> dict:
    meta = (metadata or {}).get(str(sp)) or {}
    return {
        "settlement_point": str(sp),
        "sf": float(sf),
        "contribution": float(contribution),
        "sp_type": meta.get("sp_type"),
        "load_zone": meta.get("load_zone"),
        "lat": meta.get("lat"),
        "lon": meta.get("lon"),
    }


def constraint_node_extrema(sf_row: pd.Series, mu_c: float,
                            metadata: Mapping[str, Mapping] | None = None,
                            top_n: int = TOP_N_NODES,
                            threshold: float = SF_MEANINGFUL) -> dict:
    """Global top-``top_n`` import (SF<0) and export (SF>0) nodes for one
    constraint, ranked by ``|k| = |SF| × |μ|`` over the *full* SF row.

    ``k[c, sp] = -SF[c, sp] × μ[c]`` — so import-side cells (SF<0) contribute
    positively when μ>0. Only members with ``|SF| ≥ threshold`` are eligible; a
    one-sided constraint therefore returns fewer than ``top_n`` on its thin side
    rather than padding with noise.
    """
    mu_c = float(mu_c)
    meaningful = sf_row.abs() >= threshold

    def side(sign_mask: pd.Series) -> list[dict]:
        cells = sf_row[sign_mask & meaningful]
        order = sorted(cells.index,
                       key=lambda sp: (-abs(float(cells[sp])), str(sp)))[:top_n]
        return [_node(sp, float(cells[sp]), -float(cells[sp]) * mu_c, metadata)
                for sp in order]

    return {"import": side(sf_row < 0), "export": side(sf_row > 0)}


# --- F3 — constraint archetype stats (breadth vs concentration) ------------

def constraint_stats(sf_row: pd.Series, mu_c: float,
                     threshold: float = SF_MEANINGFUL) -> dict:
    """Quantitative shape descriptors for one constraint (no archetype label).

    Reports side balance, reach, concentration (top-5 share, peak/p95 |SF|), and
    the constraint's best internal separation (``max_contrast`` = its most
    export-side minus most import-side node, valued at |μ|). Labels
    (*broad/systemic*, *strong separator*, *localized pocket*) are derived from
    these downstream once stable across days — never stored here.
    """
    mu_c = float(mu_c)
    abs_sf = sf_row.abs()
    total = float(abs_sf.sum())
    meaningful_mask = abs_sf >= threshold
    imp = abs_sf[(sf_row < 0) & meaningful_mask]
    exp = abs_sf[(sf_row > 0) & meaningful_mask]
    meaningful_vals = abs_sf[meaningful_mask]
    top5 = float(abs_sf.sort_values(ascending=False).head(5).sum())

    return {
        "reach": int(meaningful_mask.sum()),
        "import_count": int(len(imp)),
        "import_sf_sum": float(imp.sum()),
        "export_count": int(len(exp)),
        "export_sf_sum": float(exp.sum()),
        "top5_share": (top5 / total) if total else 0.0,
        "peak_abs_sf": float(abs_sf.max()) if len(abs_sf) else 0.0,
        "p95_abs_sf": float(meaningful_vals.quantile(0.95)) if len(meaningful_vals) else 0.0,
        "max_contrast": {
            "value": float(abs(mu_c) * (float(sf_row.max()) - float(sf_row.min()))),
            "export_sp": str(sf_row.idxmax()),
            "import_sp": str(sf_row.idxmin()),
        },
    }
