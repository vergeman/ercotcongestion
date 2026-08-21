# Pytest Notes

* Run: `docker compose run --rm api pytest /api/tests -v`

## Fake Pool Behavior

* `fake_pool.cursor.queue`: populate with fixtures - there's no type awareness
  at this point; just feeding it objects. These correspond with a positional return by cursor.

* So In `state.py` the `cur.fetchone()` pops the first element pushed into the
  test via `fake_pool.cursor.queue` (e.g. a `_meta_row`), and then
  `cur.fetchall()` empties the remaining queue, typically a list of buses.
  * Reminder at this point it's "faking" the cursor calls as called in router
    code order. The db returns the raw fixtures; which then get turned to json
    via response.

## "patch"

* NB: not request type, this is is from unittest.mock; temporarily replaces a
  Python object with a fake during a test.

* `test_topology.py`: it's replacing the function in the block with the mock,
  `FAKE_TOPO`.

* Because of our paths, right now it's at top level (so normally
  `api.routes.topology....`) but right now just `topology....()`

## Brief profiling

Profile a day that is not already final-cached, one request at a time, so the
result reflects the visible page's critical path rather than the in-process
settled-day cache:

```sh
curl -sS -o /dev/null -w 'brief %{http_code} %{time_total}s %{size_download}B\n' \
  'http://localhost:8000/analysis/brief?day=2026-08-14'
```

The API logs one `brief_profile` line when composition exceeds one second. It
contains the total and the seven section wall times; use that line to choose
the SQL path to inspect. Run the corresponding section directly when comparing
iterations:

```sh
curl -sS -o /dev/null -w 'standouts %{http_code} %{time_total}s\n' \
  'http://localhost:8000/analysis/standouts?delivery_date=2026-08-14'
curl -sS -o /dev/null -w 'hero %{http_code} %{time_total}s\n' \
  'http://localhost:8000/analysis/hero?date=2026-08-14'
```

Capture `EXPLAIN (ANALYZE, BUFFERS)` for the slowest section's actual SQL with
the same day/run parameters before adding an index or changing a query. Record
cache state, response size, total time, and the section breakdown in the pull
request or plan update.

### 2026-08-20 dev baseline

First uncached forecast-day `/analysis/brief` samples were 3.18 s for
2026-08-14 and 3.85 s for 2026-08-13 (about 67–68 kB). Isolated 2026-08-14
calls measured hero 1.59 s, standouts 1.35 s, context 0.20 s, top constraints
0.10 s, top nodes 0.17 s, grade 0.01 s, and grade history 0.01 s. Treat these
as a local baseline only; the new request-level log is the source for future
comparisons under the same cache state. A later concurrent composition sample
logged 4.87 s total, led by standouts at 4.84 s. `EXPLAIN` shows its
`forecast_nodal` history query uses `idx_forecast_nodal_run_date` and completes
in 0.19 ms, but dev has no `forecast_nodal` rows for the 30-day window while
all 31 artifacts exist. Standouts therefore takes its intentional 30-artifact
fallback path in this environment; do not add an index to solve that fallback.
