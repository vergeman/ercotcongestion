# 0057 - binding-proximity-fix

Type: fix
Branch: fix/0057-binding-proximity-fix

## Goal

* Replace single-slack PTDF with load-weighted distributed slack in `binding_proximity_at` so per-bus values reflect real electrical influence, not the Texas2k slack-bus radial artifact.
* Optionally add a **separate** per-bus metric `binding_proximity_n1` that captures post-contingency stress via LODF, so the frontend can offer a base-case-vs-outage-worst-case toggle without conflating the two.
* Backfill `bus_snapshots.binding_proximity` (and, if scope B, `bus_snapshots.binding_proximity_n1`) and matching `snapshot_meta` aggregates for existing rows so the map/API reflect the corrected metrics.

## Context

* `docs/binding_proximity.md` documents the artifact: Texas2k marks bus 7098 (WADSWORTH) `control='Slack'`; 7098 is connected to the rest of the grid only through transformer T688; PyPSA's single-slack PTDF gives every non-slack bus `|PTDF[T688, b]| ≈ 1`, so the `max` in `binding_proximity_at` collapses to `loading[T688]` for the vast majority of buses in most snapshots.
* Empirically on `2025-12-31 00:00 UTC`, 2666 / 2750 buses report the identical value 0.5984; distributed slack restores spread to 1477 distinct values with sd 0.15 and correctly differentiates binding-line endpoints (0.15–0.55) from quiet buses (0.05–0.15). Full comparison table in `docs/binding_proximity.md`.
* Base-case metric only sees currently-binding lines. The N-1 highlight on the map is contingency-driven — if the map should agree with the metric on "these buses are close to binding," the LODF extension is what closes that gap. See below for the decision.
* Pipeline already computes LODF per snapshot (`get_ptdf_lodf` returns `lodf_lines`) and already computes top-K contingencies at `compute/snapshot.py:182`. The LODF extension reuses both — no new expensive linear algebra.

## Decision required before implementation

**Scope A — distributed slack only.** Fixes the reported artifact by switching `binding_proximity` from single-slack to load-weighted distributed-slack PTDF. Cheap: one matmul per snapshot, existing column overwritten in place, no schema change. Recommended if the immediate goal is "make the map informative again."

**Scope B — distributed slack + new `binding_proximity_n1` column.** Adds a second, orthogonal metric that answers a different operational question (post-contingency stress vs current-dispatch stress). Requires: a schema migration to add `bus_snapshots.binding_proximity_n1` and `snapshot_meta.binding_proximity_n1_{max,p95}`, LODF-based computation restricted to top-K contingencies inside `_build_result_at`, doubled backfill work (both metrics need base-case flows, so it's still one re-solve per snapshot). The two metrics are kept **separate** — merging into one `max(...)` would hide which scenario drove any bus's value, and the frontend loses the ability to offer a base-case-vs-N-1 toggle. Recommended if the map's N-1 highlight is a first-class part of the user experience.

**Scope C — both, phased.** Ship Scope A first (immediate visible improvement, no schema change, small blast radius), then Scope B as a follow-up plan once A is validated on the map. Recommended default if unsure.

**→ Confirm scope with the user before Commit 1.** The rest of this plan is written assuming Scope C, phased: Commits 1–3 = Scope A, Commit 4 (+ migration) = Scope B added later if chosen. If Scope A only, stop after Commit 3. If Scope B alongside, promote Commit 4 and its migration to run in the same PR as Commits 1–3.

## Approach

* Work in: `compute/congestion/metrics.py`, `compute/ptdf_lodf.py`, `compute/snapshot.py`, plus a new backfill script under `compute/`.
* Entry point / primary change: `binding_proximity_at` and its PTDF input.

**Commit 1 — distributed-slack PTDF plumbing**

* In `compute/ptdf_lodf.py`:
  * Add a pure function `distribute_slack(ptdf_single: np.ndarray, w: np.ndarray) -> np.ndarray` computing `H - (H @ w)[:, None]`. Asserts `abs(w.sum() - 1.0) < 1e-9`. Length must match `ptdf_single.shape[1]`.
  * Do NOT change `get_ptdf_lodf`'s signature — it stays single-slack for reuse by `modeled_congestion_at` and the contingency screen, which are not affected by the artifact.
* In `compute/congestion/metrics.py`:
  * Add a helper `_load_weighted_slack(n, ts, bus_index) -> np.ndarray` returning a normalized (sums to 1) weight vector aligned to `bus_index`. Reuse `build_load_per_bus`-style aggregation but return in the PTDF's bus order, not `n.buses.index` order. Zero total load → uniform fallback (`1/n`). Negative loads clipped to zero before normalizing.
  * Change `binding_proximity_at` to accept an optional `slack_weights: np.ndarray | None` parameter. If provided, compute `ptdf_used = distribute_slack(ptdf_full, slack_weights)` internally; otherwise use `ptdf_full` unchanged (backward-compatible default).
* In `compute/snapshot.py`:
  * In `_build_result_at`, build the load-weighted slack vector once per snapshot and pass it into `binding_proximity_at`. Do not pass it into `modeled_congestion_at` — that metric's PTDF-weighted mu sum is not affected by the T688 artifact (mu on T688 is essentially zero because it's never a binding constraint) and behavior should not change.
  * Update the module docstring comment near `PTDF_INFLUENCE_EPS` in `metrics.py` to explain that `binding_proximity` now uses distributed slack while `modeled_congestion` still uses single slack, and why.

**Commit 2 — tests and diagnostics**

* Add a test in `compute/test_snapshot.py` (or a new `compute/test_binding_proximity.py`) that asserts:
  * On a synthetic 3-bus radial network with slack at the leaf, single-slack `binding_proximity` collapses to one value across all non-slack buses; distributed-slack produces at least two distinct values.
  * `distribute_slack(H, w).sum(axis=1)` is ~0 for every row (row sum invariance under column shift is a defining property).
  * With `w` uniform, `distribute_slack(H, w)` equals `H - H.mean(axis=1, keepdims=True)`.
* Extend `binding_proximity_diagnostics` in `metrics.py` to print `distinct @ 4dp` and `mode-count` so future regressions of this shape are visible from the snapshot log.

**Commit 3 — backfill and API/frontend verification**

* New script `compute/backfill_binding_proximity.py`:
  * For every `snapshot_meta.status='ok'` interval, re-solve is NOT required — `binding_proximity` only needs base-case flows and s_max_pu, both persisted in `bus_snapshots` and network file. Actually flows are per-branch and not persisted; simplest path is to re-run the OPF but skip the DB write for everything except the `binding_proximity` column. Confirm with a spike before committing to method.
  * Alternative: re-solve OPF using the same operating conditions and write only `bus_snapshots.binding_proximity` and `snapshot_meta.binding_proximity_{max,p95}` via targeted `UPDATE` — leaves `modeled_congestion`, `lmp`, etc. untouched. Preferable because it makes the backfill idempotent and re-runnable.
  * Script must accept `--start` / `--end` bounds and be safe to run against a live DB (single-row upsert per bus, one row per snapshot_meta, no truncate).
* Manually verify against the `web` container:
  * Map for `2025-12-31 00:00 UTC` shows spatial gradient in `binding_proximity`, not a flat color across the state.
  * Endpoint buses of currently-highlighted binding lines show elevated values (> 0.3) relative to their neighbors.
  * Hub-average API endpoints unchanged (this metric doesn't feed hubs).
* Do NOT touch `modeled_congestion`, `basis`, `fragility`, or LMP columns; do NOT change the DB schema; do NOT re-run `run_pipeline.py` stages.

**Commit 4 — OPTIONAL, only if Scope B is chosen — separate N-1 proximity metric**

* Schema migration `db/migrations/NN_binding_proximity_n1.sql`:
  * `ALTER TABLE bus_snapshots ADD COLUMN binding_proximity_n1 double precision;`
  * `ALTER TABLE snapshot_meta ADD COLUMN binding_proximity_n1_max double precision, ADD COLUMN binding_proximity_n1_p95 double precision;`
  * NULL is the correct semantic for "not yet computed" — no default backfill in the migration itself.
* In `compute/congestion/metrics.py`, add a new function `binding_proximity_n1_at` (separate from `binding_proximity_at`, not a modification of it):

  ```
  bp_N1[b] = max_{ℓ, k ∈ top_K}  |PTDF[ℓ, b] + LODF[ℓ, k] · PTDF[k, b]|
                              · min(1, |flow[ℓ] + LODF[ℓ, k] · flow[k]| / limit[ℓ])
  ```

  * `k` iterates over the top-K contingency lines that `compute_contingencies_at` already ranks — do not iterate all n_lines² pairs.
  * The `min(1, ...)` cap prevents post-contingency overloads > 1.0 from producing `binding_proximity_n1 > 1.0` per-bus, keeping the existing "> 1.0 → solver tolerance" sanity check meaningful in `binding_proximity_diagnostics`.
  * PTDF here must be the distributed-slack PTDF from Commit 1 — same PTDF used by `binding_proximity_at`.
* In `compute/snapshot.py:_build_result_at`, call the new function alongside `binding_proximity_at`; add `binding_proximity_n1` to the returned dict and `binding_proximity_n1_max` / `binding_proximity_n1_p95` to `meta`.
* In `compute/write_snapshots.py`, extend the upsert SQL to write the new column and meta fields. Update `api/models.py` (`BusResponse`, `MetaResponse`) and `api/state.py` (SELECT lists) to surface them.
* Backfill: extend the Commit 3 backfill script (or add a sibling) — same re-solve, one more column written per row. No additional OPF cost.
* Do NOT merge with `binding_proximity`. The two answer different operational questions ("stressed now" vs "stressed after worst credible outage") and keeping them separate lets the frontend toggle between them and lets an operator debug why a specific bus is hot.

* Do NOT touch: `modeled_congestion_at`, `contingency` screen output shape, `fragility`, `basis`, or any hub-level aggregation. The PTDF cache in `_ptdf_lodf_cache` stays keyed on topology; distributed slack derives from that cache, not around it.

## Acceptance

* [ ] `binding_proximity` on `2025-12-31 00:00 UTC` shows > 1000 distinct values @4dp across the 2750 buses (was 75).
* [ ] Endpoints of the five binding lines listed in `docs/binding_proximity.md` (L61, L85, L185, L189, L287) report values matching the "load-weighted (B)" column in the empirical table within ±0.02.
* [ ] `binding_proximity` on `2026-04-03 13:00 UTC` (high-congestion, already showed spread) changes by ≤ 0.02 at every endpoint of the pre-existing binding lines — confirming the fix is a no-op when the artifact was already dominated.
* [ ] `distribute_slack` returns a matrix whose row sums are within 1e-10 of zero across a synthetic PTDF fixture.
* [ ] `modeled_congestion_total` and per-bus `modeled_congestion` on `2025-12-31 00:00 UTC` are unchanged post-fix (Commit 1 must not perturb them — regression check via a stored fixture).
* [ ] Backfill script is idempotent — running twice on the same range produces identical DB state.
* [ ] Map for `2025-12-31 00:00 UTC` visibly gradients across the state; a spot-check screenshot in the PR shows this.
* [ ] (Scope B only) `binding_proximity_n1[b]` is a **separate column** from `binding_proximity[b]` — both are populated per row, neither is derived by SQL from the other.
* [ ] (Scope B only) `binding_proximity_n1[b]` elevates buses whose local branch would be overloaded under a top-K contingency, verified on a snapshot where the N-1 highlight names a specific line — the endpoints of the highlighted line have `binding_proximity_n1` in the top decile.
* [ ] (Scope B only) On a snapshot with no meaningful contingencies (no top-K post-contingency loading > 0.3), `binding_proximity_n1 ≈ binding_proximity` per bus — the two agree when there's nothing dangerous to trip.

## Notes / deviations

* Distributed-slack PTDF is a linear correction on the single-slack matrix — no re-solve, no new PyPSA call. This is why Scope A is cheap and safe.
* Kept single-slack PTDF for `modeled_congestion_at` intentionally: mu on T688 is ~0 (T688 never binds in base case), so the artifact does not propagate into `Σ PTDF · μ`. Changing it would perturb the sign-convention verification (`compute/verify_sign_convention.py`) that was validated at DFW 2025-08-19T19:00 — out of scope here.
* If backfill turns out to require re-solving OPF (Commit 3 spike concludes flows aren't persisted), split it into a separate follow-up plan; the metric change itself does not depend on backfill completing.
