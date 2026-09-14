# Pytest Notes

* Run: `docker compose run --rm api pytest api/tests -v`

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

Profile the progressive Brief requests one at a time:

```sh
curl -sS -o /dev/null -w 'brief hero %{http_code} %{time_total}s %{size_download}B\n' \
  'http://localhost:8000/analysis/brief/hero?delivery_date=2026-08-14'
```

The API logs a `brief_details_profile` line when details composition exceeds one
second. Use it to choose the SQL path to inspect:

```sh
curl -sS -o /dev/null -w 'standouts %{http_code} %{time_total}s\n' \
  'http://localhost:8000/analysis/standouts?delivery_date=2026-08-14'
curl -sS -o /dev/null -w 'details %{http_code} %{time_total}s\n' \
  'http://localhost:8000/analysis/brief/details?delivery_date=2026-08-14'
```

Capture `EXPLAIN (ANALYZE, BUFFERS)` for the slowest section's actual SQL with
the same day/run parameters before adding an index or changing a query. Record
cache state, response size, total time, and the section breakdown in the pull
request or plan update.

### 2026-08-20 dev baseline

Isolated 2026-08-14 calls measured hero 1.59 s, standouts 1.35 s, context
0.20 s, top constraints 0.10 s, top nodes 0.17 s, grade 0.01 s, and grade
history 0.01 s. A concurrent details sample logged 4.87 s total, led by
standouts at 4.84 s. `EXPLAIN` shows its
`forecast_nodal` history query uses `idx_forecast_nodal_run_date` and completes
in 0.19 ms, but dev has no `forecast_nodal` rows for the 30-day window while
all 31 artifacts exist. Standouts therefore takes its intentional 30-artifact
fallback path in this environment; do not add an index to solve that fallback.
