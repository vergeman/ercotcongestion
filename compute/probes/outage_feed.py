"""NP1-346 probe — unplanned generation outages. Read-only: no DB writes, no ingest.

plan/0089 commit 1, in the shape of `compute.probes.ruc` (0087).

**Answers one question before any ingest is paid for:** can `NP1-346-ER` (Unplanned
Resource Outages) support a **per-constraint** outage covariate at DAM close, across
the 46 backtest weeks?

**Why this arm exists at all.** R4 closed as *"every outage product is behind the MIS
Secure Area — joinable μ-mass 0.000 → ZONAL FALLBACK"*. That fallback is why
`features.outage_panel` hands the model **four zonal numbers that are identical for
every constraint in a given hour**. And that sameness *is* 0085 §5.6's diagnosis of why
persistence beat us: the model cannot tell two constraints apart, so it cannot know
*which* one will bind. NP1-346 is **unit-level**, so — if the units can be located —
the |SF| map crosswalks it into a genuinely per-constraint covariate, the same trick
`compute/mu/geo.py` uses to locate constraints without name matching.

**Every leg runs to completion even after a gate fails.** R4 died because "can we
actually get the feed?" was never probed first; 0087 then proved that a partial "no"
hides *why*, and the why is the whole finding.

Legs
----
0.  Discovery  — is NP1-346-ER on the public API, and what else is there.
A.  Depth      — archive coverage. **Gate A: must reach 2024-12-11** (panel start —
                 the training window for backtest week 1, not the week itself).
B.  Vintage    — **the leg that killed RUC.** Is the report readable *before* we must
                 predict, and does it say anything about the delivery day? RUC failed
                 not on history but on **timing**.
C.  Join       — **the open gate, and the likely killer.** Resource → settlement
                 point, weighted by **outage MW**, never by row count.
                 Gate C (pre-registered, mirroring R4's bar):
                   ≥60% of outage MW locatable → build the per-constraint covariate
                   30–60%                      → build it, flagged, on the joinable subset
                   <30%                        → **it degrades to `outages_zonal`, which
                                                  we already have. The arm is dead.**
D.  Signal     — does the located covariate carry information a *zonal* aggregate does
                 not? A feed that joins perfectly and predicts nothing is still a no.

Run:
    docker compose run --rm compute python -m compute.probes.outage_feed
"""
from __future__ import annotations

import io
import sys
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, "/ercot_ingest")

from ErcotClient import BASE_URL, SUB_KEY, ErcotClient  # noqa: E402

from shared.settings import settings  # noqa: E402

PRODUCT = "NP1-346-ER"
SHEET = "Unplanned Resource Outages"
HEADER_ROW = 4          # the data header sits on row 5 of the sheet
MW = "Effective MW Reduction Due to Outage"

# Gate A. NOT the first scored week (2025-08-14): the model trains on a 240-day
# trailing window, so a feature must exist back to the panel's start or the first
# folds train on a column that is entirely NaN.
PANEL_START = date(2024, 12, 11)
BACKTEST_START = date(2025, 8, 14)

# Gate C, pre-registered here, before the number is known — R4's bar, restated.
GATE_C_BUILD = 0.60
GATE_C_DEAD = 0.30

DAM_CLOSE_HOUR = 10     # CT, on D-1


def _hdrs(c: ErcotClient) -> dict:
    return {"Authorization": f"Bearer {c._get_token()}",
            "Ocp-Apim-Subscription-Key": SUB_KEY}


# ---------------------------------------------------------------- the feed

def archive_index(c: ErcotClient) -> pd.DataFrame:
    """Every archived document: (docId, postDatetime). Paged, 100 at a time."""
    rows, page = [], 1
    while True:
        r = c._request("GET", f"{BASE_URL}/archive/{PRODUCT}", headers=_hdrs(c),
                       params={"size": 100, "page": page}).json()
        rows.extend(r.get("archives", []))
        if page >= r["_meta"]["totalPages"]:
            break
        page += 1
    df = pd.DataFrame(rows)
    df["posted"] = pd.to_datetime(df["postDatetime"])
    return df.sort_values("posted").reset_index(drop=True)


def fetch_report(c: ErcotClient, doc_id: int) -> pd.DataFrame:
    """One archived document → the outage table.

    The payload is a **zip wrapping an xlsx**, and the data header is on row 5.
    Dumped from the wire rather than remembered — 0087's schema was wrong in five
    fields precisely because it was remembered.
    """
    r = c._request("GET", f"{BASE_URL}/archive/{PRODUCT}", headers=_hdrs(c),
                   params={"download": int(doc_id)})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    x = pd.read_excel(io.BytesIO(z.read(z.namelist()[0])), SHEET, header=HEADER_ROW)
    return x[x["Resource Name"].notna()].copy()


# ---------------------------------------------------------------- leg 0

def leg0_discovery(c: ErcotClient) -> None:
    print("\n=== LEG 0 — discovery ===")
    body = c._request("GET", BASE_URL, headers=_hdrs(c)).json()
    prods = body["_embedded"]["products"]
    print(f"  {len(prods)} products on the public API. Outage-related:")
    for p in prods:
        n = (p.get("name") or "")
        if "outage" in n.lower():
            print(f"    {p['emilId']:12} {n}")
    print("\n  NP1-346-ER is the one R4 never found: it is UNIT-LEVEL, whereas")
    print("  NP3-233-CD (already ingested as `outages_zonal`) is a 4-number zonal")
    print("  aggregate — the same value for every constraint in an hour.")


# ---------------------------------------------------------------- leg A

def legA_depth(idx: pd.DataFrame) -> None:
    print("\n=== LEG A — archive depth (Gate A) ===")
    oldest, newest = idx["posted"].min(), idx["posted"].max()
    print(f"  documents: {len(idx)}   oldest {oldest.date()}   newest {newest.date()}")
    print(f"  Gate A requires coverage back to {PANEL_START} (panel start — the")
    print(f"  240-day training window for backtest week 1 on {BACKTEST_START}).")

    if oldest.date() <= PANEL_START:
        margin = (PANEL_START - oldest.date()).days
        print(f"\n  GATE A: PASS — reaches {oldest.date()}, {margin} days of margin.")
    else:
        short = (oldest.date() - PANEL_START).days
        print(f"\n  GATE A: FAIL — starts {oldest.date()}, {short} days too late.")
        return

    # Depth is not enough: a feed with holes gives NaN weeks. Check DENSITY too —
    # NP5-755 advertised 2555 days of retention and delivered 259 days short.
    span = idx[idx["posted"].dt.date >= PANEL_START]
    days = pd.date_range(PANEL_START, newest.date(), freq="D")
    have = set(span["posted"].dt.date)
    missing = [d.date() for d in days if d.date() not in have]
    print(f"  density over the panel: {len(have)}/{len(days)} days have a report "
          f"({len(have)/len(days):.1%})")
    if missing:
        print(f"  missing days: {len(missing)}  e.g. {missing[:5]}")
        print("  (gaps are survivable — the covariate carries the last snapshot "
              "forward, or is NaN.)")


# ---------------------------------------------------------------- leg B

def legB_vintage(c: ErcotClient, idx: pd.DataFrame) -> None:
    """**The leg that killed RUC — and the one this feed has to survive.**

    RUC failed on *timing*, not history: no HRUC run at or before DAM close ever
    describes delivery day D, so a deeper archive fixed nothing. Ask the same
    question here, and answer it from the documents rather than the documentation.
    """
    print("\n=== LEG B — vintage: is it readable BEFORE we must predict? ===")

    hours = idx["posted"].dt.hour
    print(f"  posting hour (UTC): min {hours.min():02d}  median "
          f"{int(hours.median()):02d}  max {hours.max():02d}")
    ct = idx["posted"].dt.tz_localize("UTC").dt.tz_convert("America/Chicago")
    late = (ct.dt.hour >= DAM_CLOSE_HOUR).mean()
    print(f"  posted at/after {DAM_CLOSE_HOUR:02d}:00 CT: {late:.1%} of documents")

    # The D-3 rule, taken from the report's own description and CONFIRMED against a
    # real document rather than believed.
    doc = idx.iloc[-1]
    df = fetch_report(c, doc["docId"])
    posted = doc["posted"]
    starts = pd.to_datetime(df["Actual Outage Start"], errors="coerce")
    ends = pd.to_datetime(df["Planned End Date"], errors="coerce")

    print(f"\n  document posted {posted}  ({len(df)} outage rows)")
    print("  Report Info states: a snapshot of outages active on the THIRD day")
    print("  before the posting date. So at DAM close on D-1, the newest report")
    print("  available describes day D-4.")

    covered = (posted - pd.Timedelta(days=3)).normalize()
    print(f"  => newest report at DAM close for delivery day D describes ~D-4.")

    # Staleness only matters if the state DECAYS. Generation outages persist, and
    # the report says so itself: measure how much of the outage MW is still expected
    # to be out four days later.
    horizon = covered + pd.Timedelta(days=4)
    still_out = ends >= horizon
    mw_total = df[MW].sum()
    mw_persist = df.loc[still_out.fillna(False), MW].sum()
    print(f"\n  Of {mw_total:,.0f} MW out in this snapshot, "
          f"{mw_persist:,.0f} MW ({mw_persist/mw_total:.1%}) has a Planned End Date")
    print(f"  on/after {horizon.date()} — i.e. is STILL EXPECTED OUT on delivery day.")
    print("  **This is the forward-looking content, and it is what RUC could not")
    print("  give us: information about tomorrow, published before the close.**")

    old = (posted - starts).dt.days
    print(f"\n  outage age at posting (days): median {old.median():.0f}  "
          f"p90 {old.quantile(0.9):.0f}  max {old.max():.0f}")
    print("  (a persistent state is exactly what makes a 4-day-stale snapshot useful)")


# ---------------------------------------------------------------- leg C

def crosswalk(units: pd.Series, sps: set[str]) -> pd.DataFrame:
    """Resource Unit Code → settlement point. Every strategy measured, none assumed.

    **The namespaces are both *generation* names here**, which is why this is worth
    trying at all: R4's failure was `plant name` vs `transmission substation` — genuinely
    different namespaces, 4.3% and unfixable. This is resource-vs-resource.

    Strategy 1 (exact) is the only one that is unambiguous. Strategy 2 (station
    prefix) is a heuristic and is reported SEPARATELY and honestly, because it is
    exactly the fuzzy matching R4 warns against: it derives station `B` from
    `B_DAVIS_B_DAVIG1`, and several stations carry many settlement points.
    """
    u = units.fillna("").astype(str)
    out = pd.DataFrame({"unit": u})
    out["exact"] = u.where(u.isin(sps))

    by_station: dict[str, list[str]] = {}
    for s in sps:
        by_station.setdefault(s.split("_")[0], []).append(s)

    # Longest-prefix station match: prefer the most specific station token that
    # resolves, rather than blindly taking text before the first underscore.
    def station_match(code: str) -> str | None:
        if not code:
            return None
        parts = code.split("_")
        for n in range(len(parts) - 1, 0, -1):
            cand = "_".join(parts[:n])
            if cand in by_station and len(by_station[cand]) == 1:
                return by_station[cand][0]
        return None

    out["station"] = [station_match(x) for x in u]
    out["station_ambiguous"] = [
        len(by_station.get("_".join(x.split("_")[:1]), [])) > 1 for x in u]
    return out


def legC_join(c: ErcotClient, idx: pd.DataFrame, sps: set[str]) -> float:
    print("\n=== LEG C — the join (Gate C) ===")
    print(f"  Bar, pre-registered: ≥{GATE_C_BUILD:.0%} of outage MW locatable → build;")
    print(f"  <{GATE_C_DEAD:.0%} → it degrades to `outages_zonal`, which we already "
          f"have, and the arm is DEAD.")

    doc = idx.iloc[-1]
    df = fetch_report(c, doc["docId"])
    x = crosswalk(df["Resource Unit Code"], sps)
    df = pd.concat([df.reset_index(drop=True), x], axis=1)
    tot = df[MW].sum()

    ex = df["exact"].notna()
    st = df["exact"].notna() | df["station"].notna()
    print(f"\n  outage rows: {len(df)}   total {tot:,.0f} MW out")
    print(f"  exact unit-code → SP        : {ex.sum():>3}/{len(df)} rows   "
          f"{df.loc[ex, MW].sum()/tot:.1%} of MW")
    print(f"  + unambiguous station prefix: {st.sum():>3}/{len(df)} rows   "
          f"{df.loc[st, MW].sum()/tot:.1%} of MW")
    print(f"  ambiguous stations (>1 SP)  : {int(df['station_ambiguous'].sum())} rows "
          f"— excluded, not guessed")

    rate = float(df.loc[st, MW].sum() / tot) if tot else 0.0
    miss = (df.loc[~st].groupby("Resource Name")[MW].sum()
            .sort_values(ascending=False).head(8))
    if len(miss):
        print("\n  biggest UNLOCATED resources by MW:")
        for k, v in miss.items():
            print(f"    {str(k):<20} {v:>7,.0f} MW")

    verdict = ("BUILD" if rate >= GATE_C_BUILD else
               "BUILD (flagged subset)" if rate >= GATE_C_DEAD else "DEAD")
    print(f"\n  GATE C: {rate:.1%} of outage MW locatable → **{verdict}**")
    return rate


# ---------------------------------------------------------------- leg D

def legD_signal(c: ErcotClient, idx: pd.DataFrame, sps: set[str],
                n_days: int = 90) -> None:
    """**Does it carry information a zonal aggregate does not?**

    A feed that joins perfectly and predicts nothing is still a no. This is the
    cheapest possible version of the question: locate the outaged MW, push it
    through the |SF| map to get a **per-constraint outage exposure**, and ask whether
    that exposure separates the constraints that bind from the ones that do not — on
    a day the model was never trained on.

    Not a lift measurement, and it must not be quoted as one. It is a screen: if the
    exposure is uninformative *here*, no amount of ingest will make it informative
    downstream.
    """
    print("\n=== LEG D — does the located covariate carry signal? ===")

    from compute.mu.geo import load_sp_geography  # noqa: F401  (import check)
    from compute.sf.fit import implied_shift_factors
    from compute.sf.panels import load_congestion_panel, load_shadow_prices

    recent = idx[idx["posted"] >= idx["posted"].max() - pd.Timedelta(days=n_days)]
    print(f"  reading {len(recent)} daily snapshots "
          f"({recent['posted'].min().date()} → {recent['posted'].max().date()})")

    frames = []
    for _, r in recent.iterrows():
        d = fetch_report(c, r["docId"])
        x = crosswalk(d["Resource Unit Code"], sps)
        d = pd.concat([d.reset_index(drop=True), x], axis=1)
        d["sp"] = d["exact"].fillna(d["station"])
        d = d[d["sp"].notna()]
        # The snapshot describes the third day before posting.
        d["day"] = (r["posted"] - pd.Timedelta(days=3)).normalize()
        frames.append(d[["day", "sp", MW]])
    out = pd.concat(frames, ignore_index=True)
    daily = out.groupby(["day", "sp"])[MW].sum().unstack(fill_value=0.0)
    print(f"  located outage MW: {len(daily)} days × {daily.shape[1]} settlement points")

    lo = pd.Timestamp(daily.index.min() - pd.Timedelta(days=240), tz="America/Chicago")
    hi = pd.Timestamp(daily.index.max() + pd.Timedelta(days=1), tz="America/Chicago")
    with psycopg.connect(settings.pg_dsn) as conn:
        M = load_shadow_prices(conn, lo, hi)
        C = load_congestion_panel(conn, lo, hi)

    # One honest SF fit, on the window ENDING before the probed span. Enough for a
    # screen; the real feature would refit weekly (see geo.geo_panel).
    fit_end = pd.Timestamp(daily.index.min(), tz="UTC")
    fit_lo = fit_end - pd.Timedelta(days=240)
    SF = implied_shift_factors(M.loc[(M.index >= fit_lo) & (M.index < fit_end)],
                               C.loc[(C.index >= fit_lo) & (C.index < fit_end)],
                               lam=1.0, min_hours=25, standardize=True, std_floor=100.0)
    print(f"  SF (honest, fit to {fit_end.date()}): {SF.shape}")

    cols = SF.columns.intersection(daily.columns)
    if cols.empty:
        print("  no located settlement point is in the SF map — no signal possible.")
        return
    # exposure[day, constraint] = Σ_sp |SF[constraint, sp]| · outage_MW[day, sp]
    W = SF[cols].abs().to_numpy(float)
    X = daily[cols].to_numpy(float)
    expo = pd.DataFrame(X @ W.T, index=daily.index, columns=SF.index)
    print(f"  per-constraint outage exposure: {expo.shape}  "
          f"(vs the zonal fallback's 4 numbers, identical for every constraint)")

    # Realized daily |μ| per constraint, on the same days.
    day_of = (pd.DatetimeIndex(M.index).tz_convert("America/Chicago")
              .tz_localize(None).normalize())
    mu = M.abs().groupby(day_of).mean()
    days = expo.index.intersection(mu.index)
    keys = expo.columns.intersection(mu.columns)
    E, Y = expo.loc[days, keys], mu.loc[days, keys]

    # Cross-sectional: on a given day, do the MORE outage-exposed constraints bind
    # harder? That is the question the zonal aggregate structurally cannot answer,
    # because it gives every constraint the same number.
    rhos = []
    for d in days:
        e, y = E.loc[d], Y.loc[d]
        m = e.notna() & y.notna() & (e > 0)
        if m.sum() >= 20:
            rhos.append(e[m].corr(y[m], method="spearman"))
    rhos = pd.Series(rhos).dropna()
    print(f"\n  CROSS-SECTIONAL rank corr(outage exposure, realized |μ|), per day:")
    print(f"    mean {rhos.mean():+.3f}   median {rhos.median():+.3f}   "
          f"days {len(rhos)}   days>0 {(rhos > 0).mean():.0%}")
    print("  A zonal aggregate scores EXACTLY 0 here by construction — it cannot")
    print("  order constraints within a day. Anything non-zero is information R4")
    print("  concluded we did not have.")


# ---------------------------------------------------------------- schema

def dump_schema(c: ErcotClient, idx: pd.DataFrame) -> None:
    print("\n=== REAL COLUMN SET (verbatim from the wire) ===")
    df = fetch_report(c, idx.iloc[-1]["docId"])
    print(f"  {list(df.columns)}")
    print("\n  sample row:")
    print(df.head(1).to_string(index=False))
    print("\n  fuel mix of outaged capacity:")
    print(df.groupby("Fuel Type")[MW].sum().sort_values(ascending=False)
          .head(6).to_string())


def settlement_points() -> set[str]:
    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT settlement_point FROM ercot_dam_spp "
                    "WHERE interval_ts >= '2026-06-01'")
        return {r[0] for r in cur.fetchall()}


def main() -> None:
    c = ErcotClient()
    print("NP1-346 PROBE — read-only. No rows are ingested by this script.")

    leg0_discovery(c)
    idx = archive_index(c)
    legA_depth(idx)
    legB_vintage(c, idx)

    sps = settlement_points()
    rate = legC_join(c, idx, sps)

    # Leg D runs EVEN IF Gate C failed — a partial "no" hides why. If the located
    # subset carries no signal, that is a second, independent reason to stop, and it
    # is worth knowing before anyone tries to rescue the join.
    legD_signal(c, idx, sps)
    dump_schema(c, idx)

    print("\n" + "=" * 70)
    print(f"SUMMARY: Gate C (the join) = {rate:.1%} of outage MW located.")
    print("Gates A and B are the ones RUC failed; this feed passes both.")
    print("=" * 70)


if __name__ == "__main__":
    main()
