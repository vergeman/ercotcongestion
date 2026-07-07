"""DB readers for the implied-binding-proximity fit.

Two Postgres reads, one per side of the identity ``C = −M · SFᵀ``:

* ``load_shadow_prices`` — pivot ``ercot_dam_shadow_prices`` (NP4-191-CD) to
  ``(hours × key)`` where ``key = constraint_name + '|' + contingency_name``.
* ``load_congestion_panel`` — SP-level congestion from ``ercot_dam_spp`` under
  a chosen reference-price method. Default ``system_lambda`` (NP4-523-CD): the
  distributed-slack convention so implied SFs are directly comparable to the
  model-side distributed-slack PTDFs.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd


# ---------------------------------------------------------------- shadow prices

def load_shadow_prices(
    conn,
    start: date | datetime,
    end: date | datetime,
) -> pd.DataFrame:
    """Pivot NP4-191-CD to ``(hours × key)`` of shadow prices.

    ``start`` inclusive, ``end`` exclusive. ``key`` collides only if the same
    ``(constraint_name, contingency_name)`` shows up twice at the same
    ``interval_ts`` — surfaced as an AssertionError rather than silently
    summed the way the prototype did, because that would mask duplicate ingest.

    Non-binding hours arrive as zeros (missing rows filled after pivot); the
    NP4-191 feed only publishes binding rows, so absence == μ=0 by construction.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT interval_ts, constraint_name, contingency_name, shadow_price
            FROM ercot_dam_shadow_prices
            WHERE interval_ts >= %s AND interval_ts < %s
              AND dst_flag = FALSE
              AND shadow_price IS NOT NULL
            """,
            (start, end),
        )
        rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["ts", "constraint_name", "contingency_name", "mu"])
    df["key"] = (
        df["constraint_name"].astype(str).str.strip()
        + "|"
        + df["contingency_name"].astype(str).str.strip()
    )

    dupe_mask = df.duplicated(subset=["ts", "key"], keep=False)
    if dupe_mask.any():
        sample = df.loc[dupe_mask, ["ts", "key"]].head(5).to_dict("records")
        raise AssertionError(
            f"ercot_dam_shadow_prices has {int(dupe_mask.sum())} duplicate "
            f"(interval_ts, key) rows; sample: {sample}"
        )

    M = df.pivot(index="ts", columns="key", values="mu")
    M = M.fillna(0.0).sort_index()
    M.columns.name = None
    return M


# ---------------------------------------------------------------- congestion panel

def load_congestion_panel(
    conn,
    start: date | datetime,
    end: date | datetime,
    ref_method: str = "system_lambda",
) -> pd.DataFrame:
    """Build the SP-level congestion panel over ``[start, end)``.

    Only ``system_lambda`` is supported: per hour,
    ``congestion[sp] = dam_spp[sp] − system_lambda``. This matches the
    ``system_lambda`` column that ``compute.matrix`` writes to the ERCOT
    congestion npz. Other ref methods (hub_avg, load_weighted, …) are computed
    against per-hour hub / load / dispatch state that is not needed here — the
    fit assumes the distributed-slack convention.

    Returns a DataFrame indexed by ``interval_ts`` with SP columns.
    """
    if ref_method != "system_lambda":
        raise ValueError(
            f"ref_method={ref_method!r} not supported by implied_binding_proximity; "
            "only 'system_lambda' (distributed-slack) is compatible with the "
            "implied-SF fit."
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
            FROM dam_system_lambda
            WHERE interval_ts >= %s AND interval_ts < %s
            ORDER BY interval_ts, dst_flag ASC
            """,
            (start, end),
        )
        lam_rows = cur.fetchall()

    if not lam_rows:
        return pd.DataFrame()
    lam = pd.Series({ts: float(v) for ts, v in lam_rows}, name="system_lambda")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (interval_ts, settlement_point)
                   interval_ts, settlement_point, dam_spp
            FROM ercot_dam_spp
            WHERE interval_ts >= %s AND interval_ts < %s
            ORDER BY interval_ts, settlement_point, dst_flag ASC
            """,
            (start, end),
        )
        spp_rows = cur.fetchall()

    if not spp_rows:
        return pd.DataFrame()

    spp = pd.DataFrame(spp_rows, columns=["ts", "settlement_point", "dam_spp"])
    C = spp.pivot(index="ts", columns="settlement_point", values="dam_spp").sort_index()
    C.columns.name = None

    common = C.index.intersection(lam.index)
    C = C.loc[common]
    C = C.sub(lam.loc[common], axis=0)
    return C
