"""R4 spike — can outaged elements be joined to anonymous constraint keys?

The handoff rates transmission-outage flags the **highest-value covariate** for
the mu-model, and plan/0085 rates the join the single most uncertain thing in
S4. This settles it before any outage work is scoped.

**The question has two legs, and only one of them was ever in doubt.**

  * **Leg A — does a constraint key carry a physical identity?** The keys
    (``constraint_name|contingency_name``) are opaque strings, but the NP4-191
    rows behind them are not: they already carry ``from_station`` /
    ``to_station`` / ``kV`` (``loaders.py:455``). This is the under-noted bridge
    the handoff never mentions. **Measured: it holds.**
  * **Leg B — is there anything on the other side to join TO?** A join needs a
    counterparty: outage records that name transmission elements. **Measured: no
    such feed is reachable.** Every outage product on public-reports is a
    *Resource* (generation) outage product — NP3-233 (hourly resource outage
    capacity, zonal aggregate, what we already ingest), NP1-346 (unplanned
    *Resource* outages, 3-day lag), NP3-161/162 (resource planned-outage
    capacity margin). Transmission Outage Scheduler detail is not there, and the
    outage reports that do exist sit behind the **MIS Secure Area**, which takes
    a Market Participant digital certificate this project does not hold.
    **Leg B is closed, not merely unsolved.**

**Keep the two numbers apart.** ``station_resolution_mass`` (leg A) is a
*key-resolution* rate. ``joinable_mass`` (leg B) is what the pre-registered bar
is denominated in, and it is zero while no named transmission-outage feed
exists. Reading leg A's 0.976 as an R4 pass is the one mistake this module is
written to prevent: the bridge is built and lands in a field.

**Pre-registered bar (plan/0085 commit 1), fixed before the run:**

    >= 0.60 joinable mu-mass  -> build the named outage covariate
    0.30-0.60                 -> build it, flagged, for the joinable subset only
    <  0.30                   -> degrade to the zonal aggregate already ingested
                                 (``outages_zonal``); the anticipatory-alert story
                                 weakens; S4 proceeds without a named covariate.

**How good is the fallback?** ``outages_zonal`` is four load-zone MW columns —
the same value for every constraint in a zone. It could be *localized* per
constraint if a constraint's stations could be placed in a zone. Leg C measures
the cheap route (match station names against settlement-point names) and finds
it weak (~9%), so localization, if wanted, has to come from the fitted SF map
(the settlement points with the largest ``|SF|`` for a constraint are the ones
electrically near it) — which needs a persisted ``--persist-sf`` run and is
deliberately NOT done here.

    docker compose run --rm compute python -m compute.probes.outage_join
    docker compose run --rm compute python -m compute.probes.outage_join --check-catalog
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg

from shared.settings import settings

log = logging.getLogger("compute.probes.outage_join")

# plan/0085 commit 1. Fixed before the run; not edited after.
R4_BUILD_BAR = 0.60
R4_FLAGGED_BAR = 0.30

# Outage tables in the DB, and the column that would name a transmission element.
# `outages_zonal` (NP3-233) is aggregate MW by load zone: there is no element
# column, which is exactly why leg B fails. Kept as a table so that if a named
# feed is ever ingested, this probe finds it instead of hardcoding the verdict.
NAMED_OUTAGE_SOURCES: dict[str, str] = {
    # table -> column naming the outaged transmission element
    # (empty: nothing ingested today names one)
}

# Products whose names/descriptions mention outages are all Resource-side. A
# transmission product would have to match this to change the verdict.
TRANSMISSION_HINT = re.compile(r"transmission|line|circuit|substation|element",
                               re.IGNORECASE)

# EMIL ids proposed as possible transmission-outage feeds and probed directly,
# because absence from the catalog listing and absence from the API are not the
# same claim. Both 404 on the live AND archive endpoints, while NP4-158-SG — same
# '-SG' suffix, used as the control — returns 200 on the same credentials in the
# same pass. So the suffix is not a permissions class and this is not an auth or
# rate-limit artifact: these products are simply not served by public-reports.
#
# Confirmed independently by the operator (2026-07-13): every ERCOT outage report
# lives behind the MIS Secure Area, which needs a Market Participant digital
# certificate — not the subscription key this project authenticates with. So leg
# B is not "we failed to find the feed", it is "the feed is not reachable on our
# access path", and it is closed rather than open. Getting it would be a data-
# ACQUISITION project (certificate + entitlement), not a modeling one; that is a
# decision to take deliberately, not something S4 should drift into.
CANDIDATE_EMIL_IDS = ("np3-220-sg", "np4-160-sg")
CONTROL_EMIL_ID = "np4-158-sg"  # known-served; distinguishes 404 from auth failure


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ------------------------------------------------------------------ leg A

def load_constraint_stations(conn, start: date, end: date) -> pd.DataFrame:
    """One row per constraint key: its mu-mass and the station pair behind it.

    ``start`` inclusive, ``end`` exclusive. Keyed exactly as ``panels.py`` keys
    the fit (``constraint_name|contingency_name``) so the mass shares here are
    denominated in the same currency the fit and the coverage probe use.

    ERCOT writes **empty strings**, not NULLs, when a constraint has no station
    pair (the BASE CASE rows, e.g. ``E_PASP``). A ``NOT NULL`` test therefore
    passes on every row and reports a vacuous 100% resolution — the first thing
    this probe got wrong. ``nullif(btrim(...), '')`` is load-bearing.

    ``n_pairs`` > 1 means the key's stations moved over the period (a re-rating
    or a renamed element). Those keys still resolve; they just need the pair
    carried per-row rather than per-key.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT constraint_name || '|' || contingency_name        AS key,
                   nullif(btrim(from_station), '')                   AS from_station,
                   nullif(btrim(to_station), '')                     AS to_station,
                   max(from_kv)                                      AS from_kv,
                   max(to_kv)                                        AS to_kv,
                   sum(greatest(shadow_price, 0))                    AS mu_mass,
                   count(*)                                          AS bind_hours
            FROM ercot_dam_shadow_prices
            WHERE interval_ts >= %s AND interval_ts < %s
              AND dst_flag = FALSE
              AND shadow_price IS NOT NULL
            GROUP BY 1, 2, 3
            """,
            (start, end),
        )
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["key", "from_station", "to_station",
                                     "from_kv", "to_kv", "mu_mass", "bind_hours"])
    df["mu_mass"] = df["mu_mass"].astype(float)
    df["resolved"] = df["from_station"].notna() & df["to_station"].notna()
    df["n_pairs"] = df.groupby("key")["key"].transform("size")
    return df


def station_resolution(df: pd.DataFrame) -> dict:
    """Leg A: what share of keys — and of mu-mass — resolves to a station pair?

    Mass-weighted is the number that matters: a covariate that reaches 95% of
    keys but only the ones that never bind is worthless. Key-count share is
    reported beside it precisely so that gap is visible.
    """
    total = float(df["mu_mass"].sum())
    res = df[df["resolved"]]
    keys = df.groupby("key")["resolved"].any()
    return {
        "n_keys": int(keys.size),
        "n_keys_resolved": int(keys.sum()),
        "key_share": float(keys.mean()) if keys.size else float("nan"),
        "station_resolution_mass": float(res["mu_mass"].sum()) / total if total else float("nan"),
        "n_stations": int(pd.unique(
            pd.concat([res["from_station"], res["to_station"]]).dropna()).size),
        "n_keys_multi_pair": int((df[df["resolved"]]
                                  .groupby("key")["from_station"].nunique() > 1).sum()),
        "unresolved_mass": total - float(res["mu_mass"].sum()),
    }


# ------------------------------------------------------------------ leg B

def named_outage_sources(conn) -> list[str]:
    """Which ingested tables name an outaged transmission element? (Expect none.)

    Checked against the DB rather than asserted, so that the day a named feed is
    ingested this probe reports a different verdict on its own.
    """
    found = []
    for table, col in NAMED_OUTAGE_SOURCES.items():
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (table, col),
            )
            if cur.fetchone():
                found.append(f"{table}.{col}")
    return found


def joinable_mass(df: pd.DataFrame, sources: list[str]) -> float:
    """The pre-registered currency: mu-mass joinable to a NAMED outage record.

    A join needs both legs. With no named transmission-outage source ingested,
    no amount of station resolution on the constraint side produces a joinable
    hour — hence zero, not 0.976. This function exists to make that asymmetry
    impossible to fudge.
    """
    if not sources:
        return 0.0
    # A named source exists (someone ingested one after this spike): the joinable
    # mass is the resolved mass, intersected with the stations that source names.
    total = float(df["mu_mass"].sum())
    resolved = float(df.loc[df["resolved"], "mu_mass"].sum()) / total if total else 0.0
    raise NotImplementedError(
        f"named outage source(s) {sources} now exist — re-scope the R4 join "
        f"against them; the 0085 verdict assumed none. Leg A caps the answer at "
        f"{resolved:.3f} of mu-mass."
    )


def check_catalog() -> pd.DataFrame:
    """Re-verify leg B against ERCOT's live product catalog. Network; optional.

    The claim 'ERCOT publishes no transmission-outage product' has a shelf life —
    it is a fact about a catalog, not a law. This re-checks it in ~2 API calls so
    the verdict can be refreshed rather than trusted.
    """
    import os
    import sys
    sys.path.insert(0, "/ercot_ingest")
    from ErcotClient import BASE_URL, ErcotClient  # noqa: E402

    client = ErcotClient()
    token = client._get_token()
    resp = client._session.get(
        BASE_URL,
        headers={"Authorization": f"Bearer {token}",
                 "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]},
        timeout=60,
    )
    resp.raise_for_status()
    products = resp.json()["_embedded"]["products"]

    rows = []
    for p in products:
        blob = " ".join(str(v) for v in p.values())
        if re.search(r"outage", blob, re.IGNORECASE):
            rows.append({
                "emil_id": p.get("emilId"),
                "name": p.get("name"),
                # A transmission-outage product would trip this. All known
                # outage products are Resource-side and will not.
                "transmission_hint": bool(TRANSMISSION_HINT.search(str(p.get("name")))),
            })
    return pd.DataFrame(rows)


def probe_candidates() -> pd.DataFrame:
    """Direct-GET the ``CANDIDATE_EMIL_IDS`` plus the control. Network; optional.

    Listed-in-the-catalog and served-by-the-API are different claims, so the
    candidates are hit directly rather than inferred from the listing. The
    control is what makes a 404 mean something: without a known-served product
    answering 200 in the same pass on the same token, a wall of 404s is equally
    consistent with a bad key.
    """
    import os
    import sys
    sys.path.insert(0, "/ercot_ingest")
    from ErcotClient import BASE_URL, ErcotClient  # noqa: E402

    client = ErcotClient()
    token = client._get_token()
    headers = {"Authorization": f"Bearer {token}",
               "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]}

    rows = []
    for emil in (*CANDIDATE_EMIL_IDS, CONTROL_EMIL_ID):
        for path in (f"/{emil}", f"/archive/{emil}"):
            resp = client._session.get(f"{BASE_URL}{path}", headers=headers, timeout=60)
            rows.append({
                "emil_id": emil,
                "endpoint": path,
                "status": resp.status_code,
                "role": "control" if emil == CONTROL_EMIL_ID else "candidate",
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ leg C

def name_localization(conn, df: pd.DataFrame) -> dict:
    """Can a constraint's stations be placed by NAME against settlement points?

    This is not part of the R4 bar — it grades the *fallback*. ``outages_zonal``
    gives four load-zone MW columns; the same four values for every constraint.
    If stations could be mapped to settlement points, each constraint could carry
    the outage MW of *its own* zone instead, which is a materially better
    covariate for nothing but a string join.

    Measured routes: exact match, and station-as-prefix (``BIGLAKE`` ->
    ``BIGLAKE_UNIT1``). Both are weak — ERCOT's station names and settlement-point
    names are different namespaces. The remaining route is electrical, not
    lexical: the SPs with the largest ``|SF|`` for a constraint ARE its
    neighbourhood, straight off the fitted map. That needs a persisted SF run and
    is left to commit 2.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT settlement_point FROM ercot_dam_spp")
        sps = {r[0] for r in cur.fetchall()}

    res = df[df["resolved"]]
    stations = pd.unique(pd.concat([res["from_station"], res["to_station"]]).dropna())

    exact = {s for s in stations if s in sps}
    prefixed = {s for s in stations if any(p.startswith(f"{s}_") for p in sps)}
    hit = exact | prefixed

    # Mass-weighted: a key counts as localizable only if BOTH its stations place.
    both = res[res["from_station"].isin(hit) & res["to_station"].isin(hit)]
    total = float(df["mu_mass"].sum())
    return {
        "n_stations": int(stations.size),
        "n_exact": len(exact),
        "n_prefix": len(prefixed),
        "station_hit_rate": len(hit) / stations.size if stations.size else float("nan"),
        "localizable_mass": float(both["mu_mass"].sum()) / total if total else float("nan"),
    }


# ------------------------------------------------------------------ verdict

def verdict(joinable: float) -> tuple[str, str]:
    """The pre-registered R4 decision. Bars are constants; this only reads them."""
    if joinable >= R4_BUILD_BAR:
        return "BUILD", "build the named outage covariate"
    if joinable >= R4_FLAGGED_BAR:
        return "FLAGGED", "build it, flagged, for the joinable subset only"
    return "ZONAL_FALLBACK", (
        "degrade to the zonal aggregate already ingested (outages_zonal); "
        "the anticipatory-alert story weakens and S4 proceeds without a named "
        "outage covariate"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=_parse_date, default=None,
                   help="Inclusive start (default: earliest NP4-191 date).")
    p.add_argument("--end", type=_parse_date, default=None,
                   help="Exclusive end (default: latest NP4-191 date + 1d).")
    p.add_argument("--check-catalog", action="store_true",
                   help="Re-verify leg B against ERCOT's live product catalog "
                        "(network). The 'no transmission-outage product' finding "
                        "is a fact about a catalog and can expire.")
    p.add_argument("--sample", type=int, default=15,
                   help="Rows in the hand-audit sample (top keys by mu-mass).")
    p.add_argument("--out", type=str, default=None, help="Write per-key rows to CSV.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    with psycopg.connect(settings.pg_dsn) as conn:
        if args.start is None or args.end is None:
            with conn.cursor() as cur:
                cur.execute("SELECT min(interval_ts)::date, max(interval_ts)::date "
                            "FROM ercot_dam_shadow_prices")
                dmin, dmax = cur.fetchone()
            start = args.start or dmin
            end = args.end or (dmax + timedelta(days=1))
        else:
            start, end = args.start, args.end

        log.info("loading NP4-191 station bridge [%s, %s)", start, end)
        df = load_constraint_stations(conn, start, end)
        if df.empty:
            log.error("no shadow-price rows over [%s, %s)", start, end)
            return 3

        a = station_resolution(df)
        sources = named_outage_sources(conn)
        c = name_localization(conn, df)

    joinable = joinable_mass(df, sources)
    tag, action = verdict(joinable)

    pd.set_option("display.width", 250)

    print(f"\n=== R4 spike — outage <-> constraint join   [{start} .. {end}) ===")

    print("\n--- leg A: does a constraint key carry a physical identity?")
    print(f"keys                                  : {a['n_keys']}")
    print(f"keys resolving to a station pair      : {a['n_keys_resolved']} "
          f"({a['key_share']:.3f})")
    print(f"mu-mass behind a station pair         : {a['station_resolution_mass']:.3f}"
          f"   <-- key-resolution rate, NOT the R4 bar")
    print(f"distinct stations named               : {a['n_stations']}")
    print(f"keys whose station pair moved         : {a['n_keys_multi_pair']}")

    print("\n--- leg B: is there a named outage feed to join TO?")
    if sources:
        print(f"named transmission-outage source(s)   : {', '.join(sources)}")
    else:
        print("named transmission-outage source(s)   : NONE INGESTED")
        print("  every ERCOT public outage product is Resource-side:")
        print("    NP3-233  hourly resource outage capacity  (zonal MW — what we have)")
        print("    NP1-346  unplanned RESOURCE outages       (generation, 3-day lag)")
        print("    NP3-161/162  resource planned-outage capacity margin")
        print("  Transmission Outage Scheduler detail is not published.")
    print(f"joinable mu-mass (the R4 currency)    : {joinable:.3f}")

    print("\n--- leg C: how good can the zonal fallback be? (not the bar)")
    print(f"stations matching a settlement-point name : {c['n_exact']} exact + "
          f"{c['n_prefix']} prefix of {c['n_stations']} ({c['station_hit_rate']:.3f})")
    print(f"mu-mass localizable by name               : {c['localizable_mass']:.3f}")
    print("  -> too weak to localize by name. To give each constraint its OWN zone's")
    print("     outage MW, take the zone of its highest-|SF| settlement points off the")
    print("     fitted map (needs a --persist-sf run). Otherwise the covariate is the")
    print("     four zonal columns, identical for every constraint.")

    if args.check_catalog:
        cat = check_catalog()
        print("\n--- leg B re-check: ERCOT live product catalog")
        print(cat.to_string(index=False))
        if cat["transmission_hint"].any():
            print("  !! a product name hints at TRANSMISSION outages — re-scope R4.")
        else:
            print("  confirmed: all outage products are Resource-side.")

        cand = probe_candidates()
        print("\n--- leg B re-check: candidate EMIL ids, hit directly")
        print(cand.to_string(index=False))
        served = cand[(cand.role == "candidate") & (cand.status == 200)]
        control_ok = (cand[(cand.role == "control")].status == 200).any()
        if not control_ok:
            print("  !! the CONTROL did not serve — the 404s below prove nothing "
                  "about the candidates; fix credentials and re-run.")
        elif len(served):
            print(f"  !! {sorted(set(served.emil_id))} now serve — inspect them and "
                  "re-scope R4.")
        else:
            print("  confirmed: candidates 404 while the control serves. Not an "
                  "auth artifact — these products are not on public-reports.")

    print(f"\n--- hand-audit sample (top {args.sample} keys by mu-mass)")
    show = (df.sort_values("mu_mass", ascending=False)
              .head(args.sample)[["key", "from_station", "to_station", "from_kv",
                                  "to_kv", "bind_hours", "mu_mass", "resolved"]])
    print(show.to_string(index=False, float_format=lambda v: f"{v:10.1f}"))

    print(f"\n=== R4 VERDICT (bar: >={R4_BUILD_BAR:.2f} build / "
          f">={R4_FLAGGED_BAR:.2f} flagged / else zonal) ===")
    print(f"joinable mu-mass {joinable:.3f} -> {tag}")
    print(f"  {action}")
    print("\nThe join KEY is not the problem — leg A resolves "
          f"{a['station_resolution_mass']:.1%} of mu-mass to named stations, well "
          f"past the {R4_BUILD_BAR:.0%} bar.\nThe COUNTERPARTY is: ERCOT publishes no "
          "transmission-outage feed, so there is nothing to join to.\nThat is a "
          "data-availability finding, not a modelling one — do not let it become a "
          "modelling project.")

    if args.out:
        df.to_csv(args.out, index=False)
        log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
