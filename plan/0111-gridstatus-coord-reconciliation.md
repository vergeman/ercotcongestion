# 0111 - gridstatus-coord-reconciliation

Type: fix
Branch: fix/0111-gridstatus-coord-reconciliation

## Goal

* Decode the gridstatus.io node export into an authoritative SPP → lat/lon map.
* Apply it as a corrective override in the geocoding pipeline (fix errors, keep agreements).
* Clean `manual_overrides.csv` so it no longer carries known-wrong coordinates.

## Context

* Coordinate errors originate in our EIA↔ERCOT name matching; `manual_overrides.csv` was the largest error source (77 rows >25 km off).
* `gridstatus-nodes.json` gives a direct SPP→coordinate map for all 1,078 ERCOT nodes — no name matching needed.
* Encoding is base62 microdegrees (not a geohash): `lat = b62(coord[:5])/1e6 − 90`, `lon = b62(coord[5:])/1e6 − 180`; verified ~275 m RMSE vs exact matches.

## Approach

* Work in: `preprocess/geocode_ercot_layer.py`, `shared/settings.py`, `data/raw/ercot_geocode/`.
* Add `ercot_geocode_nodes_json` path in `shared/settings.py`.
* Add `decode_gridstatus_coord`, `load_gridstatus_coords` (gzip-magic aware, ERCOT-only, drop HB_/LZ_/DC_), `_haversine_km`, `apply_gridstatus_corrections`.
* Wire `apply_gridstatus_corrections` into `main()` after `apply_manual_overrides`; add `gridstatus` to the auto-match set in `run_log`.
* Correction rule: node in gridstatus AND (no coord OR ≥1 km off) → replace + retag `match_method=gridstatus`; <1 km rows keep coord and method.
* Gzip `gridstatus-nodes.json` in place (2.54 MB → 850 KB).
* Rewrite `manual_overrides.csv`: replace rows ≥1 km off or `(0,0)` sentinel-and-covered with decoded coords; keep the rest.
* Do NOT touch: `hubs_lz_centroids.csv` (HB/LZ/DC live there), the matching passes themselves.

## Acceptance

* [x] Pipeline runs in `preprocess` container; `>= 80% auto` PASS.
* [x] 100% of decoded ERCOT nodes fall inside the TX bbox; corrected coords all `match_method=gridstatus`.
* [x] `<1 km` nodes retain original coord + method; `manual_overrides.csv` rows all within 1 km of gridstatus (except non-covered).
* [x] `load_gridstatus_coords` reads the gzipped file (gzip-magic detection) and falls back to plain JSON.
