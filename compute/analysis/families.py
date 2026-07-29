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

from compute.analysis.brief import (
    SF_MEANINGFUL,
    TOP_K_CONSTRAINTS,
    TOP_N_HOTSPOTS,
    TOP_N_NODES,
    pair_contributions,
)

# The canonical liquid trading points ERCOT settles against. They live in the
# SF artifact by name (``HB_*`` hubs, ``LZ_*`` load zones) even though the
# geocoded SP metadata omits them, so F5a reads them straight from the artifact
# and never inherits ``api/matrix.py:_sp_metadata``'s geocode-only filter.
HUB_LZ_PREFIXES = ("HB_", "LZ_")
# ``*AVG`` hubs are bus/hub *averages* — aggregates, not locations — so they can
# never be a dipole endpoint.
HUB_AVG_EXCLUDE = frozenset({"HB_BUSAVG", "HB_HUBAVG"})

# F5b endpoint-type gate. The doc's intended set is {hub, LZ, RN, gen, storage},
# but the geocoded metadata's `sp_type` vocabulary is {hub, load_zone, RN, PCCRN,
# PUN, OTHER} — and the recognizable resource nodes the walkthrough headlined
# (OLNEYTN, LGW, CFLATS) are typed OTHER. A literal hubs-only allowlist would drop
# them, exactly the failure `last_mile.md` warns against ("important localized
# resource-node separations would disappear"). So the default gate is inclusive —
# any *typed* SP qualifies — and the junk it excludes is the untyped tail; callers
# can pass a stricter `allowed_types` once a real day demands it.
PAIR_COORD_ROUND = 4        # ~11 m; the granularity at which two SPs are "the same place"


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


# --- F5a — hub/LZ dipole (always emitted) ----------------------------------

def canonical_hubs(settlement_points) -> list[str]:
    """The hub/LZ settlement points present in the artifact, ``*AVG`` excluded.

    Read from the artifact's own SP vocabulary by name — no metadata lookup — so
    the fixed, liquid endpoint set is always available regardless of geocode
    coverage. Returns ~12–13 keys, sorted for determinism.
    """
    return sorted(
        str(sp) for sp in settlement_points
        if str(sp).startswith(HUB_LZ_PREFIXES) and str(sp) not in HUB_AVG_EXCLUDE
    )


def hub_dipole(cong: pd.Series, SF: pd.DataFrame, mu: pd.Series,
               hubs: list[str] | None = None,
               top_drivers: int = TOP_K_CONSTRAINTS) -> dict:
    """Project congestion onto the canonical hubs and read the spread.

    Reports the min and max hub, the spread between them, the full per-hub
    congestion vector, and the top constraint drivers of ``max − min`` (a pair
    waterfall that sums exactly to the spread). This is the one-sentence market
    read; because the endpoint set is fixed and liquid it needs no guardrails.

    ``cong`` is the day's full nodal-congestion vector (computed once per hour);
    ``SF``/``mu`` supply the two endpoint columns for the driver waterfall.
    """
    if hubs is None:
        hubs = canonical_hubs(cong.index)
    hub_cong = cong.reindex([h for h in hubs if h in cong.index]).sort_values()
    if hub_cong.empty:
        return {"min": None, "max": None, "spread": 0.0, "hubs": [], "drivers": []}

    lo, hi = str(hub_cong.index[0]), str(hub_cong.index[-1])
    spread = float(hub_cong.iloc[-1] - hub_cong.iloc[0])
    drivers = pair_contributions(SF, mu, sink=hi, source=lo)
    ranked = drivers.reindex(drivers.abs().sort_values(ascending=False).index)

    driver_list = []
    for key in ranked.index[:top_drivers]:
        name, contingency = split_constraint_key(key)
        driver_list.append({
            "constraint_key": str(key),
            "constraint_name": name,
            "contingency_name": contingency,
            "contribution": float(ranked[key]),
            "share": (float(ranked[key]) / spread) if spread else 0.0,
        })

    return {
        "min": {"settlement_point": lo, "cong": float(hub_cong.iloc[0])},
        "max": {"settlement_point": hi, "cong": float(hub_cong.iloc[-1])},
        "spread": spread,
        "hubs": [{"settlement_point": str(h), "cong": float(hub_cong[h])}
                 for h in hub_cong.index],
        "drivers": driver_list,
    }


# --- F4 — nodal hotspots and common nodes ----------------------------------

def nodal_hotspots(cong: pd.Series, SF: pd.DataFrame, mu: pd.Series,
                   top_n: int = TOP_N_HOTSPOTS,
                   top_drivers: int = TOP_N_NODES) -> list[dict]:
    """Top settlement points by ``|cong[sp]|``, each decomposed into constraints.

    ``cong`` is the forecast (μ̂-basis) nodal congestion — the same reconstructed
    operator F5 uses, so a node's ``net`` congestion equals the sum of its
    per-constraint contributions exactly. Each hotspot also reports
    ``gross = Σ_c |k[c, sp]|`` alongside ``net = Σ_c k[c, sp] = cong[sp]``: a big
    gross with a small net is a *cancellation* node (constraints fighting over
    one location), itself a finding. ``net_gross_ratio`` near 1 is pure
    reinforcement, near 0 heavy cancellation — labeling is left to the reader.
    """
    ranked = cong.reindex(cong.abs().sort_values(ascending=False).index)

    hotspots = []
    for sp in ranked.index[:top_n]:
        k = -SF[sp] * mu                       # per-constraint contribution to sp
        gross = float(k.abs().sum())
        net = float(k.sum())                   # == cong[sp]
        by_mag = k.reindex(k.abs().sort_values(ascending=False).index)
        drivers = []
        for ckey in by_mag.index[:top_drivers]:
            name, contingency = split_constraint_key(ckey)
            drivers.append({
                "constraint_key": str(ckey),
                "constraint_name": name,
                "contingency_name": contingency,
                "contribution": float(by_mag[ckey]),
                "share": (float(by_mag[ckey]) / net) if net else 0.0,
            })
        hotspots.append({
            "settlement_point": str(sp),
            "cong": float(cong[sp]),
            "gross": gross,
            "net": net,
            "net_gross_ratio": (abs(net) / gross) if gross else 0.0,
            "drivers": drivers,
        })
    return hotspots


def common_nodes(f2_results: Mapping[str, dict], min_count: int = 2) -> list[dict]:
    """Settlement points in the F2 top-N of ``≥ min_count`` constraints.

    These confluence points are where independent constraints stack on one
    location — the natural map anchors for the hour. ``f2_results`` maps a
    constraint key to its ``constraint_node_extrema`` output; a node is counted
    once per constraint (its SF sign fixes which side it lands on). Ranked by how
    many constraints touch it, then by total absolute contribution.
    """
    by_sp: dict[str, list[dict]] = {}
    for constraint_key, extrema in f2_results.items():
        for side in ("import", "export"):
            for node in extrema.get(side, []):
                by_sp.setdefault(node["settlement_point"], []).append({
                    "constraint_key": str(constraint_key),
                    "side": side,
                    "sf": node["sf"],
                    "contribution": node["contribution"],
                })

    common = []
    for sp, entries in by_sp.items():
        constraints = sorted({e["constraint_key"] for e in entries})
        if len(constraints) >= min_count:
            common.append({
                "settlement_point": sp,
                "count": len(constraints),
                "constraints": constraints,
                "total_abs_contribution": float(sum(abs(e["contribution"]) for e in entries)),
                "entries": entries,
            })
    common.sort(key=lambda d: (-d["count"], -d["total_abs_contribution"], d["settlement_point"]))
    return common


# --- F5b — best source→sink pair (guarded) ---------------------------------

def _cluster_representatives(candidates: list[str], cong: pd.Series,
                             metadata: Mapping[str, Mapping],
                             coord_round: int) -> list[str]:
    """Collapse geographic duplicates: one representative per coordinate cluster.

    SPs sharing a rounded ``(lat, lon)`` are the same electrical location (138 such
    clusters on June 30), so a raw max would keep re-reporting the same place under
    different IDs. Each cluster keeps its strongest member (max ``|cong|``, key as
    the deterministic tie-break); an SP without a geocode is its own singleton.
    """
    clusters: dict[tuple, list[str]] = {}
    for sp in candidates:
        meta = metadata.get(sp) or {}
        lat, lon = meta.get("lat"), meta.get("lon")
        key = (round(float(lat), coord_round), round(float(lon), coord_round)) \
            if lat is not None and lon is not None else ("nogeo", sp)
        clusters.setdefault(key, []).append(sp)
    return [max(members, key=lambda s: (abs(float(cong[s])), s))
            for members in clusters.values()]


def _endpoint(sp: str, cong: pd.Series, metadata: Mapping[str, Mapping]) -> dict:
    meta = metadata.get(sp) or {}
    return {
        "settlement_point": str(sp),
        "cong": float(cong[sp]),
        "sp_type": meta.get("sp_type"),
        "load_zone": meta.get("load_zone"),
        "lat": meta.get("lat"),
        "lon": meta.get("lon"),
    }


def best_pair(cong: pd.Series, SF: pd.DataFrame, mu: pd.Series,
              metadata: Mapping[str, Mapping], *,
              dam_sp_coverage: set | None = None,
              exclude_sps: set | None = None,
              allowed_types: frozenset | None = None,
              coord_round: int = PAIR_COORD_ROUND,
              top_drivers: int = TOP_K_CONSTRAINTS) -> dict | None:
    """The best quality-gated source→sink separation for one hour, or ``None``.

    Because ``cong`` is one scalar per SP, ``max |cong[b] − cong[a]|`` is just
    ``max(cong) − min(cong)`` over the eligible set, so the "pair search" is an
    argmax/argmin, not an O(N²) scan. Guardrails, applied in order:

    1. **type gate** — keep SPs whose ``sp_type`` is in ``allowed_types`` (default:
       any typed SP; see ``PAIR_COORD_ROUND`` note on why not a hubs-only list);
    2. **DAM coverage** — when ``dam_sp_coverage`` is given, both endpoints must be
       in it, so an after-action SPP spread is always computable (skipped, and
       flagged, before DAM publishes);
    3. **F5a suppression** — ``exclude_sps`` (the hub dipole's endpoints) are
       dropped so F5b never re-tells F5a's story;
    4. **duplicate clustering** — one representative per coordinate cluster.

    Ranked by absolute forecast spread. Returns the pair, its driver waterfall
    (summing exactly to the spread), the dominant driver's share, and the guardrail
    provenance; ``None`` when fewer than two SPs survive the gates.
    """
    exclude_sps = exclude_sps or set()
    candidates = []
    for sp in cong.index:
        sp = str(sp)
        if sp in exclude_sps:
            continue
        sp_type = (metadata.get(sp) or {}).get("sp_type")
        if allowed_types is None:
            if sp_type is None:
                continue                       # default gate: require a known type
        elif sp_type not in allowed_types:
            continue
        if dam_sp_coverage is not None and sp not in dam_sp_coverage:
            continue
        candidates.append(sp)

    reps = _cluster_representatives(candidates, cong, metadata, coord_round)
    if len(reps) < 2:
        return None

    rep_cong = cong.reindex(reps)
    sink, source = str(rep_cong.idxmax()), str(rep_cong.idxmin())
    spread = float(rep_cong[sink] - rep_cong[source])

    drivers = pair_contributions(SF, mu, sink=sink, source=source)
    ranked = drivers.reindex(drivers.abs().sort_values(ascending=False).index)
    driver_list = []
    for key in ranked.index[:top_drivers]:
        name, contingency = split_constraint_key(key)
        driver_list.append({
            "constraint_key": str(key), "constraint_name": name,
            "contingency_name": contingency,
            "contribution": float(ranked[key]),
            "share": (float(ranked[key]) / spread) if spread else 0.0,
        })

    return {
        "sink": _endpoint(sink, cong, metadata),
        "source": _endpoint(source, cong, metadata),
        "spread": spread,
        "dominance_share": (float(ranked.iloc[0]) / spread) if spread else 0.0,
        "drivers": driver_list,
        "guardrails": {
            "n_candidates": len(candidates),
            "n_clusters": len(reps),
            "dam_coverage_checked": dam_sp_coverage is not None,
            "f5a_suppressed": sorted(exclude_sps),
        },
    }
