"""HTTP routes for the implied shift-factor map."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query

from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.map import (
    ConstraintReach,
    ExposuresResponse,
    MapMeta,
    MapOverview,
    MapSummaryResponse,
    RankedConstraints,
)
from api.services.map import aggregate, detail, summary
from api.services.settlement_points import coordinates as settlement_point_coordinates
from api.services.settlement_points import metadata as settlement_point_metadata

router = APIRouter(prefix="/map")

# Explicit test seams; production ownership remains in settlement_points.
_SP_COORDS: dict[str, tuple[float, float]] | None = None
_SP_METADATA: dict[str, tuple[str | None, str | None]] | None = None


def _sp_coords() -> dict[str, tuple[float, float]]:
    return _SP_COORDS if _SP_COORDS is not None else settlement_point_coordinates()


def _sp_metadata() -> dict[str, tuple[str | None, str | None]]:
    return _SP_METADATA if _SP_METADATA is not None else settlement_point_metadata()


@router.get("/meta", response_model=MapMeta, summary="The refit the map is serving")
def get_map_meta() -> MapMeta:
    return aggregate.meta()


@router.get(
    "/exposures",
    response_model=ExposuresResponse,
    summary="Top-k constraints driving a node (node-explorer click)",
)
def get_map_exposures(
    sp: str = Query(..., description="Settlement point to explain"),
    k: int = Query(15, ge=1, le=500, description="Number of top constraints"),
    t: datetime | None = Query(
        None,
        description="Delivery interval in ISO-8601 UTC. The SF served is the CT delivery day's artifact, so this matches /matrix/frame at the same node and interval. Omit for the run's latest built day.",
    ),
    rank: Literal["contribution", "sf"] = Query(
        "contribution",
        description="Ordering basis. 'contribution' ranks what actually drove the node at t, by |-SF x mu|, dropping constraints that did not bind. 'sf' ranks structural exposure by |SF| over every constraint in the day's fit, including quiet ones.",
    ),
) -> ExposuresResponse:
    """Rank a node's constraints by what drove it, or by structural exposure.

    """
    return detail.exposures(
        sp, k, t, rank, coordinates=_sp_coords, metadata=_sp_metadata
    )


@router.get(
    "/reach",
    response_model=ConstraintReach,
    summary="Top-k nodes a constraint drives (constraint click)",
)
def get_map_reach(
    constraint: str = Query(..., description="Constraint key to trace"),
    k: int = Query(15, ge=1, le=500, description="Number of top nodes"),
    t: datetime | None = Query(
        None,
        description="Delivery interval in ISO-8601 UTC. The SF served is the CT delivery day's artifact, so this matches /matrix/frame at the same constraint and interval. Omit for the run's latest built day.",
    ),
    full: bool = Query(
        False,
        description="Ignore k and return every node above min_frac",
    ),
    min_frac: float = Query(
        0.05,
        ge=0.0,
        le=1.0,
        description="Noise floor: drop nodes whose |SF| is below this fraction of the constraint's peak |SF|",
    ),
    abs_floor: float = Query(
        0.0,
        ge=0.0,
        le=1.0,
        description="Absolute |SF| floor, combined with min_frac as max(min_frac*peak, abs_floor).",
    ),
) -> ConstraintReach:
    return detail.reach(
        constraint,
        k,
        t,
        full,
        min_frac,
        abs_floor,
        coordinates=_sp_coords,
        metadata=_sp_metadata,
    )


@router.get(
    "/overview",
    response_model=MapOverview,
    summary="De-piled overview: top-n constraints at their |SF|² cores",
)
def get_map_overview(
    n: int = Query(
        70, ge=1, le=500, description="Number of top constraints by binding hours."
    ),
    k: int = Query(
        16,
        ge=1,
        le=100,
        description="Top signed nodes per constraint (the mark's field).",
    ),
    min_frac: float = Query(
        0.15,
        ge=0.0,
        le=1.0,
        description="Noise floor: drop a constraint's nodes whose |SF| is below this fraction of its peak |SF|, so a weakly-fit constraint's mark is its real nodes, not the noise floor",
    ),
) -> MapOverview:
    return aggregate.overview(
        n, k, min_frac, coordinates=_sp_coords, metadata=_sp_metadata
    )


@router.get(
    "/constraints/ranked",
    response_model=RankedConstraints,
    summary="Per-day ranked constraints by congestion contribution",
)
def get_map_constraints_ranked(
    day: date | None = Query(
        None,
        description="Delivery date to rank. Omit for the forecast run's latest day with a built SF+μ artifact.",
    ),
    basis: str = Query(
        "predicted",
        pattern="^(predicted|realized)$",
        description="μ series: predicted (the day's fitted E_mu) or realized (that day's published DAM shadow prices). SF structure is shared.",
    ),
    run_id: str | None = Depends(_server_selected_run),
    k: int = Query(30, ge=1, le=200, description="Top-k constraints to return."),
    min_frac: float = Query(
        0.05,
        ge=0.0,
        le=1.0,
        description="Noise floor: a node counts toward a constraint's members / lobes only if its |SF| is at least this fraction of the constraint's peak |SF| (mirrors /map/reach).",
    ),
) -> RankedConstraints:
    return aggregate.ranked(day, basis, run_id, k, min_frac, coordinates=_sp_coords)


@router.get(
    "/summary",
    response_model=MapSummaryResponse,
    summary="One bundled payload for the Map workspace summary (0137)",
)
def get_map_summary() -> MapSummaryResponse:
    """Compose the Map workspace's four load-time requests behind one call.

    """
    return summary.build(
        overview=lambda: aggregate.overview(
            70, 6, 0.15, coordinates=_sp_coords, metadata=_sp_metadata
        ),
        meta=aggregate.meta,
    )
