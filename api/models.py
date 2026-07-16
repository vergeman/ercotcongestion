"""Response schemas for the API."""

from datetime import datetime

from pydantic import BaseModel


# ---- /api/ercot_state_range ---------------------------------------------
#
# Per-hour ERCOT settlement-point congestion, read from the active run's
# congestion_matrices.npz.

class ErcotSpState(BaseModel):
    sp_id: str
    congestion: float | None


class ErcotStateRangeEntry(BaseModel):
    interval_ts: datetime
    sps: list[ErcotSpState]


class ErcotStateRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ErcotStateRangeEntry]


# ---- /api/ercot_spp_range -----------------------------------------------
#
# Raw DAM SPP (NP4-190-CD) per settlement point, per hour. Feeds the LMP
# palette's right pane so LMP-vs-LMP comparison uses ERCOT's own published
# prices, not a derived (SPP − system_λ) quantity. Read directly from the
# ``ercot_dam_spp`` table rather than the run's congestion matrix — the
# matrix stores only the shifted congestion component, not the raw price.

class ErcotSpSpp(BaseModel):
    sp_id: str
    spp: float | None


class ErcotSppRangeEntry(BaseModel):
    interval_ts: datetime
    sps: list[ErcotSpSpp]


class ErcotSppRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ErcotSppRangeEntry]


# ---- /api/meta -----------------------------------------------------------

class MetaResponse(BaseModel):
    """What the API is currently serving. Read-only surface for debug UI.

    ``run_id``, ``ref``, ``algo``, ``k`` are derived from the served
    scorecard cell; ``promoted_at`` is the IBP DB pointer timestamp.
    Any field is ``None`` when the underlying artifact isn't in place —
    e.g. no cell has been promoted yet, or the DB pointer is unset.
    """
    run_id: str | None = None
    ref: str | None = None
    algo: str | None = None
    k: int | None = None
    promoted_at: datetime | None = None
