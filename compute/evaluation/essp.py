"""Independent daily validation of a served SF matrix against ERCOT ESSP labels."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _signature_groups(SF: pd.DataFrame) -> dict[bytes, frozenset[str]]:
    """Exact float32 SF signatures mapped to their settlement-point members."""
    groups: dict[bytes, set[str]] = {}
    for sp in SF.columns:
        values = np.ascontiguousarray(SF[sp].to_numpy(dtype=np.float32))
        groups.setdefault(values.tobytes(), set()).add(str(sp))
    return {signature: frozenset(members) for signature, members in groups.items()}


def agreement(SF: pd.DataFrame, essp: pd.DataFrame) -> dict[str, float | None]:
    """Daily group-hour precision/recall for exact SF signatures and ESSP labels.

    ESSP membership is hourly, so the score pools group-hours. A group participates
    only when all its members are visible on the other side; incomplete ESSP data
    must produce less evidence, not a fabricated split or match.
    """
    required = {"interval_ts", "settlement_point", "group_index"}
    if SF.empty or essp.empty or not required.issubset(essp.columns):
        return {"essp_precision": None, "essp_recall": None}

    signatures = _signature_groups(SF)
    signature_by_sp = {
        sp: signature for signature, members in signatures.items() for sp in members
    }
    sf_points = set(signature_by_sp)
    precision_n = precision_d = recall_n = recall_d = 0
    data = essp.copy()
    data["interval_ts"] = pd.to_datetime(data["interval_ts"], utc=True)

    for _, hourly in data.groupby("interval_ts"):
        essp_by_group = {
            int(group): frozenset(points.astype(str))
            for group, points in hourly.groupby("group_index")["settlement_point"]
        }
        essp_group_by_sp = {
            sp: group for group, members in essp_by_group.items() for sp in members
        }
        observed = set(essp_group_by_sp)

        for members in signatures.values():
            if len(members) < 2 or not members <= observed:
                continue
            precision_d += 1
            precision_n += len({essp_group_by_sp[sp] for sp in members}) == 1

        for members in essp_by_group.values():
            if len(members) < 2 or not members <= sf_points:
                continue
            recall_d += 1
            recall_n += len({signature_by_sp[sp] for sp in members}) == 1

    return {
        "essp_precision": precision_n / precision_d if precision_d else None,
        "essp_recall": recall_n / recall_d if recall_d else None,
    }


def load_final_essp(conn, D) -> pd.DataFrame:
    """The post-DAM ESSP labels for UTC delivery day ``D``."""
    D = pd.Timestamp(D)
    D = D.tz_localize("UTC") if D.tzinfo is None else D.tz_convert("UTC")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT interval_ts, settlement_point, group_index
            FROM ercot_essp
            WHERE interval_ts >= %s AND interval_ts < %s AND NOT is_study
            ORDER BY interval_ts, settlement_point
            """,
            (D, D + pd.Timedelta(days=1)),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["interval_ts", "settlement_point", "group_index"])


def score_final_essp(conn, D, SF: pd.DataFrame) -> dict[str, float | None]:
    """Score an SF matrix against settled ESSP labels available at grading time."""
    return agreement(SF, load_final_essp(conn, D))
