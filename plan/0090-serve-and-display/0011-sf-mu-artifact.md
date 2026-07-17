# 0011 - sf-mu-artifact

Type: feat
Branch: feat/0011-sf-mu-artifact

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Emit the per-day **SF + point-μ (`E_mu`) artifact** so `/forecast/drivers` and `/forecast/whatif` can be reconstructed on read instead of storing ~75M driver rows.
* Add the `forecast_sf_artifact` table (migration `31_forecast_sf_artifact.sql`) and `build_sf_mu_artifact(SF, E_mu)` writing flat/vocab-coded npz and/or a bytea blob keyed by `(run_id, delivery_date)`.
* Add the offline `--drivers` flag for curated-day debug materialization only — never full-history.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2a-nodal-panel.md` §0 (serve-and-reconstruct where the request carries a parameter), §4a (the SF+μ artifact), §5(c), §6 (`forecast_sf_artifact`), §8 (`--drivers`). Depends on **0010** (`forecast_current`, DB write path); do it first.
* Drivers ("top-K constraints around a node") and what-if (`−μ·SF[c,:]`) both carry an arbitrary per-request parameter no stored panel can enumerate — so the day's `SF` + `E_mu` are the objects to ship, and the server slices them (spec §0). Materializing driver rows is ~240k/day, ~75M across the backtest — don't.
* `E_mu = P(bind)·E[μ|bind]` and `SF` are already in hand from `draw_congestion`/`propagate_window` (0008) — the artifact is a serialize, no second SF multiply (spec §4a).
* **Guardrail (spec §4a):** a single constraint's SF can flip sign between refits inside a co-binding block. The artifact must carry enough to lead with the stable unsigned exposure (`max_c|SF|`); signed per-constraint drivers are the caveated detail. The consuming endpoints are Phase 2 serving — **not built here**; this branch only emits the substrate.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `db/migrations/31_forecast_sf_artifact.sql` (new), `compute/mu/propagate.py` (`build_sf_mu_artifact`, `--drivers`), a `save_sf_mu`/`load_sf_mu` pair beside `save_nodal`.
* **Migration `31_forecast_sf_artifact.sql`** — verbatim from spec §6: `forecast_sf_artifact (run_id text, delivery_date date, sf_npz bytea NOT NULL, PRIMARY KEY (run_id, delivery_date))`.
* **`build_sf_mu_artifact(SF, E_mu) -> bytes`** (spec §4a) — flat/vocab-coded npz: `SF` (index = constraint keys, columns = SPs; dense f32 ≈ 4–8 MB, threshold if it helps) + `E_mu` `(24h × K)` on the same key vocab. Mirror the `key_vocab`+`key_code` idiom. `save_sf_mu`/`load_sf_mu` round-trip it.
* **Persist**: write the npz under the run dir and/or `COPY`/insert the bytea into `forecast_sf_artifact` keyed by `(run_id, delivery_date)`. Idempotent replace per key, same discipline as 0010. (Which of disk vs bytea is authoritative is a spec §11 open choice — pick per how the API reads the run dir today; support both cheaply.)
* **`--drivers`** (spec §8): offline/debug materialization of driver rows for **curated days only** — a bounded set passed explicitly, never the full backtest. Guard against a full-history run (spec §2.4, §5a). No `forecast_drivers` table is created (spec §6).
* Do NOT touch: `api/` (the `/forecast/drivers` + `/forecast/whatif` endpoints are Phase 2 serving, a separate branch); `forecast_nodal`/`forecast_current` schema (0010); the panel emission path (0008/0009).

## Commits

<!-- Grouped so the migration applies and the artifact round-trips at branch end. -->

* **Commit A — `feat(db): forecast_sf_artifact (migration 31)`**
  * `db/migrations/31_forecast_sf_artifact.sql` — bytea artifact table (spec §6).
* **Commit B — `feat(propagate): build_sf_mu_artifact + save/load_sf_mu`**
  * `propagate.py` — flat vocab-coded `SF`+`E_mu` serializer from the arrays already in hand; round-trip helpers.
* **Commit C — `feat(propagate): persist SF+μ artifact per (run_id, delivery_date)`**
  * `propagate.py` — write npz under run dir and/or bytea into `forecast_sf_artifact`; idempotent per key.
* **Commit D — `feat(propagate): --drivers curated-day offline materialization`**
  * `propagate.py` — `--drivers` guarded to an explicit curated day set; refuses full-history.
* **Commit E — `test(propagate): SF+μ round-trip reproduces drivers`**
  * `compute/mu/tests/` — `load_sf_mu` recovers `SF`/`E_mu`; `contrib[k] = −E_mu[ts,k]·SF[k,sp]` for a node matches an independently computed top-K; artifact size in the single-digit-MB/day range; `--drivers` on a >1-day span raises.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] Migration 31 applies; `forecast_sf_artifact (run_id, delivery_date, sf_npz)` exists with the spec §6 PK.
* [x] `build_sf_mu_artifact` produces a flat vocab-coded npz (`SF` + `E_mu`, same key vocab) ≈ single-digit MB/day; `load_sf_mu` round-trips it.
* [x] For a spot node, `−E_mu[ts,·]·SF[·,sp]` sorted by `|contrib|` reproduces the top-K an independent computation gives (the reconstruction the endpoint will do), and `max_c|SF|` (unsigned exposure) is recoverable as the stable headline.
* [x] The artifact is stored per `(run_id, delivery_date)`, idempotent on re-run; **no** `forecast_drivers` table and **no** stored driver rows.
* [x] `--drivers` materializes only an explicit curated day set and refuses a full-history span; `api/` untouched; `pytest` green.
* [x] `python -m compute.mu.propagate --nodal-out out.npz --to-db --run-id mu-all-v1` writes both the npz and the DB panel; `pytest` green.
