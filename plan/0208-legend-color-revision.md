# 0208 — Legend color revision

Type: fix
Branch: fix/0208-legend-color-revision

## Outcome

Map colors now use fixed continuous dollar scales. LMP is centered at `$25/MWh`; congestion is neutral from `−$10` through `+$10`. Both clamp at `$500`, so one playback frame cannot recolor another.

The 280px single-bar legend is a cropped view of that fixed transform. Its gradient, histogram, and ticks use the same transformed positions as fills, expanding common values and compressing rare tails. Tick selection is collision-aware and includes `$0` when space permits.

Halos identify local extremes, not merely high systemwide prices: a value must be at least `$500` and in the highest 1% of the current frame. Congestion remains positive-only. If any loaded frame qualifies, the legend retains a dimmed local-extreme key through playback; it pulses only when the current frame has a halo.

## Rebased commits

1. `a609bdc fix(map): use fixed dollar color scales` — canonical LMP and congestion transforms, shared by map, forecast/error, and mini-map consumers.
2. `34d0b23 fix(map): crop legends to active price ranges` — transformed cropped legend, aligned histogram, readable ticks, and wider single-bar layout.
3. `b242674 fix(map): reserve halos for local extremes` — shared frame-local halo rule and stable legend key.
4. `6f8f79d docs(plan): mark legend revision complete` — original acceptance update before this summary rewrite.

## Verification

* [x] Quiet congestion remains neutral and colors stay stable through playback.
* [x] LMP, congestion, forecast error, and mini-map consumers share dollar spacing.
* [x] Legend geometry and histogram bins align with map-fill positions.
* [x] Local-extreme halos are positive-only for congestion and do not make a systemwide LMP interval pulse everywhere.
* [x] `npm run lint` and `npm run build` pass in the Compose web service.
