# 0138 - node-history from `forecast_nodal`

Type: api rewire (spun out of 0137)
Branch: (TBD, e.g. `feat/0138-forecast-nodal-live-daily`)
Status: PENDING

## Summary

`get_standouts` builds each node's trailing-30-day forecast congestion by decoding 30
SF+μ artifacts in a loop (`analysis.py:1085-1099`), which floors the cold load. The
constraint side already reads `forecast_constraint_daily` in one query; the nodal
equivalent `forecast_nodal` exists and already has the data. **The change is to read it.**

Premise correction (verified on prod): no backfill is needed. `persist_forecast` writes
`forecast_nodal` and the SF artifact together (`daily_forecast.py:428-438`), and both the
live cron and the 0133 `backfill_artifacts` re-cut use that path — so the table is already
maintained by the backfill you're running. Prod coverage matches the artifacts (h1
2025-01-01 → present, no gaps).

## The change

Replace the artifact-decode loop with one query, grouping on the stored `delivery_date`
label (reproduces the loop's per-day binning exactly, including pre-0133 UTC-cut days):

```sql
SELECT settlement_point, delivery_date, avg(point) AS peak_mean
FROM forecast_nodal
WHERE run_id=%s AND horizon=%s AND delivery_date >= d-30 AND delivery_date < d
  AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/Chicago') BETWEEN 7 AND 22
GROUP BY settlement_point, delivery_date
```

Keep `_project_node_profile` as a fallback for any day absent from the table.
`/analysis/top-nodes` uses settled history and is unaffected.

Notes: `forecast_nodal.point` = `−(E[μ]·SF)` (`project.py:366`) — the same congestion the
api projects, so a valid swap; read at the table's float32 (differs ~1e-6, below the
1.5×/0.5× standout gates — accepted).

## Acceptance

* [x] node-history reads `forecast_nodal` in one query (no 30× decode) via
      `_forecast_node_history`; unit-tested.
* [x] Fallback to artifact projection for an absent day; unit-tested.
* [ ] Prod (gated on 0133 re-cut): numerically equivalent within float32 to the artifact
      path on a sample of re-cut days.
* [ ] Prod: cold `/analysis/standouts` ~2.7s → ~0.3s, `/brief` cold ~4.2s → ~1s.
