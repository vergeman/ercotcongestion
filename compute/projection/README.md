# Compute projection

Turns the μ forecast into per-settlement-point prices by pushing it through the
SF map: **nodal congestion = −(expected μ · SF)**. This package owns the math
and the on-disk artifact formats only. It writes nothing to the database, the
runners in `compute.jobs` handle persistence.

## Files

| File           | Description                                                                                                                                                                                                                                                                                             | Used by                                                          |
|----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| `propagate.py` | The projection itself. For one window it lines up scored hours, multiplies expected μ by SF, and scores it against realized congestion when requested. | forecast publication and evaluation |
| `codecs.py`    | Read/write formats for projection artifacts, plus small helpers for explaining a node's price. See below.                                                                                                                                                                                               | forecast/backfill jobs, `forecast_store`, the API path           |


## `codecs.py`

"Codec" = coder/decoder: each pair here encodes a model object (a DataFrame or
matrix) into a compact artifact and decodes it back, so the read and write sides
of a format live together and stay in sync.

All the functions / / classes here deal with serializing / de-serializing the
projections. They group into `Nodal` artifacts, and `SfMuArtifact`.

* **`NodalPanel`**: in-memory holder for one window's forecast: hours ×
  settlement points, plus the point estimate.
* **`NodalPanel`**: carries an in-memory forecast into database persistence.
* **`build_sf_mu_artifact` / `save_sf_mu` / `load_sf_mu`**: pack one day's SF
  matrix and expected μ into a single blob (`SfMuArtifact`), which is what the
  API serves a node's forecast from.
* **`node_drivers` / `node_contributions` / `materialize_drivers`**: explain a
  node: which constraints push its price, and by how much (contribution = −SF ·
  μ).
* **`parse_curated_days`**: validate the small, explicit day list for driver
  debug output (not a full-history run).

## Notes

- **No future data in forward mode.** When `daily_forecast` projects a delivery
  day, it passes that day's 24 hours and reads no realized congestion, so no
  score is produced — grading happens later against settled results.
- **Coverage check.** Each scored window reports the share of shadow-price mass
  the SF map actually covers, so a thin or stale map is visible rather than
  silently under-projecting.
