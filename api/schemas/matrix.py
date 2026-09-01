"""Schemas served by the causal matrix route."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

# ---- /matrix/frame -------------------------------------------------------


class MatrixRow(BaseModel):
    """One stable constraint row in a delivery day's bounded SF rectangle."""

    constraint_key: str
    constraint_name: str
    contingency_name: str | None = None
    constraint_type: str | None = None
    forecast_mu: float
    ercot_dam_mu: float | None = None
    daily_rank: int
    binding_hours: int
    max_abs_sf: float


class MatrixColumn(BaseModel):
    """One stable settlement-point column in a bounded SF rectangle."""

    settlement_point: str
    settlement_point_type: str | None = None
    load_zone: str | None = None
    max_abs_sf: float


class MatrixSfValues(BaseModel):
    """Row-major recovered implied-SF values aligned to ``rows`` and ``columns``.

    A cell whose ``|value|`` equals the frame's ``sf_abs_cap`` was pinned there
    by the ridge fit's clip and is a bound rather than a measurement (0145). No
    parallel mask is sent: the clip is exact, so ``abs(v) >= sf_abs_cap`` is the
    same test the server would apply, at a fraction of the payload.
    """

    row_count: int
    column_count: int
    values: list[float]


class MatrixFrame(BaseModel):
    """A causal, immutable-artifact-backed Matrix frame for one delivery hour."""

    available: bool
    unavailable_reason: str | None = None
    run_id: str
    delivery_date: date
    interval_ts: datetime
    fit_window_start: datetime | None = None
    fit_window_end: datetime | None = None
    # Which axis got the "primary list" (ranked + searched + bounded) treatment.
    # The wire shape is unchanged — ``rows`` are always constraints and
    # ``columns`` always settlement points — but the client reads this to decide
    # the visual orientation (``nodes`` renders nodes as rows by transposing).
    orientation: Literal["constraints", "nodes"] = "constraints"
    dam_status: Literal["pending", "partial", "available"] = "pending"
    row_ordering: str = "daily_abs_forecast_contribution_desc_then_constraint_key"
    column_ordering: str = "max_abs_sf_desc_then_settlement_point"
    # The bounded rectangle is intentionally not the whole artifact.  Clients
    # need this distinction before describing any visible-only sum.
    rows_truncated: bool = False
    columns_truncated: bool = False
    # Counts describe the artifact universe, not a congestion total.  A client
    # can therefore say "30 of 143 constraints" without implying that the
    # visible rows account for all nodal congestion.
    total_constraint_count: int = 0
    total_settlement_point_count: int = 0
    # Day-wide extrema keep the color legend stable when a client filters the
    # bounded view. Contribution uses the forecast-day range for both sources
    # so their colors remain directly comparable.
    sf_day_max_abs: float = 0.0
    contribution_day_max_abs: float = 0.0
    # The fit's |SF| clip. Cells sitting exactly here were pinned by the ridge
    # rather than measured, and the client marks them; sent so the threshold has
    # one source (compute.sf_map.model.fit.SF_ABS_CAP) instead of a hardcoded 1.0 on both
    # sides of the wire.
    sf_abs_cap: float = 0.0
    rows: list[MatrixRow] = []
    columns: list[MatrixColumn] = []
    sf: MatrixSfValues
