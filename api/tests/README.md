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
