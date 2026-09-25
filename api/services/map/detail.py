"""Day-aware Map click-detail response assembly."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal

import pandas as pd
from psycopg.rows import dict_row

from compute.projection.codecs import node_contributions
from compute.sf_map.model.fit import SF_ABS_CAP
from api.db import get_pool
from api.schemas.map import ConstraintReach, ExposuresResponse, ReachSp, SpExposure
from api.services.sf_artifacts import coerce_utc, load_daily_artifact
from . import common

Coordinates = Callable[[], dict[str, tuple[float, float]]]
Metadata = Callable[[], dict[str, tuple[str | None, str | None]]]


def _absent_sp_reason(cur, run_id: str, day, sp: str) -> str:
    """Distinguish an out-of-service point from one omitted by the fit."""
    cur.execute(
        "SELECT count(*) FILTER (WHERE settlement_point = %s) AS sp_rows, count(*) AS day_rows FROM forecast_nodal WHERE run_id = %s AND delivery_date = %s",
        (sp, run_id, day),
    )
    row = cur.fetchone() or {}
    return (
        "sp_not_in_service"
        if row.get("day_rows") and not row.get("sp_rows")
        else "sp_not_in_fit"
    )


def exposures(
    sp: str,
    k: int,
    t: datetime | None,
    rank: Literal["contribution", "sf"],
    *,
    coordinates: Coordinates,
    metadata: Metadata,
) -> ExposuresResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, day, artifact = common.click_artifact(cur, t)
        if artifact is None:
            return ExposuresResponse(
                sp=sp,
                run_id=run_id,
                window_start=t,
                window_end=t,
                k=k,
                rank=rank,
                available=False,
                unavailable_reason="artifact_missing",
                exposures=[],
            )
        window_start, window_end = common.artifact_window(artifact)
        if not common.interval_in_artifact(artifact, t):
            return ExposuresResponse(
                sp=sp,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
                k=k,
                rank=rank,
                available=False,
                unavailable_reason="interval_not_in_artifact",
                exposures=[],
            )
        if sp not in artifact.SF.columns:
            # An empty exposure list means "in the fit, bound nothing"; preserve
            # the distinct unavailable reason for points absent from this day.
            return ExposuresResponse(
                sp=sp,
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
                k=k,
                rank=rank,
                available=False,
                unavailable_reason=_absent_sp_reason(cur, run_id, day, sp),
                exposures=[],
            )
        column = artifact.SF[sp]
        # Stable, unsigned headline across both ranking modes and any k.
        node_max = float(column.abs().max())
        node_gross_total = None
        if rank == "contribution":
            mu = common.hour_mu(artifact, t).reindex(artifact.SF.index).fillna(0.0)
            # Shared with /analysis/node to keep the two decompositions aligned.
            contributions = node_contributions(artifact, sp, mu)
            # Quiet constraints are not drivers and should not merely sort last.
            contributions = contributions[contributions != 0.0]
            # Gross magnitude is cancellation-safe for a bounded UI share.
            node_gross_total = float(contributions.abs().sum())
            ordered = contributions.abs().sort_values(ascending=False).index[:k]
        else:
            mu = contributions = None
            ordered = column.abs().sort_values(ascending=False).index[:k]
        geo = common.geo_metadata(cur, [str(key) for key in ordered])
        rows = [
            SpExposure(
                constraint_key=str(key),
                ctype=(geo.get(str(key)) or {}).get("ctype"),
                sf=float(column.loc[key]),
                sf_clipped=abs(float(column.loc[key])) >= SF_ABS_CAP,
                mu=None if mu is None else float(mu.loc[key]),
                contribution=(
                    None if contributions is None else float(contributions.loc[key])
                ),
                max_abs_sf=float(artifact.SF.loc[key].abs().max()),
                binding_hours=int((artifact.E_mu[key].abs() > 0).sum()),
            )
            for key in ordered
        ]
    return ExposuresResponse(
        sp=sp,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        k=k,
        rank=rank,
        node_max_abs_sf=node_max,
        node_gross_total=node_gross_total,
        exposures=rows,
    )


def reach(
    constraint: str,
    k: int,
    t: datetime | None,
    full: bool,
    min_frac: float,
    abs_floor: float,
    *,
    coordinates: Coordinates,
    metadata: Metadata,
) -> ConstraintReach:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, day, artifact = common.click_artifact(cur, t)
        basis = "artifact"
        if artifact is None:
            # Fall back only for whole-day absence: a missing constraint in a
            # present artifact means it did not bind that day, not stale reach.
            fallback_day = common.nearest_past_artifact_day(cur, run_id, day)
            if fallback_day is not None:
                artifact, day, basis = (
                    load_daily_artifact(cur, run_id, fallback_day),
                    fallback_day,
                    "nearest_past",
                )
            if artifact is None:
                return ConstraintReach(
                    constraint_key=constraint,
                    run_id=run_id,
                    window_start=t,
                    window_end=t,
                    k=k,
                    available=False,
                    unavailable_reason="artifact_missing",
                    sps=[],
                )
        window_start, window_end = common.artifact_window(artifact)
        geo = common.geo_metadata(cur, [constraint]).get(constraint) or {}
        # The fallback serves structural reach, so only its own artifact bypasses
        # the requested-interval gate.
        unavailable = (
            "interval_not_in_artifact"
            if basis == "artifact" and not common.interval_in_artifact(artifact, t)
            else (
                "constraint_not_in_artifact"
                if constraint not in artifact.SF.index
                else None
            )
        )
        if unavailable:
            return ConstraintReach(
                constraint_key=constraint,
                ctype=geo.get("ctype"),
                run_id=run_id,
                window_start=window_start,
                window_end=window_end,
                k=k,
                n_rail=geo.get("n_rail"),
                peak_offrail=geo.get("peak_offrail"),
                available=False,
                unavailable_reason=unavailable,
                sps=[],
            )
        row = artifact.SF.loc[constraint]
        # Geo supplies shape fields; these daily magnitudes must come from the
        # selected artifact so they match /matrix/frame.
        max_abs_sf = float(row.abs().max())
        binding_hours = int((artifact.E_mu[constraint].abs() > 0).sum())
        shadow_price = (
            float(artifact.E_mu.loc[pd.Timestamp(coerce_utc(t)), constraint])
            if t is not None and basis == "artifact"
            else None
        )
        dam_mu = None
        if t is not None and basis == "artifact":
            cur.execute(
                "SELECT DISTINCT ON (interval_ts, constraint_name, contingency_name) shadow_price FROM ercot_dam_shadow_prices WHERE interval_ts = %s AND btrim(constraint_name) || '|' || btrim(contingency_name) = %s ORDER BY interval_ts, constraint_name, contingency_name, dst_flag ASC",
                (pd.Timestamp(coerce_utc(t)).to_pydatetime(), constraint),
            )
            dam_row = cur.fetchone()
            if dam_row is not None and dam_row["shadow_price"] is not None:
                dam_mu = float(dam_row["shadow_price"])
        daily_mass = artifact.E_mu.abs().sum(axis=0)
        daily_rank = (
            int(
                daily_mass.sort_values(ascending=False, kind="stable").index.get_loc(
                    constraint
                )
            )
            + 1
        )
        # Relative and absolute floors prevent weak fits from padding the reach
        # with a long noise tail.
        floor = max(min_frac * max_abs_sf if max_abs_sf else 0.0, abs_floor)
        ranked = row[row.abs() >= floor].sort_values(
            key=lambda values: values.abs(), ascending=False
        )
        truncated = not full and len(ranked) > k
        if not full:
            ranked = ranked.iloc[:k]
        coords, metadata_rows = coordinates(), metadata()
        sps = [
            ReachSp(
                settlement_point=str(name),
                sf=float(sf),
                lat=coords.get(str(name), (None, None))[0],
                lon=coords.get(str(name), (None, None))[1],
                settlement_point_type=metadata_rows.get(str(name), (None, None))[0],
                load_zone=metadata_rows.get(str(name), (None, None))[1],
            )
            for name, sf in ranked.items()
        ]
    return ConstraintReach(
        constraint_key=constraint,
        ctype=geo.get("ctype"),
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        k=k,
        max_abs_sf=max_abs_sf,
        n_rail=geo.get("n_rail"),
        peak_offrail=geo.get("peak_offrail"),
        binding_hours=binding_hours,
        shadow_price=shadow_price,
        dam_mu=dam_mu,
        forecast_error=(
            None if shadow_price is None or dam_mu is None else shadow_price - dam_mu
        ),
        daily_mu_rank=daily_rank,
        daily_mu_sum=float(daily_mass.loc[constraint]),
        negative_members=int((row < 0.0).sum()),
        positive_members=int((row > 0.0).sum()),
        available=bool(sps),
        basis=basis,
        truncated=truncated,
        sps=sps,
    )
