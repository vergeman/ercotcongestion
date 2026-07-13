# implied_binding_proximity (experiment archive)

Superseded by `compute/implied_binding_proximity/` (plan 0062).

The production module reads the ingested NP4-191-CD shadow prices (plan
0061) and DAM SPP congestion directly from Postgres, adds a rolling refit
cadence (`--refit-days`, default 7), per-column standardization on the
ridge input, and per-window R² / kept-constraint diagnostics. It runs as
a pipeline stage between `matrix` and `correlation_map`.

Files here are the original CSV-in / CSV-out prototype that seeded the
design and the frozen 2025-07-23 sample it was validated on. Kept for
provenance — the walkthrough in `docs/implied_binding_proximity.md` still
references these numbers.

Run the production module:

    python -m compute.implied_binding_proximity.runner \
        --run-id <id> --start 2025-05-24 --end 2025-07-23 --refit-days 7
