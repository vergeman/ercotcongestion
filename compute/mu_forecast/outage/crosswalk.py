"""NP1-346 authoritative crosswalk — resource → settlement point. plan/0089 commit 1.

**This is the gate. Before any ingest.** The probe (`compute.probes.outage_feed`)
located outaged MW by *splitting underscores*: `Resource Unit Code` was assumed to BE a
settlement point (22.6% of MW), and a station-prefix heuristic patched it to 55.8% —
which is exactly the fuzzy matching R4 warns against (`B` from `B_DAVIS_B_DAVIG1`, 117
rows on stations that carry several settlement points). This module throws that away and
uses the **authoritative RESOURCE_NODE registries** the geocode layer already trusts
(`preprocess/geocode_ercot_layer.py`, `compute/mu/geo.py`), the same map that turns an
opaque key into a place without name matching.

**The one join that is authoritative and unambiguous.** ERCOT's `Resource Unit Code` is
`{UNIT_SUBSTATION}_{UNIT_NAME}`, and `Resource_Node_to_Unit` maps that pair straight to a
`RESOURCE_NODE` — the priced settlement point. No prefix guessing, no namespace to
reconcile: it is a lookup in ERCOT's own registry. Two weaker registry routes back it up
(the resource name is itself a priced SP; the resource name is a substation that resolves
to exactly one SP), and both are *registry* facts, not string heuristics.

**Gate C, pre-registered (the probe's bars, restated — R4's bar):**

    >= 60% of outage MW cleanly locatable -> BUILD the per-constraint covariate
    30-60%                                -> BUILD it, flagged, on the joinable subset,
                                             and report the unlocated MW every week
    <  30%                                -> DEAD: it degrades to `outages_zonal`, which
                                             we already have; this branch closes, no ingest

**By outage MW, never row count.** A crosswalk that reaches 95% of rows but only the
1-MW derates is worthless; the mass is in the thermal trips. Key/row count flatters — see
0088 — so every number here is denominated in `Effective MW Reduction Due to Outage`.

The executable coverage gate lives in `compute.probes.outage_crosswalk`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger("compute.mu_forecast.outage.crosswalk")

# Mirrors `compute.probes.outage_feed`, which is the pre-registered source of both. Kept
# as module constants here — rather than imported — so the pure crosswalk core carries no
# dependency on the probe's top-level ErcotClient import (network client). The probe's
# fetchers are pulled in lazily in main(), where the live run pays for them anyway.
MW = "Effective MW Reduction Due to Outage"
GATE_C_BUILD = 0.60     # >= this share of outage MW locatable -> BUILD
GATE_C_DEAD = 0.30      # <  this -> DEAD (degrade to outages_zonal)

# The authoritative registries, mounted at /data in the compute container (see
# docker-compose.yml `./data:/data`). Same directory geo.py and the geocode layer read.
REGISTRY_DIR = Path("/data/raw/ercot_geocode")
RN_UNIT_GLOB = "Resource_Node_to_Unit_*.csv"
SP_META_GLOB = "Settlement_Points_*.csv"


def _newest(dir_path: Path, glob: str) -> Path:
    """Newest file matching `glob` — the registries are datestamped snapshots."""
    files = sorted(dir_path.glob(glob))
    if not files:
        raise FileNotFoundError(f"no file matching {glob} in {dir_path}")
    return files[-1]


@dataclass
class Crosswalk:
    """Authoritative resource → settlement-point maps. All keys/values `.strip()`ed.

    `unitcode_to_sp` is the exact, unambiguous route (`Resource_Node_to_Unit`). The two
    substation maps are the registry-backed fallbacks, and each keeps **only** the
    substations that resolve to exactly one settlement point — an ambiguous substation is
    excluded, not guessed (the trap the probe's prefix heuristic fell into).
    """
    unitcode_to_sp: dict[str, str]
    substation_to_sp: dict[str, str]
    sp_registry: set[str] = field(default_factory=set)

    def locate(self, unit_code: object, resource_name: object,
               sp_universe: set[str]) -> tuple[str | None, str | None]:
        """Return (settlement_point, method) or (None, None). `sp_universe` is the SF
        map's own column set (priced SPs); a registry hit that the SF map does not price
        is *not* locatable, because there is nowhere to place its MW."""
        uc = str(unit_code).strip() if unit_code is not None else ""
        rn = str(resource_name).strip() if resource_name is not None else ""

        sp = self.unitcode_to_sp.get(uc)
        if sp and sp in sp_universe:
            return sp, "unitcode"
        if rn and rn in sp_universe:                    # the resource name is itself a SP
            return rn, "resname_sp"
        sp = self.substation_to_sp.get(rn)              # unique-substation fallback
        if sp and sp in sp_universe:
            return sp, "substation"
        return None, None


def load_crosswalk(registry_dir: Path = REGISTRY_DIR) -> Crosswalk:
    """Build the crosswalk from ERCOT's own registries. No fuzzy matching, no network.

    `Resource_Node_to_Unit` is the spine: `{UNIT_SUBSTATION}_{UNIT_NAME}` is exactly the
    report's `Resource Unit Code`, and `RESOURCE_NODE` is the settlement point. The
    substation fallback is assembled from both that file and `Settlement_Points`, keeping
    only substations that map to a single SP.
    """
    rn_unit = pd.read_csv(_newest(registry_dir, RN_UNIT_GLOB), dtype=str)
    for c in ("RESOURCE_NODE", "UNIT_SUBSTATION", "UNIT_NAME"):
        rn_unit[c] = rn_unit[c].fillna("").str.strip()

    unitcode_to_sp: dict[str, str] = {}
    for _, r in rn_unit.iterrows():
        if r["UNIT_SUBSTATION"] and r["UNIT_NAME"] and r["RESOURCE_NODE"]:
            unitcode_to_sp[f"{r['UNIT_SUBSTATION']}_{r['UNIT_NAME']}"] = r["RESOURCE_NODE"]

    # Substation -> the settlement points behind it, from both registries. Ambiguous
    # substations (>1 SP) are dropped, never guessed.
    sub_sps: dict[str, set[str]] = {}
    for sub, sp in zip(rn_unit["UNIT_SUBSTATION"], rn_unit["RESOURCE_NODE"]):
        if sub and sp:
            sub_sps.setdefault(sub, set()).add(sp)

    sp_meta = pd.read_csv(_newest(registry_dir, SP_META_GLOB), dtype=str)
    sp_meta["SUBSTATION"] = sp_meta["SUBSTATION"].fillna("").str.strip()
    sp_meta["RESOURCE_NODE"] = sp_meta["RESOURCE_NODE"].fillna("").str.strip()
    sp_registry = set(sp_meta.loc[sp_meta["RESOURCE_NODE"] != "", "RESOURCE_NODE"])
    sp_registry |= set(unitcode_to_sp.values())
    for sub, sp in zip(sp_meta["SUBSTATION"], sp_meta["RESOURCE_NODE"]):
        if sub and sp:
            sub_sps.setdefault(sub, set()).add(sp)

    substation_to_sp = {s: next(iter(v)) for s, v in sub_sps.items() if len(v) == 1}

    log.info("crosswalk: %d unit codes, %d unambiguous substations, %d SPs in registry",
             len(unitcode_to_sp), len(substation_to_sp), len(sp_registry))
    return Crosswalk(unitcode_to_sp, substation_to_sp, sp_registry)


def coverage(df: pd.DataFrame, xwalk: Crosswalk, sp_universe: set[str],
             mw_col: str = MW) -> dict:
    """Locate one outage snapshot and report coverage **by MW**.

    Returns located/total MW, the fraction, a by-method MW breakdown, a located
    settlement-point column aligned to `df`, and the biggest unlocated resources by MW —
    so the hole is visible rather than absorbed (the 30-60% flag rule).
    """
    located_sp, method = [], []
    for uc, rn in zip(df["Resource Unit Code"], df["Resource Name"]):
        sp, m = xwalk.locate(uc, rn, sp_universe)
        located_sp.append(sp)
        method.append(m)
    out = df.copy()
    out["located_sp"] = located_sp
    out["method"] = method

    total = float(out[mw_col].sum())
    hit = out[out["located_sp"].notna()]
    by_method = (hit.groupby("method")[mw_col].sum() / total).to_dict() if total else {}
    miss = out[out["located_sp"].isna()]
    unlocated = (miss.groupby("Resource Name")[mw_col].sum()
                 .sort_values(ascending=False)) if len(miss) else pd.Series(dtype=float)

    return {
        "total_mw": total,
        "located_mw": float(hit[mw_col].sum()),
        "rate": float(hit[mw_col].sum() / total) if total else 0.0,
        "row_rate": float(len(hit) / len(out)) if len(out) else 0.0,
        "n_sps": int(hit["located_sp"].nunique()),
        "by_method": by_method,
        "unlocated": unlocated,
        "located": out,
    }


def verdict(rate: float) -> tuple[str, str]:
    """The pre-registered Gate-C decision. Bars are constants; this only reads them."""
    if rate >= GATE_C_BUILD:
        return "BUILD", "build the per-constraint outage covariate"
    if rate >= GATE_C_DEAD:
        return "BUILD (flagged subset)", (
            "build on the joinable subset only, reporting the unlocated MW every week")
    return "DEAD", ("degrade to `outages_zonal`, which we already have; close this "
                    "branch with no ingest (the 0087 pattern)")
