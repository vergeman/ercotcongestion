"""geocode_ercot_layer.py

Build settlement_points_geocoded.csv: a mapping from priced ERCOT settlement
points (RN/PCCRN/LCCRN/PUN) to lat/lon, sourced from EIA-860 via name matching.

Hubs and Load Zones are hand-geocoded in hubs_lz_centroids.csv (companion).

Prerequisite: run extract_eia860.py to produce master_eia860.csv.

Pipeline:
  1. Read priced settlement points from the CDR LMP snapshot.
  2. Drop HB_/DC_/LZ_ (covered by hubs_lz_centroids.csv).
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

import re
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from shared.settings import settings

ERCOT_GEOCODE_DIR = Path(settings.ercot_geocode_dir)
MASTER_EIA860_CSV = Path(settings.master_eia860_csv)
OUT_CSV = Path(settings.settlement_points_geocoded_csv)
REVIEW_QUEUE_CSV = Path(settings.ercot_geocode_review_queue_csv)
MANUAL_OVERRIDES_CSV = Path(settings.ercot_geocode_manual_overrides_csv)

CDR_GLOB = "cdr.*LMPSROSNODENP6788*.csv"
CCP_GLOB = "CCP_Resource_Names_*.csv"
RN_UNIT_GLOB = "Resource_Node_to_Unit_*.csv"

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
    "LLC", "LP", "INC", "CO", "COMPANY", "GENERATING", "GENERATION",
    "STATION", "PLANT", "POWER", "ENERGY", "FACILITY", "WIND", "SOLAR",
    "CENTER", "FARM", "PROJECT",
    "UNIT", "GEN", "GENS", "BLOCK", "STG", "CCU", "ESR", "BESS",
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


def _best_compatible(
    queries: list[str],
    pool: list[str],
    pool_pos: list[int],
    plants: pd.DataFrame,
    sp_src: str | None,
) -> tuple[int, int | None]:
    """Return (best_score, best_plant_row_pos) over `queries` × `pool`,
    accepting only hits whose plant source is compatible with sp_src.
    Compatibility: either side may be None (unknown), otherwise must match."""
    best_score, best_pos = 0, None
    if not pool:
        return best_score, best_pos
    plant_src = plants["source"].tolist()
    for q in queries:
        # top-5 lets us skip the highest-scoring hit if it's incompatible.
        hits = process.extract(
            q, pool, scorer=fuzz.token_set_ratio,
            score_cutoff=REVIEW_THRESHOLD, limit=5,
        )
        for _, score, idx in hits:
            row_pos = pool_pos[idx]
            ps = plant_src[row_pos]
            if sp_src is None or ps is None or sp_src == ps:
                if score > best_score:
                    best_score, best_pos = score, row_pos
                break  # higher-scoring incompatible hits are skipped via outer loop
    return best_score, best_pos


def match_one(
    sp: str,
    rn_unit_g: pd.Series,
    unit_names_g: pd.Series,
    plant_names: list[str],
    plants: pd.DataFrame,
    lmp_exact: dict[str, int],
    lmp_pool: list[str],
    lmp_pool_pos: list[int],
    sp_src: str | None,
) -> dict:
    base = {
        "settlement_point": sp,
        "lat": None,
        "lon": None,
        "match_method": "unmatched",
        "match_confidence": 0.0,
        "matched_plant": None,
        "matched_capacity_mw": 0.0,
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

    # Pass 2: fuzzy match against LMP designation tokens (more reliable than
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

    # Pass 3: fuzzy match against plant names
    plant_pos = list(range(len(plant_names)))
    best_score_pn, best_pos_pn = _best_compatible(
        queries, plant_names, plant_pos, plants, sp_src,
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


def match_settlement_points(sps, rn_unit, plants) -> pd.DataFrame:
    lmp_exact, lmp_pool, lmp_pool_pos = build_lmp_index(plants)
    rn_unit_g = rn_unit.groupby("settlement_point")["substation"].agg(
        lambda s: sorted(set(s))
    )
    unit_names_g = rn_unit.groupby("settlement_point")["unit_name"].agg(
        lambda s: sorted(set(s))
    )
    plant_names = plants["plant_name_norm"].tolist()

    def sp_source(sp: str) -> str | None:
        return infer_source(sp, *rn_unit_g.get(sp, []), *unit_names_g.get(sp, []))

    rows = [match_one(sp, rn_unit_g, unit_names_g, plant_names, plants,
                     lmp_exact, lmp_pool, lmp_pool_pos, sp_source(sp))
            for sp in sps["settlement_point"]]
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
        ["manual", "lmp_node_designation", "fuzzy_lmp", "fuzzy_name"]
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

    known = set(out["settlement_point"])
    stale = sorted(set(ov["settlement_point"]) - known)
    if stale:
        print(f"[overrides] WARN: {len(stale)} override SPs not in current "
              f"SP universe (typo or retired): {stale[:5]}{'...' if len(stale) > 5 else ''}")

    ov_idx = ov.set_index("settlement_point")
    mask = out["settlement_point"].isin(ov_idx.index)
    out.loc[mask, "lat"] = out.loc[mask, "settlement_point"].map(ov_idx["lat"])
    out.loc[mask, "lon"] = out.loc[mask, "settlement_point"].map(ov_idx["lon"])
    out.loc[mask, "match_method"] = "manual"
    out.loc[mask, "match_confidence"] = 1.0
    print(f"[overrides] applied {int(mask.sum())} manual rows from {MANUAL_OVERRIDES_CSV.name}")
    return out


def main() -> int:
    if not MASTER_EIA860_CSV.exists():
        sys.exit(f"missing {MASTER_EIA860_CSV} — run extract_eia860.py first")

    sps = load_cdr_settlement_points()
    ccp_names = load_ccp_names()
    rn_unit = load_rn_to_unit()
    plants = load_plants()
    print(f"[input] priced SPs (non-HB/LZ/DC): {len(sps)}")
    print(f"[input] EIA-860 TX plants:         {len(plants)}")

    sps["sp_type"] = sps["settlement_point"].map(lambda s: classify(s, ccp_names))

    matched = match_settlement_points(sps, rn_unit, plants)
    out = sps.merge(matched, on="settlement_point", how="left")
    out = apply_manual_overrides(out)

    geocoded = out[out["lat"].notna()][
        ["settlement_point", "sp_type", "lat", "lon", "match_method", "match_confidence"]
    ]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    geocoded.to_csv(OUT_CSV, index=False)
    print(f"[output] {OUT_CSV}  rows={len(geocoded)}")

    rq = out[out["match_method"].isin(["review", "unmatched"])][
        ["settlement_point", "sp_type", "match_method", "match_confidence",
         "matched_plant", "matched_capacity_mw"]
    ]
    REVIEW_QUEUE_CSV.parent.mkdir(parents=True, exist_ok=True)
    rq.to_csv(REVIEW_QUEUE_CSV, index=False)
    print(f"[output] {REVIEW_QUEUE_CSV}  rows={len(rq)}")

    run_log(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
