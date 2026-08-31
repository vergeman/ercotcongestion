"""Map aggregate, metadata, and constraint-ranking services."""

from __future__ import annotations

from datetime import date
from typing import Callable

import pandas as pd
from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.map import (
    MapMeta,
    MapOverview,
    OverviewConstraint,
    RankedConstraint,
    RankedConstraints,
    ReachSp,
)
from api.services.constraint_keys import normalize_constraint_key
from api.services.sf_artifacts import load_daily_artifact
from . import common

Coordinates = Callable[[], dict[str, tuple[float, float]]]
Metadata = Callable[[], dict[str, tuple[str | None, str | None]]]


def meta() -> MapMeta:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = common.resolve(cur)
        return MapMeta(**common.meta_row(cur, run_id, window_start))


def overview(
    n: int, k: int, min_frac: float, *, coordinates: Coordinates, metadata: Metadata
) -> MapOverview:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = common.resolve(cur)
        meta_row = common.meta_row(cur, run_id, window_start)
        # NULLS LAST stops unlocatable constraints crowding out the overview.
        cur.execute(
            "SELECT constraint_key, ctype, binding_hours, max_abs_sf FROM constraint_geo WHERE run_id = %s AND window_start = %s ORDER BY binding_hours DESC NULLS LAST LIMIT %s",
            (run_id, window_start, n),
        )
        rows = cur.fetchall()
        keys = [row["constraint_key"] for row in rows]
        by_key: dict[str, list[ReachSp]] = {key: [] for key in keys}
        if keys:
            # One indexed slice; the per-constraint floor depends on each row's
            # peak, so it is applied while building the running top-k buckets.
            cur.execute(
                "SELECT constraint_key, settlement_point, sf FROM implied_shift_factors WHERE run_id = %s AND window_start = %s AND constraint_key = ANY(%s) ORDER BY constraint_key, abs(sf) DESC",
                (run_id, window_start, keys),
            )
            coords, metadata_rows = coordinates(), metadata()
            floors = {
                row["constraint_key"]: (
                    min_frac * row["max_abs_sf"] if row["max_abs_sf"] else 0.0
                )
                for row in rows
            }
            for row in cur.fetchall():
                bucket = by_key[row["constraint_key"]]
                if len(bucket) >= k or abs(row["sf"]) < floors[row["constraint_key"]]:
                    continue
                lat, lon = coords.get(row["settlement_point"], (None, None))
                point_type, load_zone = metadata_rows.get(
                    row["settlement_point"], (None, None)
                )
                bucket.append(
                    ReachSp(
                        settlement_point=row["settlement_point"],
                        sf=row["sf"],
                        lat=lat,
                        lon=lon,
                        settlement_point_type=point_type,
                        load_zone=load_zone,
                    )
                )
        constraints = [
            OverviewConstraint(
                constraint_key=row["constraint_key"],
                ctype=row["ctype"],
                binding_hours=row["binding_hours"],
                max_abs_sf=row["max_abs_sf"],
                nodes=by_key[row["constraint_key"]],
            )
            for row in rows
        ]
    return MapOverview(
        run_id=run_id,
        window_start=meta_row["window_start"],
        window_end=meta_row["window_end"],
        n=n,
        k=k,
        sf_oos_r2=meta_row["sf_oos_r2"],
        sf_stability=meta_row["sf_stability"],
        constraints=constraints,
    )


def _realized_mu_summary(cur, lo, hi) -> dict[str, tuple[float, int]]:
    """Return (Σ|μ|, binding hours) over the artifact's own interval range."""
    cur.execute(
        "SELECT constraint_name, contingency_name, sum(abs(shadow_price)) AS mass, count(*) FILTER (WHERE abs(shadow_price) > 0) AS binding_hours FROM ercot_dam_shadow_prices WHERE interval_ts >= %s AND interval_ts <= %s AND shadow_price IS NOT NULL GROUP BY constraint_name, contingency_name",
        (lo, hi),
    )
    return {
        normalize_constraint_key(row["constraint_name"], row["contingency_name"]): (
            float(row["mass"]),
            int(row["binding_hours"]),
        )
        for row in cur.fetchall()
        if row["mass"] is not None
    }


def ranked(
    day: date | None,
    basis: str,
    run_id: str | None,
    k: int,
    min_frac: float,
    *,
    coordinates: Coordinates,
) -> RankedConstraints:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            run_id = common.forecast_run_id(cur)
        if day is None:
            day = common.latest_artifact_day(cur, run_id)
            if day is None:
                raise HTTPException(
                    status_code=503,
                    detail=f"no SF+μ artifact built for run_id={run_id}.",
                )
        art = load_daily_artifact(cur, run_id, day)
        if art is None:
            raise HTTPException(
                status_code=503,
                detail=f"no SF+μ artifact for run_id={run_id} on {day}.",
            )
        keys = art.SF.index
        if basis == "realized":
            lo, hi = art.E_mu.index.min(), art.E_mu.index.max()
            summary = pd.DataFrame.from_dict(
                _realized_mu_summary(cur, lo.to_pydatetime(), hi.to_pydatetime()),
                orient="index",
                columns=["mu_mass", "binding_hours"],
            )
            mu_mass = (
                summary.get("mu_mass", pd.Series(dtype=float)).reindex(keys).fillna(0.0)
            )
            binding_hours = (
                summary.get("binding_hours", pd.Series(dtype=float))
                .reindex(keys)
                .fillna(0)
                .astype(int)
            )
        else:
            abs_mu = art.E_mu.abs().reindex(columns=keys, fill_value=0.0)
            mu_mass, binding_hours = abs_mu.sum(axis=0), (abs_mu > 0.0).sum(
                axis=0
            ).astype(int)
        # contribution is the day-total magnitude of the −E_mu·SF nodal
        # decomposition, ranked by each constraint's structural reach.
        reach = art.SF.abs().sum(axis=1)
        contribution = (mu_mass * reach).astype(float)
        ranking = contribution[contribution > 0.0].sort_values(ascending=False)
        top_keys = list(ranking.index[:k])
        geo: dict[str, dict] = {}
        if top_keys:
            # Overlay marks and ranked rows share this structural type source.
            map_run, map_window = common.resolve(cur)
            cur.execute(
                "SELECT constraint_key, ctype FROM constraint_geo WHERE run_id = %s AND window_start = %s AND constraint_key = ANY(%s)",
                (map_run, map_window, top_keys),
            )
            geo = {row["constraint_key"]: row for row in cur.fetchall()}
    coords = coordinates()
    rows = []
    for rank, key in enumerate(top_keys, start=1):
        sf_row = art.SF.loc[key]
        floor = min_frac * float(sf_row.abs().max())
        members = [
            (float(sf), coords.get(str(point)))
            for point, sf in sf_row.items()
            if abs(float(sf)) >= floor
            and sf != 0.0
            and coords.get(str(point)) is not None
        ]
        imports = sum(sf < 0 for sf, _ in members)
        exports = sum(sf > 0 for sf, _ in members)
        rows.append(
            RankedConstraint(
                constraint_id=key,
                rank=rank,
                congestion_contribution=float(ranking.loc[key]),
                mu_mass=float(mu_mass.loc[key]),
                binding_hours=int(binding_hours.loc[key]),
                reach=float(reach.loc[key]),
                n_members=len(members),
                ctype=geo.get(key, {}).get("ctype"),
                n_import=imports,
                n_export=exports,
            )
        )
    return RankedConstraints(
        run_id=run_id,
        delivery_date=day,
        basis=basis,
        k=k,
        n_ranked=int((contribution > 0.0).sum()),
        constraints=rows,
    )
