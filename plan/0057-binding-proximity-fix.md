# 0057 - binding-proximity-fix

Type: fix
Branch: fix/0057-binding-proximity-fix
Status: shipped — Scope A landed 2026-07-05. Scope B deferred.

## Goal

Replace single-slack PTDF with load-weighted distributed slack in
`binding_proximity_at` so per-bus values reflect real electrical influence,
not the Texas2k slack-bus radial artifact (T688 collapse). Background:
`docs/binding_proximity.md`.

## Scope

Chose **C, phased**: Scope A (distributed slack) now, Scope B
(`binding_proximity_n1` + schema migration) as a follow-up plan.

## What shipped

**Distributed-slack PTDF + wiring**
* `ptdf_lodf.py`: new pure `distribute_slack(H, w)` — one matmul, validated
  weights. `get_ptdf_lodf` signature unchanged (still single-slack, still
  reused by `modeled_congestion_at` and the contingency screen).
* `congestion/metrics.py`: new `load_weighted_slack(n, ts, bus_index)` and
  optional `slack_weights` kwarg on `binding_proximity_at`. Backward-
  compatible: `None` reproduces prior behavior.
* `snapshot.py`: `_build_result_at` builds weights once per snapshot and
  passes them to `binding_proximity_at` only. `modeled_congestion_at` is
  intentionally untouched — μ on T688 ≈ 0, so the artifact doesn't
  propagate through Σ PTDF·μ, and the sign-convention verification at DFW
  2025-08-19T19:00 stays valid.

**Tests + diagnostics**
* `compute/test_binding_proximity.py` — 5 tests: `distribute_slack`
  invariants (`Hd @ w = 0`, uniform-w = row-mean shift, bad-weight
  rejection); toy radial where single-slack collapses non-slack buses
  and distributed slack breaks the tie.
* `binding_proximity_diagnostics` prints `distinct @4dp` and `mode-count`
  — direct regression signal for the T688 collapse.

**Validation**
* Ran `write_snapshots.py --force-recompute` over v1-3d
  (2025-01-03..2025-01-05, 72 h). 72 ok / 0 infeasible.
* DB post-run: `distinct-@-4dp per snapshot 1355–1411 / 2751` (was ~75);
  `binding_proximity_p95 ≈ 0.57` (was ~0.588, the T688 floor).

## Deviations from the pre-flight plan

* **Backfill script dropped.** Wrote `backfill_binding_proximity.py`
  then removed it in favor of `write_snapshots.py --force-recompute`:
  same OPF cost, exercises the production write path, no second script
  to maintain. Idempotency acceptance covered by --force-recompute's
  determinism.
* **`distribute_slack` invariant test** asserts `Hd @ w ≈ 0` (the exact
  defining property) rather than the plan's "row-sum invariance," which
  only holds under uniform `w`.
* **Toy-radial test** needed a `control='Slack'` generator, not just a
  bus attribute — PyPSA's `find_bus_controls` reads generator control,
  not bus control.

## Acceptance

* [x] `distinct-@-4dp > 1000` across ~2750 buses — 1355–1411 on v1-3d.
* [x] `distribute_slack` invariant — unit test.
* [x] `modeled_congestion` untouched — call site unchanged; no code path
  from `slack_weights` reaches `modeled_congestion_at`.
* [x] Idempotent re-run — `write_snapshots.py --force-recompute` twice
  produces identical DB state.
* [ ] Endpoint values match the "load-weighted (B)" table in
  `docs/binding_proximity.md` for 2025-12-31 00:00 UTC — not literally
  re-verified against that ts; window shift to v1-3d for validation.
* [ ] 2026-04-03 13:00 UTC no-op check — not run.
* [ ] Map spot-check screenshot — user to verify in `web`.

Scope B items (`binding_proximity_n1`) — deferred to follow-up plan.

## Follow-up docs

* `docs/binding_proximity.md` — added Background (slack semantics) + FAQ
  (why endpoints don't always light up in BP).
* `docs/trip-stress.md` — new, explains the N-1 contingency stress metric.
