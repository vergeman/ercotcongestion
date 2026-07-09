"""Regime helpers — bucket hours by driver signal so downstream metrics
can be conditioned on regime rather than pooled across the whole window.

Library only. CLIs live under `compute/experiments/regime_scorecard/`
(diagnostic) and eventually `compute/regime_partition/` (production stage,
per plan/handoff-regime.md step 2).
"""
from compute.regimes.binners import (
    BinResult,
    bin_hours,
    parse_scheme,
)
from compute.regimes.covariates import load_hourly_covariates

__all__ = [
    "BinResult",
    "bin_hours",
    "parse_scheme",
    "load_hourly_covariates",
]
