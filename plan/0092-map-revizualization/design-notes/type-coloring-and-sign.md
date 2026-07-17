# Design note — constraint-type coloring & the sign-in-aggregate rule

Supplementary to `0001-revizualization.md`. Records a paradigm explored during the
spike and **parked** (not the chosen overview), plus two data findings that are
firm design constraints regardless of which overview paradigm wins.

Data: run `map-v1`, window `2025-11-04` (1044 located constraints).

## Finding 1 — a settlement point has no aggregate sign (firm rule)

Of the 1111 settlement points that carry significant SF (|SF| ≥ 0.15·peak on some
constraint), **100% appear with *both* signs across different constraints.** A node
that is a local exporter (−SF) on one GTC is an importer (+SF) on another. There is
no single "sign of a node."

**Rule:** signed (blue = −/export, red = +/import) coloring is well-defined **only
within one selected constraint** — the drill-down. The all-constraints overview must
**never** color by node sign; the same dot would want two colors. Sign is a
per-(constraint, node) quantity, not a node property.

## Finding 2 — sign is balanced, not import-dominated

Across all constraints the peak-|SF| node is an **exporter 58%** of the time,
importer 42%; top-8 nodes average 56% export / 44% import. Any overview that looks
"all red/import" is an artifact of the color encoding, not the physics.

## Parked paradigm — color the overview by constraint TYPE

Types are separable from already-persisted fields:

| type | identified by | count | % of binding-hours |
|------|---------------|-------|--------------------|
| GTC / interface | contingency = `BASE CASE` | 87 | 15% |
| transmission | line + real contingency | 952 | 84% |
| radial / pocket | rail signature (`n_rail` ≥ 1, `peak_offrail` < 0.25) | 5 | 1% |

Coloring the MST overview by type (hue = type, width/opacity = severity) does make
the GTC interfaces legible as the long spanning corridors between local transmission
clusters. **Parked** in favor of the "core" paradigm (see `0001`), but kept here
because the type field is cheap and may return as a filter/legend facet.

## Color reservation (applies to whatever overview wins)

The diverging **blue↔red** pair is **reserved** for signed SF in the drill-down.
Any categorical encoding in the overview (type, cluster, etc.) must draw from hues
**away from blue and red** — e.g. violet / amber / teal — so the overview's identity
channel never reads as import/export. The earlier blue/orange type palette violated
this (orange sits too close to the reserved red) and is rejected.
