"""Runner layer — the CLIs and DB-write orchestration for the μ forecast + SF map.

The modules under `compute/mu` and `compute/sf` are import-only libraries (no CLI
`main`, no DB side effects). This package owns the three runners that wire them to
Postgres and the served pointers:

* `daily_forecast`  — the daily fit-then-predict job (`forecast_current[ercot]`).
* `weekly_map`      — the weekly SF-map refresh (`implied_shift_factors`, `map-v1`).
* `backfill_nodal`  — the one-time backtest walk + nodal seed / verdict CLI.
"""
