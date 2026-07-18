# 0094-0001 - remove /api/meta

Type: refactor
Branch: refactor/0094-0001-remove-api-meta

## Goal

* Delete the `/meta` endpoint and its `MetaResponse` model — a debug/footer snapshot
  of the legacy zonal-map serving state.

## Context

* `/meta` reports the served scorecard cell (`served_run_dir` + `mapping/scorecard.json`
  params) and, until 0093-0001, the bp promote timestamp — all legacy-map state.
* The web client does NOT call `/meta`: `web/src/api/client.ts` has no `fetchMeta`; the
  only `/meta` string there is inside `/map/meta` (the SF map's own meta). So removal
  is web-safe.
* After 0093-0001, `meta.py` no longer reads any bp table; this removes the endpoint
  outright.

## Approach

* Work in: `api/main.py`, `api/meta.py` (delete), `api/models.py`, `api/tests/test_meta.py` (delete).
* Delete `api/meta.py` and drop its `import`/`include_router` from `api/main.py`
  (and the `/meta` line in the URL comment; keep `/healthz`, which is tagged `meta`
  but defined in `main.py`).
* Remove `MetaResponse` from `api/models.py` (confirm no other importer).
* Delete `api/tests/test_meta.py`.
* Do NOT touch: `/map/meta` (`api/map.py`), `/topology`, `/ercot_spp_range`.
* Note: `meta.py` also reads `served_run_dir`; its removal drops one of the two
  readers. The other (`/ercot_state_range`) is handled in `0002`.

## Acceptance

* [ ] `/meta` is gone (404); `/healthz`, `/map/*`, `/topology`, `/ercot_spp_range`,
  `/ercot_state_range` still serve.
* [ ] `grep -rn "MetaResponse\|meta.router\|import meta" api/` returns nothing.
* [ ] `web/` untouched and still typechecks.
* [ ] `pytest api/` green.
