"""RUC probe. Read-only: no DB writes, no model code.

Question: can the RUC enforced-constraint feed support a DAM-close mu forecast over
the 46 backtest weeks?

Legs
----
0. Discovery   — which RUC constraint products exist on the public API. Check the
                 product IDs rather than trusting them.
A. Depth       — earliest retrievable postDatetime, from both the CD and archive
                 endpoints. Must reach 2025-08-14 (backtest week 1).
A2. DAM-close  — does any RUC run at or before DAM close (10:00 CT on D-1) publish
                 rows for delivery day D? This is the deciding check: a feed we can't
                 read before we predict is useless as a covariate.
B. Namespace   — mu-mass-weighted match rate of ConstraintName|ContingencyName
                 against NP4-191. join % >= 90%. Being able to read it isn't the
                 same as being able to join it.
C. Cadence     — distinct RUCTimestamps per day. Informational, not a gate.

Run:
    docker compose run --rm compute python -m compute.probes.ruc
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
import psycopg

sys.path.insert(0, "/ercot_ingest")

from ErcotClient import BASE_URL, SUB_KEY, ErcotClient  # noqa: E402

from shared.settings import settings  # noqa: E402

# backtest week 1. An archive that stops short can't be validated against the
# existing 46-week harness.
BACKTEST_START = date(2025, 8, 14)

# DAM closes 10:00 CT on D-1. RUC timestamps are naive Central.
DAM_CLOSE_HOUR = 10

GATE_B_THRESHOLD = 0.90

HRUC = "/np5-755-cd/hrly_ruc_act_and_bind_tran_const"

# The products the plan is written against. Checked, not assumed.
PLANNED = ["np5-753-cd", "np5-754-cd"]


def _hdrs(client: ErcotClient) -> dict:
    return {
        "Authorization": f"Bearer {client._get_token()}",
        "Ocp-Apim-Subscription-Key": SUB_KEY,
    }


# ---------------------------------------------------------------- leg 0

def leg0_discovery(client: ErcotClient) -> None:
    print("\n=== LEG 0 — product discovery ===")
    body = client._request("GET", BASE_URL, headers=_hdrs(client)).json()
    products = body["_embedded"]["products"]

    for pid in PLANNED:
        status = client._request(
            "GET", f"{BASE_URL}/{pid}", headers=_hdrs(client)
        ).status_code
        verdict = "EXISTS" if status == 200 else f"ABSENT (HTTP {status})"
        print(f"  {pid:14} {verdict}")

    print("\n  RUC constraint products actually on the public API:")
    for p in products:
        name = p.get("name") or ""
        if "RUC" in name.upper() and "CONSTRAINT" in name.upper():
            print(f"    {p['emilId']:12} {name}")
            print(f"    {'':12} frequency: {p.get('generationFrequency')}")


# ---------------------------------------------------------------- leg A

def _archive_bounds(client: ErcotClient, product: str) -> tuple[int, str | None]:
    """(total docs, oldest postDatetime) from the archive endpoint."""
    url = f"{BASE_URL}/archive/{product}"
    meta = client._request(
        "GET", url, headers=_hdrs(client), params={"size": 1}
    ).json()["_meta"]
    total = meta["totalRecords"]
    if not total:
        return 0, None
    # Archive sorts postDatetime DESC, so the last page holds the oldest doc.
    last = client._request(
        "GET", url, headers=_hdrs(client), params={"size": 1, "page": total}
    ).json().get("archives", [])
    return total, last[0]["postDatetime"] if last else None


def legA_depth(client: ErcotClient) -> date | None:
    print("\n=== LEG A — archive depth (Gate A) ===")
    print(f"  Gate A requires coverage back to {BACKTEST_START} (backtest week 1).\n")

    earliest: date | None = None
    for product in ["np5-755-cd", "np6-86-cd"]:
        total, oldest = _archive_bounds(client, product)
        print(f"  {product:12} archive docs: {total:>6}   oldest: {oldest}")
        if product == "np5-755-cd" and oldest:
            earliest = pd.to_datetime(oldest).date()

    # The CD endpoint serves a rolling window; the archive is the deeper store.
    # Report both — the archive's advertised retention is metadata, not actual rows.
    print("\n  CD-endpoint retention spot-check (rows returned by postedDatetime):")
    for day in ["2025-08-14", "2026-04-01", "2026-05-01", "2026-06-01"]:
        df = client.get(
            HRUC,
            postedDatetimeFrom=f"{day}T00:00:00",
            postedDatetimeTo=f"{day}T23:59:59",
        )
        print(f"    {day}: {len(df):>6} rows")

    if earliest is None:
        print("\n  GATE A: FAIL — no NP5-755 archive at all.")
    elif earliest <= BACKTEST_START:
        print(f"\n  GATE A: PASS — archive reaches {earliest} <= {BACKTEST_START}.")
    else:
        short = (earliest - BACKTEST_START).days
        print(
            f"\n  GATE A: FAIL — archive starts {earliest}, which is {short} days "
            f"AFTER backtest week 1 ({BACKTEST_START})."
        )
    return earliest


# ---------------------------------------------------------------- leg A2

def legA2_dam_close(client: ErcotClient, start: str, end: str) -> None:
    """The deciding leg.

    Delivery day D is predicted at DAM close (10:00 CT on D-1). A RUC run is only a
    valid covariate if a run at or before that moment already describes day D.
    Measure it directly rather than trusting ERCOT's documentation.
    """
    print("\n=== LEG A2 — usability at DAM close ===")
    df = client.get(HRUC, postedDatetimeFrom=start, postedDatetimeTo=end)
    if df.empty:
        print("  no rows in window; cannot evaluate.")
        return

    ruc_ts = pd.to_datetime(df["RUCTimestamp"])
    delivery = pd.to_datetime(df["deliveryDate"])
    df = df.assign(
        run_hour=ruc_ts.dt.hour,
        run_day=ruc_ts.dt.date,
        days_ahead=(delivery.dt.date - ruc_ts.dt.date).map(lambda d: d.days),
    )

    pre_close = df[df["run_hour"] <= DAM_CLOSE_HOUR]
    forward = int((pre_close["days_ahead"] >= 1).sum())
    print(
        f"  Rows from runs at/before {DAM_CLOSE_HOUR:02d}:00 CT that describe a "
        f"FUTURE delivery day: {forward} of {len(pre_close)}"
    )

    runs = df.groupby(["run_day", "run_hour"])["days_ahead"].max().reset_index()
    forward_runs = runs[runs["days_ahead"] >= 1]
    if forward_runs.empty:
        print("  No run in the window EVER reaches the next delivery day.")
        return

    first_hour = int(forward_runs["run_hour"].min())
    print(f"  Earliest run hour that sees the next delivery day: {first_hour:02d}:00 CT")
    lag = first_hour - DAM_CLOSE_HOUR
    if lag > 0:
        print(
            f"  => The first RUC view of day D lands {lag}h AFTER DAM close.\n"
            f"     Joining it to a DAM-close forecast is a {lag}h lookahead."
        )


# ---------------------------------------------------------------- leg B

def _key(constraint: pd.Series, contingency: pd.Series) -> pd.Series:
    """Must match compute/sf/panels.py:53 exactly. Keep the two in sync."""
    return (
        constraint.astype(str).str.strip() + "|" + contingency.astype(str).str.strip()
    )


def legB_namespace(client: ErcotClient, start: str, end: str) -> None:
    print("\n=== LEG B — key namespace (Gate B) ===")
    ruc = client.get(HRUC, postedDatetimeFrom=start, postedDatetimeTo=end)
    if ruc.empty:
        print("  no RUC rows in window; Gate B not evaluable.")
        return
    ruc_keys = set(_key(ruc["constraintName"], ruc["contingencyName"]))

    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT constraint_name, contingency_name, SUM(shadow_price) AS mu_mass
            FROM ercot_dam_shadow_prices
            WHERE interval_ts >= %s AND interval_ts < %s
              AND dst_flag = FALSE
              AND shadow_price IS NOT NULL
            GROUP BY 1, 2
            """,
            (start, end),
        )
        rows = cur.fetchall()

    if not rows:
        print("  no NP4-191 mu in window; Gate B not evaluable.")
        return

    mu = pd.DataFrame(rows, columns=["constraint_name", "contingency_name", "mu_mass"])
    mu["key"] = _key(mu["constraint_name"], mu["contingency_name"])
    mu["mu_mass"] = mu["mu_mass"].astype(float)

    matched = mu["key"].isin(ruc_keys)
    total_mass = mu["mu_mass"].sum()
    hit_mass = mu.loc[matched, "mu_mass"].sum()
    # Weight by mu-mass, not key count: key count flatters the result, mu-mass is
    # what the score is actually made of.
    rate = hit_mass / total_mass if total_mass else 0.0

    print(f"  RUC keys in window:        {len(ruc_keys)}")
    print(f"  NP4-191 binding keys:      {len(mu)}")
    print(f"  Keys matched:              {int(matched.sum())} ({matched.mean():.1%} by count)")
    print(f"  mu-mass matched:           {rate:.1%}  (threshold {GATE_B_THRESHOLD:.0%})")
    verdict = "PASS" if rate >= GATE_B_THRESHOLD else "FAIL"
    print(f"\n  GATE B: {verdict}")


# ---------------------------------------------------------------- leg C

def legC_cadence(client: ErcotClient, start: str, end: str) -> None:
    print("\n=== LEG C — cadence ===")
    df = client.get(HRUC, postedDatetimeFrom=start, postedDatetimeTo=end)
    if df.empty:
        print("  no rows in window.")
        return
    ruc_ts = pd.to_datetime(df["RUCTimestamp"])
    per_day = ruc_ts.groupby(ruc_ts.dt.date).nunique()
    print(f"  distinct RUC runs in window: {ruc_ts.nunique()}")
    print(f"  runs/day: min {per_day.min()}, median {per_day.median():.0f}, max {per_day.max()}")
    median = per_day.median()
    label = "hourly" if median >= 20 else "nightly" if median >= 1 else "weekly"
    print(f"  => cadence is {label.upper()}")


# ---------------------------------------------------------------- schema

def dump_schema(client: ErcotClient, start: str, end: str) -> None:
    print("\n=== REAL COLUMN SET (verbatim — no schema from memory) ===")
    df = client.get(HRUC, postedDatetimeFrom=start, postedDatetimeTo=end)
    if df.empty:
        print("  no rows.")
        return
    print(f"  {list(df.columns)}")
    print("\n  sample row:")
    print(df.head(1).to_string(index=False))


def main() -> None:
    client = ErcotClient()

    # One week is enough for horizon and cadence — they're structural and repeat
    # every run — and keeps the pull cheap.
    week_start, week_end = "2026-06-01T00:00:00", "2026-06-08T00:00:00"

    # Gate B uses the full overlap between the RUC archive and NP4-191 mu, not a
    # convenient week: a gate that can kill the arm gets the best window available.
    overlap_start, overlap_end = "2026-05-01T00:00:00", "2026-07-01T00:00:00"

    leg0_discovery(client)
    legA_depth(client)
    legA2_dam_close(client, week_start, week_end)
    legB_namespace(client, overlap_start, overlap_end)
    legC_cadence(client, week_start, week_end)
    dump_schema(client, week_start, week_end)


if __name__ == "__main__":
    main()
