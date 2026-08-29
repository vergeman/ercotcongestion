"""DB readers for the implied-binding-proximity fit.

Two Postgres reads, one per side of the identity ``C = −M · SFᵀ``:

* ``load_shadow_prices``: pivot ``ercot_dam_shadow_prices`` (NP4-191-CD) to
  ``(hours × key)`` where ``key = constraint_name + '|' + contingency_name``.

* ``load_congestion_panel``: SP-level congestion from ``ercot_dam_spp`` under a
  chosen reference-price method. Default ``system_lambda``

"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def panel_bounds(
    conn,
    start: date | datetime,
    end: date | datetime,
) -> tuple[datetime, datetime] | None:
    """First/last hour in the same union clock used by the two SF panels.

    The map runner needs these bounds to construct the stable refit grid before
    it loads any dense pivot.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH panel_hours AS (
                SELECT interval_ts
                FROM ercot_dam_shadow_prices
                WHERE interval_ts >= %s AND interval_ts < %s
                  AND dst_flag = FALSE
                  AND shadow_price IS NOT NULL
                GROUP BY interval_ts
                UNION
                (
                    SELECT interval_ts
                    FROM dam_system_lambda
                    WHERE interval_ts >= %s AND interval_ts < %s
                    INTERSECT
                    SELECT interval_ts
                    FROM ercot_dam_spp
                    WHERE interval_ts >= %s AND interval_ts < %s
                )
            )
            SELECT min(interval_ts), max(interval_ts) FROM panel_hours
            """,
            (start, end, start, end, start, end),
        )
        lo, hi = cur.fetchone()
    return (lo, hi) if lo is not None and hi is not None else None


def load_shadow_prices(
    conn,
    start: date | datetime,
    end: date | datetime,
) -> pd.DataFrame:
    """Pivot NP4-191-CD to ``(hours × key)`` of shadow prices.

    [start, end): ``key`` collides only if the same ``(constraint_name,
    contingency_name)`` shows up twice at the same ``interval_ts`` — surfaced
    as an AssertionError.

    Non-binding hours arrive as zeros (missing rows filled after pivot)

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


# A UTC delivery window always catches the ~5h tail (00:00–04:00Z) of the prior CT
# op-day's shadow report, so a non-empty window is not proof the day's own DAM has
# landed. Require the latest interval to reach ≥12h in — well past the tail (~4h),
# well below a normal day's afternoon-peak max (~23h).
DAM_SHADOW_MIN_COVER_HOURS = 12


def dam_shadow_covers_window(ts_max, lo) -> bool:
    """True when DAM shadow prices span the delivery window, not just the ~5h
    prior-op-day tail. ``ts_max`` is the latest shadow-price ``interval_ts`` in the
    window (``None`` when there are none); ``lo`` is the window start. See
    ``DAM_SHADOW_MIN_COVER_HOURS``.
    """
    if ts_max is None or pd.isna(ts_max):
        return False
    return pd.Timestamp(ts_max) >= pd.Timestamp(lo) + pd.Timedelta(
        hours=DAM_SHADOW_MIN_COVER_HOURS)


def load_congestion_panel(
    conn,
    start: date | datetime,
    end: date | datetime,
    ref_method: str = "system_lambda",
) -> pd.DataFrame:
    """Build the SP-level congestion panel over ``[start, end)``.

    Only ``system_lambda`` is supported: per hour,
    ``congestion[sp] = dam_spp[sp] − system_lambda``.

    This matches the ``system_lambda`` column that ``compute.matrix`` writes to
    the ERCOT congestion npz.

    Other ref methods (hub_avg, load_weighted) are computed against per-hour
    hub / load / dispatch state that is not needed here — the fit assumes the
    distributed-slack convention.

    Returns a DataFrame indexed by ``interval_ts`` with SP columns.

    """
    if ref_method != "system_lambda":
        raise ValueError(
            f"ref_method={ref_method!r} "
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
