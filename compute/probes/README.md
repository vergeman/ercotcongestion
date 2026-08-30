# probes

Read-only investigative scripts.

```
docker compose run --rm compute python -m compute.probes.<name>
```

---

## `ruc.py` (NP5-753-CD, NP5-754-CD)

**Purpose:** Decide whether the RUC enforced-constraint feed can feed a DAM-close μ
forecast.

**What it does:** Runs five checks:
* discovery (which RUC products exist)
* depth (does the archive reach backtest week 1)
* DAM-close timing (does any run at/before 10:00 CT on D-1 describe delivery day D)
* key-namespace match against NP4-191 (join ≥90% of μ-mass)
* cadence. Every leg can run to completion even after one fails

**Outcome:** No RUC - Dead on timing. The feed only sees delivery day D *after*
DAM close, so joining it would be lookahead — a deep archive can't fix that.

---

## `outage_join.py` (plan/0085, R4 investigation, NP4-191)

**Purpose:** Decide whether transmission-outage records can be joined to the opaque
constraint keys.

**What it does:**
* Leg A checks if the constraint side carries a physical identity
  (`from_station`/`to_station` off NP4-191).
* Leg B checks there's a named outage feed to join *to*.
* Leg C grades the `outage_zonal` fallback existing dataset by name-matching
stations to settlement points. `--check-catalog` re-verifies the "no feed" claim
against the live API plus a control product.

**Outcome:** Dead on the counterparty. Leg A resolves ~97% of μ-mass to stations, but
every public ERCOT outage product is Resource-side — transmission detail sits behind
the MIS Secure Area. `joinable_mass` is zero.

---

## `outage_feed.py` (0089, NP1-346)

**Purpose:** Since **transmission** outages are unreachable, decide whether
NP1-346 (Unplanned **Resource** outages, unit-level) can support a
per-constraint outage covariate instead.

**What it does:**
* 0. discovery
* A. archive depth/density (must reach panel start 2024-12-11)
* B. vintage (readable before close — the report describes D-4, but generation
outages persist, so a stale snapshot still says something about tomorrow)
* C. join (Resource Unit Code → settlement point weighted by outage MW; bar ≥60%
build / 30–60% flagged / <30% dead)
* D. signal (push located MW through the |SF| map to get per-constraint
exposure, then rank-correlate against realized |μ| — a screen a zonal aggregate
scores 0 on by construction).

**Outcome:** Passes the join and vintage gates that killed the RUC feed
investigation, so it is possible to use this dataset. BUT, while the probe was
successful, `with_outage` is set to false in production, as
`plan/0089-generation-outage-arm.md` ablation, (see also
`/compute/experiments/mu/outage_ablation.py`) indicated the outage information,
though existed, didn't improve anything - outcome was negligible.

---

## `outage_crosswalk.py` (NP1-346)

**Purpose:** Confirm NP1-346 crosswalk coverage holds across history before
enabling the feature.
  * "Crosswalk" is to create a lookup table, in this case mapping to a
    Settlement Point (e.g. Resource Unit Code -> Settlement Point.) so we can
    link input data to geographical SP location.

**What it does:** Thin CLI over the *promoted* crosswalk in
`compute.mu_forecast.covariates.outages.crosswalk`. Re-scores (located MW vs
total MW) locatable-outage-MW coverage across N archive snapshots spread over
the backtest (`--snapshots`, default 6) and prints per-snapshot and pooled
coverage against the build/flagged/dead bars.

**Outcome:** The bridge between probe and shipped feature — verifies the join
that `outage_feed.py` measured on one snapshot still holds over time.
