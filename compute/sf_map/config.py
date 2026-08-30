"""Adopted SF operating point — the single source of truth for the fitted
shift-factor pipeline.

Both the μ forecast (`compute.mu`) and the SF explorer map (`compute.sf`) fit
shift factors at these values; defining them once here is what keeps the two
pipelines from drifting. Values are the honest OOS re-sweep's selection
(plan/0082 S1.5), adopted for serving in plan/0090.

CLI flags that pass these explicitly (the forecast / map cronjobs) are now
belt-and-suspenders, not load-bearing: the module defaults already are the
operating point, so a hand-run without the flags fits at the same point.
"""
from __future__ import annotations

import pandas as pd

WINDOW_DAYS = 240      # trailing SF fit window
REFIT_DAYS = 7         # refit cadence
RIDGE_LAMBDA = 1.0     # ridge on the standardized solve (0082 S1.5)
MIN_HOURS = 25         # min in-window binding hours to admit a constraint
RTC_B = pd.Timestamp("2025-12-05", tz="UTC")
