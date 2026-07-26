"""geocode_ercot_layer.py

Build settlement_points_geocoded.csv: a mapping from priced ERCOT settlement
points (RN/PCCRN/LCCRN/PUN) to lat/lon, sourced from EIA-860 via name matching.

Hubs and Load Zones are hand-geocoded in hubs_lz_centroids.csv.

Prerequisite: run extract_eia860.py to produce master_eia860.csv.

Pipeline:
  1. Read priced settlement points from the CDR LMP snapshot.
  2. Drop HB_/DC_/LZ_; then prepend their hand-geocoded centroids to output.
  3. Classify the remainder as PCCRN (via CCP_Resource_Names), PUN, RN, or OTHER.
  4. Aggregate master_eia860.csv to plant level (lat/lon, capacity sum,
     concatenated LMP node designations).
  5. Match per settlement point:
       a. direct lookup against EIA `RTO/ISO LMP Node Designation`
       b. rapidfuzz token_set_ratio of substation/SP name vs EIA plant name
            >= 85 → auto match
            70-84 → low-confidence (review queue)
       c. substring fallback on plant name
  6. Emit run log; >=80% auto-match on top-200 RNs by EIA capacity.

Idempotent.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from shared.settings import settings

ERCOT_GEOCODE_DIR = Path(settings.ercot_geocode_dir)
MASTER_EIA860_CSV = Path(settings.master_eia860_csv)
OUT_CSV = Path(settings.settlement_points_geocoded_csv)
REVIEW_QUEUE_CSV = Path(settings.ercot_geocode_review_queue_csv)
MANUAL_OVERRIDES_CSV = Path(settings.ercot_geocode_manual_overrides_csv)
GRIDSTATUS_NODES_JSON = Path(settings.ercot_geocode_nodes_json)
HUBS_LZ_CENTROIDS_CSV = Path(settings.hubs_lz_centroids_csv)


def load_hub_lz_centroids(columns: list[str]) -> pd.DataFrame:
    """Load hand-geocoded hub/load-zone centroids into the canonical schema."""
    centroids = pd.read_csv(HUBS_LZ_CENTROIDS_CSV)
    centroids["sp_type"] = np.where(
        centroids["settlement_point"].str.startswith("HB_"), "hub", "load_zone",
    )
    return centroids.reindex(columns=columns)

# gridstatus.io encodes each node coordinate as two 5-char base62 groups of
# microdegrees: lat = base62(coord[:5]) / 1e6 - 90, lon = base62(coord[5:]) /
# 1e6 - 180. Verified against exact EIA LMP-designation matches (0.0025 deg /
# ~275 m RMSE — noise in our own truth, not the encoding). This is an
# authoritative SPP -> coordinate map, so it wins over the fuzzy-matched
# result whenever the two disagree by more than the correction radius.
GRIDSTATUS_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
GRIDSTATUS_B62_IDX = {c: i for i, c in enumerate(GRIDSTATUS_B62)}
# Below this separation the existing (matched) coordinate is left untouched;
# at or above it the gridstatus coordinate replaces it. Chosen so exact
# matches (which agree to sub-km) are never churned, only real errors move.
GRIDSTATUS_CORRECTION_KM = 1.0

CDR_GLOB = "cdr.*LMPSROSNODENP6788*.csv"
CCP_GLOB = "CCP_Resource_Names_*.csv"
RN_UNIT_GLOB = "Resource_Node_to_Unit_*.csv"
STAND_ALONE_GLOB = "Stand-Alone-Generation-Resources*.csv"
DME_LIST_GLOB = "*ResDMEList*.csv"

# Trailing tokens that mark unit/aggregation suffixes on ERCOT names; stripped
# before fuzzy comparison against EIA plant names. Both `_UNIT1` and
# `_UNIT_1` forms appear in the wild.
STRIP_RE = re.compile(
    r"|".join([
        r"_RN\d*$", r"_PUN\d*$",
        r"_UNIT_?\d+$", r"_U\d+$", r"_UN\d+$",
        r"_G\d+$", r"_GEN\d*$", r"_GT\d+$", r"_ST\d+$", r"_CT\d+$",
        r"_CC\d+$", r"_CCU$", r"_ESR\d*$", r"_BESS\d*$", r"_SLR\d*$",
        r"_WND\d*$", r"_WIND\d*$", r"_STG\d*$", r"_ALL$", r"_\d+$",
    ])
)

# Generic words that add noise to fuzzy comparison. Single-token queries
# composed entirely of these collapse to nothing and get filtered out by the
# query guard, which prevents over-matching to LMP designations like
# "CN BRKS UNIT" or "TREB SOLAR1".
STOP_TOKENS = {
    "LLC", "LP", "INC", "CO", "CORP", "COMPANY", "GENERATING", "GENERATION",
    "STATION", "PLANT", "POWER", "ENERGY", "FACILITY", "WIND", "SOLAR",
    "CENTER", "FARM", "PROJECT",
    "UNIT", "GEN", "GENS", "BLOCK", "STG", "CCU", "ESR", "BESS",
    "BATTERY", "STORAGE",
}

AUTO_THRESHOLD = 85
REVIEW_THRESHOLD = 70
TOP_RN_TARGET = 200
LMP_COL = "RTO/ISO LMP Node Designation"

# Energy-source hints embedded in ERCOT unit/RN names. Token base (digits
# stripped) → canonical source bucket. Used to reject cross-type fuzzy
# matches (e.g. a solar RN landing on a gas plant).
UNIT_SOURCE_TOKENS = {
    "SOLAR": "solar", "SLR": "solar", "PV": "solar", "SUN": "solar",
    "WIND": "wind",   "WND": "wind",  "TURB": "wind",
    "BESS": "battery", "BATT": "battery", "BATTERY": "battery",
    "ESR": "battery", "ESS": "battery", "STORAGE": "battery",
    "CC": "gas", "CCU": "gas", "CT": "gas", "GT": "gas",
    "NG": "gas", "GAS": "gas",
    "COAL": "coal", "NUC": "nuclear", "NUCLEAR": "nuclear",
    "HYDRO": "hydro", "GEO": "geothermal",
}

# EIA Energy Source 1 codes → canonical bucket. ST (steam turbine) is
# intentionally omitted from both sides since the prime mover doesn't
# uniquely identify fuel.
EIA_ES_CODES = {
    "SUN": "solar",
    "WND": "wind",
    "MWH": "battery",
    "NG": "gas", "BFG": "gas", "OG": "gas", "PG": "gas", "LPG": "gas",
    "BIT": "coal", "SUB": "coal", "LIG": "coal", "RC": "coal",
    "NUC": "nuclear",
    "WAT": "hydro",
    "GEO": "geothermal",
    "DFO": "oil", "JF": "oil", "KER": "oil", "RFO": "oil", "WO": "oil",
}


def infer_source(*names: str) -> str | None:
    """Scan one or more name strings for an energy-source hint. Returns
    canonical source if exactly one bucket is implicated, else None
    (ambiguous/unknown — caller should not filter on source)."""
    found: set[str] = set()
    for n in names:
        if not isinstance(n, str):
            continue
        for tok in re.split(r"[\s_]+", n.upper()):
            base = re.sub(r"\d+$", "", tok)
            src = UNIT_SOURCE_TOKENS.get(base)
            if src:
                found.add(src)
    return next(iter(found)) if len(found) == 1 else None


def plant_source(tech: str, es: str) -> str | None:
    """Resolve an EIA plant's energy source from Technology (natural-language
    label) + Energy Source 1 code. Technology is checked first since it's
    less ambiguous than fuel codes."""
    s = (tech or "").upper()
    if "SOLAR" in s or "PHOTOVOLTAIC" in s:           return "solar"
    if "WIND" in s:                                   return "wind"
    if "BATTERY" in s or "STORAGE" in s:              return "battery"
    if "COMBINED CYCLE" in s or "GAS TURBINE" in s:   return "gas"
    if "COAL" in s:                                   return "coal"
    if "NUCLEAR" in s:                                return "nuclear"
    if "HYDROELECTRIC" in s or "HYDRO" in s:          return "hydro"
    return EIA_ES_CODES.get((es or "").strip().upper())


def newest(dir_path: Path, glob: str) -> Path:
    files = sorted(dir_path.glob(glob))
    if not files:
        raise FileNotFoundError(f"No file matching {glob} in {dir_path}")
    return files[-1]


def normalize(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.upper().strip().replace("-", " ").replace(".", " ").replace(",", " ")
    s = re.sub(r"\s+", " ", s)
    prev = None
    while prev != s:
        prev = s
        s = STRIP_RE.sub("", s)
    tokens = [t for t in re.split(r"[\s_]+", s) if t and t not in STOP_TOKENS]
    return " ".join(tokens)


def classify(sp: str, ccp_names: set[str]) -> str:
    if sp in ccp_names:
        return "PCCRN"
    if re.search(r"_PUN\d*$", sp):
        return "PUN"
    if re.search(r"_RN\d*$", sp):
        return "RN"
    return "OTHER"


def load_cdr_settlement_points() -> pd.DataFrame:
    cdr_path = newest(ERCOT_GEOCODE_DIR, CDR_GLOB)
    print(f"[cdr] {cdr_path.name}")
    df = pd.read_csv(cdr_path, usecols=["SettlementPoint"])
    df["SettlementPoint"] = df["SettlementPoint"].str.strip()
    sps = df.drop_duplicates().rename(columns={"SettlementPoint": "settlement_point"})
    return sps.loc[~sps["settlement_point"].str.startswith(("HB_", "DC_", "LZ_"))]\
              .reset_index(drop=True)


def load_ccp_names() -> set[str]:
    df = pd.read_csv(newest(ERCOT_GEOCODE_DIR, CCP_GLOB))
    return set(df["CCP_NAME"].dropna().str.strip())


def load_rn_to_unit() -> pd.DataFrame:
    df = pd.read_csv(newest(ERCOT_GEOCODE_DIR, RN_UNIT_GLOB))
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df.rename(columns={
        "RESOURCE_NODE": "settlement_point",
        "UNIT_SUBSTATION": "substation",
        "UNIT_NAME": "unit_name",
    })


# Map ERCOT Generator Type (from the stand-alone resources report) onto the
# canonical source bucket used by the matching filter.
GEN_TYPE_SOURCE = {
    "SOLAR": "solar",
    "WIND": "wind",
    "BATTERY": "battery", "ENERGY STORAGE": "battery",
    "THERMAL": "gas",   # ERCOT thermal is overwhelmingly natural gas
    "HYDRO": "hydro",
    "NUCLEAR": "nuclear",
}


def load_dme_list() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Read ERCOT's Resource DME List. Returns:
      - exact: {RESOURCE NAME (unit_code) → {owner, dme, type}}
      - by_prefix: {substation_prefix → [info, ...]}, where prefix is the
        token before the first underscore in RESOURCE NAME (substation code)

    The by-prefix index is the fallback for PCCRN-style SPs (e.g. `QALSW_CC1`)
    that are not in `Resource_Node_to_Unit`: the substation code is still
    1:1 with a single corporate owner in the data, so prefix lookup is safe.
    Optional input — returns ({}, {}) if absent.
    """
    try:
        path = newest(ERCOT_GEOCODE_DIR, DME_LIST_GLOB)
    except FileNotFoundError:
        return {}, {}
    print(f"[dme-list] {path.name}")
    df = pd.read_csv(path)
    def strip_suffix(s: str) -> str:
        if not isinstance(s, str):
            return ""
        return re.sub(r"\s*\((RE|DME)\)\s*$", "", s.strip(), flags=re.IGNORECASE)

    exact: dict[str, dict] = {}
    by_prefix: dict[str, list[dict]] = {}
    for _, r in df.iterrows():
        key = str(r["RESOURCE NAME"]).strip()
        info = {
            "owner": strip_suffix(r.get("OWNER RE", "")),
            "dme":   strip_suffix(r.get("DME", "")),
            "type":  str(r.get("TYPE", "")).strip(),
        }
        exact[key] = info
        prefix = key.split("_", 1)[0]
        if prefix:
            by_prefix.setdefault(prefix, []).append(info)
    return exact, by_prefix


def load_stand_alone() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Read ERCOT's stand-alone generation resources report. Returns:
      - exact: {Unit Code → info} where Unit Code matches
        `{UNIT_SUBSTATION}_{UNIT_NAME}` from Resource_Node_to_Unit
      - by_station: {Generator Station Code → [info, ...]}, the fallback
        for PCCRN-style SPs that don't appear in Resource_Node_to_Unit
        (e.g. `QALSW_CC1` → all units with station code `QALSW`)
    Optional input — returns ({}, {}) if absent.
    """
    try:
        path = newest(ERCOT_GEOCODE_DIR, STAND_ALONE_GLOB)
    except FileNotFoundError:
        return {}, {}
    print(f"[stand-alone] {path.name}")
    df = pd.read_csv(path)
    df["Unit Code"] = df["Unit Code"].astype(str).str.strip()
    df["Generator Station Code"] = df["Generator Station Code"]\
        .astype(str).str.strip()
    df["Generator Station Description"] = df["Generator Station Description"]\
        .astype(str).str.strip()
    df["Nameplate Capacity (MW)"] = pd.to_numeric(
        df["Nameplate Capacity (MW)"], errors="coerce"
    )
    exact: dict[str, dict] = {}
    by_station: dict[str, list[dict]] = {}
    for _, r in df.iterrows():
        info = {
            "description": r["Generator Station Description"],
            "type": str(r.get("Generator Type", "")).strip(),
            "source": GEN_TYPE_SOURCE.get(str(r.get("Generator Type", "")).strip().upper()),
            "capacity_mw": float(r["Nameplate Capacity (MW)"] or 0),
        }
        exact[r["Unit Code"]] = info
        if r["Generator Station Code"]:
            by_station.setdefault(r["Generator Station Code"], []).append(info)
    return exact, by_station


def load_plants() -> pd.DataFrame:
    """Aggregate master_eia860.csv (one row per generator) to plant level:
    lat/lon (first), summed nameplate capacity, and concatenated LMP node
    designations."""
    df = pd.read_csv(MASTER_EIA860_CSV, dtype=str)
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df["Nameplate Capacity (MW)"] = pd.to_numeric(
        df["Nameplate Capacity (MW)"], errors="coerce"
    )
    agg = {
        "Plant Name": "first",
        "Utility Name": "first",
        "Latitude": "first",
        "Longitude": "first",
        "Nameplate Capacity (MW)": "sum",
        # First-value: a plant can house mixed fuel types; the first generator
        # row gives a best-effort label. Cross-type plants will resolve to
        # None when source filtering is applied.
        "Technology": "first",
        "Energy Source 1": "first",
    }
    if LMP_COL in df.columns:
        agg[LMP_COL] = lambda s: ";".join(sorted({x.strip() for x in s.dropna() if x.strip()}))
    plants = df.groupby("Plant Code", as_index=False).agg(agg)
    plants = plants.dropna(subset=["Latitude", "Longitude"])
    plants["plant_name_norm"] = plants["Plant Name"].map(normalize)
    plants["utility_name_norm"] = plants["Utility Name"].map(normalize)
    plants["source"] = [plant_source(t, e)
                        for t, e in zip(plants["Technology"], plants["Energy Source 1"])]
    return plants.reset_index(drop=True)


def explode_lmp_tokens(val: str) -> list[str]:
    """Split a raw LMP designation cell into SP-style tokens. EIA values come
    in several shapes: 'AGUAYO_UNIT1' (single SP), 'AE BCH01' (space-as-sep),
    'AE_BCH01;AE_BCH02' (semicolon list). Yield each form upper-cased with
    spaces collapsed to underscores."""
    if not isinstance(val, str) or not val.strip():
        return []
    out: list[str] = []
    for tok in re.split(r"[;,/]+", val):
        tok = tok.strip().upper().replace(" ", "_")
        if tok:
            out.append(tok)
    return out


def build_lmp_index(plants: pd.DataFrame) -> tuple[dict[str, int], list[str], list[int]]:
    """Return (exact_index, fuzzy_pool, fuzzy_pool_pos) where:
      - exact_index: SP-style token → plant row position
      - fuzzy_pool: normalized LMP tokens (for rapidfuzz)
      - fuzzy_pool_pos: parallel list of plant row positions
    """
    exact: dict[str, int] = {}
    pool: list[str] = []
    pool_pos: list[int] = []
    if LMP_COL not in plants.columns:
        return exact, pool, pool_pos
    for pos, val in enumerate(plants[LMP_COL]):
        for raw in explode_lmp_tokens(val):
            exact.setdefault(raw, pos)
            norm = normalize(raw)
            if norm:
                pool.append(norm)
                pool_pos.append(pos)
    return exact, pool, pool_pos


def build_name_pool(plants: pd.DataFrame) -> tuple[list[str], list[int], list[str], set[str]]:
    """Build the combined search pool used by the fuzzy passes:
      - pool / pool_pos: normalized names paralleled by plant row position
      - kind: 'plant' or 'utility' for each pool entry
      - unique_utils: normalized utility names owned by exactly one plant
        (safe to accept as a match target — multi-plant utilities like
        "NRG", "Calpine", "Engie" are excluded to avoid collapsing
        unrelated SPs onto one arbitrary plant).
    """
    pool: list[str] = []
    pool_pos: list[int] = []
    kind: list[str] = []
    for i, n in enumerate(plants["plant_name_norm"]):
        if n:
            pool.append(n); pool_pos.append(i); kind.append("plant")
    util_counts = plants["utility_name_norm"].value_counts()
    unique_utils = set(util_counts[util_counts == 1].index) - {""}
    for i, u in enumerate(plants["utility_name_norm"]):
        if u and u in unique_utils:
            pool.append(u); pool_pos.append(i); kind.append("utility")
    return pool, pool_pos, kind, unique_utils


def _best_compatible(
    queries: list[str],
    pool: list[str],
    pool_pos: list[int],
    plants: pd.DataFrame,
    sp_src: str | None,
    expected_mw: float = 0.0,
) -> tuple[int, int | None]:
    """Return (best_score, best_plant_row_pos) over `queries` × `pool`,
    accepting only hits whose plant source is compatible with sp_src.
    Compatibility: either side may be None (unknown), otherwise must match.

    Ambiguity guard: token_set_ratio rewards subset matches, so a generic
    single-token query like "CALPINE" scores 100 against every unique
    utility containing CALPINE (Calpine-Hidalgo, Calpine-Magic Valley, ...).
    If multiple distinct compatible plants tie at the top score (±1) and
    no expected_mw is given, the query is treated as ambiguous and skipped.
    When expected_mw is provided (sum of Nameplate from the stand-alone
    report), ties are broken by picking the plant whose summed nameplate
    is closest — resolves cases like Buffalo Gap I/II/III where multiple
    plants legitimately share the same name root."""
    best_score, best_pos = 0, None
    if not pool:
        return best_score, best_pos
    plant_src = plants["source"].tolist()
    plant_cap = plants["Nameplate Capacity (MW)"].tolist()
    plant_name_norm = plants["plant_name_norm"].tolist()
    for q in queries:
        hits = process.extract(
            q, pool, scorer=fuzz.token_set_ratio,
            score_cutoff=REVIEW_THRESHOLD, limit=15,
        )
        compat = []
        for _, score, idx in hits:
            row_pos = pool_pos[idx]
            ps = plant_src[row_pos]
            if sp_src is None or ps is None or sp_src == ps:
                compat.append((score, row_pos))
        if not compat:
            continue
        top = compat[0][0]
        tied = [row for s, row in compat if s >= top - 1]
        tied_plants = list(dict.fromkeys(tied))
        if len(tied_plants) > 1:
            # Capacity tiebreaker only applies to plants that look like
            # variants of the same site (share at least one plant-name
            # token, e.g. Buffalo Gap / Buffalo Gap 2 / Buffalo Gap 3).
            # Unrelated plants whose utility names happen to share a
            # generic token (Calpine Hidalgo vs Calpine Magic Valley)
            # have no token overlap on plant_name_norm and stay rejected.
            token_sets = [set(plant_name_norm[r].split()) for r in tied_plants]
            shared = set.intersection(*token_sets) if token_sets else set()
            if not shared or expected_mw <= 0:
                continue
            chosen = min(tied_plants,
                         key=lambda r: abs((plant_cap[r] or 0) - expected_mw))
            if top > best_score:
                best_score, best_pos = top, chosen
        elif top > best_score:
            best_score, best_pos = top, compat[0][1]
    return best_score, best_pos


OWNER_TIGHT_THRESHOLD = 92


def match_one(
    sp: str,
    rn_unit_g: pd.Series,
    unit_names_g: pd.Series,
    plant_names: list[str],
    name_pool: list[str],
    name_pool_pos: list[int],
    plants: pd.DataFrame,
    lmp_exact: dict[str, int],
    lmp_pool: list[str],
    lmp_pool_pos: list[int],
    sp_src: str | None,
    descriptions: list[str],
    owners: list[str],
    expected_mw: float,
) -> dict:
    base = {
        "settlement_point": sp,
        "lat": None,
        "lon": None,
        "match_method": "unmatched",
        "match_confidence": 0.0,
        "matched_plant": None,
        "matched_capacity_mw": 0.0,
        # Context echoed to the output for downstream debugging / manual
        # review. The review queue surfaces these so a human can decide
        # whether the candidate description/owner is the right plant.
        "station_description": " | ".join(descriptions) if descriptions else "",
        "owner_re": " | ".join(owners) if owners else "",
        "expected_mw": expected_mw,
    }

    # Pass 1: direct LMP designation hit. Try the full SP, the SP with the
    # substation prefix doubled (BAC_BAC pattern in EIA), and the trailing
    # token after the first underscore.
    candidates = {sp}
    parts = sp.split("_")
    if len(parts) >= 2:
        candidates.add(f"{parts[0]}_{sp}")
        candidates.add("_".join(parts[1:]))
    for c in candidates:
        if c in lmp_exact:
            p = plants.iloc[lmp_exact[c]]
            return {
                **base,
                "lat": p["Latitude"], "lon": p["Longitude"],
                "match_method": "lmp_node_designation", "match_confidence": 1.0,
                "matched_plant": p["Plant Name"],
                "matched_capacity_mw": float(p["Nameplate Capacity (MW)"] or 0),
            }

    # Pass 2: fuzzy match against EIA Plant Name (and unique Utility Name)
    # using the human-readable Generator Station Description from ERCOT's
    # stand-alone resources report. This is the highest-quality bridge:
    # both sides are full plant/utility names rather than cryptic codes.
    # The utility-name pool is restricted to utilities owning a single
    # plant to avoid collapsing unrelated SPs onto a multi-plant utility.
    if descriptions:
        desc_queries = [normalize(d) for d in descriptions]
        desc_queries = [q for q in desc_queries if q]
        best_score_d, best_pos_d = _best_compatible(
            desc_queries, name_pool, name_pool_pos, plants, sp_src,
            expected_mw=expected_mw,
        )
        if best_pos_d is not None and best_score_d >= AUTO_THRESHOLD:
            p = plants.iloc[best_pos_d]
            return {
                **base,
                "lat": p["Latitude"], "lon": p["Longitude"],
                "match_method": "station_description",
                "match_confidence": round(best_score_d / 100.0, 3),
                "matched_plant": p["Plant Name"],
                "matched_capacity_mw": float(p["Nameplate Capacity (MW)"] or 0),
            }

    # Pass 3: owner/DME from the ResDMEList report. Tight threshold (92)
    # because operator and owner are easily conflated — we accept only when
    # the corporate entity name resembles the EIA Plant Name (or unique
    # Utility Name) closely after stripping LLC/LP/INC etc. via stop-tokens.
    if owners:
        owner_queries = [normalize(o) for o in owners]
        owner_queries = [q for q in owner_queries if q and len(q) >= 4]
        if owner_queries:
            best_score_o, best_pos_o = _best_compatible(
                owner_queries, name_pool, name_pool_pos, plants, sp_src,
                expected_mw=expected_mw,
            )
            if best_pos_o is not None and best_score_o >= OWNER_TIGHT_THRESHOLD:
                p = plants.iloc[best_pos_o]
                return {
                    **base,
                    "lat": p["Latitude"], "lon": p["Longitude"],
                    "match_method": "owner_name",
                    "match_confidence": round(best_score_o / 100.0, 3),
                    "matched_plant": p["Plant Name"],
                    "matched_capacity_mw": float(p["Nameplate Capacity (MW)"] or 0),
                }

    cand_names = list(rn_unit_g.get(sp, []))
    cand_names.extend(unit_names_g.get(sp, []))
    cand_names.append(sp)
    # Reject queries that are too short or contain no meaningful (non-digit)
    # token — e.g. "SOLAR1" → "1" after stop-token removal would otherwise
    # score 100 against any plant whose normalized name contains "1".
    queries = sorted({normalize(c) for c in cand_names if c})
    queries = [q for q in queries
               if len(q) >= 4 and any(t.isalpha() and len(t) >= 3
                                       for t in q.split())]

    # Pass 3: fuzzy match against LMP designation tokens (more reliable than
    # plant names since both sides use ERCOT naming conventions). Source
    # compatibility filter prevents e.g. a solar RN landing on a gas plant.
    best_score, best_pos = _best_compatible(
        queries, lmp_pool, lmp_pool_pos, plants, sp_src,
    )

    if best_pos is not None and best_score >= AUTO_THRESHOLD:
        p = plants.iloc[best_pos]
        return {
            **base,
            "lat": p["Latitude"], "lon": p["Longitude"],
            "match_method": "fuzzy_lmp",
            "match_confidence": round(best_score / 100.0, 3),
            "matched_plant": p["Plant Name"],
            "matched_capacity_mw": float(p["Nameplate Capacity (MW)"] or 0),
        }

    # Pass 5: fuzzy match against plant/utility names (cryptic SP codes vs
    # EIA names). Same combined pool as the description/owner passes.
    best_score_pn, best_pos_pn = _best_compatible(
        queries, name_pool, name_pool_pos, plants, sp_src,
    )

    if best_pos_pn is not None and best_score_pn >= AUTO_THRESHOLD:
        p = plants.iloc[best_pos_pn]
        return {
            **base,
            "lat": p["Latitude"], "lon": p["Longitude"],
            "match_method": "fuzzy_name",
            "match_confidence": round(best_score_pn / 100.0, 3),
            "matched_plant": p["Plant Name"],
            "matched_capacity_mw": float(p["Nameplate Capacity (MW)"] or 0),
        }

    # Choose the better of the two sub-threshold candidates for downstream passes.
    if best_score_pn > best_score:
        best_score, best_pos = best_score_pn, best_pos_pn

    # Pass 4: substring fallback (source-compatible plants only)
    for q in queries:
        if len(q) < 4:
            continue
        mask = plants["plant_name_norm"].str.contains(q, regex=False, na=False)
        if sp_src is not None:
            mask &= plants["source"].isin([sp_src, None]) | plants["source"].isna()
        if mask.any():
            p = plants[mask].sort_values("Nameplate Capacity (MW)", ascending=False).iloc[0]
            return {
                **base,
                "lat": p["Latitude"], "lon": p["Longitude"],
                "match_method": "substring", "match_confidence": 0.6,
                "matched_plant": p["Plant Name"],
                "matched_capacity_mw": float(p["Nameplate Capacity (MW)"] or 0),
            }

    # Pass 4: sub-threshold fuzzy → review queue. Do NOT emit coordinates;
    # these matches are not trustworthy and need human QA. The candidate plant
    # is recorded only as a hint in the review row.
    if best_pos is not None:
        p = plants.iloc[best_pos]
        return {
            **base,
            "match_method": "review",
            "match_confidence": round(best_score / 100.0, 3),
            "matched_plant": p["Plant Name"],
        }
    return base


def sp_to_descriptions(
    sp: str,
    rn_unit: pd.DataFrame,
    stand_alone_exact: dict[str, dict],
    stand_alone_by_station: dict[str, list[dict]],
) -> tuple[list[str], str | None, float]:
    """Return (unique station descriptions, source-from-type if all agree,
    summed Nameplate MW) for an SP. The capacity is the sum of all
    stand-alone units we resolve — used as a tiebreaker when fuzzy matching
    finds multiple plants tied at the top score (e.g. Buffalo Gap I/II/III)."""
    rows = rn_unit[rn_unit["settlement_point"] == sp]
    infos: list[dict] = []
    for _, r in rows.iterrows():
        info = stand_alone_exact.get(f"{r['substation']}_{r['unit_name']}")
        if info:
            infos.append(info)
    if not infos:
        prefix = sp.split("_", 1)[0]
        infos = stand_alone_by_station.get(prefix, [])
    descs: list[str] = []
    sources: set[str] = set()
    cap = 0.0
    for info in infos:
        if info["description"] and info["description"] not in descs:
            descs.append(info["description"])
        if info["source"]:
            sources.add(info["source"])
        cap += info.get("capacity_mw") or 0.0
    src = next(iter(sources)) if len(sources) == 1 else None
    return descs, src, cap


# DME TYPE → source bucket. "Generation" alone doesn't pin fuel; "Storage"
# does. Used as a fallback source hint when stand-alone Generator Type and
# token inference both come up empty.
DME_TYPE_SOURCE = {"STORAGE": "battery"}


def sp_to_owners(
    sp: str,
    rn_unit: pd.DataFrame,
    dme_exact: dict[str, dict],
    dme_by_prefix: dict[str, list[dict]],
) -> tuple[list[str], str | None]:
    """Return (unique owner/DME strings, source-from-type) for an SP. Primary
    join is `{substation}_{unit_name}` → RESOURCE NAME; the fallback uses the
    SP's own prefix as substation code (covers PCCRN-style SPs missing from
    Resource_Node_to_Unit)."""
    rows = rn_unit[rn_unit["settlement_point"] == sp]
    infos: list[dict] = []
    for _, r in rows.iterrows():
        info = dme_exact.get(f"{r['substation']}_{r['unit_name']}")
        if info:
            infos.append(info)
    if not infos:
        prefix = sp.split("_", 1)[0]
        infos = dme_by_prefix.get(prefix, [])
    owners: list[str] = []
    sources: set[str] = set()
    for info in infos:
        for fld in ("owner", "dme"):
            v = info[fld]
            if v and v not in owners:
                owners.append(v)
        src = DME_TYPE_SOURCE.get(info["type"].upper())
        if src:
            sources.add(src)
    src = next(iter(sources)) if len(sources) == 1 else None
    return owners, src


def match_settlement_points(sps, rn_unit, plants,
                            stand_alone, stand_alone_by_station,
                            dme, dme_by_prefix) -> pd.DataFrame:
    lmp_exact, lmp_pool, lmp_pool_pos = build_lmp_index(plants)
    name_pool, name_pool_pos, _kind, unique_utils = build_name_pool(plants)
    print(f"[name-pool] plant entries: {len(plants)}, "
          f"unique utilities admitted: {len(unique_utils)}")
    rn_unit_g = rn_unit.groupby("settlement_point")["substation"].agg(
        lambda s: sorted(set(s))
    )
    unit_names_g = rn_unit.groupby("settlement_point")["unit_name"].agg(
        lambda s: sorted(set(s))
    )
    plant_names = plants["plant_name_norm"].tolist()

    def sp_meta(sp: str) -> tuple[list[str], list[str], str | None, float]:
        descs, src_desc, cap = sp_to_descriptions(sp, rn_unit, stand_alone,
                                                   stand_alone_by_station)
        owners, src_dme = sp_to_owners(sp, rn_unit, dme, dme_by_prefix)
        # Source precedence: stand-alone Generator Type → DME TYPE → token
        # inference. First two are explicit; the last is a heuristic guess.
        src = src_desc or src_dme or infer_source(
            sp, *rn_unit_g.get(sp, []), *unit_names_g.get(sp, [])
        )
        return descs, owners, src, cap

    rows = []
    for sp in sps["settlement_point"]:
        descs, owners, src, cap = sp_meta(sp)
        rows.append(match_one(sp, rn_unit_g, unit_names_g, plant_names,
                              name_pool, name_pool_pos, plants,
                              lmp_exact, lmp_pool, lmp_pool_pos, src,
                              descs, owners, cap))
    return pd.DataFrame(rows)


def run_log(matched: pd.DataFrame) -> None:
    print()
    print("=" * 60, "Match Method Counts", sep="\n")
    print(matched["match_method"].value_counts(dropna=False).to_string())

    print()
    print("=" * 60, "SP Type Counts", sep="\n")
    print(matched["sp_type"].value_counts(dropna=False).to_string())

    # Top RNs ranked by mapped EIA capacity. Drop zero-capacity (unmatched)
    # rows so they don't pad the head of the list and confuse the metric.
    rns = matched[matched["sp_type"] == "RN"]
    ranked = rns[rns["matched_capacity_mw"] > 0]\
        .sort_values("matched_capacity_mw", ascending=False)
    top = ranked.head(TOP_RN_TARGET)
    auto = top["match_method"].isin(
        ["manual", "gridstatus", "lmp_node_designation", "station_description",
         "owner_name", "fuzzy_lmp", "fuzzy_name"]
    ).sum()
    sub  = (top["match_method"] == "substring").sum()
    rev  = (top["match_method"] == "review").sum()
    rate = auto / max(len(top), 1)

    print()
    print("=" * 60, f"Top {TOP_RN_TARGET} RNs by mapped EIA capacity", sep="\n")
    print(f"  total        : {len(top)} (of {len(rns)} RNs, {len(ranked)} with capacity)")
    print(f"  auto match   : {auto} ({rate:.1%})")
    print(f"  substring    : {sub}")
    print(f"  review queue : {rev}")
    print(f"  >= 80% auto  : {'PASS' if rate >= 0.80 else 'FAIL'}")


def _b62(s: str) -> int:
    v = 0
    for c in s:
        v = v * 62 + GRIDSTATUS_B62_IDX[c]
    return v


def decode_gridstatus_coord(coord: str) -> tuple[float, float]:
    """Decode a gridstatus 10-char base62 coord into (lat, lon)."""
    return _b62(coord[:5]) / 1e6 - 90.0, _b62(coord[5:]) / 1e6 - 180.0


def load_gridstatus_coords() -> pd.DataFrame:
    """Read the gridstatus node export and return ERCOT settlement points with
    decoded lat/lon. HB_/LZ_/DC_ are dropped (hand-geocoded elsewhere), so this
    aligns with the priced-SP universe. Optional input — empty frame if absent.
    """
    if not GRIDSTATUS_NODES_JSON.exists():
        print(f"[gridstatus] {GRIDSTATUS_NODES_JSON.name} absent — skipping corrections")
        return pd.DataFrame(columns=["settlement_point", "gs_lat", "gs_lon"])
    # Stored gzip-compressed (it's a ~2.5 MB export); detect the gzip magic
    # bytes so a plain-JSON file still loads.
    raw = GRIDSTATUS_NODES_JSON.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw)
    rows = payload["data"][1:]  # first row is the header
    recs = []
    for _eid, sp, market, coord in rows:
        if market != "ERCOT" or sp.startswith(("HB_", "LZ_", "DC_")):
            continue
        lat, lon = decode_gridstatus_coord(coord)
        recs.append((sp.strip(), lat, lon))
    df = pd.DataFrame(recs, columns=["settlement_point", "gs_lat", "gs_lon"])
    return df.drop_duplicates("settlement_point")


def _haversine_km(lat1, lon1, lat2, lon2):
    """Vectorized great-circle distance (km). NaN in any input yields NaN."""
    R = 6371.0088
    p = np.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (np.sin(dlat / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin(dlon / 2) ** 2)
    return 2 * R * np.arcsin(np.sqrt(a))


def apply_gridstatus_corrections(out: pd.DataFrame) -> pd.DataFrame:
    """Overlay the authoritative gridstatus coordinate wherever it disagrees
    with the current (matched or manual) result by >= GRIDSTATUS_CORRECTION_KM,
    or wherever we have no coordinate at all. Rows within the radius keep their
    existing coordinate and match_method untouched — this corrects errors
    without churning the many nodes both sources already agree on.

    Applied after manual overrides so it supersedes bad hand entries; corrected
    rows are re-tagged match_method='gridstatus'.
    """
    gs = load_gridstatus_coords()
    if gs.empty:
        return out

    merged = out.merge(gs, on="settlement_point", how="left")
    has_gs = merged["gs_lat"].notna()
    dist = _haversine_km(merged["lat"], merged["lon"],
                         merged["gs_lat"], merged["gs_lon"])
    # Correct when gridstatus knows the node AND (we don't have a coord, or the
    # two disagree beyond the radius). notna() on dist is False when our coord
    # is missing, so the isna() branch is handled explicitly.
    fix = has_gs & (merged["lat"].isna() | (dist >= GRIDSTATUS_CORRECTION_KM))

    n_missing = int((fix & merged["lat"].isna()).sum())
    n_moved = int((fix & merged["lat"].notna()).sum())

    out = out.copy()
    out.loc[fix.values, "lat"] = merged.loc[fix, "gs_lat"].values
    out.loc[fix.values, "lon"] = merged.loc[fix, "gs_lon"].values
    out.loc[fix.values, "match_method"] = "gridstatus"
    out.loc[fix.values, "match_confidence"] = 1.0

    kept = int((has_gs & ~fix).sum())
    print(f"[gridstatus] corrected {n_moved} coords (>= {GRIDSTATUS_CORRECTION_KM:g} km off), "
          f"filled {n_missing} previously unplaced, kept {kept} already-agreeing "
          f"(within {GRIDSTATUS_CORRECTION_KM:g} km), from {GRIDSTATUS_NODES_JSON.name}")
    return out


def apply_manual_overrides(out: pd.DataFrame) -> pd.DataFrame:
    """Overlay hand-edited rows from manual_overrides.csv. Any SP listed
    there is treated as resolved: its lat/lon replace the auto result and
    match_method becomes 'manual'. SPs not present in the live SP universe
    are warned (typo or stale entry) but not dropped."""
    if not MANUAL_OVERRIDES_CSV.exists():
        return out
    ov = pd.read_csv(MANUAL_OVERRIDES_CSV)
    ov = ov.dropna(subset=["settlement_point", "lat", "lon"])
    if ov.empty:
        return out

    # Sentinel (0, 0) = "cannot place." Force the coordinate to NaN so every
    # downstream reader — all of which dropna on lat/lon — treats it as an
    # honest hole. Left as literal (0, 0) it plots off the coast of Africa and
    # drags |SF|-weighted constraint centroids toward the equator.
    is_sentinel = (ov["lat"] == 0) & (ov["lon"] == 0)
    unplaceable = set(ov.loc[is_sentinel, "settlement_point"])
    ov = ov[~is_sentinel]

    known = set(out["settlement_point"])
    stale = sorted((set(ov["settlement_point"]) | unplaceable) - known)
    if stale:
        print(f"[overrides] WARN: {len(stale)} override SPs not in current "
              f"SP universe (typo or retired): {stale[:5]}{'...' if len(stale) > 5 else ''}")

    ov_idx = ov.set_index("settlement_point")
    mask = out["settlement_point"].isin(ov_idx.index)
    out.loc[mask, "lat"] = out.loc[mask, "settlement_point"].map(ov_idx["lat"])
    out.loc[mask, "lon"] = out.loc[mask, "settlement_point"].map(ov_idx["lon"])
    out.loc[mask, "match_method"] = "manual"
    out.loc[mask, "match_confidence"] = 1.0

    umask = out["settlement_point"].isin(unplaceable)
    out.loc[umask, ["lat", "lon"]] = float("nan")
    out.loc[umask, "match_method"] = "manual_unplaceable"
    out.loc[umask, "match_confidence"] = 0.0

    print(f"[overrides] applied {int(mask.sum())} manual rows, "
          f"{int(umask.sum())} marked unplaceable (0,0 sentinel), "
          f"from {MANUAL_OVERRIDES_CSV.name}")
    return out


def main() -> int:
    if not MASTER_EIA860_CSV.exists():
        sys.exit(f"missing {MASTER_EIA860_CSV} — run extract_eia860.py first")

    sps = load_cdr_settlement_points()
    ccp_names = load_ccp_names()
    rn_unit = load_rn_to_unit()
    plants = load_plants()
    stand_alone, stand_alone_by_station = load_stand_alone()
    dme, dme_by_prefix = load_dme_list()
    print(f"[input] priced SPs (non-HB/LZ/DC): {len(sps)}")
    print(f"[input] EIA-860 TX plants:         {len(plants)}")
    print(f"[input] stand-alone unit codes:    {len(stand_alone)}  (stations: {len(stand_alone_by_station)})")
    print(f"[input] DME-list resource names:   {len(dme)}  (prefixes: {len(dme_by_prefix)})")

    sps["sp_type"] = sps["settlement_point"].map(lambda s: classify(s, ccp_names))

    matched = match_settlement_points(sps, rn_unit, plants,
                                       stand_alone, stand_alone_by_station,
                                       dme, dme_by_prefix)
    out = sps.merge(matched, on="settlement_point", how="left")
    out = apply_manual_overrides(out)
    # Authoritative SPP->coordinate map: supersedes matched/manual coords that
    # disagree beyond the correction radius, and fills nodes we couldn't place.
    out = apply_gridstatus_corrections(out)
    # capacity_ratio = expected / matched. <1 means the SP is one unit of a
    # larger plant; ~1 means the SP covers the whole plant; >1 hints at a
    # cross-plant mismatch worth reviewing.
    out["capacity_ratio"] = [
        round(e / m, 3) if m and e else None
        for e, m in zip(out["expected_mw"], out["matched_capacity_mw"])
    ]
    # EIA plant/utility names contain commas ("Western Trail Wind, LLC").
    # Pandas quotes them per RFC 4180, but naive parsers (Excel default,
    # bare split-on-comma) misalign columns. Strip commas from textual
    # context fields so the output round-trips through any consumer.
    for col in ("matched_plant", "station_description", "owner_re"):
        out[col] = out[col].fillna("").astype(str).str.replace(",", "", regex=False)

    geocoded = out[out["lat"].notna()][
        ["settlement_point", "sp_type", "lat", "lon", "match_method", "match_confidence",
         "matched_plant", "matched_capacity_mw",
         "station_description", "owner_re", "expected_mw", "capacity_ratio"]
    ]
    geocoded = pd.concat([load_hub_lz_centroids(list(geocoded.columns)), geocoded], ignore_index=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    geocoded.to_csv(OUT_CSV, index=False)
    print(f"[output] {OUT_CSV}  rows={len(geocoded)}")

    rq = out[out["match_method"].isin(["review", "unmatched"])][
        ["settlement_point", "sp_type", "match_method", "match_confidence",
         "matched_plant", "matched_capacity_mw",
         "station_description", "owner_re", "expected_mw", "capacity_ratio"]
    ]
    REVIEW_QUEUE_CSV.parent.mkdir(parents=True, exist_ok=True)
    rq.to_csv(REVIEW_QUEUE_CSV, index=False)
    print(f"[output] {REVIEW_QUEUE_CSV}  rows={len(rq)}")

    run_log(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
