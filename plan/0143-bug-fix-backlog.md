# 0143 - bug-fix-backlog

Type: fix
Branch: fix/0143-bug-fix-backlog

Running queue for defects too small to justify their own plan. Append-only: add a
task as a bug is found, tick it when fixed. Anything needing a migration or
backfill graduates to its own numbered plan.

## Goal

* One queue for small, independent bug fixes.
* Each task records its root cause in a line or two, not just the symptom.
* Each fix ships with a test verified red against the pre-fix code.

## Context

* Prior fixes of this size left no trace; 0143.1 survived ~3 weeks because a
  stale premise in a comment was never corrected.
* Tasks often touch invariants owned elsewhere (0133 CT day blocks, 0123 horizon
  preview) — cite the owning plan.

## Approach

* One `###` task per bug, numbered `0143.N`; one commit each, revertable alone.
* Verify each regression test red on pre-fix code — don't assume a passing test
  is a meaningful one.
* Do NOT batch unrelated tasks, or let a task expand past a handful of files.

## Tasks

### 0143.1 — Matrix frame empty for the last 5–6 hours of every CT day ✅

* `/matrix` returned `interval_not_in_artifact` for CT-evening cursor hours (e.g.
  `t=2026-04-28T02Z`), blanking the whole board on every day.
* Cause: `get_matrix_frame` keyed the artifact by UTC date (0119/`fc776d1`), but
  the writer buckets by CT delivery date (0095/`b9d6c4f`, 0133). The block keyed
  D spans `05:00Z D → 04:00Z D+1`, so the tail hours landed in the next block.
* Fix: key the lookup by `delivery_date`. `api/matrix.py` is the only reader that
  derives an artifact key from an instant.
* Test: `test_frame_resolves_all_ct_day_hours_from_one_ct_artifact` — all 24
  hours of a CT block resolve, tail hours keep the prior CT label.

### 0143.2 — Three `test_analysis.py` grade tests fail on master

* On clean `master` (`b81efc6`): `test_grade_returns_unblended_constraint_and_node_halves`,
  `test_grade_uses_the_materialized_snapshot_without_recomputing`,
  `test_top_constraints_ranks_the_full_forecast_artifact_and_keeps_settled_missingness`.
  Grade bodies come back `graded: False, unavailable_reason: 'settlement_pending'`.
* Cause: undiagnosed. Likely the fixtures no longer clear `/analysis/grade`'s
  settlement gate — establish whether the gate or the fixtures are wrong before
  touching either.
* Test: the three existing tests, passing for the right reason.

## Acceptance

* [x] 0143.1 — every in-range hour of a CT delivery day resolves; boundary test
      verified red pre-fix.
* [ ] 0143.2 — `pytest api/tests` green on a clean checkout.
* [ ] Every closed task records a root cause, not only a symptom.
