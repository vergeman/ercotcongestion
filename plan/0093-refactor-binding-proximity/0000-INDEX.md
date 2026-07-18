# 0093 - refactor: remove binding proximity

Teardown of the legacy implied-binding-proximity (`bp`) product — which the v3 SF
map does **not** serve — followed by the SF incremental-append it unblocks.

The map serves `implied_shift_factors` + `constraint_geo` + `sf_window_meta`
(`api/map.py`, always `max(window_start)`). `bp` (`implied_binding_proximity`, the
scored `bp_ercot` panel, `--persist`/`--promote`, `ingest`, `metric.binding_proximity`)
is dead scaffolding riding along inside the SF runner.

## Order (each branch merges green on its own; later branches assume the earlier teardown)

1. `0001-api-decouple-bp` — stop the API reading the `bp` pointer (the last live reader).
2. `0002-runner-sf-only` — strip `bp` scoring / `bp_ercot.npz` / `--persist` from the SF runner.
3. `0003-delete-bp-modules` — delete the now-dead `bp` modules + persist helpers.
4. `0004-drop-bp-tables` — drop the two `bp` tables (forward migration).
5. `0005-sf-incremental-append` — per-window SF append; the payoff, simpler now that
   there is no `bp` panel to keep whole (moved here from `0092`, rewritten for the
   "persist only complete windows" design).

Teardown before schema: readers (0001) → writers (0002) → dead modules (0003) →
tables (0004). 0005 is independent of the drop but lands last (cleanest once `bp`
is gone).

## Out of scope

The **zonal/clustering** map is a separate legacy product and stays: `served_run_dir`
symlinks, `mapping/scorecard.json`, `compute.promote`'s symlink flips, and
`/api/meta`'s scorecard fields. Only the `bp`/IBP pieces come out.
