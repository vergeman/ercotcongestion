# 0007 - constraint-confidence-filter

Type: feat
Branch: feat/0007-constraint-confidence-filter

## Goal

* Replace the hours-based low-confidence flag with a **shape** verdict that
  detects the ridge-clamp artifact.
* Demote `binding_hours` to a "thin support" annotation, never a disqualifier.

## Context

* `binding_hours < 50` is a bad discriminator: clean-but-brief constraints
  (`TRDWEL` 48h, `PLC_KAME` 46h) are trustworthy, while the real artifact
  (`6429__D`, 82h) binds *more* and still rails. Hours anti-correlates with fit
  quality on these cases.
* `|SF| = 1.0` is not itself noise — it's the signature of a **radially-fed**
  node (a single-rail resource like `BELCNTY_XFMR`'s `JUNG_SLR` is legitimate).
  The artifact is the ill-conditioned ridge clamp: **several** nodes co-equal at
  the ±1 cap, scattered, detached from the body by a magnitude cliff.
* Full rationale + worked examples in `docs/ERCOT_constraints.md` §4.

## Approach

* Persist two shape scalars on `constraint_geo` (migration `29_constraint_geo_rail.sql`):
  * `n_rail` — nodes with `|SF| >= 0.999` (clamped at `SF_ABS_CAP`).
  * `peak_offrail` — max `|SF|` among non-railed nodes (top of the graded body).
* Compute both in `geo_persist.py::_window_geo`; write via `persist.py` COPY.
* **Verdict:** low-confidence := `n_rail >= 2` **or** (`n_rail >= 1` **and**
  `peak_offrail < 0.10`). Thin support := `binding_hours < 50` (annotation only).
* Surface on `ConstraintGeo` + `ConstraintReach` (`api/models.py`, `api/map.py`);
  consume in `GridMap.tsx` (muted marker + "ridge clamp" / "thin support" tooltip)
  and `DetailCard.tsx` (verdict + support line).
* Deploy order: run migration → `geo_persist --run-id <run>` backfill
  (delete-then-copy repopulates every row) → roll out API (its SELECT needs the
  new columns present first).
* Do NOT touch: the SF fit/model, the `min_frac` reach floor (0006), other endpoints.

## Acceptance

* [x] Migration adds `n_rail`/`peak_offrail`; `geo_persist` populates them (80,602 rows, 0 NULL).
* [x] Verdicts: `6429__D`/`SCARBI_TITAN` → low-confidence; `BELCNTY`/`PLC_KAME`/`TRDWEL`/`35050__B`/`6437__F` → keep (+ thin); `VALEXP` → full.
* [x] `/map/reach` returns `n_rail`/`peak_offrail`; badge shows "ridge clamp" vs "thin support".
* [x] `api/tests/test_map.py` passes; `docs/ERCOT_constraints.md` §4 rewritten around shape-not-hours.
