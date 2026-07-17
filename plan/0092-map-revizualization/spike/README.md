# Spike — 0001 map revizualization

Prototype + data probes that settled the design in `../0001-revizualization.md`.
All run against real `map-v1`, window `2025-11-04` (1044 located constraints).

## How to run

Scripts query `implied_shift_factors` / `constraint_geo` and read the geocoded SP
coords, so run them inside the `api` container (has psycopg, the PG env, and
`/data` mounted):

```
docker cp <script>.py api:/tmp/ && docker exec api python /tmp/<script>.py
```

Each dumps a JSON payload to `/tmp/*.json`; the `build_*.py` generators read those
and emit self-contained HTML. Copy the payload back out to run a generator locally.

## Probes (the findings behind the design)

| script | question it answered |
|--------|----------------------|
| `overview_spike.py` | all-constraint dipole/MST spans → median 263 km ⇒ spaghetti; need a severity cut |
| `core_spike.py` | centroid vs `\|SF\|` vs **`\|SF\|²` geo-median** vs peak → `\|SF\|²` de-piles best without collapsing |
| `type_sign_probe.py` | peak-node sign is 58% export (not import); **100% of nodes carry both signs**; type counts |
| `membership_probe.py` | memberships per displayed node: median 1, mean 2.5, p90 5 ⇒ popover is readable |
| `mst_spike.py` / `hybrid_spike.py` | extract top-K node fields + MST edges + type + core for the renders |

## Renders

* `renders/overview-interactive.html` — the final design (`build_hybrid4.py`):
  `|SF|²`-core positioning, GTC metaball region-shadow + skeleton, transmission MST
  corridors, radial points; **hover a settlement point** for its membership popover
  (source/sink tagged), click a row or a core dot to isolate.
* `renders/core-depile.html` — the centroid-pile vs `|SF|²`-core before/after
  (`build_core_html.py`).

The design of record is `../0001-revizualization.md`; the two firm data rules
(no aggregate node sign; reserved blue/red) are in `../design-notes/`.
