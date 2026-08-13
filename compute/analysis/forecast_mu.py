"""Read-time slices of the untruncated forecast-μ artifact.

The daily brief's historic ``cast`` was a presentation subset.  It must not be
used as the vocabulary for a panel that needs to distinguish a model value near
zero from a constraint absent from the fit.  The artifact is that vocabulary:
one hourly row for every represented constraint.
"""
from __future__ import annotations

import pandas as pd


def forecast_mu_rows(artifact, constraint_keys: list[str]) -> pd.DataFrame:
    """Return requested artifact rows in request order.

    The request's keys are the only serving filter. A requested constraint that
    is represented by the fit returns its possibly all-near-zero hourly
    forecast; unknown keys are never manufactured as zero-valued rows.
    """
    requested = list(dict.fromkeys(str(key) for key in constraint_keys))
    available = [key for key in requested if key in artifact.E_mu.columns]
    return artifact.E_mu.reindex(columns=available)
