"""Map aggregate, metadata, and constraint-ranking services."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
from typing import Callable

import pandas as pd
from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.map import (
    MapMeta,
    MapFitMetadata,
    MapOverview,
    OverviewConstraint,
    RankedConstraint,
    RankedConstraints,
    ReachSp,
)
from api.services.constraint_keys import normalize_constraint_key
from api.services.sf_artifacts import load_daily_artifact
from compute.projection.codecs import load_sf_window_artifact
from . import common

Coordinates = Callable[[], dict[str, tuple[float, float]]]
Metadata = Callable[[], dict[str, tuple[str | None, str | None]]]
_WINDOW_CACHE_BYTES = 32 * 1024 * 1024
_window_cache: OrderedDict[tuple[str, object], tuple[pd.DataFrame, int]] = OrderedDict()
_window_cache_size = 0


def _weekly_sf(cur, run_id: str, window_start) -> pd.DataFrame:
    """Decode a weekly artifact once per API process and map window."""
    global _window_cache_size
    key = (run_id, window_start)
    cached = _window_cache.pop(key, None)
    if cached is not None:
        _window_cache[key] = cached
        return cached[0]
    cur.execute("SELECT sf_npz FROM sf_window_artifact WHERE run_id = %s AND window_start = %s",
                (run_id, window_start))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail=f"SF artifact missing for {run_id} window {window_start}.")
    blob = row["sf_npz"] if isinstance(row, dict) else row[0]
    sf = load_sf_window_artifact(blob).SF
    size = int(sf.memory_usage(index=True, deep=True).sum())
    _window_cache[key] = (sf, size)
    _window_cache_size += size
    while _window_cache and _window_cache_size > _WINDOW_CACHE_BYTES:
        _, (_, removed) = _window_cache.popitem(last=False)
        _window_cache_size -= removed
    return sf


def meta() -> MapMeta:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = common.resolve(cur)
        return MapMeta(**common.meta_row(cur, run_id, window_start))


def fit_metadata(
    t: datetime | None = None, *, delivery_day: date | None = None
) -> MapFitMetadata:
    """Return diagnostics for the SF vintage behind the cursor's artifact."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        provenance = common.resolve_artifact_provenance(
            cur, t, delivery_day=delivery_day
        )
        if provenance.artifact is None or provenance.window_start is None:
            return MapFitMetadata(
                artifact_delivery_date=provenance.artifact_delivery_date,
                basis=provenance.basis if provenance.artifact is not None else None,
            )
        row = common.meta_row(cur, provenance.map_run_id, provenance.window_start)
        return MapFitMetadata(
            run_id=row["run_id"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            sf_oos_r2=row["sf_oos_r2"],
            coverage=row["coverage"],
            sf_stability=row["sf_stability"],
            artifact_delivery_date=provenance.artifact_delivery_date,
            basis=provenance.basis,
            available=True,
        )


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
            sf = _weekly_sf(cur, run_id, window_start)
            coords, metadata_rows = coordinates(), metadata()
            floors = {
                row["constraint_key"]: (
                    min_frac * row["max_abs_sf"] if row["max_abs_sf"] else 0.0
                )
                for row in rows
            }
            for constraint_key in keys:
                if constraint_key not in sf.index:
                    continue
                members = sf.loc[constraint_key].dropna().sort_values(
                    key=lambda values: values.abs(), ascending=False)
                for settlement_point, value in members.items():
                    if len(by_key[constraint_key]) >= k or abs(value) < floors[constraint_key]:
                        break
                    lat, lon = coords.get(settlement_point, (None, None))
                    point_type, load_zone = metadata_rows.get(settlement_point, (None, None))
                    by_key[constraint_key].append(ReachSp(
                        settlement_point=settlement_point, sf=value, lat=lat, lon=lon,
                        settlement_point_type=point_type, load_zone=load_zone,
                    ))
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
        negatives = sum(sf < 0 for sf, _ in members)
        positives = sum(sf > 0 for sf, _ in members)
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
                n_negative=negatives,
                n_positive=positives,
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
