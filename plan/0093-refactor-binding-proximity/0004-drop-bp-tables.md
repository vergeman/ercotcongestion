# 0093-0004 - drop the binding-proximity tables

Type: refactor
Branch: refactor/0093-0004-drop-bp-tables

## Goal

* Drop `implied_binding_proximity` and `implied_binding_proximity_current` — no code
  references them after 0001-0003.

## Context

* Created in `db/migrations/22_implied_binding_proximity.sql`; superseded by the SF
  tables (`25_implied_shift_factors.sql`) the v3 map serves.
* Migrations are forward-only and numbered; the latest is `32_constraint_geo_core.sql`.

## Approach

* Work in: `db/migrations/33_drop_binding_proximity.sql` (new; confirm the next free
  number at apply time).
* `DROP TABLE IF EXISTS implied_binding_proximity;` and
  `DROP TABLE IF EXISTS implied_binding_proximity_current;`.
* Do NOT edit `22_...sql` (migration history is immutable — the drop is a new forward
  migration) or `25_implied_shift_factors.sql`.

## Acceptance

* [ ] Migration applies clean on a DB that has the tables and one that does not (`IF EXISTS`).
* [ ] `grep -rn implied_binding_proximity --include=*.py .` returns nothing outside `compute/legacy/`.
* [ ] `pytest` green; API boots; `/map/*` and `/meta` still serve.
