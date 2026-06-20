# 0001 - profile one snapshot

Type: data
Branch: data/0003-bus-zone-remapping
Status: Done

## Goal

* Replace one global load scale factor with per-weather-zone scale factors, so
  ERCOT's between-zone load geography drives the model while TAMU within-zone
  spatial pattern is preserved.

## Context

* `load_row` already arrives with per-zone ERCOT loads (coast, east, far_west,
  north, north_central, south_central, southern, west, total).

* Current code collapses to ERCOT total and discards zonal detail. ~30 lines + a
feasibility fallback; no new data acquisition.

* Move to a finer grain: within-zone distribution stays TAMU's (no bus-level
ERCOT load available), but set between-zone to match ERCOT.

* Why global scaling is wrong: scale = ERCOT_total / TAMU_total (one number)
keeps every zone's share at TAMU's value. If TAMU thinks West is 8% of state
load but ERCOT this hour has West at 3%, global scaling keeps it at 8% — TAMU's
geography, not ERCOT's. That mis-geography partly determines which lines bind.

## Approach and Instructions

Main Task: verify the bus→zone mapping exists and aligns. There are TWO bus→zone
mappings; the distinction is critical:

* `bus_load_zone` → 4 ERCOT load zones (north/houston/south/west) — used for basis.

* `load_weather_zone` → 8 ERCOT weather zones (coast/east/far_west/north/
  north_central/south_central/southern/west) — and load_row is keyed by weather
  zone.

Load disaggregation MUST group by weather zone (load_weather_zone).

* Stay in `/compute` directory when doing analysis and edits.

### Sub tasks:

* String alignment. Confirm normalized load_weather_zone values match
the load_row column keys character-for-character.

If ERCOT data uses "farwest"/"far west" while the CSV produces "far_west",
.map() silently NaNs and everything falls back to global — looks fixed but
isn't.

Write a one-time assertion/printout comparing set(load_weather_zone.unique())
against the set of zone keys in a sample load_row.

* Coverage. Count buses with a non-null weather zone vs non_ercot/
unmapped. Those fall back to global; report the fraction.
