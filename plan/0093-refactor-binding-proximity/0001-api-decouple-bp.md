# 0093-0001 - api: decouple /meta from binding proximity

Type: refactor
Branch: refactor/0093-0001-api-decouple-bp

## Goal

* Stop `/api/meta` reading `implied_binding_proximity_current` — the only live API
  touchpoint on any `bp` table.
* Keep the `MetaResponse` shape unchanged so `web/src/api/client.ts` needs no change;
  `promoted_at` simply reports `null`.

## Context

* The v3 SF map (`/map/*`) serves `max(window_start)` and uses NO promote pointer
  (see the `api/map.py` header comment); `bp` is legacy.
* `api/meta.py._ibp_promoted_at` reads `implied_binding_proximity_current[ercot].promoted_at`
  for a footer "last promoted" clock — nothing else in the API reads a `bp` table.
* `web/src/api/client.ts` consumes `MetaResponse`, so *dropping* the field is a
  frontend change — avoid it; report `None` instead.

## Approach

* Work in: `api/meta.py`, `api/models.py`, `api/tests/test_meta.py`.
* Delete `_ibp_promoted_at` and its call; set `promoted_at=None` in `get_meta`.
* Keep the `promoted_at` field on `MetaResponse` (default `None`); update its
  docstring to say it is retired (always `null`).
* Drop the now-unused `psycopg` / `get_pool` / `dict_row` imports from `meta.py`.
* Update `test_meta.py`: remove the `implied_binding_proximity_current` fixture /
  assertion; assert `promoted_at is None`.
* Do NOT touch: the scorecard / `served_run_dir` fields (separate zonal product),
  `api/map.py` logic.

## Acceptance

* [ ] `grep -rn implied_binding_proximity api/` returns only comments.
* [ ] `GET /meta` returns 200 with `promoted_at: null`; the scorecard fields are unchanged.
* [ ] `MetaResponse` JSON shape unchanged; `web/` untouched and still typechecks.
* [ ] `pytest api/tests/test_meta.py` green.
