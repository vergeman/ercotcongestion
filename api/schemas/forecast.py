"""Schemas served by forecast and realized range routes."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

# ---- /ercot_range --------------------------------------------------------

class ErcotRangeEntry(BaseModel):
    interval_ts: datetime
    # One DAM system reference price per interval. It is sent alongside the
    # compact SPP/congestion arrays so timeline-level consumers do not need to
    # reconstruct it from rounded nodal values.
    system_lambda: float | None
    congestion: list[float | None]
    spp: list[float | None]


class ErcotRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    sp_ids: list[str]
    entries: list[ErcotRangeEntry]


# ---- /forecast_range -----------------------------------------------------
#
# Per-hour, per-SP deterministic forecast congestion over a window — the
# prediction counterpart to ``/ercot_range``, read from ``forecast_nodal`` at
# the current ``forecast_current[ercot]`` run. Same range shape (start / end /
# count / per-hour ``entries``) so the left ("prediction") map pane aligns to
# the same scrubber the realized right pane does, hour for hour, instead of
# both rendering one realized quantity.
#
# Each SP carries deterministic congestion, and each hour carries the DAM
# ``system_lambda`` (NP4-523-CD) so predicted LMP = forecast_congestion +
# system_λ. This is the same reference the market side subtracts, so the
# LMP-basis comparison collapses to the congestion-basis one. ``run_id`` labels
# which refit is serving; the served day is the cursor hour's date.


class ForecastSpState(BaseModel):
    """One SP's forecast congestion at one hour — a ``forecast_nodal`` row.

    ``forecast_congestion`` is ``−(E_mu · SF)``. It is nullable so an invalid
    persisted value remains explicit rather than dropping the settlement point.
    """

    sp_id: str
    forecast_congestion: float | None = None


class ForecastRangeEntry(BaseModel):
    """All SPs' forecast congestion at one interval, plus that hour's system-λ.

    ``system_lambda`` is the DAM system-λ at ``interval_ts`` when settled; on
    an unsettled hour it falls back to the most recent settled day's λ at the
    same Central hour, and ``None`` only when no settled day exists yet to
    persist from.

    ``lambda_source`` says which: ``"settled"`` or ``"persisted"``. Add
    ``system_lambda`` to each SP's congestion for the predicted LMP palette.

    """

    interval_ts: datetime
    system_lambda: float | None = None
    lambda_source: Literal["settled", "persisted"] | None = None
    sps: list[ForecastSpState]


class ForecastRangeResponse(BaseModel):
    """Per-hour forecast congestion across a window for the current forecast run.

    ``run_id`` (model version) labels which refit is serving; ``entries`` are
    the forecast hours falling in ``[start, end]`` for that run, so a window
    covering the served delivery day renders the forecast aligned to the
    realized ranges.

    ``horizons`` is the per-delivery-day provenance map (``"YYYY-MM-DD" ->
    1|2``, 0123): which horizon each served day came from — 1 = final/t+1, 2 =
    preview/t+2. Absent an explicit ``?horizon=``, the endpoint coalesces per
    day (prefer final, fall back to preview) into one continuous series; this
    map is how a client knows which days are still previews without changing
    the series shape.

    """

    start: datetime
    end: datetime
    run_id: str
    count: int
    entries: list[ForecastRangeEntry]
    horizons: dict[str, int] = {}
