# 0138 - node-history from `forecast_nodal`

Type: api rewire (spun out of 0137)
Branch: (TBD, e.g. `feat/0138-forecast-nodal-live-daily`)
Status: PENDING

## Summary

`/analysis/standouts` builds each node's trailing-30-day *forecast* congestion by
decoding 30 daily SF+μ artifacts in a Python loop (`api/analysis.py:1085-1099`). That
decode floors the cold load. The constraint side already avoids it by reading
`forecast_constraint_daily` in one query; the nodal equivalent — `forecast_nodal` —
already exists and already has the data. **The only change is to read it.**

## Premise correction (verified on prod)

The original draft assumed a new backfill was needed. It isn't. `persist_forecast`
writes `forecast_nodal` and the SF artifact **together, from the same result**
(`daily_forecast.py:428-438`), and both the live cron and the 0133 `backfill_artifacts`
re-cut job use that path. So `forecast_nodal` is already being computed by the backfill
runbook you are running now — nothing to add, no separate job. On prod the two tables
have identical coverage (h1 2025-01-01 → 2026-08-18, 595 days, no gaps).

## The change (Step 3 only)

Replace the artifact-decode loop in `get_standouts` (`analysis.py:1085-1099`, the
`load_daily_artifacts` + `_project_node_profile` loop that fills `node_histories`) with
one query:

```sql
SELECT settlement_point, delivery_date, avg(point) AS peak_mean
FROM forecast_nodal
WHERE run_id=%s AND horizon=%s AND delivery_date >= d-30 AND delivery_date < d
  AND EXTRACT(HOUR FROM ts AT TIME ZONE 'America/Chicago') BETWEEN 7 AND 22
GROUP BY settlement_point, delivery_date
```

Assemble `node_histories[point] = [peak mean per day]` in pandas — same dict shape the
standout selectors consume. Keep `_project_node_profile` as a fallback for any day
absent from the table. `/analysis/top-nodes` uses the *settled* history and is
unaffected.

## Notes

* `forecast_nodal.point` = `−(E[μ]·SF)` (`project.py:366`) — the same congestion the
  api projects (`_project_node_profile`), same sign, no energy/λ. Valid swap.
* `point` is stored float32, so the table-backed mean differs from the float64 artifact
  path at ~1e-6 — below the 1.5×/0.5× standout gates. Accepted.

## Acceptance

* [ ] standouts forecast node-history reads `forecast_nodal` (no 30× decode);
      numerically equivalent within float32 to the artifact path on sample days.
* [ ] Cold `/analysis/standouts` ~2.7s → ~0.3s; `/brief` cold ~4.2s → ~1s.
* [ ] Fallback exercised for a day absent from `forecast_nodal`.
