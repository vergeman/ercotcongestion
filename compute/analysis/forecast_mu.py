"""Read-time slices of the untruncated forecast-μ artifact.

The daily brief's historic ``cast`` was a presentation subset.  It must not be
used as the vocabulary for a panel that needs to distinguish a model value near
zero from a constraint absent from the fit.  The artifact is that vocabulary:
one hourly row for every represented constraint.
"""
from __future__ import annotations

import pandas as pd


# This is the legacy *serving* threshold, retained only as the default response
# filter.  It does not participate in fitting or change the artifact.
DEFAULT_SERVING_FLOOR_ABS = 2.0


def forecast_mu_rows(artifact, constraint_keys: list[str], *,
                     include_below_floor: bool = False,
                     serving_floor_abs: float = DEFAULT_SERVING_FLOOR_ABS) -> pd.DataFrame:
    """Return requested artifact rows in request order.

    With the default filter, a row must clear the historic per-hour serving
    floor.  ``include_below_floor`` deliberately removes only that response
    filter: a requested constraint that is represented by the fit then returns
    its (possibly all-near-zero) hourly forecast.  Unknown keys are never
    manufactured as zero-valued rows.
    """
    requested = list(dict.fromkeys(str(key) for key in constraint_keys))
    available = [key for key in requested if key in artifact.E_mu.columns]
    values = artifact.E_mu.reindex(columns=available)
    if not include_below_floor:
        available = [
            key for key in available
            if float(values[key].abs().max()) >= serving_floor_abs
        ]
        values = values.reindex(columns=available)
    return values
