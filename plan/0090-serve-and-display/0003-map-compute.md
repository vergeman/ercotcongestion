# 0090.0003 - map-compute

Type: feat
Branch: feat/0003-map-compute

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add migration `28`: `constraint_geo` table + nullable `sf_window_meta.sf_stability` column.
* Persist the SF map for a fresh `map-v1` run over full legal history (`compute.sf.runner --persist-sf`), populating `implied_shift_factors` + `sf_window_meta` for every refit window.
* Persist per-window constraint geography (`geo.constraint_geography`) into `constraint_geo`, and backfill `sf_window_meta` with `sf_stability` (+ `oos_r2`/`coverage`) via `compute.sf.eval`.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `serving-and-display-design.md` Phase 1; spec of record is `spec-phase1-serve-map.md` §0–§2, §8.1–§8.2.
* The SF matrix + window meta are already persistable — migration `25_implied_shift_factors.sql` built `implied_shift_factors` and `sf_window_meta` for exactly this. The only genuinely new persistence is `constraint_geo` (§2). No new fitting code.
* **Flag correction (verified against `compute/sf/runner.py`):** the flag that writes `implied_shift_factors` + `sf_window_meta` is **`--persist-sf`** (runner.py:232 `if args.persist_sf`, `copy_sf_rows`/`write_window_meta`), NOT `--persist`. `--persist` writes the legacy binding-proximity panel (`copy_bp_rows`), which spec §0/§3 explicitly excludes. The spec prose says "`--persist`" loosely — use `--persist-sf` and do NOT pass `--persist`/`--promote`.
* Leak-safety is inherited: `geo.py` fits SF on each honest trailing window and refuses a pre-fit global SF (`geo_panel` never accepts one) — so per-window geo is walk-forward-honest by construction (memory [[sf-map-as-geographic-crosswalk]], the fitted-SF leak trap).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `db/migrations/` (new `28_*.sql`), `compute/sf/` (`persist.py`, and a thin geo-persist entry — `runner.py` or a small sibling), `compute/mu/geo.py` (read only — reuse `constraint_geography`).
* **Migration** `28_constraint_geo.sql`: create `constraint_geo(run_id text, window_start timestamptz, constraint_key text, lat real, lon real, spread_km real, kv_mean real, kv_max real, zone_shares jsonb, max_abs_sf real, binding_hours int, PRIMARY KEY (run_id, window_start, constraint_key))`; `ALTER TABLE sf_window_meta ADD COLUMN sf_stability real` (nullable). Follow the existing migration header/style in `25_implied_shift_factors.sql`.
* **SF persist run:** `python -m compute.sf.runner --run-id map-v1 --persist-sf` over full history through the latest legal window at the adopted operating point (window 240d, refit 7d, ridge-λ=1, min-binding-hours=25, standardize — the runner defaults; pass explicitly if any default drifts). One run populates every refit window.
* **Geo persist:** for each persisted `window_start`, apply `geo.constraint_geography(SF, sp)` to that window's SF and upsert one `constraint_geo` row per constraint. Columns straight from `geo.py`: `geo_lat`→`lat`, `geo_lon`→`lon`, `geo_spread_km`→`spread_km`, `geo_kv_mean/max`→`kv_mean/max`, `geo_zone_<z>` shares→`zone_shares` jsonb. Add `max_abs_sf = max_sp |SF|` and `binding_hours` (support) per constraint from the same window. Add the `COPY`/upsert helper alongside `copy_sf_rows`/`write_window_meta` in `persist.py` (`copy_constraint_geo_rows` + `delete` for idempotent re-persist).
* **Stability backfill:** `compute.sf.eval::_sf_corr` gives disjoint-adjacent-window SF correlation → write window-level `sf_stability` onto `sf_window_meta`. Backfill `oos_r2`/`coverage` in the same eval pass if not already populated by the runner. Per-*constraint* stability is deferred (spec §1.3, §9).
* Do NOT touch: `api/`, `web/`; the legacy binding-proximity panel, its pointer (`implied_binding_proximity_current`), `--persist`/`--promote`, `compute/promote.py`. Do NOT fit a global SF anywhere near `geo.py` (leak trap).

## Commits

<!-- Grouped so each commit leaves the tree runnable; migration applies clean. -->

* **Commit A — `feat(db): add constraint_geo table + sf_window_meta.sf_stability (migration 28)`**
  * `db/migrations/28_constraint_geo.sql` — `constraint_geo` create + `sf_window_meta.sf_stability` nullable column; applies against a DB already at migration 27.
* **Commit B — `feat(sf): persist map-v1 SF matrix + window meta (--persist-sf)`**
  * Run `compute.sf.runner --run-id map-v1 --persist-sf`; verify `implied_shift_factors` + `sf_window_meta` populated for every refit window. No code change if the runner path is unmodified — capture the invocation + row counts in the commit body / ops notes.
* **Commit C — `feat(sf): persist per-window constraint geography into constraint_geo`**
  * `compute/sf/persist.py` — `copy_constraint_geo_rows` + `delete_constraint_geo(run_id)`; geo-persist step (runner hook or sibling) applying `geo.constraint_geography` per window, adding `max_abs_sf`/`binding_hours`.
* **Commit D — `feat(sf): backfill sf_stability / oos_r2 / coverage on sf_window_meta`**
  * `compute/sf/eval.py` — window-level `sf_stability` from `_sf_corr` on consecutive refits; write onto `sf_window_meta`; ensure `oos_r2`/`coverage` present for `map-v1`.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] Migration 28 applies clean on a DB at 27; `constraint_geo` and `sf_window_meta.sf_stability` exist with the columns/types in spec §2.
* [ ] `implied_shift_factors` + `sf_window_meta` contain `run_id='map-v1'` rows for every refit `window_start`; no `--persist`/binding-proximity rows written under this run.
* [ ] `constraint_geo` has one row per (window, constraint) with non-null `lat`/`lon`/`max_abs_sf`/`binding_hours`; a known west-Texas constraint's centroid lands in west Texas (spec §7 geo sanity); large `spread_km` correlates with bimodal `zone_shares`.
* [ ] `sf_window_meta.sf_stability` (+ `oos_r2`/`coverage`) is non-null for `map-v1` windows.
* [ ] Re-running the geo/SF persist under the same `run_id` is idempotent (delete-then-copy), not duplicating rows.
